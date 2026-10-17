# LabelCheck

[![CI](https://github.com/AshishYadav0704/labelcheck/actions/workflows/ci.yml/badge.svg)](https://github.com/AshishYadav0704/labelcheck/actions/workflows/ci.yml)

Scan a packaged food (label photo, barcode, or typed label text) and get a clear,
evidence-based report:

- **Health score and grade** (0–100, A–E), with Nutri-Score, processing level (NOVA)
  and front-of-pack style **HIGH FAT / SUGAR / SALT** warnings
- **Every ingredient and additive checked** against WHO, FSSAI, JECFA (FAO/WHO), IARC
  and EFSA reference data: safe daily intake, cancer classification, FSSAI status,
  bans and warnings in other countries
- **Linked long-term health effects** of regular consumption, each with an evidence
  level and a source link
- **Personal advice** by age group, health conditions (diabetes, high BP, kidney
  disease, pregnancy, PKU…), allergies and diet (vegetarian, vegan, Jain)
- **Healthier alternatives**: better-scoring products from other users' scans and
  Open Food Facts, plus simple home swaps
- **Long-term video**: a short portrait animation of what regular intake could mean
  over 1–20 years (an illustration, not a medical prediction)
- English and Hindi, installable on phones (PWA), works without any paid API

AI never decides a score or a health claim. Scores come from fixed, documented rules
(see [docs/METHODOLOGY.md](docs/METHODOLOGY.md)). AI only reads label photos, and the
user checks and corrects what was read before the report is made.

## How it works

```
 photo ──► AI vision (Claude or Gemini) ──┐
       └─► offline OCR (Tesseract) ───────┤                         ┌─► report (score, warnings,
 typed label text ──► text parser ────────┼─► user review ─► rules ─┤   additives, risks, advice)
 barcode ──► Open Food Facts ─────────────┘    (edit values)  engine ├─► alternatives
                                                                     └─► long-term video (MP4/WebM)
```

| Part | Where |
|---|---|
| API + rules engine (Python, Starlette) | `backend/app` |
| Reference data (additives, limits, health links, swaps) | `backend/app/data/*.json` |
| Web app (installable PWA, plain JS, no build step; English and Hindi, light and dark) | `web/` |
| Tests (99) | `backend/tests` |
| Deployment (Docker, Caddy, Render) | `Dockerfile`, `docker-compose.yml`, `deploy/`, `render.yaml` |

## Run it locally

You need Python 3.11 or newer (tested on 3.13) and, for offline photo reading, Tesseract
(`sudo apt install tesseract-ocr` / `brew install tesseract` / the
[Windows installer](https://github.com/UB-Mannheim/tesseract/wiki)).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. With no API key, photos are read by OCR and summaries
use templates. To use AI label reading, set **one** key before starting:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # Claude (default model: claude-sonnet-5-5)
# or
export GEMINI_API_KEY=...               # Gemini (default model: gemini-3.6-flash)
```

Run the tests:

```bash
cd backend && python -m unittest discover -s tests -t .
```

## Deploy

Phone cameras only work on **HTTPS** pages, so deploy behind HTTPS.

### Any Linux server (VPS) with Docker

1. Point your domain's DNS A record at the server.
2. On the server:

```bash
git clone https://github.com/AshishYadav0704/labelcheck.git && cd labelcheck
cp .env.example .env          # set DOMAIN, OFF_USER_AGENT, and optionally an AI key
docker compose up -d --build
```

Caddy gets a free HTTPS certificate automatically. Data (product database, saved
reports, video cache) is kept in the `labelcheck-data` volume. Back it up with
`docker compose cp app:/data ./backup`.

### Render (managed)

In Render choose **New > Blueprint** and select the `AshishYadav0704/labelcheck` repository.
`render.yaml` creates the service with a persistent disk. Add your API key in the
dashboard.

### Android / iPhone app

The web app is a Progressive Web App: open the site on a phone and choose **Add to
Home screen** / **Install app**. To publish on Google Play without writing a native app,
wrap the deployed site as a Trusted Web Activity with
[PWABuilder](https://www.pwabuilder.com) or Bubblewrap. Both take the site URL and
produce a Play Store package.

## Configuration

All settings are environment variables with safe defaults. See `.env.example` for
the full list. The main ones:

| Variable | Default | What it does |
|---|---|---|
| `AI_PROVIDER` | `auto` | `auto`, `anthropic`, `gemini` or `none` |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | – / `claude-sonnet-5-5` | Claude label reading and summaries |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | – / `gemini-3.6-flash` | Gemini label reading and summaries |
| `OCR_ENABLED` | `true` | Tesseract fallback when no AI is set or the AI service is down |
| `DATA_DIR` | `backend/data_store` | SQLite database and video cache |
| `OFF_USER_AGENT` | – | Identify your app to Open Food Facts (include an email) |
| `RATE_LIMIT_AI_PER_MIN` / `_PER_DAY` | `8` / `60` | Per-IP limits on photo reading (protects your AI bill) |
| `TRUST_PROXY_HEADERS` | `false` | Set `true` only behind a proxy that overwrites `X-Forwarded-For` |

## API

All under `/api/v1`. Errors are JSON: `{"error": "...", "request_id": "..."}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Status and which label reader is active |
| GET | `/meta` | Categories, conditions, diets, allergen groups, data versions |
| GET | `/additives?q=` · `/additives/{code}` | Search or look up an additive (INS/E number or name) |
| POST | `/label/read` | Multipart `files` (1–4 photos) → product draft to review |
| POST | `/label/text` | `{"text": "...", "name": "..."}` → product draft to review |
| POST | `/analyze/product` | `{"product": {...}, "profile": {...}}` → full report |
| POST | `/analyze/label` | Photos → full report in one step (no review) |
| GET | `/products/barcode/{barcode}` | Barcode → report (local database, then Open Food Facts) |
| GET | `/reports/{id}?profile=` | Saved report, re-personalised |
| GET | `/reports/{id}/simulation` | Long-term model data (`per_week`, `years`, `age_group`) |
| GET | `/reports/{id}/video.mp4` · `.webm` | Long-term video |

`profile` is `{"age_group": "adult", "diet": "vegetarian", "conditions": ["diabetes"], "allergies": ["milk"], "language": "hi"}`.

## Privacy

- Label photos are processed in memory, stripped of metadata (including GPS) and never stored.
- The health profile is stored only on the user's phone and sent with each request. It
  is never saved on the server.
- The server stores product data (to power alternatives and shareable report links)
  and nothing that identifies a person.

## Scaling

One container handles a college or city-scale launch comfortably. The rate limiter and
video render locks are in-process and the database is SQLite (WAL mode), so run
**one worker per instance**. To run several instances, move rate limiting to Redis
and the database to PostgreSQL (`db.py` is the only module that touches SQL).

## Important

LabelCheck gives general information based on the label and public standards. It is
**not medical advice**. Product data is partly from [Open Food Facts](https://world.openfoodfacts.org)
under the Open Database License, and the app shows this attribution wherever that data is used.
Have a qualified nutritionist review the reference data before a public launch (see
METHODOLOGY.md §10). Describe products factually and avoid naming brands in marketing
material.
