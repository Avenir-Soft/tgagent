# AI Closer — Universal AI Sales Agent Platform

Multi-tenant SaaS платформа — ИИ-продавец для любого бизнеса через Telegram. Работает через **реальный Telegram аккаунт** (MTProto/Telethon), НЕ бот.

## Текущий статус (April 2026)
- **v2.0** branch — production-ready
- **81 API тестов** — all passing
- **Ultrareview**: 0 bugs (clean)
- **Technical audit**: 6 HIGH fixed, 18 MEDIUM fixed, 8 LOW fixed
- **Vector search**: pgvector + OpenAI embeddings (hybrid with ILIKE)
- **Super Admin Platform**: 8 pages, full management
- **Per-tenant API keys**: encrypted (Fernet), OpenAI + Anthropic
- **Audit logging**: 36 action types across all modules
- **Platform settings enforcement**: maintenance_mode, read_only, limits

## Mindset при работе с кодом

> **Правило:** Когда меняешь что-то — проверяй ВСЁ, что с этим связано.

1. **Grep перед фиксом** — найди все места где используется переменная/паттерн. Не чини одно место, если их 5.
2. **Cascade check** — повлияет ли изменение на другие модули? Если менял schema — проверь router. Если менял model — проверь schema + router + frontend.
3. **Consistency** — если создал `safe_phone` из `phone_number`, используй `safe_phone` ВЕЗДЕ дальше (БД, session ref, логи). Не миксуй сырое и чистое.
4. **Будущие баги** — подумай: "а что будет через полгода когда будет 100k чатов / 50k заказов / 1000 товаров?" Memory leaks, N+1 queries, unbounded lists.
5. **Не ломай работающее** — если фиксишь баг в одной функции, проверь что аналогичные функции рядом не имеют такой же проблемы.

Полный аудит багов и TODO → `~/Desktop/AI_CLOSER_AUDIT_2.0.md`

## Стек

- **Backend**: FastAPI + async SQLAlchemy 2.x + PostgreSQL (asyncpg)
- **Frontend**: Next.js 15 (App Router, React 19) + Tailwind CSS
- **Real-time**: SSE (Server-Sent Events) via Redis pub/sub — заменил polling
- **Telegram**: Telethon (MTProto) — подключается как пользовательский аккаунт
- **AI**: OpenAI + Anthropic (per-tenant provider), function calling (tools), vector search (pgvector)
- **Search**: Hybrid — pgvector semantic + ILIKE exact (aliases), Redis-cached embeddings
- **Auth**: JWT + bcrypt + Redis token blacklist + SSE short-lived tokens + Fernet API key encryption
- **Retry**: tenacity (OpenAI), custom retry (Telegram FloodWait)
- **Testing**: pytest + aiohttp (81 comprehensive API tests)
- **Git**: `v2.0` branch, remote `Avenir-Soft/tgagent`

## Как запустить

### Backend
```bash
cd "tg agent"
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# PostgreSQL должен быть запущен
# Создать БД: createdb ai_closer
# Скопировать .env.example → .env и заполнить

uvicorn src.main:app --reload --reload-dir src --host 127.0.0.1 --port 8000
```

**Для доступа с другого устройства в сети** (ПК, телефон):
```bash
# Бэк на 0.0.0.0
uvicorn src.main:app --reload --reload-dir src --host 0.0.0.0 --port 8000

# Фронт на 0.0.0.0
cd frontend && NEXT_PUBLIC_API_URL=http://<LOCAL_IP>:8000 npm run dev -- -H 0.0.0.0

# Добавить IP в CORS: src/core/config.py → cors_origins
# Открыть: http://<LOCAL_IP>:3000
```

**Убить бэк:** `lsof -ti :8000 | xargs kill -9`

### Frontend
```bash
cd frontend
npm install
npm run dev  # порт 3000
```

### Seed данные
```bash
python scripts/seed.py
```
Создаёт демо-тенант "TechnoUz Demo Store" с 22 товарами электроники, 34 вариантами, 261 алиасом (включая кириллицу, ошибки, категорийные), 5 правилами доставки, 3 шаблонами комментариев.

### Логины
- `admin@gmail.com` / `admin123` — store_owner (основной рабочий аккаунт)
- `superadmin@gmail.com` / `admin123` — super_admin (platform admin)
- `admin@technouz-demo.com` / `admin123` — super_admin (seed)
- TechnoUz Tenant ID: `a7b1be91-b75f-4088-848a-22705b44b1b2`
- Easy Tour Tenant ID: `ed0342b5-a5b6-4013-9686-6e2717ee18e6`

### Тесты
```bash
# Запуск всех тестов (81 тест, бэк должен работать на :8001)
pytest tests/test_api_comprehensive.py -v

# Backfill embeddings для vector search
python scripts/backfill_embeddings.py
```

## Архитектура

