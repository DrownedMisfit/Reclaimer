"""
✨ EFECTOS SEGÚN LO QUE DICES (sobre los clips elegidos de la línea de tiempo, o toda si no eliges ninguno).

Mira la narración que suena durante cada clip (y un poco antes) y PROPONE, con su motivo:
  🖤 gris            blanco y negro (fx["bw"]) o 🩶 desaturado suave (color["saturation"]) cuando el tono es triste,
                     una noticia fuerte o un tema difícil. Léxico corto en español (con negaciones simples: «no murió»
                     no cuenta) y ampliable en datos/palabras_tono.txt. Opcional: solo si además nombras a alguien o
                     una palabra clave del proyecto (find_mentions + nombre al empezar frase seguido de la palabra).
                     En clips largos (> LARGO s) solo el tramo de la frase (al aplicar se corta el clip).
  🔍 zoom            zoom dinámico suave hacia la cara (o la persona) en IMÁGENES fijas: detector de OpenCV (YuNet;
                     si no, HOG de personas) UNA vez por imagen, a ≤ 640 px, con caché por archivo. Nunca en videos.
  ⭐ star            las reglas de «⭐ Mis efectos para la IA» que vienen de lo que dices (fíjense, hace años,
                     desastre, increíble…), si tienes efectos favoritos.

Todo es texto o una imagen pequeña: nada de GPU ni modelos pesados. Sin Qt.

  tone_hits(words)                    [{t, end, i, word, cat, w}] en la narración (words = [(ini, fin, texto)])
  sentence_span(words, i)             (ini, fin) de la frase de la palabra i
  start_names(words, hits)            [(t, nombre)]: nombre al empezar frase justo antes de la palabra triste
  timeline_words(p)                   todas las palabras que suenan en la línea de tiempo
  scope_clips(p, clip_ids)            los clips de imagen/video donde mirar (los elegidos o todos)
  tone_proposals(p, clips, words, …)  propuestas de gris
  image_face(path)                    {"x","y","w","h","kind"} de la cara/persona (0–1) o None (con caché)
  face_zoom_kf(dur, face)             fotogramas clave del zoom hacia ella
  zoom_proposals(p, clips, faces)     propuestas de zoom
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid

from ..core.model import KIND_AUDIO, KIND_IMAGE, TRACK_VIDEO

PRE = 1.0            # s de narración ANTES del clip que también cuentan (el B-roll suele ir un poco detrás)
LARGO = 15.0         # s: un clip más largo solo se pone gris en el tramo de la frase
MAX_FRASE = 12.0     # s: una «frase» sin puntos no se alarga más que esto a cada lado de la palabra
NOMBRE_CERCA = 4.0   # s alrededor de la frase en que tiene que sonar el nombre (casilla «solo si nombro…»)
DESAT = -0.7         # 🩶 saturación del desaturado suave (color del clip, -1…1)
NEG = {"no", "nunca", "ni", "sin", "jamas", "tampoco", "ningun", "ninguna", "ninguno", "nadie"}
CAT_ES = {"triste": "tono triste", "fuerte": "noticia fuerte", "dificil": "tema difícil"}
ICONO = {"bw": "🖤 Blanco y negro", "desat": "🩶 Desaturado suave"}

# (expresión sobre el texto normalizado: minúsculas, sin tildes ni signos · tipo · peso)
# Peso ≥ UMBRAL = inequívoco (basta con una vez). Peso ≤ 0,5 = ambiguo en partidas y ficción («el personaje muere»,
# «la guerra del juego», «pérdida de tiempo», «el cierre del video»): solo cuenta si se juntan varias en la misma
# frase (puntuación = el más fuerte + SUMA_EXTRA por cada otro). El orden importa: lo inequívoco va primero.
UMBRAL = 0.7
SUMA_EXTRA = 0.15
LEXICO = [
    # --- inequívocos
    (r"falleci\w*|ha(n)? muerto|murio (ayer|hoy|anoche|esta (semana|manana)|este (lunes|martes|miercoles|jueves|"
     r"viernes|sabado|domingo|fin de semana|mes|ano)|el pasado|a los \d+|a la edad)|murieron (ayer|hoy|anoche)",
     "triste", 1.0),
    (r"nos (ha )?dejad[oa]s?|nos dejo|se nos (ha )?ido|se nos fue|ya no esta con nosotros", "triste", 1.0),
    (r"descanse en paz|en paz descanse|q\s?e\s?p\s?d|luto|funeral(es)?|velorio|entierro|suicidio\w*|cancer|"
     r"hospitalizad[oa]s?", "triste", 0.9),
    (r"malas? noticias?|noticia (muy )?(triste|dura|fuerte|terrible)|triste noticia|duro golpe|golpe (muy )?duro|"
     r"atentados?", "fuerte", 1.0),
    (r"despidos( masivos)?|ola de despidos|despidieron|despedid[oa]s|"
     r"(cierra(n)?|cerro|cerraron|cierre de(l)?) (sus puertas|el estudio|estudio|la empresa|para siempre)|"
     r"cerrad[oa] (definitivamente|para siempre)|quiebra|bancarrota", "dificil", 0.9),
    (r"cancelad[oa]s?|cancelacion(es)?|demandad[oa]s?|demandaron|(una|la|otra) demanda (contra|a|por|judicial\w*)|"
     r"polemic\w*|escandalo\w*|acoso|arrestad[oa]s?|detenid[oa]s?|condenad[oa]s?", "dificil", 0.8),
    # --- ambiguos (solo si se juntan)
    (r"muri(o|eron|endo)|muer(e|en|te|tes|to|tos|ta|tas)|tragedi\w*|tragic[oa]s?|perdida(s)?|perdimos|despedida|"
     r"enfermedad(es)?|enferm[oa]s?|grave(mente)? herid\w*", "triste", 0.5),
    (r"tristes?|tristeza|lamentablemente|desgraciadamente|por desgracia|con mucho dolor|nos duele", "triste", 0.5),
    (r"(?<!por )accidentes?|guerras?|bombardeo\w*|violencia|crisis|catastrofe\w*|masacre|tiroteo\w*|victimas?|"
     r"heridos|incendio\w*|terremoto\w*|inundacion\w*|asesina\w*", "fuerte", 0.4),
    (r"despid(io|e|en)|cierre|abusos?|denuncia\w*|prision|carcel|demandar", "dificil", 0.4),
]


def _norm(text: str) -> str:
    from ..core.keyword_folders import norm
    return norm(text)


# ------------------------------------------------------------------ léxico (el tuyo se suma)
def user_lexicon_path() -> str:
    from ..core.paths import app_data_dir
    return str(app_data_dir() / "palabras_tono.txt")


USER_TEMPLATE = (
    "# Palabras o frases que dan tono triste, de noticia fuerte o difícil (una por línea).\n"
    "# Opcional, tras «|», el tipo: triste · fuerte · dificil.   «!palabra» = que NO cuente nunca.\n"
    "# Ejemplos (quita la # para usarlos):\n"
    "# nos ha dejado huerfanos | triste\n"
    "# despidos | dificil\n"
    "# !demanda\n")


def load_lexicon(path: str | None = None) -> tuple[list, set]:
    """([(regex compilado, tipo, peso)], {frases que no cuentan}): el léxico de serie + el tuyo."""
    rules = [(re.compile(r"\b(" + pat + r")\b"), cat, w) for pat, cat, w in LEXICO]
    ignore: set = set()
    path = path or user_lexicon_path()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("!"):
            k = _norm(ln[1:])
            if k:
                ignore.add(k)
            continue
        frase, _, cat = ln.partition("|")
        k = _norm(frase)
        cat = _norm(cat) or "triste"
        if k:
            rules.append((re.compile(r"\b(" + re.escape(k) + r")\b"), cat if cat in CAT_ES else "triste", 1.0))
    return rules, ignore


# ------------------------------------------------------------------ la narración
def _index(words: list) -> tuple[list[str], list[int], str]:
    norm, offsets, text = [], [], ""
    for w in words:
        offsets.append(len(text))
        n = _norm(w[2])
        norm.append(n)
        text += n + " "
    return norm, offsets, text


def tone_hits(words: list, lexicon: tuple | None = None) -> list[dict]:
    """Dónde suena algo triste / fuerte / difícil: [{t, end, i, word, cat, w}], sin las negadas («no murió»)."""
    if not words:
        return []
    rules, ignore = lexicon or load_lexicon()
    norm, offsets, text = _index(words)
    out, seen = [], set()
    import bisect
    for rx, cat, wt in rules:
        for mt in rx.finditer(text):
            i = bisect.bisect_right(offsets, mt.start()) - 1
            j = bisect.bisect_right(offsets, max(mt.start(), mt.end() - 1)) - 1
            frase = mt.group(0).strip()
            if frase in ignore or any(x in ignore for x in norm[i:j + 1]):
                continue
            antes = []
            for k in range(i - 1, max(-1, i - 4), -1):     # (3 palabras antes, sin pasar a la frase anterior)
                if str(words[k][2]).rstrip().endswith((".", "!", "?", "…", ";")):
                    break
                antes += norm[k].split()
            if any(x in NEG for x in antes):
                continue                                   # «no murió», «sin víctimas», «nunca cerró»
            if i in seen:
                continue
            seen.add(i)
            txt = " ".join(str(w[2]) for w in words[i:j + 1]).strip(" ,.;:¿?¡!\"'«»")
            out.append({"t": float(words[i][0]), "end": float(words[j][1]), "i": i, "word": txt, "cat": cat,
                        "w": float(wt)})
    out.sort(key=lambda h: h["t"])
    return out


def sentence_span(words: list, i: int) -> tuple[float, float]:
    """(ini, fin) de la frase de la palabra i: hasta un punto/¿?¡! o una pausa larga (máx. MAX_FRASE a cada lado)."""
    t = float(words[i][0])
    a = i
    while a > 0:
        prev = words[a - 1]
        if str(prev[2]).rstrip().endswith((".", "!", "?", "…")) or float(words[a][0]) - float(prev[1]) > 0.8 \
                or t - float(prev[0]) > MAX_FRASE:
            break
        a -= 1
    b = i
    while b < len(words) - 1:
        if str(words[b][2]).rstrip().endswith((".", "!", "?", "…")) or \
                float(words[b + 1][0]) - float(words[b][1]) > 0.8 or float(words[b + 1][1]) - t > MAX_FRASE:
            break
        b += 1
    return float(words[a][0]), float(words[b][1])


def start_names(words: list, hits: list[dict]) -> list[tuple[float, str]]:
    """Un nombre al EMPEZAR la frase («Juan falleció ayer»): find_mentions no lo cuenta (podría ser la mayúscula de
    inicio de frase), pero si justo detrás va «falleció», «murió», «nos dejó»…, es de quien se habla."""
    from .mentions import STOP
    out = []
    for h in hits:
        k = h["i"] - 1
        if k < 0 or not PERSONA.match(_norm(h["word"])):
            continue
        txt = str(words[k][2]).strip(" ,.;:¿?¡!\"'«»")
        key = _norm(txt)
        if txt[:1].isupper() and len(key) >= 3 and key not in STOP and key not in NEG \
                and not any(rx.fullmatch(key) for rx, _c, _w in _rules_cache()):
            out.append((float(words[k][0]), txt))
    return out


PERSONA = re.compile(r"(falleci|muri|muere|nos (ha )?dej|se nos|nos dejo|ya no esta)")


_RULES = {}


def _rules_cache() -> list:
    if "r" not in _RULES:
        _RULES["r"] = [(re.compile(pat), c, w) for pat, c, w in LEXICO]
    return _RULES["r"]


def timeline_words(p) -> list[tuple[float, float, str]]:
    """Todas las palabras que suenan en la línea de tiempo (de cada transcripción), por orden."""
    from ..core import subtitles
    out = []
    for mid in list(getattr(p, "transcripts", {}) or {}):
        if mid not in p.media:
            continue
        try:
            out += [(a, b, txt) for a, b, txt, _i in subtitles.timeline_words(p, mid)]
        except Exception:  # noqa: BLE001 - una transcripción rara no rompe las demás
            continue
    out.sort(key=lambda w: w[0])
    return out


def mention_names(p, extra_terms=None, glossary=None) -> list[tuple[float, str]]:
    """[(segundo de la línea de tiempo, nombre)]: personas, nombres propios y tus palabras clave (🔑 / glosario)."""
    from .mentions import find_mentions
    try:
        ms = find_mentions(p, extra_terms=extra_terms, glossary=glossary)
    except Exception:  # noqa: BLE001 - sin nombres, la casilla «solo si nombro…» no propone nada
        return []
    out = []
    for e in ms:
        nombre = clean_name(e["term"])
        if nombre:
            out += [(float(h["tl"]), nombre) for h in e["hits"] if h.get("tl") is not None]
    return out


def clean_name(name: str) -> str:
    """Sin las palabras del léxico pegadas al nombre («Lamentablemente Pedro Gómez» → «Pedro Gómez»)."""
    partes = [w for w in str(name or "").split()
              if not any(rx.fullmatch(_norm(w)) for rx, _c, _w in _rules_cache())]
    return " ".join(partes)


# ------------------------------------------------------------------ los clips
def scope_clips(p, clip_ids=None) -> list:
    """Clips de video/imagen visibles (no textos ni sonido): los elegidos o, si no hay, todos."""
    out = []
    for c in p.clips.values():
        tr = p.track(c.track_id)
        m = p.media.get(c.media_id)
        if tr is None or tr.kind != TRACK_VIDEO or c.text is not None or not c.enabled or m is None \
                or m.kind == KIND_AUDIO:
            continue
        out.append(c)
    if clip_ids:
        ids = set(clip_ids)
        elegidos = [c for c in out if c.id in ids]
        out = elegidos
    out.sort(key=lambda c: (c.start, c.track_id))
    return out


def _ya_gris(c) -> bool:
    return bool((c.fx or {}).get("bw")) or float((c.color or {}).get("saturation", 0.0) or 0.0) <= -0.5


def tone_proposals(p, clips: list, words: list, *, mode: str = "bw", need_name: bool = False,
                   names: list | None = None, lexicon: tuple | None = None) -> list[dict]:
    """🖤 Gris donde el tono es triste, fuerte o difícil. [{id, kind:"gris", mode, clip_id, track_id, t, span,
    name, reason, words}] — span = (ini, fin) solo en clips largos (se corta al aplicar)."""
    hits = tone_hits(words, lexicon)
    if not hits:
        return []
    names = sorted(list(names or []) + start_names(words, hits))
    por_frase: dict = {}
    for h in hits:
        h["span"] = sentence_span(words, h["i"])
        por_frase.setdefault(h["span"], []).append(h["w"])
    for h in hits:            # una palabra ambigua sola no basta: el más fuerte de la frase + un poco por cada otra
        ws = por_frase[h["span"]]
        h["score"] = max(ws) + SUMA_EXTRA * (len(ws) - 1)
    hits = [h for h in hits if h["score"] >= UMBRAL - 1e-9]
    if not hits:
        return []
    for h in hits:
        a, b = h["span"]
        cerca = [n for t, n in names if a - NOMBRE_CERCA <= t <= b + NOMBRE_CERCA]
        h["name"] = cerca[0] if cerca else None
    if need_name:
        hits = [h for h in hits if h["name"]]
    out = []
    for c in clips:
        if _ya_gris(c):
            continue
        lo, hi = c.start - PRE, c.end
        mine = [h for h in hits if min(hi, h["span"][1]) - max(lo, h["span"][0]) > 0.25]
        if not mine:
            continue
        if c.duration > LARGO:                       # clip largo: solo los tramos de las frases (unidos si se tocan)
            tramos: list[list] = []
            for h in mine:
                a, b = max(c.start, h["span"][0] - 0.2), min(c.end, h["span"][1] + 0.5)
                if b - a < 0.5:
                    continue
                if tramos and a - tramos[-1][1] < 1.5:
                    tramos[-1][1] = max(tramos[-1][1], b)
                    tramos[-1][2].append(h)
                else:
                    tramos.append([a, b, [h]])
            grupos = [(a, b, hs) for a, b, hs in tramos]
        else:
            grupos = [(None, None, mine)]
        for a, b, hs in grupos:
            best = max(hs, key=lambda h: h["w"])
            palabras = list(dict.fromkeys(h["word"] for h in hs))[:3]
            razon = "dice " + ", ".join(f"«{w}»" for w in palabras)
            nombre = next((h["name"] for h in hs if h["name"]), None)
            if nombre:
                razon += f" y nombra a «{nombre}»"
            razon += ": " + CAT_ES.get(best["cat"], "tono triste")
            if a is not None:
                from ..core.keyword_place import mmss
                razon += f" (solo el tramo {mmss(a)}–{mmss(b)})"
            out.append({"id": uuid.uuid4().hex[:10], "kind": "gris", "mode": mode, "clip_id": c.id,
                        "track_id": c.track_id, "t": round(a if a is not None else c.start, 3),
                        "span": (round(a, 3), round(b, 3)) if a is not None else None,
                        "name": ICONO.get(mode, ICONO["bw"]), "reason": razon, "cat": best["cat"]})
    return out


# ------------------------------------------------------------------ caras en las fotos
_lock = threading.Lock()
DETECTOR = None      # (pruebas) función imagen BGR → [(x, y, ancho, alto, confianza)] en 0–1, en vez de OpenCV
MAX_LADO = 640


def _cache_path() -> str:
    from ..core.paths import cache_dir
    return str(cache_dir("caras_imagenes") / "caras.json")


def _cache_load() -> dict:
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _firma(path: str) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return f"{st.st_size}:{int(st.st_mtime)}"


def _leer_pequena(path: str):
    """La imagen a ≤ MAX_LADO px (BGR) o None. Los recortes PNG casi transparentes → "recorte"."""
    import cv2
    import numpy as np
    data = np.fromfile(path, np.uint8)          # (rutas con tildes en Windows)
    if not data.size:
        return None
    if path.lower().endswith((".png", ".webp", ".tif", ".tiff")):
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is not None and img.ndim == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3]
            if float((alpha < 16).mean()) > 0.2:
                return "recorte"
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif img is not None and img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        flag = cv2.IMREAD_COLOR
        if data.size > 6_000_000:
            flag = cv2.IMREAD_REDUCED_COLOR_4
        elif data.size > 2_000_000:
            flag = cv2.IMREAD_REDUCED_COLOR_2
        img = cv2.imdecode(data, flag)
    if img is None:
        return None
    h, w = img.shape[:2]
    s = MAX_LADO / max(h, w)
    if s < 1.0:
        img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    return img


def _detectar(img) -> dict | None:
    """Cara (YuNet de OpenCV) o, si no hay, persona (HOG); en proporciones 0–1."""
    if DETECTOR is not None:
        caras = DETECTOR(img)
    else:
        try:
            from . import tracking
            caras = tracking.detect_faces(img)
        except Exception:  # noqa: BLE001 - sin el detector de caras (sin internet la 1.ª vez…): solo personas
            caras = []
    caras = [f for f in caras if f[4] >= 0.6 and f[2] * f[3] >= 0.0015]
    if caras:
        x, y, w, h, conf = caras[0]
        return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4), "kind": "cara",
                "conf": round(float(conf), 3)}
    if DETECTOR is not None:
        return None
    try:
        import cv2
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        H, W = img.shape[:2]
        if min(H, W) < 128:
            return None
        rects, weights = hog.detectMultiScale(img, winStride=(8, 8), padding=(8, 8), scale=1.08)
        best = None
        for (x, y, w, h), wt in zip(rects, [float(v) for v in (weights.ravel() if len(rects) else [])]):
            if wt >= 0.8 and (best is None or w * h > best[2] * best[3]):
                best = (x, y, w, h, wt)
        if best is None:
            return None
        x, y, w, h, wt = best
        # la cabeza: arriba del cuerpo
        return {"x": round((x + w * 0.3) / W, 4), "y": round(y / H, 4), "w": round(w * 0.4 / W, 4),
                "h": round(h * 0.18 / H, 4), "kind": "persona", "conf": round(min(1.0, wt / 2), 3)}
    except Exception:  # noqa: BLE001
        return None


def image_face(path: str, use_cache: bool = True) -> dict | None:
    """La cara (o persona) más grande de la foto, o None. Una sola vez por archivo: se guarda en caché."""
    firma = _firma(path)
    if firma is None:
        return None
    key = os.path.normcase(os.path.abspath(path))
    if use_cache:
        with _lock:
            hit = _cache_load().get(key)
        if hit and hit.get("firma") == firma:
            return hit.get("face")
    try:
        img = _leer_pequena(path)
    except Exception:  # noqa: BLE001 - imagen que OpenCV no lee: sin zoom
        img = None
    face = None if img is None or isinstance(img, str) else _detectar(img)
    if use_cache:
        with _lock:
            data = _cache_load()
            data[key] = {"firma": firma, "face": face}
            if len(data) > 4000:                     # (que no crezca sin fin)
                data = dict(list(data.items())[-3000:])
            tmp = _cache_path() + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, _cache_path())
            except OSError:
                pass
    return face


def cached_face(path: str):
    """(True, cara) si ya está en caché; (False, None) si hay que mirarla."""
    firma = _firma(path)
    if firma is None:
        return True, None
    with _lock:
        hit = _cache_load().get(os.path.normcase(os.path.abspath(path)))
    if hit and hit.get("firma") == firma:
        return True, hit.get("face")
    return False, None


def face_zoom_kf(duration: float, face: dict) -> list[dict]:
    """🔍 Zoom dinámico (Ken Burns suave) de la foto entera hacia la cara: claves de imagen (t desde 0)."""
    cx = min(max(face["x"] + face["w"] / 2, 0.0), 1.0)
    cy = min(max(face["y"] + face["h"] * 0.45, 0.0), 1.0)      # (los ojos, algo por encima del centro)
    z = min(1.6, max(1.2, 0.32 / max(face["h"], 1e-3)))
    return [{"t": 0.0, "z": 1.0, "x": 0.5, "y": 0.5},
            {"t": round(max(0.5, float(duration)), 3), "z": round(z, 3), "x": round(cx, 4), "y": round(cy, 4)}]


def image_clips_for_zoom(p, clips: list) -> list:
    """Fotos donde cabe un zoom: imágenes sin zoom ni animación propia."""
    from ..core import transform
    out = []
    for c in clips:
        m = p.media.get(c.media_id)
        if m is None or m.kind != KIND_IMAGE or not m.path:
            continue
        if transform.is_zoomed(c.zoom_kf or []) or getattr(c, "layout_kf", None):
            continue
        out.append(c)
    return out


def zoom_proposals(p, clips: list, faces: dict) -> list[dict]:
    """faces = {ruta: cara o None}. [{id, kind:"zoom", clip_id, t, zoom_kf, name, reason}]"""
    out = []
    for c in image_clips_for_zoom(p, clips):
        m = p.media[c.media_id]
        face = faces.get(m.path)
        if not face:
            continue
        kf = face_zoom_kf(c.duration, face)
        que = "una cara" if face.get("kind") == "cara" else "una persona"
        out.append({"id": uuid.uuid4().hex[:10], "kind": "zoom", "clip_id": c.id, "track_id": c.track_id,
                    "t": round(c.start, 3), "zoom_kf": kf, "name": "🔍 Zoom a la cara",
                    "reason": f"se ve {que} en la foto: zoom dinámico hacia ella (1,0× → {kf[-1]['z']:.2f}×)"})
    return out


# ------------------------------------------------------------------ ⭐ las reglas de «Mis efectos para la IA»
STAR_KINDS = ("senala", "pasado", "negativo", "positivo")


def star_proposals(p, clips: list, keys: list[str], freq: str = "normal") -> list[dict]:
    """Tus ⭐ efectos donde lo pide lo que dices (fíjense, hace años, desastre, increíble…), solo en esos clips."""
    if not keys or not clips:
        return []
    from . import effect_memory as EM
    ids = {c.id for c in clips}
    moments = [m for m in EM.find_moments(p, {}, {}, clip_ids=ids) if m["kind"] in STAR_KINDS]
    out = []
    for x in EM.propose(p, moments, keys, EM.load_store(), freq):
        if x["clip_id"] not in ids or EM.effect_info(x["effect"])["type"] == "transition":
            continue
        out.append(dict(x, kind="star", star_kind=x["kind"], name="⭐ " + x["name"],
                        track_id=p.clips[x["clip_id"]].track_id))
    return out


def merge(tone: list, zoom: list, star: list) -> list[dict]:
    """Todo junto, por orden, sin pisar el gris con un ⭐ de color en el mismo clip, y sin zoom en una foto larga que
    el gris va a cortar por tramos (el zoom de toda la foto quedaría partido)."""
    grises = {x["clip_id"] for x in tone}
    cortados = {x["clip_id"] for x in tone if x.get("span")}
    star = [x for x in star if not (x["clip_id"] in grises and x.get("apply") == "clip")]
    zoom = [x for x in zoom if x["clip_id"] not in cortados]
    return sorted(tone + zoom + star, key=lambda x: (x["t"], x["kind"]))
