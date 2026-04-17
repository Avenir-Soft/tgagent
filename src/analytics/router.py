"""Analytics router — RFM segmentation, conversation metrics, funnel, stock forecast, competitors."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
from src.core.rate_limit import limiter
from src.analytics.models import CustomerSegment, CompetitorPrice
from src.analytics.schemas import (
    CompetitorPriceCreate,
    CompetitorPriceOut,
    CompetitorSummary,
    ConversationAnalytics,
    CustomerSegmentOut,
    DailyTrend,
    FunnelResponse,
    FunnelStage,
    RFMSummary,
    StockForecastItem,
    StockForecastResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── RFM Customer Segmentation ──────────────────────────────────────────


@router.post("/rfm/compute")
@limiter.limit("10/minute")
async def compute_rfm(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Recompute RFM segments for all customers with orders."""
    tid = str(user.tenant_id)

    # Step 1: Compute RFM data
    rfm_query = text("""
        WITH lead_orders AS (
            SELECT
                l.id AS lead_id,
                l.customer_name,
                l.telegram_user_id,
                EXTRACT(DAY FROM now() - MAX(o.created_at))::int AS recency_days,
                COUNT(o.id)::int AS frequency,
                COALESCE(SUM(o.total_amount), 0) AS monetary
            FROM leads l
            JOIN orders o ON o.lead_id = l.id
            WHERE l.tenant_id = :tid
              AND o.status NOT IN ('draft', 'cancelled')
            GROUP BY l.id, l.customer_name, l.telegram_user_id
            HAVING COUNT(o.id) > 0
        ),
        scored AS (
            SELECT *,
                NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
                NTILE(5) OVER (ORDER BY frequency ASC) AS f_score,
                NTILE(5) OVER (ORDER BY monetary ASC) AS m_score
            FROM lead_orders
        )
        SELECT
            lead_id, customer_name, telegram_user_id,
            recency_days, frequency, monetary,
            r_score, f_score, m_score,
            r_score * 100 + f_score * 10 + m_score AS rfm_score,
            CASE
                WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'vip'
                WHEN r_score >= 3 AND f_score >= 3 THEN 'loyal'
                WHEN r_score >= 4 AND f_score <= 2 THEN 'new'
                WHEN r_score >= 3 AND f_score <= 2 AND m_score >= 3 THEN 'promising'
                WHEN r_score <= 2 AND f_score >= 3 THEN 'at_risk'
                WHEN r_score <= 2 AND f_score <= 2 THEN 'lost'
                ELSE 'regular'
            END AS segment
        FROM scored
    """)
    result = await db.execute(rfm_query, {"tid": tid})
    rows = result.mappings().all()

    if not rows:
        return {"computed": 0}

    # Step 2: Upsert into customer_segments
    upsert_query = text("""
        INSERT INTO customer_segments (
            id, tenant_id, lead_id, customer_name, telegram_user_id,
            recency_days, frequency, monetary, r_score, f_score, m_score,
            rfm_score, segment, created_at, updated_at
        ) VALUES (
            gen_random_uuid(), :tid, :lead_id, :customer_name, :telegram_user_id,
            :recency_days, :frequency, :monetary, :r_score, :f_score, :m_score,
            :rfm_score, :segment, now(), now()
        )
        ON CONFLICT (tenant_id, lead_id) DO UPDATE SET
            customer_name = EXCLUDED.customer_name,
            telegram_user_id = EXCLUDED.telegram_user_id,
            recency_days = EXCLUDED.recency_days,
            frequency = EXCLUDED.frequency,
            monetary = EXCLUDED.monetary,
            r_score = EXCLUDED.r_score,
            f_score = EXCLUDED.f_score,
            m_score = EXCLUDED.m_score,
            rfm_score = EXCLUDED.rfm_score,
            segment = EXCLUDED.segment,
            updated_at = now()
    """)

    # Batch upsert — executemany sends all params in one round-trip
    batch_size = 500
    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start:batch_start + batch_size]
        params = [{"tid": tid, **dict(row)} for row in batch]
        await db.execute(upsert_query, params)
        await db.flush()

    # Remove stale segments (leads without qualifying orders anymore)
    active_lead_ids = [r["lead_id"] for r in rows]
    if active_lead_ids:
        await db.execute(
            delete(CustomerSegment).where(
                CustomerSegment.tenant_id == user.tenant_id,
                CustomerSegment.lead_id.notin_(active_lead_ids),
            )
        )
    else:
        await db.execute(
            delete(CustomerSegment).where(CustomerSegment.tenant_id == user.tenant_id)
        )

    await db.flush()
    logger.info("RFM computed for tenant %s: %d customers", tid[:8], len(rows))
    return {"computed": len(rows)}


