"""
Módulo de IA: "HUELLAS DE SIGNIFICADO" (embeddings).

Convierte frases e imágenes en listas de números que representan su significado.
Dos cosas parecidas tienen huellas parecidas, así que se pueden comparar:
  - Frase ↔ frase       (temas de la narración)
  - Frase ↔ imagen      (buscar clips con palabras, sugerir B-roll)

Modelos locales y gratuitos (ONNX, funcionan en el procesador):
  - CLIP multilingüe (texto en español → mismo "espacio" que las imágenes)
  - CLIP de imágenes
  - Modelo de frases multilingüe (para los temas)
"""
from __future__ import annotations

import json
import os
import struct
import threading

import numpy as np

from .base import ProgressFn, report
from .transcription import models_dir

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# clave -> (repositorio, modelo ONNX cuantizado, modelo ONNX normal, archivos extra, MB aprox.)
MODELS = {
    "clip_text": ("sentence-transformers/clip-ViT-B-32-multilingual-v1", "onnx/model_quint8_avx2.onnx",
                  "onnx/model.onnx", ["tokenizer.json", "2_Dense/model.safetensors"], 135),
    "clip_image": ("Qdrant/clip-ViT-B-32-vision", "model.onnx", "model.onnx", [], 352),
    "sentence": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                 "onnx/model_quint8_avx2.onnx", "onnx/model.onnx", ["tokenizer.json"], 118),
}

CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
IMAGE_SIZE = 224

_lock = threading.Lock()
_loaded: dict[str, object] = {}


def is_available() -> tuple[bool, str]:
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False, "Faltan componentes de IA. Ejecuta INSTALAR.bat."
    return True, ""


def _cache() -> str:
    d = models_dir() / "huellas"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _repo_dir(repo: str) -> str:
    # Archivos normales en una carpeta por modelo (los enlaces simbólicos de la caché
    # de Hugging Face pueden fallar en Windows)
    return os.path.join(_cache(), repo.replace("/", "--"))


def is_downloaded(key: str) -> bool:
    repo, quant, _full, extra, _mb = MODELS[key]
    return all(os.path.isfile(os.path.join(_repo_dir(repo), f)) for f in [quant] + extra)


def _download(key: str, progress: ProgressFn = None) -> dict[str, str]:
    from huggingface_hub import hf_hub_download
    repo, quant, _full, extra, mb = MODELS[key]
    if is_downloaded(key):   # ya está en el PC: no se conecta a internet
        return {f: os.path.join(_repo_dir(repo), f) for f in [quant] + extra}
    report(progress, 0.0, f"Descargando modelo de IA (~{mb} MB, solo la primera vez)…")
    return {f: hf_hub_download(repo, f, local_dir=_repo_dir(repo)) for f in [quant] + extra}


def load_safetensors(path: str) -> dict[str, np.ndarray]:
    """Lector mínimo del formato safetensors (evita instalar otra librería)."""
    dtypes = {"F32": np.float32, "F16": np.float16, "F64": np.float64}
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
        data = f.read()
    out = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        a, b = meta["data_offsets"]
        out[name] = np.frombuffer(data[a:b], dtype=dtypes[meta["dtype"]]).reshape(meta["shape"]).astype(np.float32)
    return out


def _session(path: str):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    opts.log_severity_level = 3
    return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])


def _normalize(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)


class TextEncoder:
    """Frases → huellas normalizadas."""

    def __init__(self, key: str, progress: ProgressFn = None):
        from tokenizers import Tokenizer
        files = _download(key, progress)
        repo, quant, _full, _extra, _mb = MODELS[key]
        self.session = _session(files[quant])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tokenizer = Tokenizer.from_file(files["tokenizer.json"])
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.enable_padding()
        dense = files.get("2_Dense/model.safetensors")
        self.dense = next(iter(load_safetensors(dense).values())) if dense else None

    def encode(self, texts: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tokenizer.encode_batch([t or " " for t in texts[i:i + batch]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            tokens = self.session.run(None, feed)[0]                 # [n, tokens, dim]
            m = mask[..., None].astype(np.float32)
            pooled = (tokens * m).sum(1) / np.maximum(m.sum(1), 1e-9)  # media de los tokens
            if self.dense is not None:
                pooled = pooled @ self.dense.T                       # 768 → 512 (espacio CLIP)
            out.append(pooled)
        return _normalize(np.concatenate(out)) if out else np.zeros((0, 512), np.float32)


class ImageEncoder:
    """Imágenes RGB uint8 de 224x224 → huellas CLIP normalizadas."""

    def __init__(self, progress: ProgressFn = None):
        files = _download("clip_image", progress)
        self.session = _session(files[MODELS["clip_image"][1]])
        self.input = self.session.get_inputs()[0].name

    def encode(self, images: np.ndarray, batch: int = 16) -> np.ndarray:
        out = []
        for i in range(0, len(images), batch):
            x = images[i:i + batch].astype(np.float32) / 255.0
            x = (x - CLIP_MEAN) / CLIP_STD
            x = x.transpose(0, 3, 1, 2)                              # [n, 3, 224, 224]
            out.append(self.session.run(None, {self.input: x})[0])
        return _normalize(np.concatenate(out)) if out else np.zeros((0, 512), np.float32)


def get(name: str, progress: ProgressFn = None):
    """Modelos compartidos (se cargan una vez): 'clip_text', 'clip_image', 'sentence'."""
    with _lock:
        if name not in _loaded:
            _loaded[name] = ImageEncoder(progress) if name == "clip_image" else TextEncoder(name, progress)
        return _loaded[name]
