# AI Closer for Telegram Stores

Multi-tenant SaaS платформа — ИИ-продавец для Telegram магазинов. Работает через **реальный Telegram аккаунт** (MTProto/Telethon), НЕ бот.

## Стек

- **Backend**: FastAPI + async SQLAlchemy 2.x + PostgreSQL (asyncpg)
- **Frontend**: Next.js 14 (App Router) + Tailwind CSS
- **Telegram**: Telethon (MTProto) — подключается как пользовательский аккаунт
- **AI**: OpenAI API с function calling (tools)
- **Auth**: JWT + bcrypt

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

**Логин**: `owner@technouz-demo.com` / `admin123`

## Архитектура

### Multi-tenant
- Все таблицы имеют `tenant_id` (UUID)
- Все запросы фильтруются по `tenant_id` текущего пользователя
- Один тенант = один магазин

### Структура бэкенда (`src/`)
```
src/
├── main.py              # FastAPI app, startup (запуск Telegram клиентов)
├── core/
│   ├── config.py        # Settings (из .env)
│   └── database.py      # async SQLAlchemy engine + session
├── auth/
│   ├── models.py        # Tenant, User
│   ├── router.py        # POST /auth/login, /auth/register
│   ├── deps.py          # get_current_user, require_store_owner (owner/store_owner/super_admin)
│   └── schemas.py
├── catalog/
│   ├── models.py        # Category, Product, ProductVariant, ProductAlias, ProductMedia, Inventory, DeliveryRule, CommentTemplate
│   ├── router.py        # CRUD + ProductDetailOut с selectinload(variants→inventory, aliases, category)
│   └── schemas.py       # ProductDetailOut: variants + stock + aliases + min/max price + category_name
├── conversations/
│   ├── models.py        # Conversation (telegram_username, telegram_first_name, state_context JSONB), Message (telegram_message_id)
│   ├── router.py        # GET/PATCH conversations + messages, POST operator reply, PATCH edit message (+ Telegram sync), POST reset
│   └── schemas.py       # MessageEdit, MessageSend (sync_telegram flag)
├── leads/
│   ├── models.py        # Lead (telegram_username, customer_name auto-filled from TG)
│   └── router.py
├── orders/
│   ├── models.py        # Order, OrderItem
│   ├── router.py        # CRUD + status change → Telegram notification to user
│   └── schemas.py       # OrderItemOut with product_name + variant_title
├── telegram/
│   ├── models.py        # TelegramAccount, TelegramDiscussionGroup
│   ├── router.py        # POST /telegram/send-code, /verify-code, DELETE /accounts/{id}
│   └── service.py       # Telethon: DM handling + typing animation + comment templates
├── ai/
│   ├── orchestrator.py  # process_dm_message() — system prompt + multi-round tool calling + order pre-processor
│   ├── truth_tools.py   # 14 tool functions (see below)
│   ├── policies.py      # Codified business rules — can_cancel, can_edit, get_allowed_actions, next_state
│   ├── models.py        # AiSettings (6 policy columns)
│   ├── router.py        # GET/PUT /ai-settings
│   └── schemas.py
└── handoffs/            # Handoff модель (передача оператору)
    ├── models.py        # summary, linked_order_id fields
    ├── router.py        # enriched output with order number + conversation name
    └── schemas.py
```

### Как работает AI агент

1. Пользователь пишет в DM Telegram аккаунту магазина
2. Telethon получает сообщение → `service.py`
3. **Typing анимация** начинается (показывает "печатает..." пока AI думает)
4. Вызывается `process_dm_message(tenant_id, conversation_id, user_message, db)`
5. **Order pre-processor** (`_preprocess_order_request`) — детерминированная проверка заказов ДО вызова LLM
6. **Conversation state** определяется из `conversation.state` + `state_context`
7. **State-aware system prompt** — базовый промпт + секция для текущего состояния (STATE_PROMPTS)
8. Orchestrator строит контекст (последние 20 сообщений) + state_context + system prompt
9. OpenAI с function calling — **multi-round** (до 3 раундов tool calls за одно сообщение)
10. AI НИКОГДА не придумывает цены/наличие — только из БД через tools
11. **State transition** — после каждого tool call обновляется `conversation.state` через `policies.next_state()`
12. **Forced responses** — для add_item_to_order / remove_item_from_order / locked orders — ответ генерируется кодом, не LLM
13. **Задержка** пропорционально длине ответа (1-5 сек) — симуляция набора текста
14. Ответ отправляется в Telegram, `telegram_message_id` сохраняется для edit sync

