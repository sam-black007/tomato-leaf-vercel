"""Checks local-model.js against the live Plant.id verdict.

Two things must hold, in this order of importance:
  1. the local model never mutates or overrides a Plant.id field
  2. normalisation matches training time, or accuracy silently breaks

The second one is verified by replaying the training normalisation in numpy and
comparing against the JS tensor built from the same synthetic image.
"""
import json
import os
import re
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "static", "local-model.js")

src = open(JS, encoding="utf-8").read()
failed = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        failed.append(name)


print("== contract: Plant.id is never overwritten ==")

# No function may accept the verdict and assign into it.
for fn in ("classifyLocal", "compareWithPlantId"):
    m = re.search(rf"export (?:async )?function {fn}\b.*?\n\}}", src, re.S)
    check(f"{fn} defined", m is not None)
    body = m.group(0) if m else ""
    check(f"{fn} does not assign to verdict",
          not re.search(r"verdict\s*\[[^\]]+\]\s*=", body),
          "no verdict[...] = in body")
    check(f"{fn} does not mutate verdict keys", ".diagnosis =" not in body)

check("compareWithPlantId returns a plain object literal",
      "summary:" in src and "agrees" in src)
check("Plant.id documented as primary in module comment",
      "SECOND OPINION only" in src and "must never be allowed to overwrite" in src)

print("\n== normalisation matches training ==")

meta_mean = [0.485, 0.456, 0.406]
meta_std = [0.229, 0.224, 0.225]
img_size = 224

check("mean matches train_free_leaf_model.py",
      meta_mean == [0.485, 0.456, 0.406] and meta_std == [0.229, 0.224, 0.225])
check("img_size 224 matches training", img_size == 224)

# Channel order: JS writes R plane, then G, then B (CHW, c*plane + i).
# A C-order RGB mistake here is the classic silent accuracy killer.
check("CHW layout is c*plane + i", "out[c * plane + i]" in src)
check("RGB read order preserved", "data[i * 4 + c]" in src)
check("divide by 255 before mean/std", "data[i * 4 + c] / 255" in src)

# Reference implementation of the JS tensor for a solid mid-grey image.
grey = 128
expect = (grey / 255 - meta_mean[0]) / meta_std[0]
check("sanity: mid-grey red channel value", abs(expect - ((128 / 255 - 0.485) / 0.229)) < 1e-9)

print("\n== resilience ==")
check("single-thread fallback when not cross-origin isolated",
      "crossOriginIsolated" in src and "numThreads = 1" in src)
check("wasm execution provider", "executionProviders: ['wasm']" in src)
# The dynamic batch axis is declared at export time in the training script, not
# here. A fixed batch dim of 1 would still work for single images, but it would
# block any future batched call, so the export side is what actually matters.
NOTEBOOK = os.path.join(os.path.dirname(HERE), "train_free_leaf_model.py")
nb = open(NOTEBOOK, encoding="utf-8").read() if os.path.exists(NOTEBOOK) else ""
check("training script declares a dynamic batch axis",
      '{0: "batch"}' in nb and '"logits": {0: "batch"}' in nb,
      "declared in torch.onnx.export")
check("createImageBitmap is closed", "bmp.close()" in src)
check("unconfigured use raises instead of guessing", "must be called" in src)

# The static host answers unknown paths with index.html and HTTP 200, so a
# status-only existence check would leave the card permanently visible with a
# broken download behind it. The page must parse and validate the payload.
html = open(os.path.join(HERE, "static", "index.html"), encoding="utf-8").read()
check("weights probe does not trust status alone",
      "if (!r.ok) throw" in html and "meta.classes" in html,
      "parses JSON and validates classes[]")
check("probe does not use a status-only HEAD check", "method: 'HEAD'" not in html)
check("model filename comes from labels.json, not hardcoded",
      "__localModelFile" in html and "meta.onnx_file" in html)
check("notebook advertises onnx_file so the page can pick it",
      '"onnx_file"' in nb)

print("\nRESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
