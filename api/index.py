import json
import os
import re

import requests
from flask import Flask, jsonify, request, send_from_directory
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=None)

VISION_API_KEY = os.environ.get("VISION_API_KEY")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.groq.com/openai/v1")
VISION_MODEL = os.environ.get("VISION_MODEL", "gemini-3.5-flash")
PLANT_ID_API_KEY = os.environ.get("PLANT_ID_API_KEY")

# Plant.id is the primary engine. The narrative model sees the photo only when
# the configured provider actually serves a vision model. Groq currently serves
# none, so it runs text-only on Plant.id's structured output; Gemini does, so it
# runs with the image attached.
VISION_SUPPORTS_IMAGES = os.environ.get("VISION_SUPPORTS_IMAGES", "1") == "1"

# Gemini regularly returns 503 "high demand" on individual models, so try each
# candidate in turn before giving up on the narrative.
VISION_FALLBACK_MODELS = tuple(
    m.strip()
    for m in os.environ.get(
        "VISION_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3-flash-preview"
    ).split(",")
    if m.strip()
)

PLANT_ID_URL = "https://api.plant.id/v3/identification"
MAX_IMAGE_BYTES = 3_500_000

NARRATIVE_FIELDS = (
    "summary",
    "pathogen",
    "category",
    "severity",
    "symptoms",
    "affected_parts",
    "differential_diagnoses",
    "organic_treatment",
    "chemical_treatment",
    "prevention",
    "contagious",
    "urgency",
    "notes",
    "evidence",
)

NARRATIVE_PROMPT = """You are a plant pathologist writing the explanatory report for a leaf diagnosis app.

The Plant.id engine has already produced the structured verdict. Your job is NARRATIVE ONLY.
Never contradict or replace the structured diagnosis, crop, health status or confidence.

Write a grounded, practical report using this exact JSON shape:
{
  "summary": "2-3 sentence plain-language explanation of what is happening on this leaf",
  "pathogen": "causal organism if a disease was diagnosed, else null",
  "category": "one of: Fungal, Bacterial, Viral, Oomycete, Insect, Nutrient, Abiotic, None, Unknown",
  "severity": "one of: Mild, Moderate, Severe, Unknown",
  "symptoms": ["short symptom phrase", "..."],
  "affected_parts": ["leaf", "stem", "fruit"],
  "differential_diagnoses": ["plausible alternative, why it is less likely"],
  "organic_treatment": ["actionable non-chemical step"],
  "chemical_treatment": ["active ingredient and role, or null if not warranted"],
  "prevention": ["preventive measure"],
  "contagious": true or false or null,
  "urgency": "Routine | Monitor closely | Act within days",
  "notes": "caveats, including low confidence if confidence is low",
  "evidence": "which visible features drove the narrative"
}

Rules:
- If confidence is below 50 percent, say so plainly and present differentials as genuinely open.
- Prefer cultural, sanitation and environmental controls over pesticides.
- Never invent a product brand or a dosage.
- Return ONLY the JSON object, no markdown fences, no commentary.
"""

VISION_RULES = """- You were given the photograph. Describe only what you can actually see in it
  (colour, pattern, distribution of lesions, leaf condition) and tie those observations
  to the report. Put those observations in "evidence".
- If the photograph is not a leaf, or is too unclear to read, say so plainly and lower
  your certainty instead of guessing."""


def _narrative_prompt():
    if VISION_SUPPORTS_IMAGES:
        return NARRATIVE_PROMPT.replace(
            "- Return ONLY the JSON object",
            VISION_RULES + "\n- Return ONLY the JSON object",
        )
    return NARRATIVE_PROMPT.replace(
        "- Return ONLY the JSON object",
        "- You did NOT see the photograph. Work only from the Plant.id output given to you.\n"
        "- Do not describe leaf markings, colours or textures you were not told about.\n"
        "- Return ONLY the JSON object",
    )


def _provider_name():
    host = VISION_BASE_URL.lower()
    if "generativelanguage" in host:
        return "gemini"
    if "groq" in host:
        return "groq"
    if "openai" in host:
        return "openai"
    if "anthropic" in host:
        return "anthropic"
    return "narrative-model"