### Order Pre-Processor (`_preprocess_order_request`)
Детерминированная обработка заказов **ДО** вызова LLM. Перехватывает номер заказа из сообщения пользователя и решает кодом:

| Ситуация | Действие |
|---|---|
| Заказ не найден | Forced: "Заказ не найден. Проверьте номер" |
| Чужой заказ (другой user) | Forced: "Заказ не найден. Проверьте номер" (не раскрывает статус!) |
| Отменён/Отправлен/Доставлен + "изменить" | Forced: "Статус X — изменения невозможны" (БЕЗ оператора) |
| В обработке + "изменить" | Forced: создаёт handoff + "Подключу оператора" |
| Draft/Confirmed + "изменить" | Inject: передаёт в LLM с полной инфой + "МОЖЕШЬ изменить сам" |
| Просто номер / статус | Inject: передаёт в LLM с инфой о заказе |

### Conversation State Machine
States: `idle → browsing → selection → cart → checkout → post_order → handoff`
- `idle` — начало диалога, приветствие
- `browsing` — клиент ищет/смотрит товары (list_categories, get_product_candidates)
- `selection` — выбирает вариант товара (get_variant_candidates)
- `cart` — товары в корзине (select_for_cart, remove_from_cart)
- `checkout` — оформление заказа (сбор данных → create_order_draft)
- `post_order` — есть заказ (check_order_status, cancel_order, add/remove item)
- `handoff` — передан оператору
State transitions определяются в `policies.STATE_AFTER_TOOL`.

### Policy Layer (`src/ai/policies.py`)
- `AI_EDITABLE_STATUSES` = {"draft", "confirmed"} — AI сам изменяет
- `OPERATOR_REQUIRED_STATUSES` = {"processing"} — нужен оператор
- `LOCKED_STATUSES` = {"shipped", "delivered", "cancelled"} — изменения невозможны
- `can_cancel_order(status)` — draft: AI может, confirmed: оператор, locked: нельзя
- `can_edit_order(status)` — draft/confirmed: AI может, processing: оператор, locked: нельзя
- `get_allowed_actions(status)` — список доступных действий
- `next_state(current, tool_name)` — следующее состояние после tool call
- `STATUS_LABELS_RU` — русские названия статусов

### AI Tools (15 функций)
- `list_categories` — список категорий с кол-вом товаров
- `get_product_candidates` — поиск по имени/алиасам/категории/бренду (ILIKE + word split)
- `get_variant_candidates` — варианты товара с ценой/стоком
- `get_variant_price` — точная цена
- `get_variant_stock` — точный остаток
- `get_delivery_options` — доставка по городу (с алиасами RU/EN/UZ + районы Ташкента)
- `get_customer_history` — предыдущие заказы клиента (имя, тел, город, адрес) для повторных покупок
- `select_for_cart` — добавить вариант в корзину (state_context)
- `remove_from_cart` — удалить из корзины (ТОЛЬКО по явной просьбе)
- `create_order_draft` — создать заказ из корзины, резервирует инвентарь
- `check_order_status` — проверить статус + `allowed_actions` из policy layer (с проверкой ownership!)
- `cancel_order` — отменить draft заказ (unreserve inventory), confirmed+ → needs_operator
- `add_item_to_order` — добавить товар в существующий заказ (draft/confirmed). Forced response.
- `remove_item_from_order` — убрать товар из существующего заказа. Forced response.
- `request_handoff` — передать оператору (с summary, priority, linked_order_number)

