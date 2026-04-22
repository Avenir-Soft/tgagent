# Handoff · AI Closer Platform (Super Admin) · UI/UX Refresh

> Восстанавливаем визуальный слой супер-админ панели. **Структура файлов,
> роуты, компоненты, data-fetching и бизнес-логика не меняются** — только
> стили, разметка внутри существующих компонентов и токены.

---

## 0 · TL;DR для Claude Code

**ЧТО меняем:**

- `frontend/app/globals.css` — полностью переписать токены и базовые слои
- `frontend/components/platform-sidebar.tsx` — стилевой рефреш (разметка та же, классы новые)
- `frontend/app/(platform)/*` — рестайл 8 страниц:
  1. `platform-overview/page.tsx`
  2. `platform-tenants/page.tsx`
  3. `platform-tenants/[id]/page.tsx`
  4. `platform-users/page.tsx`
  5. `platform-ai-monitor/page.tsx`
  6. `platform-billing/page.tsx`
  7. `platform-logs/page.tsx`
  8. `platform-settings/page.tsx`
- `frontend/app/(platform)/layout.tsx` — рестайл breadcrumbs / top bar

**ЧТО НЕ ТРОГАЕМ:**

- ❌ `frontend/app/(auth)/*` — Login и все auth экраны остаются как есть
- ❌ `frontend/app/(admin)/*` — tenant-admin роут группа не трогаем
- ❌ Все роуты, имена файлов, props компонентов, API-вызовы `api.*`, типы
- ❌ `lib/theme.ts` — переключатель тем оставить как есть, только сверить атрибут
- ❌ Русская локализация текстов — все строки остаются на русском

**Подход:** только стилевой рефреш. Не переписывать структуру. Не добавлять
новых компонент-библиотек. Чистый Tailwind v4 + CSS variables.

---

## 1 · Design Files в этом пакете

**Это референс-дизайн, сделанный в одном HTML-файле.** Это НЕ production-код
для копирования 1-в-1. Задача — **воспроизвести этот дизайн в реальном Next.js
codebase**, используя существующие структуры и паттерны.

### Файлы

- `reference/platform-redesign.html` — вся система в одном HTML.
  Откройте в браузере → вкладка **«Full Redesign»** → переключатель **Dark**
  сверху справа. Клик по подпунктам навигации для переключения между экранами.
  Токены и разметка вытаскиваются оттуда.
- `screenshots/01-overview.png` … `09-settings.png` — финальный вид
  каждой страницы в dark-теме. **Dark — дефолт.** Пиксель-в-пиксель reference.

### Fidelity

**Hi-fi.** Цвета, типографика, spacing, скругления, плотность — финальные.
Разработчик должен воспроизвести пиксель-в-пиксель, используя токены из раздела 3.

---

## 2 · Технический стек (целевой)

Подтверждено пользователем:

- Next.js 15 App Router
- React 19
- TypeScript
- Tailwind CSS v4 (уже настроен в `globals.css` через `@import "tailwindcss"`)
- **Без UI-библиотек** (shadcn/ui, radix, mui — нет)
- Custom components (уже написаны, только стилизуем)
- Тема: `data-theme="dark|light"` на `<html>` + CSS variables. Уже работает
  через `lib/theme.ts` — не трогаем.

---

## 3 · Design Tokens

Единственный источник правды — ниже. Всё живёт в `globals.css` как CSS
variables. Компоненты используют только эти переменные (не хардкодить hex).

### 3.1 Цвета · Dark (по умолчанию)