def _category_for(disease_name):
    name = str(disease_name or "").lower()
    if not name:
        return "Unknown"
    fungal = (
        "alternaria", "septoria", "botrytis", "powdery", "downy", "fusarium",
        "anthracnose", "rust", "scab", "leaf spot", "leaf blight", "penicillium",
    )
    bacterial = ("bacterial", "xanthomonas", "pseudomonas", "erwinia", "peb")
    viral = ("virus", "viral", "mosaic", "yellow leaf curl", "tomato yellow")
    oomycete = ("phytophthora", "pythium", "downy mildew", "late blight")
    insect = ("mite", "aphid", "whitefly", "thrips", "leafminer", "spider mite")
    for term in oomycete:
        if term in name:
            return "Oomycete"
    for term in fungal:
        if term in name:
            return "Fungal"
    for term in bacterial:
        if term in name:
            return "Bacterial"
    for term in viral:
        if term in name:
            return "Viral"
    for term in insect:
        if term in name:
            return "Insect"
    return "Unknown"


def plant_id_identify(image_b64, health="auto"):
    if not PLANT_ID_API_KEY:
        return {"ok": False, "status": 500, "error": "PLANT_ID_API_KEY is not configured"}
    try:
        r = requests.post(
            PLANT_ID_URL,
            headers={"Api-Key": PLANT_ID_API_KEY, "Content-Type": "application/json"},
            json={"images": [image_b64], "health": health},
            timeout=30,
        )
    except requests.RequestException as exc:
        return {"ok": False, "status": 502, "error": f"Plant.id unreachable: {exc}"}

    if not 200 <= r.status_code < 300:
        detail = (r.text or "")[:300]
        return {"ok": False, "status": r.status_code, "error": f"Plant.id {r.status_code}: {detail}"}

    data = r.json()
    result = data.get("result") or {}
    is_plant = result.get("is_plant") or {}
    is_healthy = result.get("is_healthy") or {}
    species = (result.get("classification") or {}).get("suggestions") or []
    disease = (result.get("disease") or {}).get("suggestions") or []

    top_species = species[0] if species else {}
    top_disease = disease[0] if disease else {}
    healthy = bool(is_healthy.get("binary", False))

    if healthy:
        diagnosis = "Healthy"
    elif top_disease.get("name"):
        diagnosis = top_disease.get("name")
    else:
        diagnosis = None

    return {
        "ok": True,
        "status": r.status_code,
        "backend": "production",
        "model_version": data.get("model_version"),
        "is_plant": bool(is_plant.get("binary", False)),
        "is_plant_score": is_plant.get("probability"),
        "healthy": healthy,
        "healthy_score": is_healthy.get("probability"),
        "species": [
            {"name": s.get("name"), "probability": s.get("probability")} for s in species[:5]
        ],
        "disease": [
            {"name": d.get("name"), "probability": d.get("probability")} for d in disease[:5]
        ],
        "diagnosis": diagnosis,
        "probability": top_disease.get("probability"),
        "category": "None" if healthy else _category_for(diagnosis),
    }


def groq_narrative(image_b64, plantid_result):
    if not VISION_API_KEY:
        return {"configured": False, "error": "VISION_API_KEY is not configured"}

    ctx = ["Plant.id structured analysis is the source of truth for this report."]
    if plantid_result.get("ok"):
        prob = plantid_result.get("probability")
        prob_txt = f" ({prob:.0%})" if isinstance(prob, (int, float)) else ""
        ctx.append(f"Diagnosis: {plantid_result.get('diagnosis') or 'none'}{prob_txt}")
        if plantid_result.get("species"):
            ctx.append(
                "Species ranking: "
                + ", ".join(
                    f"{s['name']} ({s['probability']:.0%})"
                    for s in plantid_result["species"]
                    if s.get("name") and isinstance(s.get("probability"), (int, float))
                )
            )
        ctx.append(f"Healthy: {plantid_result.get('healthy')}")
        ctx.append(f"Is plant: {plantid_result.get('is_plant')}")
        diseases = plantid_result.get("disease") or []
        if diseases:
            ctx.append(
                "Disease ranking: "
                + ", ".join(
                    f"{d['name']} ({d['probability']:.0%})"
                    for d in diseases
                    if d.get("name") and isinstance(d.get("probability"), (int, float))
                )
            )
        top = plantid_result.get("probability")
        ctx.append(
            f"Top confidence: {top:.0%}" if isinstance(top, (int, float)) else "Top confidence: unknown"
        )
    else:
        ctx.append(
            "Plant.id was unavailable, so no structured evidence is available. "
            "Say so in the summary instead of guessing."
        )

    user_content = "\n".join(ctx)
    if VISION_SUPPORTS_IMAGES:
        user_content = [
            {"type": "text", "text": user_content},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
            },
        ]

    client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)
    candidates = [VISION_MODEL] + [m for m in VISION_FALLBACK_MODELS if m != VISION_MODEL]

    parsed = None
    used_model = None
    errors = []
    for model in candidates:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _narrative_prompt()},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                # Gemini 3.x spends part of the budget on thinking tokens, so a
                # small cap truncates the JSON mid-object.
                max_tokens=4096,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            errors.append(f"{model}: {type(exc).__name__}: {exc}")
            continue

        text = (resp.choices[0].message.content or "").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            errors.append(f"{model}: no JSON in response")
            continue
        try:
            parsed = json.loads(match.group())
            used_model = model
            break
        except json.JSONDecodeError as exc:
            errors.append(f"{model}: invalid JSON ({exc})")

    if parsed is None:
        return {"configured": False, "error": " | ".join(errors)[:800]}

    return {
        "configured": True,
        "provider": _provider_name(),
        "model": used_model,
        "sees_image": VISION_SUPPORTS_IMAGES,
        "verdict": {k: parsed.get(k) for k in NARRATIVE_FIELDS},
    }