### Forced Responses (обход LLM)
Для критических операций ответ генерируется **кодом**, не LLM — чтобы gpt-4o-mini не выдумывал:
- **add_item_to_order** → "Добавил X в заказ ORD-Y! Сумма: Z 👍 Что-нибудь ещё?"
- **remove_item_from_order** → "Убрал X из заказа ORD-Y. Сумма: Z. Что-нибудь ещё?"
- **Locked order + modify intent** → "Статус X — изменения невозможны"
- **Processing order + modify** → создаёт handoff + "Подключу оператора"
- **Чужой заказ** → "Заказ не найден"

### State Context (JSONB на Conversation)
- Персистентное хранилище между сообщениями
- `cart` — корзина (variant_id, title, price, qty)
- `products` — известные товары из поиска (product_id → name, variants)
- `orders` — созданные заказы (order_id, order_number, total_amount, items)
- `customer` — данные клиента (name, phone, city, address)
- `last_order_modifications` — история изменений заказов (action, item, order, new_total)
- Инжектируется в system prompt как "STATE_CONTEXT"

### AI поведение (system prompt)
- **State-aware** — промпт меняется в зависимости от conversation state
- **Приветствия**: отвечает на "привет/салом" дружелюбно
- **Off-topic**: "какая земля круглая?", алгебра, стартапы → "Я помогаю только с покупками"
- **НЕ off-topic**: вопросы про цены/скидки, "вы работаете?", эмоции клиента при покупке, характеристики товаров, доставка
- **Сломан айфон**: не даёт советы по ремонту → предлагает новый
- **Выбор по номеру**: "5" после списка категорий → `get_product_candidates("смартфон")`
- **Корзина**: select_for_cart → "Ещё что-то или оформляем?"
- **"Нет" после "Ещё что-то?"**: → переходит к checkout / вежливое завершение, НЕ удаляет из корзины
- **Скидки**: "Цены фиксированные"
- **Характеристики**: НИКОГДА не выдумывать RAM/storage/specs — только из результатов tools
- **Добавление в корзину**: НИКОГДА не говорить "добавил" без вызова select_for_cart
- **Изменение заказа**: pre-processor проверяет статус кодом → draft/confirmed: AI помогает, processing: handoff, locked: отказ
- **Отмена заказа**: draft → cancel_order (AI сам), confirmed → handoff, processing+ → нельзя
- **После add_item_to_order**: НЕ спрашивать адрес/данные — товар добавлен в существующий заказ
- **Доставка**: если 1 опция — не спрашивать тип, если 2+ — спросить, если город не найден — показать доступные
- **Конфликты**: 1 попытка разрешить, потом handoff. Одиночные эмоциональные слова — НЕ агрессия
- **Handoff**: при реальной агрессии (2+ сообщения с матом), запрос человека, невозможность решить — с summary, priority, linked_order

### Telegram подключение
- Используется Telethon (MTProto), НЕ Bot API
- При подключении: `device_model="AI Closer Server"`, `system_version="Linux 5.15"`
- Сессии хранятся в `sessions/{tenant_id}_{phone}.session`
- Один аккаунт на тенант
- Поддержка 2FA (пароль)
- **Typing анимация**: `client.action(chat_id, 'typing')` каждые 4 сек пока AI думает
- **Telegram message ID**: сохраняется для sync edit из админки

### Комментарии в каналах
- При написании "+" или "цена" в обсуждении канала — автоответ по шаблону
- Триггеры: keyword, emoji, regex

### Уведомления
- **Смена статуса заказа**: admin меняет статус → Telegram сообщение юзеру
- shipped → "Ваш заказ отправлен! Ожидайте доставку."
- delivered → "Ваш заказ доставлен! Спасибо за покупку!"
- cancelled → "Если есть вопросы, напишите нам."

