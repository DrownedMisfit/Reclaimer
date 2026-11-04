"""
Módulo de IA: ESTRUCTURA DE LA CANCIÓN para los edits (como hacen mugen y AV-Sync, sin librerías extra).

  · Batería: bombo (graves), caja (medios + chasquido) y platillos (agudos), por bandas de frecuencia
    (una versión ligera de la separación armónico/percusiva de librosa).
  · Compases: en qué golpe cae el «1» (donde más bombo hay) → cortes en el inicio de compás.
  · Secciones: intro · subida (build-up) · drop · pausa (break) · final, por la energía de cada compás.
  · Paradas: instantes en que la música se calla (para congelar la imagen o ir a negro).
Todo en segundos de la canción.
"""
from __future__ import annotations

import numpy as np

BANDS = {"kick": (30, 120), "snare": (150, 400), "snare_hi": (2000, 6000), "hat": (7000, 14000)}


def _peaks(env: np.ndarray, fps: float, min_gap: float = 0.09, k: float = 1.4) -> list[float]:
    """Picos de un envoltorio (golpes): máximos locales por encima de su media móvil."""
    if len(env) < 5:
        return []
    w = max(3, int(fps * 0.5))
    mov = np.convolve(env, np.ones(w) / w, mode="same")
    thr = mov + k * float(env.std())
    gap = max(1, int(min_gap * fps))
    out, last = [], -10 ** 9
    for i in range(1, len(env) - 1):
        if env[i] > thr[i] and env[i] >= env[i - 1] and env[i] >= env[i + 1] and i - last >= gap:
            out.append(i / fps)
            last = i
    return out


def drums(samples: np.ndarray, sr: int, hop: int = 512, win: int = 2048) -> dict:
    """{"fps", "kick", "snare", "hat": envoltorios 0–1, "kick_t", "snare_t", "hat_t": golpes (s)}"""
    n = 1 + (len(samples) - win) // hop if len(samples) >= win else 0
    if n <= 2:
        return {"fps": sr / hop, "kick": np.zeros(1), "snare": np.zeros(1), "hat": np.zeros(1),
                "kick_t": [], "snare_t": [], "hat_t": []}
    out = {"fps": sr / hop}
    f = np.fft.rfftfreq(win, 1 / sr)
    window = np.hanning(win).astype(np.float32)
    envs = {k: np.zeros(n, np.float32) for k in BANDS}
    prev = None
    chunk = 512
    for c0 in range(0, n, chunk):           # por trozos: poca memoria con canciones largas
        c1 = min(n, c0 + chunk + 1)
        idx = np.arange(win)[None, :] + hop * np.arange(c0, c1)[:, None]
        mag = np.log1p(10 * np.abs(np.fft.rfft(samples[idx] * window[None, :], axis=1)))
        if prev is not None:
            mag = np.vstack([prev[None, :], mag])
            base = c0 - 1
        else:
            base = c0
        diff = np.maximum(0.0, np.diff(mag, axis=0))
        for name, (lo, hi) in BANDS.items():
            sel = (f >= lo) & (f < hi)
            e = diff[:, sel].mean(axis=1)
            envs[name][base + 1:base + 1 + len(e)] = e[: max(0, n - base - 1)]
        prev = mag[-1]
    norm = lambda x: x / (np.percentile(x, 99) + 1e-9)   # noqa: E731
    kick = norm(envs["kick"])
    snare = norm(0.5 * norm(envs["snare"]) + norm(envs["snare_hi"]))
    hat = norm(envs["hat"])
    fps = out["fps"]
    shift = win / 2 / sr                     # el golpe se ve cuando entra en la ventana
    out.update(kick=np.clip(kick, 0, 1.5), snare=np.clip(snare, 0, 1.5), hat=np.clip(hat, 0, 1.5))
    out["kick_t"] = [round(t + shift, 3) for t in _peaks(kick, fps, 0.12, 1.2)]
    out["snare_t"] = [round(t + shift, 3) for t in _peaks(snare, fps, 0.12, 1.4)]
    out["hat_t"] = [round(t + shift, 3) for t in _peaks(hat, fps, 0.06, 1.6)]
    return out


def beat_hits(beats: list[float], d: dict, tol: float = 0.07) -> list[dict]:
    """Para cada golpe: cuánto bombo, caja y platillo suena justo ahí (0–1)."""
    fps = d["fps"]
    shift = 1024 / (fps * 512) if fps else 0.0
    out = []
    for b in beats:
        i = int((b - shift) * fps)
        a, z = max(0, i - int(tol * fps)), i + int(tol * fps) + 1
        val = {k: round(float(min(1.0, d[k][a:z].max())) if z > a and a < len(d[k]) else 0.0, 3)
               for k in ("kick", "snare", "hat")}
        out.append(val)
    return out


