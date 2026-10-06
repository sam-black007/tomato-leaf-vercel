"""Checks the live-case classifier against real Plant.id response shapes."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
os.environ.setdefault("VISION_API_KEY", "test")
os.environ.setdefault("PLANT_ID_API_KEY", "test")
import index as m

CASES = [
    ("api failure", {"ok": False, "error": "boom"}, "plantid_unavailable"),
    ("not a plant", {"ok": True, "is_plant": False, "is_plant_score": 0.1, "healthy": False,
                      "disease": [{"name": "Phytophthora", "probability": 0.9}]}, "not_a_plant"),
    ("healthy", {"ok": True, "is_plant": True, "is_plant_score": 0.99, "healthy": True,
                 "disease": []}, "healthy"),
    ("confident disease", {"ok": True, "is_plant": True, "healthy": False,
                           "disease": [{"name": "Alternaria", "probability": 0.88},
                                       {"name": "Septoria", "probability": 0.06}]}, "diseased_confident"),
    ("moderate disease", {"ok": True, "is_plant": True, "healthy": False,
                          "disease": [{"name": "Phytophthora", "probability": 0.52},
                                      {"name": "Botrytis", "probability": 0.30}]}, "diseased_moderate"),
    ("low top but clear winner", {"ok": True, "is_plant": True, "healthy": False,
                                  "disease": [{"name": "Phytophthora", "probability": 0.40},
                                              {"name": "Botrytis", "probability": 0.02}]},
     "diseased_uncertain"),
    ("uncertain disease (live case)", {"ok": True, "is_plant": True, "healthy": False,
                                       "disease": [{"name": "Phytophthora", "probability": 0.386},
                                                   {"name": "Botrytis", "probability": 0.286},
                                                   {"name": "Alternaria", "probability": 0.166}]},
     "diseased_uncertain"),
]

failed = False
for label, pid, want in CASES:
    got, signals = m._classify_case(pid)
    ok = got == want
    failed |= not ok
    margin = signals["margin_over_runner_up"]
    print(f"{'PASS' if ok else 'FAIL'}  {label:32} -> {got:22} margin={margin}")

print("\nEvery case has prompt instructions:",
      all(c in m.CASE_INSTRUCTIONS for c in
          ("plantid_unavailable", "not_a_plant", "healthy", "diseased_confident",
           "diseased_moderate", "diseased_uncertain")))
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
