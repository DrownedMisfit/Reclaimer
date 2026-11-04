"""
Módulo de IA: ENTENDER LA BIBLIOTECA A FONDO.

Para que, cuando hablas de algo («el Jefe Maestro», «Cortana», «los Locust»), el editor sepa
en qué imagen, cinemática o momento del gameplay aparece.

1. Análisis a fondo de cada clip: un fotograma por segundo (no solo 12 por clip), el plano
   entero y el centro, y la división en planos (cada vez que cambia la imagen).
2. Quién/qué hay en tu biblioteca («entidades»), sacado de:
     - tus IMÁGENES: «jefe maestro.png» le enseña a la IA cómo es el Jefe Maestro
       (es la forma más fiable: luego lo busca en tus videos por parecido visual),
     - los nombres de tus archivos y carpetas,
     - los nombres propios que dices en la narración,
     - un glosario de apodos que puedes editar («Jefe Maestro = Master Chief, John-117»).
3. Un índice: para cada nombre, los planos donde aparece, ordenados por seguridad.

Todo local y gratis. Tarda (≈1 min por cada hora de video), pero se guarda en caché.
"""
from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from . import embeddings
from .base import CancelFn, ProgressFn, check_cancel, report

VERSION = 1
STEP = 1.0              # un fotograma por segundo
SHOT_CUT = 0.80         # parecido mínimo entre segundos seguidos para seguir en el mismo plano

STARTER_GLOSSARY = """\
Jefe Maestro = Master Chief, John-117, el Jefe
Cortana
Pacto = Covenant
Inundación = Flood
Precursores = Forerunner, Forerunners
Inquisidor = Arbiter, Árbitro
Spartan = Spartans, Espartano, Espartanos
Marcus Fenix = Marcus
Dominic Santiago = Dom
Kait Diaz = Kait
Locust = Locusts
Kratos
Atreus
Link
Zelda
Ganondorf = Ganon
Leon Kennedy = Leon S. Kennedy
Arthur Morgan
"""

STOP = set("""el la los las un una unos unas de del al y o que en por para con sin se su sus lo le les me te nos
mi mis tu tus es son fue era pero como más mas muy ya no si sí este esta estos estas ese esa esos esas eso esto
aquí ahí allí hoy ahora porque cuando donde quien qué cómo cuál todo toda todos todas nada algo también tampoco
bueno pues entonces además hola gracias video videos juego juegos parte cosa cosas vez veces año años""".split())


def norm(text: str) -> str:
    """minúsculas y sin acentos (para comparar nombres)."""
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch)).strip()


# --------------------------------------------------------------- análisis a fondo
def _deep_path(path: str) -> str:
    return str(cache_dir("huellas_a_fondo") / f"{media_tools.cache_key(path)}_v{VERSION}.npz")


_DEEP_MEM: dict = {}          # ruta del análisis -> (fecha, resultado): se lee del disco una sola vez


def load_deep(path: str) -> dict | None:
    try:
        f = _deep_path(path)
        if os.path.exists(f):
            mt = os.path.getmtime(f)
            hit = _DEEP_MEM.get(f)
            if hit is not None and hit[0] == mt:
                return hit[1]
            d = np.load(f)
            res = {"times": d["times"], "vecs": d["vecs"].astype(np.float32), "shots": d["shots"],
                   "letterbox": float(d["letterbox"])}
            if len(_DEEP_MEM) > 400:
                _DEEP_MEM.clear()
            _DEEP_MEM[f] = (mt, res)
            return res
    except (OSError, ValueError, KeyError):
        pass
    return None


