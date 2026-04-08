"""Analytics Pydantic schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


# --- RFM / Customer Segmentation ---

class CustomerSegmentOut(BaseModel):
    lead_id: UUID
    customer_name: str | None
    telegram_user_id: int
    recency_days: int
    frequency: int
    monetary: Decimal
    r_score: int
    f_score: int
    m_score: int
    rfm_score: int
    segment: str

    model_config = {"from_attributes": True}


class RFMSummary(BaseModel):
    segments: dict[str, int]
    total_customers: int
    top_customers: list[CustomerSegmentOut]


# --- Conversation Analytics ---

class DailyTrend(BaseModel):
    date: str
    conversations: int
    resolved: int


class ConversationAnalytics(BaseModel):
    period_days: int
    avg_response_time_seconds: float | None
    median_response_time_seconds: float | None
    resolution_rate_pct: float
    handoff_rate_pct: float
    total_conversations: int
    messages_by_sender: dict[str, int]
    daily_trend: list[DailyTrend]


# --- Funnel ---

class FunnelStage(BaseModel):
    name: str
    label: str
    count: int
    pct: float | None = None


class FunnelResponse(BaseModel):
    period_days: int
    stages: list[FunnelStage]


# --- Stock Forecast ---

class StockForecastItem(BaseModel):
    variant_id: UUID
    product_id: UUID | None = None
    variant_title: str
    product_name: str
    available_stock: int
    avg_daily_sales: float
    days_until_stockout: int | None
    forecasted_demand: int
    risk: str  # critical, warning, watch, ok


class StockForecastResponse(BaseModel):
    forecast_days: int
    items: list[StockForecastItem]
    risk_summary: dict[str, int]


# --- Competitors ---

class CompetitorPriceCreate(BaseModel):
    product_id: UUID | None = None
    competitor_name: str
    competitor_channel: str | None = None
    product_title: str
    competitor_price: Decimal
    our_price: Decimal | None = None
    currency: str = "UZS"


class CompetitorPriceOut(BaseModel):
    id: UUID
    product_id: UUID | None
    competitor_name: str
    competitor_channel: str | None
    product_title: str
    competitor_price: Decimal
    our_price: Decimal | None
    currency: str
    source: str
    captured_at: datetime

    model_config = {"from_attributes": True}


class CompetitorSummary(BaseModel):
    competitor_name: str
    products_tracked: int
    avg_price_diff_pct: float | None
    cheaper_count: int
    more_expensive_count: int
