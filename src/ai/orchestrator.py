"""AI Orchestration Layer — thin conductor for tool-augmented DM closer.

Flow:
1. Load conversation + state_context + AI settings
2. Language detection + deterministic handlers (greeting, profanity, order precheck)
3. Build system prompt (prompt_builder) + conversation history
4. Multi-round OpenAI tool calling (up to 3 rounds)
5. Post-processing: hallucination guards, photo handling
6. Persist state_context + conversation.state
7. Return final text + images

All heavy logic is delegated to focused modules:
- guards.py         — profanity detection, hallucination checks, language correction
- prompt_builder.py — system prompt construction
- photo_handler.py  — image extraction, variant matching, force-fetch
- tool_executor.py  — tool dispatch + validation
- preprocessor.py   — deterministic order request handling
- state_manager.py  — state determination + context updates + cleanup
- language.py       — language detection + greeting handler
- responses.py      — forced response templates + context summary
- anomaly.py        — post-response anomaly detection
- policies.py       — state transitions, order policies
- prompts.py        — base prompt, state prompts, tool definitions
"""

import copy
import json
import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.ai.guards import contains_profanity, detect_hallucinations, strip_markdown_links
from src.ai.language import _detect_language, _check_greeting
from src.ai.photo_handler import (
    extract_images_from_tool_result,
    pick_variant_photos,
    user_wants_photos,
    force_fetch_photos,
    clean_photo_text,
)
from src.ai.policies import next_state
from src.ai.preprocessor import preprocess_order_request
from src.ai.prompt_builder import build_system_prompt
from src.ai.prompts import TOOL_DEFINITIONS
from src.ai.responses import _build_order_modification_response
from src.ai.state_manager import _determine_state, _update_context_from_tool, cleanup_state_context
from src.ai.tool_executor import execute_tool
from src.ai.tracer import start_trace, finish_trace, AITrace
from src.conversations.models import Conversation, Message
from src.core.config import settings

logger = logging.getLogger(__name__)

# Singleton OpenAI client — reused across all calls
import openai as _openai_mod
_openai_client: _openai_mod.AsyncOpenAI | None = None


def _get_openai_client() -> _openai_mod.AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = _openai_mod.AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


# ── AI Settings in-memory cache (TTL 60s) ────────────────────────────────────
_ai_settings_cache: dict[str, tuple] = {}  # tenant_id_str → (settings_obj, monotonic_ts)
_AI_SETTINGS_TTL = 60


async def _get_ai_settings_cached(tenant_id: UUID, db: AsyncSession):
    """Return AiSettings from cache or DB. Cached for 60s per tenant."""
    from src.ai.models import AiSettings

    key = str(tenant_id)
    cached = _ai_settings_cache.get(key)
    if cached and time.monotonic() - cached[1] < _AI_SETTINGS_TTL:
        return cached[0]

    result = await db.execute(select(AiSettings).where(AiSettings.tenant_id == tenant_id))
    ai_settings = result.scalar_one_or_none()
    if ai_settings:
        # Detach from session so cached object is safe to reuse across sessions
        db.expunge(ai_settings)
    _ai_settings_cache[key] = (ai_settings, time.monotonic())
    return ai_settings


def invalidate_ai_settings_cache(tenant_id) -> None:
    """Call from router when AI settings are updated/reset."""
    _ai_settings_cache.pop(str(tenant_id), None)


def _fix_mixed_script_currency(text: str, detected_lang: str) -> str:
    """Fix mixed-script currency 'со'm' → correct form per language."""
    if "со'm" not in text and "со\u2019m" not in text:
        return text
    mapping = {"ru": "сум", "uz_cyrillic": "сўм", "en": "UZS"}
    replacement = mapping.get(detected_lang, "so'm")
    return text.replace("со'm", replacement).replace("со\u2019m", replacement)


def _fix_russian_words_in_uzbek(text: str, detected_lang: str) -> str:
    """Replace Russian words that slip into Uzbek responses."""
    if detected_lang not in ("uz_latin", "uz_cyrillic"):
        return text
    # Common Russian words that GPT mixes into Uzbek
    replacements = {
        "Poludnya": "Yarim kun",
        "poludnya": "yarim kun",
        "Полудня": "Ярим кун",
        "полудня": "ярим кун",
        "Полдня": "Ярим кун",
        "полдня": "ярим кун",
        "включено": "kiritilgan" if detected_lang == "uz_latin" else "киритилган",
        "Включено": "Kiritilgan" if detected_lang == "uz_latin" else "Киритилган",
        "бесплатно": "bepul" if detected_lang == "uz_latin" else "бепул",
    }
    for ru_word, uz_word in replacements.items():
        if ru_word in text:
            text = text.replace(ru_word, uz_word)
    return text


async def _openai_with_retry(client, **kwargs):
    """Call OpenAI completions.create with retry + circuit breaker.

    Circuit breaker trips after 5 consecutive transient failures and
    rejects calls for 30s, giving OpenAI time to recover.
    """
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    import openai as _oai
    from src.core.circuit_breaker import openai_breaker

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((_oai.APITimeoutError, _oai.APIConnectionError, _oai.RateLimitError, _oai.InternalServerError)),
        before_sleep=lambda rs: logger.warning("OpenAI retry #%d after %s", rs.attempt_number, type(rs.outcome.exception()).__name__),
    )
    async def _call():
        async with openai_breaker:
            return await client.chat.completions.create(**kwargs)

    return await _call()