def _frames(path: str, vf: str, cancelled: CancelFn = None, size: int = 224):
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-skip_loop_filter", "all",   # ⚡ sin filtro de desbloqueo: ~25 % más rápido; en imágenes pequeñas para analizar no cambia nada
            "-i", path, "-an", "-sn", "-vf", vf,
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=flags)
    n = size * size * 3
    try:
        k = 0
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            if cancelled is not None and k % 50 == 0:
                check_cancel(cancelled)
            yield np.frombuffer(buf, np.uint8).reshape(size, size, 3)
            k += 1
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def analyze_deep(path: str, kind: str, duration: float, progress: ProgressFn = None,
                 cancelled: CancelFn = None) -> dict:
    """{"times", "vecs", "shots" [[ini, fin]], "letterbox"}: plano entero + centro, cada segundo."""
    cached = load_deep(path)
    if cached is not None:
        return cached
    from .clip_analysis import letterbox_ratio
    enc = embeddings.get("clip_image", progress)
    full = "scale=224:224:force_original_aspect_ratio=decrease,pad=224:224:(ow-iw)/2:(oh-ih)/2:black"
    center = "scale=224:224:force_original_aspect_ratio=increase,crop=224:224"
    if kind == "image":
        vf_f, vf_c = full, center
    else:
        vf_f, vf_c = f"fps={1 / STEP:g}," + full, f"fps={1 / STEP:g}," + center
    vecs_f, vecs_c, sample = [], [], []
    batch_f, batch_c = [], []
    total = max(1, int(duration / STEP)) if kind != "image" else 1
    done = 0
    for ff, fc in zip(_frames(path, vf_f, cancelled), _frames(path, vf_c, cancelled)):
        batch_f.append(ff)
        batch_c.append(fc)
        if len(sample) < 40 and done % max(1, total // 40) == 0:
            sample.append(fc)
        if len(batch_f) == 32:
            vecs_f.append(enc.encode(np.stack(batch_f), batch=32))
            vecs_c.append(enc.encode(np.stack(batch_c), batch=32))
            done += len(batch_f)
            batch_f, batch_c = [], []
            report(progress, min(0.99, done / total), "")
    if batch_f:
        vecs_f.append(enc.encode(np.stack(batch_f), batch=32))
        vecs_c.append(enc.encode(np.stack(batch_c), batch=32))
    if not vecs_f:
        raise RuntimeError("no se pudieron leer fotogramas")
    vf_ = np.concatenate(vecs_f)
    vc_ = np.concatenate(vecs_c)
    n = len(vf_)
    t = np.arange(n, dtype=np.float32) * STEP + (0.0 if kind == "image" else STEP / 2)
    # Planos: cuando la imagen cambia mucho de un segundo al siguiente
    shots, a = [], 0.0
    for i in range(1, n):
        if float(vf_[i] @ vf_[i - 1]) < SHOT_CUT:
            shots.append((a, i * STEP))
            a = i * STEP
    shots.append((a, max(a + STEP, duration if kind != "image" else STEP)))
    lb = letterbox_ratio(np.stack(sample)) if len(sample) >= 2 else 0.0
    res = {"times": np.concatenate([t, t]), "vecs": np.concatenate([vf_, vc_]).astype(np.float32),
           "shots": np.array(shots, np.float32), "letterbox": float(lb)}
    np.savez_compressed(_deep_path(path), times=res["times"], vecs=res["vecs"].astype(np.float16),
                        shots=res["shots"], letterbox=res["letterbox"])
    return res


# --------------------------------------------------------------------- entidades
@dataclass
class Entity:
    name: str                                   # cómo lo llamas («Jefe Maestro»)
    aliases: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)    # imágenes de tu biblioteca que lo muestran
    source: str = ""                            # glosario | imagen | narración | archivo

    def all_names(self) -> list[str]:
        return [self.name] + [a for a in self.aliases if norm(a) != norm(self.name)]


def parse_glossary(text: str) -> list[Entity]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("=")
        aliases = [a.strip() for a in rest.split(",") if a.strip()]
        out.append(Entity(name.strip(), aliases, source="glosario"))
    return out


