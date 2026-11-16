"""
Módulo de IA: TRANSCRIPCIÓN.

Convierte la narración en texto con el tiempo exacto de cada palabra, usando
Whisper (faster-whisper) en tu PC: gratis y sin internet (salvo la primera
descarga del modelo).
"""
from __future__ import annotations

import os

import numpy as np

from ..core.paths import app_data_dir
from .base import CancelFn, Cancelled, ProgressFn, check_cancel, report

SAMPLE_RATE = 16000

# clave -> (modelo de Whisper, descripción)
MODELS = {
    "equilibrado": ("large-v3-turbo", "Equilibrado (recomendado)"),
    "rapido": ("small", "Rápido, menos preciso"),
    "maximo": ("large-v3", "Máxima precisión, lento"),
}
DOWNLOAD_SIZE = {"equilibrado": "1,6 GB", "rapido": "0,5 GB", "maximo": "3 GB"}

LANGUAGES = {"es": "Español", "en": "Inglés", "": "Detectar automáticamente"}

# Ayuda a que Whisper NO borre las muletillas (así luego se pueden detectar).
FILLER_PROMPT = "Eh... mmm, bueno, este, o sea, pues eso."

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_loaded: dict[str, object] = {}


def is_available() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, "Falta el componente de transcripción. Ejecuta INSTALAR.bat."
    return True, ""


def models_dir():
    # EDITORIA_MODELOS: las pruebas usan datos temporales pero los modelos ya descargados (no se bajan otra vez)
    import os
    from pathlib import Path
    d = Path(os.environ["EDITORIA_MODELOS"]) if os.environ.get("EDITORIA_MODELOS") else app_data_dir() / "modelos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_downloaded(model_key: str) -> bool:
    name = MODELS[model_key][0]
    return any(models_dir().glob(f"models--*--faster-whisper-{name}/snapshots/*/model.bin"))


