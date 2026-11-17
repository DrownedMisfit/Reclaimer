"""
🎯 SEGUIMIENTO: los recorridos guardados en el clip (la parte sin interfaz, se puede probar sola).

Un recorrido es por dónde va un objeto DENTRO del video, fotograma a fotograma. Se guarda en el clip
(Clip.motion_tracks, en el .eia y en Ctrl+Z) para usarlo todas las veces que quieras:

    {"id": "…", "name": "Objeto 1", "fps": 15.0,
     "auto":   [[t, cx, cy, w, h, confianza], …]   lo que encontró el seguidor automático
     "manual": [[t, cx, cy, w, h], …]               claves que pusiste tú (MANDAN sobre lo automático)
     "lost":   [[a, b], …]                          tramos dudosos (el seguidor no estaba seguro): no se usan
     "smooth": 0.3}                                 suavizado 0–1 (solo a lo automático)

t = segundo del ARCHIVO (como las claves de zoom: sigue pegado al contenido aunque recortes o muevas el clip);
cx, cy = centro y w, h = tamaño, en fracciones 0–1 del fotograma.

Cómo se calcula el recorrido final (points):
  · lo automático dudoso no cuenta; lo automático pegado a una clave manual tampoco (manda la clave);
  · lo automático se suaviza por tramos (sin pasar por encima de las claves manuales);
  · una corrección a mano arrastra lo automático de alrededor (si corriges un fotograma, los de al lado se
    corrigen también, cada vez menos, hasta la clave siguiente o durante 1 s);
  · entre claves manuales sin nada automático: línea recta (todo a mano también vale).

Usos (los hace el controlador con esto): zoom o encuadre vertical que sigue, 📌 pegar otro clip (texto, imagen,
emoji…) al objeto (pin_plan) y 🙈 desenfocar/pixelar con un recuadro que lo acompaña (blur_plan; se guarda en
fx["tracked_blur"] y se ve igual en el visor y al exportar: regions_at / ffmpeg_graph).
"""
from __future__ import annotations

import uuid

import numpy as np

from . import transform

DECAY = 1.0            # segundos que «arrastra» una corrección a mano si no hay otra clave al otro lado
MAX_KEYS = 160         # claves como mucho al convertir (las expresiones de FFmpeg no deben ser enormes)
SHAPES = {"rect": "▭ Recuadro", "ellipse": "◯ Círculo"}
MODES = {"blur": "Desenfocar", "pixel": "Pixelar"}


# ------------------------------------------------------------------ datos
def new_track(name: str = "Objeto 1", fps: float = 15.0) -> dict:
    return {"id": uuid.uuid4().hex[:10], "name": name, "fps": float(fps), "auto": [], "manual": [], "lost": [],
            "smooth": 0.3}


def tracks_of(c) -> list[dict]:
    return list(getattr(c, "motion_tracks", None) or [])


def find(c, track_id: str | None) -> dict | None:
    for t in tracks_of(c):
        if t.get("id") == track_id:
            return t
    return None


def unique_name(c) -> str:
    names = {t.get("name") for t in tracks_of(c)}
    n = 1
    while f"Objeto {n}" in names:
        n += 1
    return f"Objeto {n}"


def fps_of(trk: dict) -> float:
    try:
        return min(60.0, max(2.0, float(trk.get("fps") or 15.0)))
    except (TypeError, ValueError):
        return 15.0


def tol_of(trk: dict) -> float:
    """Dos momentos más cerca que esto son el mismo fotograma del recorrido."""
    return max(0.02, 0.45 / fps_of(trk))


def _clamp_box(cx, cy, w, h) -> list[float]:
    w, h = min(1.0, max(0.004, float(w))), min(1.0, max(0.004, float(h)))
    return [round(min(1.0, max(0.0, float(cx))), 5), round(min(1.0, max(0.0, float(cy))), 5), round(w, 5),
            round(h, 5)]


