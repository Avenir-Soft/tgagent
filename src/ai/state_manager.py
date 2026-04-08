"""Conversation state management for AI orchestrator.

Handles state determination from conversation context and updating
state_context after tool calls.
"""

from src.conversations.models import Conversation


def _determine_state(conversation: Conversation, state_context: dict) -> str:
    """Determine the current conversation state based on data."""
    # If explicitly set and valid, use it
    current = conversation.state or "idle"

    # Auto-detect based on state_context
    cart = state_context.get("cart", [])
    orders = state_context.get("orders", [])
    products = state_context.get("products", {})

    if current == "handoff":
        return "handoff"

    # Has orders → post_order (unless actively shopping or checking out)
    if orders and not cart and current not in ("browsing", "selection", "checkout"):
        return "post_order"

    # In checkout — keep it (collecting name/phone/address)
    if current == "checkout":
        return "checkout"

    # Has cart items
    if cart:
        return "cart"

    # Has products with variants loaded → selection
    for info in products.values():
        if info.get("variants"):
            return "selection"

    # Has products without variants → browsing
    if products:
        return "browsing"

    # Default
    if current in ("idle", "NEW_CHAT"):
        return "idle"

    return current


def _update_context_from_tool(state_context: dict, tool_name: str, tool_args: dict, tool_result: dict) -> dict:
    """Update state_context with data from tool results."""
    if tool_name == "get_product_candidates" and tool_result.get("found"):
        products = state_context.setdefault("products", {})
        result_products = tool_result.get("products", [])
        # Collect image URLs for Telegram send_file
        for p in result_products:
            if p.get("image_url"):
                pending = state_context.setdefault("_pending_images", [])
                if p["image_url"] not in pending:
                    pending.append(p["image_url"])
        # Track shown products for proactive suggestions — BUT only for SPECIFIC searches
        # (1-2 results). Category listings (3+ results) are too broad — user didn't
        # specifically ask about any of those products.
        shown = state_context.setdefault("shown_products", [])
        in_stock_results = [p for p in result_products if p.get("in_stock", True) and p.get("total_available_stock", 0) > 0]
        is_specific_search = len(in_stock_results) <= 2
        for p in result_products:
            products[p["name"]] = {
                "product_id": p["product_id"],
                "brand": p.get("brand"),
                "model": p.get("model"),
                "total_available_stock": p.get("total_available_stock", 0),
                "in_stock": p.get("in_stock", True),
                "price_range": p.get("price_range"),
                "variants": [],
            }
            # Only track for proactive suggestion if this was a specific search (1-2 results)
            if is_specific_search and p.get("in_stock", True) and p.get("total_available_stock", 0) > 0:
                pid = p["product_id"]
                price_range = p.get("price_range", "?")
                if not any(s.get("product_id") == pid for s in shown):
                    shown.append({
                        "product_id": pid,
                        "title": p["name"],
                        "price": price_range,
                    })
        # Keep only last 10
        if len(shown) > 10:
            state_context["shown_products"] = shown[-10:]

    elif tool_name == "get_variant_candidates" and tool_result.get("found"):
        variants = tool_result.get("variants", [])
        if variants:
            # Collect variant image URLs for Telegram send_file (max 3)
            pending = state_context.setdefault("_pending_images", [])
            for v in variants:
                if v.get("image_url") and v["image_url"] not in pending and len(pending) < 3:
                    pending.append(v["image_url"])
            products = state_context.get("products", {})
            called_pid = tool_args.get("product_id", "")
            matched = False
            for name, info in products.items():
                if info.get("product_id") == called_pid:
                    info["variants"] = variants
                    matched = True
                    break
            if not matched:
                first_title = variants[0].get("title", "Unknown")
                state_context.setdefault("products", {})[first_title] = {
                    "product_id": called_pid,
                    "variants": variants,
                }

            # Track shown products for proactive suggestions later
            shown = state_context.setdefault("shown_products", [])
            for v in variants:
                vid = v.get("variant_id")
                title = v.get("title", "?")
                price = v.get("price", "?")
                if vid and not any(s.get("variant_id") == vid for s in shown):
                    shown.append({"variant_id": vid, "product_id": called_pid, "title": title, "price": price})
            # Keep only last 10 shown
            if len(shown) > 10:
                state_context["shown_products"] = shown[-10:]

    elif tool_name in ("select_for_cart", "remove_from_cart"):
        if tool_result.get("cart") is not None:
            state_context["cart"] = tool_result["cart"]

    elif tool_name == "create_order_draft" and tool_result.get("order_id"):
        orders = state_context.setdefault("orders", [])
        orders.append({
            "order_id": tool_result["order_id"],
            "order_number": tool_result.get("order_number"),
            "total_amount": tool_result.get("total_amount"),
            "items": tool_result.get("items", []),
        })
        # Mark conversation as training candidate — order was created successfully
        state_context["_training_candidate"] = True

    elif tool_name == "cancel_order" and tool_result.get("cancelled"):
        # Remove cancelled order from context
        order_num = tool_result.get("order_number")
        orders = state_context.get("orders", [])
        state_context["orders"] = [o for o in orders if o.get("order_number") != order_num]
        # Clear cart — items belonged to this order, no longer relevant
        state_context["cart"] = []

    elif tool_name in ("add_item_to_order", "remove_item_from_order") and tool_result.get("success"):
        # Update order total and items in context
        order_num = tool_result.get("order_number")
        new_total = tool_result.get("new_total")
        if order_num and new_total:
            for o in state_context.get("orders", []):
                if o.get("order_number") == order_num:
                    o["total_amount"] = new_total
                    # Update items list in context
                    if tool_name == "add_item_to_order":
                        items = o.setdefault("items", [])
                        items.append({
                            "title": tool_result.get("item_title", "?"),
                            "qty": tool_result.get("qty", 1),
                            "unit_price": tool_result.get("item_price", "0"),
                            "total_price": tool_result.get("item_price", "0"),
                        })
                    elif tool_name == "remove_item_from_order":
                        removed_title = tool_result.get("removed_item", tool_result.get("item_title", ""))
                        action = tool_result.get("action")
                        items = o.get("items", [])
                        if action == "quantity_reduced":
                            # Update qty for reduced item
                            for it in items:
                                if it.get("title") == removed_title:
                                    it["qty"] = tool_result.get("remaining_qty", it["qty"])
                                    break
                        else:
                            # Full removal
                            o["items"] = [it for it in items if it.get("title") != removed_title]

        # Track modification history so AI remembers what it did
        mods = state_context.setdefault("last_order_modifications", [])
        if tool_name == "add_item_to_order":
            mods.append({
                "action": "added",
                "item": tool_result.get("item_title", "?"),
                "order": order_num,
                "new_total": new_total,
            })
        elif tool_name == "remove_item_from_order":
            mods.append({
                "action": tool_result.get("action", "removed"),
                "item": tool_result.get("removed_item", tool_result.get("item_title", "?")),
                "order": order_num,
                "new_total": new_total,
            })
        # Keep only last 5 modifications
        if len(mods) > 5:
            state_context["last_order_modifications"] = mods[-5:]

    return state_context


def cleanup_state_context(state_context: dict) -> dict:
    """Cleanup state_context to prevent JSONB bloat.

    Caps: products<=5, shown_products<=10, orders<=5, variants<=8/product.
    Removes empty collections and per-request temporary keys.
    """
    # Keep only last 5 products
    products = state_context.get("products", {})
    if len(products) > 5:
        keys = list(products.keys())
        for k in keys[:-5]:
            del products[k]

    # Keep only last 10 shown_products
    shown = state_context.get("shown_products", [])
    if len(shown) > 10:
        state_context["shown_products"] = shown[-10:]

    # Keep only last 5 orders
    orders = state_context.get("orders", [])
    if len(orders) > 5:
        state_context["orders"] = orders[-5:]

    # Remove per-request temporary keys
    state_context.pop("_current_order_info", None)

    # Trim variant lists inside products to max 8 per product
    for prod_info in state_context.get("products", {}).values():
        variants = prod_info.get("variants", [])
        if len(variants) > 8:
            prod_info["variants"] = variants[:8]

    # Remove empty collections to keep JSONB compact
    for key in ("cart", "products", "shown_products", "orders"):
        val = state_context.get(key)
        if val is not None and not val:
            del state_context[key]

    return state_context
