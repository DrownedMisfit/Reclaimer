"""
📚 ANALIZAR UN EDIT DE EJEMPLO (herramienta para enseñar a la IA nuevos estilos; no es una opción del usuario).
Se usa así: se analizan edits que le gustan al usuario, se mira el resultado y con él se crean o ajustan los estilos de
ai/edit_engine.py (su «taste») y los efectos. Así nacieron «🎴 Estilizado» y «📜 Historia / lore» (2026-10-10).

Lo que mide (estadística, ~2 s por edit):
  · a qué va cada corte: a los ATAQUES reales de la canción o a una rejilla fija (accent_sync);
  · cada cuánto cambia la IMAGEN y cuántos «cortes» son la MISMA imagen con otro look (look_share);
  · cuántos planos se quedan quietos (still_share); destellos y negativos por minuto; saltos de zoom;
  · planos largos que respiran y cuánto dura el plano final.

  analyze(path) -> perfil · mix([perfiles]) -> perfil medio (un «taste») · describe(perfil) -> en palabras
"""
from __future__ import annotations

import os
import subprocess

import numpy as np

from ..core import media as media_tools
from .base import CancelFn, ProgressFn, check_cancel, report

MAX_S = 240.0          # se mira como mucho 4 minutos
W = 160
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _frames(path: str, dur: float, w: int, h: int, color: bool = True) -> np.ndarray:
    fmt, ch = ("bgr24", 3) if color else ("gray", 1)
    p = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-t", f"{min(dur, MAX_S):.2f}", "-i", path,
                        "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", fmt, "-"],
                       capture_output=True, creationflags=NO_WINDOW)
    a = np.frombuffer(p.stdout, np.uint8)
    n = len(a) // (w * h * ch)
    return a[: n * w * h * ch].reshape((n, h, w, ch) if color else (n, h, w))


def _sim(a: np.ndarray, b: np.ndarray) -> float:
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    return float((a * b).mean())


def _onsets(path: str, dur: float) -> np.ndarray:
    """Ataques fuertes del audio (segundos)."""
    sr = 22050
    x = media_tools.decode_mono(path, sr)[: int(min(dur, MAX_S) * sr)].astype(np.float32)
    hop, win = 256, 1024
    n = 1 + (len(x) - win) // hop if len(x) >= win else 0
    if n < 8:
        return np.array([])
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    parts = []
    for c in range(0, n, 2048):
        mag = np.log1p(10 * np.abs(np.fft.rfft(x[idx[c:c + 2049]] * np.hanning(win), axis=1)))
        parts.append(np.maximum(0, np.diff(mag, axis=0)).mean(axis=1))
    on = np.concatenate(parts)
    on = (on - on.mean()) / (on.std() + 1e-9)
    pk = [i for i in range(2, len(on) - 2) if on[i] > 1.5 and on[i] == on[i - 2:i + 3].max()]
    return (np.array(pk) + 1) * hop / sr


