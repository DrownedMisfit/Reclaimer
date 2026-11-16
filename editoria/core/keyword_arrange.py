"""
⚡ Acomodar por palabras clave: cada vez que dices una palabra que tiene carpeta (🔑 «Clips por palabra»), se pone ahí
un trozo de su material, y TODAS las menciones se acomodan de una vez. Sin Qt.

  · Tipo de cada archivo (kind_of_file): las subcarpetas mandan («Gameplay», «Cinemáticas», «Tráiler»… también en el
    nombre del archivo); si no dicen nada, lo que vio la IA (MediaItem.ai_type). Las imágenes, «image».
  · Cada mención (collect) lleva un tipo sugerido (suggest) por lo que dices alrededor («la cinemática del final» → 🎬,
    «el combate» → 🎮) y lo que haya en su carpeta; el usuario lo cambia con un clic (project.kw_choices[clave]).
  · La secuencia (plan):
      – avanzar en orden: cada mención del mismo tipo toma el trozo SIGUIENTE de su material (sin repetir escenas);
      – orden de los archivos: 01, 02, 10… (orden natural del nombre; las subcarpetas cuentan) = el de la historia;
      – según lo que dices: si el material tiene huellas de la IA, la frase elige el momento más parecido, pero solo
        hacia delante (la historia no retrocede) y solo si se parece claramente más que el resto.
  · Duración: la de la frase (2–6 s), sin pisar la siguiente mención.
  · 🧩 Relleno (fill=True): donde no se ve NADA (ningún clip a pantalla completa ni de palabra clave), sigue el gameplay
    del juego del que estás hablando (el de la última mención; antes de la primera, el de la primera), hacia delante
    en su material y sin repetir lo que ya usaron las menciones. Hasta que nombras otro juego.

Clave de una mención: «palabra|media_id|segundo del archivo» (no cambia al mover o recortar la narración).
"""
from __future__ import annotations

import bisect
import os
import re
from dataclasses import dataclass, field

from . import keyword_folders as KF
from .model import IMAGE_EXT, VIDEO_EXT

KINDS = ("gameplay", "cinematic", "image", "none")
ICON = {"gameplay": "🎮", "cinematic": "🎬", "image": "🖼", "none": "✕"}
NAME = {"gameplay": "Gameplay", "cinematic": "Cinemática", "image": "Imagen", "none": "Nada (no poner)"}
COLOR = {"gameplay": "#4cc38a", "cinematic": "#b07cf0", "image": "#e0b341", "none": "#6b6f78"}

# lo que dicen las carpetas (y los nombres de archivo), por palabras completas («Escenarios» no es «escena»)
_CINE_PRE = ("cinematic", "cutscene", "trailer")
_CINE_PAL = {"escena", "escenas", "historia", "cine", "cinema", "cinematica", "cinematicas"}
_GAME_PAL = {"gameplay", "jugabilidad", "partida", "partidas", "gameplays"}
# lo que dices alrededor de la palabra
_CINE_CTX = {"cinematica", "cinematicas", "escena", "escenas", "historia", "trama", "argumento", "final", "revela",
             "revelacion", "muere", "muerte", "dialogo", "dice", "cuenta", "trailer", "cutscene", "cinematic",
             "story", "ending", "villano", "personaje", "personajes", "narrativa", "guion"}
_GAME_CTX = {"jugar", "jugando", "juegas", "jugable", "jugabilidad", "gameplay", "mecanica", "mecanicas", "combate",
             "combates", "pelea", "peleas", "pelear", "disparar", "disparos", "arma", "armas", "nivel", "niveles",
             "mision", "misiones", "explorar", "exploracion", "mapa", "jefe", "jefes", "enemigos", "controles",
             "multijugador", "online", "partida", "partidas", "habilidad", "habilidades", "combat", "shooting",
             "fighting", "exploring", "looting", "driving", "boss"}
DUR_MIN = 1.0          # una mención que casi pisa la siguiente: al menos un segundo o nada


