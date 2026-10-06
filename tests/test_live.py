"""Live integration test against the deployed app.

Skipped unless LIVE=1, because it spends real Plant.id credits on every run.

    set LIVE=1 && python tests/test_live.py

These assertions exist because every bug that actually reached students came
from the gap between what the code intends and what the deployed providers
return, which no amount of mocking catches.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("LIVE_BASE", "https://tomato-leaf-vercel.vercel.app").rstrip("/")
IMAGE = os.environ.get("LIVE_IMAGE", "")

pytestmark = __import__("pytest").mark.skipif(
    not os.environ.get("LIVE") or not os.environ.get("LIVE_IMAGE"),
    reason="set LIVE=1 and LIVE_IMAGE=<path to jpeg> to run",
)


def post(path, payload, timeout=150):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), time.time() - t0


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def test_health_reports_both_engines():
    status, body = get("/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["plantid_configured"] is True, "PLANT_ID_API_KEY missing in Vercel env"


def test_health_does_not_leak_secrets():
    _, body = get("/health")
    text = json.dumps(body)
    for leak in ("Api-Key", "Bearer", "sk-", "PLANT_ID_API_KEY="):
        assert leak not in text


def test_root_serves_the_app():
    with urllib.request.urlopen(BASE + "/", timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    assert r.status == 200
    assert "tomato" in html.lower()


def test_weights_are_real_json_when_present():
    # The static host answers unknown paths with index.html at HTTP 200, so this
    # asserts the payload parses as the labels object the page requires. While
    # weights are un-uploaded the SPA fallback is the expected, correct state:
    # the UI stays hidden and nothing breaks.
    try:
        with urllib.request.urlopen(BASE + "/models/labels.json", timeout=30) as r:
            ctype = r.headers.get("Content-Type", "")
            raw = r.read()
    except urllib.error.HTTPError:
        return  # 404 is fine, weights not uploaded yet

    if "json" not in ctype:
        assert b"<!DOCTYPE html>" in raw[:200], (
            "expected either real JSON weights or the SPA fallback")
        return

    meta = json.loads(raw)
    assert isinstance(meta.get("classes"), list) and len(meta["classes"]) >= 2
    assert meta.get("onnx_file", "").endswith(".onnx")


def test_real_analysis_contract():
    with open(IMAGE, "rb") as f:
        import base64
        b64 = base64.b64encode(f.read()).decode()

    status, body, elapsed = post("/api/analyze", {"image": b64})

    assert status == 200, f"expected 200, got {status}: {body}"
    assert elapsed < 60, f"took {elapsed:.1f}s, over the 60s function limit"

    for key in ("verdict", "plantid", "narrative"):
        assert key in body, f"missing {key} - the UI reads this key"

    v = body["verdict"]
    assert "case" in v
    assert "live_signals" in v

    # Structured provenance must survive the live round trip.
    assert v["diagnosis_source"] in ("plant.id", "unavailable")
    if v["diagnosis_source"] == "plant.id":
        assert v["category"] in ("Fungal", "Bacterial", "Viral", "Oomycete",
                                 "Insect", "Nutrient", "Abiotic", "None", "Unknown")
        assert isinstance(v["confidence"], int)
        assert 0 <= v["confidence"] <= 100

    sig = v["live_signals"]
    for key in ("top_disease_probability", "margin_over_runner_up",
                "crop_is_confident", "plant_probability"):
        assert key in sig

    # The narrative must not have overwritten structured fields.
    assert v.get("diagnosis") != "Wheat"


def test_plantid_version_reported():
    with open(IMAGE, "rb") as f:
        import base64
        b64 = base64.b64encode(f.read()).decode()
    _, body, _ = post("/api/analyze", {"image": b64})
    print("model_version:", body["plantid"].get("model_version"))
    print("case:", body["verdict"].get("case"))
    print("narrative model:", body["narrative"].get("model"))
    print("sees_image:", body["narrative"].get("sees_image"))
    assert body["narrative"].get("sees_image") is True


def test_empty_post_is_400():
    status, _, _ = post("/api/analyze", {}, timeout=30)
    assert status == 400


def test_oversized_is_413():
    status, _, _ = post("/api/analyze", {"image": "A" * 4_000_000}, timeout=60)
    assert status == 413
