"""
🎬 Clip de escena: una escena en la línea de tiempo como UN SOLO clip en UNA pista (como un clip compuesto), pero sin
cocinarla a video: el visor y la exportación la «despliegan» justo antes de pintar o renderizar.

  · El clip usa un medio propio de la escena (una imagen con su miniatura, categoría «🎬 Escenas»); la escena guarda
    su id en escena["media_id"] y el clip lleva la nota de la escena (doble clic = editarla). Se mueve, corta y
    recorta como cualquier clip: source_in = segundo de la escena desde el que se ve (cortarlo da dos clips que
    enseñan tramos distintos de la misma escena).
  · expandir(p) → un proyecto para pintar o exportar donde cada clip de escena es lo que pondría «✓ Aplicar»: el
    fondo (imagen o 🎨 capa de ajuste desenfocada u oscurecida sobre lo de debajo; «Sin fondo» = nada), una pista por
    personaje (en orden de capas, justo encima de la pista del clip) con sus animaciones, y los sonidos en pistas de
    audio; todo desplazado a su tiempo y recortado a su tramo. Los demás clips son los MISMOS objetos (lo que mueves
    en vivo se sigue viendo). Sin clips de escena devuelve el mismo proyecto.
  · desplegar(p, clip) → lo mismo pero de verdad en el proyecto («Deshacer clip compuesto»).
Sin Qt.
"""
from __future__ import annotations

import copy
import os

from . import scenes
from .model import KIND_IMAGE, TRACK_AUDIO, TRACK_VIDEO, Clip, Track, new_id

CATEGORIA = "🎬 Escenas"


# ---------------------------------------------------------------- consultas
def escena_de_medio(p, media_id: str) -> dict | None:
    if not media_id:
        return None
    for e in (getattr(p, "scenes", None) or {}).values():
        if e.get("media_id") == media_id:
            return e
    return None


def es_medio_escena(p, media_id: str) -> bool:
    return escena_de_medio(p, media_id) is not None


def escena_del_clip(p, c) -> dict | None:
    return escena_de_medio(p, getattr(c, "media_id", ""))


def clips_de_escena(p, escena_id: str) -> list:
    e = (getattr(p, "scenes", None) or {}).get(escena_id) or {}
    mid = e.get("media_id")
    return [c for c in p.clips.values() if mid and c.media_id == mid]


def _medios_escena(p) -> set:
    return {e.get("media_id") for e in (getattr(p, "scenes", None) or {}).values() if e.get("media_id")}


def hay(p) -> bool:
    mids = _medios_escena(p)
    return bool(mids) and any(c.media_id in mids for c in p.clips.values())


# ---------------------------------------------------------------- miniatura (el medio del clip)
def miniatura(p, escena: dict, carpeta: str) -> str:
    """Un PNG del tamaño del proyecto (reducido) con los personajes en su sitio, transparente detrás: así, si algo lo
    pinta sin desplegar, al menos se ve la escena quieta. Devuelve la ruta."""
    from PIL import Image
    os.makedirs(carpeta, exist_ok=True)
    W = 480
    H = max(2, int(round(W * p.height / max(1, p.width))))
    lienzo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for act in escena.get("actores", []):
        m = p.media.get(act.get("media_id", ""))
        if m is None or not os.path.isfile(m.path) or act.get("efecto"):
            continue
        c = act["caja"]
        try:
            with Image.open(m.path) as im:
                im = im.convert("RGBA")
                bw, bh = max(1, int(c["w"] * W)), max(1, int(c["h"] * H))
                if c.get("fit") == "stretch":
                    im = im.resize((bw, bh))
                else:
                    k = min(bw / im.width, bh / im.height)
                    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
                if c.get("flip_h"):
                    im = im.transpose(Image.FLIP_LEFT_RIGHT)
                x = int(c["x"] * W + (bw - im.width) / 2)
                y = int(c["y"] * H + (bh - im.height) / 2)
                lienzo.alpha_composite(im, (max(0, x), max(0, y)),
                                       (max(0, -x), max(0, -y)))
        except (OSError, ValueError):
            continue
    ruta = os.path.join(carpeta, f"escena_{escena['id']}.png")
    lienzo.save(ruta)
    return ruta


# ---------------------------------------------------------------- desplegar
def _ajuste(p) -> str | None:
    from . import generators
    return next((m.id for m in p.media.values() if generators.is_adjust(m)), None)