# ──────────────────────────────────────────────
# Checkout triggers for proactive suggestion
# ──────────────────────────────────────────────
_BOOKING_TRIGGERS = {
    # Uzbek Latin
    "bron", "bron qil", "bron qilish", "buyurtma", "buyurtma ber",
    "joy band qil", "joy band", "rasmiylashtiramiz", "rasmiylashtir",
    "tamom", "bas", "boldi", "bo'ldi", "ha", "hop", "xop", "mayli",
    "shu", "shuni", "kerak", "olaман", "olaman", "boramiz", "boraman",
    # Uzbek Cyrillic
    "брон", "буюртма", "жой банд", "расмийлаштирамиз",
    "тамом", "бас", "бўлди", "ха", "хоп", "хўп", "майли",
    # Russian
    "бронь", "забронировать", "забронируй", "оформить", "оформляем",
    "да", "ок", "окей", "конечно", "ладно", "хорошо", "давай",
    # English
    "book", "booking", "reserve", "yes", "yeah", "sure", "ok", "okay", "done",
}

# Confirm words for booking guard
_CONFIRM_WORDS = {
    "ha", "hop", "xop", "mayli", "kerak", "bron", "olaman", "boraman", "boramiz",
    "да", "ха", "хоп", "хўп", "майли",
    "yes", "yea", "sure", "ok", "okay", "давай", "конечно", "ладно", "хорошо",
}

_PROACTIVE_SUGGESTIONS = {
    "ru": "Кстати, вы ещё интересовались {items} — хотите забронировать? 👍",
    "uz_cyrillic": "Айтганча, сиз {items} ҳам кўрган эдингиз — бронлашни хоҳлайсизми? 👍",
    "uz_latin": "Aytgancha, siz {items} ham ko'rgan edingiz — bronlashni xohlaysizmi? 👍",
    "en": "By the way, you were also looking at {items} — would you like to book? 👍",
}

# Language switch patterns
_LANG_SWITCH = {
    "uz_cyrillic": [
        "узбекча гапир", "узбекча ёз", "ўзбекча гапир", "ўзбекча ёз",
        "на узбекском", "по-узбекски", "по узбекски",
    ],
    "uz_latin": [
        "uzbecha gapir", "o'zbekcha gapir", "ozbekcha yoz",
        "uzbecha yoz", "speak uzbek", "in uzbek",
    ],
    "ru": ["по-русски", "по русски", "на русском", "русча гапир", "ruscha gapir"],
    "en": ["speak english", "in english", "английски"],
}

_PROFANITY_RESPONSES = {
    "ru": "Подключаю оператора, подождите немного \U0001f64f",
    "uz_cyrillic": "Операторни улаяпман, озгина кутинг \U0001f64f",
    "uz_latin": "Operatorni ulayapman, ozgina kuting \U0001f64f",
    "en": "Connecting you with an operator, please wait \U0001f64f",
}


# ──────────────────────────────────────────────
# MAIN ORCHESTRATION
# ──────────────────────────────────────────────