def label_from_name(filename: str) -> str:
    """«jefe_maestro_02.png» → «jefe maestro»"""
    base = os.path.splitext(os.path.basename(filename))[0]
    base = re.sub(r"[_\-.]+", " ", base)
    base = re.sub(r"\b(\d+|img|image|imagen|captura|screenshot|copy|copia|final|hd|4k)\b", " ", base, flags=re.I)
    return re.sub(r"\s+", " ", base).strip()


def narration_names(words: list, min_count: int = 1) -> list[str]:
    """Nombres propios que dices: palabras con mayúscula que no empiezan frase («Jefe Maestro»)."""
    out: dict[str, int] = {}
    cur: list[str] = []
    prev_end = True

    def flush():
        if cur:
            phrase = " ".join(cur)
            if norm(phrase) not in STOP and len(phrase) >= 3:
                out[phrase] = out.get(phrase, 0) + 1
        cur.clear()
    for w in words:
        raw = str(w[2]).strip()
        token = raw.strip(".,;:¡!¿?…\"'()«»")
        cap = token[:1].isupper() and not token.isupper() or (token.isupper() and len(token) >= 2)
        if cap and not prev_end and norm(token) not in STOP:
            cur.append(token)
            if len(cur) >= 3:
                flush()
        else:
            flush()
        prev_end = raw.endswith((".", "?", "!", "…"))
        if prev_end:
            flush()
    flush()
    return [k for k, v in sorted(out.items(), key=lambda kv: -kv[1]) if v >= min_count]


def matches(entity: Entity, text: str) -> bool:
    """¿Se menciona esta entidad en el texto? (sin importar mayúsculas ni acentos)"""
    t = " " + re.sub(r"[^a-z0-9ñ\- ]+", " ", norm(text)) + " "
    for n in entity.all_names():
        k = re.sub(r"[^a-z0-9ñ\- ]+", " ", norm(n)).strip()
        if k and f" {k} " in t:
            return True
    return False


def build_entities(media: list[dict], words: list, glossary_text: str) -> list[Entity]:
    """media: [{media_id, name, kind, tags}]  ·  words: palabras de la narración."""
    ents = parse_glossary(glossary_text)

    def find(name: str) -> Entity | None:
        return next((e for e in ents if any(norm(n) == norm(name) for n in e.all_names())), None)

    # Imágenes: su nombre dice qué muestran
    for m in media:
        if m["kind"] != "image":
            continue
        label = label_from_name(m["name"])
        if len(label) < 3:
            continue
        e = find(label) or next((x for x in ents if matches(x, label)), None)
        if e is None:
            e = Entity(label.title(), source="imagen")
            ents.append(e)
        e.refs.append(m["media_id"])
    # Nombres propios de la narración
    for phrase in narration_names(words):
        if find(phrase) is None and not any(matches(e, phrase) for e in ents):
            ents.append(Entity(phrase, source="narración"))
    return ents


# ------------------------------------------------------------------------ índice
@dataclass
class Hit:
    media_id: str
    time: float          # mejor segundo
    start: float         # plano
    end: float
    score: float


def _robust_z(x: np.ndarray) -> np.ndarray:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) * 1.4826 + 1e-6
    return (x - med) / mad


