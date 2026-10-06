/* Optional browser-side plant classifier. Runs entirely on the student's device.
 *
 * This is the "truly unlimited" path: no API key, no quota, no server cost, and it
 * keeps working offline once the model file has been cached.
 *
 * It is a SECOND OPINION only. Plant.id stays the primary structured source,
 * because a PlantVillage-trained model is materially weaker on field photos.
 * This file must never be allowed to overwrite a Plant.id field.
 */

const ORT_VERSION = '1.20.1';
const ORT_CDN = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VERSION}/dist`;

let session = null;
let labels = null;
let loading = null;
const meta = { mean: [0.485, 0.456, 0.406], std: [0.229, 0.224, 0.225], imgSize: 224 };

function ortReady() {
  if (window.ort) return Promise.resolve(window.ort);
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `${ORT_CDN}/ort.min.js`;
    s.onload = () => resolve(window.ort);
    s.onerror = () => reject(new Error('Could not load onnxruntime-web from CDN'));
    document.head.appendChild(s);
  });
}

/* Training-time normalisation happens here so the student device does the same
 * math the model was fitted with. Skipping this silently wrecks accuracy. */
function toTensor(imageBitmap) {
  const { imgSize, mean, std } = meta;
  const canvas = document.createElement('canvas');
  canvas.width = imgSize;
  canvas.height = imgSize;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const scale = Math.max(imgSize / imageBitmap.width, imgSize / imageBitmap.height);
  const w = imageBitmap.width * scale;
  const h = imageBitmap.height * scale;
  ctx.drawImage(imageBitmap, (imgSize - w) / 2, (imgSize - h) / 2, w, h);

  const { data } = ctx.getImageData(0, 0, imgSize, imgSize);
  const out = new Float32Array(3 * imgSize * imgSize);
  const plane = imgSize * imgSize;
  for (let i = 0; i < plane; i++) {
    for (let c = 0; c < 3; c++) {
      out[c * plane + i] = (data[i * 4 + c] / 255 - mean[c]) / std[c];
    }
  }
  return new window.ort.Tensor('float32', out, [1, 3, imgSize, imgSize]);
}

export async function loadLocalModel({ modelUrl, labelsUrl }) {
  if (session && labels) return { session, labels };
  if (loading) return loading;

  loading = (async () => {
    const ort = await ortReady();
    // Threads need cross-origin isolation; fall back to a single thread so this
    // still works when the page is not served with COOP/COEP headers.
    try {
      ort.env.wasm.numThreads = crossOriginIsolated ? navigator.hardwareConcurrency || 4 : 1;
      ort.env.wasm.simd = true;
    } catch (e) {
      ort.env.wasm.numThreads = 1;
    }

    const [sess, lbl] = await Promise.all([
      ort.InferenceSession.create(modelUrl, { executionProviders: ['wasm'] }),
      fetch(labelsUrl).then((r) => {
        if (!r.ok) throw new Error(`labels.json missing (${r.status})`);
        return r.json();
      }),
    ]);

    if (Array.isArray(lbl.img_size)) meta.imgSize = lbl.img_size[0];
    if (lbl.mean) meta.mean = lbl.mean;
    if (lbl.std) meta.std = lbl.std;

    session = sess;
    labels = lbl;
    return { session, labels };
  })().catch((err) => {
    loading = null;
    throw err;
  });

  return loading;
}

export async function classifyLocal(fileOrBlob) {
  const { session: s, labels: lbl } = await loadLocalModel(getConfiguredUrls());
  const bmp = await createImageBitmap(fileOrBlob);
  try {
    const feeds = { input: toTensor(bmp) };
    const outputName = s.outputNames[0];
    const results = await s.run(feeds);
    const logits = results[outputName].data;

    const probs = softmax(Array.from(logits));
    const ranked = probs
      .map((p, i) => ({ label: lbl.classes[i], probability: p }))
      .sort((a, b) => b.probability - a.probability);

    return {
      available: true,
      top: ranked[0],
      top3: ranked.slice(0, 3),
      field_top1: lbl.field_top1 ?? null,
      source: 'local-onnx',
      note: 'Second opinion only. PlantVillage-trained, so weakest on field photos.',
    };
  } finally {
    bmp.close();
  }
}

function softmax(v) {
  const max = Math.max(...v);
  const e = v.map((x) => Math.exp(x - max));
  const sum = e.reduce((a, b) => a + b, 0);
  return e.map((x) => x / sum);
}

let urls = null;
export function configureLocalModel(modelUrl, labelsUrl) {
  urls = { modelUrl, labelsUrl };
}
function getConfiguredUrls() {
  if (!urls) {
    throw new Error('configureLocalModel(modelUrl, labelsUrl) must be called before classifyLocal');
  }
  return urls;
}

/* Deliberately advisory. Returns a plain-language comparison and never mutates
 * the verdict that Plant.id produced. */
export function compareWithPlantId(local, verdict) {
  if (!local || !local.available || !verdict) return null;

  const plantDiagnosis = verdict.diagnosis || '';
  const localLabel = (local.top?.label || '').split('___').slice(1).join(' ') || local.top?.label || '';
  const agrees = localLabel && plantDiagnosis
    ? localLabel.toLowerCase().replace(/[_ ]/g, '').includes(plantDiagnosis.toLowerCase().replace(/[_ ]/g, ''))
    : false;

  return {
    plantid: { diagnosis: plantDiagnosis, confidence: verdict.confidence ?? null },
    local: { label: local.top?.label ?? null, confidence: local.top ? Math.round(local.top.probability * 100) : null },
    agrees,
    summary: agrees
      ? 'Both engines agree on the disease.'
      : local.top
        ? `Plant.id reports ${plantDiagnosis || 'no disease'} while the local model leans ${localLabel}. Plant.id stays the primary reading; treat the local result as a weaker opinion trained on studio images.`
        : '',
  };
}
