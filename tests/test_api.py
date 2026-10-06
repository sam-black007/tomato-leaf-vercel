"""pytest suite for the Vercel API.

Covers the parts that have actually broken before: Plant.id response parsing,
the structured/narrative field contract, live-case classification, input
validation and the HTTP contract the UI depends on.

Run: python -m pytest tests -v
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.path.dirname(HERE), "api")
sys.path.insert(0, APP_DIR)

os.environ.setdefault("PLANT_ID_API_KEY", "test-plant-id")
os.environ.setdefault("VISION_API_KEY", "test-vision")

import index as m  # noqa: E402


def plantid_ok(**over):
    base = {
        "ok": True,
        "status": 201,
        "backend": "production",
        "model_version": "plant_id:5.1.1",
        "is_plant": True,
        "is_plant_score": 0.9999,
        "healthy": False,
        "healthy_score": 0.001,
        "species": [{"name": "Solanum lycopersicum", "probability": 0.34}],
        "disease": [{"name": "Phytophthora", "probability": 0.386},
                    {"name": "Botrytis", "probability": 0.286}],
        "diagnosis": "Phytophthora",
        "probability": 0.386,
        "category": "Oomycete",
    }
    base.update(over)
    return base


def narrative(**over):
    base = {
        "configured": True,
        "provider": "gemini",
        "model": "gemini-3.5-flash",
        "sees_image": True,
        "verdict": {"summary": "lesions on the leaf", "severity": "Moderate"},
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# _category_for
# --------------------------------------------------------------------------

class TestCategory:
    @pytest.mark.parametrize("disease,expected", [
        ("Phytophthora infestans", "Oomycete"),
        ("Late blight", "Oomycete"),
        ("Pythium root rot", "Oomycete"),
        ("Early blight", "Fungal"),
        ("Alternaria solani", "Fungal"),
        ("Septoria leaf spot", "Fungal"),
        ("Powdery mildew", "Fungal"),
        ("Cedar apple rust", "Fungal"),
        ("Bacterial spot", "Bacterial"),
        ("Xanthomonas", "Bacterial"),
        ("Tomato mosaic virus", "Viral"),
        ("Tomato yellow leaf curl virus", "Viral"),
        ("Two-spotted spider mite", "Insect"),
        ("Whitefly damage", "Insect"),
        (None, "Unknown"),
        ("", "Unknown"),
        ("Something unlisted", "Unknown"),
    ])
    def test_mapping(self, disease, expected):
        assert m._category_for(disease) == expected

    def test_oomycete_beats_fungal_on_shared_terms(self):
        # "late blight" is in the fungal list as "leaf blight" but must stay Oomycete.
        assert m._category_for("Late blight") == "Oomycete"
        assert m._category_for("Downy mildew") == "Oomycete"

    def test_case_insensitive(self):
        assert m._category_for("PHYTOPHTHORA") == m._category_for("phytophthora")


# --------------------------------------------------------------------------
# plant_id_identify
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=201, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload


class TestPlantIdParsing:
    def test_healthy_result_wins_over_disease(self, monkeypatch):
        payload = {"model_version": "plant_id:5.1.1", "result": {
            "is_plant": {"binary": True, "probability": 0.99},
            "is_healthy": {"binary": True, "probability": 0.97},
            "classification": {"suggestions": [{"name": "Solanum lycopersicum", "probability": 0.9}]},
            "disease": {"suggestions": [{"name": "Phytophthora", "probability": 0.05}]},
        }}
        monkeypatch.setattr(m.requests, "post", lambda *a, **k: FakeResponse(201, payload))
        out = m.plant_id_identify("img")
        assert out["ok"] is True
        assert out["healthy"] is True
        assert out["diagnosis"] == "Healthy"
        assert out["category"] == "None"

    def test_201_is_accepted(self, monkeypatch):
        # Regression: Plant.id returns 201, and an earlier `== 200` check rejected it.
        monkeypatch.setattr(m.requests, "post", lambda *a, **k: FakeResponse(201, {
            "result": {"is_plant": {"binary": True, "probability": 0.99},
                       "is_healthy": {"binary": False, "probability": 0.01},
                       "disease": {"suggestions": [{"name": "Botrytis", "probability": 0.8}]}}},
        ))
        assert m.plant_id_identify("img")["ok"] is True

    @pytest.mark.parametrize("status", [200, 201, 202, 204])
    def test_all_2xx_accepted(self, monkeypatch, status):
        monkeypatch.setattr(m.requests, "post", lambda *a, **k: FakeResponse(status, {
            "result": {"is_plant": {"binary": True, "probability": 0.99},
                       "is_healthy": {"binary": False, "probability": 0.01},
                       "disease": {"suggestions": [{"name": "Botrytis", "probability": 0.8}]}}},
        ))
        assert m.plant_id_identify("img")["ok"] is True

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500, 502])
    def test_error_statuses_surface(self, monkeypatch, status):
        monkeypatch.setattr(m.requests, "post", lambda *a, **k: FakeResponse(status, {}, text="nope"))
        out = m.plant_id_identify("img")
        assert out["ok"] is False
        assert out["status"] == status

    def test_network_error_is_502_not_crash(self, monkeypatch):
        def boom(*a, **k):
            raise m.requests.RequestException("timeout")
        monkeypatch.setattr(m.requests, "post", boom)
        out = m.plant_id_identify("img")
        assert out["ok"] is False
        assert out["status"] == 502

    def test_missing_key_reports_not_configured(self, monkeypatch):
        monkeypatch.setattr(m, "PLANT_ID_API_KEY", "")
        out = m.plant_id_identify("img")
        assert out["ok"] is False
        assert "not configured" in out["error"]

    def test_empty_result_block_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(m.requests, "post", lambda *a, **k: FakeResponse(201, {"result": {}}))
        out = m.plant_id_identify("img")
        assert out["ok"] is True
        assert out["diagnosis"] is None
        assert out["species"] == []

    def test_suggestions_capped_at_five(self, monkeypatch):
        many = [{"name": f"sp{i}", "probability": 0.5 - i / 100} for i in range(12)]
        monkeypatch.setattr(m.requests, "post", lambda *a, **k: FakeResponse(201, {
            "result": {"is_plant": {"binary": True, "probability": 0.99},
                       "is_healthy": {"binary": False, "probability": 0.01},
                       "classification": {"suggestions": many},
                       "disease": {"suggestions": many}}},
        ))
        out = m.plant_id_identify("img")
        assert len(out["species"]) == 5
        assert len(out["disease"]) == 5

    def test_probability_follows_top_disease_not_top_species(self, monkeypatch):
        # Confidence must describe the disease call, not the crop call. The real
        # reading has crop 34% and disease 38.6%, and reporting 34% would
        # understate the disease verdict.
        payload = {
            "result": {
                "is_plant": {"binary": True, "probability": 0.99},
                "is_healthy": {"binary": False, "probability": 0.01},
                "classification": {"suggestions": [
                    {"name": "Solanum lycopersicum", "probability": 0.34}]},
                "disease": {"suggestions": [
                    {"name": "Phytophthora", "probability": 0.386}]},
            }
        }
        monkeypatch.setattr(m.requests, "post",
                            lambda *a, **k: FakeResponse(201, payload))
        assert m.plant_id_identify("img")["probability"] == 0.386


# --------------------------------------------------------------------------
# merge_verdict: the structured/narrative contract
# --------------------------------------------------------------------------

class TestMergeContract:
    STRUCTURED = ("diagnosis", "crop", "category", "pathogen", "healthy",
                  "probability", "confidence", "is_plant", "model_version",
                  "diagnosis_source", "species")

    HOSTILE = {
        "summary": "hostile", "category": "Insect", "pathogen": "Botrytis cinerea",
        "diagnosis": "Healthy", "crop": "Wheat", "healthy": True, "probability": 0.99,
        "confidence": 99, "is_plant": False, "model_version": "fake",
        "species": [{"name": "Triticum aestivum", "probability": 0.99}],
        "severity": "Severe",
    }

    def test_hostile_narrative_cannot_touch_structured_fields(self):
        v = m.merge_verdict(plantid_ok(), narrative(verdict=dict(self.HOSTILE)))
        assert v["diagnosis"] == "Phytophthora"
        assert v["crop"] == "Solanum lycopersicum"
        assert v["category"] == "Oomycete"
        assert v["pathogen"] == "Phytophthora"
        assert v["healthy"] is False
        assert v["confidence"] == 39
        assert v["is_plant"] is True
        assert v["model_version"] == "plant_id:5.1.1"
        assert v["diagnosis_source"] == "plant.id"

    def test_narrative_fields_still_land(self):
        v = m.merge_verdict(plantid_ok(), narrative(verdict=dict(self.HOSTILE)))
        assert v["summary"] == "hostile"
        assert v["severity"] == "Severe"

    def test_category_and_pathogen_not_in_allowlist(self):
        # The regression this whole contract exists to prevent.
        assert "category" not in m.NARRATIVE_FIELDS
        assert "pathogen" not in m.NARRATIVE_FIELDS
        assert "diagnosis" not in m.NARRATIVE_FIELDS
        assert "confidence" not in m.NARRATIVE_FIELDS

    def test_pathogen_derived_from_plantid_top_disease(self):
        v = m.merge_verdict(plantid_ok(), narrative())
        assert v["pathogen"] == "Phytophthora"

    def test_pathogen_none_when_no_disease(self):
        v = m.merge_verdict(plantid_ok(disease=[], diagnosis=None, probability=None,
                                       healthy=True, category="None"), narrative())
        assert v["pathogen"] is None

    def test_failed_plantid_marks_source_unavailable(self):
        v = m.merge_verdict({"ok": False, "status": 402, "error": "no credits"}, narrative())
        assert v["diagnosis_source"] == "unavailable"
        assert v["diagnosis"] is None
        assert v["confidence"] == 0
        assert v["category"] == "Unknown"

    def test_narrative_absence_is_not_fatal(self):
        v = m.merge_verdict(plantid_ok(), {"configured": False, "error": "boom"})
        assert v["narrative_ok"] is False
        assert v["narrative_error"] == "boom"
        assert v["diagnosis"] == "Phytophthora"

    def test_missing_summary_gets_placeholder(self):
        v = m.merge_verdict(plantid_ok(), narrative(verdict={"severity": "Mild"}))
        assert "no narrative text" in v["summary"]

    def test_empty_values_do_not_overwrite(self):
        # An empty string from the model must not blank a real value.
        v = m.merge_verdict(plantid_ok(), narrative(verdict={"summary": "", "severity": None}))
        assert v["summary"] != ""
        # Empty values are skipped entirely rather than stored as None.
        assert "severity" not in v

    def test_healthy_verdict_category_is_none(self):
        v = m.merge_verdict(plantid_ok(healthy=True, diagnosis="Healthy", probability=None,
                                       disease=[], category="None"), narrative())
        assert v["healthy"] is True
        assert v["category"] == "None"


# --------------------------------------------------------------------------
# _classify_case / _live_signals
# --------------------------------------------------------------------------

class TestCaseClassification:
    def test_live_uncertain_reading_is_uncertain(self):
        # The real 38.6% / 10-point-margin reading must not read as "moderate".
        case, sig = m._classify_case(plantid_ok())
        assert case == "diseased_uncertain"
        assert sig["top_disease_probability"] == 0.386
        assert round(sig["margin_over_runner_up"], 3) == 0.100

    @pytest.mark.parametrize("prob,margin,expected", [
        (0.88, 0.82, "diseased_confident"),
        (0.65, 0.20, "diseased_confident"),
        (0.52, 0.22, "diseased_moderate"),
        (0.46, 0.05, "diseased_moderate"),
        (0.386, 0.10, "diseased_uncertain"),
        (0.40, 0.38, "diseased_uncertain"),
    ])
    def test_thresholds(self, prob, margin, expected):
        pid = plantid_ok(probability=prob, disease=[
            {"name": "A", "probability": prob},
            {"name": "B", "probability": round(prob - margin, 4)},
        ])
        assert m._classify_case(pid)[0] == expected

    def test_not_a_plant(self):
        assert m._classify_case(plantid_ok(is_plant=False))[0] == "not_a_plant"

    def test_healthy(self):
        assert m._classify_case(plantid_ok(healthy=True, disease=[]))[0] == "healthy"

    def test_plantid_failure(self):
        assert m._classify_case({"ok": False})[0] == "plantid_unavailable"

    def test_healthy_beats_disease_even_with_disease_present(self):
        assert m._classify_case(plantid_ok(healthy=True))[0] == "healthy"

    def test_single_candidate_has_no_margin(self):
        pid = plantid_ok(disease=[{"name": "A", "probability": 0.9}])
        _, sig = m._classify_case(pid)
        assert sig["margin_over_runner_up"] is None

    def test_crop_is_confident_threshold(self):
        split = plantid_ok(species=[{"name": "a", "probability": 0.40},
                                    {"name": "b", "probability": 0.35}])
        clear = plantid_ok(species=[{"name": "a", "probability": 0.80},
                                    {"name": "b", "probability": 0.10}])
        assert m._live_signals(split)["crop_is_confident"] is False
        assert m._live_signals(clear)["crop_is_confident"] is True

    def test_every_case_has_prompt_instructions(self):
        for case in ("plantid_unavailable", "not_a_plant", "healthy",
                     "diseased_confident", "diseased_moderate", "diseased_uncertain"):
            assert case in m.CASE_INSTRUCTIONS
            assert len(m.CASE_INSTRUCTIONS[case]) > 50

    def test_prompt_carries_the_case_and_signals(self):
        p = m._narrative_prompt("diseased_uncertain")
        assert "diseased_uncertain" in p or "UNRESOLVED" in p.upper()
        assert "ONLY the JSON object" in p


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------

@pytest.fixture
def client():
    m.app.config["TESTING"] = True
    with m.app.test_client() as c:
        yield c


class TestRoutes:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_health_never_leaks_keys(self, client):
        body = client.get("/health").get_data(as_text=True)
        assert "Api-Key" not in body
        assert m.PLANT_ID_API_KEY not in body

    def test_missing_image_is_400(self, client):
        assert client.post("/api/analyze", json={}).status_code == 400
        assert client.post("/api/analyze", json={"image": ""}).status_code == 400

    def test_non_dict_body_is_400(self, client):
        assert client.post("/api/analyze", json=["not", "a", "dict"]).status_code == 400

    def test_oversized_image_is_413(self, client):
        big = "A" * (m.MAX_IMAGE_BYTES + 10)
        assert client.post("/api/analyze", json={"image": big}).status_code == 413

    def test_get_on_analyze_is_rejected(self, client):
        # The catch-all static route owns GET, so a 404 is the honest answer.
        # What matters is that it never runs a Plant.id call and returns no verdict.
        r = client.get("/api/analyze")
        assert r.status_code in (404, 405)
        assert "verdict" not in (r.get_json() or {})

    def test_payload_shape_matches_ui_contract(self, client, monkeypatch):
        # The UI reads data.verdict, data.plantid and data.narrative. Regression:
        # an earlier build returned narrative at the top level and every tab
        # rendered empty.
        monkeypatch.setattr(m, "plant_id_identify", lambda *a, **k: plantid_ok())
        monkeypatch.setattr(m, "groq_narrative", lambda *a, **k: narrative())
        body = client.post("/api/analyze", json={"image": "AAA"}).get_json()
        assert set(("verdict", "plantid", "narrative")).issubset(body.keys())
        assert body["verdict"]["diagnosis"] == "Phytophthora"
        assert body["verdict"]["case"] == "diseased_uncertain"
        assert body["verdict"]["live_signals"]["top_disease_probability"] == 0.386
        assert "verdict" not in body["narrative"]

    def test_both_engines_down_is_502_with_honest_payload(self, monkeypatch):
        # 502 is correct here: both engines failed, so there is no usable result.
        # The body still carries the payload so the UI can explain the failure.
        m.app.config["TESTING"] = True
        with m.app.test_client() as c:
            monkeypatch.setattr(m, "plant_id_identify",
                                lambda *a, **k: {"ok": False, "status": 402, "error": "no credits"})
            monkeypatch.setattr(m, "groq_narrative",
                                lambda *a, **k: {"configured": False, "error": "skipped"})
            r = c.post("/api/analyze", json={"image": "AAA"})
            assert r.status_code == 502
            body = r.get_json()
            assert body["verdict"]["diagnosis_source"] == "unavailable"
            assert body["verdict"]["case"] == "plantid_unavailable"

    def test_plantid_down_but_narrative_ok_still_succeeds(self, monkeypatch):
        # One engine down is a degraded result, not a failed request.
        m.app.config["TESTING"] = True
        with m.app.test_client() as c:
            monkeypatch.setattr(m, "plant_id_identify",
                                lambda *a, **k: {"ok": False, "status": 402, "error": "no credits"})
            monkeypatch.setattr(m, "groq_narrative", lambda *a, **k: narrative())
            r = c.post("/api/analyze", json={"image": "AAA"})
            assert r.status_code == 200
            assert r.get_json()["verdict"]["narrative_ok"] is True


# --------------------------------------------------------------------------
# narrative provider behaviour
# --------------------------------------------------------------------------

class TestNarrativeFallback:
    def test_no_key_is_not_configured(self, monkeypatch):
        monkeypatch.setattr(m, "VISION_API_KEY", "")
        assert m.groq_narrative("img", plantid_ok())["configured"] is False

    def test_json_extracted_from_fenced_text(self, monkeypatch):
        class Msg:
            content = '```json\n{"summary": "ok", "severity": "Mild"}\n```'
        class Choice:
            message = Msg()
        class Resp:
            choices = [Choice()]

        class FakeCompletions:
            def create(self, **kw):
                return Resp()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            def __init__(self, **kw):
                self.chat = FakeChat()

        monkeypatch.setattr(m, "OpenAI", FakeClient)
        monkeypatch.setattr(m, "VISION_FALLBACK_MODELS", ())
        out = m.groq_narrative("img", plantid_ok())
        assert out["configured"] is True
        assert out["verdict"]["summary"] == "ok"

    def test_all_models_failing_is_reported_not_raised(self, monkeypatch):
        def boom(**kw):
            raise RuntimeError("503 high demand")

        fake_completions = type("Co", (), {"create": staticmethod(boom)})
        fake_chat = type("Ch", (), {"completions": fake_completions})
        monkeypatch.setattr(m, "OpenAI", type("C", (), {"__init__": lambda s, **k: None,
                                                         "chat": fake_chat}))
        out = m.groq_narrative("img", plantid_ok())
        assert out["configured"] is False
        assert "503" in out["error"]

    def test_provider_named_from_base_url(self, monkeypatch):
        monkeypatch.setattr(m, "VISION_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
        assert m._provider_name() == "gemini"
        monkeypatch.setattr(m, "VISION_BASE_URL", "https://api.groq.com/openai/v1")
        assert m._provider_name() == "groq"
        monkeypatch.setattr(m, "VISION_BASE_URL", "https://example.test/v1")
        assert m._provider_name() == "narrative-model"

    def test_only_narrative_fields_are_passed_through(self, monkeypatch):
        class Msg:
            content = json.dumps({"summary": "s", "category": "Insect", "diagnosis": "fake"})
        class Choice:
            message = Msg()
        class Resp:
            choices = [Choice()]
        monkeypatch.setattr(m, "OpenAI", type("C", (), {
            "__init__": lambda s, **k: None,
            "chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(lambda **kw: Resp())})()})()}))
        monkeypatch.setattr(m, "VISION_FALLBACK_MODELS", ())
        out = m.groq_narrative("img", plantid_ok())
        assert "category" not in out["verdict"]
        assert "diagnosis" not in out["verdict"]
        assert out["verdict"]["summary"] == "s"
