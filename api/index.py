import os, base64, json, re, requests
from flask import Flask, request, jsonify, send_from_directory
from openai import OpenAI

import os
static_dir = os.path.join(os.path.dirname(__file__), '..', 'static')
app = Flask(__name__, static_folder=static_dir)

VISION_API_KEY = os.environ.get("VISION_API_KEY")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.groq.com/openai/v1")
VISION_MODEL = os.environ.get("VISION_MODEL", "llama-3.2-11b-vision-preview")
PLANT_ID_API_KEY = os.environ.get("PLANT_ID_API_KEY")
print(f"[STARTUP] VISION_MODEL = {VISION_MODEL}")  # Debug
print(f"[STARTUP] VISION_BASE_URL = {VISION_BASE_URL}")  # Debug

def plant_id_identify(image_b64, health="auto"):
    if not PLANT_ID_API_KEY:
        return {"ok": False, "error": "PLANT_ID_API_KEY not set"}
    url = "https://api.plant.id/v3/identification"
    headers = {"Api-Key": PLANT_ID_API_KEY, "Content-Type": "application/json"}
    payload = {"images": [image_b64], "health": health}
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        return {"ok": False, "error": f"Plant.id {r.status_code}: {r.text}"}
    data = r.json()
    res = data.get("result", {})
    is_plant = res.get("is_plant", {})
    is_healthy = res.get("is_healthy", {})
    classification = res.get("classification", {}).get("suggestions", [])
    disease = res.get("disease", {}).get("suggestions", [])
    # Add top disease name/prob for merge_verdict
    top_disease = disease[0] if disease else {}
    return {
        "ok": True,
        "backend": "production",
        "model_version": data.get("model_version"),
        "is_plant": is_plant.get("binary", False),
        "is_plant_score": is_plant.get("probability", 0),
        "healthy": is_healthy.get("binary", False),
        "healthy_score": is_healthy.get("probability", 0),
        "species": [{"name": s.get("name"), "probability": s.get("probability")} for s in classification[:3]],
        "disease": [{"name": d.get("name"), "probability": d.get("probability")} for d in disease[:4]],
        "diagnosis": top_disease.get("name"),
        "probability": top_disease.get("probability"),
    }

def groq_narrative(image_b64, plantid_result):
    with open(r'C:\temp\groq_debug.log', 'a') as f:
        f.write(f"[DEBUG groq] ENTERED, plantid_ok = {plantid_result.get('ok')}\n")
    if not VISION_API_KEY:
        return {"configured": False, "error": "VISION_API_KEY not set"}
    ctx = []
    if plantid_result.get("ok"):
        td = plantid_result
        ctx.append(f"Plant.id diagnosis: {td.get('diagnosis', 'N/A')} ({td.get('probability', 0):.0%})")
        if td.get("species"):
            sp_fmt = ', '.join(f'{s["name"]} ({s["probability"]:.0%})' for s in td["species"])
            ctx.append(f"Species: {sp_fmt}")
        ctx.append(f"Healthy: {td.get('healthy', False)}")
    prompt = (
        "You are a plant pathologist. Given the Plant.id structured analysis and the leaf image, "
        "produce a concise 19-field JSON report: "
        "diagnosis, pathogen, category, severity, confidence, summary, symptoms, affected_parts, "
        "differential_diagnoses, organic_treatment, chemical_treatment, prevention, contagious, urgency, notes. "
        "Use the Plant.id data as primary evidence but add expert context. "
        "Return ONLY valid JSON."
    )
    model = os.environ.get("VISION_MODEL", "llama-3.2-11b-vision-preview")
    with open(r'C:\temp\groq_debug.log', 'a') as f:
        f.write(f"[DEBUG groq] model from env = {model}\n")
    client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)
    with open(r'C:\temp\groq_debug.log', 'a') as f:
        f.write(f"[DEBUG groq] calling Groq with model = {model}\n")
    try:
        with open(r'C:\temp\groq_debug.log', 'a') as f:
            f.write(f"[DEBUG groq] about to call client.chat.completions.create with model={model}\n")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Plant.id context:\n" + "\n".join(ctx)},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]}
            ],
            temperature=0.2, max_tokens=1500,
        )
        text = resp.choices[0].message.content
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return {"configured": True, "provider": "groq", "model": model, "verdict": json.loads(m.group())}
    except Exception as e:
        print(f"[DEBUG groq] error: {e}")  # Debug
        return {"configured": False, "error": str(e)}
    return {"configured": False, "error": "Failed to parse Groq response"}

def merge_verdict(plantid, groq):
    v = {}
    if plantid.get("ok"):
        td = plantid
        disease = (td.get("disease") or [{}])[0]
        v.update({
            "diagnosis_source": "plant.id",
            "diagnosis": disease.get("name"),
            "pathogen": disease.get("name"),
            "probability": disease.get("probability"),
            "confidence": int((disease.get("probability") or 0) * 100),
            "healthy": td.get("healthy", False),
            "crop": (td.get("species") or [{}])[0].get("name"),
            "is_plant": td.get("is_plant", False),
            "category": "Fungal" if "phytophthora" in str(disease.get("name","")).lower() else "Unknown",
        })
    if groq.get("configured") and groq.get("verdict"):
        v.update(groq["verdict"])
        v["diagnosis_source"] = v.get("diagnosis_source", "groq")
    return v

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "tomato-leaf-vercel"})

@app.route('/api/analyze', methods=['POST'])
def analyze():
    with open(r'C:\temp\analyze_debug.log', 'a') as f:
        f.write("[DEBUG analyze] ENTERED\n")
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "Missing image (base64)"}), 400
    img_b64 = data["image"]
    pid = plant_id_identify(img_b64)
    with open(r'C:\temp\analyze_debug.log', 'a') as f:
        f.write(f"[DEBUG analyze] pid.ok = {pid.get('ok')}, calling groq_narrative\n")
    groq = groq_narrative(img_b64, pid)
    with open(r'C:\temp\analyze_debug.log', 'a') as f:
        f.write(f"[DEBUG analyze] groq result: {groq}\n")
    verdict = merge_verdict(pid, groq)
    return jsonify({"verdict": verdict, "plantid": pid, "groq": groq})

@app.route('/api/crosscheck', methods=['POST'])
def crosscheck():
    return jsonify({"status": "not implemented in vercel-only version"}), 501

if __name__ == '__main__':
    app.run(port=5000, debug=False)