def clean(trk: dict) -> dict:
    """Copia ordenada y redondeada (lo que se guarda en el clip)."""
    out = {k: v for k, v in trk.items() if k not in ("auto", "manual", "lost")}
    out["fps"] = fps_of(trk)
    try:
        out["smooth"] = round(min(1.0, max(0.0, float(trk.get("smooth", 0.3)))), 3)
    except (TypeError, ValueError):
        out["smooth"] = 0.3
    auto = []
    for r in trk.get("auto") or []:
        try:
            auto.append([round(float(r[0]), 4)] + _clamp_box(*r[1:5]) + [round(float(r[5]) if len(r) > 5 else 1.0, 3)])
        except (TypeError, ValueError, IndexError):
            continue
    man = []
    for r in trk.get("manual") or []:
        try:
            man.append([round(float(r[0]), 4)] + _clamp_box(*r[1:5]))
        except (TypeError, ValueError, IndexError):
            continue
    lost = []
    for r in trk.get("lost") or []:
        try:
            a, b = sorted((float(r[0]), float(r[1])))
            lost.append([round(a, 4), round(b, 4)])
        except (TypeError, ValueError, IndexError):
            continue
    out["auto"] = sorted(auto, key=lambda r: r[0])
    out["manual"] = sorted(man, key=lambda r: r[0])
    out["lost"] = _merge_ranges(lost)
    return out