def _natural(s: str) -> list:
    """Orden natural por partes de la ruta: «2» antes que «10»; sin distinguir mayúsculas ni tildes. Clave homogénea
    (los números y las letras nunca se comparan entre sí)."""
    out = []
    for parte in re.split(r"[\\/]+", s):
        trozos = [p for p in re.split(r"(\d+)", KF.norm(parte).replace(" ", "")) if p]
        out.append(tuple((0, int(t), "") if t.isdigit() else (1, 0, t) for t in trozos))
    return out


def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _dentro(path: str, roots: list[str]) -> tuple[str, str] | None:
    """(raíz, ruta relativa) de la primera raíz que contiene el archivo."""
    np_ = _norm_path(path)
    for r in roots:
        nr = _norm_path(r).rstrip("\\/")
        if np_.startswith(nr + os.sep):
            return r, os.path.relpath(np_, nr)
    return None


def _tipo_de_texto(texto: str) -> str | None:
    pal = KF.norm(texto).split()
    if any(w.startswith(_CINE_PRE) for w in pal) or set(pal) & _CINE_PAL:
        return "cinematic"
    if set(pal) & _GAME_PAL or "game play" in " ".join(pal):
        return "gameplay"
    return None


def kind_of_file(path: str, roots: list[str], ai_type: str = "", linked: list[str] | None = None) -> str | None:
    """«gameplay» | «cinematic» | «image» | None (no se sabe: vale como gameplay y como cinemática).
    roots: las carpetas de esa palabra (la propia y las enlazadas): lo que hay ENTRE ellas y el archivo (subcarpetas),
    el nombre de la carpeta enlazada (linked: «…/Halo cinemáticas») y el nombre del archivo mandan sobre la IA."""
    if os.path.splitext(path)[1].lower() in IMAGE_EXT:
        return "image"
    partes: list[str] = []
    d = _dentro(path, roots)
    if d is not None:
        raiz, rel = d
        if linked and any(_norm_path(raiz) == _norm_path(x) for x in linked):
            partes.append(os.path.basename(os.path.normpath(raiz)))
        partes += rel.split(os.sep)[:-1]
    partes.append(os.path.splitext(os.path.basename(path))[0])
    for parte in reversed(partes):                 # (la subcarpeta más cercana al archivo manda)
        k = _tipo_de_texto(parte)
        if k:
            return k
    t = KF.norm(ai_type)
    if t.startswith("cinematica"):
        return "cinematic"
    if t == "gameplay":
        return "gameplay"
    return None


@dataclass
class Pool:
    """El material de una palabra, por tipo, en el orden de la historia."""
    folder: str
    gameplay: list[str] = field(default_factory=list)
    cinematic: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)      # videos sin tipo: sirven para los dos
    image: list[str] = field(default_factory=list)

    def videos(self, kind: str) -> list[str]:
        own = self.gameplay if kind == "gameplay" else self.cinematic if kind == "cinematic" else []
        return own + self.unknown

    def available(self) -> list[str]:
        out = []
        if self.gameplay or self.unknown:
            out.append("gameplay")
        if self.cinematic or self.unknown:
            out.append("cinematic")
        if self.image:
            out.append("image")
        return out + ["none"]


def build_pools(folders: list[dict], ai_type_of=None, file_order: bool = True) -> dict[str, Pool]:
    """{label de la palabra: Pool}. ai_type_of(ruta) → tipo que vio la IA ('' si no se sabe)."""
    pools: dict[str, Pool] = {}
    for f in folders:
        links = list(f.get("links") or [])
        roots = ([f["own_path"]] if f.get("own_path") else []) + links
        pool = Pool(f["label"])
        files = [p for p in f.get("files") or [] if os.path.splitext(p)[1].lower() in (VIDEO_EXT | IMAGE_EXT)]
        if file_order:
            def clave(p, roots=roots):
                d = _dentro(p, roots)
                return _natural(d[1] if d else os.path.basename(p))
            files = sorted(files, key=clave)
        for p in files:
            k = kind_of_file(p, roots, ai_type_of(p) if ai_type_of else "", links)
            getattr(pool, k if k in ("gameplay", "cinematic", "image") else "unknown").append(p)
        pools[f["label"]] = pool
    return pools