def _recortar(c: Clip, lo: float, hi: float, es_imagen: bool) -> tuple[bool, bool, bool]:
    """Deja el clip dentro de [lo, hi] (tiempo de la línea). (¿queda algo?, ¿se cortó el inicio?, ¿y el final?)."""
    izq = der = False
    if c.start < lo - 1e-6:
        cut = lo - c.start
        c.start = lo
        c.duration -= cut
        izq = True
        if es_imagen:                       # (en una imagen las claves cuentan desde su inicio)
            for attr in ("zoom_kf", "layout_kf", "op_kf", "vol_kf"):
                kf = getattr(c, attr, None)
                if kf:
                    setattr(c, attr, [dict(k, t=round(k["t"] - cut, 4)) for k in kf])
        else:
            c.source_in += cut * (c.speed or 1.0)
    if c.start + c.duration > hi + 1e-6:
        c.duration = hi - c.start
        der = True
    return c.duration > 1e-3, izq, der


def _a_caja(box: dict, L: dict) -> dict:
    """Una caja (fracciones de la pantalla) metida en el encuadre L del clip de escena."""
    b = dict(box)
    for k, d in (("x", 0.0), ("y", 0.0), ("w", 1.0), ("h", 1.0)):
        b.setdefault(k, d)
    b["x"] = round(float(L.get("x", 0)) + float(b["x"]) * float(L.get("w", 1)), 5)
    b["y"] = round(float(L.get("y", 0)) + float(b["y"]) * float(L.get("h", 1)), 5)
    b["w"] = round(float(b["w"]) * float(L.get("w", 1)), 5)
    b["h"] = round(float(b["h"]) * float(L.get("h", 1)), 5)
    return b


def _por_curva(x: Clip, kf_escena: list, s0: float, sp: float) -> None:
    """Multiplica la opacidad animada de la pieza (imagen) por la del clip de escena (en segundos de la escena)."""
    from .curves import value_at
    propios = list(x.op_kf or [])
    ts = {round(k["t"], 4) for k in propios}
    ts |= {round((float(k["t"]) - s0) / sp, 4) for k in kf_escena}
    ts |= {0.0, round(x.duration, 4)}
    x.op_kf = [{"t": t, "v": round(value_at(propios, t) * value_at(kf_escena, s0 + t * sp), 4)}
               for t in sorted(v for v in ts if -1e-6 <= v <= x.duration + 1e-6)]


def _piezas_de(p, esc: dict, nota: str, ajuste: str | None, ids: bool, base: str):
    """[(capa, Clip)] con los tiempos de la escena empezando en 0 (capa: "fondo", "ajuste", id de actor, "sonido:k")."""
    e = scenes.copia(esc)
    scenes.mover(e, 0.0)
    out = []
    n = [0]

    def cid():
        n[0] += 1
        return new_id() if ids else f"{base}~{n[0]}"
    largo = scenes.largo(e)
    trozos = scenes.piezas(e)
    img = e.get("fondo_img") if e.get("fondo") in ("img", "img_blur") else None
    from . import transform
    if img and img in p.media and trozos:
        fi = Clip(cid(), img, "", 0.0, 0.0, largo, volume=0.0, note=nota, layout=dict(transform.FULL, fit="cover"))
        fi.fx = {"fade_in": 0.25, "fade_out": 0.25}
        if e["fondo"] == "img_blur":
            fi.fx["blur"] = scenes.BLUR
        out.append(("fondo", fi))
    if e.get("fondo") in ("blur", "dark") and ajuste and trozos:
        fo = Clip(cid(), ajuste, "", 0.0, 0.0, largo, volume=0.0, note=nota,
                  layout=dict(transform.FULL, fit="stretch", bg="none"))
        if e["fondo"] == "blur":
            fo.fx = {"blur": scenes.BLUR}
        else:
            fo.color = {"exposure": scenes.OSCURO}
        fo.fx = dict(fo.fx or {}, fade_in=0.25, fade_out=0.25)
        out.append(("ajuste", fo))
    for act in e["actores"]:
        m = p.media.get(act["media_id"])
        if m is None:
            continue
        for pz in (x for x in trozos if x["actor"] == act["id"]):
            c = Clip(cid(), act["media_id"], "", pz["a"], 0.0, pz["b"] - pz["a"], volume=0.0, note=nota)
            pl = pz["plan"]
            c.layout, c.layout_kf, c.op_kf = dict(pl["layout"]), [dict(k) for k in pl["layout_kf"]], \
                [dict(k) for k in pl["op_kf"]]
            if pl["fx"]:
                c.fx = dict(pl["fx"])
            if m.kind != KIND_IMAGE:
                c.layout_kf = [dict(k, t=round(c.src_at(k["t"]), 4)) for k in c.layout_kf]
                c.op_kf = [dict(k, t=round(c.src_at(k["t"]), 4)) for k in c.op_kf]
            out.append((act["id"], c))
    for k, s in enumerate(scenes.sonidos(e)):
        m = p.media.get(s["media_id"])
        if m is None:
            continue
        d = s["b"] - s["a"]
        if m.duration:
            d = min(d, float(m.duration))
        out.append((f"sonido:{k}", Clip(cid(), s["media_id"], "", s["a"], 0.0, d, volume=float(s.get("vol", 1.0)),
                                         note=nota)))
    return out