### Multi-tenant
- Все таблицы имеют `tenant_id` (UUID), **кроме** `order_items` (только `order_id` с CASCADE)
- Все запросы фильтруются по `tenant_id` текущего пользователя
- Один тенант = один магазин

### Структура бэкенда (`src/`)
```
src/
├── main.py              # FastAPI app, startup (Telegram clients, scheduled broadcasts, draft cleanup, SSE cleanup)
├── core/
│   ├── config.py        # Settings (из .env), CORS origins
│   ├── database.py      # async SQLAlchemy engine + session
│   ├── models.py        # PkMixin, TenantMixin, TimestampMixin, UpdatableMixin
│   ├── security.py      # JWT encode/decode, bcrypt, Redis token blacklist, media tokens
│   └── rate_limit.py    # slowapi limiter
├── auth/
│   ├── models.py        # User (NOT Tenant — Tenant in tenants/models.py)
│   ├── router.py        # POST /auth/login, /auth/logout, /auth/change-password
│   ├── deps.py          # get_current_user (+ blacklist check), require_store_owner, require_operator
│   └── schemas.py
├── tenants/
│   ├── models.py        # Tenant (relationship → users, telegram_accounts)
│   ├── router.py        # CRUD tenants (super_admin only)
│   └── schemas.py
├── catalog/
│   ├── models.py        # Category, Product, ProductVariant, ProductAlias, ProductMedia, Inventory, DeliveryRule
│   ├── router.py        # CRUD products/variants/aliases/media/categories/delivery-rules + CSV import
│   └── schemas.py       # ProductDetailOut, DeliveryRuleUpdate
├── conversations/
│   ├── models.py        # CommentTemplate, Conversation (is_training_candidate, state_context JSONB), Message
│   ├── router.py        # Thin HTTP handlers — delegates to service.py
│   ├── service.py       # Business logic: enriched listing, customer history, reset, cascade delete, operator messaging
│   └── schemas.py       # MessageEdit, MessageSend, BroadcastRequest, TrainingLabelUpdate
├── leads/
│   ├── models.py        # Lead (telegram_username, customer_name auto-filled from TG)
│   └── router.py
├── orders/
│   ├── models.py        # Order, OrderItem (NO tenant_id!)
│   ├── router.py        # Thin HTTP handlers — delegates to service.py
│   ├── service.py       # Business logic: create/update order, validation, inventory, TG notifications
│   └── schemas.py       # OrderCreate (validated: items≥1, qty≥1, prices≥0, name/phone length)
├── telegram/
│   ├── models.py        # TelegramAccount, TelegramDiscussionGroup
│   ├── router.py        # send-code, verify-code (sanitized phone), accounts, status, reconnect, activity-logs, media proxy
│   └── service.py       # TelegramClientManager: DM handling + read receipts + human-like typing + debounce + entity resolution + SSE emission
├── ai/
│   ├── orchestrator.py  # process_dm_message() — координатор, делегирует в модули ниже
│   ├── prompt_builder.py # Builds system prompt: base + state section + settings + context
│   ├── tool_executor.py # Multi-round tool calling dispatcher (до 3 раундов)
│   ├── guards.py        # Hallucination guards: cart claims, price/spec fabrication, language mismatch
│   ├── photo_handler.py # GPT-4o Vision для фото от клиентов
│   ├── truth_tools.py   # 16 tool functions (включая request_return)
│   ├── policies.py      # Codified business rules — can_cancel, can_edit, can_return, get_allowed_actions, next_state
│   ├── prompts.py       # State-aware system prompts (STATE_PROMPTS)
│   ├── language.py      # Language detection + post-processing (ru/uz_cyrillic/uz_latin/en)
│   ├── preprocessor.py  # Order pre-processor (deterministic, before LLM) + handoff flush
│   ├── responses.py     # Forced response templates
│   ├── state_manager.py # State context management, proactive suggestions
│   ├── anomaly.py       # Anomaly detection (6 failure types → training candidates)
│   ├── context_schema.py # JSONB schema for state_context
│   ├── models.py        # AiSettings (14 settings — all enforced at runtime)
│   ├── router.py        # GET/PUT /ai-settings, test notification, reset
│   └── schemas.py
├── sse/
│   ├── event_bus.py     # Redis pub/sub: publish_event(), subscribe(), close_event_bus()
│   └── router.py        # GET /events/stream — SSE endpoint with JWT auth, keepalive, token re-validation
├── dashboard/
│   ├── models.py        # BroadcastHistory
│   ├── router.py        # Thin HTTP handlers — delegates to service.py
│   ├── service.py       # Business logic: stats, broadcast, cart recovery, draft cleanup
│   └── schemas.py
├── training/
│   └── router.py        # stats, conversations (batch aggregation), label, smart-label (GPT-4o), export JSONL, fine-tune
├── analytics/
│   ├── models.py        # CustomerSegment, CompetitorPrice
│   ├── router.py        # RFM segmentation, conversation metrics, funnel, stock-forecast, revenue, competitors
│   └── schemas.py
├── handoffs/
│   ├── models.py        # Handoff (summary, linked_order_id, resolution_notes)
│   ├── router.py        # list + update (with assigned_to_user_name enrichment)
│   └── schemas.py       # HandoffOut has assigned_to_user_name, resolution_notes
└── import_data/
    └── router.py        # Bulk import products
```

