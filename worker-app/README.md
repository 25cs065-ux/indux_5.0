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

## Pages and navigation (`src/router/`, `src/pages/`)

| Route | Page | Contents |
|---|---|---|
| `#/equipment` (default) | Equipment | Machine selection or ID entry, details from the site machine list only (`src/data/machines.ts`, a copy of `docs/lists/machines.json`), "Selected from QR code" tag, Start diagnosis |
| `#/diagnose` | Diagnose | Machine bar, voice-enabled issue form, diagnosis report |
| `#/history` | Repair history | Placeholder only: no records are shown until the read-only history page is built |

- Hash routes work on any static host and keep the `?machine=` query from QR
  links. A QR link opens Equipment with the machine preselected; the worker
  confirms with Start diagnosis.
- Mobile (< 960px): fixed bottom bar with 64px targets. Desktop: tabs in the
  header. The active page is marked with `aria-current="page"`.
- On page change the page title updates, the view scrolls to the top and focus
  moves to the page heading.
- Kept across pages: selected machine, question text, current diagnosis.
- Reset when leaving Diagnose: safety acknowledgements (the diagnosis view
  unmounts), voice recording (aborted; recognised text is kept) and read-aloud.
- No machine status, health, readings or activity are shown, because none exist
  in the repository.

### Diagnose page workflow

1. Machine bar shows the machine selected on Equipment (with a Change link).
2. Type the issue, or press **Record issue** and speak; recognised text lands
   in the field for editing. Nothing is sent until **Diagnose** is pressed.
3. While loading: progress line and **Cancel**. Double clicks never send twice.
4. Errors show their cause with **Retry** (same request, sent once).
5. The answer follows the safety rules above; **Read aloud** / **Stop speaking**
   follow the same gating.
6. **New question** (beside the Diagnosis heading once there is something to
   clear) stops recording and read-aloud, cancels any request in flight,
   clears the question and diagnosis (so acknowledgements reset), keeps the
   machine and focuses the issue field.

If `GET /health` fails, or an `/ask` request cannot reach the server (network
error, or 502/504 from a gateway or the dev proxy), the header shows
**Unreachable** and the Diagnose page shows a **Server unreachable** notice
with **Check again**. Typing and recording still work. A successful answer
clears the notice.

## API layer (`src/api/`)

| File | Purpose |
|---|---|
| `types.ts` | Wire types matching `backend/main.py` and `ai/schemas.py`, plus the normalized types the UI uses |
| `client.ts` | `askQuestion(question, machineId)` → `POST /ask`; `getHealth()` → `GET /health`; timeouts (45s / 5s) and cancellation |
| `parse.ts` | Validates the `/ask` envelope and nested `answer`, repairs incomplete fields and records them in `issues` |
| `errors.ts` | `ApiError` with `kind`: `validation` (422), `unavailable` (503), `http`, `network`, `timeout`, `aborted`, `malformed` |

### Supported answer formats

The `/ask` envelope (`backend/main.py`) is unchanged. The nested `answer` is
accepted in two formats:

| | Legacy | Current (`ai/schemas.py`, `ai/brain.py`) |
|---|---|---|
| Status | `OK`, `NOT_FOUND` | `SUCCESS`, `NOT_FOUND`, `SAFETY_ALERT` |
| Danger flag | `is_dangerous` | none (status + checklist) |
| History note | `history_note` | none |
| Step number | `step_no` | `step_number` |
| Source | `manual`, `page` | `manual_title`, `page_number`, `section` |
| Retrieval | none | `search_score` (vector distance) |

Response handling rules:

- Status is matched case-insensitively; `SUCCESS` is normalized to `OK` and the
  received value is shown as is. Any other status, or a body with no `answer`
  object, is rejected as `malformed`: steps are never shown from a response the
  app cannot interpret.
- Field names are read from either format. Missing or null lists become `[]`
  and missing strings `""`. Steps without an instruction and sources without a
  manual title are dropped. Repairs are listed in `AskResult.issues`, only for
  fields the detected format requires (so current answers are not flagged for
  lacking `is_dangerous` / `history_note`).
