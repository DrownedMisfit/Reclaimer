"""♻ «Restaurar este video»: los archivos del proyecto que faltan (borrados por error) vuelven de la Papelera a su
sitio, y sus clips dejan de salir «NO ENCONTRADO». Lo usan el clic derecho de la línea de tiempo y el de Medios."""
from __future__ import annotations

import os


def faltan(ctrl, media_ids) -> list[str]:
    """De esos medios, los que salen «NO ENCONTRADO» (en ctrl.missing y su archivo no está)."""
    p = ctrl.project
    out = []
    for mid in media_ids or []:
        m = p.media.get(mid)
        if m is not None and mid in ctrl.missing and not os.path.exists(m.path) and mid not in out:
            out.append(mid)
    return out


def restaurar(ctrl, media_ids, parent=None, al_acabar=None):
    """Saca de la Papelera (en segundo plano) los archivos de esos medios y avisa en la barra de estado."""
    from ..core import papelera
    from .jobs import BackgroundJob
    ids = faltan(ctrl, media_ids)
    if not ids:
        ctrl.message.emit("Ese archivo no falta: no hay nada que restaurar.")
        return None
    rutas = {mid: ctrl.project.media[mid].path for mid in ids}
    ctrl.message.emit("♻ Buscando en la Papelera de Windows…")

    def trabajo(_p, _c):
        return {mid: papelera.restaurar(r) for mid, r in rutas.items()}

    def listo(res: dict):
        ok = [mid for mid, r in res.items() if r in ("OK", "EXISTE") and os.path.exists(rutas[mid])]
        no = [os.path.basename(rutas[mid]) for mid, r in res.items() if r == "NO"]
        mal = [f"{os.path.basename(rutas[mid])} ({r[7:60]})" for mid, r in res.items() if r.startswith("ERROR")]
        if ok:
            ctrl.recheck_missing()
        partes = []
        if ok:
            partes.append(f"♻ {len(ok)} archivo(s) restaurados a su carpeta: sus clips vuelven a verse.")
        if no:
            partes.append(f"No está en la Papelera: {', '.join(no[:3])} (¿se vació o lo moviste a otra carpeta?).")
        if mal:
            partes.append(f"No pude restaurar: {', '.join(mal[:2])}")
        ctrl.message.emit(" ".join(partes) or "Nada que restaurar.")
        if al_acabar is not None:
            al_acabar(ok)

    job = BackgroundJob(trabajo, parent)
    job.done.connect(listo)
    job.failed.connect(lambda m: ctrl.message.emit(f"No pude restaurar: {m[:150]}"))
    if parent is not None:
        parent._job_restaurar = job
    job.start()
    return job
