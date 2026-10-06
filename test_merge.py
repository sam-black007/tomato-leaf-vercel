"""Proves Plant.id owns every structured field and the narrative model cannot touch them."""
import io, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
os.environ.setdefault("VISION_API_KEY", "test")
os.environ.setdefault("PLANT_ID_API_KEY", "test")
import index as m

plantid = {
    "ok": True, "status": 201, "model_version": "plant_id:5.1.1",
    "is_plant": True, "is_plant_score": 0.99,
    "healthy": False, "healthy_score": 0.001,
    "species": [{"name": "Solanum lycopersicum", "probability": 0.34}],
    "disease": [{"name": "Phytophthora", "probability": 0.386},
                {"name": "Botrytis", "probability": 0.286}],
    "diagnosis": "Phytophthora", "probability": 0.386, "category": "Oomycete",
}

# A hostile narrative: contradicts the diagnosis on every structured axis.
narrative = {
    "configured": True,
    "verdict": {
        "summary": "hostile summary",
        "category": "Insect",
        "pathogen": "Botrytis cinerea",
        "diagnosis": "Healthy",
        "crop": "Wheat",
        "species": [{"name": "Triticum aestivum", "probability": 0.99}],
        "healthy": True,
        "probability": 0.99,
        "confidence": 99,
        "is_plant": False,
        "model_version": "fake",
        "severity": "Severe",
        "organic_treatment": ["do a thing"],
    },
}

v = m.merge_verdict(plantid, narrative)

expected = {
    "diagnosis": "Phytophthora",
    "crop": "Solanum lycopersicum",
    "category": "Oomycete",
    "pathogen": "Phytophthora",
    "healthy": False,
    "probability": 0.386,
    "confidence": 39,
    "is_plant": True,
    "model_version": "plant_id:5.1.1",
    "diagnosis_source": "plant.id",
    "species": [{"name": "Solanum lycopersicum", "probability": 0.34}],
}
expected_narrative = {
    "summary": "hostile summary",
    "severity": "Severe",
    "organic_treatment": ["do a thing"],
}

failed = False
for k, want in expected.items():
    got = v.get(k)
    ok = got == want
    failed |= not ok
    print(("PASS " if ok else "FAIL ") + f"{k}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
for k, want in expected_narrative.items():
    got = v.get(k)
    ok = got == want
    failed |= not ok
    print(("PASS " if ok else "FAIL ") + f"narrative {k}: {got!r}")

print("\nRESULT:", "FAIL" if failed else "PASS - structured fields are untouchable")
sys.exit(1 if failed else 0)