### Service Layer Pattern
Роутеры — тонкие HTTP-обработчики, бизнес-логика в `service.py`:
- `orders/router.py` (123 строк) → `orders/service.py` (330 строк)
- `conversations/router.py` (370 строк) → `conversations/service.py` (382 строк)
- `dashboard/router.py` (289 строк) → `dashboard/service.py` (442 строк)

Роутер только: парсит запрос, проверяет auth, вызывает сервис, возвращает ответ. Вся логика (валидация, уведомления, inventory, cascade delete) — в сервисе.

### SSE (Server-Sent Events) — real-time
Заменяет polling. Redis pub/sub для доставки событий между процессами.

**Каналы:**
- `sse:{tenant_id}:tenant` — события уровня тенанта (новые диалоги, заказы)
- `sse:{tenant_id}:conversation:{id}` — события конкретного диалога (новые сообщения)

**Endpoint:** `GET /events/stream?token=JWT&conversation_id=UUID`
- JWT через query param (EventSource не поддерживает заголовки)
- Keepalive каждые 15 сек
- Re-validation токена каждые 5 мин
- Named SSE events: `new_message`, `conversation_updated`, `new_conversation`, `order_status_changed`, `auth_expired`

**Точки эмиссии событий:**
- `telegram/service.py` — после входящего сообщения + после ответа AI
- `conversations/router.py` — после отправки оператором
- `orders/service.py` — после смены статуса заказа

**Frontend:** `useEventSource` hook (`lib/use-event-source.ts`)
- Chat: SSE + 30s fallback polling
- Conversations list: SSE с debounce 500ms + 30s fallback
- Dashboard: SSE с debounce 1s + 60s fallback

### Как работает AI агент

1. Пользователь пишет в DM Telegram аккаунту магазина
2. Telethon получает сообщение → `telegram/service.py` (debounce 3.5s для быстрых сообщений)
3. **Per-conversation lock** (`asyncio.Lock`) — предотвращает race condition
4. **Read receipt** (✓✓) — `send_read_acknowledge()` мгновенно
5. **"Reading" пауза** (1.5–3.5с) — пропорционально длине сообщения, имитация чтения
6. **Typing анимация** (`SetTypingRequest`) — показывает "печатает..." пока AI думает
7. Вызывается `orchestrator.process_dm_message(tenant_id, conversation_id, user_message, db)`
8. **Kill switch** — если `allow_auto_dm_reply=False`, return None (AI молчит)
9. **Order pre-processor** (`preprocessor.py`) — детерминированная проверка заказов ДО вызова LLM
10. **System prompt** (`prompt_builder.py`) — base + state section + AI settings + context
11. **Tool execution** (`tool_executor.py`) — multi-round tool calling (до 3 раундов) с retry (tenacity)
12. **Hallucination guards** (`guards.py`) — cart claims, price/spec fabrication, language mismatch
13. **State transition** — после каждого tool call через `policies.next_state()`
14. **Forced responses** (`responses.py`) — для add/remove_item, locked orders, returns — ответ кодом
15. **Language post-processing** (`language.py`) — детект и коррекция языка (ru↔uz_cyrillic↔uz_latin)
16. **Anomaly detection** (`anomaly.py`) — 6 типов ошибок → training candidate
17. **Typing delay** пропорционально длине ответа (1–6 сек) — имитация набора
18. Ответ отправляется с retry (FloodWait handling), `telegram_message_id` сохраняется
19. **SSE emission** — `publish_event()` уведомляет фронтенд о новом сообщении в реальном времени
20. **Fallback mode** — при ошибке AI: попытка fallback model (gpt-4o) или создание handoff

**AI модули** (бывший God Object orchestrator.py 1665 строк → 7 модулей):
| Модуль | Ответственность |
|---|---|
| `orchestrator.py` | Координатор — делегирует в модули |
| `prompt_builder.py` | Сборка system prompt |
| `tool_executor.py` | Диспетчер tool calls (multi-round) |
| `guards.py` | Проверка галлюцинаций |
| `photo_handler.py` | GPT-4o Vision для фото |
| `preprocessor.py` | Детерминированная обработка заказов до LLM |
| `responses.py` | Шаблоны принудительных ответов |