def collect(found: list[dict], folders: list[dict]) -> list[dict]:
    """Las menciones con hora de las palabras que tienen carpeta, en orden: [{key, term, folder, t, context, mods}]."""
    out = []
    for e in found or []:
        f = KF.match(e.get("term", ""), folders)
        if f is None:
            continue
        for h in e.get("hits") or []:
            if h.get("tl") is None:
                continue
            out.append({"key": f"{KF.norm(f['label'])}|{e.get('media_id', '')}|{float(h.get('src', 0)):.2f}",
                        "term": e["term"], "folder": f["label"], "t": float(h["tl"]),
                        "context": str(h.get("context") or ""), "mods": list(h.get("mods") or [])})
    out.sort(key=lambda m: m["t"])
    limpio = []
    for m in out:                                   # (dos menciones en el mismo sitio: la primera)
        if limpio and abs(limpio[-1]["t"] - m["t"]) < 0.05:
            continue
        limpio.append(m)
    return limpio


def suggest(mention: dict, pool: Pool | None) -> str:
    """El tipo que mejor encaja con lo que dices alrededor y con lo que hay en la carpeta."""
    disp = pool.available() if pool else ["none"]
    palabras = set(KF.norm(mention.get("context", "")).split()) | {KF.norm(m) for m in mention.get("mods") or []}
    cine, juego = len(palabras & _CINE_CTX), len(palabras & _GAME_CTX)
    if cine > juego and "cinematic" in disp:
        return "cinematic"
    if juego > cine and "gameplay" in disp:
        return "gameplay"
    if pool is not None and not pool.gameplay and pool.cinematic and "cinematic" in disp:
        return "cinematic"                          # (solo hay cinemáticas: esas)
    for k in ("gameplay", "cinematic", "image"):
        if k in disp:
            return k
    return "none"


def kind_for(mention: dict, choices: dict, pool: Pool | None) -> tuple[str, bool]:
    """(tipo, elegido a mano). Lo elegido a mano manda si aún hay material de ese tipo."""
    c = (choices or {}).get(mention["key"])
    if c in KINDS and (c == "none" or (pool is not None and c in pool.available())):
        return c, True
    return suggest(mention, pool), False


@dataclass
class Item:
    key: str
    t: float
    dur: float
    path: str
    src: float
    kind: str
    by_context: bool = False
    fill: bool = False          # 🧩 relleno de un hueco (no es una mención)
    folder: str = ""            # la carpeta (palabra) de donde sale


FILL_MIN = 1.0       # un hueco más corto que esto no se rellena (un parpadeo de 1 s no molesta tanto como un salto)


def gaps(covered: list[tuple[float, float]], start: float, end: float, min_len: float = FILL_MIN) -> list[tuple]:
    """Los tramos de [start, end] que no tapa nada de «covered» (de al menos min_len)."""
    out, t = [], start
    for a, b in sorted((max(start, a), min(end, b)) for a, b in covered if b > start and a < end):
        if a - t >= min_len:
            out.append((t, a))
        t = max(t, b)
    if end - t >= min_len:
        out.append((t, end))
    return out


def durations(mentions: list[dict], kinds: list[str], phrase_dur=None, timeline_end: float | None = None
              ) -> list[float]:
    """La duración de cada mención: la de su frase, sin pisar la SIGUIENTE QUE PONE ALGO (las ✕ no cuentan)."""
    out = []
    activos = [m["t"] for m, k in zip(mentions, kinds) if k != "none"]
    for m in mentions:
        d = float(phrase_dur(m["t"])) if phrase_dur else 4.0
        nxt = next((t for t in activos if t > m["t"] + 1e-3), None)
        if nxt is not None:
            d = min(d, nxt - m["t"])
        if timeline_end is not None:
            d = min(d, timeline_end - m["t"])
        out.append(d)
    return out


def _s0(d_f: float, dur: float) -> float:
    """Donde empieza un video sin usar: tras los logos del principio, si cabe."""
    return min(3.0, 0.1 * d_f, max(0.0, d_f - dur - 0.1))


