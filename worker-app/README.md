# Indux Assistant — Worker App

Mobile-first web app that lets a technician ask the Indux backend for
air-compressor troubleshooting help. Built with React + TypeScript + Vite.

This folder is the frontend only. The FastAPI backend lives in `../backend`
and is owned by another team member.

## Requirements

- Node.js 20.19+ (tested with Node 25)
- The backend running locally (default `http://localhost:8000`) for API calls

## Setup

```bash
cd worker-app
npm install
cp .env.example .env.local   # optional; defaults work for local dev
npm run dev
```

Open http://localhost:5173.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on `localhost:5173` with the `/api` proxy |
| `npm run dev:host` | Same, but reachable from other devices on the LAN (HTTP only — see below) |
| `npm run build` | Type-check and build to `dist/` |
| `npm run typecheck` | Type-check only |
| `npm test` | Run unit tests once (Vitest) |
| `npm run test:watch` | Run tests in watch mode |
| `npm run preview` | Serve the built `dist/` locally |

## Configuration

| Variable | Used in | Default | Purpose |
|---|---|---|---|
| `VITE_API_BASE_URL` | browser bundle | `/api` | Backend base URL. Leave empty in development to use the proxy. Set to the backend's public HTTPS URL for deployed builds. |
| `VITE_DEV_PROXY_TARGET` | `vite.config.ts` (dev server only) | `http://localhost:8000` | Where the dev proxy forwards `/api/*`. |

How requests are routed:

- **Development:** the app calls `/api/ask`; Vite strips `/api` and forwards to
  `VITE_DEV_PROXY_TARGET/ask`.
- **Deployed:** the app calls `${VITE_API_BASE_URL}/ask` directly.

**Security:** every `VITE_*` value is embedded in the public JavaScript bundle.
Never put API keys, Supabase keys, or Gemini keys in this app. All secrets stay
in the backend.

Machine IDs are sent to the backend exactly as entered (or as given in the QR
link `?machine=`). They are not normalized until the backend team confirms
the canonical format (`compressor-01` vs `compressor_01`).

## API layer (`src/api/`)

| File | Purpose |
|---|---|
| `types.ts` | Wire types matching `backend/main.py` and `ai/schemas.py`, plus the normalized types the UI uses |
| `client.ts` | `askQuestion(question, machineId)` → `POST /ask`; `getHealth()` → `GET /health`; timeouts (45s / 5s) and cancellation |
| `parse.ts` | Validates the `/ask` envelope and nested `answer`, repairs incomplete fields and records them in `issues` |
| `errors.ts` | `ApiError` with `kind`: `validation` (422), `unavailable` (503), `http`, `network`, `timeout`, `aborted`, `malformed` |

Response handling rules:

- An answer whose `status` is not exactly `OK` or `NOT_FOUND`, or a body with no `answer` object, is rejected as `malformed`. Steps are never shown from a response the app cannot interpret.
- Missing or null lists become `[]` and missing strings become `""`. Steps without an instruction and sources without a manual are dropped. Every repair is listed in `AskResult.issues`.
- `NOT_FOUND` always means `escalate = true` with no steps, even if the backend says otherwise.
- `is_dangerous` and `is_demo` are true only when the backend sends the boolean `true`.
- Only 422 and 503 messages from the backend are shown to workers. Other error statuses show a generic message so internal details are not exposed.

Mock responses exist only in `src/api/__tests__/`. The app itself has no hard-coded answers.

## HTTPS mobile testing plan

Browsers only allow microphone access (speech-to-text) in a *secure context*:
HTTPS, or `http://localhost`. Opening `http://<laptop-ip>:5173` on a phone will
load the page but the mic will be blocked. Options, in order of preference:

1. **Android over USB (no certificates needed).** Enable USB debugging on the
   phone, connect it, then run:
   ```bash
   adb reverse tcp:5173 tcp:5173
   ```
   Open `http://localhost:5173` in Chrome on the phone. Because it is
   `localhost`, the mic works, and the `/api` proxy still reaches the backend
   on the laptop. Debug from desktop Chrome at `chrome://inspect`.
2. **Local HTTPS with a trusted dev certificate (Android and iOS on the same
   Wi‑Fi).** Use [mkcert](https://github.com/FiloSottile/mkcert) to create a
   local CA and a certificate for the laptop's LAN IP, install the mkcert root
   CA on the test phone, and serve Vite over HTTPS with that certificate.
   Certificates go in `worker-app/certs/`, which is git-ignored. Never commit
   certificates or private keys, and remove the root CA from the phone after
   testing. (Wiring this into `vite.config.ts` will happen in a later stage.)
3. **Vercel preview deployment.** Every push gets an HTTPS URL. Set
   `VITE_API_BASE_URL` in the Vercel project to the backend's HTTPS URL. The
   backend must also be reachable over HTTPS, because browsers block HTTP API
   calls from an HTTPS page (mixed content).

Avoid public tunnels (ngrok, Cloudflare Tunnel) unless needed. If you use one,
keep it short-lived, because it exposes the dev server and backend to the
internet.

## Roadmap

1. ✅ Scaffold: Vite + React + TS, env config, mobile-first styles, start screen
2. ✅ API layer: typed client for `/ask` and `/health`, error handling (503, 422, network, timeout), response validation, tests
3. Machine ID entry plus the typed-question flow
4. Answer view: safety checklist (acknowledgement required before steps on
   dangerous answers; summary, escalation and sources always visible), numbered
   steps, sources, NOT_FOUND / escalate
5. Speech-to-text (Web Speech API) with an editable transcript, sent via `/ask`
6. Read Aloud / Stop Speaking (speechSynthesis)
7. Polish, accessibility, deployment

### Automated testing (added in later stages)

Vitest + React Testing Library, with the backend mocked at the `fetch` level:

- **API:** request body shape for `/ask`, success-envelope parsing, 503 and 422
  (string and array `detail`), network failure, timeout, base-URL joining.
- **Safety:** dangerous answers hide steps until every item is acknowledged;
  summary, escalation warning and sources stay visible; NOT_FOUND shows
  escalation.
- **Speech:** recognition and synthesis hooks with mocked
  `SpeechRecognition` / `speechSynthesis`, unsupported-browser fallback,
  permission-denied handling, stop speaking.