### Telethon Entity Resolution (важный паттерн!)
После перезапуска сервера Telethon не имеет entity пользователей в кэше. Все исходящие отправки (broadcast, operator reply, notifications) используют паттерн:
```python
try:
    entity = await client.get_input_entity(chat_id)
except ValueError:
    if username:
        entity = await client.get_input_entity(username)
    else:
        raise
await client.send_message(entity, text)
```
Это НЕ нужно для `event.respond()` / `event.reply()` — они уже имеют entity из входящего сообщения.

### Human-like Telegram поведение
```
Клиент отправил → ✓✓ мгновенно → пауза 1.5-3.5с ("читает") → typing... → AI думает → typing ещё 1-6с → отправка
```
- Typing через `SetTypingRequest` (НЕ `client.action()` — он не отправляет, только создаёт объект!)
- Read receipt через `client.send_read_acknowledge(chat_id)`
- Задержки пропорциональны длине: короткий "привет" → 1.5с+1с, длинный вопрос → 3.5с+6с

### Order Pre-Processor
Детерминированная обработка заказов **ДО** вызова LLM:

| Ситуация | Действие |
|---|---|
| Заказ не найден | Forced: "Заказ не найден. Проверьте номер" |
| Чужой заказ | Forced: "Заказ не найден" (не раскрывает!) |
| Locked (cancelled/shipped/delivered/returned) + "изменить" | Forced: "Статус X — изменения невозможны" |
| Processing + "изменить" | Forced: создаёт handoff + `await db.flush()` + "Подключу оператора" |
| Draft/Confirmed + "изменить" | Inject: передаёт в LLM с инфой |
| Просто номер / статус | Inject: передаёт в LLM |

### Conversation State Machine
`idle → browsing → selection → cart → checkout → post_order → handoff`

### Policy Layer (`src/ai/policies.py`)
- `AI_EDITABLE_STATUSES` = {"draft", "confirmed"}
- `OPERATOR_REQUIRED_STATUSES` = {"processing"}
- `LOCKED_STATUSES` = {"shipped", "delivered", "cancelled", "returned"}
- `RETURNABLE_STATUSES` = {"delivered"}
- `can_cancel_order(status)`, `can_edit_order(status)`, `can_return_order(status)`, `get_allowed_actions(status)`, `next_state(current, tool_name)`

### AI Tools (16 функций)
`list_categories`, `get_product_candidates`, `get_variant_candidates`, `get_variant_price`, `get_variant_stock`, `get_delivery_options`, `get_customer_history`, `select_for_cart`, `remove_from_cart`, `create_order_draft`, `check_order_status`, `cancel_order`, `add_item_to_order`, `remove_item_from_order`, `request_handoff`, `request_return`

### AI Settings (14 — все работают)
| Setting | Тип | Где проверяется |
|---|---|---|
| `allow_auto_dm_reply` | bool | orchestrator.py — kill switch (Step 0.95) |
| `allow_auto_comment_reply` | bool | service.py — comment handler |
| `allow_ai_cancel_draft` | bool | truth_tools.py — cancel_order |
| `require_operator_for_edit` | bool | orchestrator.py — order preprocessor |
| `require_handoff_for_unknown_product` | bool | orchestrator.py — get_product_candidates hint |
| `max_variants_in_reply` | int | orchestrator.py — get_variant_candidates trim |
| `confirm_before_order` | bool | orchestrator.py — system prompt injection |
| `tone` | str | orchestrator.py — system prompt injection |
| `language` | str | orchestrator.py — default language for new chats |
| `fallback_mode` | str | orchestrator.py — "handoff" or "fallback_model" |
| `channel_show_price` | bool | service.py — comment reply with price range |
| `operator_telegram_username` | str | orchestrator.py — handoff notification |
| `operator_notification_enabled` | bool | orchestrator.py — send TG notification to operator |
| `auto_handoff_on_negative_sentiment` | bool | orchestrator.py — sentiment detection |

### Frontend Design System
- **Palette**: slate grays, indigo primary, violet accent, emerald success, amber warning, rose error
- **Dark mode**: CSS-global-override в `globals.css` (~150 lines), `lib/theme.ts`, FOUC prevention в `layout.tsx`
- **Cards**: `.card` CSS class (`bg-white rounded-xl border border-slate-200/60 shadow-sm`)
- **Sidebar**: dark gradient (slate-900 to slate-950), 13 SVG icons, 5 nav groups, moon/sun toggle
- **Login**: glassmorphism (`bg-white/[0.07] backdrop-blur-xl`)
- **Animations**: slide-up, fade-in, shimmer (skeleton), pulse-soft
- **Error boundaries**: `app/error.tsx` (global) + `app/(admin)/error.tsx` (admin routes)
- **Auth guard**: admin layout blocks render until `isAuthenticated()` returns true