def plan(mentions: list[dict], choices: dict, pools: dict[str, Pool], duration_of, phrase_dur=None,
         timeline_end: float | None = None, context: bool = True, vecs_of=None, qvecs=None, cancel=None,
         fill: bool = False, covered: list[tuple[float, float]] | None = None
         ) -> tuple[list[Item], dict]:
    """El acomodo: [Item] en orden y un resumen {"placed", "skipped", "repeated", "by_context"}.
    duration_of(ruta) → segundos (0 = no se sabe: ese archivo se salta); solo se pide al llegar a ese archivo.
    phrase_dur(t) → duración de la frase. vecs_of(ruta) → (momentos, huellas) o None; qvecs.get(clave) → huella de lo
    que dices (según lo que dices). cancel() → True para parar.
    Lo usado se apunta POR ARCHIVO (hasta qué segundo), para todo el acomodo: un trozo no sale dos veces aunque el
    archivo sirva para 🎮 y para 🎬, o lo enlacen dos palabras, o las frases duren distinto."""
    import numpy as np
    memo_d: dict[str, float] = {}

    def dur_of(path):
        if path not in memo_d:
            try:
                memo_d[path] = float(duration_of(path) or 0.0)
            except Exception:  # noqa: BLE001 - archivo dañado: se salta
                memo_d[path] = 0.0
        return memo_d[path]

    memo_v: dict[str, object] = {}

    def vec_of(path):
        if vecs_of is None:
            return None
        if path not in memo_v:
            try:
                memo_v[path] = vecs_of(path)
            except Exception:  # noqa: BLE001 - huellas dañadas: sin ellas
                memo_v[path] = None
        return memo_v[path]

    kinds = [kind_for(m, choices, pools.get(m["folder"]))[0] if pools.get(m["folder"]) else "none" for m in mentions]
    durs = durations(mentions, kinds, phrase_dur, timeline_end)
    usado: dict[str, float] = {}                     # ruta → segundo hasta el que ya se usó
    tramos: dict[str, list] = {}                     # ruta → [(desde, hasta)] usados (para aprovechar lo saltado)
    cursor: dict[tuple[str, str], int] = {}          # (palabra, tipo) → por qué archivo va la historia
    img_n: dict[str, int] = {}
    items: list[Item] = []
    res = {"placed": 0, "skipped": 0, "repeated": 0, "by_context": 0, "filled": 0, "filled_s": 0.0}

    def libre(path, dur) -> float | None:
        """Desde dónde cabe un trozo de dur en ese archivo (None = no cabe)."""
        d_f = dur_of(path)
        if d_f < dur + 0.2:
            return None
        src = usado.get(path)
        src = _s0(d_f, dur) if src is None else src
        return src if src + dur <= d_f - 0.1 + 1e-6 else None

    def mencion(m, kind, dur, dur_alt=None):
        pool = pools.get(m["folder"])
        if kind == "none" or pool is None:
            return
        if dur < DUR_MIN:
            res["skipped"] += 1
            return
        if kind == "image":
            n = img_n.get(m["folder"], 0)
            items.append(Item(m["key"], m["t"], dur, pool.image[n % len(pool.image)], 0.0, kind))
            res["repeated"] += int(n == len(pool.image))
            img_n[m["folder"]] = n + 1
            res["placed"] += 1
            return
        files = pool.videos(kind)
        if not files:
            res["skipped"] += 1
            return
        ck = (m["folder"], kind)
        c = cursor.get(ck, 0)
        # los archivos ya gastados (ni el trozo más corto cabe) dejan de ser «por donde va»
        while c < len(files) and libre(files[c], DUR_MIN) is None:
            c += 1
        elegido, por_ctx = None, False
        if context and vecs_of is not None and qvecs is not None:   # según lo que dices: hacia delante
            ventana = [fi for fi in range(c, min(len(files), c + 3)) if vec_of(files[fi])]
            q = qvecs.get(m["key"]) if ventana else None
            if q is not None:
                cand = []
                for fi in ventana:
                    desde = libre(files[fi], dur)
                    if desde is None:
                        continue
                    ts, vs = vec_of(files[fi])
                    try:
                        sims = np.asarray(vs, np.float32) @ np.asarray(q, np.float32)
                    except ValueError:                       # (huellas de otro modelo)
                        continue
                    d_f = dur_of(files[fi])
                    for tk, sim in zip(ts, sims):
                        if desde <= float(tk) <= d_f - dur - 0.1:
                            cand.append((float(sim), fi, float(tk), desde))
                if len(cand) >= 3:
                    sims = np.array([x[0] for x in cand])
                    best = max(cand)
                    if best[0] - float(np.median(sims)) >= 0.025:
                        _s, fi, tk, desde = best
                        elegido = (fi, max(desde, min(tk - dur * 0.3, dur_of(files[fi]) - dur - 0.1)))
                        por_ctx = True
        if elegido is None:                          # avanzar en orden: el primer sitio libre desde «por donde va»
            for fi in list(range(c, len(files))) + list(range(0, c)):   # (y lo que quedó sin usar atrás)
                src = libre(files[fi], dur)
                if src is not None:
                    elegido = (fi, src)
                    break
        if elegido is None:                          # lo que quedó sin usar (saltado por «lo que dices»)
            for fi, f in enumerate(files):
                h = _hueco_libre(f, dur_of(f), tramos, dur)
                if h is not None:
                    elegido = (fi, h)
                    break
        if elegido is None and dur_alt is not None and dur_alt < dur - 1e-6:
            for fi in list(range(c, len(files))) + list(range(0, c)):   # (alargada no cabe: lo máximo que quepa)
                f = files[fi]
                d_f = dur_of(f)
                src = libre(f, dur_alt)
                if src is not None:
                    hasta = d_f - 0.1
                else:
                    src = _hueco_libre(f, d_f, tramos, dur_alt)
                    hasta = min([a2 for a2, _b2 in tramos.get(f, []) if src is not None and a2 > src + 1e-6]
                                + [d_f - 0.1])
                if src is not None:
                    elegido, dur = (fi, src), max(dur_alt, min(dur, hasta - src))
                    break
        if (elegido is None and not any(dur_of(f) >= dur + 0.2 for f in files) and dur_alt is not None
                and dur_alt < dur - 1e-6 and any(dur_of(f) >= dur_alt + 0.2 for f in files)):
            dur = dur_alt                            # (alargada no cabe en ningún archivo: la de la frase)
        if elegido is None and any(dur_of(f) >= dur + 0.2 for f in files):
            for f in files:                          # se acabó TODO su material: vuelve a empezar
                usado.pop(f, None)
                tramos.pop(f, None)
            res["repeated"] += 1
            c = 0
            for fi in range(len(files)):
                src = libre(files[fi], dur)
                if src is not None:
                    elegido = (fi, src)
                    break
        if elegido is None:
            res["skipped"] += 1
            return
        fi, src = elegido
        items.append(Item(m["key"], m["t"], dur, files[fi], round(src, 3), kind, by_context=por_ctx,
                          folder=m["folder"]))
        usado[files[fi]] = max(usado.get(files[fi], 0.0), src + dur)
        tramos.setdefault(files[fi], []).append((src, src + dur))
        cursor[ck] = fi if fi >= c else c
        res["placed"] += 1
        res["by_context"] += int(por_ctx)

    eventos = []
    durs0 = list(durs)                            # (la de la frase, por si alargada ya no cabe)
    if fill and timeline_end:
        # (sin rendijas negras: una mención que acaba a menos de 1 s de lo siguiente se alarga hasta tocarlo)
        cand = [i for i, (m, kind, dur) in enumerate(zip(mentions, kinds, durs))
                if kind != "none" and pools.get(m["folder"]) is not None and dur >= DUR_MIN]
        bordes = sorted([a_ for a_, _b in (covered or [])] + [mentions[i]["t"] for i in cand] + [float(timeline_end)])
        for i in cand:
            fin = mentions[i]["t"] + durs[i]
            k = bisect.bisect_left(bordes, fin - 2e-3)
            if k < len(bordes) and 2e-3 < bordes[k] - fin < FILL_MIN and not any(
                    a_ < bordes[k] - 1e-6 and b_ > fin + 1e-6 for a_, b_ in (covered or [])):
                durs[i] = round(durs[i] + (bordes[k] - fin), 3)
        ocupado = list(covered or []) + [(mentions[i]["t"], mentions[i]["t"] + durs[i]) for i in cand]
        juego_en = _juego_en(mentions, pools)
        for a_, b_, folder in _tramos_relleno(mentions, pools, ocupado, float(timeline_end)):
            eventos.append((a_, 1, (a_, b_, folder)))
        reservado = set(cand)
    eventos += [(m["t"], 0, i) for i, m in enumerate(mentions)]
    eventos.sort(key=lambda e: (e[0], e[1]))
    for _t, tipo, dato in eventos:                # menciones y huecos EN ORDEN: el material va siempre hacia delante
        if cancel is not None and cancel():
            break
        if tipo == 0:
            antes = res["placed"]
            mencion(mentions[dato], kinds[dato], durs[dato], durs0[dato])
            if fill and timeline_end and res["placed"] == antes and dato in reservado:
                m = mentions[dato]                   # (no cupo: su sitio, con el gameplay del juego del que hablas,
                pool = pools.get(m["folder"])        #  y solo donde no se ve nada: nunca encima de un clip tuyo)
                folder = m["folder"] if pool is not None and pool.videos("gameplay") else juego_en(m["t"])
                if folder is not None:
                    for g0, g1 in gaps(list(covered or []), m["t"], m["t"] + durs[dato]):
                        _relleno(items, res, pools, dur_of, usado, cursor, tramos, g0, g1, folder)
        else:
            _relleno(items, res, pools, dur_of, usado, cursor, tramos, *dato)
    items.sort(key=lambda it: it.t)
    return items, res