```css
/* surfaces */
--bg:       #0a0d12;   /* body */
--bg-2:     #0f1319;   /* subtle hover, input bg */
--panel:    #131821;   /* cards, sidebar, top bar */
--panel-2:  #171d27;   /* table thead, tfoot, pager */

/* lines */
--line:     #232a36;   /* все основные border */
--line-2:   #2b3442;   /* hovered border, focused ring base */
--hair:     #1b2230;   /* разделители внутри карточек (dashed) */

/* ink (text) — 4 градации */
--ink:      #e7ecf3;   /* primary */
--ink-2:    #9aa3b2;   /* secondary body */
--ink-3:    #6a7386;   /* meta, dim, labels */
--ink-4:    #4a5264;   /* disabled, chart axis */

/* accent · primary brand */
--accent:       #7c8cff;
--accent-soft:  #7c8cff1a;   /* 10% alpha — для chip/hover */
--accent-ring:  #7c8cff55;   /* focus ring */

/* signal */
--good:      #4ade80;   --good-soft:  #4ade801a;
--warn:      #f5b454;   --warn-soft:  #f5b4541a;
--bad:       #f87171;   --bad-soft:   #f871711a;
--info:      #60a5fa;   --info-soft:  #60a5fa1a;

/* shadow */
--shadow: 0 1px 0 #ffffff06 inset, 0 8px 24px -12px #00000066;
```

### 3.2 Цвета · Light

```css
--bg:      #f6f5f0;   --bg-2:     #faf8f2;
--panel:   #ffffff;   --panel-2:  #fbfaf5;
--line:    #e3dfd4;   --line-2:   #d6d1c4;   --hair: #ece7d9;
--ink:     #141210;   --ink-2:    #5a544c;   --ink-3: #8a847a;   --ink-4: #b2ab9f;
--accent:      #2a4a7f;
--accent-soft: #2a4a7f14;
--accent-ring: #2a4a7f55;
--good: #2f6a3f; --good-soft: #2f6a3f14;
--warn: #9c6b00; --warn-soft: #9c6b0014;
--bad:  #9c2a2a; --bad-soft:  #9c2a2a14;
--info: #1e5a9c; --info-soft: #1e5a9c14;
--shadow: 0 1px 0 #00000008 inset, 0 4px 14px -8px #00000018;
```

### 3.3 Типографика

- **Основной:** `Inter` (уже подключён через `next/font/google` в `app/layout.tsx` — оставить)
- **Моно:** `'Geist Mono', ui-monospace, monospace` — **добавить** через `next/font/google`.
  Применять: labels таблиц, timestamps, slug, ID, KPI delta, kbd, чипы с mono-стилем.
- **Tabular nums:** класс `.tnum { font-variant-numeric: tabular-nums; }` — на все числа в
  таблицах, KPI-значениях, timestamps. Уже есть в утилитах globals.css, довести.

Шкала (основная):

| класс | size / line | использование |
|---|---|---|
| `.h1` | 22px / 1.15, 600, -0.01em | Заголовок страницы |
| `.kpi-v` | 26px / 1.0, 600, -0.02em | Значение KPI |
| `.card-t` | 12px / 1.2, 600 | Заголовок карточки |
| body | 12.5px / 1.5, 400 | Ячейки таблиц, контент |
| `.label` | 9.5–10.5px, 500, uppercase, letter-spacing 0.14–0.18em | Метки, thead, nav-группы (mono) |
| `.meta` | 10.5–11.5px, 400 | Подписи, breadcrumbs |

### 3.4 Spacing / Radius / Motion

- Радиусы: `5px` (маленькие chip, page-button), `6px` (button, input, select, nav-item), `7px` (search, segmented), `9px` (card), `10px` (shell, modal)
- Гэп внутри карточки: `10px` (card-h → content), между карточками: `12px`, между секциями страницы: `14px`
- Переходы: `.12s` для hover, `.15s` для fade
- Плотность: **compact** (строка таблицы 10px вертикальный padding, input 8px)

---

## 4 · Компоненты · map на существующий код

