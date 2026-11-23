"""
🎙 Transcribir en la tarjeta gráfica (AMD con ROCm o NVIDIA con CUDA) con Whisper large-v3-turbo (openai-whisper,
licencia MIT). Para las tarjetas que faster-whisper no usa (AMD): medido en una RX 9060 XT, ~11× tiempo real frente a
~4× del procesador, con el mismo texto.

Uso:  python transcribir.py trabajo.json
  {"entrada": wav PCM16 mono 16 kHz (u otro audio con "ffmpeg"), "salida": json, "idioma": "es",
   "palabras": hotwords o "", "prompt": ejemplo (muletillas) o "", "previo": texto ya transcrito antes de «desde»,
   "desde": segundos, "bloque": 180, "modelo": "turbo"}
Escribe «PROGRESO f texto», «PARCIAL ruta» (lo hecho hasta ahora, cada bloque) y al final «LISTO ruta».
Sin tarjeta: «SIN_TARJETA» y sale con código 3 (Reclaimer transcribe como siempre, con el procesador).
Cada bloque se corta en una pausa (cerca de los «bloque» segundos): ninguna palabra se parte.
Reclaimer usa estas funciones desde servidor_voz.py (el modelo se queda cargado entre transcripciones);
este script suelto sigue sirviendo para un trabajo de una vez.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np

SR = 16000


def say(f, text):
    print(f"PROGRESO {max(0.0, min(1.0, f)):.4f} {text}", flush=True)


def cargar(ffmpeg: str, ruta: str) -> np.ndarray:
    import wave
    try:
        with wave.open(ruta, "rb") as w:           # el wav de Reclaimer ya viene a 16 kHz mono: sin ffmpeg ni copia doble
            if w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2:
                raw = np.memmap(ruta, dtype="<i2", mode="r", offset=_inicio_datos(ruta), shape=(w.getnframes(),))
                return (raw.astype(np.float32) / 32768.0)
    except (wave.Error, EOFError, ValueError, OSError):
        pass
    r = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", ruta, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le",
                        "-"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def _inicio_datos(ruta: str) -> int:
    """Dónde empiezan las muestras dentro del wav (tras el trozo «data»)."""
    with open(ruta, "rb") as f:
        f.seek(12)
        while True:
            cab = f.read(8)
            if len(cab) < 8:
                raise ValueError("wav sin datos")
            n = int.from_bytes(cab[4:], "little")
            if cab[:4] == b"data":
                return f.tell()
            f.seek(n + (n & 1), 1)


def recortar_previo(texto: str, n: int = 150) -> str:
    """Las últimas ~n letras, empezando en una palabra entera."""
    texto = texto.strip()
    if len(texto) <= n:
        return texto
    cola = texto[-n:]
    i = cola.find(" ")
    return cola[i + 1:] if 0 <= i < len(cola) - 1 else cola


def pausa_cerca(audio: np.ndarray, t: float, margen: float = 6.0) -> float:
    """El instante más silencioso (ventanas de 0,1 s) a ±margen de t: ahí se corta el bloque."""
    a, b = int(max(0.0, t - margen) * SR), int(min(len(audio) / SR, t + margen) * SR)
    n = int(0.1 * SR)
    if b - a < 2 * n:
        return t
    seg = audio[a:b]
    k = len(seg) // n
    rms = np.sqrt((seg[:k * n].reshape(k, n).astype(np.float64) ** 2).mean(axis=1))
    return (a + int(np.argmin(rms)) * n + n // 2) / SR


def cargar_modelo(modelo: str, destino: str):
    """⚡ Carga rápida (medido en la RX 9060 XT: large-v3 de 11,7 s a 3,8 s): los pesos del archivo (ya en fp16) van
    directos a la tarjeta, sin crear antes el modelo entero al azar en el procesador (lo que hace whisper.load_model).
    Mismo resultado (texto idéntico, comprobado). Si algo falla (otra versión de whisper), la carga de siempre."""
    import torch
    import whisper
    try:
        from whisper.model import AudioEncoder, ModelDimensions, TextDecoder, Whisper
        url = whisper._MODELS[modelo]
        ruta = os.path.join(destino, os.path.basename(url))
        if not os.path.exists(ruta):
            raise FileNotFoundError(ruta)            # (la primera vez: whisper lo descarga y lo comprueba)
        ck = torch.load(ruta, map_location="cpu", weights_only=True, mmap=True)
        d = ModelDimensions(**ck["dims"])
        model = Whisper.__new__(Whisper)
        torch.nn.Module.__init__(model)
        model.dims = d
        with torch.device("meta"):
            model.encoder = AudioEncoder(d.n_mels, d.n_audio_ctx, d.n_audio_state, d.n_audio_head, d.n_audio_layer)
            model.decoder = TextDecoder(d.n_vocab, d.n_text_ctx, d.n_text_state, d.n_text_head, d.n_text_layer)
        model.load_state_dict(ck["model_state_dict"], assign=True)
        n = d.n_text_ctx
        model.decoder.register_buffer("mask", torch.empty(n, n).fill_(float("-inf")).triu_(1), persistent=False)
        model.set_alignment_heads(whisper._ALIGNMENT_HEADS[modelo])
        model = model.to("cuda", dtype=torch.float16)
        for m in model.modules():                    # (las normas, en float32 como las usa whisper)
            if isinstance(m, torch.nn.LayerNorm):
                m.float()
        return model
    except Exception:  # noqa: BLE001
        return whisper.load_model(modelo, device="cuda", download_root=destino)


def acelerar_dtw():
    """La alineación de palabras de whisper (DTW con numba) se compilaba en CADA transcripción (~1,5 s): con caché en
    disco se compila una sola vez."""
    try:
        import numba
        import whisper.timing as wt
        if getattr(wt, "_reclaimer_cache", False):
            return
        wt.backtrace = numba.jit(nopython=True, cache=True)(wt.backtrace.py_func)
        wt.dtw_cpu = numba.jit(nopython=True, parallel=True, cache=True)(wt.dtw_cpu.py_func)
        wt._reclaimer_cache = True
    except Exception:  # noqa: BLE001 - sin caché: como siempre
        pass


def calentar(model):
    """Una transcripción de 2 s de ruido suave al cargar (~4 s): la tarjeta prepara sus núcleos y numba deja la DTW
    lista. Medido con large-v3: la primera transcripción de verdad pasa de 18,8 s a 13,2 s."""
    try:
        rng = np.random.default_rng(0)
        ruido = (rng.standard_normal(2 * SR) * 0.003).astype(np.float32)
        model.transcribe(ruido, language="es", word_timestamps=True, fp16=True, verbose=None,
                         condition_on_previous_text=False, temperature=0.0, sample_len=16)
    except Exception:  # noqa: BLE001
        pass


def transcribir_audio(model, audio: np.ndarray, job: dict, emitir_parcial=None) -> dict:
    """La transcripción por bloques (ver arriba). emitir_parcial(dict) cada bloque."""
    total = max(len(audio) / SR, 0.001)
    bloque = float(job.get("bloque") or 180.0)
    t = min(max(0.0, float(job.get("desde") or 0.0)), total)
    words: list[list] = []
    segs: list[list] = []
    # Orden del ejemplo: palabras que pediste → ejemplo de muletillas → lo último que se dijo. Whisper recorta por
    # delante si no cabe, así que lo que más importa (el contexto inmediato) va al final.
    prompt_base = " ".join(x for x in ((job.get("palabras") or "").strip(), (job.get("prompt") or "").strip()) if x)
    previo = recortar_previo(job.get("previo") or "")
    idioma = job.get("idioma") or None
    nombre = job.get("nombre") or "large-v3-turbo"
    say(t / total, "Transcribiendo en la tarjeta gráfica…")
    while t < total - 0.05:
        if total - t <= bloque * 1.2:
            fin = total
        else:
            fin = max(pausa_cerca(audio, t + bloque, min(6.0, bloque / 3)), t + 1.0)
        trozo = audio[int(t * SR):int(fin * SR)]
        prompt = (prompt_base + " " + recortar_previo(previo)).strip() or None
        r = model.transcribe(trozo, language=idioma, word_timestamps=True, initial_prompt=prompt, fp16=True,
                             condition_on_previous_text=True, verbose=None, hallucination_silence_threshold=2.0)
        bueno = []                                   # (lo que pasa al bloque siguiente: sin trozos «en bucle»)
        for s in r.get("segments", []):
            if float(s.get("temperature", 0.0)) <= 0.5 and float(s.get("compression_ratio", 0.0)) <= 2.4:
                bueno.append((s.get("text") or "").strip())
            first = len(words)
            for w in s.get("words", []) or []:
                txt = (w.get("word") or "").strip()
                if txt and txt.strip(".…·- "):
                    words.append([round(t + float(w["start"]), 3), round(t + float(w["end"]), 3), txt,
                                  round(float(w.get("probability", 1.0)), 3)])
            if len(words) > first:
                segs.append([words[first][0], words[-1][1], first, len(words)])
        previo = recortar_previo((previo + " " + " ".join(bueno)).strip(), 400)
        t = fin
        m, sec = divmod(int(t), 60)
        say(min(0.97, t / total), f"Transcribiendo en la tarjeta… {m:02d}:{sec:02d} de "
                                  f"{int(total) // 60:02d}:{int(total) % 60:02d}")
        if t < total - 1.0 and words and emitir_parcial is not None:
            emitir_parcial({"language": r.get("language") or idioma or "es", "model": nombre,
                            "words": words, "segments": segs, "hasta": round(t, 3)})
        idioma = idioma or r.get("language")
    return {"language": idioma or "es", "model": nombre, "words": words, "segments": segs}


def oir_tramos(model, audio: np.ndarray, tramos: list, idioma: str | None, prompt: str | None = None,
               beam: int | None = None) -> list[list]:
    """Red de seguridad: vuelve a escuchar (de uno en uno, sin ejemplo ni contexto: lo más fiable) los tramos con voz
    que se quedaron sin texto. Devuelve, por tramo, sus palabras con tiempos del audio entero (Reclaimer decide
    cuáles meter)."""
    todos: list[list] = []
    for a0, b0 in tramos:
        out: list[list] = []
        todos.append(out)
        trozo = audio[int(float(a0) * SR):int(float(b0) * SR)]
        if len(trozo) < SR // 5:
            continue
        extra = {"initial_prompt": prompt, "temperature": 0.0} if prompt else {}   # (escucha literal: su ejemplo)
        if beam:
            extra.update(beam_size=int(beam), best_of=int(beam))
        r = model.transcribe(trozo, language=idioma or None, word_timestamps=True, fp16=True, verbose=None,
                             condition_on_previous_text=False, **extra)
        for s in r.get("segments", []):
            for w in s.get("words", []) or []:
                txt = (w.get("word") or "").strip()
                if txt and txt.strip(".…·- "):
                    out.append([round(float(a0) + float(w["start"]), 3), round(float(a0) + float(w["end"]), 3), txt,
                                round(float(w.get("probability", 1.0)), 3)])
    return todos


def ruta_modelos() -> str:
    raiz = os.environ.get("RECLAIMER_MOTOR_DATOS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, "modelos", "whisper")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)
    import torch
    if not torch.cuda.is_available():
        print("SIN_TARJETA", flush=True)
        sys.exit(3)
    if job.get("ffmpeg"):
        os.environ["PATH"] = os.path.dirname(job["ffmpeg"]) + os.pathsep + os.environ.get("PATH", "")
    destino = ruta_modelos()
    modelo = job.get("modelo") or "turbo"
    ya = os.path.exists(os.path.join(destino, "large-v3-turbo.pt")) or modelo != "turbo"
    say(0.0, "Cargando el modelo de voz en la tarjeta…" if ya else
        "Descargando el modelo de voz (solo la primera vez, ~1,6 GB)…")
    acelerar_dtw()
    model = cargar_modelo(modelo, destino)
    audio = cargar(job.get("ffmpeg") or "ffmpeg", job["entrada"])
    parcial = job["salida"] + ".parcial.json"

    def emitir(p):
        with open(parcial, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False)
        print(f"PARCIAL {parcial}", flush=True)
    res = transcribir_audio(model, audio, job, emitir)
    with open(job["salida"], "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    try:
        os.remove(parcial)
    except OSError:
        pass
    say(1.0, f"Transcripción lista: {len(res['words'])} palabras.")
    print(f"LISTO {job['salida']}", flush=True)


if __name__ == "__main__":
    main()
