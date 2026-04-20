"""Forced response builder and context summary for AI orchestrator.

Contains deterministic response generation for tour bookings
and the state_context summary builder used in the system prompt.

Adapted for Easy Tour — tour booking context.
"""


_FORMAL_TONES = {"formal_business", "formal", "business"}


def _strip_emoji(text: str) -> str:
    """Remove common emoji from text for formal tone."""
    import re
    return re.sub(r"[\U0001f300-\U0001f9ff\u2600-\u26ff\u2700-\u27bf]", "", text).replace("  ", " ").strip()


def _build_order_modification_response(tool_name: str, result: dict, language: str = "uz_latin", tone: str = "friendly_sales") -> str | None:
    """Build a deterministic response for booking tools.

    Returns a ready-made response string, bypassing the LLM entirely.
    Language-aware, tone-aware.
    """
    # Forced response for create_order_draft — ALWAYS show booking number + tour details + payment instructions
    if tool_name == "create_order_draft" and result.get("order_id"):
        order_num = result.get("order_number", "?")
        items = result.get("items", [])
        total = result.get("total_amount", "?")

        try:
            total_fmt = f"{int(float(total)):,}".replace(",", " ")
        except (ValueError, TypeError):
            total_fmt = str(total)

        # Language-specific labels for items
        _qty_label = {"ru": "чел.", "en": "pax", "uz_cyrillic": "киши"}.get(language, "kishi")
        _currency = {"ru": "сум", "en": "UZS", "uz_cyrillic": "сўм"}.get(language, "so'm")

        items_lines = []
        for item in items:
            ititle = item.get("title", "?")
            iprice = item.get("total_price", item.get("unit_price", "?"))
            try:
                iprice_fmt = f"{int(float(iprice)):,}".replace(",", " ")
            except (ValueError, TypeError):
                iprice_fmt = str(iprice)
            qty = item.get("qty", 1)
            qty_str = f" x{qty} {_qty_label}" if qty > 1 else ""
            items_lines.append(f"  - {ititle}{qty_str} — {iprice_fmt} {_currency}")

        items_text = "\n".join(items_lines)

        if language == "en":
            resp = (
                f"Booking confirmed! 🎉\n\n"
                f"Booking #{order_num}\n"
                f"Tour:\n{items_text}\n\n"
                f"Total: {total_fmt} UZS\n\n"
                f"Please pay via Payme, Click, or cash, and send the receipt screenshot here. "
                f"Our operator will confirm your booking."
            )
        elif language == "uz_cyrillic":
            resp = (
                f"Буюртмангиз расмийлаштирилди! 🎉\n\n"
                f"Буюртма рақами: {order_num}\n"
                f"Тур:\n{items_text}\n\n"
                f"Жами: {total_fmt} сўм\n\n"
                f"Тўловни амалга оширинг (Payme, Click ёки нақд) ва чекни шу ерга юборинг 📸\n"
                f"Операторимиз буюртмангизни тасдиқлайди."
            )
        elif language == "ru":
            resp = (
                f"Бронирование оформлено! 🎉\n\n"
                f"Номер бронирования: {order_num}\n"
                f"Тур:\n{items_text}\n\n"
                f"Итого: {total_fmt} сум\n\n"
                f"Оплатите через Payme, Click или наличными и отправьте скриншот чека сюда 📸\n"
                f"Оператор подтвердит бронирование."
            )
        else:  # uz_latin (default)
            resp = (
                f"Buyurtmangiz rasmiylashtirildi! 🎉\n\n"
                f"Buyurtma raqami: {order_num}\n"
                f"Tur:\n{items_text}\n\n"
                f"Jami: {total_fmt} so'm\n\n"
                f"To'lovni amalga oshiring (Payme, Click yoki naqd) va chekni shu yerga yuboring 📸\n"
                f"Operatorimiz buyurtmangizni tasdiqlaydi."
            )
        return _strip_emoji(resp) if tone in _FORMAL_TONES else resp

    # Forced response for request_handoff — always respond in customer's language
    if tool_name == "request_handoff" and result.get("status") == "handoff_created":
        templates = {
            "ru": "Я подключил оператора. Пожалуйста, подождите — вам скоро ответят. 🙏",
            "uz_cyrillic": "Операторни чақирдим. Илтимос, бироз кутинг — тез орада жавоб берамиз. 🙏",
            "uz_latin": "Operatorni chaqirdim. Iltimos, biroz kuting — tez orada javob beramiz. 🙏",
            "en": "I've connected you to an operator. Please wait a moment. 🙏",
        }
        resp = templates.get(language, templates["uz_latin"])
        return _strip_emoji(resp) if tone in _FORMAL_TONES else resp

    return None


def _build_context_summary(state_context: dict | None) -> str:
    """Build a summary of known tours/variants from state_context for the system prompt."""
    if not state_context:
        return ""

    parts = []

    # Booking info (if in booking flow)
    booking = state_context.get("booking", {})
    if booking:
        parts.append("═══ JORIY BUYURTMA MA'LUMOTLARI ═══")
        if booking.get("variant_id"):
            parts.append(f"  Tanlangan sana variant_id: {booking['variant_id']}")
        if booking.get("tour_name"):
            parts.append(f"  Tur: {booking['tour_name']}")
        parts.append("═══════════════════════════════════")
        parts.append("")

    # Known tours from search
    products = state_context.get("products", {})
    if products:
        parts.append("Dialoqdagi ma'lum turlar:")
        for name, info in products.items():
            pid = info.get("product_id", "?")
            parts.append(f"  {name} (product_id: {pid})")
            for i, v in enumerate(info.get("variants", []), 1):
                vid = v.get("variant_id", "?")
                title = v.get("title", "?")
                price = v.get("price", "?")
                seats = v.get("available_seats", v.get("available_quantity", "?"))
                parts.append(f"    {i}. {title} — {price} so'm, {seats} ta joy (variant_id: {vid})")

    # Previous bookings
    orders = state_context.get("orders", [])
    if orders:
        parts.append("\nMijoz buyurtmalari:")
        for o in orders:
            parts.append(f"  {o.get('order_number', '?')} — {o.get('total_amount', '?')} so'm")

    customer = state_context.get("customer", {})
    if customer:
        parts.append(f"\nMijoz ma'lumotlari: ism={customer.get('name','?')}, tel={customer.get('phone','?')}")

    return "\n".join(parts) if parts else ""
