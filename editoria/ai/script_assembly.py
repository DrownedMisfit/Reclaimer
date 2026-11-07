"""
📜 Montaje desde el guion (como AI IntelliScript de DaVinci Resolve 20). Sin Qt.

El guion tiene UNA ORACIÓN POR LÍNEA. La narración se grabó (a veces repitiendo frases si te equivocas).

  parse_script(text) -> [{"i", "text", "tags": [{"kind": "clip"|"img"|"music"|"nota", "value"}]}]
  align_script(lines, words) -> (por_linea, improvisados)
      por_linea[k] = lista de tomas de la línea k (None si la línea no tiene texto); cada toma:
        {"a_idx", "b_idx" (palabras de la transcripción, ambas incluidas), "start", "end" (segundos del archivo),
         "score" (parecido 0–1), "complete" (¿dice la frase entera?), "text"}
      improvisados = tramos que dijiste y no estaban en el guion (≥ 2 s): {"a_idx", "b_idx", "start", "end", "text"}
  choose_takes(aligned) -> [{"i", "chosen": toma|None, "discarded": [tomas], "missing": bool, "empty": bool}]
  cut_span(words, a_idx, b_idx) -> (inicio, fin) del tramo que se quita de una toma descartada
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

MIN_SCORE = 0.5        # una toma cuenta si se parece a la línea al menos esto
GOOD_SCORE = 0.75      # «buena» toma: parecido alto y frase entera
COMPLETE = 0.85        # fracción de las palabras de la línea que aparece en la toma
BREAK = 1.2            # una pausa mayor de esto corta una toma (no se mezcla con la de después)
IMPRO_GAP = 1.0        # palabras improvisadas seguidas separadas menos de esto forman un tramo
IMPRO_MIN = 2.0        # un tramo improvisado dura al menos esto

TAG_RE = re.compile(r"\[([^\[\]\n]+)\]")
_KINDS = {"clip": "clip", "img": "img", "imagen": "img", "musica": "music", "music": "music", "nota": "nota"}


def fold(text: str) -> str:
    """Minúsculas y sin tildes."""
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _tok(word: str) -> str:
    return "".join(ch for ch in fold(word) if ch.isalnum())


def parse_script(text: str) -> list[dict]:
    """Una oración por línea. Las etiquetas [CLIP: x], [IMG: x], [MÚSICA: x], [NOTA: x] van entre corchetes en
    cualquier parte de la línea; se quitan del texto a alinear. Las líneas vacías se ignoran."""
    out = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        tags = []
        for m in TAG_RE.finditer(line):
            body = m.group(1).strip()
            k, sep, v = body.partition(":")
            kind = _KINDS.get(fold(k).strip()) if sep else None
            if kind is None:
                kind, value = "nota", body
            else:
                value = v.strip()
            tags.append({"kind": kind, "value": value})
        clean = " ".join(TAG_RE.sub(" ", line).split())
        out.append({"i": len(out), "text": clean, "tags": tags})
    return out


def _index(words: list) -> tuple[list[str], list[int]]:
    """Solo las palabras con letras: (tokens normalizados, índice de cada token en words)."""
    toks, idx = [], []
    for i, w in enumerate(words):
        t = _tok(w[2])
        if t:
            toks.append(t)
            idx.append(i)
    return toks, idx


def _limits(words: list, idx: list[int]) -> list[int]:
    """Para cada token, hasta qué token puede llegar una toma sin cruzar una pausa larga."""
    m = len(idx)
    lim = list(range(m))
    for t in range(m - 2, -1, -1):
        gap = words[idx[t + 1]][0] - words[idx[t]][1]
        lim[t] = t if gap > BREAK else lim[t + 1]
    return lim


def _candidates(k: int, L: list[str], toks: list[str], lim: list[int], used: list[bool]) -> list[tuple]:
    """Tomas posibles de una línea: (parecido, inicio_token, fin_token_excl, palabras_que_coinciden, línea)."""
    n = len(L)
    Ls = set(L)
    m = len(toks)
    need = min(2, n)
    out = []
    for s in range(m):
        if used[s] or toks[s] not in Ls:
            continue
        if sum(1 for t in toks[s:s + n + 3] if t in Ls) < need:
            continue
        best = None
        hi = min(s + n + 3, m, lim[s] + 1)
        lo = s + 1
        for e in range(s + 1, hi + 1):
            if used[e - 1]:
                break
            if e < lo:
                continue
            W = toks[s:e]
            M = sum(b.size for b in SequenceMatcher(None, L, W, autojunk=False).get_matching_blocks())
            ratio = 2.0 * M / (n + len(W))
            if best is None or ratio > best[0] + 1e-9:
                best = (ratio, e, M)
        if best is None:
            continue
        ratio, e, M = best
        if ratio >= MIN_SCORE and M >= need:
            out.append((ratio, s, e, M, k))
    return out


def align_script(lines: list[dict], words: list) -> tuple[list, list]:
    """Busca cada línea del guion en la transcripción (tolera tropiezos, repeticiones y palabras de más). Cada zona
    de la narración se asigna a la línea que mejor se parece; lo que no se asigna y dura ≥ 2 s es improvisado."""
    toks, idx = _index(words)
    lim = _limits(words, idx)
    used = [False] * len(toks)
    Ls = [None if not ln.get("text") else [t for t in (_tok(x) for x in ln["text"].split()) if t] for ln in lines]
    Ls = [L if L else None for L in Ls]

    cands = []
    for k, L in enumerate(Ls):
        if L:
            cands += _candidates(k, L, toks, lim, used)
    # Gana la coincidencia más parecida; lo que se pise con otra ya aceptada no cuenta
    cands.sort(key=lambda c: (-c[0], c[1]))
    occ = [False] * len(toks)
    accepted = []
    for ratio, s, e, M, k in cands:
        if any(occ[t] for t in range(s, e)):
            continue
        for t in range(s, e):
            occ[t] = True
        accepted.append((ratio, s, e, M, k))

    aligned: list = [None if L is None else [] for L in Ls]
    for ratio, s, e, M, k in accepted:
        n = len(Ls[k])
        a, b = idx[s], idx[e - 1]
        aligned[k].append({"a_idx": a, "b_idx": b, "start": float(words[a][0]), "end": float(words[b][1]),
                           "score": round(ratio, 3), "complete": M / n >= COMPLETE,
                           "text": " ".join(w[2] for w in words[a:b + 1])})
    for takes in aligned:
        if takes:
            takes.sort(key=lambda t: t["start"])

    covered = [False] * len(words)
    for takes in aligned:
        for tk in takes or []:
            for i in range(tk["a_idx"], tk["b_idx"] + 1):
                covered[i] = True
    return aligned, _improvised(words, covered)


def _improvised(words: list, covered: list[bool]) -> list[dict]:
    out, cur = [], []

    def flush():
        if len(cur) >= 2 and words[cur[-1]][1] - words[cur[0]][0] >= IMPRO_MIN:
            a, b = cur[0], cur[-1]
            out.append({"a_idx": a, "b_idx": b, "start": float(words[a][0]), "end": float(words[b][1]),
                        "text": " ".join(w[2] for w in words[a:b + 1])})
        cur.clear()

    for i, w in enumerate(words):
        if covered[i]:
            flush()
            continue
        if not _tok(w[2]):
            continue
        if cur and w[0] - words[cur[-1]][1] >= IMPRO_GAP:
            flush()
        cur.append(i)
    flush()
    return out


def choose_takes(aligned: list) -> list[dict]:
    """La toma buena de cada línea: la ÚLTIMA entera (parecido ≥ 0,75); si no hay ninguna, la de mayor parecido.
    Las demás tomas de la línea se descartan. Sin toma ≥ 0,5 → falta."""
    out = []
    for k, takes in enumerate(aligned):
        if takes is None:
            out.append({"i": k, "chosen": None, "discarded": [], "missing": False, "empty": True})
            continue
        ok = [t for t in takes if t["score"] >= MIN_SCORE]
        if not ok:
            out.append({"i": k, "chosen": None, "discarded": [], "missing": True, "empty": False})
            continue
        good = [t for t in ok if t["score"] >= GOOD_SCORE and t["complete"]]
        pick = max(good, key=lambda t: t["start"]) if good else max(ok, key=lambda t: t["score"])
        out.append({"i": k, "chosen": pick, "discarded": [t for t in ok if t is not pick], "missing": False,
                    "empty": False})
    return out


def cut_span(words: list, a_idx: int, b_idx: int) -> tuple[float, float]:
    """El tramo del archivo que se quita con una toma descartada (incluye la pausa pegada, como en las tomas
    repetidas de la limpieza automática)."""
    a = words[a_idx][0] - 0.02
    if a_idx > 0:
        a = max(a, words[a_idx - 1][1] + 0.01)
    e = words[b_idx][1]
    if b_idx + 1 < len(words):
        gap = words[b_idx + 1][0] - e
        e = max(e, words[b_idx + 1][0] - 0.03) if gap < 0.6 else e + 0.1
    else:
        e += 0.1
    return max(0.0, a), e
