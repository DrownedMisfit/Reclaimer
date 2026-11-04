"""
▦ RELLENO (como el «Relleno» de los efectos de Resolve): lo que queda vacío alrededor del clip (al aplastarlo, al
hacerlo más pequeño o con otra forma que la pantalla) se llena con la PROPIA imagen ampliada y desenfocada.
No es automático: lo pones tú (Efectos → Imagen → ▦ Relleno, o el Inspector) y lo ajustas.

  fx["relleno"] = {"desenfoque": 0–1, "oscurecer": 0–1, "zoom": 1–3}
El fondo ocupa TODA la pantalla detrás del clip (tapa lo de las pistas de debajo, como en Resolve).
"""
from __future__ import annotations

DEFAULT = {"desenfoque": 0.5, "oscurecer": 0.15, "zoom": 1.0}


def of(fx) -> dict | None:
    r = (fx or {}).get("relleno")
    if not isinstance(r, dict):
        return None
    out = dict(DEFAULT)
    for k in DEFAULT:
        try:
            out[k] = float(r.get(k, DEFAULT[k]))
        except (TypeError, ValueError):
            pass
    out["desenfoque"] = min(1.0, max(0.0, out["desenfoque"]))
    out["oscurecer"] = min(0.9, max(0.0, out["oscurecer"]))
    out["zoom"] = min(3.0, max(1.0, out["zoom"]))
    return out


def ffmpeg_bg(k: int, r: dict, W: int, H: int, rt: str, F: str, start: float, label: str) -> str:
    """Filtro del fondo de relleno: la entrada k ampliada para llenar la pantalla (× zoom), desenfocada (se hace a 1/4
    de tamaño: rápido) y oscurecida, colocada desde start. Sale en [label]."""
    z = r["zoom"]
    qw, qh = max(2, (W // 4) // 2 * 2), max(2, (H // 4) // 2 * 2)
    zw, zh = max(qw, int(qw * z) // 2 * 2), max(qh, int(qh * z) // 2 * 2)
    rad = max(1, int(round(1 + 9 * r["desenfoque"])))
    rad = min(rad, max(1, min(qw, qh) // 2 - 1))
    blur = f"boxblur={rad}:2," if r["desenfoque"] > 0.01 else ""
    dark = f"eq=brightness={-0.6 * r['oscurecer']:.3f}," if r["oscurecer"] > 0.01 else ""
    return (f"[{k}:v]{rt}fps={F},scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={qw}:{qh},{blur}{dark}"
            f"scale={W}:{H}:flags=fast_bilinear,setsar=1,format=yuv420p,setpts=PTS-STARTPTS+{start:.3f}/TB[{label}]")