async def process_dm_message(
    tenant_id: UUID,
    conversation_id: UUID,
    user_message: str,
    db: AsyncSession,
    comment_hint: dict | None = None,
    customer_photo_path: str | None = None,
) -> dict | None:
    """Process an incoming DM and generate AI response.

    Returns dict {"text": str, "image_urls": list[str]} or None.
    """
    trace = start_trace(tenant_id, conversation_id, user_message)
    t0 = time.monotonic()

    try:
        client = _get_openai_client()

        # --- Step 1: Load conversation + state ---
        conv_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            logger.error("Conversation %s not found", conversation_id)
            return None

        state_context = copy.deepcopy(conversation.state_context) if conversation.state_context else {}
        trace.state_before = conversation.state or "idle"

        if not user_message or not user_message.strip():
            return None

        # --- Step 2: Load AI settings (cached, TTL 60s) ---
        ai_settings = await _get_ai_settings_cached(tenant_id, db)

        # Kill switch
        if ai_settings and not ai_settings.allow_auto_dm_reply:
            logger.info("DM auto-reply disabled for tenant %s — skipping AI", tenant_id)
            trace.add_step("info", "Kill switch", "allow_auto_dm_reply=False — AI отключён")
            return None

        # --- Step 3: Language detection ---
        default_lang = ai_settings.language if ai_settings else "ru"
        current_lang = state_context.get("language", default_lang)
        # Don't re-detect language for photo placeholders — keep current language
        if "[Клиент отправил фото]" in user_message or (customer_photo_path and len(user_message.strip()) < 5):
            detected_lang = current_lang
        else:
            detected_lang = _detect_language(user_message, current_lang)
            detected_lang = _check_language_switch(user_message, detected_lang)
        # Backward compat: old "uz" value
        if detected_lang == "uz":
            detected_lang = "uz_cyrillic"
        state_context["language"] = detected_lang
        trace.detected_language = detected_lang
        trace.add_step("info", "Language", f"detected={detected_lang}, default={default_lang}")

        # --- Step 4: Deterministic greeting ---
        current_conv_state = conversation.state or "idle"
        greeting_response = _check_greeting(user_message, detected_lang)
        if greeting_response:
            if current_conv_state not in ("idle", "NEW_CHAT"):
                conversation.state = "idle"
            conversation.state_context = state_context
            flag_modified(conversation, "state_context")
            await db.flush()
            trace.add_step("info", "Greeting (deterministic)", greeting_response)
            trace.final_response = greeting_response
            trace.state_after = "idle"
            trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
            await finish_trace(tenant_id, trace, db)
            return {"text": greeting_response, "image_urls": []}

        # --- Step 5: Proactive suggestion at checkout ---
        proactive = _check_proactive_suggestion(user_message, state_context, current_conv_state, detected_lang)
        if proactive:
            conversation.state_context = state_context
            flag_modified(conversation, "state_context")
            await db.flush()
            trace.add_step("info", "Proactive suggestion", proactive)
            trace.final_response = proactive
            trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
            await finish_trace(tenant_id, trace, db)
            return {"text": proactive, "image_urls": []}

        # --- Step 5.5: Customer photo analysis (GPT-4o Vision) ---
        # Trigger on: no-caption photos ("[Клиент отправил фото]") OR any photo with caption during pending_payment
        if customer_photo_path and (
            "[Клиент отправил фото]" in user_message
            or (conversation.state or "") in ("pending_payment", "post_order", "checkout")
        ):
            photo_analysis = await _analyze_customer_photo(
                client, customer_photo_path, conversation, state_context, detected_lang,
                tenant_id, ai_settings, db,
            )
            if photo_analysis:
                conversation.state_context = state_context
                flag_modified(conversation, "state_context")
                await db.flush()
                trace.add_step("photo", "Customer photo → Vision", photo_analysis["text"][:100])
                trace.final_response = photo_analysis["text"]
                trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
                await finish_trace(tenant_id, trace, db)
                return photo_analysis

        # --- Step 6: Order pre-processing ---
        t_pre = time.monotonic()
        order_precheck = await preprocess_order_request(
            tenant_id, conversation, user_message, state_context, db,
            ai_settings=ai_settings, detected_lang=detected_lang,
        )
        pre_ms = int((time.monotonic() - t_pre) * 1000)
        if order_precheck.get("forced_response"):
            conversation.state_context = state_context
            flag_modified(conversation, "state_context")
            await db.flush()
            trace.add_step("guard", "Order pre-processor (forced)", order_precheck["forced_response"][:200], pre_ms)
            trace.final_response = order_precheck["forced_response"]
            trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
            await finish_trace(tenant_id, trace, db)
            return {"text": order_precheck["forced_response"], "image_urls": []}
        if order_precheck.get("order_context_injection"):
            state_context["_current_order_info"] = order_precheck["order_context_injection"]
            trace.add_step("guard", "Order pre-processor (inject)", str(order_precheck["order_context_injection"])[:200], pre_ms)
        else:
            trace.add_step("guard", "Order pre-processor", "no match", pre_ms)

        # --- Step 7: Profanity detection ---
        profanity_enabled = bool(ai_settings and ai_settings.auto_handoff_on_profanity)
        has_profanity = contains_profanity(user_message) if profanity_enabled else False
        if profanity_enabled and has_profanity:
            trace.add_step("guard", "Profanity detected", f"instant handoff — msg: {user_message[:80]}")
            result = await _handle_profanity(
                tenant_id, conversation_id, conversation, state_context, detected_lang, ai_settings, db,
            )
            trace.final_response = result["text"] if result else ""
            trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
            await finish_trace(tenant_id, trace, db)
            return result
        else:
            trace.add_step("info", "Profanity check",
                           f"enabled={profanity_enabled}, detected={has_profanity}")

        # --- Step 8: Build system prompt ---
        current_state = _determine_state(conversation, state_context)
        system_content = build_system_prompt(conversation, state_context, detected_lang, ai_settings, current_state)
        trace.model = settings.openai_model_main
        trace.add_step("info", "State & prompt", f"state={current_state}, prompt_len={len(system_content)}")

        # --- Step 9: Build messages with history (last 20) ---
        messages = await _build_messages(conversation_id, system_content, user_message, comment_hint, db)
        trace.add_step("info", "History", f"{len(messages) - 2} messages loaded")

        # --- Step 10: Multi-round tool calling ---
        booking_before_ai = state_context.get("booking", {}).copy()
        final_text, collected_image_urls, tools_called, current_state, variant_images_map = await _run_tool_loop(
            client, messages, tenant_id, conversation, state_context,
            current_state, detected_lang, ai_settings, db, trace,
        )
        trace.tools_called = list(tools_called)

        # --- Step 11: Post-processing ---
        if final_text:
            final_text = strip_markdown_links(final_text)
            final_text = _fix_mixed_script_currency(final_text, detected_lang)
            final_text = _fix_russian_words_in_uzbek(final_text, detected_lang)
            correction = detect_hallucinations(
                final_text, tools_called, state_context,
                booking_before_ai, detected_lang,
            )
            if correction:
                trace.add_step("guard", "Hallucination correction", f"original truncated: {final_text[:100]}...")
                final_text = correction

        # --- Step 12: Photo handling ---
        photos_before = len(collected_image_urls)
        final_text, collected_image_urls = await _finalize_photos(
            final_text, collected_image_urls, user_message,
            variant_images_map, tenant_id, state_context, db,
        )
        photos_after = len(collected_image_urls)
        if photos_before or photos_after:
            trace.add_step("photo", "Photo finalize", f"before={photos_before} → after={photos_after}, urls={collected_image_urls[:3]}")

        # --- Step 13: Persist state + anomaly detection ---
        cleanup_state_context(state_context)

        booking_save = state_context.get("booking", {})
        if booking_save:
            logger.info("Saving state_context: booking=%s, state=%s", booking_save, current_state)

        try:
            from src.ai.anomaly import _detect_anomalies
            anomalies = _detect_anomalies(
                user_message, final_text, detected_lang, tools_called,
                state_context, conversation_id, tenant_id,
            )
            if anomalies:
                existing = state_context.get("_anomalies", [])
                existing.extend(anomalies)
                state_context["_anomalies"] = existing[-20:]
                conversation.is_training_candidate = True
                trace.add_step("guard", "Anomaly detected", str(anomalies)[:200])
        except Exception:
            logger.debug("Anomaly detection failed (non-fatal)", exc_info=True)

        conversation.state_context = state_context
        conversation.state = current_state
        flag_modified(conversation, "state_context")
        await db.flush()

        trace.final_response = final_text or ""
        trace.image_urls = collected_image_urls
        trace.state_after = current_state
        trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
        await finish_trace(tenant_id, trace, db)

        return {"text": final_text, "image_urls": collected_image_urls}

    except Exception as exc:
        from src.core.circuit_breaker import CircuitBreakerOpen
        if isinstance(exc, CircuitBreakerOpen):
            logger.warning("OpenAI circuit breaker OPEN for tenant %s — skipping AI", tenant_id)
            trace.add_step("guard", "Circuit Breaker", f"OPEN — retry after {exc.retry_after:.0f}s")
        else:
            logger.exception("AI processing error for tenant %s, conversation %s", tenant_id, conversation_id)
        trace.add_step("info", "ERROR", f"{type(exc).__name__}: {exc}")
        trace.total_duration_ms = int((time.monotonic() - t0) * 1000)
        await finish_trace(tenant_id, trace, db)
        return await _handle_fallback(tenant_id, conversation_id, user_message, exc, db)


