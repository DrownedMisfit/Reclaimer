"""
Módulo de IA: MEJORES FOTOGRAMAS PARA LA MINIATURA.

Recorre el material de tu video (los clips usados en la línea de tiempo; si no hay, toda la
biblioteca) y propone los fotogramas con más posibilidades de funcionar como miniatura:

  + caras (y que sean grandes y estén bien colocadas), personajes en primer plano,
  + nitidez, contraste y color (sin pasarse), una composición fácil de leer,
  + relación con el tema del video (si lo hay: título, temas detectados),
  − fotogramas oscuros, quemados, borrosos, en plena transición o casi repetidos.

No elige al azar: cada propuesta dice por qué («rostro grande», «muy nítido», «alto contraste»…).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from .base import CancelFn, ProgressFn, check_cancel, report

STEP = 2.0          # un fotograma cada 2 s
W_SMALL = 384       # tamaño para analizar (rápido)


@dataclass
class Candidate:
    media_id: str
    time: float
    score: float
    reasons: list[str] = field(default_factory=list)
    path: str = ""          # fotograma a resolución completa (se extrae al final)
    vec: np.ndarray | None = None


def _frames(path: str, start: float, dur: float, cancelled: CancelFn):
    """Fotogramas pequeños (RGB) cada STEP segundos entre start y start+dur."""
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, start):.2f}", "-t", f"{dur:.2f}",
            "-skip_loop_filter", "all",   # ⚡ sin filtro de desbloqueo: ~25 % más rápido; en imágenes pequeñas para analizar no cambia nada
            "-i", path, "-an", "-sn", "-vf", f"fps=1/{STEP:g},scale={W_SMALL}:-2", "-pix_fmt", "rgb24",
            "-f", "rawvideo", "-"]
    probe = media_tools.probe(path)
    w = W_SMALL
    h = int(round(W_SMALL * probe["height"] / max(1, probe["width"]) / 2) * 2) or 216
    n = w * h * 3
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=flags)
    try:
        k = 0
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            if cancelled is not None and k % 20 == 0:
                check_cancel(cancelled)
            yield start + STEP / 2 + k * STEP, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            k += 1
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def _metrics(rgb: np.ndarray) -> dict:
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lum = g.astype(np.float32) / 255
    sharp = float(cv2.Laplacian(g, cv2.CV_32F).var())
    r, gg, b = [rgb[..., i].astype(np.float32) for i in range(3)]
    rg, yb = r - gg, 0.5 * (r + gg) - b
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)) / 100
    # Bandas negras arriba/abajo (cinemáticas): se mide el contenido sin ellas
    rows = lum.mean(axis=1)
    content = rows > 0.04
    letter = 1 - content.mean()
    return {"bright": float(lum.mean()), "contrast": float(lum.std()), "sharp": sharp, "color": colorful,
            "letterbox": float(letter), "edges": float((cv2.Canny(g, 80, 160) > 0).mean())}


def find(media: list[dict], topic_text: str = "", top: int = 12, progress: ProgressFn = None,
         cancelled: CancelFn = None) -> list[Candidate]:
    """media: [{media_id, path, kind, duration, ranges: [(ini, fin)] (trozos usados; vacío = todo)}]."""
    from . import embeddings
    from .tracking import detect_faces
    cands: list[Candidate] = []
    total = sum(sum(b - a for a, b in (m.get("ranges") or [(0, m["duration"])])) for m in media) or 1
    done = 0.0
    for m in media:
        if m["kind"] != "video":
            continue
        for a, b in (m.get("ranges") or [(0.0, m["duration"])]):
            if b - a < 0.5:
                continue
            for t, rgb in _frames(m["path"], a, b - a, cancelled):
                done += STEP
                if len(cands) % 10 == 0:
                    report(progress, min(0.8, 0.8 * done / total), "Mirando los fotogramas de tu video…")
                mt = _metrics(rgb)
                if mt["bright"] < 0.08 or mt["bright"] > 0.92 or mt["sharp"] < 25 or mt["contrast"] < 0.05:
                    continue      # negro, quemado, borroso o plano: descartado
                score, why = 0.0, []
                faces = detect_faces(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                if faces:
                    fx, fy, fw, fh, conf = faces[0]
                    size = fh
                    cx, cy = fx + fw / 2, fy + fh / 2
                    s = min(1.0, size / 0.35)                      # cuanto más grande (hasta ~35 % del alto)
                    thirds = 1 - min(abs(cx - 1 / 3), abs(cx - 2 / 3), abs(cx - 0.5)) * 3
                    score += 2.2 * s * conf + 0.4 * max(0.0, thirds)
                    why.append("rostro grande" if size > 0.25 else "rostro")
                    if len(faces) == 2:
                        score += 0.2
                        why.append("dos personas")
                sh = min(1.0, np.log1p(mt["sharp"]) / np.log1p(1500))
                score += 0.9 * sh
                if sh > 0.85:
                    why.append("muy nítido")
                score += 0.8 * min(1.0, mt["contrast"] / 0.28)
                if mt["contrast"] > 0.25:
                    why.append("alto contraste")
                score += 0.5 * min(1.0, mt["color"] / 0.6) - 0.6 * max(0.0, mt["color"] - 1.1)
                if 0.4 < mt["color"] < 1.1:
                    why.append("buen color")
                score -= 0.6 * max(0.0, mt["edges"] - 0.18) * 5      # demasiado detalle = difícil de leer
                score -= 0.3 * mt["letterbox"]
                cands.append(Candidate(m["media_id"], round(t, 2), score, why))
    if not cands:
        return []
    # Afinar con la IA de imágenes: personajes en primer plano y relación con el tema
    cands.sort(key=lambda c: -c.score)
    pre = cands[:max(top * 6, 60)]
    report(progress, 0.85, "Buscando personajes y el tema del video…")
    by_media = {m["media_id"]: m for m in media}
    small = []
    for c in pre:
        img = _grab(by_media[c.media_id]["path"], c.time, 224)
        small.append(img if img is not None else np.zeros((224, 224, 3), np.uint8))
    try:
        enc_i = embeddings.get("clip_image")
        enc_t = embeddings.get("clip_text")
        vecs = enc_i.encode(np.stack(small))
        prompts = ["un primer plano de un personaje", "un retrato de una persona con expresión intensa",
                   "a close-up of a video game character"]
        char = enc_t.encode(prompts).mean(0)
        char /= np.linalg.norm(char) + 1e-9
        cs = vecs @ char
        z = (cs - cs.mean()) / (cs.std() + 1e-6)
        for c, v, zz in zip(pre, vecs, z):
            c.vec = v
            c.score += 0.35 * float(zz)
            if zz > 1.0 and "rostro" not in " ".join(c.reasons):
                c.reasons.append("personaje en primer plano")
        if topic_text.strip():
            tv = enc_t.encode([topic_text]).mean(0)
            tv /= np.linalg.norm(tv) + 1e-9
            ts = vecs @ tv
            tz = (ts - ts.mean()) / (ts.std() + 1e-6)
            for c, zz in zip(pre, tz):
                c.score += 0.3 * float(zz)
                if zz > 1.2:
                    c.reasons.append("encaja con el tema")
    except Exception:  # noqa: BLE001 - sin modelos de IA: se usa lo medido
        pass
    # Variedad: nada casi repetido (mismo momento o imagen muy parecida)
    pre.sort(key=lambda c: -c.score)
    chosen: list[Candidate] = []
    for c in pre:
        dup = False
        for o in chosen:
            if o.media_id == c.media_id and abs(o.time - c.time) < 6:
                dup = True
            elif c.vec is not None and o.vec is not None and float(c.vec @ o.vec) > 0.93:
                dup = True
            if dup:
                break
        if not dup:
            chosen.append(c)
        if len(chosen) >= top:
            break
    # Fotograma a resolución completa de cada propuesta
    for i, c in enumerate(chosen):
        report(progress, 0.9 + 0.1 * i / len(chosen), "Preparando las propuestas…")
        p = by_media[c.media_id]["path"]
        out = os.path.join(str(cache_dir("miniaturas_material")), f"{media_tools.cache_key(p)}_{c.time:.2f}.png")
        if not os.path.exists(out):
            media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{c.time:.3f}",
                                   "-i", p, "-frames:v", "1", out], timeout=60)
        c.path = out if os.path.exists(out) else ""
        if not c.reasons:
            c.reasons.append("buena composición")
    return [c for c in chosen if c.path]


def _grab(path: str, t: float, size: int) -> np.ndarray | None:
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.2f}",
                               "-i", path, "-frames:v", "1", "-vf",
                               f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}",
                               "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], timeout=60)
    if r.returncode != 0 or len(r.stdout) != size * size * 3:
        return None
    return np.frombuffer(r.stdout, np.uint8).reshape(size, size, 3)
