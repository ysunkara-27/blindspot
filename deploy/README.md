# Deploying Blindspot at https://ysunkara.com/blindspot

Architecture: one Docker container on a **Hugging Face Space** (Docker SDK, free CPU tier) serves the built
frontend and the FastAPI API under the base path `/blindspot`. The Vercel-hosted site `ysunkara.com` proxies
`/blindspot/*` to the Space. Everything except `/blindspot/api/health`, `/blindspot/api/about` and
`/blindspot/api/access` sits behind an **access code**; the expert review page and the cohort dashboard need a
second **review code**.

> **The dataset must stay behind the access code.** SPEC §20: no public redistribution of dataset images. The
> image bundle lives in a **private** HF dataset repo, the container image contains no data, and every image
> request needs the access cookie. Never make the dataset repo public; never disable `BLINDSPOT_ACCESS_CODE`
> on a public URL.

## Files

| file | what |
|---|---|
| `deploy/Dockerfile` (canonical) and `/Dockerfile` (identical copy, HF needs it at the repo root) | 2 stages: Vite build with `VITE_BASE_PATH=/blindspot/`, then python:3.12-slim + uv (runtime deps only, **no `ml` extra**, no torch). Non-root uid 1000, HOME writable, listens on `$PORT` (default **7860**). Keep in sync: `cp deploy/Dockerfile Dockerfile`. |
| `/.dockerignore` | keeps `data/`, `logs/`, `.env`, `node_modules`, `.venv` out of the build context |
| `deploy/entrypoint.py` | at container **start**: if `/data/processed` is empty, `snapshot_download` the private dataset repo `$BLINDSPOT_DATA_REPO` with `$HF_TOKEN`; create the SQLite schema at `/data/blindspot.sqlite`; optional demo seed; `exec uvicorn` with proxy headers |
| `deploy/make_data_bundle.py` | stages `data/processed` minus preview PNGs, anatomy `.npz`, holdout cases (and `data/qa`), gzips zones JSON; prints sizes; `--tar FILE`; `--upload <user>/blindspot-data` creates the **private** dataset repo and uploads |
| `deploy/space/README.md` | the Space-side README (HF front-matter: `sdk: docker`, `app_port: 7860`) |

## 1. Data bundle (once, and after any data change)

```bash
uv run python deploy/make_data_bundle.py            # → data/bundle/processed, prints sizes
# measured 2026-10-05: 3,427 cases (151 holdout excluded); images 1.3 GB, masks 35 MB,
# zones 35 MB (gzipped from ~300 MB), cases.jsonl + meta 12 MB; total ≈ 1.3 GB
HF_TOKEN=hf_xxx uv run python deploy/make_data_bundle.py --upload <hf-user>/blindspot-data
```

The upload refuses to proceed if the repo is public. Use a token with write access for the upload; the Space
only needs a **read** token (fine-grained, read access to that one dataset repo).

## 2. Create the Space

1. huggingface.co → New Space → name `blindspot`, SDK **Docker**, hardware **CPU basic (free)**, visibility
   **Public** (the Vercel proxy cannot authenticate to a private Space; the app gate protects the content).
2. Settings → **Secrets** (never in variables, never committed):
   - `ANTHROPIC_API_KEY` — live debriefs; without it the tutor serves validated templates (offline mode)
   - `HF_TOKEN` — read token for the private dataset repo
   - `BLINDSPOT_ACCESS_CODE` — the code learners type on the gate screen
   - `BLINDSPOT_REVIEW_CODE` — for `/review` and `/cohort` (expert reviewers, instructor)
3. Settings → **Variables**:
   - `BLINDSPOT_BASE_PATH=/blindspot` (already the image default)
   - `BLINDSPOT_DATA_REPO=<hf-user>/blindspot-data`
   - `BLINDSPOT_MODEL_DEBRIEF`, `BLINDSPOT_MODEL_FAST` (model ids; app code never hard-codes them)
   - `BLINDSPOT_MAX_LIVE_CALLS_PER_MIN=30` (global live-call budget; over it the tutor falls back to templates)
   - optional: `BLINDSPOT_SEED_DEMO=1` (seed the demo learner + playlist at start, offline),
     `BLINDSPOT_CORS_ORIGINS=https://ysunkara.com` (only needed if a page on another origin calls the API directly;
     the rewrite below is same-origin)
4. Push this repo to the Space with the Space README at the root (HF reads front-matter only from the root
   `README.md`):

   ```bash
   git remote add space https://huggingface.co/spaces/<hf-user>/blindspot
   git checkout -b space-deploy
   cp deploy/space/README.md README.md && git commit -am "chore(space): HF Space README"
   git push space space-deploy:main
   git checkout main
   ```

   First build ≈ 5 min (npm ci + uv sync); first start downloads ≈ 1.3 GB (≈ 1–3 min). Check
   `https://<hf-user>-blindspot.hf.space/blindspot/api/health` → `{"ok":true,"cases":3427,...}`.

