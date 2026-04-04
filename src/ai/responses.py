"""Forced response builder and context summary for AI orchestrator.

Contains deterministic response generation for order modifications
and the state_context summary builder used in the system prompt.
"""


def _build_order_modification_response(tool_name: str, result: dict, language: str = "ru") -> str | None:
    """Build a deterministic response for order modification tools.

    Returns a ready-made response string, bypassing the LLM entirely.
    This prevents the LLM from asking for address/checkout after modifying an existing order.
    Language-aware: responds in the customer's language.
    """
    title = result.get("item_title", "?")
    order_num = result.get("order_number", "")
    new_total = result.get("new_total", "?")
    try:
        total_fmt = f"{int(float(new_total)):,}".replace(",", " ")
    except (ValueError, TypeError):
        total_fmt = str(new_total)

    if tool_name == "add_item_to_order" and result.get("success"):
        if result.get("action") == "quantity_updated":
            new_qty = result.get("new_qty", "?")
            templates = {
                "ru": f"Обновил количество {title} в заказе {order_num} — теперь {new_qty} шт. Общая сумма: {total_fmt} сум 👍 Яна нима керак бўлса, ёзинг!",
                "uz_cyrillic": f"{title} миқдори {order_num} буюртмада янгиланди — энди {new_qty} дона. Жами: {total_fmt} сўм 👍 Яна нима керак бўлса, ёзинг!",
                "uz_latin": f"{title} miqdori {order_num} buyurtmada yangilandi — endi {new_qty} dona. Jami: {total_fmt} so'm 👍 Yana nima kerak bo'lsa, yozing!",
                "en": f"Updated {title} quantity in order {order_num} — now {new_qty} pcs. Total: {total_fmt} UZS 👍 Let me know if you need anything else!",
            }
        else:
            templates = {
                "ru": f"Добавил {title} в заказ {order_num}! Общая сумма: {total_fmt} сум 👍 Ещё что-то нужно?",
                "uz_cyrillic": f"{title} {order_num} буюртмага қўшилди! Жами: {total_fmt} сўм 👍 Яна нима керак бўлса, ёзинг!",
                "uz_latin": f"{title} {order_num} buyurtmaga qo'shildi! Jami: {total_fmt} so'm 👍 Yana nima kerak bo'lsa, yozing!",
                "en": f"Added {title} to order {order_num}! Total: {total_fmt} UZS 👍 Need anything else?",
            }
        return templates.get(language, templates["ru"])

    if tool_name == "remove_item_from_order" and result.get("success"):
        removed = result.get("removed_item", result.get("item_title", "?"))
        remaining = result.get("remaining_items", "?")
        if result.get("action") == "quantity_reduced":
            rem_qty = result.get("remaining_qty", "?")
            templates = {
                "ru": f"Уменьшил количество {removed} в заказе {order_num} — осталось {rem_qty} шт. Сумма: {total_fmt} сум. Ещё что-то?",
                "uz_cyrillic": f"{removed} миқдори {order_num} буюртмада камайтирилди — {rem_qty} дона қолди. Жами: {total_fmt} сўм. Яна нима керак?",
                "uz_latin": f"{removed} miqdori {order_num} buyurtmada kamaytirildi — {rem_qty} dona qoldi. Jami: {total_fmt} so'm. Yana nima kerak?",
                "en": f"Reduced {removed} quantity in order {order_num} — {rem_qty} left. Total: {total_fmt} UZS. Anything else?",
            }
        else:
            templates = {
                "ru": f"Убрал {removed} из заказа {order_num}. Осталось {remaining} товаров, сумма: {total_fmt} сум. Ещё что-то?",
                "uz_cyrillic": f"{removed} {order_num} буюртмадан олиб ташланди. {remaining} та товар қолди, жами: {total_fmt} сўм. Яна нима керак?",
                "uz_latin": f"{removed} {order_num} buyurtmadan olib tashlandi. {remaining} ta tovar qoldi, jami: {total_fmt} so'm. Yana nima kerak?",
                "en": f"Removed {removed} from order {order_num}. {remaining} items left, total: {total_fmt} UZS. Anything else?",
            }
        return templates.get(language, templates["ru"])

    # Forced response for create_order_draft — ALWAYS show order number + real items
    if tool_name == "create_order_draft" and result.get("order_id"):
        order_num = result.get("order_number", "?")
        items = result.get("items", [])
        total = result.get("total_amount", "?")
        delivery = result.get("delivery_note", "")
        eta = result.get("delivery_eta", "")

        try:
            total_fmt = f"{int(float(total)):,}".replace(",", " ")
        except (ValueError, TypeError):
            total_fmt = str(total)

        items_lines = []
        for item in items:
            ititle = item.get("title", "?")
            iprice = item.get("total_price", item.get("unit_price", "?"))
            try:
                iprice_fmt = f"{int(float(iprice)):,}".replace(",", " ")
            except (ValueError, TypeError):
                iprice_fmt = str(iprice)
            qty = item.get("qty", 1)
            qty_str = f" x{qty}" if qty > 1 else ""
            items_lines.append(f"  - {ititle}{qty_str} — {iprice_fmt}")

        items_text = "\n".join(items_lines)

        if language == "en":
            delivery_line = f"\n  - Delivery: {delivery}" if delivery else ""
            eta_line = f"\nETA: {eta}" if eta else ""
            return (
                f"Order confirmed! 🎉\n\n"
                f"Order #{order_num}\n"
                f"Items:\n{items_text}{delivery_line}\n\n"
                f"Total: {total_fmt} UZS{eta_line}\n\n"
                f"Thank you! Write if you need anything else."
            )
        elif language == "uz_cyrillic":
            delivery_line = f"\n  - Етказиб бериш: {delivery}" if delivery else ""
            eta_line = f"\nМуддати: {eta}" if eta else ""
            return (
                f"Буюртмангиз расмийлаштирилди! 🎉\n\n"
                f"Буюртма рақами: {order_num}\n"
                f"Товарлар:\n{items_text}{delivery_line}\n\n"
                f"Жами: {total_fmt} сўм{eta_line}\n\n"
                f"Харидингиз учун раҳмат! Яна нимадир керак бўлса, ёзинг 😊"
            )
        elif language == "uz_latin":
            delivery_line = f"\n  - Yetkazib berish: {delivery}" if delivery else ""
            eta_line = f"\nMuddati: {eta}" if eta else ""
            return (
                f"Buyurtmangiz rasmiylashtirildi! 🎉\n\n"
                f"Buyurtma raqami: {order_num}\n"
                f"Tovarlar:\n{items_text}{delivery_line}\n\n"
                f"Jami: {total_fmt} so'm{eta_line}\n\n"
                f"Xaridingiz uchun rahmat! Yana nimadir kerak bo'lsa, yozing 😊"
            )
        else:  # ru
            delivery_line = f"\n  - Доставка: {delivery}" if delivery else ""
            eta_line = f"\nСрок: {eta}" if eta else ""
            return (
                f"Заказ оформлен! 🎉\n\n"
                f"Номер заказа: {order_num}\n"
                f"Товары:\n{items_text}{delivery_line}\n\n"
                f"Итого: {total_fmt} сум{eta_line}\n\n"
                f"Спасибо за покупку! Если что еще надо пишите!"
            )

    # Forced response for request_handoff — always respond in customer's language
    if tool_name == "request_handoff" and result.get("status") == "handoff_created":
        templates = {
            "ru": "Я подключил оператора. Пожалуйста, подождите — вам скоро ответят. 🙏",
            "uz_cyrillic": "Операторни чақирдим. Илтимос, бироз кутинг — тез орада жавоб берамиз. 🙏",
            "uz_latin": "Operatorni chaqirdim. Iltimos, biroz kuting — tez orada javob beramiz. 🙏",
            "en": "I've connected you to an operator. Please wait a moment. 🙏",
        }
        return templates.get(language, templates["ru"])

    return None


