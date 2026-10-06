# Trained model weights

Drop these two files here after running `../train_free_leaf_model.py` in Colab:

- `leaf_model_int8.onnx` (or `leaf_model.onnx` if the quantized version is bigger)
- `labels.json`

The UI probes for `labels.json` before showing the on-device card, so the deploy
works fine with this folder empty. Nothing else breaks while you wait for weights.

`leaf_model.onnx` is gitignored deliberately: it is a ~90 MB binary and the repo
should not carry model artifacts. Upload it to Vercel with:

```
vercel.cmd deploy --prod --archive=tgz
```

after placing the files, or copy them into a fresh deploy. Do not commit them.
