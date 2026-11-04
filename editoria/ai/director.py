"""
Módulo de IA: MODO DIRECTOR.

Convierte una instrucción escrita en español en un PLAN de edición que se revisa
antes de aplicarlo. Entiende instrucciones típicas de edición:

  "En esta parte usa gameplay de combate, cambia de clip cada 3-5 segundos y cuando
   diga 'el problema' haz un pequeño zoom al personaje. No agregues texto."

  - qué material usar ("usa gameplay de combate", "pon cinemáticas", "muestra a Marcus")
  - ritmo ("cambia de clip cada 3-5 segundos", "cada 4 segundos")
  - zooms en palabras ("cuando diga 'X' haz zoom", "pequeño zoom al personaje / a la cara")
  - textos ("pon el texto 'NO FUNCIONA'", "no agregues texto")
  - proteger ("no modifiques esta parte", "no toques nada aquí")
  - dónde ("de 1:20 a 1:40", "durante 20 segundos", "en esta parte" = el tema bajo el cabezal)

Es un intérprete por reglas (funciona en tu PC, sin internet). Si algo no lo entiende, lo dice.
"""
from __future__ import annotations

import re

from ..core.organize import normalize

TYPE_WORDS = {"gameplay": "Gameplay", "jugabilidad": "Gameplay", "cinematica": "Cinemáticas",
              "cinematicas": "Cinemáticas", "escena": "Cinemáticas", "escenas": "Cinemáticas",
              "imagen": "Imágenes", "imagenes": "Imágenes", "captura": "Imágenes", "capturas": "Imágenes"}

_NUM = r"(\d+(?:[.,]\d+)?)"


