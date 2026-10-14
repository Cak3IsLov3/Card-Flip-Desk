# Card Flip Desk

[![CI](https://github.com/Cak3IsLov3/Card-Flip-Desk/actions/workflows/ci.yml/badge.svg)](https://github.com/Cak3IsLov3/Card-Flip-Desk/actions/workflows/ci.yml)

A Django app that tracks the full sales cycle of sports cards, from purchase
to sale on eBay, and works out what is really left after all fees. It also
helps with pricing, photos, writing listings and warning you about stock that
is not moving.

Built as a portfolio project, but meant to be used for real: every amount is
a `Decimal`, business rules live in testable services, uploads are handled
safely, OAuth runs against an external provider, and the app keeps working
when eBay goes down.

![Dashboard](docs/screenshots/01-dashboard.jpg)

| | |
|---|---|
| ![Charts](docs/screenshots/02-dashboard-charts.jpg) **Dashboard:** revenue and profit per month, margin per set, fastest and slowest sellers | ![Inventory](docs/screenshots/03-inventory.jpg) **Inventory:** filters (also by variant), main photo, variants, condition, age with colour and label |
| ![Card form](docs/screenshots/04-card-form.jpg) **Card form:** several variants per card; the parallel name and serial number appear when Parallel is ticked | ![Photos](docs/screenshots/05-photos.jpg) **Photos:** front and back, main photo, ordering, checklist |
| ![Listing generator](docs/screenshots/06-listing-generator.jpg) **Listing generator:** title of at most 80 characters with the variants, checks, profit at the asking price | ![Needs attention](docs/screenshots/07-attention.jpg) **Needs attention:** a suggestion per card; a price drop shows the new profit straight away |
| ![Calculator](docs/screenshots/08-calculator.jpg) **Calculator:** from price to profit and from profit to price | ![API docs](docs/screenshots/09-api-docs.jpg) **REST API:** OpenAPI docs with token authentication |

*The card images are generated placeholders from `seed_demo`.*

---

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Docker](#docker)
- [Architecture](#architecture)
- [Business rules](#business-rules)
- [Security](#security)
- [eBay integration](#ebay-integration)
- [REST API](#rest-api)
- [Configuration](#configuration)
- [Tests](#tests)
- [Known limitations and next steps](#known-limitations-and-next-steps)

## Features

| | |
|---|---|
| **Inventory** | Cards with purchases, filters and search (HTMX), inventory value, counts per set. Several variants per card (Rookie, Auto, Parallel, Insert) with the parallel name and serial number (23/50) or insert name (names you used before are suggested), and a condition from a fixed list. CSV import with column mapping; bad rows end up in a report without blocking the rest. |
| **Calculator** | Commission, payment fees, net, profit and margin. Also in reverse: "I want €X profit" gives the lowest asking price. Rates live in fee profiles, not in the code. |
| **Photos** | 1–6 per card, with a main photo and ordering. Resized, thumbnailed, EXIF removed, and only visible to the owner. |
| **Sales and dashboard** | Fees recorded at the rate that applied on the sale date. Profit per card, set and month, weighted margin, days to sale, and money tied up in stock. |
| **Listing generator** | Templates with placeholders, length check, photo checklist, copy buttons and profit at the asking price. |
| **Stale inventory** | Per-user thresholds (30/60/90), colour coding, "Needs attention" with a suggestion per card, pinning, weekly email. |
| **Price advice** | Active eBay listings (Browse API) next to your own sales history: minimum, median, maximum and a suggested price. |
| **REST API** | DRF with token authentication, own data only, OpenAPI docs. |

## Quick start

Requires Python 3.12+ (developed on 3.14; CI runs 3.12 and 3.14).

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt  # macOS/Linux: .venv/bin/pip
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo          # demo account with cards, sales and photos
.venv\Scripts\python manage.py runserver
```

`requirements.txt` holds what the app needs to run; `requirements-dev.txt` adds the
test and lint tools.

Open <http://localhost:8000>. The demo account's login details are in
[`seed_demo.py`](inventory/management/commands/seed_demo.py); the command
refuses to run without `DEBUG`. You can also create your own account via
*Sign up*, which gives you a sample fee profile.

Without eBay keys everything works except the active listings in the price
advice. See [Configuration](#configuration).

## Docker

[`compose.yaml`](compose.yaml) runs the app with PostgreSQL 17. The image
([`Dockerfile`](Dockerfile)) uses gunicorn, serves static files with WhiteNoise,
runs as a non-root user and applies migrations on start.

```bash
cp .env.example .env
```

Fill in `DJANGO_SECRET_KEY`, `TOKEN_ENCRYPTION_KEYS` and `POSTGRES_PASSWORD` in
`.env` (the commands to generate them are in the file). Compose refuses to start
without the first two. `.env` is in `.gitignore`.

```bash
docker compose up -d --build
```

```bash
docker compose exec web python manage.py createsuperuser
```

Open <http://localhost:8000> and sign up or log in. Useful commands:

| What | Command |
|---|---|
| Logs (also emails, without SMTP) | `docker compose logs -f web` |
| Weekly digest (run from cron) | `docker compose run --rm web python manage.py send_stale_digest` |
| Database backup | `docker compose exec db pg_dump -U cardflipdesk cardflipdesk > backup.sql` |
| Stop, keep data | `docker compose down` |
| Stop and delete all data | `docker compose down -v` |

- **Data** lives in two named volumes: `pgdata` (database) and `media` (photos).
  Photos are never served as public files; they go through the app's access check.
- **HTTPS:** put the container behind a TLS proxy (Caddy, Traefik, nginx), set
  `DJANGO_HTTPS=1` and use `https://` in `DJANGO_CSRF_TRUSTED_ORIGINS` and
  `SITE_URL`. That turns on the HTTPS redirect, secure cookies and HSTS.
- **Health:** `/health/` checks the database and is used by the container
  healthcheck.
- `seed_demo` refuses to run in the container, because `DEBUG` is off.

## Architecture

### Apps and dependencies

```mermaid
flowchart LR
    subgraph Web["Web (Django views + HTMX)"]
        direction TB
        V[views / templates]
    end
    API[api<br/>DRF viewsets]

    subgraph Domain
        direction TB
        INV[inventory<br/>Card · Purchase · CardPhoto<br/>photos · aging · digest · csv_import]
        FIN[finance<br/>calculator · FeeProfile]
        SAL[sales<br/>Listing · Sale · services<br/>dashboard · listing_generator]
        PRI[pricing<br/>advice · PriceSnapshot]
    end
    EB[ebay<br/>client · oauth · crypto]
    EXT[(eBay REST API)]

    V --> INV & SAL & FIN & PRI & EB
    API --> INV & SAL & FIN
    SAL --> INV & FIN
    INV --> FIN
    PRI --> EB & SAL & INV & FIN
    EB --> EXT
```

| App | Responsible for |
|---|---|
| `finance` | `calculator.py`: pure functions without a database (Decimal, rounding, reverse calculation). `FeeProfile` per category with `valid_from`. |
| `inventory` | Cards, purchases and photos. `photos.py` (validation, re-encoding, management), `storage.py` (private storage), `aging.py` (age and suggestions), `digest.py` (weekly email), `csv_import.py`. |
| `sales` | Listings, sales and templates. `services.register_sale`, `dashboard.py`, `listing_generator.py`. |
| `pricing` | Price advice: filtering eBay results, own history, suggested price, snapshots. |
| `ebay` | HTTP client with tokens, retries, budget and ETag cache; Authorization Code Flow; encrypted token storage. Knows nothing about the rest of the app. |
| `api` | Serializers and viewsets. No business rules of its own: everything goes through the same services. |

### Layers

```
view / API view   thin: validate input, call a service, render
      │
service           business rules: register_sale, add_photos, stale_items, build_advice, generate
      │
queryset methods  every aggregation in the database: with_cost, with_profit, with_age_start, per_set …
      │
models            data + constraints (one main photo, increasing thresholds, unique tokens)
```

A few choices that come back throughout:

- **A pure arithmetic core.** `finance/calculator.py` knows nothing about
  Django. The web app, the API, the listing generator, price advice and the
  attention list all use the same `calculate()` and `required_price()`.
- **An explicit "today".** `aging`, `dashboard`, `digest` and `build_advice`
  receive `today` as an argument, so boundaries (exactly on the threshold, a
  day before or after) can be tested without touching the clock.
- **A fixed number of queries.** Lists and dashboards use annotations,
  subqueries and `Prefetch`. Tests use `django_assert_max_num_queries` to make
  sure the count does not grow with the data.
- **Amounts recorded at the moment itself.** A sale stores its commission and
  fees at the rate that applied then, so a rate change never alters past
  profits.
- **One path for the rules.** Photo validation, recording a sale and the
  listing generator are services. The web app and the API call the same code.

### A request end to end: price advice

```mermaid
sequenceDiagram
    participant U as User
    participant V as pricing.views
    participant A as pricing.advice
    participant C as ebay.client
    participant DB as CachedResponse
    participant E as eBay Browse API

    U->>V: POST /pricing/card/42/ (HTMX)
    V->>A: build_advice(card, today)
    A->>C: search_items(query)
    C->>DB: response younger than 6 hours?
    alt fresh in cache
        DB-->>C: data
    else expired or missing
        C->>C: application token (cache) and daily budget
        C->>E: GET item_summary/search + If-None-Match
        alt 200 / 304
            E-->>C: data (or 304 → cache)
            C->>DB: store with ETag
        else 429 / 5xx / network
            C->>C: backoff, retry (max. 3×)
            C-->>A: old copy (stale) or EbayUnavailable
        end
    end
    A->>A: filter currency + player name, statistics, own history
    A->>A: suggested price → calculator (profit, margin)
    A-->>V: Advice
    V-->>U: HTML fragment
```

### Folders

```
config/        settings, urls, sign-up
inventory/     cards, purchases, photos, stale inventory, CSV import, management commands
finance/       calculator and fee profiles
sales/         listings, sales, dashboard, listing generator
pricing/       price advice
ebay/          eBay client, OAuth, encryption
api/           REST API (DRF + drf-spectacular)
templates/     Django templates (HTMX fragments start with _)
static/        CSS, dashboard.js (Chart.js), listing.js
tests/         pytest-django; respx for eBay
docs/          screenshots
```

**Stack:** Django 6.1, Django REST Framework, drf-spectacular, HTMX 2,
Chart.js 4, Pillow, httpx, cryptography (Fernet), SQLite (PostgreSQL works
too), pytest-django and respx.

## Business rules

### Calculator

- **`Decimal` only:** a float raises a `TypeError`.
- **Basis:** commission and payment fees are charged on the price plus the
  shipping charged.
- **Rounding:** every cost item is rounded to cents on its own with
  `ROUND_HALF_UP`. Net and profit are sums of rounded items.
- **Margin:** profit / gross × 100, rounded to 0.1; `None` when gross is 0.
- **Reverse calculation:** returns the **lowest** price that reaches the
  target profit. Because of rounding that can be a cent below the "naive"
  price (a profit of €5.24 needs €9.99, not €10.00). Tested over 136 target
  profits and four fee profiles.

Rates live in `FeeProfile`, per category and with a `valid_from`. The starter
profile (13.25% + €0.35) is an example; check the current eBay rates.

### Dashboard

- **Margin is weighted:** total profit ÷ total revenue. An average of
  individual margins would weigh a €1 card the same as a €50 one.
- **Days to sale:** counted from "listed since", otherwise from the first
  purchase.
- **Period filter:** applies to all sales figures; inventory figures always
  apply to today. Months without sales show as zero in the chart.
- **Charts:** one y-axis per chart, colours with separate steps for light and
  dark mode that were checked for colour blindness and contrast, and a table
  below each chart.

### Listing generator

- **Patterns:** for example `{year} {set} {player} #{number} {variant} {condition}`.
  Unknown placeholders are rejected when you save a template.
- **Empty fields leave nothing behind:** no stray `#`, `()` or double spaces,
  and a line `Variant:` without a value is dropped.
- **Title max. 80 characters:** anything longer is cut at a word boundary,
  with a warning that says what was dropped.
- **Characters:** Unicode is normalised (NFC) and control characters are
  removed. Card data is never re-read as a pattern.
- **Variants:** `{variant}` lists every variant in a fixed order and uses the
  name when you entered one, e.g. "Rookie Gold Refractor 23/50". `{parallel}`,
  `{serial}` and `{insert}` are available for templates that want them
  separately.

### Card details

- **Variants:** a card can be several at once (a rookie auto, a numbered
  parallel insert …); nothing ticked means a base card. They are stored as a
  list in a fixed order without duplicates.
- **Parallel and insert:** "Which parallel?", "Serial number" and "Which
  insert?" appear only while that variant is ticked, and are cleared when you
  untick it. A serial number is `23/50` or `/50`; a number above the print run
  is rejected.
- **Remembered names:** parallel and insert names you typed before are
  suggested in those fields (most used first, only from your own cards). A new
  name can always be typed.
- **Price advice** searches on the print run (`/50`), not the exact copy
  (`23/50`), which would find almost nothing.
- **Condition** is a choice: Mint, Near Mint, Excellent, Very Good, Good, Fair,
  Poor. The CSV import also understands abbreviations such as `NM`, `NM-MT` and
  `EX`, and several variants in one cell (`Rookie/Auto`, `rookie auto`).

### Stale inventory

- **Age:** counted from "listed since", otherwise from the first purchase
  (without a purchase: from when the card was entered). Calculated in the
  database with `with_age_start()`.
- **Thresholds:** per user. **A card exactly on the threshold already counts.**
- **Suggestions per level:**
  - 30+ days: improve the photos or the title;
  - 60+ days: lower the price, with the new profit and margin shown and a
    warning if it becomes a loss;
  - 90+ days: bundle with cards from the same set, or write it off.
- **Pinning:** a card pinned until a date gives no alerts until then. Actions
  are logged in `InventoryNote`.
- **Weekly email:** `python manage.py send_stale_digest` sends **nothing
  when there is nothing to report**, at most once every 7 days, and can be
  turned off. Options: `--dry-run`, `--force`, `--today YYYY-MM-DD`. The
  command is independent of the scheduler:

```bash
# cron, every Monday at 08:00
0 8 * * 1 cd /path/to/card-flip-desk && .venv/bin/python manage.py send_stale_digest
```

```bash
schtasks /Create /SC WEEKLY /D MON /ST 08:00 /TN "Card Flip Desk digest" /TR "\"C:\path\.venv\Scripts\python.exe\" \"C:\path\manage.py\" send_stale_digest"
```

## Security

| Topic | Measure |
|---|---|
| Access | Every view and API queryset filters on the owner. Another user's object returns **404**, not 403, so you cannot probe which ids exist. In the API, `IsOwner` checks the object again, and references to another user's card or profile give the same error as an unknown id. Tested per endpoint. |
| Uploads | The type is decided by the **contents** (Pillow), not the extension. Size and dimensions are checked **before** decoding (against decompression bombs). Everything is re-encoded, which drops EXIF (GPS), XMP and text chunks. File names are random `uuid4` names. |
| Serving photos | Stored outside the public folder; `storage.url()` fails on purpose. Served through a view that checks ownership, with `Cache-Control: private`. Files are only deleted after a successful commit. |
| Tokens | eBay tokens are stored encrypted (Fernet, key rotation with `MultiFernet`). Outside `DEBUG` the app refuses to store them without a key. The OAuth `state` is kept in the session, compared in constant time and used only once. |
| External data | eBay titles are escaped, amounts are read as `Decimal`, and links are only allowed to https eBay domains (`evil-ebay.attacker.com` and `javascript:` are dropped). |
| Other | CSRF on every form and HTMX request. Redirects back (`next`) only go to our own host. Token requests through the API are limited to 10 per minute. Secrets live in environment variables. |

## eBay integration

**What eBay allows** (checked on developer.ebay.com, October 2026):

- **Searching:** `GET /buy/browse/v1/item_summary/search` works with an
  **application token** (client credentials, scope
  `https://api.ebay.com/oauth/api_scope`). Limit: 5,000 calls per day; tokens
  1,000 per day, valid for 2 hours. Without a filter, only Buy It Now
  listings are returned.
- **Production:** the Buy APIs are partly *Limited Release*. Anyone with a
  developer account can use the **sandbox**; for **production** you apply for
  access through the eBay Partner Network, and approval is not guaranteed.
- **Sold items:** the Marketplace Insights API is only available on a
  limited basis. That is why your own sales history weighs more.
- **Placing listings:** goes through the Sell APIs with a **user token**
  (Authorization Code Flow with a RuName). That flow is built and tested but
  not used anywhere yet: the app reads and calculates first.

**How the client works:**

- **Application token:** stays in the cache until 5 minutes before it
  expires. On a 401 the client requests a new token once.
- **Retries:** on network errors, 429 and 5xx there are up to 3 retries with
  exponential backoff and jitter. A `Retry-After` takes precedence, but the
  client never waits longer than 10 s.
- **Daily budget:** 4,500 calls by default, below the eBay limit.
- **Cache:** GET responses stay fresh for 6 hours and are then revalidated
  with `If-None-Match`.
- **When eBay is down:** the app shows the last saved version with a notice,
  or otherwise only your own history. The rest of the app keeps working.

**Price advice:**

- **Search query:** built from the card data and editable.
- **Filters:** only listings in the configured currency and with the
  player's surname in the title.
- **Suggested price:** the median of your own sales (from 2 onwards),
  otherwise the median of the asking prices, with a clear note that those
  are not sale prices.
- **Snapshots:** every fetch creates a `PriceSnapshot`.

## REST API

Base URL `/api/v1/`. Interactive docs live at **`/api/v1/docs/`**, the
OpenAPI 3 schema at `/api/v1/schema/` (validates without warnings). You manage
your token on the **API** page in the app.

| Endpoint | Methods |
|---|---|
| `cards/` (`?q=&status=&set_name=&year=`) | CRUD, `POST cards/{id}/generate-listing/` |
| `purchases/` | CRUD |
| `photos/` | upload (multipart), list, `PATCH` label, `DELETE`, `POST {id}/set-main/`, `GET {id}/file/`, `GET {id}/thumbnail/` |
| `listings/`, `listing-templates/` | CRUD (a sold listing is frozen) |
| `sales/` | list, detail, create (fees from the fee profile) |
| `fee-profiles/` | CRUD |
| `calculator/`, `calculator/reverse/` | `POST` |
| `auth/token/` | `POST` username and password → token |

```bash
curl -H "Authorization: Token <token>" "http://localhost:8000/api/v1/cards/?status=for_sale"
```

- **Amounts** are decimal strings (`"5.24"`), not floats.
- **Lists** are paginated per 50, with a limit of 2,000 requests per hour per
  user.

## Configuration

Everything comes from environment variables; the defaults are for local
development.

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev value | **Always set outside local development** |
| `DJANGO_DEBUG` | `1` | `0` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated, with scheme: `https://cards.example.com` |
| `DJANGO_HTTPS` | `0` | `1` behind a TLS proxy: HTTPS redirect, secure cookies, HSTS |
| `DJANGO_HSTS_SECONDS` | `3600` | HSTS duration with `DJANGO_HTTPS=1`; raise it once HTTPS works everywhere |
| `DATABASE_URL` | empty (SQLite) | `postgres://user:password@host:5432/name` |
| `TOKEN_ENCRYPTION_KEYS` | derived in DEBUG | Fernet key(s); the first one encrypts. Create one: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `PRIVATE_MEDIA_ROOT` | `private_media/` | Folder for photos (do not serve it publicly) |
| `SITE_URL` | `http://localhost:8000` | For links in emails |
| `DEFAULT_FROM_EMAIL` | `noreply@localhost` | Sender |
| `EMAIL_HOST` | empty | SMTP server; without it emails are printed to the console/log |
| `EMAIL_PORT`, `EMAIL_USE_TLS` | `587`, `1` | SMTP port and STARTTLS |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | empty | SMTP login |
| `DJANGO_LOG_LEVEL` | `INFO` | Console log level |
| `EBAY_ENVIRONMENT` | `sandbox` | `sandbox` or `production` |
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | empty | From *Application Keys* on developer.ebay.com |
| `EBAY_RUNAME` | empty | Only for connecting a user account; accept URL = `SITE_URL` + `/ebay/callback/` |
| `EBAY_MARKETPLACE_ID`, `EBAY_CURRENCY` | `EBAY_NL`, `EUR` | Marketplace and currency for price advice |
| `EBAY_CATEGORY_IDS` | empty | Optional, to narrow the search |
| `EBAY_DAILY_CALL_BUDGET`, `EBAY_CACHE_SECONDS` | `4500`, `21600` | Budget and cache duration |

## Tests

```bash
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
```

**GitHub Actions** ([`ci.yml`](.github/workflows/ci.yml)) runs on every push to
`main` and on every pull request:

- **Lint:** Ruff with pyflakes, pycodestyle, import sorting, bugbear,
  pyupgrade, Django and bandit (security) rules. The configuration is in
  [`pyproject.toml`](pyproject.toml).
- **Tests:** on Python 3.12 and 3.14, `manage.py check`, a check that no
  migrations are missing, OpenAPI schema validation (warnings fail the build)
  and the full pytest suite.
- **PostgreSQL:** all migrations and the full suite against PostgreSQL 17.
- **Docker:** builds the image, starts Compose with throwaway secrets, waits for
  the healthchecks, fetches `/health/`, the login page and a static file, and
  runs `check --deploy`.

278 tests, without a network (eBay is mocked with respx), in about a minute
and a half. A selection:

- **Calculator:** known examples with exact `Decimal`s, rounding boundaries
  (0.005 → 0.01, 0.025 → 0.03), zero and negative profit, and a reverse
  calculation that works back to exactly the same profit.
- **Photos:** valid and invalid files, a non-image with `.jpg`, too large,
  thumbnail dimensions, EXIF gone (including GPS), at most one main photo,
  files removed when a card is deleted, another user gets a 404.
- **CSV import:** bad rows reported with the right line number, the rest goes
  through; several variants per cell, condition abbreviations and serial numbers.
- **Card details:** variant order and duplicates, names cleared when a variant is
  unticked, serial number validation, remembered parallel and insert names
  (own cards only), the variant filter, and the title and search
  query built from them.
- **Title generator:** exactly 80 characters, 81 characters, missing fields,
  special characters and Unicode normalisation.
- **Stale inventory:** 29, 30 and 31 days, pinned cards, a loss on a price
  suggestion, the dashboard total, and a mail command that sends nothing when
  there is nothing to report.
- **eBay client:** token caching and renewal, 429 with `Retry-After`, 5xx with
  growing backoff, ETag/304, falling back to old data, 401 → new token, daily
  budget, encryption and key rotation, OAuth `state`.
- **Access:** for every endpoint (web and API), another user can neither see
  nor change anything.
- **Data migrations:** the switch to English placeholder names and category, and
  free-text conditions mapped to the new choices (unknown text moves to the notes).

## Known limitations and next steps

- **Seller Hub import of sales** is still missing. It needs a real export to
  base the column format on.
- **Bundling** and **writing off** are suggested, but there is no action yet
  that carries them out.
- **Profit on a price drop and in the price advice** is calculated without
  shipping.
- **Real eBay prices** require production access to the Buy APIs (see
  above); the sandbox contains test data.
- **API tokens** (DRF authtoken) are stored unencrypted in the database.
  Treat them like passwords; you can revoke them in the app.
- **Optional extensions** from the plan: a grading ROI calculator, an export
  for tax returns and Docker Compose.