def build_index(entities: list[Entity], data: dict[str, dict], meta: dict[str, str],
                progress: ProgressFn = None, z_min: float = 3.0) -> dict[str, list[Hit]]:
    """data: {media_id: {"times","vecs","shots","kind"}}  ·  meta: {media_id: texto de nombre/carpeta}.
    Devuelve {nombre: [Hit…]} ordenado de más a menos seguro."""
    if not data or not entities:
        return {}
    enc = embeddings.get("clip_text", progress)
    mids = list(data)
    all_vecs = np.concatenate([data[m]["vecs"] for m in mids])
    owner = np.concatenate([np.full(len(data[m]["vecs"]), i) for i, m in enumerate(mids)])
    times = np.concatenate([np.asarray(data[m]["times"], np.float32) for m in mids])
    # «Centrar»: quitar lo que TODOS tus fotogramas tienen en común (p. ej. «escena oscura de videojuego»)
    # para que destaque lo que distingue a cada uno. Mejora mucho la búsqueda por parecido.
    mu = all_vecs.mean(0)
    centered = all_vecs - mu
    centered /= np.linalg.norm(centered, axis=1, keepdims=True) + 1e-9
    pos = {m: 0 for m in mids}
    k0 = 0
    for m in mids:
        pos[m] = k0
        k0 += len(data[m]["vecs"])
    out: dict[str, list[Hit]] = {}
    for e in entities:
        names = e.all_names()
        prompts = [p for n in names for p in (n, f"una imagen de {n}", f"{n} en un videojuego")]
        tv = enc.encode(prompts).mean(0)
        tv /= np.linalg.norm(tv) + 1e-9
        s_text = all_vecs @ tv
        score = _robust_z(s_text)
        refs = [r for r in e.refs if r in data]
        need = z_min
        ex_pos, ex_neg = (None, None)
        try:
            from .image_feedback import video_examples
            ex_pos, ex_neg = video_examples(names)
        except Exception:  # noqa: BLE001 - sin ejemplos guardados
            pass
        if refs or ex_pos is not None:
            parts = [centered[pos[r]:pos[r] + len(data[r]["vecs"])] for r in refs]
            if ex_pos is not None:   # los momentos que marcaste ✓ al buscar este nombre
                ex = ex_pos - mu
                parts.append(ex / (np.linalg.norm(ex, axis=1, keepdims=True) + 1e-9))
            rv = np.concatenate(parts).mean(0)
            rv /= np.linalg.norm(rv) + 1e-9
            # Parecido visual a tus imágenes de referencia: es lo más fiable, pesa mucho más que el nombre
            score = 0.15 * score + 0.85 * _robust_z(centered @ rv)
        else:
            need = z_min + 0.5      # solo con el nombre, más exigente (evita falsos positivos)
        if ex_neg is not None:      # lo que marcaste ✗: se aparta
            nv = ex_neg - mu
            nv /= np.linalg.norm(nv, axis=1, keepdims=True) + 1e-9
            score = score - 0.6 * np.maximum(0.0, _robust_z((centered @ nv.T).max(axis=1)) - 1.0)
        # Afinar: los momentos más claros sirven de nueva referencia (encuentra más apariciones)
        top = [i for i in np.argsort(-score)[:6] if score[i] > need]
        if top:
            pv = centered[top].mean(0)
            pv /= np.linalg.norm(pv) + 1e-9
            score = 0.6 * score + 0.4 * _robust_z(centered @ pv)
        # Nombre en el archivo o la carpeta: cuenta como aparición
        named = {i for i, m in enumerate(mids) if any(f" {norm(n)} " in f" {norm(meta.get(m, ''))} " for n in names)}
        hits: list[Hit] = []
        for i, m in enumerate(mids):
            sel = owner == i
            sc, tt = score[sel], times[sel]
            if not len(sc):
                continue
            boost = 2.0 if i in named else 0.0
            shots = data[m].get("shots")
            if shots is None or not len(shots) or data[m].get("kind") == "image":
                k = int(np.argmax(sc))
                if sc[k] + boost > need or i in named:
                    hits.append(Hit(m, float(tt[k]), 0.0, float(data[m].get("duration", 0) or 0), float(sc[k] + boost)))
                continue
            for a, b in shots:
                inside = (tt >= a) & (tt < b)
                if not inside.any():
                    continue
                k = int(np.argmax(np.where(inside, sc, -1e9)))
                if sc[k] + boost > need:
                    hits.append(Hit(m, float(tt[k]), float(a), float(b), float(sc[k] + boost)))
        hits.sort(key=lambda h: -h.score)
        if hits:
            out[e.name] = hits
    return out
