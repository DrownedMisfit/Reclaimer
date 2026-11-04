"""
👍 / 👎 de los EDITS: la IA aprende qué te funciona.

Cada edit tiene una «huella»: cuánto duran los planos en cada parte de la canción (intro, subida, drop, pausa,
final, en golpes) y con qué frecuencia usa cada efecto (destello, temblor, negativo, glitch, zoom de golpe, zoom
3D, velocity, cámara lenta, congelado) y las transiciones. La huella se saca de lo que HAY en la línea de tiempo,
así que si moviste o cambiaste cosas a mano, cuenta TU versión (y pesa más).

  · 👍 = acércate a esto · 👎 = aléjate de esto (comparado con lo normal de ese estilo)
  · 🎛 Mix de un trozo = «ahí no me convenció» (pesa poco)
learned(style) → {"len_mult": {parte: ×}, "fx_mult": {efecto: ×}, "n": cuántas notas}, que usa el motor.
Se guarda en datos/aprendizaje_edits.json (solo en tu PC).
"""
from __future__ import annotations

import json
import math
import os
import time

from ..core.paths import app_data_dir

KINDS = ("intro", "build", "drop", "break", "outro")
FX = ("flash", "shake", "invert", "glitch", "punch", "pulse", "velocity", "slowmo", "freeze", "trans")
FX_ES = {"flash": "destellos", "shake": "temblor", "invert": "negativo", "glitch": "glitch", "punch": "zoom de golpe",
         "pulse": "zoom 3D", "velocity": "velocity", "slowmo": "cámara lenta", "freeze": "congelados",
         "trans": "transiciones"}
KIND_ES = {"intro": "intro", "build": "subida", "drop": "drop", "break": "pausa", "outro": "final"}
MAX_ENTRIES = 400


def _path() -> str:
    return str(app_data_dir() / "aprendizaje_edits.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("entries", [])
            d.setdefault("base", {})
            return d
    except (OSError, ValueError):
        pass
    return {"entries": [], "base": {}}


def _save(d: dict):
    d["entries"] = d["entries"][-MAX_ENTRIES:]
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _path())


# ------------------------------------------------------------------ huella
def _kind_at(sections: list[dict], t: float) -> str:
    for s in sections or []:
        if s["a"] - 1e-3 <= t < s["b"]:
            return s["kind"]
    return sections[-1]["kind"] if sections else "drop"


def _zoom_shape(z: list) -> str:
    """'punch' (empieza cerca y se aleja), 'pulse' (se acerca y se aleja = zoom 3D) o ''."""
    vals = [float(v) for v in z]
    if len(vals) >= 3 and max(vals[1:-1]) > max(vals[0], vals[-1]) + 0.1:
        return "pulse"
    if len(vals) >= 2 and vals[0] >= 1.15 and vals[-1] < vals[0] - 0.1:
        return "punch"
    return ""


def shots_from_plan(plan: dict) -> list[dict]:
    """Los planos de un plan del motor: [{start, dur, pieces:[{speed, fx, zoom, trans}]}]."""
    out: dict[int, dict] = {}
    for c in plan.get("clips", []):
        sh = out.setdefault(c["shot"], {"start": c["start"], "dur": 0.0, "pieces": []})
        sh["dur"] += c["duration"]
        sh["pieces"].append({"speed": c.get("speed", 1.0), "fx": c.get("fx") or {},
                             "zoom": [z for _t, z, *_r in c.get("zoom") or []], "trans": c.get("trans")})
    return [out[k] for k in sorted(out)]


def shots_from_clips(clips: list, base: float) -> list[dict]:
    """Los planos que HAY en la línea de tiempo (Clip del modelo, ordenados): seguidos y del mismo material
    = el mismo plano (las partes de un velocity o un congelado)."""
    shots: list[dict] = []
    prev = None
    for c in sorted(clips, key=lambda c: c.start):
        cont = prev is not None and c.media_id == prev.media_id and abs(c.start - prev.end) < 0.02 and (
            c.speed == 0 or prev.speed == 0 or
            abs(prev.source_in + prev.duration * prev.speed - c.source_in) < 0.06)
        piece = {"speed": c.speed, "fx": c.fx or {}, "zoom": [k.get("z", 1.0) for k in (c.zoom_kf or [])],
                 "trans": (c.fx or {}).get("trans")}
        if cont:
            shots[-1]["dur"] += c.duration
            shots[-1]["pieces"].append(piece)
        else:
            shots.append({"start": c.start - base, "dur": c.duration, "pieces": [piece]})
        prev = c
    return shots


def fingerprint(shots: list[dict], sections: list[dict], period: float) -> dict:
    """{"len": {parte: golpes de media}, "rate": {efecto: fracción de planos}, "n": planos}"""
    period = max(0.05, float(period or 0.5))
    lens: dict[str, list[float]] = {}
    hits = {k: 0 for k in FX}
    for sh in shots:
        kind = _kind_at(sections, sh["start"] + 1e-3)
        lens.setdefault(kind, []).append(sh["dur"] / period)
        speeds = [p["speed"] for p in sh["pieces"]]
        fx = {}
        for p in sh["pieces"]:
            fx.update(p["fx"])
        shape = next((s for s in (_zoom_shape(p["zoom"]) for p in sh["pieces"]) if s), "")
        for key in ("flash", "shake", "invert", "glitch"):
            hits[key] += 1 if fx.get(key) else 0
        hits["punch"] += shape == "punch"
        hits["pulse"] += shape == "pulse"
        hits["velocity"] += any(s >= 2 for s in speeds)
        hits["slowmo"] += any(0 < s < 0.99 for s in speeds) and not any(s >= 2 for s in speeds)
        hits["freeze"] += any(s == 0 for s in speeds)
        hits["trans"] += bool(sh["pieces"][0].get("trans"))
    n = max(1, len(shots))
    return {"len": {k: round(sum(v) / len(v), 3) for k, v in lens.items()},
            "rate": {k: round(hits[k] / n, 3) for k in FX}, "n": len(shots)}


