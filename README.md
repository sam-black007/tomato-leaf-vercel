# Vercel-only: Plant.id + Groq (no local ML)

## Deploy
```bash
cd vercel-app
git init && git add . && git commit -m "Vercel-only deploy"
# Push to GitHub, then import in Vercel
```

## Vercel Settings
- **Framework**: Flask (auto-detected)
- **Build Command**: `pip install -r requirements.txt`
- **Output Directory**: `static`
- **Function Timeout**: 30s (set in vercel.json)

## Environment Variables (set in Vercel dashboard)
| Variable | Value |
|---|---|
| `VISION_API_KEY` | `gsk_YOUR_GROQ_KEY` |
| `VISION_BASE_URL` | `https://api.groq.com/openai/v1` |
| `VISION_MODEL` | `llama-3.2-90b-vision-preview` |
| `PLANT_ID_API_KEY` | *(set in Vercel dashboard — never commit)* |

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