def _juego_en(mentions, pools):
    """El juego del que hablas en cada momento (ver _tramos_relleno): función t → carpeta o None."""
    cambios = []
    for m in mentions:
        pool = pools.get(m["folder"])
        if pool is None:
            continue
        if pool.videos("gameplay"):
            cambios.append((m["t"], m["folder"]))
        elif pool.cinematic:
            cambios.append((m["t"], None))
    tiempos = [t for t, _f in cambios]
    primero = next((f for _t, f in cambios if f), None)

    def en(t):
        k = bisect.bisect_right(tiempos, t + 1e-6) - 1
        return primero if k < 0 else cambios[k][1]
    return en


def _hueco_libre(path, d_f, tramos, minimo):
    """El primer trozo de ese archivo sin usar de al menos «minimo» s (tras los logos del principio): desde dónde."""
    x, tope = min(3.0, 0.1 * d_f), d_f - 0.1
    for a, b in sorted(tramos.get(path, [])):
        if a - x >= minimo:
            return x
        x = max(x, b)
    return x if tope - x >= minimo else None


def _tramos_relleno(mentions, pools, ocupado, end) -> list[tuple]:
    """🧩 Los huecos sin imagen [(desde, hasta, carpeta del juego)]. El juego cambia en las menciones de una carpeta
    con gameplay (ese juego) o con videos pero sin gameplay (solo cinemáticas: ahí deja de rellenar, para no enseñar
    el juego de antes). Las de solo imágenes (una persona, una empresa) no cambian nada. Antes de la primera
    mención, el primer juego."""
    cambios = []
    for m in mentions:
        pool = pools.get(m["folder"])
        if pool is None:
            continue
        if pool.videos("gameplay"):
            cambios.append((m["t"], m["folder"]))
        elif pool.cinematic:
            cambios.append((m["t"], None))
    if not any(f for _t, f in cambios):
        return []
    tiempos = [t for t, _f in cambios]
    primero = next(f for _t, f in cambios if f)
    def en(t):
        k = bisect.bisect_right(tiempos, t + 1e-6) - 1
        return primero if k < 0 else cambios[k][1]
    out = []
    for g0, g1 in gaps(ocupado, 0.0, end):
        tramos_g = [[g0, None, en(g0)]]
        for t in tiempos:
            if g0 < t < g1 and en(t) != tramos_g[-1][2]:   # (solo donde el juego cambia de verdad)
                tramos_g[-1][1] = t
                tramos_g.append([t, None, en(t)])
        tramos_g[-1][1] = g1
        i = 0                                    # un trozo de menos de 1 s se junta con su vecino (el más largo manda)
        while len(tramos_g) > 1 and i < len(tramos_g):
            a, b, f = tramos_g[i]
            if b - a < FILL_MIN:
                j = i - 1 if i == len(tramos_g) - 1 else (i + 1 if i == 0 else
                                                          (i - 1 if tramos_g[i - 1][1] - tramos_g[i - 1][0] >=
                                                           tramos_g[i + 1][1] - tramos_g[i + 1][0] else i + 1))
                lo, hi = min(i, j), max(i, j)
                vecino = tramos_g[j]
                tramos_g[lo:hi + 1] = [[tramos_g[lo][0], tramos_g[hi][1], vecino[2]]]
                i = 0
                continue
            i += 1
        for a, b, folder in tramos_g:
            if folder is not None and b - a >= FILL_MIN:
                out.append((a, b, folder))
    return out