**Persistence.** Free Spaces have no persistent disk: `/data` (dataset + SQLite) is rebuilt on every restart or
rebuild, so **attempts, dashboards and reviews reset**. Acceptable for the demo. For the pilot, add HF persistent
storage (mounted at `/data`, paid) — the entrypoint then skips the download and the DB survives — and export
`/blindspot/api/review/export.csv` before any restart. RAM: 1 GB is enough (no GPU, no torch); the case repository
caches 16 zone sets and 256 masks.

## 3. Proxy from ysunkara.com (Vercel)

In the site repo's `vercel.json`:

```json
{
  "rewrites": [
    { "source": "/blindspot", "destination": "https://<hf-user>-blindspot.hf.space/blindspot/" },
    { "source": "/blindspot/:path*", "destination": "https://<hf-user>-blindspot.hf.space/blindspot/:path*" }
  ]
}
```

Put these before any catch-all SPA rewrite of the site. The container also accepts unprefixed paths, so a proxy
that strips `/blindspot` works too, but keep the prefix (above) so redirects and cookie paths line up.

**Cookies.** `POST /blindspot/api/access {code}` answers with
`Set-Cookie: bs_access=<hmac token>; Path=/blindspot; HttpOnly; SameSite=Lax; Secure` and **no `Domain`**, so the
browser files it under `ysunkara.com` (the host it sees) and sends it with every `/blindspot/...` request,
including `<img>` loads. The cookie carries an HMAC of the code, never the code. `bs_review` works the same via
`POST /blindspot/api/review/access`. `GET /blindspot/api/access` reports `{access_required, access_granted,
review_required, review_granted, base_path}` so the frontend can show the gate once. Scripts may send headers
`X-Blindspot-Access: <code>` / `X-Blindspot-Review: <code>` instead. 10 wrong codes per IP in 5 min → 429.

## Other hosts (nginx / Caddy in front of the same container)

```nginx
location /blindspot/ {
    proxy_pass http://127.0.0.1:7860;          # no trailing slash: keep the /blindspot prefix
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
location = /blindspot { return 308 /blindspot/; }
```

```caddy
ysunkara.com {
    handle /blindspot* {
        reverse_proxy 127.0.0.1:7860
    }
}
```

Local run of the image (data mounted instead of downloaded):

```bash
docker build -t blindspot .
docker run --rm -p 7860:7860 -v "$PWD/data/bundle:/data" \
  -e BLINDSPOT_ACCESS_CODE=test -e BLINDSPOT_REVIEW_CODE=test2 blindspot
# http://localhost:7860/blindspot/
```

## Without Docker (what the checks below used)

```bash
cd frontend && VITE_BASE_PATH=/blindspot npm run build && cd ..
BLINDSPOT_BASE_PATH=/blindspot BLINDSPOT_SERVE_FRONTEND=1 BLINDSPOT_ACCESS_CODE=test \
  uv run uvicorn backend.app.main:app --port 8010
curl -s localhost:8010/blindspot/api/health          # 200
curl -s -o /dev/null -w '%{http_code}' localhost:8010/blindspot/api/sessions -X POST   # 401
curl -s localhost:8010/blindspot/ | head -c 80        # index.html
```

## Settings reference (backend/app/settings.py)

| env | default | effect |
|---|---|---|
| `BLINDSPOT_BASE_PATH` | `""` (image: `/blindspot`) | API at `{base}/api/...`, SPA at `{base}/`, `image_url`s carry the base, cookie `Path` |
| `BLINDSPOT_SERVE_FRONTEND` | `0` (image: `1`) | serve `frontend/dist` with SPA fallback to `index.html`; `/assets/*` immutable cache |
| `BLINDSPOT_FRONTEND_DIST` | `./frontend/dist` | where the built SPA lives |
| `BLINDSPOT_ACCESS_CODE` | unset | unset = nothing gated (local dev) |
| `BLINDSPOT_REVIEW_CODE` | unset | unset = `/api/review/*`, `/api/cohort/*` need only the access code |
| `BLINDSPOT_CORS_ORIGINS` | unset | extra allowed origins (comma list), on top of the Vite dev origins |
| `BLINDSPOT_DATA_DIR` / `BLINDSPOT_DB_PATH` | `./data`, `./data/blindspot.sqlite` (image: `/data/...`) | data + DB |
| `BLINDSPOT_DATA_REPO`, `HF_TOKEN` | unset | entrypoint download source |

API responses carry `Cache-Control: no-store`; case images keep `public, max-age=31536000, immutable`.