def _colocar(p, c: Clip, esc: dict, ids: bool) -> list[str]:
    """Pone en p lo de la escena que enseña el clip c (y quita c). ids=False: ids fijos (para pintar sin parpadeos).
    Del clip de escena se respetan: su tramo (source_in), velocidad, encuadre (toda la escena dentro de su caja),
    opacidad y su curva, fundidos de entrada y salida, color y efectos de imagen; la pista oculta la oculta."""
    tr = p.track(c.track_id)
    if tr is None or not c.enabled:
        p.clips.pop(c.id, None)
        return []
    nota = scenes.nota(esc["id"])
    piezas = _piezas_de(p, esc, nota, _ajuste(p), ids, c.id)
    p.clips.pop(c.id, None)
    sp = float(c.speed) if c.speed and c.speed > 0 else 1.0
    lo, hi = c.start, c.start + c.duration
    L = c.layout if c.layout and any(abs(float(c.layout.get(k, d)) - d) > 1e-4
                                     for k, d in (("x", 0), ("y", 0), ("w", 1), ("h", 1))) else None
    fx_c = dict(c.fx or {})
    fade_in, fade_out = float(fx_c.pop("fade_in", 0) or 0), float(fx_c.pop("fade_out", 0) or 0)
    tr_in = fx_c.pop("trans", None)               # (transiciones con los vecinos: al menos un fundido)
    if isinstance(tr_in, dict):
        fade_in = max(fade_in, float(tr_in.get("dur", 0) or 0))
    vecino = next((o for o in p.clips.values() if o.track_id == c.track_id and o.id != c.id
                   and abs(o.start - hi) < 1e-3), None)
    tr_out = (vecino.fx or {}).get("trans") if vecino is not None else None
    if isinstance(tr_out, dict):
        fade_out = max(fade_out, float(tr_out.get("dur", 0) or 0))
    capas_v = []                                    # (de abajo arriba: fondo, ajuste, actores en su orden)
    for capa, _x in piezas:
        if not capa.startswith("sonido:") and capa not in capas_v:
            capas_v.append(capa)
    pistas: dict[str, str] = {}
    i = p.track_index(tr.id)
    for k, capa in enumerate(capas_v):              # (cada una ENCIMA de la anterior: se inserta en el mismo índice)
        t = Track(new_id() if ids else f"{tr.id}~{c.id}~{k}", TRACK_VIDEO, f"🎬 {esc.get('nombre') or 'Escena'}",
                  hidden=tr.hidden, locked=tr.locked, fx=dict(tr.fx or {}))
        p.tracks.insert(i, t)
        pistas[capa] = t.id
    ult_audio = max((j for j, t in enumerate(p.tracks) if t.kind == TRACK_AUDIO), default=len(p.tracks) - 1)
    creados = []
    for capa, x in piezas:
        sonido = capa.startswith("sonido:")
        if sonido:
            t = Track(new_id() if ids else f"{tr.id}~{c.id}~{capa}", TRACK_AUDIO, f"🎬 {esc.get('nombre') or ''}",
                      muted=tr.hidden or tr.muted)
            ult_audio += 1
            p.tracks.insert(ult_audio, t)
            x.track_id = t.id
        else:
            x.track_id = pistas[capa]
        m = p.media.get(x.media_id)
        es_img = bool(m and m.kind == KIND_IMAGE)
        x.start = round(c.start + (x.start - c.source_in) / sp, 4)      # (segundo de la escena → de la línea)
        if sp != 1.0:
            x.duration = x.duration / sp
            if es_img:
                for attr in ("layout_kf", "op_kf", "zoom_kf"):
                    kf = getattr(x, attr, None)
                    if kf:
                        setattr(x, attr, [dict(k, t=round(k["t"] / sp, 4)) for k in kf])
            else:
                x.speed = (x.speed or 1.0) * sp
            if x.fx:
                x.fx = {k: (v / sp if k in ("fade_in", "fade_out") and isinstance(v, (int, float)) else v)
                        for k, v in x.fx.items()}
        ok, izq, der = _recortar(x, lo, hi, es_img)
        if not ok:
            continue
        if x.fx and (izq or der):                  # (el fundido propio, solo en el principio o fin de verdad)
            x.fx = {k: v for k, v in x.fx.items() if not ((izq and k == "fade_in") or (der and k == "fade_out"))} \
                or None
        if not sonido:
            if L is not None:
                x.layout = _a_caja(x.layout or {"x": 0, "y": 0, "w": 1, "h": 1, "fit": "stretch"}, L)
                x.layout_kf = [dict(_a_caja(k, L), t=k["t"], **({"i": k["i"]} if "i" in k else {}))
                               for k in (x.layout_kf or [])]
            if c.opacity != 1.0:
                x.opacity = x.opacity * c.opacity
            if c.op_kf and es_img:
                _por_curva(x, c.op_kf, c.source_in + (x.start - c.start) * sp, sp)
            if c.color and not x.color:
                x.color = dict(c.color)
            if fx_c:
                x.fx = dict(fx_c, **(x.fx or {}))
            fx = dict(x.fx or {})
            if fade_in and x.start <= lo + 1e-3:
                fx["fade_in"] = max(float(fx.get("fade_in", 0) or 0), fade_in)
            if fade_out and x.start + x.duration >= hi - 1e-3:
                fx["fade_out"] = max(float(fx.get("fade_out", 0) or 0), fade_out)
            x.fx = fx or None
        p.clips[x.id] = x
        creados.append(x.id)
    return creados