def merge_verdict(plantid, groq):
    v = {}

    if plantid.get("ok"):
        disease = (plantid.get("disease") or [{}])[0]
        species = (plantid.get("species") or [{}])[0]
        probability = plantid.get("probability")
        v.update(
            {
                "diagnosis_source": "plant.id",
                "diagnosis": plantid.get("diagnosis"),
                "crop": species.get("name"),
                "species": plantid.get("species"),
                "is_plant": plantid.get("is_plant"),
                "is_plant_score": plantid.get("is_plant_score"),
                "healthy": plantid.get("healthy"),
                "healthy_score": plantid.get("healthy_score"),
                "probability": probability,
                "confidence": int(round((probability or 0) * 100)),
                "category": plantid.get("category") or _category_for(plantid.get("diagnosis")),
                "model_version": plantid.get("model_version"),
            }
        )
    else:
        v.update(
            {
                "diagnosis_source": "unavailable",
                "diagnosis": None,
                "confidence": 0,
                "healthy": None,
                "is_plant": None,
                "category": "Unknown",
            }
        )

    narrative = (groq.get("verdict") or {}) if groq.get("configured") else {}
    for field in NARRATIVE_FIELDS:
        value = narrative.get(field)
        if value not in (None, "", [], {}):
            v[field] = value

    if plantid.get("ok") and not v.get("summary"):
        v["summary"] = "Structured analysis returned no narrative text."
    if plantid.get("ok") and not v.get("pathogen"):
        v["pathogen"] = (plantid.get("disease") or [{}])[0].get("name")

    v["narrative_ok"] = bool(groq.get("configured"))
    v["narrative_error"] = groq.get("error")
    return v


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "tomato-leaf-vercel",
            "plantid_configured": bool(PLANT_ID_API_KEY),
            "narrative_configured": bool(VISION_API_KEY),
            "narrative_model": VISION_MODEL if VISION_API_KEY else None,
            "narrative_sees_image": VISION_SUPPORTS_IMAGES,
        }
    )


@app.errorhandler(Exception)
def on_unhandled_error(exc):
    app.logger.exception("unhandled error")
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data.get("image"):
            return jsonify({"error": "Missing image (base64 string)"}), 400

        image_b64 = data["image"]
        if len(image_b64) > MAX_IMAGE_BYTES:
            return jsonify({"error": "Image too large. Use a JPEG under ~2.5 MB."}), 413

        plantid = plant_id_identify(image_b64)
        narrative = groq_narrative(image_b64, plantid)
        verdict = merge_verdict(plantid, narrative)
    except Exception as exc:
        app.logger.exception("analyze failed")
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    payload = {
        "verdict": verdict,
        "plantid": plantid,
        "narrative": {k: v for k, v in narrative.items() if k != "verdict"},
    }
    if not plantid.get("ok") and not narrative.get("configured"):
        return jsonify(payload), 502
    return jsonify(payload)


@app.route("/api/crosscheck", methods=["POST"])
def crosscheck():
    return jsonify({"status": "not available in the Vercel-only deployment"}), 501


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_files(path):
    if path.startswith("api/") or path == "health":
        return jsonify({"error": "Not found"}), 404
    full = os.path.join(STATIC_DIR, path)
    if not os.path.isfile(full):
        return send_from_directory(STATIC_DIR, "index.html")
    return send_from_directory(STATIC_DIR, path)


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)), debug=False)