def _load(name: str):
    if name not in _loaded:
        from faster_whisper import WhisperModel
        threads = max(1, (os.cpu_count() or 4) // 2)
        _loaded.clear()  # solo un modelo en memoria a la vez
        from ..core.hw import whisper_device
        device, ctype = whisper_device()        # NVIDIA lista → la tarjeta; si no, procesador (int8)
        _loaded[name] = WhisperModel(name, device=device, compute_type=ctype,
                                     cpu_threads=threads, download_root=str(models_dir()))
    return _loaded[name]


BLOCK = 180.0           # 📝 cada 3 min de audio transcrito se entrega lo hecho (se puede usar sin esperar al final)


def transcribe(samples: np.ndarray, model_key: str = "equilibrado", language: str = "es",
               progress: ProgressFn = None, cancelled: CancelFn = None, fillers: bool = True,
               partial=None, block: float = BLOCK, start_at: float = 0.0, prev: dict | None = None) -> dict:
    """
    📝 Por bloques: Whisper escucha en orden, del segundo 0 al final; cada «block» segundos de audio llama a
      partial(tr_a_medias) con lo que lleva, marcado con tr["hasta"] = segundo hasta el que está hecho (se puede usar
      ya: palabras, subtítulos, cortes…). Si se corta, lo entregado se queda; start_at + prev siguen desde ahí.
    samples: audio mono a 16 kHz (float32).
    fillers: True (Limpieza: buscar muletillas, titubeos…) = sin lotes y con el ejemplo FILLER_PROMPT, para que
      Whisper NO borre las muletillas; False (subtítulos) = por lotes (más rápido) y sin ejemplo.
      ⚠ NUNCA el ejemplo en el modo por lotes: se le pone delante a CADA trozo de 30 s y Whisper se pierde (se queda
      escribiendo «... ... ...» y se salta frases enteras). Pasó el 3/11/2026 en un Short: de 256 palabras dichas
      salieron 101 y 21 s sin subtítulos. Sin el ejemplo, el mismo modo por lotes las saca todas.
    Al final, red de seguridad (fill_holes): un tramo con voz y sin palabras se vuelve a escuchar.
    Devuelve {"language", "model", "words": [[inicio, fin, texto, confianza], ...],
              "segments": [[inicio, fin, primera_palabra, última_palabra+1], ...]}
    Los tiempos son del archivo original (no de la timeline).
    """
    name = MODELS[model_key][0]
    aviso = ""
    global _motor_off, _motor_fallos
    if _usar_tarjeta_motor(name):            # 🎙 AMD (o sin las DLL de NVIDIA): Whisper en la tarjeta, por el motor de IA
        ultimo: list = []

        def guardar_parcial(p):
            ultimo[:] = [p]
            if partial is not None:
                partial(p)
        try:
            tr = _transcribe_motor(samples, name, language, progress, cancelled, fillers, guardar_parcial, block,
                                   start_at, prev)
            _motor_fallos = 0
            return tr
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - la tarjeta falla: como siempre, con el procesador
            from ..core import motor_ia as _MI
            _motor_fallos += 1
            if isinstance(exc, _MI.SinTarjeta) or _motor_fallos >= 2:
                _motor_off = True                    # (sin tarjeta, o falló 2 veces seguidas: el resto de la sesión, CPU)
            aviso = ("Sin tarjeta usable: " if isinstance(exc, _MI.SinTarjeta)
                     else f"La tarjeta no pudo ({str(exc).strip().splitlines()[-1][:80] if str(exc).strip() else 'error'}): ")
            if ultimo and ultimo[0].get("hasta"):    # lo que ya transcribió la tarjeta se queda: se sigue desde ahí
                prev, start_at = ultimo[0], float(ultimo[0]["hasta"])
            report(progress, 0.0, aviso + "sigo con el procesador…")
    report(progress, 0.0, aviso + ("cargando el modelo de voz…" if aviso else "Cargando el modelo de voz…")
           if is_downloaded(model_key)
           else aviso + "descargando el modelo de voz (solo la primera vez, puede tardar varios minutos)…")
    model = _load(name)
    check_cancel(cancelled)
    total = max(len(samples) / SAMPLE_RATE, 0.001)
    start_at = min(max(0.0, float(start_at or 0.0)), total)
    audio = samples[int(start_at * SAMPLE_RATE):] if start_at else samples
    report(progress, start_at / total, "Transcribiendo…")
    from .word_fix import hotwords
    # hotwords: las palabras que le pediste tener en cuenta (clic derecho en una palabra del panel Texto)
    if fillers:
        segments, info = model.transcribe(audio, language=language or None, word_timestamps=True, beam_size=5,
                                          vad_filter=True, initial_prompt=FILLER_PROMPT, hotwords=hotwords())
    else:
        from faster_whisper import BatchedInferencePipeline
        segments, info = BatchedInferencePipeline(model=model).transcribe(
            audio, language=language or None, word_timestamps=True, beam_size=5, batch_size=8)

    words: list[list] = []
    segs: list[list] = []
    if start_at and prev:                     # seguir: lo ya hecho (hasta start_at) se queda tal cual
        words = [list(w) for w in prev.get("words", []) if float(w[1]) <= start_at + 1e-3]
        segs = [list(sg) for sg in prev.get("segments", []) if sg[3] <= len(words)]
    next_emit = (int(start_at // block) + 1) * block if block > 0 else float("inf")
    for seg in segments:
        check_cancel(cancelled)
        first = len(words)
        for w in seg.words or []:
            text = w.word.strip()
            if text and text.strip(".…·- "):          # (fuera las «palabras» que son solo puntos: «...»)
                words.append([round(start_at + float(w.start), 3), round(start_at + float(w.end), 3), text,
                              round(float(w.probability), 3)])
        if len(words) > first:
            segs.append([words[first][0], words[-1][1], first, len(words)])
        end = start_at + float(seg.end)
        m, s = divmod(int(end), 60)
        report(progress, min(0.95, end / total), f"Transcribiendo… {m:02d}:{s:02d} de "
                                                 f"{int(total) // 60:02d}:{int(total) % 60:02d}")
        if partial is not None and end >= next_emit and words and end < total - 1.0:
            partial({"language": info.language, "model": name, "words": [list(w) for w in words],
                     "segments": [list(sg) for sg in segs], "hasta": round(end, 3)})
            while next_emit <= end:
                next_emit += block
    tr = {"language": info.language, "model": name, "words": words, "segments": segs}
    tr = fill_holes(samples, tr, model, language, cancelled)
    report(progress, 1.0, f"Transcripción lista: {len(tr['words'])} palabras.")
    return tr


# ------------------------------------------------------------------ 🎙 en la tarjeta (motor de IA)
_motor_off = False                         # sin tarjeta o 2 fallos seguidos en esta sesión: no se vuelve a intentar
_motor_fallos = 0
_MOTOR_NAMES = {"large-v3-turbo": "turbo", "large-v3": "large-v3", "medium": "medium", "small": "small",
                "base": "base"}


def _borrar(ruta: str):
    import os as _os
    try:
        _os.remove(ruta)
    except OSError:
        pass


def _usar_tarjeta_motor(name: str) -> bool:
    """La tarjeta por el motor de IA solo si faster-whisper NO la usa ya (AMD, o NVIDIA sin sus DLL), el motor tiene
    Whisper y no lo apagaste (Voz → ajustes: «voz/tarjeta_motor»)."""
    if _motor_off or name not in _MOTOR_NAMES:
        return False
    import os as _os
    if _os.environ.get("EDITORIA_TARJETA_MOTOR") == "0":    # (las pruebas con modelos falsos: el procesador)
        return False
    try:
        from PySide6.QtCore import QSettings
        if str(QSettings("EditorIA", "EditorIA").value("voz/tarjeta_motor", "true")).lower() != "true":
            return False
    except Exception:  # noqa: BLE001
        pass
    from ..core import motor_ia
    from ..core.hw import whisper_device
    return whisper_device()[0] == "cpu" and motor_ia.whisper_ok()


def _transcribe_motor(samples, name, language, progress, cancelled, fillers, partial, block, start_at, prev) -> dict:
    import json as _json
    import os as _os
    import tempfile as _tmp
    import wave
    from ..core import media as media_tools
    from ..core import motor_ia
    from ..core.paths import temp_dir
    from .word_fix import hotwords
    total = max(len(samples) / SAMPLE_RATE, 0.001)
    start_at = min(max(0.0, float(start_at or 0.0)), total)
    fd, wav = _tmp.mkstemp(prefix="voz_", suffix=".wav", dir=str(temp_dir()))
    _os.close(fd)
    salida = wav[:-4] + ".json"
    try:
        with wave.open(wav, "wb") as w:              # (el audio ya está a 16 kHz: se pasa tal cual, por trozos de 60 s)
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            paso = 60 * SAMPLE_RATE
            for i in range(0, len(samples), paso):
                w.writeframes((np.clip(samples[i:i + paso], -1, 1) * 32767).astype("<i2").tobytes())
    except BaseException:
        _borrar(wav)
        raise
    keep = [list(w) for w in (prev or {}).get("words", []) if start_at and float(w[1]) <= start_at + 1e-3]
    keep_segs = [list(sg) for sg in (prev or {}).get("segments", []) if start_at and sg[3] <= len(keep)]

    def unir(res: dict) -> dict:
        off = len(keep)
        words = keep + [list(w) for w in res.get("words", [])]
        segs = keep_segs + [[sg[0], sg[1], sg[2] + off, sg[3] + off] for sg in res.get("segments", [])]
        out = {"language": res.get("language") or language or "es", "model": name, "motor": "tarjeta",
               "words": words, "segments": segs}
        if "hasta" in res:
            out["hasta"] = res["hasta"]
        return out

    def al_parcial(ruta: str):
        if partial is None:
            return
        with open(ruta, encoding="utf-8") as f:
            partial(unir(_json.load(f)))

    hw_ = hotwords() or ""
    hw_ = " ".join(hw_.split()[-28:]) if isinstance(hw_, str) else ""     # (~100 fichas: que quepa todo el ejemplo)
    job = {"ffmpeg": media_tools.ffmpeg(), "entrada": wav, "salida": salida, "idioma": language or "",
           "palabras": hw_, "prompt": FILLER_PROMPT if fillers else "",
           "previo": " ".join(w[2] for w in keep[-30:]),
           "desde": start_at, "bloque": float(block or BLOCK), "modelo": _MOTOR_NAMES[name]}

    def prog(f, txt=""):
        report(progress, f, txt)
    try:
        ruta = motor_ia.run("transcribir.py", job, prog, cancelled, partial=al_parcial)
        with open(ruta, encoding="utf-8") as f:
            tr = unir(_json.load(f))
    except RuntimeError as exc:
        if "Cancelado" in str(exc) or (cancelled is not None and cancelled()):
            raise Cancelled() from exc
        raise
    finally:                                         # (también al cancelar o fallar: nada se queda en «temporal»)
        for x in (wav, salida, salida + ".parcial.json"):
            _borrar(x)
    if holes(samples, tr["words"]):            # red de seguridad: los huecos con voz, con el modelo de siempre
        report(progress, 0.98, "Repasando los tramos con voz que se quedaron sin texto…")
        try:
            tr = fill_holes(samples, tr, _load(name), language, cancelled)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - lo de la tarjeta ya vale: la red de seguridad es un extra
            pass
    report(progress, 1.0, f"Transcripción lista (tarjeta gráfica): {len(tr['words'])} palabras.")
    return tr


# ------------------------------------------------------------------ red de seguridad
HOLE_MIN = 2.5          # un tramo sin palabras de al menos 2,5 s…
HOLE_VOICE = 0.4        # …en el que al menos el 40 % suena como voz, se vuelve a escuchar


def voice_frames(samples: np.ndarray, hop: float = 0.1) -> np.ndarray:
    """Por cada 0,1 s: ¿suena como voz? (nivel cerca del de tu voz en este audio, no un silencio ni un ruido bajo)."""
    n = int(hop * SAMPLE_RATE)
    k = len(samples) // n
    if k == 0:
        return np.zeros(0, bool)
    fr = samples[:k * n].reshape(k, n)
    db = 20 * np.log10(np.sqrt((fr.astype(np.float64) ** 2).mean(axis=1)) + 1e-9)
    loud = np.percentile(db, 80)               # el nivel típico de cuando hablas
    return db > max(loud - 14.0, -50.0)


def holes(samples: np.ndarray, words: list) -> list[tuple[float, float]]:
    """Tramos sin palabras (también antes de la primera y tras la última) donde se oye voz."""
    v = voice_frames(samples)
    total = len(samples) / SAMPLE_RATE
    edges = [0.0] + [x for w in words for x in (float(w[0]), float(w[1]))] + [total]
    out = []
    for a, b in zip(edges[0::2], edges[1::2]):
        if b - a < HOLE_MIN:
            continue
        seg = v[int(a / 0.1):int(b / 0.1)]
        if len(seg) and seg.mean() >= HOLE_VOICE:
            out.append((a, b))
    return out


def fill_holes(samples: np.ndarray, tr: dict, model, language: str = "es", cancelled: CancelFn = None) -> dict:
    """Vuelve a escuchar (de uno en uno, sin ejemplo: lo más fiable) los tramos con voz que se quedaron sin texto y
    mete lo que oiga en su sitio. Lo recuperado queda en tr["filled"] = [[inicio, fin], …]."""
    words = [list(w) for w in tr.get("words", [])]
    found = holes(samples, words)
    if not found:
        return tr
    new_all, filled = [], []
    for a, b in found:
        check_cancel(cancelled)
        a0, b0 = max(0.0, a - 0.3), min(len(samples) / SAMPLE_RATE, b + 0.3)
        clip = samples[int(a0 * SAMPLE_RATE):int(b0 * SAMPLE_RATE)]
        segs, _info = model.transcribe(clip, language=language or None, word_timestamps=True, beam_size=5,
                                       vad_filter=True, condition_on_previous_text=False)
        got = [[round(a0 + float(w.start), 3), round(a0 + float(w.end), 3), w.word.strip(),
                round(float(w.probability), 3)] for s in segs for w in (s.words or [])
               if w.word.strip().strip(".…·- ")]
        got = [w for w in got if a - 0.05 <= (w[0] + w[1]) / 2 <= b + 0.05]
        if got:
            new_all += got
            filled.append([round(a, 3), round(b, 3)])
    if not new_all:
        return tr
    from .verbatim import _rebuild_segments
    merged = sorted(words + new_all, key=lambda w: w[0])
    out = dict(tr, words=merged, segments=_rebuild_segments(merged, words, tr.get("segments") or []))
    out["filled"] = list(tr.get("filled") or []) + filled
    return out