@router.get("/rfm/segments", response_model=RFMSummary)
async def get_rfm_segments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get RFM segment summary + top customers."""
    tid = str(user.tenant_id)

    # Segment counts
    seg_result = await db.execute(
        text("SELECT segment, COUNT(*)::int AS cnt FROM customer_segments WHERE tenant_id = :tid GROUP BY segment"),
        {"tid": tid},
    )
    segments = {row.segment: row.cnt for row in seg_result}
    total = sum(segments.values())

    # Top 20 by monetary
    top_result = await db.execute(
        text("""
            SELECT lead_id, customer_name, telegram_user_id, recency_days,
                   frequency, monetary, r_score, f_score, m_score, rfm_score, segment
            FROM customer_segments WHERE tenant_id = :tid
            ORDER BY monetary DESC LIMIT 20
        """),
        {"tid": tid},
    )
    top_customers = [CustomerSegmentOut(**dict(r)) for r in top_result.mappings()]

    return RFMSummary(segments=segments, total_customers=total, top_customers=top_customers)


@router.get("/rfm/customers", response_model=list[CustomerSegmentOut])
async def list_rfm_customers(
    segment: str | None = None,
    sort_by: str = "monetary",
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List customers with RFM data, filterable by segment."""
    from src.analytics.models import CustomerSegment
    q = select(CustomerSegment).where(CustomerSegment.tenant_id == user.tenant_id)
    if segment:
        q = q.where(CustomerSegment.segment == segment)

    allowed_sorts = {
        "monetary": CustomerSegment.monetary.desc(),
        "frequency": CustomerSegment.frequency.desc(),
        "recency_days": CustomerSegment.recency_days.asc(),
    }
    q = q.order_by(allowed_sorts.get(sort_by, CustomerSegment.monetary.desc()))
    q = q.limit(limit).offset(offset)

    result = await db.execute(q)
    rows = result.scalars().all()
    return [CustomerSegmentOut.model_validate(r) for r in rows]


