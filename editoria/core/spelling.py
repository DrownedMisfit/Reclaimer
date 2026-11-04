"""
Ortografía de lo que TÚ escribes (textos en pantalla, miniaturas, frases del edit). No tiene nada que ver con la
transcripción.

Idiomas: «mixto» (español de México + inglés: una palabra vale si existe en cualquiera de los dos; para cuando
mezclas, p. ej. «el boss final del gameplay»), «es» (español de México) o «en» (inglés).
Motor: diccionarios Hunspell de LibreOffice (es_MX y en_US, en assets/diccionarios; licencias libres, ver sus README)
leídos con spylls. Más un vocabulario de gaming/streaming y TU diccionario personal («Añadir al diccionario»).

  is_ok(palabra, idioma) -> bool     (rápido: < 1 ms)
  suggest(palabra, idioma) -> [...]  (lo más probable primero: la misma palabra con tilde, luego la más parecida)
  misspelled(texto, idioma) -> [(inicio, fin), ...]
  add_word(palabra)
"""
from __future__ import annotations

import os
import re
import threading
import unicodedata

from .paths import app_data_dir

LANGS = {"mixto": "Mixto (español + inglés)", "es": "Español (México)", "en": "English", "off": "Sin corregir"}
_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "diccionarios")
_FILES = {"es": "es_MX", "en": "en_US"}

# Palabras de gaming / streaming / redes que los diccionarios no traen (se aceptan en cualquier idioma)
EXTRA = {
    "vámonos", "vamonos", "gameplay", "gameplays", "speedrun", "speedruns", "speedrunner", "streamer", "streamers",
    "stream", "streams", "streaming", "gamer", "gamers", "youtuber", "youtubers", "tiktoker", "tiktok", "youtube",
    "twitch", "shorts", "short", "clip", "clips", "setup", "lag", "loot", "boss", "bosses", "skin", "skins", "mod",
    "mods", "spawn", "respawn", "nerf", "buff", "noob", "noobs", "pro", "gg", "ez", "lol", "xd", "fps", "pvp", "pve",
    "dlc", "npc", "npcs", "hud", "rpg", "mmo", "mmorpg", "random", "randoms", "crack", "cracks", "edit", "edits",
    "remix", "drop", "hype", "outro", "intro", "vlog", "vlogs", "challenge", "speed", "combo", "combos", "headshot",
    "clutch", "spoiler", "spoilers", "trailer", "trailers", "lore", "tryhard", "smurf", "meme", "memes", "like",
    "likes", "suscríbete", "suscribanse", "suscríbanse", "jaja", "jajaja", "jajajaja", "ajá", "eh", "mmm", "uff",
    "wow", "ok", "okey", "bro", "neta", "wey", "güey", "órale", "chido", "chida", "chidos", "chidas",
}

# Palabras muy comunes que suelen ir pegadas a la siguiente por error («enserio», «porfavor», «aver», «sinembargo»)
COMMON = {"a", "al", "de", "del", "en", "por", "para", "con", "sin", "que", "lo", "la", "el", "los", "las", "se", "no",
          "ya", "y", "o", "es", "un", "una", "mi", "tu", "su", "te", "me", "le", "of", "in", "on", "to", "the", "a",
          "at", "for", "my", "is", "it"}

_lock = threading.Lock()
_dicts: dict = {}
_personal: set[str] | None = None
_ignored: set[str] = set()
WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:'[A-Za-z]+)?")


def _load(lang: str):
    """El diccionario (se carga una vez, ~0,4 s; se puede llamar desde otro hilo)."""
    with _lock:
        d = _dicts.get(lang)
        if d is not None:
            return d
    from spylls.hunspell import Dictionary
    d = Dictionary.from_files(os.path.join(_DIR, _FILES[lang]))
    with _lock:
        _dicts.setdefault(lang, d)
        return _dicts[lang]


def ready(lang: str) -> bool:
    need = ("es", "en") if lang == "mixto" else ((lang,) if lang in _FILES else ())
    return all(k in _dicts for k in need)


def preload(lang: str = "mixto"):
    """Carga los diccionarios en segundo plano (para que el primer subrayado no frene la escritura)."""
    def go():
        for k in (("es", "en") if lang == "mixto" else (lang,)):
            if k in _FILES:
                try:
                    _load(k)
                except Exception:  # noqa: BLE001 - sin diccionario, simplemente no se subraya
                    pass
    threading.Thread(target=go, daemon=True).start()


def _personal_path() -> str:
    return os.path.join(str(app_data_dir()), "diccionario_personal.txt")


def personal() -> set[str]:
    global _personal
    if _personal is None:
        words = set()
        try:
            with open(_personal_path(), encoding="utf-8") as f:
                words = {ln.strip().lower() for ln in f if ln.strip()}
        except OSError:
            pass
        _personal = words
    return _personal