| Существующий компонент | Изменения |
|---|---|
| `components/platform-sidebar.tsx` | Разметка та же. Классы → новые (см. § 5.1). Фон `var(--panel)`, группы-лейблы в mono, активный пункт `bg-[var(--accent-soft)] text-[var(--accent)]`. |
| `components/ui/card.tsx` (если есть) | `bg-[var(--panel)] border border-[var(--line)] rounded-[9px] p-[14px] shadow-[var(--shadow)]`. Заголовок `.card-t`. |
| `components/ui/button.tsx` | Primary: `bg-[var(--accent)] text-white`. Ghost: `bg-transparent border border-[var(--line)]`. Warn (для «Войти как Admin»): `bg-[var(--warn)] text-[#1a1205] font-semibold`. Все padding `6px 11px`, radius `6px`, font 12. |
| `components/ui/table.tsx` | thead: `bg-[var(--panel-2)]`, label mono uppercase 9.5px / 0.15em, cell padding `10px 12px`, border-bottom `var(--hair)`. Hover row: `bg-[var(--bg-2)]`. |
| `components/ui/input.tsx` + `select.tsx` | `bg-[var(--bg)] border border-[var(--line)] rounded-md px-[10px] py-[8px] text-[12.5px]`. Focus: `border-[var(--accent)] shadow-[0_0_0_3px_var(--accent-soft)]`. |
| `components/ui/badge.tsx` (chip) | 5 вариантов: `good | warn | bad | accent | info`. Все с 10% tint фоном + `border` через `color-mix(oklab, var(--X) 30%, transparent)`. Точка впереди — символ `●`. |
| `components/ui/segmented.tsx` (если нет — сделать) | Обёртка `bg-[var(--bg-2)] border border-[var(--line)] rounded-[7px] p-[2px]`. Активный: `bg-[var(--panel)] text-[var(--ink)] shadow-sm`. |
| `app/(platform)/layout.tsx` | Breadcrumbs: `font-size:12px`, последний `var(--ink)`, остальные `var(--ink-3)`, разделитель `/` в `var(--ink-4)`. Добавить `⌘K` cmdk-пилюлю справа (визуально — функциональность можно пока заглушкой). |

**Приоритет:** если компонента нет — создавать в `components/ui/`. Если есть —
только переписать внутренние классы. Props / API остаётся без изменений.

---

## 5 · Экраны — инструкции

Для каждого экрана приложен скриншот в `screenshots/`. Открывать рядом с
кодом. Все экраны используют общий shell (sidebar 232px + main).

### 5.1 Sidebar (общий для всех 8 страниц)

Файл: `components/platform-sidebar.tsx`

Структура (логическая разметка та же, классы новые):

```
Aside w=232, bg=var(--panel), border-right var(--line)
├── Brand row (px 16, py 14, border-bottom var(--line))
│   ├── Logo 30×30 bg=var(--accent), text "AC" 11px 700 #fff, radius 7
│   └── "AI Closer" 13px/600 + "platform · super admin" 9.5px mono uppercase tracking-[0.15em] var(--ink-3)
├── Nav (p 10px 8px)
│   ├── Group label "ОБЗОР" 9.5px mono uppercase tracking-[0.16em] var(--ink-4)
│   ├── Item: py-[7px] px-[10px] text-[12.5px] rounded-[6px] text-[var(--ink-2)]
│   │   Active: bg-[var(--accent-soft)] text-[var(--accent)] + right dot 4px
│   └── Groups: ОБЗОР / УПРАВЛЕНИЕ / МОНИТОРИНГ / СИСТЕМА
└── User row (p 10, border-top var(--line))
    ├── Avatar 30×30 rounded-full bg=var(--accent-soft) text-[var(--accent)] 11px/600
    ├── Email 12px var(--ink) + Role 9.5px mono uppercase var(--ink-3)
    └── Logout icon button (28×28 rounded-[6px] hover:bg var(--bg-2))
```

Смотри `screenshots/01-overview.png` слева — все остальные экраны используют
тот же sidebar.

### 5.2 Overview · `platform-overview/page.tsx`

Скриншот: `screenshots/01-overview.png`