@router.get("/rfm/customer-detail")
async def get_customer_detail(
    telegram_user_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get customer segment reason, conversation link, and recent messages."""
    tid = str(user.tenant_id)

    # Find conversation for this telegram user
    conv_result = await db.execute(
        text("""
            SELECT id, telegram_chat_id, last_message_at, state
            FROM conversations
            WHERE tenant_id = :tid AND telegram_user_id = :tuid
            ORDER BY last_message_at DESC NULLS LAST
            LIMIT 1
        """),
        {"tid": tid, "tuid": telegram_user_id},
    )
    conv = conv_result.mappings().first()
    conversation_id = str(conv["id"]) if conv else None

    # Get last customer messages (to explain segment)
    messages = []
    if conversation_id:
        msg_result = await db.execute(
            text("""
                SELECT raw_text, sender_type, created_at
                FROM messages
                WHERE conversation_id = :cid
                ORDER BY created_at DESC
                LIMIT 10
            """),
            {"cid": conversation_id},
        )
        for m in msg_result.mappings():
            messages.append({
                "text": (m["raw_text"] or "")[:200],
                "sender_type": m["sender_type"],
                "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            })
        messages.reverse()

    # Get segment info
    seg_result = await db.execute(
        text("""
            SELECT segment, recency_days, frequency, monetary, r_score, f_score, m_score
            FROM customer_segments
            WHERE tenant_id = :tid AND telegram_user_id = :tuid
            LIMIT 1
        """),
        {"tid": tid, "tuid": telegram_user_id},
    )
    seg = seg_result.mappings().first()

    # Build reason explanation
    reason = ""
    if seg:
        segment = seg["segment"]
        r, f, m = seg["r_score"], seg["f_score"], seg["m_score"]
        recency = seg["recency_days"]
        freq = seg["frequency"]

        reasons = {
            "vip": f"Частые покупки ({freq} заказов), высокий чек, активен {recency} дн. назад",
            "loyal": f"Стабильные покупки ({freq} заказов), был {recency} дн. назад",
            "promising": f"Недавно активен ({recency} дн.), потенциал роста (R={r}, F={f})",
            "new": f"Новый клиент, первая покупка {recency} дн. назад",
            "at_risk": f"Давно не покупал ({recency} дн.), раньше было {freq} заказов. R={r}, F={f}",
            "lost": f"Не активен {recency} дн., был {freq} заказ(ов). Возможно ушёл к конкуренту",
            "regular": f"Стандартная активность: {freq} заказов, {recency} дн. назад",
        }
        reason = reasons.get(segment, f"R={r} F={f} M={m}")

    return {
        "conversation_id": conversation_id,
        "reason": reason,
        "messages": messages,
    }


# ── Conversation Analytics ─────────────────────────────────────────────


@router.get("/conversations", response_model=ConversationAnalytics)
async def get_conversation_analytics(
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Conversation performance metrics."""
    tid = str(user.tenant_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Avg & median response time (using LEAD window function instead of correlated subquery)
    rt_result = await db.execute(
        text("""
            WITH ordered_msgs AS (
                SELECT
                    direction,
                    created_at,
                    LEAD(created_at) OVER (PARTITION BY conversation_id ORDER BY created_at) AS next_at,
                    LEAD(direction) OVER (PARTITION BY conversation_id ORDER BY created_at) AS next_dir
                FROM messages
                WHERE tenant_id = :tid
                  AND created_at >= :since
            ),
            pairs AS (
                SELECT
                    EXTRACT(EPOCH FROM (next_at - created_at)) AS rt_seconds
                FROM ordered_msgs
                WHERE direction = 'inbound' AND next_dir = 'outbound'
            )
            SELECT
                AVG(rt_seconds)::float AS avg_rt,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rt_seconds)::float AS median_rt
            FROM pairs
        """),
        {"tid": tid, "since": since},
    )
    rt = rt_result.mappings().first()
    avg_rt = round(rt["avg_rt"], 1) if rt and rt["avg_rt"] else None
    median_rt = round(rt["median_rt"], 1) if rt and rt["median_rt"] else None

    # Total conversations
    total_result = await db.execute(
        text("SELECT COUNT(*)::int AS cnt FROM conversations WHERE tenant_id = :tid AND source_type = 'dm' AND created_at >= :since"),
        {"tid": tid, "since": since},
    )
    total_convs = total_result.scalar() or 0

    # Resolution rate (reached post_order or has confirmed+ order)
    # Use LEFT JOIN instead of correlated EXISTS for better performance
    resolved_result = await db.execute(
        text("""
            WITH ordered_users AS (
                SELECT DISTINCT l.telegram_user_id
                FROM leads l JOIN orders o ON o.lead_id = l.id
                WHERE l.tenant_id = :tid
                  AND o.status IN ('confirmed','processing','shipped','delivered')
            )
            SELECT COUNT(*)::int AS cnt FROM conversations c
            LEFT JOIN ordered_users ou ON ou.telegram_user_id = c.telegram_user_id
            WHERE c.tenant_id = :tid AND c.source_type = 'dm' AND c.created_at >= :since
              AND (c.state = 'post_order' OR ou.telegram_user_id IS NOT NULL)
        """),
        {"tid": tid, "since": since},
    )
    resolved = resolved_result.scalar() or 0
    resolution_pct = round(resolved / total_convs * 100, 1) if total_convs else 0

    # Handoff rate
    handoff_result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT h.conversation_id)::int AS cnt
            FROM handoffs h WHERE h.tenant_id = :tid AND h.created_at >= :since
        """),
        {"tid": tid, "since": since},
    )
    handoff_count = handoff_result.scalar() or 0
    handoff_pct = round(handoff_count / total_convs * 100, 1) if total_convs else 0

    # Messages by sender type
    sender_result = await db.execute(
        text("""
            SELECT sender_type, COUNT(*)::int AS cnt FROM messages
            WHERE tenant_id = :tid AND created_at >= :since
            GROUP BY sender_type
        """),
        {"tid": tid, "since": since},
    )
    messages_by_sender = {r.sender_type: r.cnt for r in sender_result}

    # Daily trend
    trend_result = await db.execute(
        text("""
            SELECT DATE(created_at)::text AS day,
                   COUNT(*)::int AS conversations,
                   COUNT(*) FILTER (WHERE state = 'post_order')::int AS resolved
            FROM conversations
            WHERE tenant_id = :tid AND source_type = 'dm' AND created_at >= :since
            GROUP BY DATE(created_at) ORDER BY DATE(created_at)
        """),
        {"tid": tid, "since": since},
    )
    daily_trend = [DailyTrend(date=r.day, conversations=r.conversations, resolved=r.resolved) for r in trend_result]

    return ConversationAnalytics(
        period_days=days,
        avg_response_time_seconds=avg_rt,
        median_response_time_seconds=median_rt,
        resolution_rate_pct=resolution_pct,
        handoff_rate_pct=handoff_pct,
        total_conversations=total_convs,
        messages_by_sender=messages_by_sender,
        daily_trend=daily_trend,
    )


# ── Funnel Visualization ──────────────────────────────────────────────


@router.get("/funnel", response_model=FunnelResponse)
async def get_funnel(
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Conversion funnel data."""
    tid = str(user.tenant_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM conversations WHERE tenant_id = :tid AND source_type = 'dm' AND created_at >= :since)::int AS visitors,
                (SELECT COUNT(*) FROM leads WHERE tenant_id = :tid AND created_at >= :since)::int AS leads,
                (SELECT COUNT(*) FROM conversations WHERE tenant_id = :tid AND source_type = 'dm' AND created_at >= :since
                 AND state IN ('cart','checkout','post_order'))::int AS cart,
                (SELECT COUNT(*) FROM conversations WHERE tenant_id = :tid AND source_type = 'dm' AND created_at >= :since
                 AND state IN ('checkout','post_order'))::int AS checkout,
                (SELECT COUNT(*) FROM orders WHERE tenant_id = :tid AND created_at >= :since AND status NOT IN ('draft','cancelled'))::int AS orders,
                (SELECT COUNT(*) FROM orders WHERE tenant_id = :tid AND created_at >= :since AND status = 'delivered')::int AS delivered
        """),
        {"tid": tid, "since": since},
    )
    row = result.mappings().first()
    visitors = row["visitors"] or 0

    labels = {
        "visitors": "Посетители",
        "leads": "Лиды",
        "cart": "Корзина",
        "checkout": "Оформление",
        "orders": "Заказы",
        "delivered": "Доставлено",
    }

    stages = []
    for key in ["visitors", "leads", "cart", "checkout", "orders", "delivered"]:
        count = row[key] or 0
        pct = round(count / visitors * 100, 1) if visitors > 0 else None
        stages.append(FunnelStage(name=key, label=labels[key], count=count, pct=pct))

    return FunnelResponse(period_days=days, stages=stages)


# ── Stock Forecast ─────────────────────────────────────────────────────


@router.get("/stock-forecast", response_model=StockForecastResponse)
async def get_stock_forecast(
    forecast_days: int = Query(14, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Demand forecast and stockout alerts."""
    tid = str(user.tenant_id)

    result = await db.execute(
        text("""
            WITH daily_sales AS (
                SELECT
                    oi.product_variant_id AS variant_id,
                    DATE(o.created_at) AS day,
                    SUM(oi.qty)::int AS daily_qty
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.tenant_id = :tid
                  AND o.status NOT IN ('draft', 'cancelled')
                  AND o.created_at >= now() - interval '30 days'
                  AND oi.product_variant_id IS NOT NULL
                GROUP BY oi.product_variant_id, DATE(o.created_at)
            ),
            velocity AS (
                SELECT
                    variant_id,
                    AVG(daily_qty)::float AS avg_daily_sales,
                    COUNT(*)::int AS active_days
                FROM daily_sales
                GROUP BY variant_id
            )
            SELECT
                i.variant_id,
                pv.product_id,
                pv.title AS variant_title,
                p.name AS product_name,
                (i.quantity - i.reserved_quantity)::int AS available_stock,
                COALESCE(v.avg_daily_sales, 0)::float AS avg_daily_sales,
                CASE
                    WHEN COALESCE(v.avg_daily_sales, 0) > 0
                    THEN FLOOR((i.quantity - i.reserved_quantity) / v.avg_daily_sales)::int
                    ELSE NULL
                END AS days_until_stockout,
                ROUND(COALESCE(v.avg_daily_sales, 0) * :forecast_days)::int AS forecasted_demand
            FROM inventory i
            JOIN product_variants pv ON pv.id = i.variant_id
            JOIN products p ON p.id = pv.product_id
            LEFT JOIN velocity v ON v.variant_id = i.variant_id
            WHERE i.tenant_id = :tid AND pv.is_active = true
            ORDER BY days_until_stockout ASC NULLS LAST
        """),
        {"tid": tid, "forecast_days": forecast_days},
    )

    items = []
    risk_summary = {"critical": 0, "warning": 0, "watch": 0, "ok": 0}
    for row in result.mappings():
        d = row["days_until_stockout"]
        if d is not None and d < 3:
            risk = "critical"
        elif d is not None and d < 7:
            risk = "warning"
        elif d is not None and d < forecast_days:
            risk = "watch"
        else:
            risk = "ok"
        risk_summary[risk] += 1
        items.append(StockForecastItem(
            variant_id=row["variant_id"],
            product_id=row["product_id"],
            variant_title=row["variant_title"] or "",
            product_name=row["product_name"] or "",
            available_stock=row["available_stock"],
            avg_daily_sales=round(row["avg_daily_sales"], 2),
            days_until_stockout=d,
            forecasted_demand=row["forecasted_demand"] or 0,
            risk=risk,
        ))

    return StockForecastResponse(forecast_days=forecast_days, items=items, risk_summary=risk_summary)


# ── Revenue by Day ────────────────────────────────────────────────────


@router.get("/revenue")
async def get_revenue_by_day(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Daily revenue from non-cancelled orders."""
    tid = str(user.tenant_id)
    result = await db.execute(
        text("""
            SELECT
                DATE(created_at) AS day,
                COUNT(*)::int AS orders,
                COALESCE(SUM(total_amount), 0)::float AS revenue
            FROM orders
            WHERE tenant_id = :tid
              AND status NOT IN ('draft', 'cancelled')
              AND created_at >= now() - make_interval(days => :days)
            GROUP BY DATE(created_at)
            ORDER BY day
        """),
        {"tid": tid, "days": days},
    )
    rows = [{"date": str(r[0]), "orders": r[1], "revenue": r[2]} for r in result.fetchall()]

    total_revenue = sum(r["revenue"] for r in rows)
    total_orders = sum(r["orders"] for r in rows)
    return {
        "days": days,
        "daily": rows,
        "total_revenue": total_revenue,
        "total_orders": total_orders,
    }


# ── Competitor Analysis ────────────────────────────────────────────────


@router.post("/competitors", response_model=CompetitorPriceOut, status_code=201)
@limiter.limit("30/minute")
async def add_competitor_price(
    request: Request,
    body: CompetitorPriceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Add a competitor price entry."""
    entry = CompetitorPrice(
        tenant_id=user.tenant_id,
        product_id=body.product_id,
        competitor_name=body.competitor_name,
        competitor_channel=body.competitor_channel,
        product_title=body.product_title,
        competitor_price=body.competitor_price,
        our_price=body.our_price,
        currency=body.currency,
        source="manual",
    )
    db.add(entry)
    await db.flush()
    return CompetitorPriceOut.model_validate(entry)


@router.get("/competitors", response_model=list[CompetitorPriceOut])
async def list_competitor_prices(
    product_id: UUID | None = None,
    competitor_name: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List competitor price entries."""
    from src.analytics.models import CompetitorPrice
    q = select(CompetitorPrice).where(CompetitorPrice.tenant_id == user.tenant_id)
    if product_id:
        q = q.where(CompetitorPrice.product_id == product_id)
    if competitor_name:
        q = q.where(CompetitorPrice.competitor_name.ilike(f"%{competitor_name}%"))
    q = q.order_by(CompetitorPrice.captured_at.desc()).limit(limit).offset(offset)

    result = await db.execute(q)
    rows = result.scalars().all()
    return [CompetitorPriceOut.model_validate(r) for r in rows]


@router.get("/competitors/summary", response_model=list[CompetitorSummary])
async def get_competitor_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Price comparison summary per competitor."""
    tid = str(user.tenant_id)
    result = await db.execute(
        text("""
            SELECT
                competitor_name,
                COUNT(*)::int AS products_tracked,
                AVG(CASE WHEN our_price > 0 THEN (competitor_price - our_price) / our_price * 100 END)::float AS avg_price_diff_pct,
                COUNT(*) FILTER (WHERE competitor_price < our_price)::int AS cheaper_count,
                COUNT(*) FILTER (WHERE competitor_price > our_price)::int AS more_expensive_count
            FROM competitor_prices
            WHERE tenant_id = :tid AND captured_at >= now() - interval '30 days'
            GROUP BY competitor_name
            ORDER BY products_tracked DESC
        """),
        {"tid": tid},
    )
    return [CompetitorSummary(**dict(r)) for r in result.mappings()]


# ── AI Insights ───────────────────────────────────────────────────────


@router.get("/ai-insights")
@limiter.limit("30/minute")
async def get_ai_insights(
    request: Request,
    days: int = Query(30, ge=7, le=90),
    refresh: bool = Query(False, description="Force regeneration (ignore cache)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate AI-powered business insights from analytics data.

    Results are cached in Redis for 1 hour per tenant+days.
    Pass ?refresh=true to force regeneration.
    """
    import json as _json
    import openai
    from src.core.config import settings as app_settings
    from src.core.security import _redis

    tid = str(user.tenant_id)
    cache_key = f"ai_insights:{tid}:{days}"

    # For refresh=true (actual OpenAI generation): enforce stricter per-tenant limit
    if refresh:
        try:
            gen_key = f"ai_insights_gen:{tid}"
            gen_count = await _redis.incr(gen_key)
            if gen_count == 1:
                await _redis.expire(gen_key, 600)  # 10-minute window
            if gen_count > 5:
                raise HTTPException(status_code=429, detail="Лимит генерации: 5 раз за 10 минут. Попробуйте позже.")
        except HTTPException:
            raise
        except Exception:
            pass  # fail-open if Redis unavailable

    # Return cached insights if available and not forced refresh
    if not refresh:
        try:
            cached = await _redis.get(cache_key)
            if cached:
                return _json.loads(cached)
        except Exception:
            pass  # fail-open
        # No cache and no refresh — return empty (don't generate on page load)
        return None

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Gather data in parallel-ish (sequential but fast — all indexed queries)
    # 1) Revenue summary
    rev = await db.execute(text("""
        SELECT COUNT(*)::int AS orders, COALESCE(SUM(total_amount),0)::float AS revenue,
               COALESCE(AVG(total_amount),0)::float AS avg_check
        FROM orders WHERE tenant_id = :tid AND status NOT IN ('draft','cancelled') AND created_at >= :since
    """), {"tid": tid, "since": since})
    rev_data = dict(rev.mappings().first() or {})

    # Previous period for comparison
    prev_since = since - timedelta(days=days)
    prev_rev = await db.execute(text("""
        SELECT COUNT(*)::int AS orders, COALESCE(SUM(total_amount),0)::float AS revenue
        FROM orders WHERE tenant_id = :tid AND status NOT IN ('draft','cancelled')
          AND created_at >= :prev_since AND created_at < :since
    """), {"tid": tid, "prev_since": prev_since, "since": since})
    prev_data = dict(prev_rev.mappings().first() or {})

    # 2) Conversation stats
    conv = await db.execute(text("""
        SELECT COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE state = 'post_order')::int AS converted,
               COUNT(*) FILTER (WHERE status = 'handoff')::int AS handoffs
        FROM conversations WHERE tenant_id = :tid AND source_type = 'dm' AND created_at >= :since
    """), {"tid": tid, "since": since})
    conv_data = dict(conv.mappings().first() or {})

    # 3) Top products
    top_products = await db.execute(text("""
        SELECT p.name, SUM(oi.qty)::int AS sold, SUM(oi.total_price)::float AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN product_variants pv ON pv.id = oi.product_variant_id
        JOIN products p ON p.id = pv.product_id
        WHERE o.tenant_id = :tid AND o.status NOT IN ('draft','cancelled') AND o.created_at >= :since
        GROUP BY p.name ORDER BY revenue DESC LIMIT 5
    """), {"tid": tid, "since": since})
    top_prods = [dict(r) for r in top_products.mappings()]

    # 4) Stock alerts
    stock_alerts = await db.execute(text("""
        SELECT p.name, pv.title, (i.quantity - i.reserved_quantity)::int AS stock
        FROM inventory i
        JOIN product_variants pv ON pv.id = i.variant_id
        JOIN products p ON p.id = pv.product_id
        WHERE i.tenant_id = :tid AND pv.is_active = true AND (i.quantity - i.reserved_quantity) <= 3
        ORDER BY stock ASC LIMIT 10
    """), {"tid": tid})
    low_stock = [dict(r) for r in stock_alerts.mappings()]

    # 5) RFM summary
    rfm = await db.execute(text("""
        SELECT segment, COUNT(*)::int AS cnt FROM customer_segments WHERE tenant_id = :tid GROUP BY segment
    """), {"tid": tid})
    rfm_data = {r.segment: r.cnt for r in rfm}

    # 6) Handoff reasons
    handoff_reasons = await db.execute(text("""
        SELECT reason, COUNT(*)::int AS cnt FROM handoffs
        WHERE tenant_id = :tid AND created_at >= :since
        GROUP BY reason ORDER BY cnt DESC LIMIT 5
    """), {"tid": tid, "since": since})
    handoff_data = [dict(r) for r in handoff_reasons.mappings()]

    # Build context for GPT
    conversion_rate = round(conv_data.get("converted", 0) / conv_data.get("total", 1) * 100, 1) if conv_data.get("total") else 0
    prev_rev = prev_data.get("revenue", 0) or 0
    if prev_rev > 0:
        rev_change = round((rev_data.get("revenue", 0) - prev_rev) / prev_rev * 100, 1)
        rev_change = max(min(rev_change, 9999.9), -100.0)  # cap at ±9999.9%
    elif rev_data.get("revenue", 0) > 0:
        rev_change = None  # new revenue, no prior baseline
    else:
        rev_change = 0.0

    data_summary = f"""
Период: последние {days} дней

ВЫРУЧКА:
- Заказов: {rev_data.get('orders', 0) or 0}, выручка: {(rev_data.get('revenue', 0) or 0):,.0f} сум, средний чек: {(rev_data.get('avg_check', 0) or 0):,.0f} сум
- Прошлый период: {prev_data.get('orders', 0) or 0} заказов, {(prev_data.get('revenue', 0) or 0):,.0f} сум
- Изменение выручки: {f'{rev_change:+.1f}%' if rev_change is not None else 'нет данных за прошлый период (первые продажи)'}

КОНВЕРСИЯ:
- Всего диалогов: {conv_data.get('total', 0)}, конвертировано: {conv_data.get('converted', 0)} ({conversion_rate}%)
- Передач оператору: {conv_data.get('handoffs', 0)}

ТОП ТОВАРЫ (по выручке):
{chr(10).join(f'- {p["name"]}: {p["sold"]} шт, {p["revenue"]:,.0f} сум' for p in top_prods) if top_prods else '- Нет данных'}

НИЗКИЙ ОСТАТОК:
{chr(10).join(f'- {s["name"]} ({s["title"]}): {s["stock"]} шт' for s in low_stock) if low_stock else '- Все в норме'}

RFM СЕГМЕНТЫ:
{chr(10).join(f'- {seg}: {cnt} клиентов' for seg, cnt in rfm_data.items()) if rfm_data else '- Не рассчитано'}

ПРИЧИНЫ HANDOFF:
{chr(10).join(f'- {h["reason"]}: {h["cnt"]} раз' for h in handoff_data) if handoff_data else '- Нет данных'}
"""

    client = openai.AsyncOpenAI(api_key=app_settings.openai_api_key)
    try:
        response = await client.chat.completions.create(
            model=app_settings.openai_model_main,
            messages=[
                {"role": "system", "content": """Ты — аналитик электронной коммерции для Telegram-магазина в Узбекистане. Анализируй данные и давай конкретные, actionable инсайты.

Формат ответа — JSON массив объектов:
[
  {"type": "growth|warning|opportunity|action", "title": "Краткий заголовок", "text": "Подробное объяснение с цифрами", "priority": "high|medium|low"}
]

Правила:
- 4-6 инсайтов, каждый с конкретными цифрами
- Сравнивай текущий период с прошлым
- Укажи что растёт, что падает, что требует внимания
- Давай конкретные рекомендации (какой товар продвигать, что заказать, кого вернуть)
- Используй валюту "сум" (Узбекистан)
- Пиши на русском языке, кратко и по делу"""},
                {"role": "user", "content": data_summary},
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        import json
        raw = response.choices[0].message.content.strip()
        # Strip markdown code block if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        insights = json.loads(raw)
    except Exception as e:
        logger.error("AI insights generation failed: %s", e)
        insights = [{"type": "warning", "title": "Не удалось сгенерировать инсайты", "text": str(e)[:200], "priority": "low"}]

    result = {
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "insights": insights,
        "data_summary": {
            "revenue": rev_data.get("revenue", 0) or 0,
            "revenue_change_pct": rev_change,
            "orders": rev_data.get("orders", 0) or 0,
            "avg_check": rev_data.get("avg_check", 0) or 0,
            "conversations": conv_data.get("total", 0) or 0,
            "conversion_rate": conversion_rate,
            "handoffs": conv_data.get("handoffs", 0) or 0,
        },
    }

    # Cache for 1 hour
    try:
        await _redis.setex(cache_key, 3600, _json.dumps(result, default=str))
    except Exception:
        pass  # fail-open

    return result


@router.delete("/competitors/{entry_id}")
@limiter.limit("20/minute")
async def delete_competitor_price(
    request: Request,
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Delete a competitor price entry."""
    result = await db.execute(
        select(CompetitorPrice).where(
            CompetitorPrice.id == entry_id,
            CompetitorPrice.tenant_id == user.tenant_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(entry)
    return {"status": "deleted"}
