"""
⊞ Composición por huecos (la del visor: 2, 3, 4, 6 o 9 huecos).

Lo que hace que funcione de verdad:
  · Varios videos o imágenes soltados A LA VEZ (o elegidos con Ctrl en la lista del «+») llenan los huecos EN ORDEN,
    empezando por el hueco donde los sueltas y siguiendo por los vacíos; todos empiezan en el cabezal (antes iban uno
    detrás de otro en el mismo hueco).
  · Cada uno va en su propia pista «⊞ Composición» y, si el video tiene sonido, con su sonido vinculado: en el visor y
    al exportar se ven y suenan todos a la vez.
  · Soltar en un hueco ocupado lo cambia (lo que había en ese hueco desde el cabezal se quita).
  · Dentro del hueco: mover y escalar el contenido (encuadre = zoom del clip), doble clic = encuadrar (volver a
    llenar el hueco), cambiar dos huecos entre sí y vaciar un hueco.
Todo en UN paso de Ctrl+Z cada vez. Usa el deshacer del controlador (ctrl._edit) sin cambiar controller.py.
"""
from __future__ import annotations

from .model import DEFAULT_IMAGE_DURATION, KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_VIDEO, Clip, new_id

TOL = 0.02          # (fracción del lienzo: una capa «está en el hueco» si su caja coincide con esta tolerancia)
EPS = 1e-3


def misma_caja(a: dict | None, b: dict | None, tol: float = TOL) -> bool:
    if not a or not b:
        return False
    return all(abs(float(a.get(k, 0)) - float(b.get(k, 0))) < tol for k in ("x", "y", "w", "h"))


def clips_en_hueco(p, caja: dict, t: float) -> list:
    """Los clips de las pistas «⊞ Composición» que ocupan ese hueco en el segundo t."""
    out = []
    for c in p.clips.values():
        tr = p.track(c.track_id)
        if tr is None or tr.kind != TRACK_VIDEO or getattr(tr, "role", "") != "comp":
            continue
        if c.start - EPS <= t < c.end - EPS and misma_caja(c.layout, caja):
            out.append(c)
    return sorted(out, key=lambda c: -p.track_index(c.track_id))


def clip_en_hueco(p, caja: dict, t: float):
    """El clip que se ve en ese hueco en t (el de la pista más alta), o None."""
    cs = clips_en_hueco(p, caja, t)
    if not cs:
        return None
    return min(cs, key=lambda c: p.track_index(c.track_id))


def repartir(n_ids: int, idx: int, n_huecos: int, ocupados: set[int] | None = None) -> list[int]:
    """En qué hueco va cada uno de n_ids: el primero donde lo sueltas (idx) y los demás en los huecos VACÍOS que
    siguen (dando la vuelta); si no quedan vacíos, los ocupados que siguen. Los que no caben se quedan fuera.
    idx = -1 → todos de fondo (devuelve -1 para cada uno)."""
    if idx < 0 or n_huecos <= 0:
        return [-1] * n_ids
    ocupados = set(ocupados or ())
    orden = [(idx + k) % n_huecos for k in range(n_huecos)]
    vacios = [i for i in orden[1:] if i not in ocupados]
    llenos = [i for i in orden[1:] if i in ocupados]
    return ([idx] + vacios + llenos)[:n_ids]


def _quitar_con_pareja(ctrl, p, c):
    for o in [c] + list(ctrl.partners(p, c)):
        p.clips.pop(o.id, None)