def fix_offbeat(beats: list[float], d: dict, duration: float, reach: int = 4) -> tuple[list[float], bool]:
    """Si el detector de golpes se enganchó al contratiempo (los platillos entre bombos), mueve la rejilla
    medio golpe para que caiga sobre el bombo. Se mira por TRAMOS (±4 golpes): el detector puede ir bien
    al principio y engancharse al contratiempo más tarde. Devuelve (golpes, si se movió alguno)."""
    if len(beats) < 8 or not len(d.get("kick", [])):
        return beats, False
    fps = d["fps"]
    shift = 1024 / (fps * 512)
    kick = np.asarray(d["kick"])

    def at(t):
        i = int((t - shift) * fps)
        a, z = max(0, i - 2), min(len(kick), i + 3)
        return float(kick[a:z].max()) if z > a else 0.0
    b = np.asarray(beats, np.float64)
    period = float(np.median(np.diff(b)))
    half = np.append(np.diff(b), period) / 2
    on = np.array([at(t) for t in b])
    off = np.array([at(t) for t in b + half])
    moved, out = False, []
    for i, t in enumerate(b):
        lo, hi = max(0, i - reach), min(len(b), i + reach + 1)
        on_v, off_v = float(on[lo:hi].mean()), float(off[lo:hi].mean())
        if off_v > 1.3 * on_v and off_v > 0.15:
            t = t + half[i]
            moved = True
        out.append(float(t))
    if moved and out[0] > b[0] + 1e-6 and out[0] - 2 * half[0] >= 0:   # el golpe de antes del primero
        out.insert(0, float(out[0] - 2 * half[0]))
    res: list[float] = []
    for t in sorted(out):
        if 0 <= t < duration and (not res or t - res[-1] >= 0.6 * period):
            res.append(round(t, 4))
    return res, moved


def snap_beats(beats: list[float], d: dict, frac: float = 0.3, reach: int = 4) -> list[float]:
    """Alinea la rejilla de golpes con el BOMBO real (o la caja si no hay bombo cerca): para cada golpe se
    mira cuánto se desvía el bombo más cercano y se usa la mediana de los ±4 golpes vecinos (robusto: un
    platillo suelto no mueve nada). Así los cortes caen justo en el golpe aunque el detector se adelante."""
    if len(beats) < 4:
        return beats
    b = np.asarray(beats, np.float64)
    period = float(np.median(np.diff(b)))

    def offsets(hits):
        hits = np.asarray(sorted(hits), np.float64)
        off = np.full(len(b), np.nan)
        if not len(hits):
            return off
        for i, t in enumerate(b):
            j = int(np.searchsorted(hits, t))
            cand = [hits[k] for k in (j - 1, j) if 0 <= k < len(hits)]
            c = min(cand, key=lambda h: abs(h - t))
            if abs(c - t) <= frac * period:
                off[i] = c - t
        return off
    ko, so = offsets(d.get("kick_t", [])), offsets(d.get("snare_t", []))
    out = []
    for i in range(len(b)):
        lo, hi = max(0, i - reach), min(len(b), i + reach + 1)
        k = ko[lo:hi][~np.isnan(ko[lo:hi])]
        sn = so[lo:hi][~np.isnan(so[lo:hi])]
        if len(k) >= 3:
            o = float(np.median(k))
        elif len(sn) >= 3:
            o = float(np.median(sn))
        else:
            o = 0.0
        out.append(b[i] + (o if abs(o) > 0.015 else 0.0))
    res = [round(float(out[0]), 4)]
    for t in out[1:]:            # siempre en orden y sin golpes pegados
        if t - res[-1] >= 0.5 * period:
            res.append(round(float(t), 4))
    return res


def downbeat_phase(hits: list[dict], beats_per_bar: int = 4) -> int:
    """En qué golpe cae el «1» del compás: el de más bombo (y menos caja, que suele ir en 2 y 4)."""
    if len(hits) < beats_per_bar * 2:
        return 0
    score = [0.0] * beats_per_bar
    for i, h in enumerate(hits):
        score[i % beats_per_bar] += h["kick"] - 0.5 * h["snare"]
    return int(np.argmax(score))