- **Хедер:** `<h1 class="h1">Обзор платформы</h1>` + sub «Последнее обновление: 14:32:06 · обновить ↻» + справа segmented **24ч / 7д / 30д**
- **5 KPI** (grid-cols-5, gap 10px): «ТЕНАНТЫ», «ПОЛЬЗОВАТЕЛИ», «СООБЩЕНИЙ 24Ч», «ЗАКАЗОВ 24Ч», «ВЫРУЧКА 24Ч». Каждая: label (mono uppercase 9.5px), value (26px/600 tnum), row(delta + sub) 10.5px mono, sparkline 16px высотой
- **Ряд 2:** grid 1.5fr / 1fr
  - слева: **Chart card** «Сообщения · 7 дней», ось Y (5 делений: 140/105/70/35/0), grid dashed 4 линии, bars с hover, подпись дня под каждым столбиком, значение над столбиком (9.5px mono)
  - справа: **System health**. Список из 4 строк: postgres / redis / telegram / backend. Каждая: зелёная точка + название 12.5px + meta (primary · 14.2) 10.5px mono + latency справа
- **Ряд 3:** grid 1.5fr / 1fr
  - слева: **Топ тенанты · 24ч** — таблица, ранг-бейдж в круге 18×18, правые колонки tnum
  - справа: **Последние события** — список: time (mono dim 60px) + chip (action type) + truncate message + tenant справа dim

### 5.3 Tenants list · `platform-tenants/page.tsx`

Скриншот: `screenshots/02-tenants.png`

- H1 «Тенанты» + count-pill «2» (accent-soft chip) + sub со сводкой. Справа: «Экспорт CSV» ghost + «+ Новый тенант» primary
- Toolbar: search (280px, иконка `⌕` слева) + segmented **Все · 2 / Active · 2 / Trial · 0 / Suspended · 0** + справа «Строк: 25/50/100»
- Таблица (bordered, внутри `fr-p0` карточки):
  - thead: `НАЗВАНИЕ · SLUG`, `СТАТУС`, `ТОВАРЫ`, `ДИАЛОГИ`, `ЗАКАЗЫ`, `ПОЛЬЗ.`, `СОЗДАН` (все right-aligned кроме первых двух), + checkbox-колонка + пустая 9-я
  - Колонка identity: avatar 28×28 (инициалы), название + slug mono 10.5 var(--ink-3)
  - Chip `● Активен` good
  - Правые числа tnum, последний столбец «Открыть →» link
- Pager в футере карточки: «Показано 1–2 из 2» + стрелки + номера

### 5.4 Tenant create modal · (реализация в `platform-tenants/page.tsx`)

Скриншот: `screenshots/03-tenant-create.png`