- `NOT_FOUND` always means escalate with no steps.
- **Internal errors**: a `summary` that looks like backend error text (e.g.
  `brain.py`'s "Failed to parse AI response: ...", Python tracebacks,
  `SomethingError: ...`) is discarded, never displayed or spoken. The worker sees
  "The assistant could not complete this diagnosis", distinct from NOT_FOUND.
- `search_score` is stored as a distance and **never displayed or spoken**. It
  is not a confidence value or a safety rating.
- References show the manual title exactly as returned, the page, and the
  section when present.
- `is_demo` is true only when the backend sends the boolean `true`; demo
  answers are always labelled.
- Only 422 and 503 messages from the backend are shown to workers. Other error
  statuses show a generic message so internal details are not exposed.

Mock responses exist only in test files. The app itself has no hard-coded answers.

## Safety states (`src/lib/safety.ts`)

| State | When | Steps |
|---|---|---|
| `alert` | `SAFETY_ALERT` | Withheld; escalation required. No acknowledgement unlocks them (policy pending) |
| `flagged` with checklist | legacy `is_dangerous: true`, or a checklist with `is_dangerous: false` | Hidden until every checklist item is ticked; unticking locks them again. Acknowledgement resets for each new response |
| `flagged` without checklist | legacy `is_dangerous: true` and an empty checklist | Withheld; the worker is directed to a qualified supervisor and site safety procedures |
| `uncertain` | no verified safety signal: **any current-format `SUCCESS`** (with or without a checklist), a legacy/mixed answer without `is_dangerous`, or a backend error | Withheld; summary, references and escalation stay visible |
| `not_flagged` | legacy `is_dangerous: false` with no checklist | Shown, labelled "not a safety clearance" |

A current-format `SUCCESS` is treated as an **unverified** safety state until the
backend team confirms that an empty checklist authorises repair steps
(`docs/json-format.md` on main says "Empty `[]` if safe", but this is not yet a
confirmed safety policy). The rule is the constant
`CURRENT_FORMAT_EMPTY_CHECKLIST_MEANS_NOT_FLAGGED` (currently `false`); change it
only once the policy is confirmed in writing. A regression test guards it.

Open contract questions for the backend team:

1. What action, if any, may a worker take on a `SAFETY_ALERT` (acknowledge and
   proceed, or always escalate)? Until defined, steps are withheld.
2. Will an explicit danger flag return, or will the team confirm that
   "`SUCCESS` + empty checklist" authorises repair steps? Until then, no
   current-format answer shows actionable steps.
3. Can parse failures use a distinct status instead of `NOT_FOUND` with the
   exception text in `summary`?

The UI never states that equipment is safe.

## Voice input (`src/hooks/useSpeechRecognition.ts`)

Record issue uses the browser's built-in Web Speech API
(`SpeechRecognition` / `webkitSpeechRecognition`). No paid speech service is
used and nothing is added to the backend.

How it behaves:

- The recognizer is created only when the worker presses **Record issue**, so
  the browser asks for microphone permission at that moment, never on page load.
- While recording, a **LISTENING** strip shows a level-meter animation (static
  when reduced motion is on) and interim words. The button becomes **Stop
  recording**. The text field is read-only so typing cannot clash with
  recognised text.
- Final text goes into the issue field after anything already typed. Each
  update rebuilds the field from "text before recording + this session's
  transcript", so repeated or cumulative recognition events cannot duplicate
  words.
- The question is **never submitted automatically**. After stopping, the
  worker edits the text and presses Diagnose.
- Pressing Diagnose, or leaving the page, stops recording immediately.
- Errors shown to the worker: microphone blocked, no microphone, no speech
  detected, no network, language not available, unexpected failure. Browsers
  without the API, or pages not served over HTTPS, show Record issue disabled
  with an explanation.