def colocar(ctrl, asignaciones: list[tuple[str, dict | None]], start: float) -> list[str]:
    """Pone cada (media_id, caja) desde start en un paso de deshacer. caja = hueco (fracciones del lienzo); None =
    de fondo (esos van seguidos, como siempre). Los de un hueco empiezan TODOS en start, cada uno en su pista
    «⊞ Composición», con su sonido vinculado. Devuelve los clips de imagen creados."""
    from .controller import EditError

    def fn(p):
        made = []
        t0 = max(0.0, start)
        main = next((c for tr in reversed([x for x in p.tracks if x.kind == TRACK_VIDEO and x.role not in
                                           ("comp", "fondo")])
                     for c in [p.clip_at(tr.id, t0)] if c is not None), None)
        medios = [(p.media.get(mid), caja) for mid, caja in asignaciones]
        medios = [(m, caja) for m, caja in medios if m is not None and m.kind != KIND_AUDIO]
        for m, _caja in medios:
            if m.kind != KIND_IMAGE and m.duration <= 0:
                raise EditError(f"Todavía se está analizando «{m.name}». Prueba en un momento.")
        largo_videos = max((m.duration for m, caja in medios if caja is not None and m.kind != KIND_IMAGE),
                           default=0.0)

        def dura(m, t):
            if main is not None and main.end - t > 0.5:
                d = main.end - t
                return min(d, m.duration) if m.kind != KIND_IMAGE else d
            if m.kind != KIND_IMAGE:
                return m.duration
            return largo_videos or DEFAULT_IMAGE_DURATION      # (una imagen junto a videos dura lo que el más largo)

        # ⊞ lo que ya había en esos huecos desde el cabezal: se cambia por lo nuevo
        for _m, caja in medios:
            if caja is not None:
                for viejo in clips_en_hueco(p, caja, t0):
                    _quitar_con_pareja(ctrl, p, viejo)
        t_fondo = t0
        for m, caja in medios:
            t = t0 if caja is not None else t_fondo
            d = dura(m, t)
            tid = ctrl._comp_track(p, caja is None, t, t + d)
            lay = dict(caja) if caja is not None else {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "cover"}
            c = Clip(new_id(), m.id, tid, t, 0.0, d, layout=lay)
            p.clips[c.id] = c
            if m.kind == KIND_VIDEO:
                ctrl._link_audio(p, c, m)                    # 🔊 que suene (antes la composición iba muda)
            made.append(c.id)
            if caja is None:
                t_fondo += d
        if not made:
            raise EditError("Arrastra una imagen, un video o un GIF (el sonido va en la línea de tiempo).")
        return made

    res = ctrl._edit("⊞ Composición", fn)
    return res if isinstance(res, list) else []


def vaciar(ctrl, clip_id: str) -> bool:
    """Quita lo que hay en un hueco (la imagen y su sonido) y las pistas «⊞ Composición» / «Audio de video» que se
    quedan vacías por ello. Un paso de deshacer."""
    from .model import TRACK_AUDIO

    def fn(p):
        c = p.clips.get(clip_id)
        if c is None:
            return False
        quitar = [c] + list(ctrl.partners(p, c))
        for x in quitar:
            ctrl._check_clip(p, x)
        pistas = {x.track_id for x in quitar}
        for x in quitar:
            p.clips.pop(x.id, None)
        av = getattr(ctrl, "AV_TRACK", None)            # (el nombre de las pistas «Audio de video»)
        for tid in pistas:
            tr = p.track(tid)
            if tr is None or p.clips_on(tid):
                continue
            comp = tr.kind == TRACK_VIDEO and getattr(tr, "role", "") == "comp"
            if comp or (tr.kind == TRACK_AUDIO and av and tr.name.endswith(av)):
                p.tracks.remove(tr)
        return True

    return bool(ctrl._edit("⊞ Vaciar hueco", fn))


def intercambiar(ctrl, a_id: str, b_id: str) -> bool:
    """Cambia dos huecos entre sí (cada uno se lleva la caja del otro y vuelve a llenarla). Un paso de deshacer."""
    def fn(p):
        a, b = p.clips.get(a_id), p.clips.get(b_id)
        if a is None or b is None or a is b:
            return False
        for c in (a, b):
            ctrl._check_clip(p, c)
        la, lb = dict(a.layout or {}), dict(b.layout or {})
        a.layout, b.layout = lb, la
        a.zoom_kf, b.zoom_kf = [], []
        return True

    return bool(ctrl._edit("⊞ Cambiar huecos", fn))


def encuadrar(ctrl, clip_id: str) -> bool:
    """Doble clic en un hueco: el contenido vuelve a llenar su hueco, centrado (sin zoom). Un paso de deshacer."""
    def fn(p):
        c = p.clips.get(clip_id)
        if c is None:
            return False
        ctrl._check_clip(p, c)
        c.zoom_kf = []
        if c.layout is not None:
            c.layout["fit"] = "cover"
        return True

    return bool(ctrl._edit("⊞ Encuadrar en su hueco", fn))


def mover_contenido(ctrl, clip_id: str, t: float, dx: float, dy: float, pasos: float = 0.0):
    """Mueve (dx, dy en fracciones del lienzo) o escala (pasos de rueda) el contenido DENTRO de su hueco: es el
    encuadre del clip (zoom y punto de mira), así se ve igual en el visor y al exportar."""
    from . import transform
    p = ctrl.project
    c = p.clips.get(clip_id)
    if c is None:
        return
    src = ctrl.clip_source_time(clip_id, t)
    z, x, y = transform.value_at(c.zoom_kf, src)
    box = c.layout or transform.FULL
    if pasos:
        z = min(max(z * (1.12 ** pasos), 1.0), transform.MAX_ZOOM)
    elif (dx or dy) and z < 1.15:
        z = 1.15                                  # (sin acercar no hay nada que mover: se acerca un poco y se mueve)
    if z > 1.0:
        x -= dx / max(1e-3, box["w"]) / z
        y -= dy / max(1e-3, box["h"]) / z
    ctrl.set_zoom_at(clip_id, t, z, x, y, text="⊞ Encuadre en el hueco")