def _time(text: str) -> float | None:
    """'1:20' → 80, '2m10s' → 130, '45' → 45"""
    text = text.strip()
    m = re.fullmatch(r"(\d+):(\d{1,2}(?:[.,]\d+)?)", text)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2).replace(",", "."))
    m = re.fullmatch(r"(?:(\d+)\s*m(?:in)?)?\s*(?:(\d+(?:[.,]\d+)?)\s*s)?", text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + float((m.group(2) or "0").replace(",", "."))
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse(instruction: str, playhead: float, topic_range: tuple[float, float] | None,
          total: float) -> dict:
    """Interpreta la instrucción. Devuelve {"range": (a, b), "steps": [...], "unknown": [...]}"""
    raw = instruction.strip()
    t = normalize(raw)
    steps: list[dict] = []
    understood: list[str] = []

    # ¿Dónde?
    rng = None
    m = re.search(r"(?:de|desde|entre)(?: el)?(?: minuto)? (\d+:\d+(?:[.,]\d+)?|\d+\s*s|\d+) "
                  r"(?:a|hasta|y)(?: el)?(?: minuto)? (\d+:\d+(?:[.,]\d+)?|\d+\s*s|\d+)", t)
    if m and _time(m.group(1)) is not None and _time(m.group(2)) is not None:
        rng = (_time(m.group(1)), _time(m.group(2)))
        understood.append(m.group(0))
    if rng is None:
        m = re.search(r"(?:durante|por|unos|aproximadamente|como) (?:unos |aproximadamente )?" + _NUM +
                      r" ?(?:s|seg|segundos)\b", t)
        if m:
            rng = (playhead, playhead + float(m.group(1).replace(",", ".")))
            understood.append(m.group(0))
    if rng is None and topic_range is not None:
        rng = topic_range
    if rng is None:
        rng = (playhead, min(total, playhead + 20.0)) if total > playhead else (playhead, playhead + 20.0)
    a, b = max(0.0, min(rng)), max(rng)

    # ¿Proteger?
    if re.search(r"\bno (modifiques|modificar|toques|tocar|cambies|cambiar)\b", t):
        steps.append({"kind": "lock", "label": "🔒 Proteger esta parte: la IA no la tocará"})
        understood.append("no modificar")
        return {"range": (a, b), "steps": steps, "unknown": [], "understood": understood}

    # Ritmo
    pace = None
    m = re.search(r"cada " + _NUM + r"(?: ?(?:-|a|y) ?" + _NUM + r")? ?(?:s|seg|segundos)?", t)
    if m:
        lo = float(m.group(1).replace(",", "."))
        hi = float(m.group(2).replace(",", ".")) if m.group(2) else lo + 1.0
        pace = (min(lo, hi), max(lo, hi))
        understood.append(m.group(0))

    # Material ("usa gameplay de combate")
    m = re.search(r"\b(usa|utiliza|pon|ponme|muestra|mete|ensena|quiero) (?:clips de |imagenes de |material de )?"
                  r"([^,.;]+?)(?=,|\.|;| y cuando| cuando| cambia| no |$)", t)
    if m and not re.match(r"(un |una )?(zoom|texto)", m.group(2)) and not m.group(2).startswith("el texto"):
        what = m.group(2).strip()
        prefer = [TYPE_WORDS[w] for w in re.findall(r"[a-z]+", what) if w in TYPE_WORDS]
        steps.append({"kind": "broll", "query": what, "prefer": prefer[:1], "pace": pace or (4.0, 7.0),
                      "label": f"🎬 B-roll de «{what}»" + (f", cambiando cada {pace[0]:g}–{pace[1]:g} s" if pace else "")})
        understood.append(m.group(0))
    elif pace:
        steps.append({"kind": "broll", "query": "", "prefer": [], "pace": pace,
                      "label": f"🎬 Cambiar de clip cada {pace[0]:g}–{pace[1]:g} s (según lo que dices)"})

    # Zooms en palabras
    for m in re.finditer(r"cuando (?:diga|digo|dice|menciono|mencione) [\"'«“]?([^\"'»”,.]+?)[\"'»”]?"
                         r",? (?:haz|hazme|pon|mete)? ?(?:un |una )?(pequeno |ligero |suave |gran |fuerte )?"
                         r"(zoom|acercamiento)( (?:al|a la|en el|en la|sobre el|sobre la) ([a-z ]+?))?(?=,|\.|;| y |$)", t):
        word = m.group(1).strip()
        size = (m.group(2) or "").strip()
        z = 1.3 if size in ("pequeno", "ligero", "suave") else 2.0 if size in ("gran", "fuerte") else 1.6
        target = (m.group(5) or "").strip()
        face = bool(re.search(r"cara|rostro|personaje|protagonista|cabeza", target))
        steps.append({"kind": "zoom_word", "word": word, "z": z, "face": face,
                      "label": f"🔍 Zoom {'pequeño ' if z < 1.5 else ''}cuando digas «{word}»"
                               + (f" (hacia {target})" if target else "")})
        understood.append(m.group(0))

    # Textos
    for m in re.finditer(r"(?:pon|anade|agrega|escribe|mete) (?:el |un )?texto [\"'«“]([^\"'»”]+)[\"'»”]", raw,
                         flags=re.IGNORECASE):
        steps.append({"kind": "text", "content": m.group(1), "label": f"T Texto en pantalla: «{m.group(1)}»"})
        understood.append(m.group(0))
    if re.search(r"\bno (agregues|anadas|pongas|metas|incluyas) (ningun )?(texto|textos|titulos)\b", t):
        steps.append({"kind": "no_text", "label": "✓ Sin textos nuevos en esta parte"})
        understood.append("sin texto")

    if not steps:
        return {"range": (a, b), "steps": [], "understood": understood,
                "unknown": ["No entendí qué hacer. Prueba con frases como «usa gameplay de combate», "
                            "«cambia de clip cada 3-5 segundos», «cuando diga 'X' haz zoom», "
                            "«pon el texto 'X'» o «no modifiques esta parte»."]}
    return {"range": (a, b), "steps": steps, "unknown": [], "understood": understood}