### Frontend страницы (15)
- `/login` — glassmorphism авторизация
- `/dashboard` — KPI stats + bar chart (SSE real-time updates, 60s fallback)
- `/products` — список (категория, цена range, наличие badge, варианты count)
- `/products/[id]` — детали (варианты таблица + алиасы + media + sales)
- `/conversations` — карточки диалогов (SSE real-time, debounce 500ms, 30s fallback)
- `/conversations/[id]` — чат (SSE real-time messages, bubble UI, date separators, edit, operator reply, handoff banner, media preview, anomaly navigation, message search)
- `/leads` — карточки лидов (аватар, имя, @username, phone, city, status)
- `/orders` — expandable карточки (items list, delivery, summary)
- `/delivery` — правила (group by city, filter, CSV import, edit, delete)
- `/telegram` — подключение (status polling, reconnect, activity logs)
- `/templates` — шаблоны комментариев
- `/settings` — AI настройки (14 toggles/dropdowns, operator TG username, test notification)
- `/handoffs` — карточки (priority badge, summary, linked order, filter, "Решено")
- `/broadcast` — рассылка (audience estimate, 5000 cap warning, scheduled, history, image, abandoned carts)
- `/training` — обучение AI (label messages, smart-label GPT-4o, export JSONL, fine-tune)
- `/analytics` — RFM, funnel, revenue, stock-forecast, competitors

### API endpoints (ключевые)
```
# Auth
POST /auth/login, POST /auth/logout, GET /auth/me, POST /auth/change-password

# Catalog (NO prefix — routes at root)
GET/POST /products, GET/PATCH /products/{id}
GET/POST /products/{id}/variants, PATCH /variants/{id}, DELETE /variants/{id}
GET/POST /products/{id}/aliases, DELETE /aliases/{id}
GET/POST /products/{id}/media, DELETE /media/{id}
GET /products/{id}/sales
GET/POST /categories
GET/POST /delivery-rules, PATCH/DELETE /delivery-rules/{id}, POST /delivery-rules/import-csv
PUT /inventory/{id}

# Conversations (prefix /conversations)
GET /conversations, GET/DELETE /conversations/{id}
GET /conversations/{id}/messages, POST /conversations/{id}/messages (operator reply)
PATCH /conversations/{id}/toggle-ai, PATCH /conversations/{id}/messages/{msg_id} (edit)
POST /conversations/{id}/reset
GET/POST/PATCH/DELETE /conversations/templates (shares prefix — routes before {id})

# Orders (prefix /orders)
GET/POST /orders, GET /orders/{id}, PATCH /orders/{id} (status → TG notification)

# Leads (prefix /leads)
GET/PATCH /leads

# Handoffs (prefix /handoffs)
GET /handoffs, PATCH /handoffs/{id}

# Telegram (prefix /telegram)
GET /telegram/accounts, POST /telegram/send-code, POST /telegram/verify-code
DELETE /telegram/accounts/{id}, GET /telegram/status, POST /telegram/accounts/{id}/reconnect
GET /telegram/activity-logs

# AI Settings
GET/PUT /ai-settings, POST /ai-settings/test-notification, POST /ai-settings/reset

# Dashboard (prefix /dashboard)
GET /dashboard/stats, GET/POST /dashboard/broadcast, GET /dashboard/broadcast-estimate
GET /dashboard/broadcast-recipients, GET /dashboard/broadcast-history, DELETE /dashboard/broadcast-history/{id}
POST /dashboard/abandoned-carts/{id}/remind, GET /dashboard/abandoned-carts

# Training (prefix /training)
GET /training/stats, GET /training/conversations
PATCH /training/messages/{id}/label, POST /training/messages/{id}/smart-label
GET /training/export.jsonl
POST /training/fine-tune, GET /training/fine-tune-status

# Analytics (prefix /analytics)
POST /analytics/rfm/compute, GET /analytics/rfm/segments, GET /analytics/rfm/customers
GET /analytics/conversations, GET /analytics/funnel, GET /analytics/stock-forecast
GET /analytics/revenue
GET/POST /analytics/competitors, GET /analytics/competitors/summary, DELETE /analytics/competitors/{id}

# SSE (real-time events)
GET /events/stream?token=JWT&conversation_id=UUID

# Tenants (super_admin only)
GET/POST /tenants
```

## Важные решения и нюансы