def analyze(path: str, progress: ProgressFn = None, cancelled: CancelFn = None) -> dict:
    import cv2
    from . import edit_maker
    info = media_tools.probe(path)
    dur = min(float(info["duration"]), MAX_S)
    fps = float(info.get("fps") or 24.0) or 24.0
    h = max(2, int(round(W * info["height"] / max(1, info["width"]) / 2)) * 2)
    report(progress, 0.05, "📚 Mirando el edit de ejemplo…")
    fr = _frames(path, dur, W, h)
    check_cancel(cancelled)
    N = len(fr)
    if N < fps * 3:
        raise ValueError("El video es demasiado corto para aprender de él.")
    gray = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in fr]
    hsv = [cv2.cvtColor(x, cv2.COLOR_BGR2HSV) for x in fr]
    hd = np.zeros(N)
    pix = np.zeros(N)
    div = np.zeros(N)
    mag = np.zeros(N)
    small = [cv2.resize(g, (W // 2, h // 2)) for g in gray]
    for i in range(1, N):
        if i % 50 == 0:
            check_cancel(cancelled)
            report(progress, 0.05 + 0.6 * i / N, f"📚 Mirando el edit de ejemplo… {i / fps:.0f} de {N / fps:.0f} s")
        h1 = cv2.calcHist([hsv[i - 1]], [0, 1], None, [16, 8], [0, 180, 0, 256]).ravel()
        h2 = cv2.calcHist([hsv[i]], [0, 1], None, [16, 8], [0, 180, 0, 256]).ravel()
        hd[i] = 0.5 * np.abs(h1 / max(1, h1.sum()) - h2 / max(1, h2.sum())).sum()
        pix[i] = np.abs(gray[i].astype(np.int16) - gray[i - 1]).mean()
        fl = cv2.calcOpticalFlowFarneback(small[i - 1], small[i], None, 0.5, 2, 9, 2, 5, 1.1, 0)
        div[i] = float((np.gradient(fl[..., 0], axis=1) + np.gradient(fl[..., 1], axis=0)).mean())
        mag[i] = float(np.hypot(fl[..., 0].mean(), fl[..., 1].mean()))
    cuts = [i for i in range(1, N) if hd[i] > 0.35 and pix[i] > 18]
    # Cada corte: ¿imagen nueva, la misma con otro look, o un salto de zoom?
    kinds = []
    for c in cuts:
        A = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray[c - 1].astype(np.float32), cv2.CV_32F)), (5, 5), 0)
        B = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray[c].astype(np.float32), cv2.CV_32F)), (5, 5), 0)
        best, zbest = _sim(A, B), 1.0
        for z in (1.08, 1.15, 1.25, 1.4, 1.6):
            for X, Y in ((A, B), (B, A)):
                cw, ch = int(W / z), int(h / z)
                x0, y0 = (W - cw) // 2, (h - ch) // 2
                s = _sim(cv2.resize(X[y0:y0 + ch, x0:x0 + cw], (W, h)), Y)
                if s > best:
                    best, zbest = s, z
        if best < 0.35:
            kinds.append("nueva")
        elif zbest > 1.04:
            kinds.append("zoom")
        elif _sim(gray[c - 1].astype(np.float32), gray[c].astype(np.float32)) < -0.3:
            kinds.append("negativo")
        else:
            kinds.append("look")
    report(progress, 0.7, "📚 Escuchando la canción…")
    check_cancel(cancelled)
    song = edit_maker.analyze_song(path)
    tempo = float(song.get("tempo") or 100.0)
    per = 60.0 / max(tempo, 1.0)
    tc = np.array(cuts) / fps
    ons = _onsets(path, dur)
    hit = float(np.mean([np.min(np.abs(ons - t)) < 0.07 for t in tc])) if len(ons) and len(tc) else 0.0
    rng = np.random.default_rng(0)
    base = float(np.mean([np.mean([np.min(np.abs(ons - t)) < 0.07 for t in rng.uniform(0, dur, max(1, len(tc)))])
                          for _ in range(20)])) if len(ons) and len(tc) else 0.0
    accent = float(np.clip((hit - base) / max(1e-6, 1 - base), 0, 1))
    # Planos de imagen nueva (lo que dura cada imagen, juntando sus cambios de look)
    edges = [0.0] + [t for t, k in zip(tc, kinds) if k == "nueva"] + [N / fps]
    img = np.diff(edges)
    img = img[img > 0.05]
    allsh = np.diff([0.0] + list(tc) + [N / fps])
    still = moving = 0
    for a, b in zip([0.0] + list(tc), list(tc) + [N / fps]):
        i0, i1 = int(a * fps) + 2, int(b * fps) - 1
        if i1 - i0 < 3:
            continue
        if abs(div[i0:i1].mean()) > 0.004 or mag[i0:i1].mean() > 0.25:
            moving += 1
        else:
            still += 1
    lum = np.array([g.mean() for g in gray])
    flashes = sum(1 for i in range(2, N - 3) if lum[i] - min(lum[i - 2], lum[i - 1]) > 35 and lum[i] - lum[i + 3] > 25)
    mins = max(1e-6, (N / fps) / 60.0)
    nk = max(1, len(kinds))
    prof = {
        "name": os.path.splitext(os.path.basename(path))[0], "path": path, "dur": round(N / fps, 2),
        "tempo": round(tempo, 1), "cuts": len(cuts),
        "accent_sync": round(accent, 3), "cut_on_attack": round(hit, 3),
        "image_every_s": round(float(np.median(img)) if len(img) else 0.0, 3),
        "image_every_beats": round(float(np.median(img)) / per if len(img) else 0.0, 3),
        "shot_median_s": round(float(np.median(allsh)), 3),
        "look_share": round(kinds.count("look") / nk, 3),
        "invert_share": round(kinds.count("negativo") / nk, 3),
        "zoom_step_share": round(kinds.count("zoom") / nk, 3),
        "still_share": round(still / max(1, still + moving), 3),
        "flash_per_min": round(flashes / mins, 2),
        "invert_per_min": round(kinds.count("negativo") / mins, 2),
        "hold_share": round(float(np.mean(img >= 2.5)) if len(img) else 0.0, 3),
        "final_hold_s": round(float(img[-1]) if len(img) else 0.0, 2),
        "saturation": round(float(np.mean([x[..., 1].mean() for x in hsv])), 1),
    }
    report(progress, 1.0, "📚 Listo")
    return prof


KEYS = ("accent_sync", "image_every_beats", "look_share", "invert_share", "zoom_step_share", "still_share",
        "flash_per_min", "invert_per_min", "hold_share", "final_hold_s")


def mix(refs: list[dict]) -> dict | None:
    """El perfil medio de varios edits de ejemplo (sirve de «taste» para un estilo)."""
    if not refs:
        return None
    out = {k: round(float(np.mean([float(r.get(k, 0) or 0) for r in refs])), 3) for k in KEYS}
    out["n"] = len(refs)
    out["names"] = [r.get("name", "") for r in refs]
    return out


def describe(ref: dict | None) -> str:
    """Lo aprendido de tus ejemplos, en palabras."""
    if not ref:
        return ""
    bits = []
    if ref["accent_sync"] > 0.25:
        bits.append("los cortes van a los golpes fuertes de la canción (no a una rejilla fija)")
    bits.append(f"la imagen cambia cada ~{ref['image_every_beats']:.1f} golpes (Reclaimer no baja del mínimo de tu "
                "estilo: el ritmo lo ponen los cambios de look)")
    if ref["look_share"] > 0.2:
        bits.append(f"en {ref['look_share']:.0%} de los golpes la MISMA imagen cambia de look (color, glitch)")
    if ref["still_share"] > 0.6:
        bits.append(f"{ref['still_share']:.0%} de los planos quietos (poco zoom)")
    if ref["flash_per_min"] < 2:
        bits.append("casi sin destellos")
    if ref["invert_per_min"] < 6:
        bits.append("negativo solo de vez en cuando")
    if ref["hold_share"] > 0.05 or ref["final_hold_s"] > 3:
        bits.append("algún plano largo que respira y un final largo")
    return "; ".join(bits)