### Схема БД (ключевые таблицы)
- **tenants** — магазины
- **users** — пользователи (owner/admin/operator роли)
- **categories** — категории товаров (self-referential parent_id)
- **products** — товары (name, slug, brand, model, category_id)
- **product_variants** — варианты (title, color, storage, ram, size, price, currency)
- **product_aliases** — синонимы для поиска AI (261+ включая кириллицу, ошибки, категорийные)
- **inventory** — остатки (quantity, reserved_quantity, available_quantity = qty - reserved)
- **delivery_rules** — правила доставки по городам (CITY_ALIASES для RU/EN/UZ + районы)
- **comment_templates** — шаблоны ответов на комментарии
- **conversations** — чаты (telegram_username, telegram_first_name, state_context JSONB, ai_enabled, state: idle/browsing/selection/cart/checkout/post_order/handoff)
- **messages** — сообщения (direction, sender_type: customer/ai/human_admin/system, telegram_message_id для edit sync)
- **leads** — лиды (auto-fill customer_name, telegram_username из TG; status → converted при заказе)
- **orders** + **order_items** — заказы (order_number, items with product/variant names)
- **ai_settings** — настройки AI (tone, language, fallback_mode, allow_ai_cancel_draft, require_operator_for_edit, require_operator_for_returns, max_variants_in_reply, confirm_before_order, auto_handoff_on_profanity)
- **telegram_accounts** — подключённые Telegram аккаунты
- **handoffs** — переданные оператору (reason, summary, priority: low/normal/high/urgent, linked_order_id)

### Frontend страницы
- `/login` — авторизация
- `/dashboard` — статистика
- `/products` — список товаров (категория, цена range, наличие badge, варианты count)
- `/products/[id]` — детали (варианты таблица: color, storage, RAM, price, stock, reserved + алиасы)
- `/conversations` — карточки диалогов (имя + @username, статус, AI toggle, "2 ч назад")
- `/conversations/[id]` — чат-интерфейс (bubble messages, date separators, edit button hover, operator reply input, auto-refresh 3s, handoff banner, AI toggle)
- `/leads` — карточки лидов (аватар, имя, @username, phone, city, status select)
- `/orders` — expandable карточки (header + click → items list с product/variant names, delivery, summary)
- `/delivery` — карточки правил (type icon, edit, active toggle)
- `/telegram` — подключение/отключение Telegram аккаунта
- `/templates` — шаблоны комментариев
- `/settings` — AI настройки (toggle switches для order policies, AI behavior, conflict handling)
- `/handoffs` — карточки с priority badge, summary, linked order, conversation link, filter buttons, "Решено" button

### API endpoints (conversations)
- `GET /conversations` — список с фильтром по source_type
- `GET /conversations/{id}` — детали
- `GET /conversations/{id}/messages` — сообщения
- `PATCH /conversations/{id}/toggle-ai` — вкл/выкл AI (resets handoff state)
- `PATCH /conversations/{id}/messages/{msg_id}` — edit message + Telegram sync
- `POST /conversations/{id}/messages` — operator reply + send to Telegram
- `POST /conversations/{id}/reset` — очистить state_context, вернуть в idle

### API endpoints (orders)
- `GET /orders` — список с items (product_name, variant_title)
- `PATCH /orders/{id}` — update status → Telegram notification

## Важные решения и нюансы

