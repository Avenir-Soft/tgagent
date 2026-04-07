"""Analytics router — RFM segmentation, conversation metrics, funnel, stock forecast, competitors."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_current_user, require_store_owner
from src.auth.models import User
from src.core.database import get_db
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
async def compute_rfm(
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

    for row in rows:
        await db.execute(upsert_query, {"tid": tid, **dict(row)})

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

    # Avg & median response time
    rt_result = await db.execute(
        text("""
            WITH pairs AS (
                SELECT
                    m1.conversation_id,
                    m1.created_at AS customer_at,
                    (SELECT MIN(m2.created_at) FROM messages m2
                     WHERE m2.conversation_id = m1.conversation_id
                       AND m2.created_at > m1.created_at
                       AND m2.direction = 'outbound') AS response_at
                FROM messages m1
                WHERE m1.tenant_id = :tid
                  AND m1.direction = 'inbound'
                  AND m1.created_at >= :since
            )
            SELECT
                AVG(EXTRACT(EPOCH FROM (response_at - customer_at)))::float AS avg_rt,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (response_at - customer_at)))::float AS median_rt
            FROM pairs
            WHERE response_at IS NOT NULL
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
    resolved_result = await db.execute(
        text("""
            SELECT COUNT(*)::int AS cnt FROM conversations c
            WHERE c.tenant_id = :tid AND c.source_type = 'dm' AND c.created_at >= :since
              AND (c.state = 'post_order' OR EXISTS (
                  SELECT 1 FROM leads l JOIN orders o ON o.lead_id = l.id
                  WHERE l.telegram_user_id = c.telegram_user_id AND l.tenant_id = :tid
                    AND o.status IN ('confirmed','processing','shipped','delivered')
              ))
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
    forecast_days: int = Query(14, ge=1, le=60),
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
async def add_competitor_price(
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


@router.delete("/competitors/{entry_id}")
async def delete_competitor_price(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_store_owner),
):
    """Delete a competitor price entry."""
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(CompetitorPrice).where(
            CompetitorPrice.id == entry_id,
            CompetitorPrice.tenant_id == user.tenant_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(entry)
    return {"status": "deleted"}