_CACHE: dict = {}


def expandir(p):
    """El proyecto para pintar o exportar, con cada clip de escena desplegado (ver arriba). Memorizado por versión."""
    if not hay(p):
        return p
    mids = _medios_escena(p)
    suyos = sorted((c for c in p.clips.values() if c.media_id in mids), key=lambda c: c.id)
    firma = (id(p), id(p.clips), tuple(map(id, p.clips.values())), len(p.tracks),
             tuple((c.id, c.start, c.duration, c.source_in, c.track_id, c.enabled, c.opacity, c.speed,
                    repr(c.layout), repr(c.layout_kf), repr(c.op_kf), repr(c.fx), repr(c.color)) for c in suyos),
             tuple(sorted((k, repr(v)) for k, v in p.scenes.items() if v.get("media_id"))),
             tuple((t.id, t.hidden, t.locked, t.muted, t.solo, repr(t.fx)) for t in p.tracks))
    hit = _CACHE.get("q")
    if hit is not None and hit[0] == firma:
        _al_dia(hit[1], p)
        return hit[1]
    q = copy.copy(p)
    for k in ("_lect", "_lect_rev"):
        q.__dict__.pop(k, None)
    q.clips = dict(p.clips)
    q.tracks = list(p.tracks)
    for c in suyos:
        esc = escena_de_medio(p, c.media_id)
        if esc is not None:
            _colocar(q, copy.copy(c), esc, ids=False)
    _CACHE["q"] = (firma, q)
    return q


def _al_dia(q, p) -> None:
    """La copia memorizada, con lo de ahora del proyecto (marcas, nombre, tamaño, marcadores…) salvo clips y pistas."""
    for k, v in p.__dict__.items():
        if k not in ("clips", "tracks", "_lect", "_lect_rev"):
            q.__dict__[k] = v


def sincronizar(p, carpeta: str) -> list[str]:
    """Que cada escena con medio lo tenga en Medios y con su miniatura en el disco (otro PC, datos limpios, deshacer
    y rehacer…), y fuera los medios de escenas que ya no existen y nadie usa. Devuelve los ids que cambiaron."""
    from .model import MediaItem
    cambiados = []
    usados = set()
    for e in (getattr(p, "scenes", None) or {}).values():
        mid = e.get("media_id")
        if not mid or scenes.es_comparativa(e):
            continue
        usados.add(mid)
        m = p.media.get(mid)
        if m is None:
            ruta = miniatura(p, e, carpeta)
            p.media[mid] = MediaItem(id=mid, path=ruta, kind=KIND_IMAGE, name=f"🎬 {e.get('nombre') or 'Escena'}",
                                     category=CATEGORIA, width=p.width, height=p.height, probed=True,
                                     duration=round(scenes.largo(e), 3))
            cambiados.append(mid)
        elif not os.path.isfile(m.path):
            m.path = miniatura(p, e, carpeta)
            cambiados.append(mid)
    en_uso = {c.media_id for c in p.clips.values()}
    for mid, m in list(p.media.items()):
        if m.category == CATEGORIA and mid not in usados and mid not in en_uso and \
                os.path.basename(m.path).startswith("escena_") and \
                os.path.basename(os.path.dirname(m.path)) == "escenas_clip":
            del p.media[mid]
            cambiados.append(mid)
    return cambiados


def desplegar(p, clip_id: str) -> list[str]:
    """«Deshacer clip compuesto» de un clip de escena: sus clips sueltos, de verdad, en p. Devuelve sus ids."""
    c = p.clips.get(clip_id)
    esc = escena_del_clip(p, c) if c is not None else None
    if esc is None:
        return []
    return _colocar(p, c, esc, ids=True)