- **UUIDs** для всех primary keys
- **Trailing slash**: эндпоинты без trailing slash (`@router.get("")`) — иначе redirect теряет Authorization header
- **WatchFiles reload**: использовать `--reload-dir src` — иначе бесконечный рестарт
- **OpenAI модели**: `OPENAI_MODEL_MAIN=gpt-4o-mini`, `OPENAI_MODEL_FALLBACK=gpt-4o`
- **Продукт без вариантов = нет цены**. Цена всегда на уровне variant
- **selectinload** обязательно в async SQLAlchemy для eager loading
- **Inventory**: `available_quantity` = `quantity - reserved_quantity`. При создании заказа → `reserved_quantity += qty`. При отмене → rollback.
- **CITY_ALIASES**: маппинг город → алиасы (RU/EN/UZ + declensions + районы Ташкента + опечатки: такент, ташент, тошкен)
- **telegram_message_id**: сохраняется при отправке AI → нужен для edit_message sync из админки
- **state_context**: cart + known products + orders + customer data + last_order_modifications, персистится в JSONB на Conversation
- **Conversation state machine**: idle → browsing → selection → cart → checkout → post_order → handoff. Автоматически обновляется через `policies.next_state()`.
- **Policy layer** (`src/ai/policies.py`): can_cancel_order, can_edit_order, get_allowed_actions — codified business rules, не в prompt
- **Order pre-processor**: детерминированная проверка заказов ДО вызова LLM — ownership check, status check, forced responses для locked/processing
- **Forced responses**: add_item_to_order, remove_item_from_order, locked orders — ответ генерируется кодом, НЕ LLM
- **"Нет" disambiguation**: в state=cart после "Ещё что-то?" → checkout (НЕ remove_from_cart). В post_order → вежливое завершение.
- **Typing**: `client.action(chat_id, 'typing')` в asyncio task + delay пропорционально длине ответа
- **Delivery cost**: если правило не найдено → `delivery_note: "стоимость уточняется"`, НЕ "бесплатно". price=0 → "доставка включена"
- **Delivery type**: если 1 опция — не спрашивать, если 2+ — спросить
- **Handoff**: AI пробует разрешить 1 раз, потом передаёт. "Хочу изменить заказ" — НЕ конфликт.
- **Lead auto-fill**: customer_name и telegram_username берутся из Conversation (которое берёт из Telethon sender)
- **Order status notification**: PATCH /orders/{id} с новым status → send_message в Telegram через lead → conversation → telegram_chat_id
- **Order number normalization**: `_normalize_order_number()` — принимает "5BE9D692" или "ORD-5BE9D692", всегда возвращает "ORD-5BE9D692"
- **Ownership verification**: check_order_status и add/remove_item проверяют что заказ принадлежит текущему пользователю через lead → telegram_user_id
- **Характеристики товаров**: AI НИКОГДА не выдумывает RAM/storage/battery/specs — только данные из get_variant_candidates. Код-уровневая проверка: regex ловит fabricated specs и заменяет ответ.
- **Per-conversation lock**: `asyncio.Lock` per chat_id в TelegramClientManager — предотвращает race condition когда юзер шлёт 2+ сообщения быстро. Без лока: оба сообщения загружают старый state_context, второе перезаписывает изменения первого (cart loss, duplicate responses).
- **Повторный клиент**: `get_customer_history` tool — если клиент говорит "олдинги адрес" / "предыдущий адрес", AI находит данные из прошлого заказа и подтверждает.
- **Language post-processing**: Если AI ответил на русском в uz_cyrillic чате (или Cyrillic в uz_latin) — код детектит и заменяет ответ на правильный язык.

## TODO (запланированные улучшения)

- [ ] **AI policy settings enforcement** — настройки из AiSettings (allow_ai_cancel_draft, require_operator_for_edit и т.д.) хранятся в БД, но НЕ читаются orchestrator'ом при runtime. Нужно загружать и применять.
- [ ] **delivery_type в create_order_draft** — Order модель имеет поле delivery_type, но tool не передаёт его. Нужно добавить параметр.
- [ ] **Характеристики товаров в админке** — показывать RAM/storage/color в списке вариантов в admin UI
- [ ] **Intent logging** — логирование state transitions и intent classification для отладки
- [ ] **Test scenarios** — автотесты для AI agent (mock OpenAI, проверка forced responses, policy checks)
- [ ] **Рассмотреть переход на gpt-4o** — gpt-4o-mini плохо следует сложным промпт-инструк��иям. Детерминированный код (pre-processor, forced responses) компенсирует, но gpt-4o был бы надёжнее

## .env переменные
```
DATABASE_URL=postgresql+asyncpg://USER@localhost:5432/ai_closer
SECRET_KEY=your-secret-key
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
OPENAI_API_KEY=...
OPENAI_MODEL_MAIN=gpt-4o-mini
OPENAI_MODEL_FALLBACK=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_MODERATION_MODEL=omni-moderation-latest
```
