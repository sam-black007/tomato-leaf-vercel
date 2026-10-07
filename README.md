# Tomato Leaf — Vercel deployment (Plant.id + Gemini narrative)

Live: https://tomato-leaf-vercel.vercel.app

Plant.id produces the structured verdict (crop, health, disease, confidence).
Gemini (vision) writes the narrative only. The narrative can never overwrite
the structured fields.

## Endpoints
| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Static UI (served from the CDN) |
| `/health` | GET | Liveness + which keys are configured |
| `/api/analyze` | POST | `{ "image": "<base64>" }` â†’ merged verdict |
| `/api/crosscheck` | POST | Not available in this deployment (501) |

## Architecture
- UI is a single self-contained `static/index.html` served by Vercel's CDN.
- One Python function, `api/index.py`, handles every API route (see `vercel.json`).
- Plant.id is the **only** engine that looks at pixels for the structured verdict.
  Success is **HTTP 201**, so all 2xx codes are accepted.
- Gemini reads the photo for the narrative; Groq is a text-only fallback (see below).

## Narrative provider
| Env var | Value |
|---|---|
| `VISION_API_KEY` | Gemini API key from https://aistudio.google.com/apikey |
| `VISION_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `VISION_MODEL` | `gemini-3.5-flash` |
| `VISION_SUPPORTS_IMAGES` | `1` (Gemini reads the photo) |
| `VISION_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3-flash-preview` |
| `PLANT_ID_API_KEY` | Plant.id API key |

The OpenAI-compatible Gemini layer authenticates with an `Authorization: Bearer`
header, which is what the `openai` SDK sends, so no custom header handling is needed.

### Groq is no longer usable for images
`GET https://api.groq.com/openai/v1/models` returns no vision-capable model:

| Model | Result |
|---|---|
| `llama-3.2-90b-vision-preview` | `model_decommissioned` |
| `llama-3.2-11b-vision-preview` | `model_decommissioned` |
| `meta-llama/llama-4-scout-17b-16e-instruct` | `model_not_found` |

Text-only Groq still works (`qwen/qwen3.8-27b`). Set `VISION_SUPPORTS_IMAGES=0`
with a Groq base URL and the prompt switches to text-only mode automatically.

### Model fallback
Gemini returns `503 UNAVAILABLE` ("high demand") on individual models fairly
often, so `groq_narrative` walks `VISION_MODEL` then each entry in
`VISION_FALLBACK_MODELS` until one returns parseable JSON. All attempts are
reported in `narrative.error` if every candidate fails.

### max_tokens
Gemini 3.x spends part of the token budget on thinking, so a small cap truncates
the JSON mid-object. `max_tokens=4096` is required.

### httpx pin
`openai==1.54.3` passes `proxies=` to httpx, removed in httpx 0.28. `httpx==0.27.2`
is pinned in `requirements.txt`; without it every deployed call dies with
`TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`.

## Merge contract
Structured fields always come from Plant.id: `diagnosis`, `crop`, `species`,
`healthy`, `probability`, `confidence`, `category`, `is_plant`, `model_version`.

Narrative fields come only from Groq, and only when non-empty: `summary`,
`pathogen`, `severity`, `symptoms`, `affected_parts`, `differential_diagnoses`,
`organic_treatment`, `chemical_treatment`, `prevention`, `contagious`,
`urgency`, `notes`, `evidence`.

If Plant.id fails the response is HTTP 502 with the Groq narrative still
attached, so the page degrades instead of showing a blank result.

## Environment variables
Set in Vercel â†’ Settings â†’ Environment Variables, marked **sensitive**.
Never commit real keys.

| Variable | Value |
|---|---|
| `VISION_API_KEY` | Gemini API key (`AIza...`) |
| `VISION_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `VISION_MODEL` | `gemini-3.5-flash` |
| `VISION_SUPPORTS_IMAGES` | `1` (Gemini reads the photo) |
| `VISION_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3-flash-preview` |
| `PLANT_ID_API_KEY` | your Plant.id API key |

### Easiest way to set them
From this folder:
```powershell
powershell -ExecutionPolicy Bypass -File .\set_keys.ps1
```
It prompts for each key, stores them encrypted, and redeploys. Keys never
touch the repo or chat history.

Or manually:
```powershell
vercel.cmd login
vercel.cmd env add VISION_API_KEY production --value "<gemini-key>" --sensitive --yes
vercel.cmd env add VISION_BASE_URL production --value "https://generativelanguage.googleapis.com/v1beta/openai/" --sensitive --yes
vercel.cmd env add VISION_MODEL production --value "gemini-3.5-flash" --sensitive --yes
vercel.cmd env add PLANT_ID_API_KEY production --value "..." --sensitive --yes
vercel.cmd deploy --prod
```

## Image size
Base64 inflates images by ~33%. Requests above ~2.5 MB are rejected with HTTP
413, because Vercel caps request bodies at about 4.5 MB. The UI compresses the
selected photo in the browser before upload.

## Known limits
- `VISION_MODEL` must be served by the configured provider: Gemini by default,
  Groq (`https://api.groq.com/openai/v1`) only as a text-only fallback with
  `VISION_SUPPORTS_IMAGES=0`.
- Plant.id spends 1 credit for a healthy leaf and 2 for a diseased one.
- No offline models here: no CLIP gate, no disease probe, no ViT/ResNet
  second opinion, no calibration badges, no local agreement badge. Those live in
  the full local version and the Fly.io container build.
- CORS allows browser clients: `/api/analyze` answers `OPTIONS` with
  `Access-Control-Allow-Origin: *`, so the PlantLab webcam can POST from any origin.