# ------------------------------------------------------------------ notas
def note_created(style: str, fp: dict):
    """Cada edit que hace la IA ajusta «lo normal» de ese estilo (media móvil)."""
    d = load()
    b = d["base"].get(style)
    if b is None:
        d["base"][style] = fp
    else:
        for part in ("len", "rate"):
            for k, v in fp[part].items():
                old = b[part].get(k, v)
                b[part][k] = round(0.8 * old + 0.2 * v, 4)
    _save(d)


def record(style: str, fp: dict, rating: int, ai_fp: dict | None = None, where: str = "edit") -> dict:
    """rating +1 (👍) o -1 (👎). Si tu versión difiere de la de la IA (la tocaste a mano), pesa más.
    where = "edit" (el edit entero) o "mix" (un trozo que pediste rehacer)."""
    d = load()
    manual = ai_fp is not None and changed(ai_fp, fp)
    w = (1.5 if manual else 1.0) * (0.5 if where == "mix" else 1.0)
    d["entries"].append({"style": style, "fp": fp, "ai": ai_fp, "rating": int(rating), "w": w, "where": where,
                         "manual": manual, "ts": int(time.time())})
    _save(d)
    return {"manual": manual, "n": sum(1 for e in d["entries"] if e["style"] == style)}


def changed(a: dict, b: dict) -> bool:
    """¿Tu versión es distinta de la de la IA? (planos o efectos que cambiaron de verdad)"""
    if abs(a.get("n", 0) - b.get("n", 0)) >= 2:
        return True
    for k in set(a.get("len", {})) | set(b.get("len", {})):
        x, y = a["len"].get(k), b["len"].get(k)
        if x is None or y is None or abs(math.log(max(x, 0.05) / max(y, 0.05))) > 0.15:
            return True
    return any(abs(a["rate"].get(k, 0) - b["rate"].get(k, 0)) > 0.08 for k in FX)


def learned(style: str) -> dict:
    """Lo aprendido para un estilo: planos más largos/cortos por parte y más/menos de cada efecto.
    👍 empuja hacia esa huella y 👎 en contra, respecto a lo normal del estilo (y, si lo tocaste a mano,
    respecto a lo que hizo la IA). Se queda entre ×0,5 y ×2."""
    d = load()
    ents = [e for e in d["entries"] if e.get("style") == style]
    if not ents:
        return {"len_mult": {}, "fx_mult": {}, "n": 0}
    base = d["base"].get(style) or {"len": {}, "rate": {}}
    len_acc: dict[str, list[tuple[float, float]]] = {}
    fx_acc: dict[str, list[tuple[float, float]]] = {}
    for e in ents:
        ref = e.get("ai") if e.get("manual") and e.get("ai") else base
        r, w = float(e["rating"]), float(e.get("w", 1.0))
        for k, v in e["fp"].get("len", {}).items():
            b0 = (ref.get("len") or {}).get(k) or (base.get("len") or {}).get(k)
            if b0:
                len_acc.setdefault(k, []).append((r * w * math.log(max(v, 0.05) / max(b0, 0.05)), w))
        for k in FX:
            v = e["fp"].get("rate", {}).get(k, 0.0)
            b0 = (ref.get("rate") or {}).get(k, (base.get("rate") or {}).get(k, 0.0))
            fx_acc.setdefault(k, []).append((r * w * (v - b0), w))
    len_mult = {}
    for k, xs in len_acc.items():
        tot = sum(w for _x, w in xs)
        m = math.exp(sum(x for x, _w in xs) / max(tot, 1e-6))
        len_mult[k] = round(min(2.0, max(0.5, m)), 3)
    fx_mult = {}
    for k, xs in fx_acc.items():
        tot = sum(w for _x, w in xs)
        delta = sum(x for x, _w in xs) / max(tot, 1e-6)          # cambio de frecuencia deseado (−1 … 1)
        b0 = max(0.08, (base.get("rate") or {}).get(k, 0.0))
        fx_mult[k] = round(min(2.0, max(0.0, 1.0 + delta / b0)), 3)
    return {"len_mult": len_mult, "fx_mult": fx_mult, "n": len(ents)}


def describe(lr: dict) -> str:
    """Lo aprendido, en palabras («planos más largos en el drop, más zoom 3D, menos glitch»)."""
    bits = []
    for k, m in sorted(lr.get("len_mult", {}).items(), key=lambda kv: -abs(math.log(kv[1]))):
        if abs(math.log(m)) > 0.15:
            bits.append(f"planos más {'largos' if m > 1 else 'cortos'} en {KIND_ES.get(k, k)}")
    for k, m in sorted(lr.get("fx_mult", {}).items(), key=lambda kv: -abs(kv[1] - 1)):
        if abs(m - 1) > 0.2:
            bits.append(f"{'más' if m > 1 else 'menos'} {FX_ES.get(k, k)}")
    return ", ".join(bits[:5])