# ──────────────────────────────────────────────
# Helper functions (private, thin wrappers)
# ──────────────────────────────────────────────


def _check_language_switch(user_message: str, detected_lang: str) -> str:
    """Check for explicit language-switch requests."""
    msg_lower = user_message.lower().strip()
    for lang, patterns in _LANG_SWITCH.items():
        if any(p in msg_lower for p in patterns):
            return lang
    return detected_lang


def _check_proactive_suggestion(
    user_message: str, state_context: dict, current_state: str, detected_lang: str,
) -> str | None:
    """Check if we should suggest other tours the user looked at."""
    # For tours: no cart. Only suggest if user browsed multiple tours
    # and is now in selection state with a booking trigger
    products = state_context.get("products", {})
    msg_stripped = user_message.strip().lower().rstrip("!?.,")

    # NEVER trigger on confirmations — they're answering a question, not browsing
    msg_words = set(msg_stripped.replace(",", " ").replace(".", " ").split())
    if msg_words & _CONFIRM_WORDS:
        return None

    # NEVER trigger if booking context exists (user is mid-booking)
    if state_context.get("booking"):
        return None

    # NEVER trigger if user message contains booking details (name, phone, participant count)
    # This means user is trying to BOOK, not browsing
    import re as _re
    has_phone = bool(_re.search(r'\d{7,}', msg_stripped))
    has_kishi = bool(_re.search(r'\d+\s*(?:kishi|kishilik|нафар|человек|чел)', msg_stripped))
    has_name_and_book = any(w in msg_stripped for w in ("bron qil", "бронируй", "забронируй", "book")) and len(msg_stripped) > 20
    if has_phone or has_kishi or has_name_and_book:
        return None

    is_trigger = current_state == "selection" and any(t in msg_stripped for t in _BOOKING_TRIGGERS)
    if not (is_trigger and len(products) > 1):
        return None

    if state_context.get("_proactive_suggested", False):
        return None

    # Show other tours they browsed but haven't selected
    booking = state_context.get("booking", {})
    selected_pid = booking.get("product_id")
    other_tours = [
        name for name, info in products.items()
        if info.get("product_id") != selected_pid and info.get("in_stock", True)
    ]

    if other_tours:
        state_context["_proactive_suggested"] = True
        items_text = ", ".join(other_tours[:2])
        template = _PROACTIVE_SUGGESTIONS.get(detected_lang, _PROACTIVE_SUGGESTIONS["uz_latin"])
        return template.format(items=items_text)

    return None


async def _handle_profanity(tenant_id, conversation_id, conversation, state_context, detected_lang, ai_settings, db):
    """Handle profanity detection — create handoff and return response."""
    logger.info("PROFANITY DETECTED (instant handoff enabled)")
    from src.handoffs.models import Handoff

    handoff = Handoff(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason="profanity",
        priority="urgent",
        summary="Автоматический handoff: обнаружена нецензурная лексика (instant mode)",
    )
    db.add(handoff)
    conversation.state = "handoff"
    conversation.ai_enabled = False
    conversation.state_context = state_context
    flag_modified(conversation, "state_context")
    await db.flush()

    # SSE notification
    try:
        from src.sse.event_bus import publish_event
        await publish_event(f"sse:{tenant_id}:tenant", {
            "event": "conversation_updated",
            "conversation_id": str(conversation_id),
            "state": "handoff",
            "reason": "profanity",
        })
    except Exception:
        pass

    # Notify operator
    await _notify_operator_handoff(
        tenant_id, conversation_id,
        "⚠️ Обнаружена нецензурная лексика\n\nДиалог передан оператору.",
        ai_settings,
    )

    return {"text": _PROFANITY_RESPONSES.get(detected_lang, _PROFANITY_RESPONSES["ru"]), "image_urls": []}