def _merge_ranges(rs: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def set_manual(trk: dict, t: float, box) -> dict:
    """Clave manual (cx, cy, w, h) en el segundo t: sustituye a la que hubiera en ese fotograma."""
    tol = tol_of(trk)
    out = dict(trk)
    out["manual"] = [list(r) for r in trk.get("manual") or [] if abs(r[0] - t) > tol] + \
        [[round(float(t), 4)] + _clamp_box(*box)]
    out["manual"].sort(key=lambda r: r[0])
    return out


def manual_at(trk: dict, t: float) -> list | None:
    tol = tol_of(trk)
    best = None
    for r in trk.get("manual") or []:
        if abs(r[0] - t) <= tol and (best is None or abs(r[0] - t) < abs(best[0] - t)):
            best = r
    return best


def remove_manual(trk: dict, t: float) -> tuple[dict, bool]:
    k = manual_at(trk, t)
    if k is None:
        return trk, False
    out = dict(trk)
    out["manual"] = [list(r) for r in trk.get("manual") or [] if r is not k]
    return out, True


def neighbors(trk: dict, t: float) -> tuple[float | None, float | None]:
    """La clave manual anterior y la siguiente a t (sin contar la que esté justo en t)."""
    tol = tol_of(trk)
    prev = [r[0] for r in trk.get("manual") or [] if r[0] < t - tol]
    nxt = [r[0] for r in trk.get("manual") or [] if r[0] > t + tol]
    return (max(prev) if prev else None), (min(nxt) if nxt else None)


def replace_auto(trk: dict, a: float, b: float, samples: list, lost: list | None = None) -> dict:
    """Lo automático entre a y b pasa a ser «samples» (y sus tramos dudosos, «lost»)."""
    a, b = min(a, b), max(a, b)
    eps = 1e-4
    out = dict(trk)
    out["auto"] = sorted([list(r) for r in trk.get("auto") or [] if not (a - eps <= r[0] <= b + eps)] +
                         [list(r) for r in samples], key=lambda r: r[0])
    old = []
    for la, lb in trk.get("lost") or []:      # los tramos dudosos viejos fuera de [a, b] se quedan (recortados)
        if lb < a - eps or la > b + eps:
            old.append([la, lb])
        else:
            if la < a - eps:
                old.append([la, a])
            if lb > b + eps:
                old.append([b, lb])
    out["lost"] = _merge_ranges(old + [sorted((float(x), float(y))) for x, y in (lost or [])])
    return out


def clear_auto(trk: dict) -> dict:
    out = dict(trk)
    out["auto"], out["lost"] = [], []
    return out


def is_lost(trk: dict, t: float) -> bool:
    return any(a - 1e-4 <= t <= b + 1e-4 for a, b in trk.get("lost") or [])


def span(trk: dict) -> tuple[float, float] | None:
    ts = [r[0] for r in trk.get("auto") or []] + [r[0] for r in trk.get("manual") or []]
    return (min(ts), max(ts)) if ts else None


def is_empty(trk: dict | None) -> bool:
    return not trk or (not trk.get("auto") and not trk.get("manual"))


# ------------------------------------------------------------------ el recorrido final
def _smooth_run(v: np.ndarray, half: int) -> np.ndarray:
    if half < 1 or len(v) < 3:
        return v
    half = min(half, (len(v) - 1) // 2)
    if half < 1:
        return v
    k = np.ones(2 * half + 1) / (2 * half + 1)
    pad = np.pad(v, ((half, half), (0, 0)), mode="edge")
    return np.stack([np.convolve(pad[:, j], k, mode="valid") for j in range(v.shape[1])], axis=1)


def points(trk: dict) -> np.ndarray:
    """Puntos del recorrido final: array (N, 6) = [t, cx, cy, w, h, manual 0/1], ordenado por t."""
    fps = fps_of(trk)
    tol = tol_of(trk)
    man = np.array([r[:5] for r in trk.get("manual") or []], dtype=np.float64).reshape(-1, 5)
    man = man[np.argsort(man[:, 0])] if len(man) else man
    lost = trk.get("lost") or []
    auto = [r[:5] for r in trk.get("auto") or []
            if not any(a - 1e-4 <= r[0] <= b + 1e-4 for a, b in lost)]
    au = np.array(auto, dtype=np.float64).reshape(-1, 5)
    if len(au):
        au = au[np.argsort(au[:, 0])]
        if len(man):          # (manda la clave manual: fuera lo automático de ese fotograma)
            near = np.min(np.abs(au[:, 0][:, None] - man[:, 0][None, :]), axis=1) <= tol
            au = au[~near]
    if len(au):
        # Suavizado por tramos (un tramo se corta en un hueco o en una clave manual)
        half = int(round(float(trk.get("smooth", 0.3) or 0) * fps * 0.5))
        if half >= 1 and len(au) >= 3:
            gap = np.diff(au[:, 0]) > 2.5 / fps
            if len(man):
                k_idx = np.searchsorted(man[:, 0], au[:, 0])
                gap |= np.diff(k_idx) != 0
            starts = [0] + list(np.nonzero(gap)[0] + 1) + [len(au)]
            for s0, s1 in zip(starts, starts[1:]):
                au[s0:s1, 1:] = _smooth_run(au[s0:s1, 1:], half)
        # Una corrección a mano arrastra lo automático de alrededor
        if len(man):
            near_w = 2.0 / fps
            off_r: list = []      # desfase de cada clave con lo automático que viene DESPUÉS
            off_l: list = []      # … y con lo de ANTES
            for r in man:
                i = int(np.searchsorted(au[:, 0], r[0]))
                off_r.append(r[1:] - au[i, 1:] if i < len(au) and au[i, 0] - r[0] <= near_w else None)
                off_l.append(r[1:] - au[i - 1, 1:] if i > 0 and r[0] - au[i - 1, 0] <= near_w else None)
            k_idx = np.searchsorted(man[:, 0], au[:, 0])     # clave siguiente de cada muestra
            for j in range(len(au)):
                t = au[j, 0]
                ki = int(k_idx[j])
                lft = ki - 1 if ki - 1 >= 0 else None
                rgt = ki if ki < len(man) else None
                oa = off_r[lft] if lft is not None else None
                ob = off_l[rgt] if rgt is not None else None
                if oa is not None and ob is not None:
                    u = (t - man[lft, 0]) / max(1e-6, man[rgt, 0] - man[lft, 0])
                    au[j, 1:] += oa * (1 - u) + ob * u
                elif oa is not None:
                    au[j, 1:] += oa * max(0.0, 1 - (t - man[lft, 0]) / DECAY)
                elif ob is not None:
                    au[j, 1:] += ob * max(0.0, 1 - (man[rgt, 0] - t) / DECAY)
    rows = [np.append(r, 0.0) for r in au] + [np.append(r, 1.0) for r in man]
    if not rows:
        return np.zeros((0, 6))
    out = np.array(rows, dtype=np.float64)
    out = out[np.argsort(out[:, 0], kind="stable")]
    out[:, 1:3] = np.clip(out[:, 1:3], 0.0, 1.0)
    out[:, 3:5] = np.clip(out[:, 3:5], 0.004, 1.0)
    return out


def box_at(trk: dict, t: float, pts: np.ndarray | None = None) -> tuple[float, float, float, float] | None:
    """(cx, cy, w, h) del objeto en el segundo t (fuera del recorrido: el primero / el último)."""
    pts = points(trk) if pts is None else pts
    if not len(pts):
        return None
    ts = pts[:, 0]
    if t <= ts[0]:
        return tuple(float(v) for v in pts[0, 1:5])
    if t >= ts[-1]:
        return tuple(float(v) for v in pts[-1, 1:5])
    i = int(np.searchsorted(ts, t))
    a, b = pts[i - 1], pts[i]
    u = (t - a[0]) / max(1e-9, b[0] - a[0])
    return tuple(float(a[k] + (b[k] - a[k]) * u) for k in range(1, 5))


def sample(trk: dict, a: float, b: float, fps: float | None = None,
           pts: np.ndarray | None = None) -> list[tuple[float, float, float, float, float]]:
    """El recorrido cada 1/fps entre a y b (solo dentro de lo que tiene recorrido): [(t, cx, cy, w, h)]."""
    pts = points(trk) if pts is None else pts
    if not len(pts):
        return []
    fps = fps or fps_of(trk)
    lo, hi = max(min(a, b), pts[0, 0]), min(max(a, b), pts[-1, 0])
    if hi < lo:
        return []
    n = max(1, int(np.floor((hi - lo) * fps + 1e-6)))
    ts = [lo + i / fps for i in range(n + 1) if lo + i / fps <= hi + 1e-6]
    if hi - ts[-1] > 1e-3:
        ts.append(hi)
    return [(round(t, 4),) + box_at(trk, t, pts) for t in ts]


# ------------------------------------------------------------------ claves con pocas muestras
def simplify_lin(kf: list[dict], keys: tuple, tol: float = 0.002, max_keys: int = MAX_KEYS) -> list[dict]:
    """Quita claves que una línea recta entre sus vecinas ya explica (Douglas-Peucker en el tiempo)."""
    kf = sorted(kf, key=lambda k: k["t"])
    if len(kf) <= 2:
        return kf
    t = np.array([k["t"] for k in kf])
    v = np.array([[k[x] for x in keys] for k in kf], dtype=np.float64)
    while True:
        keep = np.zeros(len(kf), bool)
        keep[0] = keep[-1] = True
        stack = [(0, len(kf) - 1)]
        while stack:
            i, j = stack.pop()
            if j - i < 2:
                continue
            u = (t[i + 1:j] - t[i]) / max(1e-9, t[j] - t[i])
            pred = v[i] + (v[j] - v[i]) * u[:, None]
            err = np.max(np.abs(pred - v[i + 1:j]), axis=1)
            m = int(np.argmax(err))
            if err[m] > tol:
                keep[i + 1 + m] = True
                stack += [(i, i + 1 + m), (i + 1 + m, j)]
        if keep.sum() <= max_keys:
            return [kf[i] for i in range(len(kf)) if keep[i]]
        tol *= 1.6


# ------------------------------------------------------------------ del fotograma a la pantalla
def _src_to_box(c, m, s: float, local: float, fx: float, fy: float, W: int, H: int, is_image: bool = False,
                flip: bool = True):
    """Un punto del fotograma (0–1) → su sitio en la caja del clip (0–1 de la caja), con el zoom, el encaje
    (contain / cover / deformado, con 🎯 «sigue la acción»), las ▭ barras quitadas y el volteo."""
    from . import black_bars as BB
    sw, sh = float(m.width or 16), float(m.height or 9)
    lay = c.layout or transform.FULL
    bars = BB.of(lay) if not is_image and m.width and m.height else None
    if bars:
        fx, fy = (fx - bars[0]) / max(1e-6, bars[2]), (fy - bars[1]) / max(1e-6, bars[3])
        sw, sh = sw * bars[2], sh * bars[3]
    u, v = fx, fy
    if transform.is_zoomed(c.zoom_kf):
        z, zx, zy = transform.value_at(c.zoom_kf, local if is_image else s)
        left, top, size = transform.window(z, zx, zy)
        u, v = (fx - left) / size, (fy - top) / size
    box = transform.layout_at(c, local, is_image) or transform.FULL
    bw, bh = max(1.0, float(box["w"]) * W), max(1.0, float(box["h"]) * H)
    fit = box.get("fit", "contain")
    if fit == "stretch":
        bx, by = u, v
    elif fit == "cover":
        k = max(bw / sw, bh / sh)
        cw, ch = sw * k, sh * k
        fol = transform.follow_at(box, local if is_image else s)
        left_px = (cw - bw) / 2 if fol is None else min(max(fol * cw - bw / 2, 0.0), cw - bw)
        bx, by = (u * cw - left_px) / bw, (v * ch - (ch - bh) / 2) / bh
    else:
        k = min(bw / sw, bh / sh)
        cw, ch = sw * k, sh * k
        bx, by = ((bw - cw) / 2 + u * cw) / bw, ((bh - ch) / 2 + v * ch) / bh
    if flip and box.get("flip_h"):
        bx = 1 - bx
    if flip and box.get("flip_v"):
        by = 1 - by
    return bx, by, box


def obj_in_box(c, m, s: float, local: float, b: tuple, W: int, H: int, flip: bool = True):
    """El objeto (cx, cy, w, h del fotograma) en fracciones de la caja del clip: (cx, cy, w, h, caja).
    flip=False: sin el ↔ ↕ volteo de la capa (el 🙈 tapado va ANTES de voltear, en el visor y al exportar)."""
    cx, cy, w, h = b
    x0, y0, box = _src_to_box(c, m, s, local, cx - w / 2, cy - h / 2, W, H, flip=flip)
    x1, y1, _b = _src_to_box(c, m, s, local, cx + w / 2, cy + h / 2, W, H, flip=flip)
    return (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0), abs(y1 - y0), box


def obj_on_screen(c, m, s: float, local: float, b: tuple, W: int, H: int):
    """El objeto en fracciones de la PANTALLA: (cx, cy, w, h)."""
    bx, by, bw, bh, box = obj_in_box(c, m, s, local, b, W, H)
    return (float(box["x"]) + bx * float(box["w"]), float(box["y"]) + by * float(box["h"]),
            bw * float(box["w"]), bh * float(box["h"]))


def _grid(a: float, b: float, fps: float) -> list[float]:
    if b <= a:
        return [a]
    n = int(np.floor((b - a) * fps + 1e-6))
    ts = [a + i / fps for i in range(n + 1)]
    if b - ts[-1] > 1e-3:
        ts.append(b)
    return ts


def timeline_points(p, vc, trk: dict, a: float, b: float, fps: float | None = None):
    """[(T de la timeline, s del archivo, objeto en pantalla (cx, cy, w, h))] entre a y b, solo donde el clip de
    video se ve Y el recorrido tiene datos."""
    m = p.media_of(vc)
    if m is None:
        return []
    pts = points(trk)
    if not len(pts):
        return []
    fps = fps or fps_of(trk)
    lo, hi = max(a, vc.start), min(b, vc.end)
    tol = tol_of(trk)
    out = []
    for T in _grid(lo, hi, fps):
        local = T - vc.start
        s = vc.src_at(local)
        if s < pts[0, 0] - tol or s > pts[-1, 0] + tol:
            continue
        out.append((T, s, obj_on_screen(vc, m, s, local, box_at(trk, s, pts), p.width, p.height)))
    return out


# ------------------------------------------------------------------ 📌 pegar otro clip al objeto
def pieces_points(p, pieces, a: float, b: float):
    """timeline_points de varios trozos de un mismo video con el mismo recorrido (tras dividirlo): [(T, s, objeto)]."""
    out = []
    for vc, trk in pieces:
        out += timeline_points(p, vc, trk, a, b)
    out.sort(key=lambda x: x[0])
    clean_ = []
    for x in out:
        if clean_ and x[0] - clean_[-1][0] < 1e-3:
            continue
        clean_.append(x)
    return clean_


def pin_anchor(p, pieces, oc, ref_T: float | None = None, scale: bool = False) -> dict | None:
    """📌 El desfase con el que colocaste el clip respecto al objeto en el momento ref_T (de la timeline): se guarda en
    el clip pegado (text["pegado"] / layout["pegado"]) para volver a calcular sus claves si algo se mueve."""
    pts = pieces_points(p, pieces, oc.start, oc.end)
    if len(pts) < 2:
        return None
    vc, trk = pieces[0]
    if ref_T is None or not (pts[0][0] - 1e-6 <= ref_T <= pts[-1][0] + 1e-6):
        ref_T = min(max(ref_T if ref_T is not None else oc.start, pts[0][0]), pts[-1][0])
    i = int(np.argmin([abs(T - ref_T) for T, _s, _o in pts]))
    ref = pts[i][2]
    loc_ref = min(max(pts[i][0] - oc.start, 0.0), oc.duration)
    info = {"clip": vc.id, "track": trk.get("id", ""), "name": trk.get("name", ""), "scale": bool(scale)}
    if oc.text is not None:
        bx, by = float(oc.text.get("x", 0.5)), float(oc.text.get("y", 0.5))
        ox, oy = text_offset_at(oc.text, loc_ref)            # (si ya estaba pegado: donde se ve ahora)
        info.update(dx=round(bx + ox - ref[0], 5), dy=round(by + oy - ref[1], 5), bx=bx, by=by, scale=False)
        return info
    mo = p.media_of(oc)
    b0 = transform.layout_at(oc, loc_ref, bool(mo and mo.kind == "image")) or transform.FULL
    info.update(dx=round(float(b0["x"]) + float(b0["w"]) / 2 - ref[0], 5),
                dy=round(float(b0["y"]) + float(b0["h"]) / 2 - ref[1], 5),
                w0=round(float(b0["w"]), 5), h0=round(float(b0["h"]), 5), oh0=round(max(1e-4, ref[3]), 5))
    return info


def pin_apply(p, pieces, oc, info: dict) -> dict | None:
    """Las claves del clip pegado con ese desfase. Texto → {"pos_kf"}; imagen/video → {"layout_kf", "layout"}.
    Los tiempos se traducen por la timeline: da igual que el de encima empiece antes o después que el video."""
    pts = pieces_points(p, pieces, oc.start, oc.end)
    if len(pts) < 2:
        return None
    dx, dy = float(info.get("dx", 0)), float(info.get("dy", 0))
    if oc.text is not None:
        bx, by = float(info.get("bx", oc.text.get("x", 0.5))), float(info.get("by", oc.text.get("y", 0.5)))
        kf = [{"t": round(T - oc.start, 4), "x": round(o[0] + dx - bx, 5), "y": round(o[1] + dy - by, 5),
               "i": "linear"} for T, _s, o in pts]
        return {"pos_kf": simplify_lin(kf, ("x", "y"), 0.0015)}
    mo = p.media_of(oc)
    img = bool(mo and mo.kind == "image")
    kf = []
    for T, _s, o in pts:
        local = min(max(T - oc.start, 0.0), oc.duration)
        k = 1.0
        if info.get("scale"):
            k = min(4.0, max(0.25, o[3] / max(1e-4, float(info.get("oh0", o[3])))))
            w, h = float(info.get("w0", 0.2)) * k, float(info.get("h0", 0.2)) * k
        else:
            bx = transform.layout_at(oc, local, img) or transform.FULL
            w, h = float(bx["w"]), float(bx["h"])
        cx, cy = o[0] + dx * k, o[1] + dy * k
        t = local if img else oc.src_at(local)
        kf.append({"t": round(t, 4), "x": round(cx - w / 2, 5), "y": round(cy - h / 2, 5), "w": round(w, 5),
                   "h": round(h, 5), "i": "linear"})
    lay = dict(oc.layout or dict(transform.FULL, bg="none"))
    return {"layout_kf": simplify_lin(kf, transform.LAYOUT_KEYS, 0.0015), "layout": lay}


def pin_plan(p, pieces, oc, ref_T: float | None = None, scale: bool = False) -> dict | None:
    """Desfase + claves de una vez: {"info", "pos_kf" | "layout_kf"/"layout"}. pieces = [(clip de video, recorrido)]
    (varios si el video se dividió: el recorrido sigue por todos sus trozos)."""
    info = pin_anchor(p, pieces, oc, ref_T, scale)
    plan = pin_apply(p, pieces, oc, info) if info else None
    if plan is None:
        return None
    info["sig"] = pin_sig(p, pieces, oc)
    plan["info"] = info
    return plan


# ------------------------------------------------------------------ firmas: ¿hay que volver a calcular?
def _hash(x) -> str:
    import hashlib
    return hashlib.md5(repr(x).encode("utf-8")).hexdigest()[:12]


def sig_of(p, vc, trk: dict) -> str:
    """Lo que decide dónde cae el objeto DENTRO de la caja del clip (zoom, encuadre, formato, recorrido)."""
    m = p.media_of(vc)
    return _hash((p.width, p.height, m.width if m else 0, m.height if m else 0, vc.source_in, vc.duration, vc.speed,
                  vc.reverse, vc.zoom_kf, vc.layout, vc.layout_kf, trk.get("v"), trk.get("id")))


def pin_sig(p, pieces, oc) -> str:
    """Además, dónde están los clips en la timeline (si uno se mueve, el pegado se recalcula)."""
    return _hash((tuple((sig_of(p, vc, trk), vc.start, vc.id) for vc, trk in pieces), oc.start, oc.duration,
                  oc.speed, oc.reverse, oc.source_in))


def trim_track(trk: dict, a: float, b: float) -> dict:
    """Solo las muestras entre a y b (al dividir o recortar el clip, cada trozo se queda con lo suyo)."""
    auto = [r for r in trk.get("auto") or [] if a <= r[0] <= b]
    man = [r for r in trk.get("manual") or [] if a <= r[0] <= b]
    lost = [[max(x, a), min(y, b)] for x, y in trk.get("lost") or [] if y >= a and x <= b]
    if len(auto) == len(trk.get("auto") or []) and len(man) == len(trk.get("manual") or []) and             lost == list(trk.get("lost") or []):
        return trk
    return dict(trk, auto=auto, manual=man, lost=lost)


def text_offset_at(text: dict | None, local: float) -> tuple[float, float]:
    """📌 Desplazamiento (dx, dy) de un texto pegado a un objeto, en el instante local (desde que empieza)."""
    kf = (text or {}).get("pos_kf") or []
    if not kf:
        return 0.0, 0.0
    try:
        v = transform.layout_value_at([dict(k, w=1.0, h=1.0) for k in kf], local)
        return float(v["x"]), float(v["y"])
    except (KeyError, TypeError, ValueError):
        return 0.0, 0.0


def text_offset_expr(text: dict, t_expr: str) -> tuple[str, str] | None:
    """Los mismos desplazamientos como expresiones de FFmpeg (t_expr = segundos desde que empieza el texto)."""
    kf = (text or {}).get("pos_kf") or []
    if not kf:
        return None
    return transform.layout_expr(kf, "x", t_expr), transform.layout_expr(kf, "y", t_expr)


# ------------------------------------------------------------------ 🙈 desenfocar / pixelar lo seguido
def blur_plan(p, vc, trk: dict, shape: str = "rect", mode: str = "blur", amount: float = 0.7,
              pad: float = 1.25) -> dict | None:
    """Una zona que acompaña al objeto: {"shape", "mode", "amount", "w", "h", "x", "y", "kf": [{t (archivo), x, y}],
    "track"}; posiciones en fracciones de la CAJA del clip (como el ◌ desenfoque por zonas). Tamaño fijo: el más
    grande que llega a tener el objeto (con margen), así nunca se ve un trozo sin tapar."""
    m = p.media_of(vc)
    pts = points(trk)
    if m is None or not len(pts):
        return None
    fps = fps_of(trk)
    tol = tol_of(trk)
    kf, ws, hs = [], [], []
    for local in _grid(0.0, vc.duration, fps):
        s = vc.src_at(local)
        if s < pts[0, 0] - tol or s > pts[-1, 0] + tol:
            continue
        bx, by, bw, bh, _box = obj_in_box(vc, m, s, local, box_at(trk, s, pts), p.width, p.height, flip=False)
        kf.append({"t": round(s, 4), "x": round(bx, 5), "y": round(by, 5), "i": "linear"})
        ws.append(bw)
        hs.append(bh)
    if not kf:
        return None
    kf = sorted(kf, key=lambda k: k["t"])
    w = min(1.0, max(0.02, max(ws) * pad))
    h = min(1.0, max(0.02, max(hs) * pad))
    kf = simplify_lin(kf, ("x", "y"), 0.0015)
    return {"shape": "ellipse" if shape == "ellipse" else "rect", "mode": "pixel" if mode == "pixel" else "blur",
            "amount": round(min(1.0, max(0.05, float(amount))), 3), "w": round(w, 5), "h": round(h, 5),
            "x": kf[0]["x"], "y": kf[0]["y"], "kf": kf, "track": trk.get("id", ""), "name": trk.get("name", ""),
            "pad": round(float(pad), 3), "sig": sig_of(p, vc, trk)}


def tracked_blurs(fx: dict | None) -> list[dict]:
    out = []
    for r in (fx or {}).get("tracked_blur") or []:
        try:
            if r.get("kf") and float(r["w"]) > 0 and float(r["h"]) > 0:
                out.append(r)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def regions_at(fx: dict | None, s: float | None) -> list[dict]:
    """Las zonas que acompañan a un objeto, colocadas en el segundo s del archivo (formato del ◌ desenfoque por
    zonas + "mode")."""
    out = []
    for r in tracked_blurs(fx):
        w, h = min(1.0, max(0.02, float(r["w"]))), min(1.0, max(0.02, float(r["h"])))
        if s is None:
            x, y = float(r.get("x", 0.5)), float(r.get("y", 0.5))
        else:
            v = transform.layout_value_at([dict(k, w=1.0, h=1.0) for k in r["kf"]], s)
            x, y = v["x"], v["y"]
        out.append({"shape": "ellipse" if r.get("shape") == "ellipse" else "rect", "x": min(1 - w / 2, max(w / 2, x)),
                    "y": min(1 - h / 2, max(h / 2, y)), "w": w, "h": h,
                    "amount": min(1.0, max(0.05, float(r.get("amount", 0.7)))),
                    "mode": "pixel" if r.get("mode") == "pixel" else "blur", "track": r.get("track", "")})
    return out


def block_px(w: float, h: float, amount: float, mode: str) -> int:
    """Tamaño del desenfoque / del píxel (en píxeles) para una zona de w×h píxeles: igual en visor y exportación."""
    k = 0.04 + 0.16 * amount if mode != "pixel" else 0.06 + 0.18 * amount
    return max(2, int(round(min(w, h) * k)))


def ffmpeg_graph(regions: list[dict], k: int, s_expr: str, bw: int, bh: int) -> str:
    """Trozo de filtergraph: [tz{k}] → zonas que se mueven con el objeto → [to{k}]. Tamaño fijo, posición con la
    misma recta entre claves que el visor (eval=frame)."""
    parts = []
    n = len(regions)
    for i, r in enumerate(regions):
        src = f"[tz{k}]" if i == 0 else f"[tq{k}_{i}]"
        dst = f"[to{k}]" if i == n - 1 else f"[tq{k}_{i + 1}]"
        w, h = min(1.0, max(0.02, float(r["w"]))), min(1.0, max(0.02, float(r["h"])))
        cw, ch = max(4, int(w * bw) // 2 * 2), max(4, int(h * bh) // 2 * 2)
        kf = [dict(q, w=1.0, h=1.0) for q in r["kf"]]
        xe = transform.layout_expr(kf, "x", s_expr)
        ye = transform.layout_expr(kf, "y", s_expr)
        cx = f"trunc(max(0,min(iw-{cw},iw*({xe})-{cw}/2))/2)*2"
        cy = f"trunc(max(0,min(ih-{ch},ih*({ye})-{ch}/2))/2)*2"
        ox = f"trunc(max(0,min(main_w-{cw},main_w*({xe})-{cw}/2))/2)*2"
        oy = f"trunc(max(0,min(main_h-{ch},main_h*({ye})-{ch}/2))/2)*2"
        amount = min(1.0, max(0.05, float(r.get("amount", 0.7))))
        if r.get("mode") == "pixel":
            px = block_px(cw, ch, amount, "pixel")
            eff = f"pixelize=width={px}:height={px}"
        else:
            kr = 0.04 + 0.16 * amount
            eff = (f"boxblur=lr='max(1,min(w,h)*{kr:.3f})':lp=3"
                   f":cr='max(1,min(cw,ch)*{kr:.3f})':cp=3")
        mask = ""
        if r.get("shape") == "ellipse":
            mask = (",format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)'"
                    ":a='255*clip((1-sqrt(pow((X-W/2)/(W/2),2)+pow((Y-H/2)/(H/2),2)))/0.12,0,1)'")
        parts.append(f"{src}split[ta{k}_{i}][tc{k}_{i}];[tc{k}_{i}]crop=w={cw}:h={ch}:x='{cx}':y='{cy}',{eff}{mask}"
                     f"[td{k}_{i}];[ta{k}_{i}][td{k}_{i}]overlay=x='{ox}':y='{oy}':eval=frame:format=auto{dst}")
    return ";".join(parts)