- Overlay: `fixed inset-0 bg-black/45 backdrop-blur-[2px]`
- Modal: max-w-[480px], bg-[var(--panel)], border var(--line), rounded-[10px], shadow lg
- Header: title «Новый тенант» 15px/600 + sub 11.5 var(--ink-3). Close ×
- Section «Организация»: label mono uppercase 10px + 3 поля (Название, Slug с префиксом `aicloser.app /`, 2 select'а в row 50/50)
- Section «Первый администратор»: 2 поля в row + checkbox «Отправить приглашение на email»
- Footer: «Отмена» ghost + «Создать тенант» primary, выровнены вправо

### 5.5 Tenant detail · `platform-tenants/[id]/page.tsx`

Скриншот: `screenshots/04-tenant-detail.png`

- Хедер: back button ← (ic-btn 28×28) + identity (avatar 40×40 «TD») + H1 «TechnoUz Demo Store» + chip good. Meta строка: slug mono, дата, владелец. Справа кнопки «✎ Редактировать» ghost + **«↳ Войти как Admin» warn** (оранжевая, обязательно использовать цвет warn как раньше)
- Tabs: Обзор / Пользователи · 3 / Товары · 24 / Диалоги · 10 / Заказы · 6 / Биллинг / Настройки. Активный — underline 2px var(--accent)
- 4 KPI (Товары, Диалоги, Заказы, Выручка · 30Д)
- Таблица пользователей тенанта (email mono, chip super_admin accent / store_owner info, status + dot good, last login tnum dim)
- Ряд 2: 30-дневный chart + «Конфигурация» — `<dl>` grid 150px/1fr (AI модель, Язык, Часовой пояс, Макс. сообщений, Макс. товаров, Telegram Bot, Канал)

### 5.6 Users · `platform-users/page.tsx`

Скриншот: `screenshots/05-users.png`

- H1 «Пользователи» + count «4» + sub «Super Admin · 2 · Store Owner · 2 · деактивированных 0»
- Toolbar: search + 3 select (Все тенанты / Все роли / Все статусы) + справа bulk-actions (disabled при 0 selected): «Активировать» / «Деактивировать»
- Таблица идентична tenants list по паттерну, добавлены колонки «РОЛЬ» (chip super_admin=accent, store_owner=info) и «ТЕНАНТ»

### 5.7 AI Monitor · `platform-ai-monitor/page.tsx` ⚠ ВАЖНО

Скриншот: `screenshots/06-ai-monitor.png`

**Ключевое исправление vs текущий код:** раньше колонка «Статус» показывала
модель (gpt-4o-mini). Теперь — две отдельные колонки: **«СТАТУС»** (ok/slow/error/no call) и **«МОДЕЛЬ»** (mono dim).

- H1 «AI Монитор» count «50» + sub: `<dot pulse good>` + «Авто-обновление · каждые 15с · следующее через 7с»
- Справа: «⏸ Пауза» ghost + «↻ Обновить» ghost
- 4 KPI: **ВЫЗОВОВ · 1Ч**, **P95 LATENCY** (tone warn если >4s), **ТОКЕНОВ · 1Ч** + стоимость, **TIMEOUT / ERR %** (tone bad)
- Toolbar: 4 select (Все тенанты / Все статусы / Все модели / Последний час) + справа подсказка «Показаны успешные · ошибки · медленные (>5с)»
- Таблица: `ВРЕМЯ` (mono dim tnum right) · `ТЕНАНТ` · `USER MSG` (truncate 320px) · `ИНСТРУМЕНТЫ` (mono xs dim) · `MS` (tnum, цвет зависит от порога: >5000 warn, error bad) · `ТОКЕНЫ` (tnum dim) · `СТАТУС` (chip: good=ok, warn=slow, bad=error, dim=— no call) · `МОДЕЛЬ` (mono xs dim) · `↗` detail link
- Строка с `error`: подсветка фона `color-mix(oklab, var(--bad) 6%, transparent)`

### 5.8 Billing · `platform-billing/page.tsx`

Скриншот: `screenshots/07-billing.png`

- H1 «Биллинг» + sub «Период: 22 мар — 21 апр · 30 дней». Справа «Экспорт CSV/PDF» ghost
- Карточка «Период»: 2 даты inline + segmented **7д / 30д / 90д / YTD** + «Обновить» primary sm
- 5 KPI: Сообщений / AI вызовов / Заказов / Диалогов / Стоимость (последний с accent tone на value)
- Ряд 2: chart 30 дней + «Распределение по моделям» (dist-row: chip-mono + bar + count + cost)
- Таблица «Использование по тенантам» с `<tfoot>` в стиле thead (bold, border-top var(--line))

### 5.9 Logs · `platform-logs/page.tsx`

Скриншот: `screenshots/08-logs.png`

- H1 «Аудит логи» + count «50» + sub «Записей 8,432 всего · retention 90 дней»
- Toolbar: search «actor email · entity id · trace id…» + 2 select + segmented **1ч / 24ч / 7д / 30д / custom**
- Таблица: ВРЕМЯ · АКТОР (avatar инициалы 24×24, email mono 12, meta xs dim) · ДЕЙСТВИЕ (mono xs chip: impersonate=accent, comment_*=info, tenant_*=warn, other=good) · СУЩНОСТЬ (mono xs dim) · ТЕНАНТ · TRACE (mono xs dim right)
- **Expand pattern:** клик по строке → раскрывает `<tr>` с `<td colspan="7">` ниже, содержащий `detail-grid` (2 колонки, 110px/1fr: admin_email, target_tenant, target_user, reason, ip, ua, session_id, duration). Футер деталей: «скопировать JSON · завершить сессию». Фон `var(--bg-2)`.

### 5.10 Settings · `platform-settings/page.tsx`

Скриншот: `screenshots/09-settings.png`

- H1 + sub «Глобальные значения для новых тенантов · изменения логируются»
- 2-колонный layout: sticky nav 180px (AI / Локализация / Лимиты / Регистрация / Критические / Интеграции) + body
- Body — секции в карточках:
  - **AI:** 2 set-row (model, fallback)
  - **Локализация:** 2 set-row
  - **Лимиты:** 4 set-row с `input.input-num` + суффиксом (шт/чел/день)
  - **Регистрация:** toggle-switch
  - **⚠ Критические** — карточка с `border var(--bad) 50%`. Красный заголовок. Maintenance mode + Read-only mode switches.
- Footer: «Несохранённых изменений нет» + «Отмена / Сохранить настройки»
- **Set-row pattern:** grid 1fr/auto, padding 12px 0, border-top dashed var(--hair). Слева: title 12.5px/500 + sub 10.5px var(--ink-3) max-width 380px. Справа: контрол.
- **Toggle switch:** 36×20, off=bg-2, on=accent. `::after` белый круг 16×16 translateX на 16px при `.on`.

---

## 6 · globals.css — новый шаблон

Полностью заменить содержимое `frontend/app/globals.css`:

```css
@import "tailwindcss";

/* ============================================================
   AI Closer Platform · tokens + base
   ============================================================ */

:root, [data-theme="light"] {
  --bg: #f6f5f0;
  --bg-2: #faf8f2;
  --panel: #ffffff;
  --panel-2: #fbfaf5;
  --line: #e3dfd4;
  --line-2: #d6d1c4;
  --hair: #ece7d9;
  --ink: #141210;
  --ink-2: #5a544c;
  --ink-3: #8a847a;
  --ink-4: #b2ab9f;
  --accent: #2a4a7f;
  --accent-soft: #2a4a7f14;
  --accent-ring: #2a4a7f55;
  --good: #2f6a3f;  --good-soft: #2f6a3f14;
  --warn: #9c6b00;  --warn-soft: #9c6b0014;
  --bad:  #9c2a2a;  --bad-soft:  #9c2a2a14;
  --info: #1e5a9c;  --info-soft: #1e5a9c14;
  --shadow: 0 1px 0 #00000008 inset, 0 4px 14px -8px #00000018;
}

[data-theme="dark"] {
  --bg: #0a0d12;
  --bg-2: #0f1319;
  --panel: #131821;
  --panel-2: #171d27;
  --line: #232a36;
  --line-2: #2b3442;
  --hair: #1b2230;
  --ink: #e7ecf3;
  --ink-2: #9aa3b2;
  --ink-3: #6a7386;
  --ink-4: #4a5264;
  --accent: #7c8cff;
  --accent-soft: #7c8cff1a;
  --accent-ring: #7c8cff55;
  --good: #4ade80;  --good-soft: #4ade801a;
  --warn: #f5b454;  --warn-soft: #f5b4541a;
  --bad:  #f87171;  --bad-soft:  #f871711a;
  --info: #60a5fa;  --info-soft: #60a5fa1a;
  --shadow: 0 1px 0 #ffffff06 inset, 0 8px 24px -12px #00000066;
}

html, body {
  background: var(--bg);
  color: var(--ink);
  font-feature-settings: "ss01", "cv11";
}

@layer utilities {
  .tnum { font-variant-numeric: tabular-nums; }
  .mono { font-family: 'Geist Mono', ui-monospace, monospace; }
  .label-mono {
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 9.5px; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.16em;
    color: var(--ink-3);
  }
}

/* существующие @keyframes slide-up и прочее — сохранить */
```

Добавить в `app/layout.tsx` импорт Geist Mono:
```tsx
import { Inter, Geist_Mono } from "next/font/google";
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });
// добавить geistMono.variable в className <html>
```

---

## 7 · Процесс работы

Рекомендуемый порядок для Claude Code:

1. **Сначала токены:** переписать `globals.css` (раздел 6). Добавить Geist Mono. Убедиться, что `lib/theme.ts` ставит `data-theme` на `<html>` (сейчас так и должно быть).
2. **Sidebar:** `components/platform-sidebar.tsx` — только классы и структура groups/items (раздел 5.1). Открыть скриншот `01-overview.png` и свериться.
3. **Overview** — самая насыщенная карта компонентов, если сделать её — остальные шаблоны повторяются. Скриншот 01.
4. Дальше по скриншотам 02 → 09 в порядке: tenants → tenant_create → tenant_detail → users → **ai-monitor (проверить фикс колонки «Статус»)** → billing → logs → settings.
5. После каждого экрана: `npm run dev` → визуальное сравнение со скриншотом → `pnpm typecheck`.

---

## 8 · Чего избегать (важно)

- ❌ **Не добавлять** shadcn/ui, radix, headlessui или другие UI-либы — это явное требование
- ❌ **Не менять** роуты, имена файлов, ключи localStorage, API-пути, формат ответов
- ❌ **Не переводить** русские строки — оставлять как есть
- ❌ **Не трогать** `app/(auth)/*` и `app/(admin)/*`
- ❌ **Не использовать** градиенты на кнопках или плашках (кроме опционально глоу на Login — но Login не входит в скоуп)
- ❌ **Не терять** функцию «Войти как Admin» — это важное действие, оно остаётся оранжевым (warn)
- ❌ **Не убирать** mono-шрифт на числах, slug, timestamp — это часть DNA

---

## 9 · Файлы в пакете

```
design_handoff_platform_redesign/
├── README.md                                  ← этот файл
├── reference/
│   └── platform-redesign.html                 ← открыть в браузере, вкладка Full Redesign
└── screenshots/
    ├── 01-overview.png
    ├── 02-tenants.png
    ├── 03-tenant-create.png
    ├── 04-tenant-detail.png
    ├── 05-users.png
    ├── 06-ai-monitor.png                     ← обратить внимание: 2 отдельные колонки status/model
    ├── 07-billing.png
    ├── 08-logs.png
    └── 09-settings.png
```

---

## 10 · Промпт для старта в Claude Code

Скопируйте целиком:

```
Read design_handoff_platform_redesign/README.md carefully.

We are doing a style-only refresh of the Super Admin panel (platform route
group) in this Next.js 15 + React 19 + TypeScript + Tailwind v4 codebase.

Scope (only touch these):
- frontend/app/globals.css
- frontend/app/layout.tsx (only to add Geist Mono font)
- frontend/app/(platform)/layout.tsx
- frontend/components/platform-sidebar.tsx
- frontend/app/(platform)/platform-overview/page.tsx
- frontend/app/(platform)/platform-tenants/page.tsx
- frontend/app/(platform)/platform-tenants/[id]/page.tsx
- frontend/app/(platform)/platform-users/page.tsx
- frontend/app/(platform)/platform-ai-monitor/page.tsx
- frontend/app/(platform)/platform-billing/page.tsx
- frontend/app/(platform)/platform-logs/page.tsx
- frontend/app/(platform)/platform-settings/page.tsx
- frontend/components/ui/*  (only if used by the above)

Do NOT touch:
- frontend/app/(auth)/*     (Login stays as-is)
- frontend/app/(admin)/*    (tenant admin routes stay as-is)
- any api.ts / types.ts / routes / file names / component props / API calls

Follow the README section by section. Start with globals.css (section 6),
then sidebar, then overview, then the remaining 7 pages in order. For each
page open the matching screenshot in screenshots/ and match pixel-by-pixel.

Keep all Russian strings. Keep dark theme as the default via data-theme on
<html>. Keep the existing lib/theme.ts theme switcher logic.

Report back after each page so I can review.
```

---

Удачи!