async def _analyze_customer_photo(client, photo_path, conversation, state_context, detected_lang, tenant_id, ai_settings, db):
    """Analyze a customer-sent photo using GPT-4o Vision.

    If payment receipt detected during pending_payment:
    1. Extract amount from receipt via Vision
    2. Compare with order total
    3. If matches → auto-confirm order + create/find tour group + invite customer
    4. If doesn't match → tell customer the amount is wrong
    """
    import base64
    import os

    try:
        with open(photo_path, "rb") as f:
            photo_b64 = base64.b64encode(f.read()).decode()
    except Exception:
        logger.debug("Could not read customer photo: %s", photo_path, exc_info=True)
        return None
    finally:
        try:
            os.unlink(photo_path)
        except Exception:
            pass

    conv_state = conversation.state or "idle"
    has_pending_order = conv_state in ("pending_payment", "post_order", "checkout")

    # Ask Vision to classify the photo AND extract amount
    vision_prompt = (
        "Analyze this image. Is it a payment receipt/check (to'lov cheki, квитанция, скриншот оплаты, bank transfer)? "
        "If yes, extract the payment amount (number only, no currency). "
        "Reply ONLY with JSON: {\"is_receipt\": true/false, \"amount\": 0, \"description_uz\": \"...\", \"description_ru\": \"...\"}"
    )

    try:
        vision_response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": vision_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}", "detail": "low"}},
                ],
            }],
            max_tokens=200,
            temperature=0.1,
        )
        vision_text = vision_response.choices[0].message.content or ""
        logger.info("Vision analysis: %s", vision_text[:200])
    except Exception:
        logger.warning("Vision API failed for customer photo", exc_info=True)
        return None

    # Parse response
    import re
    is_receipt = False
    receipt_amount = 0
    try:
        json_match = re.search(r'\{[^}]+\}', vision_text)
        if json_match:
            parsed = json.loads(json_match.group())
            is_receipt = parsed.get("is_receipt", False)
            receipt_amount = int(float(parsed.get("amount", 0)))
    except Exception:
        is_receipt = "true" in vision_text.lower() and "is_receipt" in vision_text.lower()

    if is_receipt and has_pending_order:
        return await _handle_payment_receipt(
            tenant_id, conversation, state_context, detected_lang,
            receipt_amount, ai_settings, db,
        )

    # Not a receipt or not in payment state — let normal AI flow continue
    if not is_receipt:
        desc = ""
        try:
            parsed = json.loads(re.search(r'\{[^}]+\}', vision_text).group())
            desc = parsed.get(f"description_{'ru' if detected_lang == 'ru' else 'uz'}", "")
        except Exception:
            pass
        if desc:
            state_context["_customer_photo_description"] = desc
    return None


