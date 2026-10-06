# Vercel-only: Plant.id + Groq (no local ML)

## Deploy
```bash
cd vercel-app
git add . && git commit -m "Vercel-only deploy"
git push -u origin master
```
Then import the repo at https://vercel.com/new and add the env vars below.

## Vercel Settings
- **Framework**: Flask (auto-detected)
- **Build Command**: `pip install -r requirements.txt`
- **Output Directory**: `static`
- **Function Timeout**: 30s (set in vercel.json)

## Environment Variables (set in Vercel dashboard — never commit real keys)
| Variable | Value |
|---|---|
| `VISION_API_KEY` | your Groq API key (`gsk_...`) |
| `VISION_BASE_URL` | `https://api.groq.com/openai/v1` |
| `VISION_MODEL` | a vision-capable model currently listed by `GET /openai/v1/models` |
| `PLANT_ID_API_KEY` | your Plant.id API key |

## What's Included
- `/api/analyze` → Plant.id (2 credits) + Groq narrative → merged JSON
- Static UI with hero, Plant.id card, 6 narrative tabs
- ~5MB bundle, instant cold starts

## What's NOT Included (vs full Fly.io version)
- Offline CLIP gate / disease probe / ViT / ResNet
- Calibration badges (ECE 0.08)
- Local agreement badges
- Kindwise trial cross-check
- Species ranking from full model

## Cost
- Vercel: Free tier (100GB bandwidth, 1000 invocations/mo)
- Plant.id: Your 50 credits
- Groq: Free tier