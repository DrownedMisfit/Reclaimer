"""
🎙 «Edita desde tu voz», paso 2 «Pule tu voz»: las DUDAS de una narración, en una sola lista (23/11, plan
notas_claude/PLAN_EDITA_DESDE_TU_VOZ.md, secciones 1, 6 y 7). Sin Qt; no corta nada (eso lo hace el usuario con ✓).

analizar(words, …) -> [duda]; cada duda es un dict:
  {"clave", "tipo", "titulo", "detalle", "t" (segundo del archivo donde se ve), "quitar": [[a, b], …] (lo que se
   quita con ✓, en segundos del ARCHIVO), "marcada": bool (✓ propuesto), y para las tomas: "versiones": [{"a", "b",
   "estado": "completa"|"incompleta"|"traba", "ini", "fin", "texto"}], "elegida": índice, "juntar": {…} o None}
Tipos:
  tomas      la misma frase (o párrafo) dicha varias veces: seguidas, reformuladas, a medias, largas (30–60 s) o
             lejanas (varios minutos), por parecido de palabras, por cómo empiezan y por sentido (si hay modelo);
             retomar a mitad de frase («…y por eso, y por eso la consola») es una toma corta: solo se quita lo repetido;
             con guion pegado, gana la versión que más se le parece; si el principio de una y el final de otra son lo
             mejor, se ofrece juntarlas en el punto común.
  orden      una orden hablada («quita esto», «otra vez»…) suelta, con pausa antes y después: se quita la orden y lo
             que la orden señala (si vuelves a empezar algo, desde donde empezó la vez anterior; si no, la frase de
             antes). Ya va marcada.
  traba      palabra repetida o cortada, muletilla clara.
  frase      una frase que se quedó a medias dentro de una toma larga: solo esa frase.
  pausa      pausa larga (se deja una pausa natural).
  ruido      tos, risa, chasquido o respiración fuerte (tipo propio, cada uno con su nombre).
  intencion  ¿repetición a propósito? (no va marcada).
Lo reutiliza todo de ai/repetition_detection (frases, puntuación de tomas, palabras repetidas, muletillas) y de
ai/silence_detection (niveles, silencios, ruidos).

ajustar_corte(a, b, words, samples): un corte que no se come palabras (nunca dentro de una palabra que se queda; los
finales suaves con «s» enteros; al punto más silencioso cerca).
comprobar(words_editado): lo que quede (tomas, trabas, órdenes) tras editar, para el aviso final con su minuto.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import numpy as np

from . import repetition_detection as rep

ORDENES = ["esto no", "quita esto", "quita eso", "borra esto", "borra eso", "otra vez", "desde aquí", "corta",
           "corta eso", "repito", "espera", "no no"]
PAUSA_ORDEN = 0.5          # una orden va suelta: ≥ 0,5 s de pausa antes y después
VENTANA_TOMAS = 360.0      # se buscan tomas hasta 6 min atrás
PAUSA_LARGA = 1.6          # pausas más largas que esto son una duda (se deja PAUSA_QUEDA)
PAUSA_QUEDA = 0.35
PALABRAS_CORTE = {"otra", "vez", "repito", "corta", "espera"}


def _n(w: str) -> str:
    return rep._norm(w)


def _toks(words, a, b) -> list[str]:
    return [t for t in (_n(w[2]) for w in words[a:b]) if t]


def _contenido(toks) -> set[str]:
    return {t for t in toks if len(t) >= 4 and t not in rep.STOP}


def _texto(words, a, b, n: int = 0) -> str:
    ws = [w[2] for w in words[a:b]]
    if n and len(ws) > n:
        ws = ws[:n] + ["…"]
    return " ".join(ws)


def _ini_fin(words, a, b, n: int = 5) -> tuple[str, str]:
    ws = [w[2] for w in words[a:b]]
    if len(ws) <= 2 * n:
        return " ".join(ws), ""
    return " ".join(ws[:n]) + " …", "… " + " ".join(ws[-n:])


def _gap(words, i) -> float:
    return words[i + 1][0] - words[i][1] if i + 1 < len(words) else 9.0


def _gap_antes(words, i) -> float:
    return words[i][0] - words[i - 1][1] if i > 0 else 9.0


# ------------------------------------------------------------------ órdenes habladas
def _ordenes_toks(ordenes) -> list[list[str]]:
    out = []
    for o in ordenes or ORDENES:
        t = [x for x in (_n(p) for p in str(o).split()) if x]
        if t:
            out.append(t)
    return sorted(out, key=len, reverse=True)


def _buscar_ordenes(words, toks, ordenes) -> list[tuple[int, int, str]]:
    """(inicio, fin, orden) de cada orden suelta: pausa ≥ PAUSA_ORDEN antes y después y nada más en medio."""
    out = []
    i = 0
    lst = _ordenes_toks(ordenes)
    while i < len(words):
        hit = None
        for o in lst:
            if toks[i:i + len(o)] == o:
                j = i + len(o)
                if _gap_antes(words, i) >= PAUSA_ORDEN and _gap(words, j - 1) >= PAUSA_ORDEN:
                    hit = (i, j, " ".join(o))
                    break
        if hit:
            out.append(hit)
            i = hit[1]
        else:
            i += 1
    return out


def _parecido_inicio(A: list[str], B: list[str]) -> float:
    """Qué tanto empieza B como A (las primeras 6 palabras), 0–1."""
    A, B = A[:6], B[:6]
    if len(A) < 2 or len(B) < 2:
        return 0.0
    n = 0
    while n < min(len(A), len(B)) and A[n] == B[n]:
        n += 1
    return max(n / min(len(A), len(B), 4), SequenceMatcher(None, A, B).ratio())


def _duda_orden(words, toks, frases, i0, i1, orden) -> dict:
    """Qué quita una orden: si después vuelves a empezar algo, desde donde empezó la vez anterior (aunque sean
    minutos y cambie alguna palabra); si no, la frase de antes (hasta la última pausa)."""
    sig = [t for t in toks[i1:i1 + 8] if t]
    desde = None
    if len(sig) >= 2:
        mejor = 0.0
        t_orden = words[i0][0]
        for a, b in frases:
            if b > i0 or words[a][0] < t_orden - VENTANA_TOMAS:
                continue
            s = _parecido_inicio(_toks(words, a, b), sig)
            if s >= 0.66 and s >= mejor:                 # (a igual parecido, la más cercana: la última vez)
                mejor, desde = s, a
    como = "vuelves a empezar: desde donde empezó la vez anterior"
    if desde is None:
        k = i0 - 1
        while k > 0 and _gap(words, k - 1) < PAUSA_ORDEN and not words[k - 1][2].rstrip().endswith((".", "?", "!")):
            k -= 1
        desde = max(0, k)
        como = "la frase de antes"
    a = words[desde][0] - 0.03
    b = words[i1 - 1][1] + 0.05
    return {"clave": f"orden:{round(words[i0][0], 2)}", "tipo": "orden", "titulo": f"Dijiste «{orden}»",
            "detalle": f"Se quita la orden y {como}: «{_texto(words, desde, i0, 12)}»",
            "t": words[i0][0], "quitar": [[a, b]], "marcada": True, "orden": orden,
            "palabras": [desde, i1]}


# ------------------------------------------------------------------ tomas
def _parrafos(words, frases, pausa: float = 1.2) -> list[tuple[int, int]]:
    """Frases juntas hasta una pausa larga (para las tomas de 30–60 s o de un párrafo entero)."""
    out, ini = [], None
    for k, (a, b) in enumerate(frases):
        if ini is None:
            ini = a
        if k + 1 == len(frases) or words[frases[k + 1][0]][0] - words[b - 1][1] >= pausa:
            out.append((ini, b))
            ini = None
    return out


def _estado(words, a, b, otras: list[list[str]]) -> str:
    toks = _toks(words, a, b)
    ultimo = words[b - 1][2].rstrip()
    sig = words[b][2].lstrip("¿¡\"«(") if b < len(words) else ""
    if ultimo.endswith(("...", "…", "-")) or (toks and any(len(toks) + 1 < len(o) and o[:len(toks)] == toks
                                                            for o in otras)):
        return "incompleta"
    if not ultimo.endswith((".", "?", "!", ",")) and _gap(words, b - 1) < 0.6 and sig[:1].isupper():
        return "incompleta"
    for i in range(len(toks) - 1):
        if toks[i] == toks[i + 1] or toks[i] in rep.PURE_FILLERS or \
                (len(toks[i]) >= 2 and toks[i + 1].startswith(toks[i]) and len(toks[i]) < len(toks[i + 1])):
            return "traba"
    if toks and toks[-1] in rep.PURE_FILLERS:
        return "traba"
    return "completa"


def _sim(A: list[str], B: list[str]) -> float:
    if not A or not B:
        return 0.0
    r = SequenceMatcher(None, A, B, autojunk=False).ratio()
    ca, cb = _contenido(A), _contenido(B)
    j = len(ca & cb) / max(1, len(ca | cb)) if ca and cb else 0.0
    return max(r, j)


def _es_toma(A, B, sem: float | None = None) -> bool:
    if len(A) < 3 and len(B) < 3:
        return False
    if len(A) < len(B) and B[:len(A)] == A and len(A) >= 2:
        return True                                     # la empezaste y la volviste a empezar
    s = _sim(A, B)
    ini = _parecido_inicio(A, B)
    if s >= 0.62 or (ini >= 0.75 and s >= 0.4):
        return True
    return sem is not None and sem >= 0.8 and s >= 0.25


def _grupos(words, unidades, encode=None, ventana: float = VENTANA_TOMAS) -> list[list[int]]:
    """Grupos de unidades (frases o párrafos) que son tomas de lo mismo, hasta «ventana» segundos atrás."""
    toks = [_toks(words, a, b) for a, b in unidades]
    vec = None
    if encode is not None and len(unidades) >= 2:
        try:
            vec = np.asarray(encode([_texto(words, a, b) for a, b in unidades]), np.float32)
            if vec.ndim != 2 or vec.shape[1] < 2:
                vec = None
        except Exception:  # noqa: BLE001 - sin modelo de frases: solo palabras
            vec = None
    padre = list(range(len(unidades)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x
    for j in range(len(unidades)):
        tj = words[unidades[j][0]][0]
        for i in range(j - 1, -1, -1):
            if tj - words[unidades[i][1] - 1][1] > ventana:
                break
            sem = float(vec[i] @ vec[j]) if vec is not None else None
            if _es_toma(toks[i], toks[j], sem):
                padre[raiz(j)] = raiz(i)
                break
    g: dict[int, list[int]] = {}
    for k in range(len(unidades)):
        g.setdefault(raiz(k), []).append(k)
    return [sorted(v) for v in g.values() if len(v) >= 2]


def _con_continuacion(words, unidades, grupo) -> list:
    """Cada versión que acaba en coma sigue con el resto de su frase («…demasiado lento, sobre todo al principio»):
    las unidades del grupo se alargan hasta ahí (se modifica «unidades» en su sitio, sin solaparse con otra versión)."""
    en = set(grupo)
    for x in grupo:
        a, b = unidades[x]
        y = x
        while (y + 1 < len(unidades) and y + 1 not in en and y - x < 2 and words[b - 1][2].rstrip().endswith(",")
               and unidades[y + 1][0] == b and _gap(words, b - 1) < 0.6):
            y += 1
            b = unidades[y][1]
        unidades[x] = (a, b)
    return grupo


def _intencion(words, unidades, grupo) -> str | None:
    """Repetición a propósito («y otra vez, y otra vez»): "si" = seguidas, cortas, iguales y sin pausa (no es duda);
    "duda" = la segunda sigue tras repetir un trozo corto con una palabra de énfasis («y otra vez, y otra vez salta»):
    se avisa «¿repetición a propósito?» sin marcar. None = es una toma de verdad (p. ej. retomar a mitad de frase)."""
    if len(grupo) != 2 or grupo[1] != grupo[0] + 1:
        return None
    (a0, a1), (b0, b1) = unidades[grupo[0]], unidades[grupo[1]]
    A, B = _toks(words, a0, a1), _toks(words, b0, b1)
    seguidas = words[b0][0] - words[a1 - 1][1] < 0.35
    if A == B and len(A) <= 4 and seguidas:
        return "si"
    if seguidas and len(A) <= 4 and B[:len(A)] == A and set(A) & rep.EMPHASIS - {"no", "si", "ya"}:
        return "duda"
    return None


def _puntos_comunes(A: list[str], B: list[str]) -> tuple[int, int] | None:
    """El punto común más largo (≥ 2 palabras) para juntar dos versiones: (índice en A, índice en B)."""
    m = SequenceMatcher(None, A, B, autojunk=False).find_longest_match(0, len(A), 0, len(B))
    return (m.a, m.b) if m.size >= 2 else None


def _duda_tomas(words, unidades, grupo, guion_toks=None) -> dict:
    vs = []
    toks = [_toks(words, *unidades[x]) for x in grupo]
    for k, x in enumerate(grupo):
        a, b = unidades[x]
        otras = [t for kk, t in enumerate(toks) if kk != k]
        ini, fin = _ini_fin(words, a, b)
        vs.append({"a": round(words[a][0] - 0.02, 3), "b": round(words[b - 1][1] + 0.05, 3),
                   "estado": _estado(words, a, b, otras), "ini": ini, "fin": fin,
                   "texto": _texto(words, a, b), "i": [a, b]})
    # por defecto: la última completa y sin trabas (con guion: la que más se le parece)
    elegida = None
    if guion_toks:
        elegida = max(range(len(vs)), key=lambda k: (SequenceMatcher(None, toks[k], guion_toks,
                                                                     autojunk=False).find_longest_match(
            0, len(toks[k]), 0, len(guion_toks)).size / max(1, len(toks[k])), k))
    if elegida is None:
        buenas = [k for k, v in enumerate(vs) if v["estado"] == "completa"]
        elegida = buenas[-1] if buenas else len(vs) - 1
    for k, v in enumerate(vs):
        v["distancia"] = round(vs[elegida]["a"] - v["a"], 1)
    juntar = None
    if len(vs) == 2:                                   # lo mejor en dos versiones: principio de una y final de otra
        p, q = (0, 1)
        if vs[p]["estado"] in ("incompleta", "traba") and vs[q]["estado"] == "traba":
            pc = _puntos_comunes(toks[p], toks[q])
            if pc is not None and 0 < pc[0] and 0 < pc[1]:
                wa = [i for i in range(*vs[p]["i"]) if _n(words[i][2])]
                wb = [i for i in range(*vs[q]["i"]) if _n(words[i][2])]
                if pc[0] < len(wa) and pc[1] < len(wb):
                    corte_a = words[wa[pc[0]]][0] - 0.02        # se queda A hasta aquí…
                    corte_b = words[wb[pc[1]]][0] - 0.02        # …y B desde aquí
                    juntar = {"corte_a": round(corte_a, 3), "corte_b": round(corte_b, 3),
                              "texto": _texto(words, vs[p]["i"][0], wa[pc[0]]) + " + " +
                                       _texto(words, wb[pc[1]], vs[q]["i"][1])}
    largas = any(v["b"] - v["a"] >= 25 for v in vs)
    lejos = max(v["a"] for v in vs) - min(v["a"] for v in vs) >= 60
    corta = len(vs) == 2 and vs[0]["estado"] == "incompleta" and vs[1]["a"] - vs[0]["b"] < 1.5 and \
        len(toks[0]) <= 6
    titulo = ("Retomaste a mitad de frase" if corta else
              f"Tomas de este párrafo ({len(vs)})" if largas else f"Tomas de esta frase ({len(vs)})")
    d = {"clave": "tomas:" + ",".join(str(round(v["a"], 1)) for v in vs), "tipo": "tomas", "titulo": titulo,
         "detalle": ("Varias versiones separadas por minutos. " if lejos else "") +
                    "Se queda la que eliges; las demás se quitan.",
         "t": vs[elegida]["a"], "versiones": vs, "elegida": elegida, "juntar": juntar, "marcada": True}
    d["quitar"] = quitar_de(d)
    return d


def quitar_de(d: dict, elegida: int | None = None) -> list[list[float]]:
    """Lo que se quita de una duda con ✓ (tomas: todas menos la elegida; -1 = juntar las dos)."""
    if d.get("tipo") != "tomas":
        return [list(x) for x in d.get("quitar") or []]
    e = d.get("elegida", 0) if elegida is None else elegida
    vs = d["versiones"]
    if e == -1 and d.get("juntar"):
        j = d["juntar"]
        out = [[j["corte_a"], vs[0]["b"]], [vs[1]["a"], j["corte_b"]]]
        out += [[v["a"], v["b"]] for v in vs[2:]]
        return out
    return [[v["a"], v["b"]] for k, v in enumerate(vs) if k != e]


# ------------------------------------------------------------------ trabas, frases a medias, pausas, ruidos
def _trabas(words, ocupado) -> list[dict]:
    out = []
    for d in rep.find_repeated_words(words):
        if _ocupa(ocupado, d["start"], d["end"]):
            continue
        emph = not (d.get("data") or {}).get("auto", True)
        out.append({"clave": f"traba:{round(d['start'], 2)}", "tipo": "intencion" if emph else "traba",
                    "titulo": "¿Repetición a propósito?" if emph else d["label"].split(":")[0],
                    "detalle": d["label"], "t": d["start"], "quitar": [[d["start"], d["end"]]],
                    "marcada": not emph})
    for d in rep.find_fillers(words):
        if d.get("label", "").startswith("Posible") or _ocupa(ocupado, d["start"], d["end"]):
            continue
        out.append({"clave": f"traba:{round(d['start'], 2)}", "tipo": "traba", "titulo": "Muletilla",
                    "detalle": d.get("label", ""), "t": d["start"], "quitar": [[d["start"], d["end"]]],
                    "marcada": True})
    return out


def _frases_a_medias(words, frases, ocupado) -> list[dict]:
    """Toma larga con una sola frase mala: una frase que acaba en «…» / «-» dentro de un párrafo y después sigue
    otra cosa → solo esa frase."""
    out = []
    for k, (a, b) in enumerate(frases[:-1]):
        ult = words[b - 1][2].rstrip()
        if not ult.endswith(("...", "…", "-")) or b - a < 3:
            continue
        ta, tb = words[a][0] - 0.02, words[b - 1][1] + 0.05
        if _ocupa(ocupado, ta, tb):
            continue
        out.append({"clave": f"frase:{round(ta, 2)}", "tipo": "frase", "titulo": "Frase a medias",
                    "detalle": f"«{_texto(words, a, b, 12)}» se quedó a medias: se quita solo esa frase.",
                    "t": ta, "quitar": [[ta, tb]], "marcada": True})
    return out


def _pausas(words, levels=None, sr=None, ocupado=()) -> list[dict]:
    out = []
    if levels is not None:
        from . import silence_detection as sil
        tramos = sil.find_silences(levels, PAUSA_LARGA)
    else:
        tramos = [(words[i][1], words[i + 1][0]) for i in range(len(words) - 1)
                  if words[i + 1][0] - words[i][1] >= PAUSA_LARGA]
    for s, e in tramos:
        a, b = s + PAUSA_QUEDA / 2, e - PAUSA_QUEDA / 2
        if b - a < 0.3 or _ocupa(ocupado, a, b) or any(a < w[0] and w[1] < b for w in words):
            continue
        out.append({"clave": f"pausa:{round(s, 2)}", "tipo": "pausa", "titulo": f"Pausa de {e - s:.1f} s",
                    "detalle": f"Se deja una pausa natural de {PAUSA_QUEDA:.2f} s.", "t": s,
                    "quitar": [[round(a, 3), round(b, 3)]], "marcada": True})
    return out


def _tipo_ruido(seg: np.ndarray, sr: int) -> str:
    """Tos, risa, chasquido o respiración, por la forma del sonido (duración, golpes y lo «ruidoso» que es)."""
    dur = len(seg) / sr
    if dur < 0.13:
        return "Chasquido"
    hop = max(1, int(0.02 * sr))
    env = np.array([float(np.sqrt(np.mean(seg[i:i + hop] ** 2) + 1e-12)) for i in range(0, len(seg) - hop, hop)])
    if len(env) < 3:
        return "Chasquido"
    db = 20 * np.log10(env + 1e-9)
    picos = int(np.sum((db[1:-1] > db[:-2]) & (db[1:-1] > db[2:]) & (db[1:-1] > db.max() - 8)))
    zcr = float(np.mean(np.abs(np.diff(np.sign(seg))) > 0))
    if picos >= 3 and dur >= 0.5:
        return "Risa"
    if zcr > 0.25 and db.max() - db.mean() < 10:
        return "Respiración"
    return "Tos"


def _ruidos(words, levels, samples, sr, ocupado) -> list[dict]:
    from . import silence_detection as sil
    out = []
    for a, b in sil.find_noises(levels, words):
        if _ocupa(ocupado, a, b):
            continue
        tipo = _tipo_ruido(samples[int(a * sr):int(b * sr)], sr) if samples is not None else "Ruido"
        out.append({"clave": f"ruido:{round(a, 2)}", "tipo": "ruido", "titulo": tipo,
                    "detalle": f"{tipo} entre palabras ({b - a:.1f} s). Escúchalo antes de quitarlo.", "t": a,
                    "quitar": [[round(a, 3), round(b, 3)]], "marcada": tipo != "Respiración", "ruido": tipo})
    return out


def _ocupa(ocupado, a, b) -> bool:
    return any(a < y - 0.02 and b > x + 0.02 for x, y in ocupado)


# ------------------------------------------------------------------ todo junto
def analizar(words: list, samples: np.ndarray | None = None, sr: int = 16000, guion: str = "",
             ordenes=None, encode=None, hasta: float | None = None) -> list[dict]:
    """Las dudas de la narración (tiempos del archivo), ordenadas por minuto. hasta: solo hasta ahí (la
    transcripción por trozos: la última frase puede estar a medias y se deja para el trozo siguiente)."""
    words = [w for w in words or [] if len(w) >= 3]
    if hasta is not None:
        words = [w for w in words if w[1] <= hasta]
    if len(words) < 2:
        return []
    toks = [_n(w[2]) for w in words]
    frases = rep.split_phrases(words, restarts=True)
    out: list[dict] = []
    ocupado: list[tuple[float, float]] = []
    # 1) órdenes habladas (y lo que señalan)
    ords = _buscar_ordenes(words, toks, ordenes)
    usadas = set()
    for i0, i1, o in ords:
        d = _duda_orden(words, toks, frases, i0, i1, o)
        out.append(d)
        ocupado += [tuple(x) for x in d["quitar"]]
        usadas.update(range(d["palabras"][0], i1))
    # 2) tomas: frases y párrafos (sin las órdenes ni lo que ya quitan)
    libres = [(a, b) for a, b in frases if not usadas.intersection(range(a, b))]
    guion_toks = [t for t in (_n(x) for x in (guion or "").split()) if t]
    en_grupo: set[int] = set()                         # (palabras que ya son de alguna toma)
    for unidades in (_parrafos(words, libres), libres):
        largos = unidades is not libres
        for g in _grupos(words, unidades, encode if not largos else None):
            if largos and all(words[unidades[x][1] - 1][1] - words[unidades[x][0]][0] < 12 for x in g):
                continue                                 # (párrafos cortos: ya salen como frases)
            g = _con_continuacion(words, unidades, g)
            idx = {i for x in g for i in range(unidades[x][0], unidades[x][1])}
            inten = _intencion(words, unidades, g)
            if idx & en_grupo or inten == "si":
                continue
            d = _duda_tomas(words, unidades, g, guion_toks)
            if inten == "duda":
                d.update(tipo="intencion", titulo="¿Repetición a propósito?", marcada=False,
                         detalle="Parece a propósito (énfasis). ✓ quita la primera; ✗ la deja.")
            out.append(d)
            en_grupo |= idx
            ocupado += [(v["a"], v["b"]) for v in d["versiones"]]
    # 3) frases a medias, trabas, pausas, ruidos
    out += _frases_a_medias(words, libres, ocupado)
    ocupado += [tuple(x) for d in out if d["tipo"] == "frase" for x in d["quitar"]]
    out += _trabas(words, ocupado)
    levels = None
    if samples is not None and len(samples) > sr:
        from . import silence_detection as sil
        levels = sil.analyze_levels(samples, sr)
    out += _pausas(words, levels, sr, ocupado)
    if levels is not None:
        out += _ruidos(words, levels, samples, sr, ocupado)
    out.sort(key=lambda d: d["t"])
    return out


# ------------------------------------------------------------------ cortes que no se comen palabras
SUAVES = ("s", "z", "x", "ce", "ces", "ses")


def ajustar_corte(a: float, b: float, words: list, samples: np.ndarray | None = None, sr: int = 16000,
                  margen: float = 0.03) -> tuple[float, float] | None:
    """[a, b] sin comerse palabras: si cae dentro de una palabra que se queda (la mayor parte fuera), se aparta de
    ella; un final suave en «s» se deja entero (+60 ms); y cada borde va al punto más silencioso en ±40 ms."""
    for w in words:
        w0, w1 = float(w[0]), float(w[1])
        if w0 < a < w1:
            if (w1 - a) < (a - w0):                  # casi toda la palabra se queda: el corte, después de ella
                a = w1 + margen
            else:
                a = w0 - margen
        if w0 < b < w1:
            if (b - w0) < (w1 - b):
                b = w0 - margen
            else:
                b = w1 + margen
    prev = [w for w in words if float(w[1]) <= a + 1e-3]
    if prev and _n(prev[-1][2]).endswith(SUAVES) and a - float(prev[-1][1]) < 0.06:
        a = float(prev[-1][1]) + 0.06
    if samples is not None and len(samples):
        a = _silencio_cerca(samples, sr, a)
        b = _silencio_cerca(samples, sr, b)
    return (round(a, 3), round(b, 3)) if b - a > 0.02 else None


def _silencio_cerca(samples, sr, t, r: float = 0.04) -> float:
    i0, i1 = max(0, int((t - r) * sr)), min(len(samples), int((t + r) * sr))
    if i1 - i0 < 64:
        return t
    hop = max(1, int(0.005 * sr))
    seg = samples[i0:i1]
    e = [float(np.mean(seg[k:k + hop] ** 2)) for k in range(0, len(seg) - hop, hop)]
    if not e:
        return t
    k = int(np.argmin(e))
    return (i0 + k * hop + hop // 2) / sr


# ------------------------------------------------------------------ comprobación final
def comprobar(words: list, ordenes=None) -> list[dict]:
    """Lo que queda tras editar (tiempos de lo editado): tomas seguidas, trabas y órdenes habladas."""
    if len(words) < 2:
        return []
    out = [d for d in analizar(words, ordenes=ordenes) if d["tipo"] in ("tomas", "orden", "traba", "frase")]
    for d in out:
        d["titulo"] = "Queda: " + d["titulo"][0].lower() + d["titulo"][1:]
        if d.get("versiones"):                       # (el aviso, donde empieza: en la primera versión)
            d["t"] = min(v["a"] for v in d["versiones"])
    return out


def minuto(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60}:{t % 60:02d}"


def es_orden_valida(texto: str) -> bool:
    return bool(re.sub(r"\s+", "", texto or ""))

# ------------------------------------------------------------------ verbatim solo donde hay dudas
def regiones_dudosas(dudas: list, dur: float, margen: float = 1.0, tope: float = 0.3) -> list[list[float]]:
    """Los tramos (con margen) de las tomas, trabas y frases a medias: ahí Whisper se suele comer repeticiones. Como
    mucho «tope» del audio (si no, no compensa frente a escuchar todo)."""
    tr = []
    for d in dudas:
        if d.get("tipo") in ("tomas", "traba", "frase", "intencion"):
            xs = [(v["a"], v["b"]) for v in d.get("versiones") or []] or [tuple(x) for x in d.get("quitar") or []]
            tr += [[max(0.0, a - margen), min(dur, b + margen)] for a, b in xs]
    tr.sort()
    out = []
    for a, b in tr:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    total = sum(b - a for a, b in out)
    return out if out and total <= tope * max(dur, 1.0) else out[: max(1, int(len(out) * tope * dur / max(total, 1e-6)))]


def verbatim_en_dudas(samples: np.ndarray, sr: int, words: list, dudas: list, model_key: str = "equilibrado",
                      language: str = "es", cancelled=None) -> list | None:
    """Transcripción palabra por palabra (ai/verbatim) SOLO en los tramos dudosos; devuelve las palabras con lo
    recuperado metido en su sitio, o None si no hay oído literal o no cambió nada."""
    from . import verbatim
    if not verbatim.available()[0]:
        return None
    dur = len(samples) / sr
    nuevas = [list(w) for w in words]
    cambio = False
    try:
        for a, b in regiones_dudosas(dudas, dur):
            if cancelled is not None and cancelled():
                break
            dentro = [[w[0] - a, w[1] - a] + list(w[2:]) for w in nuevas if a <= (w[0] + w[1]) / 2 < b]
            got = verbatim.recover(samples[int(a * sr):int(b * sr)], {"words": dentro, "segments": []}, model_key,
                                   language, None, cancelled)
            if not got.get("recovered"):
                continue
            fuera = [w for w in nuevas if not a <= (w[0] + w[1]) / 2 < b]
            nuevas = sorted(fuera + [[round(w[0] + a, 3), round(w[1] + a, 3)] + list(w[2:]) for w in got["words"]],
                            key=lambda w: w[0])
            cambio = True
    finally:
        try:
            from . import align
            align.unload()
        except Exception:  # noqa: BLE001
            pass
    return nuevas if cambio else None