async def _handle_payment_receipt(tenant_id, conversation, state_context, detected_lang, receipt_amount, ai_settings, db):
    """Handle payment receipt: verify amount, confirm order, create group, invite customer."""
    from src.orders.models import Order
    from sqlalchemy.orm import selectinload

    # Find the pending order for this conversation (newest first)
    orders_in_ctx = state_context.get("orders", [])
    order = None
    for o_ctx in reversed(orders_in_ctx):
        oid = o_ctx.get("order_id")
        if oid:
            order = await db.get(Order, UUID(oid), options=[selectinload(Order.items)])
            if order and order.status == "pending_payment":
                break
            order = None

    # Fallback: find any pending_payment order for this tenant+conversation
    if not order:
        from src.leads.models import Lead
        result = await db.execute(
            select(Order)
            .join(Lead, Lead.id == Order.lead_id, isouter=True)
            .where(
                Order.tenant_id == tenant_id,
                Order.status == "pending_payment",
                Lead.telegram_user_id == conversation.telegram_user_id,
            )
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        order = result.scalar_one_or_none()

    if not order:
        msgs = {
            "uz_latin": "Chekingiz qabul qilindi, lekin to'lov kutayotgan buyurtma topilmadi. Avval tur bron qiling!",
            "uz_cyrillic": "Чекингиз қабул қилинди, лекин тўлов кутаётган буюртма топилмади. Аввал тур брон қилинг!",
            "ru": "Чек получен, но заказ на оплату не найден. Сначала забронируйте тур!",
            "en": "Receipt received, but no pending order found. Please book a tour first!",
        }
        return {"text": msgs.get(detected_lang, msgs["uz_latin"]), "image_urls": []}

    # Compare receipt amount with order total
    order_total = int(order.total_amount)
    total_fmt = f"{order_total:,}".replace(",", " ")
    receipt_fmt = f"{receipt_amount:,}".replace(",", " ") if receipt_amount > 0 else "?"

    if receipt_amount > 0:
        logger.info("Receipt amount: %d, Order total: %d", receipt_amount, order_total)

    # --- ALL receipts go to operator for verification (no auto-confirm) ---
    from src.handoffs.models import Handoff

    if receipt_amount > 0 and receipt_amount < order_total * 0.90:
        # Clearly too little — tell customer, but still notify operator
        reason = "receipt_amount_low"
        summary = (f"Chek summasi kam: {receipt_fmt} so'm (buyurtma: {total_fmt} so'm). "
                   f"Mijozga to'g'ri summa yuborishni ayting.")
        operator_msg = (
            f"⚠️ Chek summasi kam\n\nBuyurtma: {order.order_number}\n"
            f"Buyurtma summasi: {total_fmt} so'm\nChek summasi: {receipt_fmt} so'm\n"
            f"Mijoz: {conversation.telegram_first_name}"
        )
        customer_msgs = {
            "uz_latin": f"Chekdagi summa ({receipt_fmt} so'm) buyurtma summasi ({total_fmt} so'm) dan kam. To'g'ri summadagi chekni yuboring!",
            "uz_cyrillic": f"Чекдаги сумма ({receipt_fmt} сўм) буюртма суммаси ({total_fmt} сўм) дан кам. Тўғри суммадаги чекни юборинг!",
            "ru": f"Сумма в чеке ({receipt_fmt} сум) меньше суммы заказа ({total_fmt} сум). Отправьте чек с правильной суммой!",
            "en": f"Receipt amount ({receipt_fmt} UZS) is less than order total ({total_fmt} UZS). Please send the correct receipt!",
        }
    elif receipt_amount > 0 and receipt_amount > order_total * 1.10:
        # Much more than order — possible bank commission or wrong transfer
        diff_fmt = f"{receipt_amount - order_total:,}".replace(",", " ")
        reason = "receipt_amount_over"
        summary = (f"Chek summasi ko'p: {receipt_fmt} so'm (buyurtma: {total_fmt} so'm, farq: +{diff_fmt}). "
                   f"Bank komissiyasi bo'lishi mumkin. Tekshiring.")
        operator_msg = (
            f"⚠️ Chek summasi farqi\n\nBuyurtma: {order.order_number}\n"
            f"Buyurtma summasi: {total_fmt} so'm\nChek summasi: {receipt_fmt} so'm\n"
            f"Farq: +{diff_fmt} so'm\nMijoz: {conversation.telegram_first_name}\n\n"
            f"Bank komissiyasi bo'lishi mumkin. Tekshiring!"
        )
        customer_msgs = {
            "uz_latin": f"Chekingiz qabul qilindi! Operator tekshirib, tez orada tasdiqlaydi. Buyurtma: {order.order_number}",
            "uz_cyrillic": f"Чекингиз қабул қилинди! Оператор текшириб, тез орада тасдиқлайди. Буюртма: {order.order_number}",
            "ru": f"Чек получен! Оператор проверит и подтвердит. Заказ: {order.order_number}",
            "en": f"Receipt received! Operator will verify and confirm. Order: {order.order_number}",
        }
    else:
        # Amount matches (or couldn't extract) — still goes to operator
        reason = "receipt_verification"
        summary = (f"Chek qabul qilindi. Buyurtma: {order.order_number}, "
                   f"summa: {total_fmt} so'm, chek: {receipt_fmt} so'm. Tasdiqlang.")
        operator_msg = (
            f"📸 Chek keldi — tasdiqlash kerak!\n\nBuyurtma: {order.order_number}\n"
            f"Buyurtma summasi: {total_fmt} so'm\nChek summasi: {receipt_fmt} so'm\n"
            f"Mijoz: {conversation.telegram_first_name}\n\n"
            f"Tekshirib, buyurtmani tasdiqlang!"
        )
        customer_msgs = {
            "uz_latin": f"Chekingiz qabul qilindi! Operator tekshirib, tez orada tasdiqlaydi. Buyurtma: {order.order_number}",
            "uz_cyrillic": f"Чекингиз қабул қилинди! Оператор текшириб, тез орада тасдиқлайди. Буюртма: {order.order_number}",
            "ru": f"Чек получен! Оператор проверит и подтвердит. Заказ: {order.order_number}",
            "en": f"Receipt received! Operator will verify and confirm. Order: {order.order_number}",
        }

    # Create handoff for operator
    handoff = Handoff(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        reason=reason,
        summary=summary,
    )
    db.add(handoff)
    await db.flush()
    logger.info("Receipt handoff created for order %s (reason=%s)", order.order_number, reason)

    # Notify operator via Telegram
    await _notify_operator_handoff(tenant_id, conversation.id, operator_msg, ai_settings)

    return {"text": customer_msgs.get(detected_lang, customer_msgs["uz_latin"]), "image_urls": []}


async def _find_or_create_tour_group(tenant_id, conversation, tour_name, tour_date, detected_lang) -> str | None:
    """Find existing or create new Telegram group for this tour+date, invite customer.

    Group name format: "Easy Tour | {tour_name} | {tour_date}"
    """
    try:
        from src.telegram.service import telegram_manager
        tg_client = telegram_manager.get_client(tenant_id)
        if not tg_client:
            logger.warning("No Telegram client for group operations")
            return None

        chat_id = conversation.telegram_chat_id
        if not chat_id:
            return None

        group_title = f"Easy Tour | {tour_name}"
        if tour_date:
            group_title += f" | {tour_date}"

        # --- Search for existing group with this name ---
        from telethon.tl.functions.messages import GetDialogsRequest
        from telethon.tl.types import InputPeerEmpty

        existing_group = None
        invite_link = None

        try:
            dialogs = await tg_client.get_dialogs(limit=100)
            for d in dialogs:
                if d.is_group and d.title == group_title:
                    existing_group = d.entity
                    logger.info("Found existing tour group: %s (id=%s)", group_title, d.id)
                    break
        except Exception:
            logger.warning("Could not search dialogs for group", exc_info=True)

        # --- Create group if not found ---
        if not existing_group:
            try:
                from telethon.tl.functions.messages import CreateChatRequest
                # Create with just ourselves first
                result = await tg_client(CreateChatRequest(
                    users=["me"],
                    title=group_title,
                ))
                # Get the created chat from result
                chats = getattr(result, 'chats', []) or []
                if chats:
                    existing_group = chats[0]
                    logger.info("Created new tour group: %s (id=%s)", group_title, existing_group.id)
            except Exception:
                logger.warning("Could not create tour group", exc_info=True)
                return None

        if not existing_group:
            return None

        # --- Get invite link ---
        try:
            from telethon.tl.functions.messages import ExportChatInviteRequest
            invite_result = await tg_client(ExportChatInviteRequest(peer=existing_group))
            invite_link = invite_result.link
        except Exception:
            logger.warning("Could not get invite link", exc_info=True)

        # --- Try to add customer to group ---
        added = False
        try:
            user_entity = await tg_client.get_input_entity(int(chat_id))
            from telethon.tl.functions.messages import AddChatUserRequest
            from telethon.tl.functions.channels import InviteToChannelRequest

            # Try channel-style first (supergroup), fallback to chat-style
            try:
                await tg_client(InviteToChannelRequest(
                    channel=existing_group,
                    users=[user_entity],
                ))
                added = True
            except Exception:
                try:
                    group_id = existing_group.id if hasattr(existing_group, 'id') else existing_group
                    await tg_client(AddChatUserRequest(
                        chat_id=group_id,
                        user_id=user_entity,
                        fwd_limit=0,
                    ))
                    added = True
                except Exception as e:
                    logger.warning("Could not add user to group: %s", e)
        except Exception:
            logger.warning("Could not resolve user entity for group invite", exc_info=True)

        # --- Build response ---
        return _group_link_message(invite_link or "", group_title, detected_lang, added=added)

    except Exception:
        logger.warning("Tour group operations failed (non-fatal)", exc_info=True)
        return None


async def _notify_operator_handoff(tenant_id, conversation_id, message_text, ai_settings):
    """Send Telegram notification to operator about a handoff."""
    if not (ai_settings and ai_settings.operator_telegram_username):
        return
    try:
        from src.telegram.service import telegram_manager
        tg_client = telegram_manager.get_client(tenant_id)
        if tg_client:
            frontend_url = "http://127.0.0.1:3001"
            notify_text = (
                f"{message_text}\n\n"
                f"Диалог передан оператору.\n"
                f"👉 {frontend_url}/conversations/{conversation_id}"
            )
            try:
                entity = await tg_client.get_input_entity(ai_settings.operator_telegram_username)
            except ValueError:
                entity = await tg_client.get_input_entity(ai_settings.operator_telegram_username)
            await tg_client.send_message(entity, notify_text)
            logger.info("Operator notified about handoff: %s", ai_settings.operator_telegram_username)
    except Exception:
        logger.warning("Failed to notify operator about handoff (non-fatal)", exc_info=True)


def _group_link_message(link: str, group_name: str, lang: str, added: bool) -> str:
    """Build localized message about group invite."""
    if added:
        msgs = {
            "uz_latin": f"Sizni \"{group_name}\" guruhiga qo'shdik!\nGuruh havolasi: {link}",
            "uz_cyrillic": f"Сизни \"{group_name}\" гуруҳига қўшдик!\nГуруҳ ҳаволаси: {link}",
            "ru": f"Мы добавили вас в группу \"{group_name}\"!\nСсылка на группу: {link}",
            "en": f"You've been added to \"{group_name}\" group!\nGroup link: {link}",
        }
    else:
        msgs = {
            "uz_latin": f"Iltimos, \"{group_name}\" guruhiga qo'shiling — barcha muhim ma'lumotlar shu yerda!\n{link}",
            "uz_cyrillic": f"Илтимос, \"{group_name}\" гуруҳига қўшилинг — барча муҳим маълумотлар шу ерда!\n{link}",
            "ru": f"Пожалуйста, присоединитесь к группе \"{group_name}\" — вся важная информация там!\n{link}",
            "en": f"Please join \"{group_name}\" group — all important info is there!\n{link}",
        }
    return msgs.get(lang, msgs["uz_latin"])


async def _build_messages(conversation_id, system_content, user_message, comment_hint, db):
    """Build OpenAI messages array from system prompt + conversation history."""
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history_messages = list(reversed(history_result.scalars().all()))

    messages = [{"role": "system", "content": system_content}]
    for msg in history_messages:
        if msg.direction == "inbound":
            messages.append({"role": "user", "content": msg.raw_text or ""})
        elif msg.direction == "outbound" and msg.ai_generated:
            messages.append({"role": "assistant", "content": msg.raw_text or ""})

    if comment_hint:
        hint_text = (
            f"[KONTEKST: Bu mijoz kanalda {comment_hint.get('product_name', 'tur')} haqida so'ragan. "
        )
        if comment_hint.get("variants_summary"):
            hint_text += f"Mavjud variantlar: {comment_hint['variants_summary']}. "
        hint_text += "Mijoz kanaldan keldi — shu tur bilan yordam ber. Agar mijoz shu tur haqida so'rasa, sanalar va narxlarni tools orqali ko'rsat.]"
        messages.append({"role": "system", "content": hint_text})

    messages.append({"role": "user", "content": user_message})
    return messages


async def _run_tool_loop(
    client, messages, tenant_id, conversation, state_context,
    current_state, detected_lang, ai_settings, db,
    trace: AITrace | None = None,
):
    """Execute multi-round tool calling loop (up to 3 rounds).

    Returns (final_text, collected_image_urls, tools_called, current_state, variant_images_map).
    """
    final_text = None
    collected_image_urls: list[str] = []
    variant_images_map: dict = {}
    tools_called: set[str] = set()

    for round_num in range(3):
        t_llm = time.monotonic()
        response = await _openai_with_retry(
            client,
            model=settings.openai_model_main,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            max_tokens=500,
            temperature=0.3,
        )
        llm_ms = int((time.monotonic() - t_llm) * 1000)
        assistant_msg = response.choices[0].message
        if trace and response.usage:
            trace.prompt_tokens += response.usage.prompt_tokens or 0
            trace.completion_tokens += response.usage.completion_tokens or 0

        if not assistant_msg.tool_calls:
            final_text = assistant_msg.content
            if trace:
                trace.add_step("llm_call", f"Round {round_num + 1} → text response", (final_text or "")[:200], llm_ms)
            break

        if trace:
            tool_names = [tc.function.name for tc in assistant_msg.tool_calls]
            trace.add_step("llm_call", f"Round {round_num + 1} → {len(tool_names)} tool(s)", ", ".join(tool_names), llm_ms)

        messages.append(assistant_msg.model_dump())
        forced_response = None
        round_tool_names = {tc.function.name for tc in assistant_msg.tool_calls}

        for tool_call in assistant_msg.tool_calls:
            tools_called.add(tool_call.function.name)
            tool_args = json.loads(tool_call.function.arguments)

            # Guard: block create_order_draft in same round as get_variant_candidates
            # (must show dates to customer first before booking)
            if tool_call.function.name == "create_order_draft" and "get_variant_candidates" in round_tool_names:
                msg_lower = (messages[-1].get("content") or "").lower().strip() if messages else ""
                is_short_confirm = len(msg_lower.split()) <= 5 and any(w in msg_lower.split() for w in _CONFIRM_WORDS)
                if not is_short_confirm:
                    logger.warning("BLOCKED create_order_draft in same round as get_variant_candidates")
                    result = {"error": "Avval sanalarni mijozga ko'rsat va tanlovini kut. Avtomatik buyurtma yaratish mumkin emas."}
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result, ensure_ascii=False)})
                    if trace:
                        trace.add_step("guard", f"BLOCKED {tool_call.function.name}", "blocked in same round as get_variant_candidates")
                    continue

            t_tool = time.monotonic()
            result = await execute_tool(
                tool_call.function.name, tool_args,
                tenant_id=tenant_id, conversation=conversation,
                state_context=state_context, db=db, ai_settings=ai_settings,
            )
            tool_ms = int((time.monotonic() - t_tool) * 1000)

            # Trace: tool call + result
            if trace:
                args_str = json.dumps(tool_args, ensure_ascii=False, default=str)
                trace.add_step("tool_call", tool_call.function.name, f"args: {args_str}", 0)
                result_str = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, dict) else str(result)
                trace.add_step("tool_result", f"← {tool_call.function.name}", result_str[:500], tool_ms)

            # Extract images from tool results
            if isinstance(result, dict):
                imgs_before = len(collected_image_urls)
                collected_image_urls = extract_images_from_tool_result(
                    tool_call.function.name, result, variant_images_map, collected_image_urls,
                )
                imgs_after = len(collected_image_urls)
                if trace and imgs_after != imgs_before:
                    trace.add_step("photo", f"Photos from {tool_call.function.name}", f"{imgs_before} → {imgs_after} urls")

            # Update state_context
            if isinstance(result, dict):
                state_context = _update_context_from_tool(state_context, tool_call.function.name, tool_args, result)

            # Update conversation state
            new_state = next_state(current_state, tool_call.function.name)
            if new_state != current_state:
                if trace:
                    trace.add_step("state", "State transition", f"{current_state} → {new_state}")
                current_state = new_state
                conversation.state = new_state

            # Build forced response for order modification tools
            if isinstance(result, dict) and result.get("success"):
                forced_response = _build_order_modification_response(
                    tool_call.function.name, result, detected_lang,
                    tone=ai_settings.tone if ai_settings else "friendly_sales",
                )

            # Transliterate tool results to Cyrillic when user writes in Cyrillic
            tool_result_for_llm = result
            if detected_lang == "uz_cyrillic" and isinstance(result, dict):
                from src.ai.truth_tools import transliterate_tool_result
                tool_result_for_llm = transliterate_tool_result(result, "cyrillic")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result_for_llm, ensure_ascii=False, default=str),
            })

        if forced_response:
            final_text = forced_response
            if trace:
                trace.add_step("info", "Forced response", final_text[:200])
            break
    else:
        # Max rounds reached
        t_llm = time.monotonic()
        response = await _openai_with_retry(
            client,
            model=settings.openai_model_main,
            messages=messages,
            max_tokens=500,
            temperature=0.3,
        )
        llm_ms = int((time.monotonic() - t_llm) * 1000)
        final_text = response.choices[0].message.content
        if trace and response.usage:
            trace.prompt_tokens += response.usage.prompt_tokens or 0
            trace.completion_tokens += response.usage.completion_tokens or 0
        if trace:
            trace.add_step("llm_call", "Max rounds → final text", (final_text or "")[:200], llm_ms)

    return final_text, collected_image_urls, tools_called, current_state, variant_images_map


