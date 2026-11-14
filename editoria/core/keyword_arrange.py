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

Clave de una mención: «palabra|media_id|segundo del archivo» (no cambia al mover o recortar la narración).
"""
from __future__ import annotations

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
         timeline_end: float | None = None, context: bool = True, vecs_of=None, qvecs=None, cancel=None
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
    cursor: dict[tuple[str, str], int] = {}          # (palabra, tipo) → por qué archivo va la historia
    img_n: dict[str, int] = {}
    items: list[Item] = []
    res = {"placed": 0, "skipped": 0, "repeated": 0, "by_context": 0}

    def libre(path, dur) -> float | None:
        """Desde dónde cabe un trozo de dur en ese archivo (None = no cabe)."""
        d_f = dur_of(path)
        if d_f < dur + 0.2:
            return None
        src = usado.get(path)
        src = _s0(d_f, dur) if src is None else src
        return src if src + dur <= d_f - 0.1 + 1e-6 else None

    for m, kind, dur in zip(mentions, kinds, durs):
        if cancel is not None and cancel():
            break
        pool = pools.get(m["folder"])
        if kind == "none" or pool is None:
            continue
        if dur < DUR_MIN:
            res["skipped"] += 1
            continue
        if kind == "image":
            n = img_n.get(m["folder"], 0)
            items.append(Item(m["key"], m["t"], dur, pool.image[n % len(pool.image)], 0.0, kind))
            res["repeated"] += int(n == len(pool.image))
            img_n[m["folder"]] = n + 1
            res["placed"] += 1
            continue
        files = pool.videos(kind)
        if not files:
            res["skipped"] += 1
            continue
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
        if elegido is None and any(dur_of(f) >= dur + 0.2 for f in files):
            for f in files:                          # se acabó TODO su material: vuelve a empezar
                usado.pop(f, None)
            res["repeated"] += 1
            c = 0
            for fi in range(len(files)):
                src = libre(files[fi], dur)
                if src is not None:
                    elegido = (fi, src)
                    break
        if elegido is None:
            res["skipped"] += 1
            continue
        fi, src = elegido
        items.append(Item(m["key"], m["t"], dur, files[fi], round(src, 3), kind, by_context=por_ctx))
        usado[files[fi]] = src + dur
        cursor[ck] = fi if fi >= c else c
        res["placed"] += 1
        res["by_context"] += int(por_ctx)
    return items, res
