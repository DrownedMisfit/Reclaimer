"""
🎬 Mi intro y mi outro: el archivo que pones siempre al principio y al final de tus videos, uno por tipo de proyecto
(YouTube · Shorts · Edits). Se guarda en tus ajustes (QSettings «intro_outro/<formato>/intro|outro»).

place(): importa los archivos si no están en Medios, abre un hueco al principio en TODAS las pistas (como «Insertar»,
sin desincronizar nada) y pone la intro en 0 y la outro al final. Todo en un solo paso de Ctrl+Z. Si ya están
puestas (mismo medio al principio o al final), no las duplica.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from . import mapping
from .controller import EditError
from .model import DEFAULT_IMAGE_DURATION, KIND_IMAGE, ORIGIN_USER, Clip, new_id

FORMATOS = (("youtube", "🎬 YouTube"), ("short", "📱 Shorts"), ("edit", "🎵 Edits"))
TOL = mapping.TOL


def get(fmt: str) -> tuple[str, str]:
    """(ruta de la intro, ruta de la outro) de ese tipo de proyecto; «» si no hay."""
    st = QSettings("EditorIA", "EditorIA")
    return (str(st.value(f"intro_outro/{fmt}/intro", "") or ""),
            str(st.value(f"intro_outro/{fmt}/outro", "") or ""))


def set_(fmt: str, intro: str, outro: str) -> None:
    st = QSettings("EditorIA", "EditorIA")
    for quien, ruta in (("intro", intro), ("outro", outro)):
        if ruta:
            st.setValue(f"intro_outro/{fmt}/{quien}", ruta)
        else:
            st.remove(f"intro_outro/{fmt}/{quien}")


def configured(fmt: str) -> bool:
    return any(get(fmt))


def _medio_de(p, ruta: str):
    norm = os.path.normcase(os.path.abspath(ruta))
    return next((m for m in p.media.values() if os.path.normcase(os.path.abspath(m.path)) == norm), None)


def _duracion(m) -> float:
    return DEFAULT_IMAGE_DURATION if m.kind == KIND_IMAGE else m.duration


def _hay_clip(p, mid: str, cumple) -> bool:
    return any(c.media_id == mid and cumple(c) for c in p.clips.values())


def _poner(ctrl, p, m, t: float, dur: float) -> None:
    """Un clip de ese medio en t, en una pista libre de su tipo (y su sonido vinculado, como al añadir)."""
    tid = ctrl._compatible_track(p, m, None)
    tid = ctrl._free_track(p, ctrl.track_kind_for(m), tid, t, t + dur)
    c = Clip(new_id(), m.id, tid, t, 0.0, dur, origin=ORIGIN_USER, layout=ctrl._auto_layout(p, m, tid))
    p.clips[c.id] = c
    ctrl._link_audio(p, c, m)


def place(ctrl, intro: str = "", outro: str = "") -> int:
    """Pone la intro al principio y la outro al final. Devuelve cuántas piezas se pusieron (0 = ya estaban)."""
    for ruta in (intro, outro):
        if ruta and not os.path.isfile(ruta):
            ctrl.message.emit(f"No encuentro «{os.path.basename(ruta)}». Elige otro archivo en «🎬 Mi intro y mi outro».")
            return 0
    pedidos: list[tuple[str, str]] = []           # (intro|outro, id del medio)
    for ruta, quien in ((intro, "intro"), (outro, "outro")):
        if not ruta:
            continue
        m = _medio_de(ctrl.project, ruta)
        if m is None:                              # no está en Medios: se importa ahora
            ids = ctrl.import_now([ruta])
            m = ctrl.project.media.get(ids[0]) if ids else None
        if m is None:
            ctrl.message.emit(f"No pude importar «{os.path.basename(ruta)}».")
            return 0
        pedidos.append((quien, m.id))

    def fn(p):
        n = 0
        for quien, mid in pedidos:
            m = p.media[mid]
            dur = _duracion(m)
            if quien == "intro":
                if _hay_clip(p, mid, lambda c: c.start <= TOL):
                    continue
                if dur <= 0:
                    raise EditError(f"Todavía se está analizando «{m.name}». Prueba en un momento.")
                if any(tr.locked and p.clips_on(tr.id) for tr in p.tracks):
                    raise EditError("🔒 Hay una pista bloqueada con clips: desbloquéala para poner la intro "
                                    "sin que se desincronice.")
                ctrl._push_after(p, 0.0, dur)      # todo se corre a la derecha en TODAS las pistas
                _poner(ctrl, p, m, 0.0, dur)
                n += 1
            else:
                fin = max((c.end for c in p.clips.values()), default=0.0)
                if fin > 0 and _hay_clip(p, mid, lambda c: abs(c.end - fin) <= TOL):
                    continue
                if dur <= 0:
                    raise EditError(f"Todavía se está analizando «{m.name}». Prueba en un momento.")
                _poner(ctrl, p, m, fin, dur)
                n += 1
        return n

    res = ctrl._edit("🎬 Poner mi intro y outro", fn)
    n = res if isinstance(res, int) and not isinstance(res, bool) else 0
    if n:
        ctrl.message.emit(f"🎬 Intro y outro puestas ({n}): la intro al principio y la outro al final. Ctrl+Z lo deshace.")
    else:
        ctrl.message.emit("Tu intro y tu outro ya estaban puestas.")
    return n