def add_word(word: str):
    """«Añadir al diccionario»: se acepta siempre (en todos los idiomas) y se guarda."""
    w = word.strip()
    if not w:
        return
    personal().add(w.lower())
    try:
        with open(_personal_path(), "a", encoding="utf-8") as f:
            f.write(w + "\n")
    except OSError:
        pass


def ignore(word: str):
    """«Ignorar»: solo mientras Reclaimer esté abierto."""
    _ignored.add(word.lower())


def _langs(lang: str) -> tuple[str, ...]:
    return ("es", "en") if lang == "mixto" else ((lang,) if lang in _FILES else ())


def is_ok(word: str, lang: str = "mixto") -> bool:
    if lang == "off" or len(word) <= 1:
        return True
    low = word.lower()
    if low in EXTRA or low in personal() or low in _ignored:
        return True
    if word.isupper() and len(word) <= 5:          # siglas (FPS, NPC, GTA…)
        return True
    for k in _langs(lang):
        if k not in _dicts:
            return True                            # aún cargando: no se marca nada
        d = _dicts[k]
        if d.lookup(word) or (word[:1].isupper() and d.lookup(low)):
            return True
    return False


def misspelled(text: str, lang: str = "mixto") -> list[tuple[int, int]]:
    """Dónde están las palabras mal escritas (ignora números, #etiquetas, @menciones y enlaces)."""
    if lang == "off":
        return []
    out = []
    for m in WORD_RE.finditer(text):
        a, b = m.span()
        prev = text[a - 1] if a > 0 else " "
        nxt = text[b] if b < len(text) else " "
        if prev in "#@/._" or nxt in "/._" or prev.isdigit() or nxt.isdigit():
            continue
        if not is_ok(m.group(), lang):
            out.append((a, b))
    return out


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _dist(a: str, b: str) -> int:
    """Distancia de edición con letras cambiadas de sitio como UN error («becuase» → «because»)."""
    n, m = len(a), len(b)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[n][m]


def _in_dict(word: str, lang: str) -> bool:
    """Solo los diccionarios (no el vocabulario gamer ni el personal): para separar palabras pegadas."""
    for k in _langs(lang):
        d = _dicts.get(k)
        if d is not None and (d.lookup(word) or d.lookup(word.lower())):
            return True
    return False


def suggest(word: str, lang: str = "mixto", n: int = 6) -> list[str]:
    """Sugerencias, la más probable primero: la misma palabra con sus tildes (despues → después), luego dos palabras
    («enserio» → «en serio»), luego las más parecidas."""
    cands: list[str] = []
    for k in _langs(lang):
        try:
            cands += list(_load(k).suggest(word))[:8]
        except Exception:  # noqa: BLE001
            pass
    # la «h» que falta (aora → ahora, ay → hay): muy común en español y Hunspell no la propone
    with_h = set()
    for i in range(len(word) + 1):
        w2 = word[:i] + "h" + word[i:]
        if _in_dict(w2, lang):
            cands.insert(0, w2)
            with_h.add(w2.lower())
    p = _plain(word)
    accent_fix = any(_plain(c) == p for c in cands)
    cands = [c for c in cands if "-" not in c]                      # «por-favor»: nunca

    def good_split(c: str) -> bool:      # «en serio», «por favor», «a ver»: la 1.ª parte, una palabra muy común
        parts = c.split(" ")
        return len(parts) == 2 and parts[0].lower() in COMMON and _plain(c).replace(" ", "") == p
    if accent_fix:                                                  # solo falta la tilde: nada de «des pues»
        cands = [c for c in cands if " " not in c or good_split(c)]
    # dos palabras pegadas («enserio» → «en serio», «porfavor» → «por favor»), solo con palabras de diccionario y si
    # no es simplemente una tilde que falta (si no, salen cosas como «des pues»)
    if not accent_fix:
        for i in range(1, len(word)):
            a, b = word[:i], word[i:]
            if len(b) >= 2 and (len(a) > 1 or a.lower() in "aoyeu") and _in_dict(a, lang) and _in_dict(b, lang):
                cands.append(f"{a} {b}")
    letters = sorted(p)
    seen, scored = set(), []
    for order, c in enumerate(cands):
        if c.lower() in seen or c == word:
            continue
        seen.add(c.lower())
        pc = _plain(c)
        same = pc.replace(" ", "") == p
        d = _dist(pc, p) + (0.5 if " " in c else 0)
        if " " in c and good_split(c):
            d -= 1.0
        if c.lower() in with_h:
            d -= 0.5
        same = same and " " not in c
        score = (0 if same else 1, d, 0 if sorted(pc) == letters else 1, order)
        scored.append((score, c))
    scored.sort()
    out = [c for _s, c in scored[:n]]
    if word[:1].isupper():                         # respeta la mayúscula inicial
        out = [c[:1].upper() + c[1:] for c in out]
    return out