def _build_context_summary(state_context: dict | None) -> str:
    """Build a summary of known products/variants from state_context for the system prompt."""
    if not state_context:
        return ""

    parts = []

    # Cart (most important — these will be ordered)
    cart = state_context.get("cart", [])
    if cart:
        try:
            total = sum(float(item.get("price", 0)) * int(item.get("qty", 1)) for item in cart)
            total_fmt = f"{int(total):,}".replace(",", " ")
        except (ValueError, TypeError):
            total_fmt = "?"
        parts.append("═══ РЕАЛЬНАЯ КОРЗИНА КЛИЕНТА (ТОЛЬКО ЭТИ ТОВАРЫ!) ═══")
        parts.append(f"⚠️ ВАЖНО: В корзине ровно {len(cart)} товар(ов). НЕ добавляй другие товары в список при оформлении!")
        for i, item in enumerate(cart, 1):
            title = item.get("title", "?")
            price = item.get("price", "?")
            qty = item.get("qty", 1)
            vid = item.get("variant_id", "?")
            try:
                price_fmt = f"{int(float(price)):,}".replace(",", " ")
            except (ValueError, TypeError):
                price_fmt = str(price)
            parts.append(f"  {i}. {title} — {price_fmt} сум x{qty} (variant_id: {vid})")
        parts.append(f"  Итого товаров: {total_fmt} сум")
        parts.append("═══════════════════════════════════════════════")
        parts.append("")

    # Known products from search
    products = state_context.get("products", {})
    if products:
        parts.append("Известные товары в этом диалоге:")
        for name, info in products.items():
            pid = info.get("product_id", "?")
            parts.append(f"  {name} (product_id: {pid})")
            for i, v in enumerate(info.get("variants", []), 1):
                vid = v.get("variant_id", "?")
                title = v.get("title", "?")
                price = v.get("price", "?")
                stock = v.get("available_quantity", "?")
                specs = v.get("specs")
                spec_str = ""
                if specs and isinstance(specs, dict):
                    spec_parts = [f"{k}: {val}" for k, val in specs.items()]
                    spec_str = f" | {', '.join(spec_parts)}"
                parts.append(f"    {i}. {title} — {price} сум, {stock} шт (variant_id: {vid}){spec_str}")

    # Proactive suggestion: products shown but not in cart
    shown = state_context.get("shown_products", [])
    if cart and shown:
        cart_vids = {item.get("variant_id") for item in cart}
        cart_pids = set()
        for item in cart:
            vid = item.get("variant_id")
            for prod_info in state_context.get("products", {}).values():
                for v in prod_info.get("variants", []):
                    if v.get("variant_id") == vid:
                        cart_pids.add(prod_info.get("product_id"))
        not_carted = [s for s in shown if s.get("variant_id") not in cart_vids and s.get("product_id") not in cart_pids]
        if not_carted:
            parts.append("ТОВАРЫ КОТОРЫЕ КЛИЕНТ СМОТРЕЛ НО НЕ ДОБАВИЛ В КОРЗИНУ:")
            for s in not_carted[-3:]:  # Last 3 at most
                parts.append(f"  → {s.get('title', '?')} — {s.get('price', '?')} сум")
            parts.append("  💡 Когда клиент переходит к оформлению — ОДИН раз спроси: 'Вы также смотрели [товар]. Добавить в заказ?' Если игнорирует — не повторяй.")
            parts.append("")

    # Previous orders
    orders = state_context.get("orders", [])
    if orders:
        parts.append("\nЗаказы клиента:")
        for o in orders:
            parts.append(f"  {o.get('order_number', '?')} — {o.get('total_amount', '?')} сум")

    customer = state_context.get("customer", {})
    if customer:
        parts.append(f"\nДанные клиента: имя={customer.get('name','?')}, тел={customer.get('phone','?')}, город={customer.get('city','?')}, адрес={customer.get('address','?')}")

    # Recent order modifications (what AI actually did)
    mods = state_context.get("last_order_modifications", [])
    if mods:
        parts.append("\nПОСЛЕДНИЕ ИЗМЕНЕНИЯ ЗАКАЗОВ (ты это сделал!):")
        for m in mods:
            action = "Добавил" if m.get("action") == "added" else "Убрал"
            parts.append(f"  ✓ {action} {m.get('item', '?')} в заказ {m.get('order', '?')}")

    return "\n".join(parts) if parts else ""