- **UUIDs** для всех primary keys
- **OrderItem НЕ имеет tenant_id** — только `order_id` с CASCADE. Удалять через `order_id.in_(tenant_scoped_order_ids)`.
- **Trailing slash**: эндпоинты без trailing slash (`@router.get("")`) — иначе redirect теряет Authorization header
- **WatchFiles reload**: использовать `--reload-dir src` — иначе бесконечный рестарт
- **OpenAI модели**: `OPENAI_MODEL_MAIN=gpt-4o-mini`, `OPENAI_MODEL_FALLBACK=gpt-4o`
- **Продукт без вариантов = нет цены**. Цена всегда на уровне variant
- **selectinload** обязательно в async SQLAlchemy для eager loading
- **Inventory**: `available_quantity` = `quantity - reserved_quantity`. При создании заказа → `reserved_quantity += qty`. При отмене → rollback.
- **Pydantic v2**: нельзя делать `model.extra_field = value` если поле не объявлено в схеме — будет `ValueError`. Все поля, устанавливаемые в коде (conversation_id в OrderOut, assigned_to_user_name в HandoffOut), ДОЛЖНЫ быть в Pydantic schema с `= None`.
- **SQLAlchemy models vs DB columns**: если startup migration (main.py) добавляет колонку в БД, она ДОЛЖНА быть объявлена и в SQLAlchemy model. Иначе ORM-запросы по этой колонке падают с `AttributeError`.
- **CORS**: origins в `src/core/config.py`. При доступе с другого устройства — добавить его origin.
- **Auth**: фронтенд хранит JWT в localStorage, шлёт в `Authorization: Bearer`. НЕ удалять токен при 401 (иначе cascade failure). НЕ использовать `_redirecting` flag. Бэкенд проверяет blacklist при каждом запросе (fail-open если Redis недоступен).
- **Password policy**: минимум 8 символов, обязательно буквы И цифры.
- **Phone sanitization**: в Telegram router `phone_number` проходит через `re.sub(r"[^0-9+]", "", phone)` перед использованием в filesystem path и БД.
- **Polling с auth**: при 401 — останавливать polling interval, не спамить логи.
- **Telegram sessions**: хранятся в `sessions/` (gitignored). После удаления/восстановления проекта нужно переподключить аккаунт через UI.
- **Telethon typing**: использовать `SetTypingRequest` напрямую, НЕ `client.action()` (он не отправляет, только создаёт объект).
- **Telethon entity resolution**: ОБЯЗАТЕЛЬНО `get_input_entity()` перед `send_message()` для всех исходящих (кроме event.respond/reply).
- **Per-conversation lock**: `asyncio.Lock` per chat_id — предотвращает race condition при быстрых сообщениях.
- **Memory cleanup**: `TelegramClientManager._periodic_cleanup()` раз в час чистит stale entries из in-memory dicts (dedup 5min, hints 1h, locks/chat_map cap 10k). Только RAM, не БД.
- **Message debounce**: 3.5s — буферизует быстрые сообщения в одно.
- **Order creation validation**: product/variant existence check, qty≥1, prices≥0, total_price = qty×unit_price, order number collision retry (12 hex = 2^48).
- **Handoff flush**: ОБЯЗАТЕЛЬНО `await db.flush()` после `db.add(handoff)` + изменений conversation. Без flush данные теряются при return.
- **Training aggregation**: batch query с `func.count().filter()` и `GROUP BY`, НЕ цикл с 3 запросами на conversation.
- **Fine-tuning**: `openai.AsyncOpenAI` (не sync), модель из `settings.openai_model_main` (не hardcoded).
- **CITY_ALIASES**: маппинг город → алиасы (RU/EN/UZ + declensions + районы Ташкента + опечатки)
- **State context**: cart + products + orders + customer + last_order_modifications, JSONB на Conversation
- **Forced responses**: add/remove_item_to_order, locked orders, returns — ответ кодом, НЕ LLM
- **Language post-processing**: детект + замена если AI ответил не на том языке
- **Hallucination guards**: regex ловит fabricated specs, cart claims без tool call, price без БД
- **Anomaly detection**: 6 типов ошибок → автоматически помечает conversation как training candidate
- **Delivery**: если правило не найдено → "стоимость уточняется" (НЕ "бесплатно"). price=0 → "доставка включена"
- **Handoff**: AI пробует разрешить 1 раз, потом передаёт. Одиночные эмоциональные слова — НЕ агрессия.
- **SSE publish**: fire-and-forget (`try/except pass`) — SSE никогда не ломает основной flow. Используй `from src.sse.event_bus import publish_event`.
- **SSE channels**: `sse:{tenant_id}:tenant` (tenant-wide) + `sse:{tenant_id}:conversation:{id}` (per-conversation).
- **React hooks ordering**: ВСЕ хуки (useState, useMemo, useCallback, useEffect, custom hooks) ДОЛЖНЫ вызываться до любого раннего `return`. React 19 строго проверяет количество хуков между рендерами.
- **useEventSource hook**: `lib/use-event-source.ts` — JWT через query param, auto-reconnect, named events. Использовать с debounce для list-страниц.

## Super Admin Platform (`/platform-*` routes, `(platform)` route group)

8 страниц для управления всей SaaS платформой (только `super_admin`):

