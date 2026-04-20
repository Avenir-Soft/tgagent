"""Conversation state management for AI orchestrator.

Handles state determination from conversation context and updating
state_context after tool calls.

Adapted for Easy Tour — tour booking context (no cart/delivery).
"""

from src.conversations.models import Conversation


def _determine_state(conversation: Conversation, state_context: dict) -> str:
    """Determine the current conversation state based on data."""
    current = conversation.state or "idle"

    # Auto-detect based on state_context
    booking = state_context.get("booking", {})
    orders = state_context.get("orders", [])
    products = state_context.get("products", {})

    if current == "handoff":
        return "handoff"

    # Has orders → post_order (unless actively browsing or selecting)
    if orders and not booking and current not in ("browsing", "selection"):
        return "post_order"

    # In booking flow — keep it (collecting name/phone/participants)
    if current == "booking":
        return "booking"

    # Pending payment — waiting for receipt
    if current == "pending_payment":
        return "pending_payment"

    # Has booking context
    if booking:
        return "booking"

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
        for p in result_products:
            products[p["name"]] = {
                "product_id": p["product_id"],
                "difficulty": p.get("difficulty"),
                "duration": p.get("duration"),
                "total_seats_available": p.get("total_seats_available", 0),
                "in_stock": p.get("in_stock", True),
                "price_range": p.get("price_range"),
                "variants": [],
            }

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

    elif tool_name == "create_order_draft" and tool_result.get("order_id"):
        orders = state_context.setdefault("orders", [])
        orders.append({
            "order_id": tool_result["order_id"],
            "order_number": tool_result.get("order_number"),
            "total_amount": tool_result.get("total_amount"),
            "items": tool_result.get("items", []),
        })
        # Clear booking context after successful order
        state_context.pop("booking", None)
        state_context.pop("_proactive_suggested", None)
        # Mark conversation as training candidate — booking was created successfully
        state_context["_training_candidate"] = True

    elif tool_name == "cancel_order" and tool_result.get("cancelled"):
        # Remove cancelled booking from context
        order_num = tool_result.get("order_number")
        orders = state_context.get("orders", [])
        state_context["orders"] = [o for o in orders if o.get("order_number") != order_num]

    return state_context


def cleanup_state_context(state_context: dict) -> dict:
    """Cleanup state_context to prevent JSONB bloat.

    Caps: products<=5, orders<=5, variants<=8/product.
    Removes empty collections and per-request temporary keys.
    """
    # Keep only last 5 products
    products = state_context.get("products", {})
    if len(products) > 5:
        keys = list(products.keys())
        for k in keys[:-5]:
            del products[k]

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
    for key in ("products", "orders", "booking"):
        val = state_context.get(key)
        if val is not None and not val:
            del state_context[key]

    return state_context
