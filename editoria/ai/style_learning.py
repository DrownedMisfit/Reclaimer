"""
Módulo de IA: APRENDIZAJE DE MI ESTILO DE EDICIÓN (opcional, apagado de fábrica).

Privacidad:
  · Solo funciona si lo activas (y no está en pausa) y solo mientras Reclaimer está abierto.
  · Solo mira lo que pasa DENTRO del editor (los pasos de deshacer/rehacer y el proyecto); nunca el ratón,
    el teclado, otras ventanas ni otras carpetas. Nada sale de tu PC.
  · Todo se guarda en un archivo (aprendizaje_estilo.json) que puedes borrar con un botón.

Cómo aprende (sin modelos de IA corriendo: son estadísticas, milisegundos):
  A · mientras editas: solo cuenta acciones pequeñas en memoria (cortar, mover, borrar…; lo que deshaces
      enseguida no cuenta: suele ser un error).
  B · al guardar o cerrar: resume el proyecto (duración de planos, transiciones, zooms, música, textos,
      silencios que quitas…) y, si la IA hizo una primera versión, compara lo que propuso con tu resultado
      final («propuesta → tus cambios → resultado»).
  C · «Analizar esta sesión» cuando quieras.
  Un patrón solo se vuelve preferencia si se repite en VARIOS proyectos (nunca por una acción suelta),
  con una confianza que puedes ver; tú lo aceptas, lo editas o lo borras.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import date

import numpy as np

from ..core.model import (KIND_IMAGE, ORIGIN_AI, SUG_APPLIED, SUG_REJECTED, TRACK_AUDIO, TRACK_TEXT,
                          TRACK_VIDEO, Project)
from ..core.paths import app_data_dir

KINDS = {"youtube": "Videos largos", "short": "Shorts", "edit": "Edits"}
SUBTYPES = ["Crítica", "Gameplay", "Video narrativo", "Noticias", "Otro"]
AI_MARKS = ("IA ·", "Primera versión", "Edit musical", "✨", "Rellenar", "B-roll")

# (clave, nombre, formato)
PATTERNS = [
    ("clip_len", "Duración de los planos", "{:.1f} s"),
    ("cuts_min", "Cortes por minuto", "{:.0f}"),
    ("trans_min", "Transiciones por minuto", "{:.1f}"),
    ("zoom_share", "Planos con zoom", "{:.0%}"),
    ("fx_share", "Planos con efectos", "{:.0%}"),
    ("image_share", "Imágenes entre los planos", "{:.0%}"),
    ("text_min", "Textos por minuto", "{:.1f}"),
    ("music_share", "Música de fondo", "{:.0%} del video"),
    ("silence_cut", "Silencios que quitas", "{:.0%}"),
    ("filler_cut", "Muletillas y repeticiones que quitas", "{:.0%}"),
    ("speed_share", "Planos con cambio de velocidad", "{:.0%}"),
    ("first_shot", "Primer plano (inicio)", "{:.1f} s"),
    ("vtracks", "Pistas de video usadas", "{:.0f}"),
    ("ai_kept", "De lo que propone la IA, conservas", "{:.0%}"),
]
PATTERN_NAMES = {k: n for k, n, _f in PATTERNS}

_lock = threading.Lock()


# ------------------------------------------------------------------ archivo
def _path() -> str:
    return str(app_data_dir() / "aprendizaje_estilo.json")


def load() -> dict:
    with _lock:
        try:
            with open(_path(), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
    d.setdefault("settings", {"enabled": False, "paused": False, "low_priority": True})
    d.setdefault("projects", {})
    d.setdefault("prefs", {})
    return d


def save(d: dict):
    with _lock:
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path())


def delete_profile() -> None:
    """Empezar de cero: borra todo lo aprendido (los ajustes de activado/pausa se conservan)."""
    d = load()
    save({"settings": d["settings"], "projects": {}, "prefs": {}})


def project_key(path: str | None) -> str | None:
    return os.path.normcase(os.path.abspath(path)) if path else None


# ------------------------------------------------------------------ resumen de un proyecto
def features(p: Project, ai_ids: set | None = None) -> dict:
    """Cómo está editado un proyecto (números simples, comparables entre proyectos)."""
    tracks = {t.id: t for t in p.tracks}
    vis = [c for c in p.clips.values() if tracks.get(c.track_id) and tracks[c.track_id].kind == TRACK_VIDEO
           and c.text is None and c.enabled]
    texts = [c for c in p.clips.values() if (tracks.get(c.track_id) and tracks[c.track_id].kind == TRACK_TEXT)
             or c.text is not None]
    music = [c for c in p.clips.values() if tracks.get(c.track_id) and tracks[c.track_id].kind == TRACK_AUDIO
             and tracks[c.track_id].duck_db is not None and c.enabled]
    end = max([c.end for c in p.clips.values()] or [0.0])
    out: dict = {"duration": round(end, 2), "n_clips": len(vis)}
    if not vis or end < 5:
        return out
    mins = end / 60
    lens = np.array([c.duration for c in vis])
    out["clip_len"] = round(float(np.median(lens)), 2)
    out["cuts_min"] = round(len(vis) / mins, 2)
    out["trans_min"] = round(sum(1 for c in vis if (c.fx or {}).get("trans")) / mins, 2)
    out["zoom_share"] = round(sum(1 for c in vis if c.zoom_kf) / len(vis), 3)
    looks = ("flash", "shake", "glitch", "invert", "bw", "vignette", "grain", "blur", "oldfilm", "warm", "cold",
             "letterbox")
    out["fx_share"] = round(sum(1 for c in vis if any((c.fx or {}).get(k) for k in looks)) / len(vis), 3)
    out["image_share"] = round(sum(1 for c in vis if p.media.get(c.media_id) and
                                   p.media[c.media_id].kind == KIND_IMAGE) / len(vis), 3)
    out["text_min"] = round(len(texts) / mins, 2)
    covered = sum(c.duration for c in music)
    out["music_share"] = round(min(1.0, covered / end), 3)
    out["speed_share"] = round(sum(1 for c in vis if c.speed != 1.0) / len(vis), 3)
    first = min(vis, key=lambda c: c.start)
    out["first_shot"] = round(first.duration, 2)
    out["vtracks"] = len({c.track_id for c in vis})
    for key, kinds in (("silence_cut", ("silence",)), ("filler_cut", ("filler", "repeat", "retake"))):
        s = [x for x in p.suggestions if x.kind in kinds and x.status in (SUG_APPLIED, SUG_REJECTED)]
        if len(s) >= 3:
            out[key] = round(sum(1 for x in s if x.status == SUG_APPLIED) / len(s), 3)
    if ai_ids:
        out["ai_kept"] = round(sum(1 for i in ai_ids if i in p.clips) / len(ai_ids), 3)
    return out


def ai_clip_ids(p: Project) -> set:
    return {c.id for c in p.clips.values() if c.origin == ORIGIN_AI}


# ------------------------------------------------------------------ sesión (lo que observa en vivo)
class Session:
    """Lo que se apunta mientras editas: solo contadores en memoria (nada se escribe hasta guardar/cerrar)."""

    def __init__(self):
        self.actions: dict[str, int] = {}
        self._last: tuple[int, str, float] | None = None
        self.baseline: dict | None = None
        self.baseline_ai: set = set()
        self.started = time.time()

    def on_index(self, index: int, text: str, project: Project):
        """Cada paso de deshacer/rehacer. Si deshaces enseguida lo que acabas de hacer, no cuenta."""
        now = time.time()
        if self._last and index < self._last[0] and now - self._last[2] < 15:
            label = self._last[1]
            if self.actions.get(label, 0) > 0:
                self.actions[label] -= 1
            self._last = None
            return
        if self._last and index <= self._last[0]:
            self._last = (index, text, now)
            return
        label = (text or "").split(":")[0].strip()[:40] or "?"
        self.actions[label] = self.actions.get(label, 0) + 1
        self._last = (index, label, now)
        if any(text.startswith(m) for m in AI_MARKS) and self.baseline is None:
            # La primera edición hecha por la IA en esta sesión: «propuesta inicial»
            self.baseline_ai = ai_clip_ids(project)
            self.baseline = features(project)


def end_session(d: dict, key: str, p: Project, s: Session | None, kind: str) -> dict | None:
    """Al guardar/cerrar (o «Analizar esta sesión»): guarda el resumen del proyecto y vuelve a calcular
    los patrones. Devuelve el registro del proyecto (None si este proyecto no se usa para aprender)."""
    rec = d["projects"].setdefault(key, {"kind": kind, "subtype": "", "learn": True, "sessions": 0,
                                         "name": p.name})
    rec["kind"] = kind
    rec["name"] = p.name
    if not rec.get("learn", True):
        return None
    ai = (s.baseline_ai if s and s.baseline_ai else None) or set(rec.get("ai_ids", [])) or None
    rec["final"] = features(p, ai)
    if s and s.baseline is not None and "baseline" not in rec:
        rec["baseline"] = s.baseline
        rec["ai_ids"] = sorted(s.baseline_ai)[:5000]
    if s:
        acts = rec.setdefault("actions", {})
        for k, v in s.actions.items():
            if v > 0:
                acts[k] = acts.get(k, 0) + v
        rec["minutes"] = round(rec.get("minutes", 0) + (time.time() - s.started) / 60, 1)
    rec["sessions"] = rec.get("sessions", 0) + 1
    rec["updated"] = date.today().isoformat()
    refresh_prefs(d)
    return rec


# ------------------------------------------------------------------ patrones y confianza
def _scope_records(d: dict, scope: str, key: str | None = None) -> list[dict]:
    """scope: "general" · un tipo ("youtube", "short", "edit") · "proyecto" (solo key)."""
    recs = []
    for k, r in d["projects"].items():
        if not r.get("learn", True) or "final" not in r:
            continue
        if scope == "proyecto" and k != key:
            continue
        if scope in KINDS and r.get("kind") != scope:
            continue
        recs.append(r)
    return recs


def patterns(d: dict, scope: str = "general", key: str | None = None) -> list[dict]:
    """[{key, name, value, text, n, confidence}] — la confianza sube con el número de proyectos y con lo
    parecidos que son entre sí (un proyecto suelto, o muy distinto a los demás, cuenta poco)."""
    recs = _scope_records(d, scope, key)
    out = []
    for k, name, fmt in PATTERNS:
        vals = np.array([r["final"][k] for r in recs if k in r.get("final", {})], np.float64)
        if not len(vals):
            continue
        med = float(np.median(vals))
        if len(vals) >= 4:             # proyectos muy raros (¿un error, un estilo distinto?) pesan poco
            mad = float(np.median(np.abs(vals - med))) or 1e-9
            vals = vals[np.abs(vals - med) / (1.4826 * mad) < 3.0] if mad > 1e-6 else vals
            med = float(np.median(vals))
        spread = float(np.median(np.abs(vals - med))) / (abs(med) + (0.15 if fmt.endswith("%}") else 0.5))
        n = len(vals)
        conf = (1 - math.exp(-n / 2.5)) / (1 + 2.5 * spread)
        out.append({"key": k, "name": name, "value": med, "text": fmt.format(med), "n": n,
                    "confidence": round(max(0.0, min(1.0, conf)), 3)})
    return out


def _delta(recs: list[dict], k: str) -> tuple[float, int]:
    ds = [r["final"][k] - r["baseline"][k] for r in recs
          if "baseline" in r and k in r["final"] and k in r["baseline"]]
    return (float(np.mean(ds)) if ds else 0.0), len(ds)


def detect_prefs(d: dict, scope: str) -> list[dict]:
    """Frases de preferencia a partir de los patrones con suficiente confianza (≥3 proyectos)."""
    pats = {p["key"]: p for p in patterns(d, scope)}
    tipo = KINDS.get(scope, "tus videos").lower()
    out = []

    def add(pid, text, value=None, unit=None, pat=None):
        p = pats.get(pat) if pat else None
        conf = p["confidence"] if p else 0.6
        out.append({"id": f"{scope}:{pid}", "scope": scope, "text": text, "value": value, "unit": unit,
                    "pattern": pat, "confidence": conf})

    def ok(k, min_n=3, min_c=0.5):
        return k in pats and pats[k]["n"] >= min_n and pats[k]["confidence"] >= min_c

    if ok("clip_len"):
        v = pats["clip_len"]["value"]
        word = "cortos" if v < 3.0 else ("largos" if v > 6.0 else "de duración media")
        add("clip_len", f"Prefieres planos {word} (≈{v:.1f} s) en {tipo}.", round(v, 1), "s", "clip_len")
    if ok("trans_min"):
        v = pats["trans_min"]["value"]
        if v < 0.3:
            add("trans_pocas", f"Utilizas pocas transiciones en {tipo}.", round(v, 2), "por min", "trans_min")
        elif v > 1.5:
            add("trans_muchas", f"Utilizas muchas transiciones en {tipo}.", round(v, 2), "por min", "trans_min")
    if ok("music_share"):
        v = pats["music_share"]["value"]
        if v > 0.5:
            add("musica_si", f"Sueles poner música de fondo en {tipo}.", round(v, 2), None, "music_share")
        elif v < 0.1:
            add("musica_no", f"Casi no usas música de fondo en {tipo}.", round(v, 2), None, "music_share")
    if ok("silence_cut"):
        v = pats["silence_cut"]["value"]
        if v > 0.7:
            add("silencios_fuera", "Normalmente eliminas los silencios largos.", round(v, 2), None, "silence_cut")
        elif v < 0.3:
            add("silencios_dejas", "Sueles dejar los silencios (pausas naturales).", round(v, 2), None, "silence_cut")
    if ok("zoom_share"):
        v = pats["zoom_share"]["value"]
        if v > 0.4:
            add("zooms_muchos", f"Usas muchos zooms en {tipo}.", round(v, 2), None, "zoom_share")
        elif 0.08 < v <= 0.4:
            add("zooms_ocasionales", f"Usas zooms de vez en cuando en {tipo}.", round(v, 2), None, "zoom_share")
    if ok("text_min") and pats["text_min"]["value"] > 1.0:
        add("texto_frecuente", f"Pones texto en pantalla con frecuencia en {tipo}.", None, None, "text_min")
    if ok("ai_kept", 2) and pats["ai_kept"]["value"] < 0.6:
        add("ia_cambias", f"Cambias bastante lo que propone la IA (conservas ≈{pats['ai_kept']['value']:.0%}).",
            None, None, "ai_kept")
    recs = _scope_records(d, scope)
    dt, n = _delta(recs, "trans_min")
    if n >= 2 and dt < -0.3:
        add("ia_quitas_trans", "Cuando la IA pone transiciones, sueles quitarlas.", None, None, "trans_min")
    dl, n = _delta(recs, "clip_len")
    if n >= 2 and dl > 0.8:
        add("ia_alargas", f"Alargas los planos que propone la IA (≈+{dl:.1f} s).", round(dl, 1), "s", "clip_len")
    elif n >= 2 and dl < -0.8:
        add("ia_acortas", f"Acortas los planos que propone la IA (≈{dl:.1f} s).", round(dl, 1), "s", "clip_len")
    return out


def refresh_prefs(d: dict):
    """Añade las preferencias nuevas como «detectada» (tú decides); actualiza la confianza de las que hay.
    Las rechazadas no vuelven a proponerse."""
    kinds = [k for k in KINDS if any(r.get("kind") == k and r.get("learn", True) for r in d["projects"].values())]
    scopes = kinds + (["general"] if len(kinds) >= 2 else [])   # «general» solo si mezclas tipos de video
    found = {}
    for sc in scopes:
        for p in detect_prefs(d, sc):
            found[p["id"]] = p
    for pid, p in found.items():
        cur = d["prefs"].get(pid)
        if cur is None:
            d["prefs"][pid] = dict(p, state="detectada")
        else:
            cur["confidence"] = p["confidence"]
            if cur.get("state") != "editada":
                cur["text"], cur["value"] = p["text"], p["value"]
    for pid, cur in d["prefs"].items():     # las que ya no se cumplen pierden confianza (no se borran solas)
        if pid not in found and cur.get("state") in ("detectada", "aceptada"):
            cur["confidence"] = round(cur.get("confidence", 0) * 0.8, 3)


# ------------------------------------------------------------------ usar el perfil
def hints(d: dict, kind: str) -> list[dict]:
    """Ajustes para la primera versión automática según tus preferencias ACEPTADAS (o editadas):
    [{setting, value, reason}]. Nunca se aplican solas: la ventana los preselecciona y te dice por qué."""
    if not d["settings"].get("enabled"):
        return []
    acc = {p["id"].split(":", 1)[1]: p for p in d["prefs"].values()
           if p.get("state") in ("aceptada", "editada") and p.get("scope") in (kind, "general")}
    # el tipo de video manda sobre lo general
    for p in d["prefs"].values():
        if p.get("state") in ("aceptada", "editada") and p.get("scope") == kind:
            acc[p["id"].split(":", 1)[1]] = p
    out = []
    if "clip_len" in acc and acc["clip_len"].get("value"):
        v = float(acc["clip_len"]["value"])
        pace = "fast" if v < 3.0 else ("slow" if v > 6.0 else "normal")
        out.append({"setting": "ritmo", "value": pace,
                    "reason": f"Ritmo «{ {'fast': 'rápido', 'normal': 'normal', 'slow': 'pausado'}[pace] }» porque en "
                              f"tus proyectos parecidos los planos duran ≈{v:.1f} s."})
    if "trans_pocas" in acc or "ia_quitas_trans" in acc:
        out.append({"setting": "estilo", "value": "natural",
                    "reason": "Estilo natural (sin transiciones con whoosh) porque sueles quitar las transiciones."})
    elif "trans_muchas" in acc:
        out.append({"setting": "estilo", "value": "cinematic",
                    "reason": "Estilo cinematográfico porque usas muchas transiciones."})
    if "silencios_fuera" in acc:
        out.append({"setting": "corte_silence", "value": True,
                    "reason": "Quito los silencios largos porque normalmente los eliminas."})
    elif "silencios_dejas" in acc:
        out.append({"setting": "corte_silence", "value": False,
                    "reason": "Dejo los silencios porque sueles conservar las pausas."})
    if "zooms_ocasionales" in acc or "zooms_muchos" in acc:
        out.append({"setting": "zooms", "value": True, "reason": "Zooms al señalar algo porque los usas."})
    if "musica_no" in acc:
        out.append({"setting": "musica", "value": None,
                    "reason": "Sin música de fondo porque casi nunca la usas en este tipo de video."})
    return out


def compare(d: dict, p: Project, kind: str) -> list[str]:
    """Comentarios opcionales: en qué se parece o se aleja este proyecto de tu estilo."""
    f = features(p)
    pats = {x["key"]: x for x in patterns(d, kind) if x["n"] >= 3 and x["confidence"] >= 0.5}
    out = []
    if "clip_len" in f and "clip_len" in pats:
        a, b = f["clip_len"], pats["clip_len"]["value"]
        if a > b * 1.4:
            out.append(f"En proyectos similares sueles usar cortes más rápidos (≈{b:.1f} s; aquí {a:.1f} s).")
        elif a < b / 1.4:
            out.append(f"Aquí los planos son más cortos de lo habitual en ti (≈{a:.1f} s frente a {b:.1f} s).")
        else:
            out.append("Esta edición se parece a tus proyectos anteriores en el ritmo de los planos.")
    if "trans_min" in f and "trans_min" in pats and f["trans_min"] > pats["trans_min"]["value"] + 0.8:
        out.append("Tienes más transiciones de lo que sueles usar.")
    if "music_share" in f and "music_share" in pats:
        if pats["music_share"]["value"] > 0.5 and f["music_share"] < 0.2:
            out.append("Normalmente pones música de fondo en este tipo de videos.")
    return out


# ------------------------------------------------------------------ recursos
def process_usage(prev: tuple[float, float] | None) -> tuple[dict, tuple[float, float]]:
    """CPU (% de todo el PC) y RAM de Reclaimer, sin librerías extra."""
    now = (time.time(), time.process_time())
    cpu = 0.0
    if prev:
        dt = now[0] - prev[0]
        if dt > 0:
            cpu = 100.0 * (now[1] - prev[1]) / dt / (os.cpu_count() or 1)
    ram = 0
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        fn = k32.K32GetProcessMemoryInfo     # (el «handle» del propio proceso no cabe en un int de 32 bits)
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        fn.restype = wintypes.BOOL
        if fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            ram = int(pmc.WorkingSetSize)
    except Exception:  # noqa: BLE001
        pass
    try:
        disk = os.path.getsize(_path())
    except OSError:
        disk = 0
    return {"cpu": max(0.0, cpu), "ram_mb": ram / 1e6, "disk_kb": disk / 1e3}, now