| Страница | URL | Что делает |
|---|---|---|
| Overview | `/platform-overview` | KPI, 7-day chart, system health, top tenants, recent events |
| Tenants | `/platform-tenants` | List/search/filter/sort/bulk/create/edit/impersonate |
| Tenant Detail | `/platform-tenants/[id]` | KPI, users, activity 30d, AI config, TG monitoring |
| Users | `/platform-users` | Cross-tenant users, create/edit (UserModal), bulk actions |
| AI Monitor | `/platform-ai-monitor` | AI trace logs, 4 KPI, auto-refresh 15s, period filters |
| Billing | `/platform-billing` | Usage per tenant, model distribution, cost estimate, CSV/PDF |
| Logs | `/platform-logs` | 36 action types, expandable details, period/search/filters |
| Settings | `/platform-settings` | 5 sections, toggles, limits enforcement |

**Backend:** `src/platform/router.py` (15 endpoints), `src/platform/schemas.py`, `src/platform/settings_cache.py`, `src/platform/deps.py`
**Frontend:** `frontend/app/(platform)/`, `frontend/components/platform-sidebar.tsx`, `frontend/components/user-modal.tsx`

### Platform Settings Enforcement
Настройки хранятся в JSON файле, кэшируются 30 сек. Проверяются в middleware/endpoints:

| Setting | Где проверяется | Действие |
|---|---|---|
| `maintenance_mode` | orchestrator.py Step 0.5 | AI молчит → "на обслуживании" |
| `read_only_mode` | 28 write endpoints (catalog/orders/conversations) | 403 на запись |
| `max_products_per_tenant` | catalog/router.py create_product | 403 при превышении |
| `max_users_per_tenant` | platform + tenants routers | 403 при превышении |
| `max_messages_per_day` | orchestrator.py Step 0.6 (Redis INCR) | "Лимит исчерпан" |
| `default_ai_model` | orchestrator.py fallback chain | Последний fallback |
| `default_language` | tenants/router.py create_tenant | Auto AiSettings |

### Impersonate Flow
Super admin входит в тенант клиента: `POST /tenants/{id}/impersonate` → 30-min JWT с `impersonated_by` claim → redirect `/dashboard` → amber banner "Viewing as {name}" → Exit → restore original token.

## Vector Search (pgvector)

**Hybrid search**: vector (semantic) + ILIKE (exact aliases). Результаты merge + rank.

- **Extension**: `CREATE EXTENSION vector` + HNSW index на `products.embedding`
- **Embedding**: `text-embedding-3-small` (1536 dim), ~$0.02/1M tokens
- **Text**: `name + brand + model + category + description + aliases`
- **Генерация**: при create/update product + backfill скрипт
- **Поиск**: query embedding (Redis-cached 5 min) → cosine distance → top 10
- **Fallback**: если vector fails → ILIKE only (graceful degradation)

```python
# В truth_tools.py get_product_candidates():
# 1. Vector search → top 10 by cosine similarity
# 2. ILIKE search → existing alias/name matching
# 3. Merge: vector_ids | ilike_ids → deduplicate → rank
```

## Per-tenant API Keys

Каждый тенант может подключить свой OpenAI/Anthropic ключ. Без ключа → fallback на глобальный.

- **Хранение**: Fernet encryption (SHA-256 от `ENCRYPTION_KEY`)
- **Провайдеры**: `openai`, `anthropic`
- **Модели**: gpt-4o-mini, gpt-4o, claude-haiku-4-5, claude-sonnet-4-6
- **Endpoints**: `PUT/GET/DELETE /ai-settings/api-key`, `POST /ai-settings/test-api-key`
- **Frontend**: Settings → "AI Провайдер и API Ключ" секция
- **НИКОГДА** не возвращать ключ на фронт — только `has_key: bool`

## Audit Logging (36 action types)

Fire-and-forget через `log_audit()` helper (`src/core/audit.py`). Никогда не ломает основной flow.

| Модуль | Действия |
|---|---|
| Auth | login, logout, password_change |
| Orders | order.create, order.update, order.delete |
| Products | product.create, product.update, variant.*, delivery_rule.* |
| Conversations | toggle_ai, reset, delete, message.send, message.edit |
| Telegram | connect, disconnect, reconnect |
| Settings | settings.update, api_key.set, api_key.delete |
| Tenants | tenant.create, tenant.update, tenant.user_create |
| Platform | user_create, user_update, user_bulk_status, settings_update |
| Broadcast | broadcast.create, broadcast.cancel |

## Security (что сделано)

