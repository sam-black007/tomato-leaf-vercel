# Tomato Leaf — Vercel deployment (Plant.id + Groq)

Live: https://tomato-leaf-vercel.vercel.app

Plant.id produces the structured verdict (crop, health, disease, confidence).
Groq writes the narrative only. Groq can never overwrite the structured fields.

## Endpoints
| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Static UI (served from the CDN) |
| `/health` | GET | Liveness + which keys are configured |
| `/api/analyze` | POST | `{ "image": "<base64>" }` → merged verdict |
| `/api/crosscheck` | POST | Not available in this deployment (501) |

## Architecture
- UI is a single self-contained `static/index.html` served by Vercel's CDN.
- One Python function, `api/index.py`, handles every API route (see `vercel.json`).
- Plant.id: `POST https://api.plant.id/v3/identification`, header `Api-Key`,
  body `{"images":[base64],"health":"auto"}`. Success is **HTTP 201**, so all 2xx
  codes are accepted.
- Groq: OpenAI-compatible endpoint at `https://api.groq.com/openai/v1`.

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
Set in Vercel → Settings → Environment Variables, marked **sensitive**.
Never commit real keys.

| Variable | Value |
|---|---|
| `VISION_API_KEY` | your Groq API key (`gsk_...`) |
| `VISION_BASE_URL` | `https://api.groq.com/openai/v1` |
| `VISION_MODEL` | a vision model currently returned by `GET /openai/v1/models` |
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
vercel.cmd env add VISION_API_KEY production --value "gsk_..." --sensitive --yes
vercel.cmd env add VISION_BASE_URL production --value "https://api.groq.com/openai/v1" --sensitive --yes
vercel.cmd env add VISION_MODEL production --value "llama-3.2-11b-vision-preview" --sensitive --yes
vercel.cmd env add PLANT_ID_API_KEY production --value "..." --sensitive --yes
vercel.cmd deploy --prod
```

## Image size
Base64 inflates images by ~33%. Requests above ~2.5 MB are rejected with HTTP
413, because Vercel caps request bodies at about 4.5 MB. The UI compresses the
selected photo in the browser before upload.

## Known limits
- `VISION_MODEL` must be a model Groq currently serves. `llama-3.2-90b-vision-preview`
  was decommissioned.
- Plant.id spends 1 credit for a healthy leaf and 2 for a diseased one.
- No offline models here: no CLIP gate, no disease probe, no ViT/ResNet
  second opinion, no calibration badges, no local agreement badge. Those live in
  the full local version and the Fly.io container build.