- Language is `en-IN` (`src/speech/support.ts`), which handles Indian English
  and Hinglish best of the available options.

### Browser support

| Browser | Status |
|---|---|
| Chrome (Android, Windows, macOS) | Supported. Audio is sent to Google's speech service by the browser, so an internet connection is required. |
| Edge (Windows) | Supported (uses Microsoft's online service). |
| Safari (iOS 14.5+, macOS) | Supported through `webkitSpeechRecognition`; uses Apple's service. Behaviour differs in places (sessions may end on silence), and must be tested on a real device. |
| Samsung Internet | Generally works (Chromium-based); test before relying on it. |
| Firefox | Not supported. Record issue is disabled; workers type instead. |
| In-app webviews (e.g. opened from a QR scanner app) | Often blocked. Open the link in Chrome or Safari. |

Privacy note: on supported browsers the speech is processed by the browser
vendor's speech service, not by Indux. Nothing reaches the Indux backend until
the worker presses Diagnose.

### HTTPS and phones

Browsers only allow the microphone in a secure context: `https://` or
`http://localhost`. Opening `http://<laptop-ip>:5173` on a phone loads the app
but Record issue is disabled ("needs a secure (HTTPS) connection"). Use one of
the options in the HTTPS mobile testing plan below. The quickest is
`adb reverse tcp:5173 tcp:5173` with an Android phone over USB, then open
`http://localhost:5173` in Chrome on the phone.

If the worker blocks the microphone, the browser remembers it. To re-enable:
Chrome on Android: tap the icon beside the address, open **Permissions**, set
**Microphone** to Allow. Safari on iOS: **Settings → Safari → Microphone**.

## Read aloud (`src/speech/readAloud.ts`, `src/hooks/useSpeechSynthesis.ts`)

**Read aloud** and **Stop speaking** sit at the top of every diagnosis. They
use the browser's built-in `speechSynthesis`; no paid or external service.

What is read, in the order shown on screen:

1. Demo / incomplete-response notes, if any
2. Safety: the hazard warning and every checklist item, or the "status
   unknown" / "no checklist" warnings, or "no hazard flagged, not a safety
   clearance"
3. Escalation (OK) or "No verified manual guidance was found. Escalation is
   required." (NOT_FOUND)
4. Summary
5. Steps, **only if they are visible on screen**. Locked or withheld steps are
   described ("2 troubleshooting steps are locked until every safety check is
   confirmed") but never read
6. "Manual references are listed on screen" (file names are not read)
7. Repair history, labelled as context only
8. The fixed safety disclaimer

Machine IDs, status codes, field names, manual file names and JSON are never
spoken.

Speech stops when the worker presses Stop speaking, starts a new diagnosis,
starts recording (so the microphone does not hear it), when a new answer
replaces the old one, or when a safety box is unticked and steps lock again.
Pressing Read aloud while already speaking is ignored. Browsers without
`speechSynthesis` show both buttons disabled with a note.

A voice for `en-IN` is preferred, then any English voice. Windows desktops
usually only have en-US voices; Android and iOS usually include an Indian
English voice.

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
3. ✅ Worker interface: machine selection or entry, editable question, Diagnose via `/ask`, loading, error and retry states, safety state notice (no steps shown yet)
4. ✅ Diagnosis view: safety checklist with per-item acknowledgement before steps on flagged answers (summary, escalation and references always visible), numbered steps with check questions, manual references, distinct NOT_FOUND block, repair history shown separately as context, incomplete-response notice
5. ✅ Speech-to-text (Web Speech API): Record / Stop recording, listening indicator, interim text, editable transcript, no auto-submit, error handling; sent via `/ask` only when Diagnose is pressed
6. ✅ Read Aloud / Stop Speaking (speechSynthesis), following the on-screen safety gating
7. ✅ (Stage B) Three-page navigation and Equipment page
   ✅ (Stage C) Diagnose workflow: New question, Retry, server-unreachable notice
8. Read-only repair history page
9. Polish, accessibility, deployment

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
