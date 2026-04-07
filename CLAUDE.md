# AI Closer for Telegram Stores

Multi-tenant SaaS платформа — ИИ-продавец для Telegram магазинов. Работает через **реальный Telegram аккаунт** (MTProto/Telethon), НЕ бот.

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
- **Frontend**: Next.js 14 (App Router) + Tailwind CSS
- **Telegram**: Telethon (MTProto) — подключается как пользовательский аккаунт
- **AI**: OpenAI API с function calling (tools)
- **Auth**: JWT + bcrypt + Redis token blacklist
- **Retry**: tenacity (OpenAI), custom retry (Telegram FloodWait)
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
- `admin@gmail.com` / `admin` — store_owner (основной рабочий аккаунт)
- `owner@technouz-demo.com` / `admin123` — super_admin (seed)
- Tenant ID: `a7b1be91-b75f-4088-848a-22705b44b1b2`

## Архитектура

### Multi-tenant
- Все таблицы имеют `tenant_id` (UUID), **кроме** `order_items` (только `order_id` с CASCADE)
- Все запросы фильтруются по `tenant_id` текущего пользователя
- Один тенант = один магазин

### Структура бэкенда (`src/`)
```
src/
├── main.py              # FastAPI app, startup (запуск Telegram клиентов, scheduled broadcasts, draft cleanup)
├── core/
│   ├── config.py        # Settings (из .env), CORS origins
│   ├── database.py      # async SQLAlchemy engine + session
│   ├── models.py        # PkMixin, TenantMixin, TimestampMixin, UpdatableMixin
│   ├── security.py      # JWT encode/decode, bcrypt, Redis token blacklist
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
│   ├── models.py        # CommentTemplate, Conversation (is_training_candidate, state_context JSONB), Message (training_label, rejection_reason)
│   ├── router.py        # CRUD conversations + messages + templates, DELETE cascade, operator reply, edit sync, reset
│   └── schemas.py       # MessageEdit, MessageSend, BroadcastRequest, TrainingLabelUpdate
├── leads/
│   ├── models.py        # Lead (telegram_username, customer_name auto-filled from TG)
│   └── router.py
├── orders/
│   ├── models.py        # Order, OrderItem (NO tenant_id!)
│   ├── router.py        # CRUD + validation (product/variant existence, price check) + status → TG notification
│   └── schemas.py       # OrderCreate (validated: items≥1, qty≥1, prices≥0, name/phone length)
├── telegram/
│   ├── models.py        # TelegramAccount, TelegramDiscussionGroup
│   ├── router.py        # send-code, verify-code (sanitized phone), accounts, status, reconnect, activity-logs
│   └── service.py       # TelegramClientManager: DM handling + read receipts + human-like typing + debounce + entity resolution + periodic memory cleanup
├── ai/
│   ├── orchestrator.py  # process_dm_message() — system prompt + multi-round tool calling + order pre-processor + retry (tenacity) + fallback mode
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
├── dashboard/
│   ├── models.py        # BroadcastHistory
│   ├── router.py        # stats, broadcast (immediate+scheduled, 5000 cap), broadcast-history, abandoned-carts, cleanup
│   └── schemas.py
├── training/
│   └── router.py        # stats, conversations (batch aggregation), label, smart-label (GPT-4o), export JSONL, fine-tune (async OpenAI)
├── analytics/
│   ├── models.py        # CustomerSegment, CompetitorPrice
│   ├── router.py        # RFM segmentation, conversation metrics, funnel (safe division), stock-forecast, revenue, competitors
│   └── schemas.py
├── handoffs/
│   ├── models.py        # Handoff (summary, linked_order_id, resolution_notes)
│   ├── router.py        # list + update (with assigned_to_user_name enrichment)
│   └── schemas.py       # HandoffOut has assigned_to_user_name, resolution_notes
└── import_data/
    └── router.py        # Bulk import products
```

### Как работает AI агент

1. Пользователь пишет в DM Telegram аккаунту магазина
2. Telethon получает сообщение → `service.py` (debounce 3.5s для быстрых сообщений)
3. **Per-conversation lock** (`asyncio.Lock`) — предотвращает race condition
4. **Read receipt** (✓✓) — `send_read_acknowledge()` мгновенно
5. **"Reading" пауза** (1.5–3.5с) — пропорционально длине сообщения, имитация чтения
6. **Typing анимация** (`SetTypingRequest`) — показывает "печатает..." пока AI думает
7. Вызывается `process_dm_message(tenant_id, conversation_id, user_message, db)`
8. **Kill switch** — если `allow_auto_dm_reply=False`, return None (AI молчит)
9. **Order pre-processor** (`preprocessor.py`) — детерминированная проверка заказов ДО вызова LLM
10. **Conversation state** определяется из `conversation.state` + `state_context`
11. **State-aware system prompt** — базовый промпт + секция для текущего состояния + настройки (tone, language, confirm_before_order)
12. Orchestrator строит контекст (последние 20 сообщений) + state_context + system prompt
13. OpenAI с function calling + **retry** (tenacity, 3 попытки, exponential backoff) — **multi-round** (до 3 раундов tool calls)
14. AI НИКОГДА не придумывает цены/наличие — только из БД через tools
15. **Hallucination guards**: cart claims, price/spec fabrication, language mismatch — код-уровневая проверка
16. **State transition** — после каждого tool call через `policies.next_state()`
17. **Forced responses** — для add/remove_item_to_order, locked orders, returns — ответ кодом
18. **Language post-processing** — детект и коррекция языка (ru↔uz_cyrillic↔uz_latin)
19. **State context cleanup** — cap: products≤5, orders≤5, variants≤8/product
20. **Typing delay** пропорционально длине ответа (1–6 сек) — имитация набора
21. Ответ отправляется с retry (FloodWait handling), `telegram_message_id` сохраняется
22. **Fallback mode** — при ошибке AI: попытка fallback model (gpt-4o) или создание handoff

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
- `/dashboard` — KPI stats + bar chart
- `/products` — список (категория, цена range, наличие badge, варианты count)
- `/products/[id]` — детали (варианты таблица + алиасы + media + sales)
- `/conversations` — карточки диалогов (имя + @username, AI toggle, time-ago)
- `/conversations/[id]` — чат (bubble messages, date separators, edit, operator reply, auto-refresh 3s, handoff banner)
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

## .env переменные
```
DATABASE_URL=postgresql+asyncpg://USER@localhost:5432/ai_closer
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
OPENAI_API_KEY=...
OPENAI_MODEL_MAIN=gpt-4o-mini
OPENAI_MODEL_FALLBACK=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_MODERATION_MODEL=omni-moderation-latest
```
