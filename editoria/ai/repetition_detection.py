"""
Módulo de IA: DETECCIÓN DE REPETICIONES Y MULETILLAS (sobre la transcripción).

- Muletillas: "eh", "mmm", "este,", "o sea"...
- Palabras repetidas: "el el problema".
- Tomas repetidas: cuando dices una frase, te equivocas y la vuelves a decir.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..core.organize import normalize

# Siempre son muletillas
PURE_FILLERS = {"eh", "ehh", "eeh", "em", "emm", "ehm", "mm", "mmm", "hmm", "mhm", "ah", "ahh",
                "uh", "um", "umm", "eem"}
# Pueden ser muletillas o palabras normales: solo se avisan si van seguidas de pausa o coma
SOFT_FILLERS = {"este", "esto", "bueno", "pues", "digamos", "vale", "osea", "tipo"}
SOFT_PAIRS = {("o", "sea"), ("como", "que")}


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9ñ]", "", normalize(word))


def _gap_after(words, i) -> float:
    return words[i + 1][0] - words[i][1] if i + 1 < len(words) else 1.0


def _cut_end(words, i, extra=0.1) -> float:
    """Fin del corte para la palabra i: hasta justo antes de la siguiente si está cerca."""
    if i + 1 < len(words) and words[i + 1][0] - words[i][1] < 0.6:
        return max(words[i][1], words[i + 1][0] - 0.03)
    return words[i][1] + extra


# Preguntas de coletilla al final de una frase («…lo que pasó, ¿no?»): casi siempre sobran al editar
TAG_QUESTIONS = {("no",), ("verdad",), ("sabes",), ("cierto",), ("ok",), ("okay",), ("vale",), ("eh",), ("va",),
                 ("ves",), ("entiendes",), ("me", "explico"), ("me", "entiendes"), ("sale",)}


def _tag_question(words, i) -> int:
    """¿Empieza en i una pregunta de coletilla («¿no?», «¿me explico?»)? Devuelve cuántas palabras ocupa (o 0)."""
    for n in (1, 2):
        if i + n > len(words):
            break
        seg = words[i:i + n]
        first, last = seg[0][2].strip(), seg[-1][2].strip()
        if not last.endswith("?"):
            continue
        opened = first.startswith("¿") or (i > 0 and words[i - 1][2].rstrip().endswith((",", ".", "…")))
        if opened and tuple(_norm(w[2]) for w in seg) in TAG_QUESTIONS:
            return n
    return 0


def _mine(phrases) -> list[tuple[tuple[str, ...], bool]]:
    """Tus muletillas («¿por qué?», «la verdad»…): (palabras, ¿tiene que ser una pregunta suelta?)."""
    out = []
    for p in phrases or []:
        toks = tuple(t for t in (_norm(x) for x in str(p).split()) if t)
        if toks:
            out.append((toks, "?" in str(p)))
    return sorted(out, key=lambda m: -len(m[0]))


def find_fillers(words: list, mine=()) -> list[dict]:
    """Muletillas. mine = las tuyas (lista de frases que escribiste en «Mis muletillas»)."""
    out = []
    own = _mine(mine)
    i = 0
    while i < len(words):
        raw = words[i][2]
        n = _norm(raw)
        pair = (n, _norm(words[i + 1][2])) if i + 1 < len(words) else None
        hit = next((m for m in own if tuple(_norm(w[2]) for w in words[i:i + len(m[0])]) == m[0]
                    and (not m[1] or words[i + len(m[0]) - 1][2].rstrip().endswith("?"))), None)
        tag = _tag_question(words, i)
        if hit:
            k = len(hit[0])
            text = " ".join(w[2] for w in words[i:i + k]).strip(",.")
            out.append({"start": words[i][0] - 0.02, "end": _cut_end(words, i + k - 1),
                        "label": f"Muletilla tuya: «{text}»", "words": list(range(i, i + k)),
                        "detail": "Está en tu lista «Mis muletillas».", "data": {"mine": True}})
            i += k
            continue
        if tag:
            text = " ".join(w[2] for w in words[i:i + tag]).strip(",. ")
            out.append({"start": words[i][0] - 0.02, "end": _cut_end(words, i + tag - 1),
                        "label": f"Posible muletilla: «{text}»", "words": list(range(i, i + tag)),
                        "detail": "Pregunta de coletilla al final de la frase. Quítala si no la necesitas."})
            i += tag
            continue
        if n in PURE_FILLERS:
            out.append({"start": words[i][0] - 0.02, "end": _cut_end(words, i),
                        "label": f"Muletilla: «{raw.strip(',.')}»", "words": [i]})
        elif pair in SOFT_PAIRS and (
                words[i + 1][2].rstrip().endswith((",", "...", "…")) or _gap_after(words, i + 1) >= 0.3):
            out.append({"start": words[i][0] - 0.02, "end": _cut_end(words, i + 1),
                        "label": f"Posible muletilla: «{raw} {words[i + 1][2].strip(',.')}»",
                        "words": [i, i + 1]})
            i += 1
        elif n in SOFT_FILLERS and (raw.rstrip().endswith((",", "...", "…")) or _gap_after(words, i) >= 0.3):
            out.append({"start": words[i][0] - 0.02, "end": _cut_end(words, i),
                        "label": f"Posible muletilla: «{raw.strip(',.')}»", "words": [i]})
        i += 1
    return out


# Repeticiones que muchas veces son A PROPÓSITO («muy muy bueno», «no, no, no»): se avisan, no se cortan solas
EMPHASIS = {"muy", "no", "si", "sí", "ya", "bien", "mas", "más", "nunca", "jamas", "jamás", "todo", "nada", "mucho",
            "otra", "vez", "corre", "vamos", "dale", "ay", "ja", "jaja"}


def _prob(w) -> float:
    return float(w[3]) if len(w) > 3 else 1.0


def find_repeated_words(words: list) -> list[dict]:
    out = []
    for i in range(len(words) - 1):
        a, b = _norm(words[i][2]), _norm(words[i + 1][2])
        gap = words[i + 1][0] - words[i][1]
        if a and a == b and not a.isdigit() and gap < 0.6:
            emph = a in EMPHASIS
            out.append({"start": words[i][0] - 0.02, "end": max(words[i][1], words[i + 1][0] - 0.03),
                        "label": (f"Repetición (¿a propósito?): «{words[i][2].strip(',.')} "
                                  f"{words[i + 1][2].strip(',.')}»" if emph else
                                  f"Palabra repetida: «{words[i][2].strip(',.')} {words[i + 1][2].strip(',.')}»"),
                        "detail": ("Puede ser énfasis: la limpieza automática no la quita." if emph else
                                   "Se quita la primera y se queda la segunda."),
                        "words": [i], "data": {"auto": not emph}})
        elif a and b and len(a) >= 2 and len(a) < len(b) and b.startswith(a) and gap < 0.45 \
                and (words[i][2].rstrip().endswith(("-", "…", "...")) or _prob(words[i]) < 0.6 or len(a) <= 3):
            out.append({"start": words[i][0] - 0.02, "end": max(words[i][1], words[i + 1][0] - 0.03),
                        "label": f"Palabra cortada: «{words[i][2].strip(',.')}… {words[i + 1][2].strip(',.')}»",
                        "detail": "Empezaste la palabra y la repetiste entera: se quita el trozo cortado.",
                        "words": [i], "data": {"auto": True}})
    return out


NEGATIONS = {"no", "nunca", "jamas", "tampoco", "ni"}

# Palabras tan comunes que repetirlas no dice nada («de la que…»): un «volver a empezar» necesita algo más
STOP = {"a", "al", "de", "del", "el", "la", "las", "los", "lo", "le", "les", "un", "una", "unos", "unas", "y", "o",
        "que", "en", "es", "se", "no", "si", "me", "te", "mi", "tu", "su", "por", "para", "con", "como", "pero",
        "ya", "yo", "ese", "esa", "eso", "este", "esta", "esto", "mas", "muy", "hay", "fue", "era", "ha", "he"}


def _restarts(toks: list[str], a: int, b: int) -> list[int]:
    """Dentro de una frase [a, b): dónde vuelves a empezar lo mismo («el día de ayer yo estaba jugando el día de
    ayer estaba trabajando» → se parte en el segundo «el»). Devuelve los índices donde empieza cada toma."""
    cuts, k = [], a
    j = a + 2
    while j + 2 < b:
        g = toks[j:j + 3]
        if all(g) and any(len(t) >= 4 and t not in STOP for t in g):
            for i in range(max(k, j - 25), j - 1):
                if toks[i:i + 3] == g:
                    s, t = i, j
                    while s > k and t - 1 > s + 1 and toks[s - 1] and toks[s - 1] == toks[t - 1]:
                        s, t = s - 1, t - 1                 # «el día de ayer…»: empieza en «el», no en «día»
                    cuts += [s, t] if s > k else [t]
                    k = t
                    break
        j += 1
    return sorted(set(c for c in cuts if a < c < b))


def split_phrases(words: list, gap: float = 0.6, restarts: bool = False) -> list[tuple[int, int]]:
    """Divide en frases: termina en . ? ! o hay una pausa larga. Con restarts=True, si dentro de una frase vuelves a
    empezar lo mismo (Whisper a veces junta las dos tomas sin punto ni pausa), también se parte ahí."""
    phrases, start = [], 0
    for i, w in enumerate(words):
        end_punct = w[2].rstrip().endswith((".", "?", "!", "…"))
        if end_punct or _gap_after(words, i) >= gap or i == len(words) - 1:
            phrases.append((start, i + 1))
            start = i + 1
    if not restarts:
        return phrases
    toks = [_norm(w[2]) for w in words]
    # Por comas también («No sé si se superó, no sé si superó esas inseguridades»), si los dos lados son de 3+ palabras
    by_comma = []
    for a, b in phrases:
        start = a
        for i in range(a, b - 1):
            if words[i][2].rstrip().endswith(",") and i + 1 - start >= 3 and b - (i + 1) >= 3:
                by_comma.append((start, i + 1))
                start = i + 1
        by_comma.append((start, b))
    out = []
    for a, b in by_comma:
        bounds = [a] + _restarts(toks, a, b) + [b]
        out += [(x, y) for x, y in zip(bounds, bounds[1:]) if y > x]
    return _tail_restarts(toks, out)


def _tail_restarts(toks: list[str], phrases: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """El final de una frase vuelve a salir al principio de la siguiente («…no es un odio personal. No es un odio
    personal hacia Deborah»): ese final se separa como una toma propia."""
    out = list(phrases)
    k = 0
    while k + 1 < len(out):
        (a0, a1), (b0, b1) = out[k], out[k + 1]
        best_i, best_n = None, 0
        for i in range(max(a0 + 1, a1 - 25), a1):
            n = 0
            while i + n < a1 and b0 + n < b1 and toks[i + n] and toks[i + n] == toks[b0 + n]:
                n += 1
            if n >= 3 and n > best_n and any(len(t) >= 4 and t not in STOP for t in toks[i:i + n]):
                best_i, best_n = i, n
        if best_i is not None:
            out[k:k + 1] = [(a0, best_i), (best_i, a1)]
            k += 1
        k += 1
    return out


def _phrase_range(words, phrases, x) -> tuple[float, float]:
    a0, a1 = phrases[x]
    nxt = phrases[x + 1][0] if x + 1 < len(phrases) else None
    end = words[nxt][0] - 0.05 if nxt is not None else words[a1 - 1][1] + 0.1
    return words[a0][0] - 0.02, end


def _continues(words, phrases, x, group) -> bool:
    """¿El trozo x acaba en coma y la frase sigue justo después (sin que lo que sigue sea otra toma)?"""
    a1 = phrases[x][1]
    return (words[a1 - 1][2].rstrip().endswith(",") and a1 < len(words) and x + 1 not in (group or ())
            and _gap_after(words, a1 - 1) < 0.6 and not words[a1][2].lstrip("¿¡\"«(")[:1].isupper())


def score_take(words: list, phrases, x: int, norm: list[list[str]], others: list[list[str]],
               group: list[int] | None = None) -> tuple[float, list, list]:
    """Cuánto vale una toma (más = mejor) y por qué: completa, sin muletillas ni trabas, clara y fluida."""
    a0, a1 = phrases[x]
    ws = words[a0:a1]
    toks = [t for t in norm[x] if t]
    score, good, bad = 0.0, [], []
    # ¿La dejaste a medias? (es el principio de la otra toma y más corta; la última palabra puede estar cortada:
    # «esa dis…» → «esa discusión»)
    other = max(others, key=len) if others else []

    def starts(o) -> bool:
        n = len(toks)
        return n < len(o) and o[:n - 1] == toks[:n - 1] and o[n - 1].startswith(toks[n - 1])
    if toks and any(starts(o) for o in others):
        score -= 2.5
        bad.append("se quedó a medias")
    elif toks and any(len(toks) + 2 <= len(o) and SequenceMatcher(None, toks, o[:len(toks) + 2]).ratio() >= 0.8
                      for o in others):
        score -= 1.0                                   # casi lo mismo que el principio de otra toma que dice más
        bad.append("dice menos que la otra")
    # ¿Termina bien? Un «…» al final es quedarse a medias si después no sigue la frase (mayúscula o pausa larga);
    # si sigue en minúscula, Whisper solo marcó una duda.
    last = ws[-1][2].rstrip()
    gap_after = _gap_after(words, a1 - 1)
    nxt = words[a1][2].lstrip("¿¡\"«(") if a1 < len(words) else ""
    if last.endswith(("...", "…", "-")):
        if not nxt or gap_after >= 1.0 or nxt[:1].isupper():
            score -= 1.0
            if "se quedó a medias" not in bad:
                bad.append("se quedó a medias")
    elif last.endswith((".", "?", "!")) or gap_after >= 0.6 or _continues(words, phrases, x, group):
        score += 0.8
        good.append("termina completa")
    else:
        score -= 0.6
    # Muletillas y trabas dentro
    fillers = sum(1 for t in toks if t in PURE_FILLERS)
    trabas = sum(1 for i in range(len(toks) - 1) if toks[i] and (toks[i] == toks[i + 1] or
                                                               (len(toks[i]) >= 2 and toks[i + 1].startswith(toks[i])
                                                                and len(toks[i]) < len(toks[i + 1]))))
    trabas += sum(1 for i in range(min(3, len(toks) - 2)) if toks[i] == toks[i + 2])   # «pero ahora, pero si…»
    score -= 0.7 * fillers + 0.6 * trabas
    if fillers:
        bad.append(f"{fillers} muletilla{'s' if fillers > 1 else ''}")
    if trabas:
        bad.append("se traba")
    # Pausas raras dentro de la frase
    pauses = sum(1 for i in range(a0, a1 - 1) if words[i + 1][0] - words[i][1] > 0.5)
    score -= 0.4 * pauses
    if pauses:
        bad.append("pausas largas")
    # Claridad: qué tan seguro estuvo el reconocimiento de voz
    probs = [_prob(w) for w in ws]
    conf = sum(probs) / max(1, len(probs))
    low = sum(1 for p in probs if p < 0.4)
    score += 2.0 * conf - 0.5 * low
    if low:
        bad.append("palabras poco claras")
    elif conf > 0.85:
        good.append("se entiende muy bien")
    # Dice más (cubre toda la idea)
    extra = len(toks) - len(other)
    if extra > 0:
        score += min(0.6, 0.15 * extra)
        if extra >= 2:
            good.append("dice la idea completa")
    return score, good, bad


# Qué tanto se parecen las tomas (lo que ve el usuario en el resumen)
LEVELS = {"igual": "Se repite", "medio": "Se medio repite", "parecido": "Suena parecido"}


def _phrase_text(words, phrases, x, max_words: int = 0) -> str:
    ws = [w[2] for w in words[phrases[x][0]:phrases[x][1]]]
    if max_words and len(ws) > max_words:
        ws = ws[:max_words] + ["…"]
    return " ".join(ws)


def _level(A: list[str], B: list[str]) -> str:
    """igual = casi palabra por palabra (o la empezaste y la volviste a empezar); medio = cambia algo."""
    if not A or not B:
        return "medio"
    short, long_ = (A, B) if len(A) <= len(B) else (B, A)
    if long_[:len(short)] == short or SequenceMatcher(None, A, B).ratio() >= 0.85:
        return "igual"
    return "medio"


def _retake_items(words, phrases, group: list[int], norm, level: str | None = None, auto: bool = True) -> list[dict]:
    """Sugerencias de un grupo de tomas: la IA elige la mejor y propone quitar las demás (diciendo por qué)."""
    toks = {x: [t for t in norm[x] if t] for x in group}
    scored = {}
    for x in group:
        others = [toks[y] for y in group if y != x]
        sc, good, bad = score_take(words, phrases, x, norm, others, group)
        # casi siempre repites porque la anterior salió mal: la más reciente lleva ventaja
        scored[x] = (sc + 0.4 * group.index(x) / max(1, len(group) - 1), good, bad)
    best = max(group, key=lambda x: scored[x][0])
    if all(toks[x] == toks[group[0]] for x in group):    # dijiste exactamente lo mismo: la última (ya te salió)
        best = group[-1]
    others_bad = list(dict.fromkeys(b for y in group if y != best for b in scored[y][2]))
    reason = ", ".join(scored[best][1]) or "es la más limpia"
    if others_bad:
        reason += " · las otras: " + ", ".join(others_bad)
    if scored[best][2]:
        reason += " (aunque esta también: " + ", ".join(scored[best][2]) + ")"
    last = {}                                           # cada toma, con el resto de su frase si sigue tras la coma
    for x in group:
        y = x
        while y + 1 < len(phrases) and y - x < 2 and _continues(words, phrases, y, group):
            y += 1
        last[x] = y
    texts = {x: " ".join(_phrase_text(words, phrases, y) for y in range(x, last[x] + 1)) for x in group}

    def take_range(x):
        return _phrase_range(words, phrases, x)[0], _phrase_range(words, phrases, last[x])[1]
    nxt = max(last.values()) + 1
    after = _phrase_text(words, phrases, nxt, 14) if nxt < len(phrases) else ""
    n = len(group)
    out = []
    for x in group:
        if x == best:
            continue
        first, second = (x, best) if x < best else (best, x)
        r1, r2 = take_range(first), take_range(second)
        keep = 2 if best == second else 1
        lv = level or _level(toks[x], toks[best])
        detail = "\n".join(f"{'⭐ ' if y == best else '✗ '}Toma {group.index(y) + 1}: «{texts[y]}»" for y in group)
        if after:
            detail += f"\n\nDespués dijiste: «{after}»"
        out.append({"start": r1[0], "end": r1[1], "alt_start": r2[0], "alt_end": r2[1],
                    "label": f"{LEVELS[lv]}{f' ({n} tomas)' if n > 2 else ''} · la IA se queda con la toma "
                             f"{group.index(best) + 1}",
                    "detail": f"{detail}\n\nPor qué: {reason}.",
                    "words": list(range(phrases[x][0], phrases[last[x]][1])),
                    "data": {"best": keep, "reason": reason, "auto": auto, "level": lv,
                             "takes": [[texts[y], y == best] for y in group], "after": after}})
    return out


def find_retakes(words: list, min_words: int = 3, min_ratio: float = 0.6) -> list[dict]:
    """Tomas repetidas: una frase que dijiste 2 o más veces seguidas. La IA elige la MEJOR toma (no siempre la
    última) y propone quitar las demás, diciendo por qué."""
    phrases = split_phrases(words, restarts=True)
    norm = [[_norm(w[2]) for w in words[a:b]] for a, b in phrases]

    def content(x) -> set[str]:
        return {t for t in norm[x] if len(t) >= 4 and t not in STOP}

    def parallel(k, j) -> bool:
        """Dos trozos de frase (partidas por comas) que empiezan igual pero siguen distinto: «Si cuestionas el
        diseño, estás atacando a la actriz. Si cuestionas el cambio de protagonista, odias a las mujeres»."""
        if j == k + 1 or not words[phrases[k][1] - 1][2].rstrip().endswith(","):
            return False
        if j + 1 >= len(phrases) or not words[phrases[j][1] - 1][2].rstrip().endswith(","):
            return False
        ca, cb = content(k + 1), content(j + 1)
        return len(ca) >= 2 and len(cb) >= 2 and not ca & cb

    def similar(k, j) -> tuple[bool | None, float]:
        """True = otra toma de lo mismo · False = no · None = empiezan igual pero dicen cosas DISTINTAS (una
        enumeración a propósito: «lo que sí puedo cuestionar es… / lo que sí puedo decir es…»)."""
        A, B = [w for w in norm[k] if w], [w for w in norm[j] if w]
        if len(A) < min_words and len(B) < min_words:
            return False, 0.0
        if min(len(A), len(B)) < 2:
            return False, 0.0
        ratio = SequenceMatcher(None, A, B).ratio()
        prefix = len(A) < len(B) and B[:len(A)] == A and len(A) >= 2      # la empezaste y la repetiste
        if prefix:
            return True, ratio
        n = 0
        while n < min(len(A), len(B)) and A[n] == B[n]:
            n += 1
        tail_a = {t for t in A[n:] if len(t) >= 4 and t not in STOP}
        tail_b = {t for t in B[n:] if len(t) >= 4 and t not in STOP}
        if n >= 2 and len(tail_a) >= 3 and len(tail_b) >= 3 and not tail_a & tail_b:
            return None, ratio
        if bool(set(A[:3]) & NEGATIONS) != bool(set(B[:3]) & NEGATIONS) and ratio < 0.8:
            return None, ratio                       # «no estoy pensando en la actriz / estoy pensando en el arte»
        if parallel(k, j):
            return None, ratio
        unfinished = words[phrases[k][1] - 1][2].rstrip().endswith(("...", "…", "-")) or len(A) <= 4
        content_a = {t for t in A if len(t) >= 4 and t not in STOP}
        content_b = {t for t in B if len(t) >= 4 and t not in STOP}
        same_start = (n >= 3 and (unfinished or ratio >= 0.5)) or \
            (n >= 2 and unfinished and bool(content_a & content_b))       # «Yo no siente como…» → «yo no sé cómo se siente»
        return ratio >= min_ratio or (same_start and len(A) <= len(B) + 2), ratio

    out, used = [], set()
    for k in range(len(phrases) - 1):
        if k in used:
            continue
        group, ratios = [k], []
        j = k + 1
        # la otra toma puede venir justo después (aunque hayas hecho una pausa larga) o hasta 3 trozos después si hubo
        # algo a medias en medio, en menos de 10 s
        while j < len(phrases) and (j == group[-1] + 1 or (
                j <= group[-1] + 3 and words[phrases[j][0]][0] - words[phrases[group[-1]][1] - 1][1] <= 10.0)):
            ok, r = similar(group[-1], j)
            if ok is None:                         # dicen cosas distintas: aquí se acaba el grupo
                break
            if not ok and len(group) > 1:
                ok, r = similar(k, j)
            if ok:
                group.append(j)
                ratios.append(r)
            j += 1
        if len(group) < 2:
            continue
        used.update(group)
        out += _retake_items(words, phrases, group, norm)
    return out


def find_similar(words: list, encode, taken: list[dict] | None = None, min_words: int = 4,
                 min_sim: float = 0.74) -> list[dict]:
    """«Suena parecido»: dos frases seguidas que dicen casi lo mismo con OTRAS palabras («ayer me puse a trabajar» /
    «lo que hice ayer fue trabajar»). Lo decide un modelo de frases (encode(textos) -> huellas normalizadas). Solo se
    avisa: la limpieza automática no lo quita sin que lo taches tú."""
    phrases = split_phrases(words, restarts=True)
    norm = [[_norm(w[2]) for w in words[a:b]] for a, b in phrases]
    mids = [(w[0] + w[1]) / 2 for w in words]
    busy = set()
    for d in taken or []:                              # lo que ya es una toma repetida (todas sus tomas) no va aquí
        for a, b in ((d["start"], d["end"]), (d.get("alt_start"), d.get("alt_end"))):
            if a is not None:
                busy.update(i for i, m in enumerate(mids) if a <= m <= b)
    cand = [x for x in range(len(phrases)) if len([t for t in norm[x] if t]) >= min_words
            and not busy.intersection(range(*phrases[x]))]
    if len(cand) < 2:
        return []
    vecs = encode([_phrase_text(words, phrases, x) for x in cand])
    pos = {x: k for k, x in enumerate(cand)}
    out, used = [], set()
    for x in cand:
        if x in used:
            continue
        for y in (x + 1, x + 2):
            if y in pos and y not in used and words[phrases[y][0]][0] - words[phrases[x][1] - 1][1] < 6.0:
                if float(vecs[pos[x]] @ vecs[pos[y]]) >= min_sim:
                    used.update((x, y))
                    out += _retake_items(words, phrases, [x, y], norm, level="parecido", auto=False)
                    break
    return out


def find_doubtful(words: list, max_prob: float = 0.35) -> list[dict]:
    """Palabras que Whisper entendió con poca seguridad: posibles palabras cortadas o errores."""
    return [{"start": w[0] - 0.1, "end": w[1] + 0.1,
             "label": f"Palabra dudosa: «{w[2]}» ({w[3]:.0%})", "words": [i]}
            for i, w in enumerate(words) if len(w) > 3 and w[3] < max_prob and _norm(w[2]) not in PURE_FILLERS]