- **ILIKE injection**: `escape_like()` для всех `ILIKE` запросов
- **Alembic**: все DDL через миграции, не raw SQL в main.py
- **Password validation**: единый `_validate_password` через Pydantic schema
- **Broadcast confirmation**: `confirmed=True` обязателен для >100 получателей
- **SSE token**: short-lived (5 min) вместо JWT в URL
- **Redis pool**: единый shared pool в `core/redis.py`
- **CORS**: explicit methods, no wildcard
- **RLS**: `set_config(..., false)` — session-scoped (не теряется после commit)
- **Login dedup**: `.limit(1)` для cross-tenant email collision
- **SSE recovery**: CLOSED state → reconnect через 2с
- **Password reset**: токены инвалидируются при смене пароля
- **Raw exceptions**: не leak'аются клиенту — логируются, generic message
- **File I/O**: async через `asyncio.to_thread`
- **Audit silent fail**: теперь логирует warning вместо pass

## Branches

| Branch | Назначение | Статус |
|---|---|---|
| `v2.0` | Production — universal e-commerce AI | Active, production-ready |
| `tour-ai-agent` | Easy Tour — tour agency adaptation | Paused (demo postponed) |
| `main` | Stable releases | Behind v2.0 |

## Ключевые решения и контекст (из memory)

### Пользователь
- Solo developer, Russian speaker, Uzbekistan market
- Action-oriented — требует КОД, не объяснения
- Планирует запуск SaaS **16 мая 2026**
- Друзья с бизнесом: одежда, оптика — первые тестировщики
- Коллега AI-разработчик ревьюил search → рекомендовал vector search (сделано)

### Фидбеки
- **Bug fix approach**: всегда grep перед фиксом, cascade check, consistency
- **Admin UI**: панель на русском, AI говорит на языке клиента (ru/uz/en)
- **Telegram MCP**: @oybeff = клиент тест, @avenir_uz = бот. НИКОГДА не слать @osonturizm
- **Роль Claude**: senior full-stack dev (10+ лет) + software engineer (12+ лет), production quality

### Проекты
- **AI Closer v2.0** — main product, universal e-commerce AI (active)
- **Easy Tour** — tour agency adaptation (branch `tour-ai-agent`, paused)
- **Instagram** — instagrapi DM text works, photos/comments blocked, Meta Developer verification stuck from UZ

### Universal Platform Vision
Платформа должна работать для ЛЮБОГО бизнеса:
- Электроника ✅ (готово)
- Тур агентства ✅ (готово на tour-ai-agent)
- Одежда/оптика — нужен `business_type` + адаптивные промпты
- Кафе/рестораны — нужен working hours + меню
- Салоны красоты — нужен booking + time slots

Ядро (Product/Variant/Order) уже универсальное. Нужны только промпты по типу бизнеса.

### История сессий
| Дата | Что сделано |
|------|-------------|
| Mar 31 | UI redesign — 15 pages, design system (slate/indigo/violet) |
| Apr 1-3 | Dark mode, Telegram/Delivery upgrades |
| Apr 4 | 5 critical bugs fixed (Orders/Handoffs/Training 500s) |
| Apr 7 | Full audit 2.0 — 38 bugs fixed, score 7.5→9.0 |
| Apr 8 | Orchestrator refactor (1665→7 modules), Service Layer, SSE |
| Apr 8 P3 | Performance: N+1 fix, caching, skeletons, pagination |
| Apr 9 | 7 router bugs, 62 tests, rate limits, health check |
| Apr 9 P3 | Docker, UX audit (Playwright, 15 pages, Score 7.2) |
| Apr 14 | Circuit breaker, structured logging, RLS, Telegram SSE |
| Apr 20-22 | Instagram, 20 security fixes, Super Admin (8 pages), API keys, audit logging, UI redesign |
| Apr 22-23 | Vector search (pgvector), 81 tests, technical audit (32 issues fixed), Ultrareview clean |

### Production Deploy Checklist
- [ ] Rotate ALL secrets (SECRET_KEY, ENCRYPTION_KEY, API keys)
- [ ] Set `DEBUG=false`
- [ ] Restrict CORS to actual frontend domain
- [ ] HTTPS via Nginx reverse proxy
- [ ] `--workers 4` (Gunicorn/Uvicorn)
- [ ] PostgreSQL: dedicated app role for RLS enforcement
- [ ] Redis: password protection
- [ ] Log rotation
- [ ] Backup strategy (pg_dump cron)

## Планы (TODO)

### До запуска (16 мая 2026):
1. Деплой на сервер (Docker + Nginx + HTTPS)
2. Домен
3. Business type адаптация (одежда, оптика)
4. Оплата (ручной перевод на старте)

### После запуска:
- Landing page
- Self-service onboarding
- AI Monitor expandable rows
- Multi-provider тест (Claude Haiku/Sonnet)
- Billing → Stripe/Payme интеграция

## .env переменные
```
DATABASE_URL=postgresql+asyncpg://USER@localhost:5432/ai_closer
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
ENCRYPTION_KEY=your-32-byte-key
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
OPENAI_API_KEY=...
OPENAI_MODEL_MAIN=gpt-4o-mini
OPENAI_MODEL_FALLBACK=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_MODERATION_MODEL=omni-moderation-latest
```