def _relleno(items, res, pools, dur_of, usado, cursor, tramos, a, b, folder):
    """🧩 Un hueco [a, b] con el gameplay de esa carpeta, desde «por donde va» y sin repetir (comparte lo usado con
    las menciones). Ningún trozo queda de menos de FILL_MIN (un resto corto se reparte con el trozo de antes)."""
    files = pools[folder].videos("gameplay")
    ck = (folder, "gameplay")
    t, vuelta = a, False

    def sin_resto_corto(largo, exigente):
        """Que lo que falte del hueco no quede en un trocito de menos de 1 s: se acorta este trozo; si no se puede,
        None (exigente: probar otro archivo) o el trozo tal cual (sin otra opción)."""
        resto = b - t - largo
        if 1e-3 < resto < FILL_MIN:
            if largo - (FILL_MIN - resto) >= FILL_MIN:
                return largo - (FILL_MIN - resto)
            return None if exigente else largo
        return largo

    def de_orden(exigente):
        c = cursor.get(ck, 0)
        for fi in list(range(c, len(files))) + list(range(0, c)):
            path = files[fi]
            d_f = dur_of(path)
            if d_f <= FILL_MIN + 0.2:
                continue
            src = usado.get(path)
            src = _s0(d_f, min(b - t, d_f)) if src is None else src
            largo = min(b - t, d_f - 0.1 - src)
            if largo < FILL_MIN:
                continue
            largo = sin_resto_corto(largo, exigente)
            if largo is not None:
                return fi, path, src, largo
        return None

    def de_saltado(exigente):                 # lo que quedó sin usar atrás (saltado por «lo que dices»)
        for f in files:
            d_f = dur_of(f)
            x = _hueco_libre(f, d_f, tramos, FILL_MIN) if d_f > FILL_MIN + 0.2 else None
            if x is None:
                continue
            fin_libre = min([a2 for a2, _b2 in tramos.get(f, []) if a2 > x + 1e-6] + [d_f - 0.1])
            largo = sin_resto_corto(min(b - t, fin_libre - x), exigente)
            if largo is not None:
                return None, f, x, largo
        return None

    while b - t >= FILL_MIN:
        puesto = False
        elegido = de_orden(True) or de_saltado(True) or de_orden(False) or de_saltado(False)
        if elegido is not None:
            fi, path, src, largo = elegido
            items.append(Item(f"relleno|{t:.2f}", t, round(largo, 3), path, round(src, 3), "gameplay",
                              fill=True, folder=folder))
            tramos.setdefault(path, []).append((src, src + largo))
            if fi is not None:                    # (en orden: «por donde va» avanza; lo saltado no lo mueve)
                usado[path] = max(usado.get(path, 0.0), src + largo)
                cursor[ck] = fi
            res["filled"] += 1
            res["filled_s"] += round(largo, 3)
            if vuelta:
                res["repeated"] += 1                  # (solo cuenta si de verdad volvió a empezar y cupo algo)
            t += largo
            puesto, vuelta = True, False
        if not puesto:
            if vuelta:
                break                                 # (ni volviendo a empezar cabe: se deja el hueco)
            for f in files:                           # se acabó su material: vuelve a empezar
                usado.pop(f, None)
                tramos.pop(f, None)
            vuelta = True