async def _finalize_photos(final_text, collected_image_urls, user_message, variant_images_map, tenant_id, state_context, db):
    """Pick variant photos, handle force-fetch, clean text."""
    # Pick correct variant photos based on AI response
    matched = pick_variant_photos(variant_images_map, final_text, user_message)
    if matched:
        collected_image_urls = matched

    # Only send photos when user explicitly asks
    wants = user_wants_photos(user_message)
    if not wants:
        if collected_image_urls:
            logger.info("PHOTO: clearing %d photos — user didn't ask to see", len(collected_image_urls))
        collected_image_urls = []

    # Force-fetch photos if user asked but none collected
    if wants and not collected_image_urls:
        collected_image_urls = await force_fetch_photos(tenant_id, user_message, state_context, db)

    # Clean AI text — always strip fake photo promises, deep clean when photos present
    final_text = clean_photo_text(final_text, bool(collected_image_urls))

    return final_text, collected_image_urls


async def _handle_fallback(tenant_id, conversation_id, user_message, exc, db):
    """Handle AI processing failure — fallback model or handoff."""
    try:
        from src.ai.models import AiSettings as _AiS
        fb_result = await db.execute(select(_AiS).where(_AiS.tenant_id == tenant_id))
        fb_settings = fb_result.scalar_one_or_none()
        fb_mode = fb_settings.fallback_mode if fb_settings else "handoff"

        if fb_mode == "fallback_model":
            fb_client = _get_openai_client()
            conv_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
            conv = conv_result.scalar_one_or_none()
            if conv and user_message:
                logger.info("Fallback: trying %s for tenant %s", settings.openai_model_fallback, tenant_id)
                fb_response = await fb_client.chat.completions.create(
                    model=settings.openai_model_fallback,
                    messages=[
                        {"role": "system", "content": "Sen Easy Tour yordamchisisan. Asosiy tizim vaqtincha ishlamayapti. Qisqacha javob ber va keyinroq yozishni taklif qil."},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=300,
                    temperature=0.5,
                )
                fb_text = fb_response.choices[0].message.content
                if fb_text:
                    return {"text": fb_text, "image_urls": []}

        # Default fallback: create handoff
        from src.handoffs.models import Handoff
        conv_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = conv_result.scalar_one_or_none()
        if conv:
            handoff = Handoff(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                reason="ai_error",
                priority="high",
                summary=f"AI ошибка: {type(exc).__name__}. Сообщение клиента: {(user_message or '')[:100]}",
            )
            db.add(handoff)
            await db.flush()
            return {"text": "Operatorni chaqiraman, biroz kuting \U0001f64f", "image_urls": []}

    except Exception:
        logger.exception("Fallback handler also failed for tenant %s", tenant_id)

    return None
