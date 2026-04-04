"""Post-response anomaly detection for AI orchestrator.

Detects known AI failure patterns after each response, including
language mismatches, missed discount handling, and forbidden phrases.
"""

import re as _re_anomaly
import logging
from datetime import datetime as _dt
from uuid import UUID


logger = logging.getLogger(__name__)

_DISCOUNT_PATTERNS_RU = [
    r"\bскинуть\b", r"\bскиньте\b", r"\bскидк[уиуе]\b", r"\bскидку\b",
    r"\bпонизить\b", r"\bснизить\b", r"\bсбросьте\b", r"\bподешевле\b",
    r"\bторгов[аеую]\b", r"\bторговаться\b",
]
_DISCOUNT_PATTERNS_UZ = [
    r"\bnarx\b.*\btushir", r"\btushirib\b", r"\bnarchini\b",
    r"\bnarchini\s+arzon", r"\bnarxini\s+kamayt",
]
_STORE_CONDITIONS_PATTERNS = [
    r"\bусловия\b", r"\bусловие\b", r"\bправила\b", r"\bполитика\b",
    r"\bкак\s+работаете\b", r"\bкак\s+заказать\b",
    r"\bshart\b", r"\bshartlar\b", r"\bnizom\b",
]


def _detect_anomalies(
    user_message: str,
    ai_response: str,
    detected_lang: str,
    tools_called: set,
    state_context: dict,
    conversation_id: UUID,
    tenant_id: UUID,
) -> list[dict]:
    """Detect known AI failure patterns after each response.

    Returns list of anomaly dicts. Each anomaly is logged + stored in state_context.
    Anomaly types:
      - lang_wrong_unit: "дона" used in Russian response
      - lang_mismatch: AI responded in wrong language
      - discount_missed: user asked for discount, AI didn't say "фиксированные"
      - conditions_mishandled: user asked about store conditions, AI showed catalog
      - forbidden_phrase: AI said it can only respond in one language
      - repeated_question: user repeated same question (AI failed to answer)
    """
    anomalies = []
    msg_lower = user_message.lower().strip()
    resp_lower = ai_response.lower() if ai_response else ""

    def _add(atype: str, severity: str, detail: str):
        a = {
            "type": atype,
            "severity": severity,
            "detail": detail,
            "turn": user_message[:60],
            "ts": _dt.utcnow().strftime("%H:%M:%S"),
        }
        anomalies.append(a)
        logger.warning(
            "AI_ANOMALY tenant=%s conv=%s type=%s severity=%s detail=%s turn=%r",
            str(tenant_id)[:8], str(conversation_id)[:8],
            atype, severity, detail, user_message[:60],
        )

    # 1. "дона" in Russian context
    if detected_lang == "ru" and "дона" in resp_lower:
        _add("lang_wrong_unit", "medium",
             "AI used 'дона' (Uzbek unit) in Russian response — should use 'шт'")

    # 2. AI said forbidden "only one language" phrases
    _forbidden = [
        "i can only respond in", "я могу отвечать только",
        "могу отвечать только", "могу общаться только",
        "only respond in english", "only in english",
    ]
    for f in _forbidden:
        if f in resp_lower:
            _add("forbidden_phrase", "high",
                 f"AI claimed language restriction: '{f[:40]}'")
            break

    # 3. Discount request not handled — user asked for discount but AI didn't say "фиксированные"
    is_discount_request = (
        any(_re_anomaly.search(p, msg_lower) for p in _DISCOUNT_PATTERNS_RU)
        or any(_re_anomaly.search(p, msg_lower) for p in _DISCOUNT_PATTERNS_UZ)
    )
    if is_discount_request and "фиксированн" not in resp_lower and "fixed" not in resp_lower:
        _add("discount_missed", "medium",
             "User requested discount but AI didn't say prices are fixed")

    # 4. "условия/правила" query → AI called list_categories (showed catalog instead of conditions)
    is_conditions_query = any(_re_anomaly.search(p, msg_lower) for p in _STORE_CONDITIONS_PATTERNS)
    if is_conditions_query and "list_categories" in tools_called:
        _add("conditions_mishandled", "medium",
             "User asked about store conditions but AI showed product catalog")

    # 5. AI mixed languages — Cyrillic in Latin response or vice versa
    if detected_lang in ("uz_latin",) and ai_response:
        _cyr = sum(1 for c in ai_response if "\u0400" <= c <= "\u04FF")
        _lat = sum(1 for c in ai_response if "a" <= c.lower() <= "z")
        if _cyr > 20 and _cyr > _lat * 0.5:
            _add("lang_mismatch", "high",
                 f"AI responded in Cyrillic ({_cyr} chars) to {detected_lang} user")
        # English response to Uzbek Latin user
        _en_markers = ["please", "wait", "connected", "operator", "help", "thank you",
                       "your order", "i've", "i have", "moment", "can i help"]
        _en_count = sum(1 for m in _en_markers if m in resp_lower)
        _uz_markers_lat = ["qo'sh", "buyurtma", "chaqir", "iltimos", "kuting",
                           "kerak", "tovar", "rahmat", "javob", "operatorni"]
        _uz_count = sum(1 for m in _uz_markers_lat if m in resp_lower)
        if _en_count >= 2 and _uz_count == 0:
            _add("lang_mismatch", "high",
                 "AI responded in English instead of uz_latin")
    elif detected_lang == "uz_cyrillic" and ai_response:
        _cyr = sum(1 for c in ai_response if "\u0400" <= c <= "\u04FF")
        # Check for Russian markers (not Uzbek Cyrillic)
        _ru_markers = ["отлично", "готово", "ваш заказ", "пожалуйста", "спасибо за"]
        _has_uz = any(c in ai_response for c in "ўқғҳ")
        _ru_count = sum(1 for m in _ru_markers if m in resp_lower)
        if _ru_count >= 2 and not _has_uz:
            _add("lang_mismatch", "high",
                 "AI responded in Russian instead of uz_cyrillic")
        # English response to Uzbek Cyrillic user
        _en_markers = ["please", "wait", "connected", "operator", "help", "thank you",
                       "your order", "i've", "i have", "moment"]
        _en_count = sum(1 for m in _en_markers if m in resp_lower)
        if _en_count >= 2 and not _has_uz:
            _add("lang_mismatch", "high",
                 "AI responded in English instead of uz_cyrillic")
    elif detected_lang == "en" and ai_response:
        _cyr = sum(1 for c in ai_response if "\u0400" <= c <= "\u04FF")
        _lat = sum(1 for c in ai_response if "a" <= c.lower() <= "z")
        if _cyr > 20 and _cyr > _lat * 0.5:
            _add("lang_mismatch", "high",
                 f"AI responded in Cyrillic ({_cyr} chars) to English user")

    return anomalies