def sections(song: dict, beats_per_bar: int = 4) -> list[dict]:
    """[{a, b, kind, level}] por compases: kind = intro | build | drop | break | outro.
    level = energía del tramo respecto a lo más fuerte de la canción (0–1)."""
    beats = song["beats"]
    phase = song.get("downbeat_phase", 0)
    bars = beats[phase::beats_per_bar]
    if len(bars) < 3:
        return [{"a": 0.0, "b": song["duration"], "kind": "drop", "level": 1.0}]
    inten = np.asarray(song.get("intensity") or [0.0], np.float32)
    edges = list(bars) + [song["duration"]]
    lv = []
    for a, b in zip(edges, edges[1:]):
        seg = inten[int(a * 10):max(int(a * 10) + 1, int(b * 10))]
        lv.append(float(seg.mean()) if len(seg) else float(inten.mean()))
    lv = np.asarray(lv)
    hi, lo = float(np.percentile(lv, 90)), float(np.percentile(lv, 10))
    rel = np.clip((lv - lo) / max(hi - lo, 1e-6), 0, 1)
    # Etiquetas por compás y luego se juntan compases seguidos iguales
    tags = []
    for i, r in enumerate(rel):
        if r >= 0.72:
            tags.append("drop")
        elif r <= 0.35:
            tags.append("break")
        else:
            tags.append("mid")
    # «mid» que sube hacia un drop = subida; «mid» tras un drop = break suave
    for i, t in enumerate(tags):
        if t == "mid":
            nxt = next((tags[j] for j in range(i + 1, min(len(tags), i + 5)) if tags[j] != "mid"), None)
            rising = i + 1 < len(rel) and rel[min(len(rel) - 1, i + 1)] >= rel[i] - 0.02
            tags[i] = "build" if (nxt == "drop" or rising) else "break"
    tags = _smooth_tags(tags, rel)
    first_drop = next((i for i, t in enumerate(tags) if t == "drop"), None)
    for i in range(first_drop if first_drop is not None else 0):
        if tags[i] == "break":
            tags[i] = "intro"
    out: list[dict] = []
    if bars[0] > 0.3:
        out.append({"a": 0.0, "b": bars[0], "kind": "intro", "level": float(rel[0]) * 0.5})
    for i, t in enumerate(tags):
        a, b = edges[i], edges[i + 1]
        if out and out[-1]["kind"] == t:
            out[-1]["b"] = b
            out[-1]["level"] = max(out[-1]["level"], float(rel[i]))
        else:
            out.append({"a": a, "b": b, "kind": t, "level": float(rel[i])})
    if len(out) > 2 and out[-1]["kind"] in ("break", "build"):
        out[-1]["kind"] = "outro"
    return out


def _smooth_tags(tags: list[str], rel, min_bars: int = 4) -> list[str]:
    """Las partes de una canción duran frases (4 compases o más): un compás suelto más fuerte no es un drop, ni
    uno más flojo una pausa. Los tramos cortos se juntan con el vecino de energía más parecida (el más corto
    primero), así no hay «subida-drop-subida-drop» cada pocos segundos (= cortes que se aceleran de la nada)."""
    tags = list(tags)
    if len(tags) < min_bars * 2:
        return tags

    def runs():
        out, i = [], 0
        while i < len(tags):
            j = i
            while j < len(tags) and tags[j] == tags[i]:
                j += 1
            out.append([i, j, tags[i]])
            i = j
        return out
    for _ in range(len(tags)):
        rs = runs()
        short = [k for k, (a, b, _t) in enumerate(rs) if b - a < min_bars and len(rs) > 1]
        if not short:
            break
        k = min(short, key=lambda k: (rs[k][1] - rs[k][0], -float(np.mean(rel[rs[k][0]:rs[k][1]]))))
        a, b, _t = rs[k]
        lv = float(np.mean(rel[a:b]))
        cands = []
        for n in (k - 1, k + 1):
            if 0 <= n < len(rs):
                na, nb, nt = rs[n]
                cands.append((abs(float(np.mean(rel[na:nb])) - lv), nt))
        tags[a:b] = [min(cands)[1]] * (b - a)
    return tags


def stops(song: dict, min_len: float = 0.18, drop_db: float = 14.0) -> list[tuple[float, float]]:
    """Instantes en que la música se calla de golpe (antes de un drop, por ejemplo): [(inicio, duración)]."""
    inten = np.asarray(song.get("intensity") or [], np.float32)
    if len(inten) < 20:
        return []
    ref = np.convolve(inten, np.ones(20) / 20, mode="same")
    quiet = inten < ref - drop_db
    out, i = [], 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if (j - i) / 10 >= min_len and i > 10:
                out.append((round(i / 10, 2), round((j - i) / 10, 2)))
            i = j
        else:
            i += 1
    return out


def section_at(secs: list[dict], t: float) -> dict:
    for s in secs:
        if s["a"] - 1e-3 <= t < s["b"]:
            return s
    return secs[-1] if secs else {"kind": "drop", "level": 1.0, "a": 0.0, "b": 1e9}