def con_sonido(ctrl, made: list[str]) -> int:
    """Cuántos de los clips puestos llevan sonido vinculado (para avisar si suenan varios a la vez)."""
    p = ctrl.project
    return sum(1 for cid in made if cid in p.clips and ctrl.partners(p, p.clips[cid]))


def caja_por_id(ids: list[str], cajas) -> list:
    """La señal comp_drop lleva UNA caja (dict o None = fondo, como siempre) o una LISTA (una por archivo)."""
    if isinstance(cajas, (list, tuple)):
        return list(cajas)[:len(ids)] + [None] * max(0, len(ids) - len(cajas))
    return [cajas] * len(ids)


def mover_a_hueco(ctrl, clip_id: str, caja: dict) -> bool:
    """⇄ con un hueco vacío: el contenido se muda a ese hueco (y vuelve a llenarlo). Un paso de deshacer."""
    def fn(p):
        c = p.clips.get(clip_id)
        if c is None:
            return False
        ctrl._check_clip(p, c)
        c.layout = dict(caja)
        c.zoom_kf = []
        return True

    return bool(ctrl._edit("⊞ Cambiar de hueco", fn))


def recolocar(ctrl, pares: list) -> bool:
    """Al cambiar el número de huecos: lo que había pasa a los huecos nuevos en orden ([(clip, caja), …]). Un paso."""
    def fn(p):
        hecho = False
        for cid, caja in pares:
            c = p.clips.get(cid)
            if c is None or not caja:
                continue
            ctrl._check_clip(p, c)
            fit = (c.layout or {}).get("fit", "cover")
            c.layout = dict(caja, fit=fit)
            hecho = True
        return hecho

    return bool(ctrl._edit("⊞ Huecos recolocados", fn))


def recolocar_huecos(ctrl, pares: list) -> bool:
    """Al cambiar el número de huecos: TODO lo de cada hueco viejo (a cualquier hora de la línea de tiempo) pasa al hueco
    nuevo con su número ([(caja_vieja, caja_nueva | None), …]). Lo de los huecos que ya no existen se queda donde
    estaba y se avisa (nada se borra). Un paso de deshacer."""
    sobran = []

    def fn(p):
        hecho = False
        mover = []
        for vieja, nueva in pares:
            for c in p.clips.values():
                tr = p.track(c.track_id)
                if tr is None or tr.kind != TRACK_VIDEO or getattr(tr, "role", "") != "comp" or \
                        not misma_caja(c.layout, vieja):
                    continue
                if nueva is None:
                    sobran.append(c.id)
                else:
                    mover.append((c, nueva))
        for c, nueva in mover:                         # (después de mirar todos: un hueco nuevo puede ser uno viejo)
            ctrl._check_clip(p, c)
            c.layout = dict(nueva, fit=(c.layout or {}).get("fit", "cover"))
            hecho = True
        return hecho

    ok = bool(ctrl._edit("⊞ Huecos recolocados", fn))
    if sobran:
        try:
            ctrl.message.emit(f"⊞ {len(sobran)} no caben en los huecos nuevos: siguen donde estaban (elige más "
                              "huecos, vacíalos o muévelos).")
        except Exception:  # noqa: BLE001 - (sin ventana: solo no se avisa)
            pass
    return ok


def accion(ctrl, t: float, nombre: str, args) -> bool:
    """Lo que pide el visor (señal Canvas.comp_accion): vaciar, intercambiar, mover_a_hueco, encuadrar, mover
    (dx, dy) o escalar (pasos de rueda) el contenido de un hueco."""
    args = list(args or ())
    if nombre == "vaciar":
        return vaciar(ctrl, args[0])
    if nombre == "intercambiar":
        return intercambiar(ctrl, args[0], args[1])
    if nombre == "mover_a_hueco":
        return mover_a_hueco(ctrl, args[0], args[1])
    if nombre == "recolocar":
        return recolocar(ctrl, args)
    if nombre == "recolocar_huecos":
        return recolocar_huecos(ctrl, args)
    if nombre == "encuadrar":
        return encuadrar(ctrl, args[0])
    if nombre == "mover":
        mover_contenido(ctrl, args[0], t, float(args[1]), float(args[2]))
        return True
    if nombre == "escalar":
        mover_contenido(ctrl, args[0], t, 0.0, 0.0, float(args[1]))
        return True
    return False
