"""
🎙 Servidor de voz del motor de IA: un Python que se queda abierto con Whisper (y el alineador de palabras) YA
cargados en la tarjeta gráfica, para que cada transcripción no pague otra vez arrancar PyTorch y cargar el modelo
(medido en una RX 9060 XT con large-v3: ~17 s menos por transcripción).

Reclaimer le manda órdenes por la entrada (una línea JSON cada una) y lee por la salida, como los demás trabajos:
  «PROGRESO f texto», «PARCIAL ruta», y al terminar cada orden «LISTO resultado» o «FALLO motivo».
Órdenes:
  {"cmd": "cargar", "modelo": "large-v3"}                      precargar (y calentar) un modelo de Whisper
  {"cmd": "transcribir", ...lo mismo que transcribir.py...}     → LISTO ruta del json
  {"cmd": "rellenar", "entrada", "salida", "tramos": [[a, b]…], "idioma", "modelo", ["prompt", "beam"]}
      volver a escuchar tramos sueltos (red de seguridad, escucha literal) → LISTO ruta
  {"cmd": "emisiones", "entrada", "salida", "tramos": [[a, b]…]}  alineador wav2vec2 → LISTO ruta (.npz)
  {"cmd": "salir"}
Sin tarjeta: «SIN_TARJETA» y sale con código 3. Si nadie le manda nada en ESPERA segundos (o Reclaimer se cierra),
se cierra solo y libera la memoria de la tarjeta.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcribir as T  # noqa: E402

ESPERA = float(os.environ.get("RECLAIMER_VOZ_ESPERA", "600"))      # 10 min sin trabajo: se cierra
_MOTOR_NAMES = {"large-v3-turbo": "turbo"}


class Voz:
    def __init__(self):
        self.whisper = None
        self.nombre = ""
        self.alineador = None
        self.audio_ruta = ""
        self.audio = None

    def modelo(self, nombre: str, avisar: bool = True):
        nombre = _MOTOR_NAMES.get(nombre, nombre) or "turbo"
        if self.whisper is not None and self.nombre == nombre:
            return self.whisper
        import torch
        self.whisper = None                          # (solo un Whisper en la tarjeta a la vez)
        torch.cuda.empty_cache()
        destino = T.ruta_modelos()
        ya = os.path.exists(os.path.join(destino, "large-v3-turbo.pt")) or nombre != "turbo"
        if avisar:
            T.say(0.0, "Cargando el modelo de voz en la tarjeta…" if ya else
                  "Descargando el modelo de voz (solo la primera vez, ~1,6 GB)…")
        self.whisper = T.cargar_modelo(nombre, destino)
        self.nombre = nombre
        T.calentar(self.whisper)
        return self.whisper

    def leer(self, job: dict) -> np.ndarray:
        ruta = job["entrada"]
        try:
            clave = (ruta, os.path.getmtime(ruta), os.path.getsize(ruta))
        except OSError:
            clave = None
        if clave is None or clave != self.audio_ruta:
            self.audio = T.cargar(job.get("ffmpeg") or "ffmpeg", ruta)
            self.audio_ruta = clave
        return self.audio

    def cargar_alineador(self):
        if self.alineador is not None:
            return self.alineador
        import torch
        from torchaudio.models import wav2vec2_model
        from torchaudio.models.wav2vec2.utils.import_huggingface import _get_config
        import types
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alineador_es")
        with open(os.path.join(d, "config.json"), encoding="utf-8") as f:
            cfg = types.SimpleNamespace(**json.load(f))
        m = wav2vec2_model(**_get_config(cfg), aux_num_out=cfg.vocab_size)
        sd = torch.load(os.path.join(d, "pytorch_model.bin"), map_location="cpu", weights_only=True, mmap=True)
        nuevo = {}
        for k, v in sd.items():                      # (nombres de transformers → torchaudio, sin transformers)
            if k == "wav2vec2.masked_spec_embed":
                continue
            if k.startswith("lm_head."):
                k = "aux." + k[8:]
            elif k.startswith("wav2vec2.feature_extractor."):
                k = k[9:]
            elif k.startswith("wav2vec2.feature_projection."):
                k = "encoder." + k[9:]
            elif k.startswith("wav2vec2.encoder."):
                k = "encoder.transformer." + k[17:]
                k = k.replace("pos_conv_embed.conv.weight_g", "pos_conv_embed.conv.parametrizations.weight.original0")
                k = k.replace("pos_conv_embed.conv.weight_v", "pos_conv_embed.conv.parametrizations.weight.original1")
            nuevo[k] = v
        m.load_state_dict(nuevo)
        self.alineador = m.eval().to("cuda", dtype=torch.float16)
        return self.alineador

    # ---------------------------------------------------------------- órdenes
    def transcribir(self, job: dict) -> str:
        model = self.modelo(job.get("modelo") or "turbo")
        audio = self.leer(job)
        parcial = job["salida"] + ".parcial.json"

        def emitir(p):
            with open(parcial, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False)
            print(f"PARCIAL {parcial}", flush=True)
        res = T.transcribir_audio(model, audio, job, emitir)
        with open(job["salida"], "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        try:
            os.remove(parcial)
        except OSError:
            pass
        T.say(1.0, f"Transcripción lista: {len(res['words'])} palabras.")
        return job["salida"]

    def rellenar(self, job: dict) -> str:
        model = self.modelo(job.get("modelo") or "turbo", avisar=False)
        por_tramo = T.oir_tramos(model, self.leer(job), job.get("tramos") or [], job.get("idioma") or None,
                                  job.get("prompt") or None, job.get("beam") or None)
        with open(job["salida"], "w", encoding="utf-8") as f:
            json.dump({"por_tramo": por_tramo}, f, ensure_ascii=False)
        return job["salida"]

    def emisiones(self, job: dict) -> str:
        import torch
        m = self.cargar_alineador()
        audio = self.leer(job)
        out = {}
        tramos = job.get("tramos") or []
        for i, (a, b) in enumerate(tramos):
            x = audio[int(float(a) * T.SR):int(float(b) * T.SR)].astype(np.float32)
            if len(x) < T.SR // 10:
                continue
            x = (x - x.mean()) / (x.std() + 1e-7)
            with torch.inference_mode():
                em, _ = m(torch.from_numpy(x)[None].to("cuda", dtype=torch.float16))
                out[f"e{i}"] = torch.log_softmax(em[0].float(), dim=-1).cpu().numpy()
            if i % 5 == 0:
                T.say(i / max(1, len(tramos)), f"🎯 Afinando palabras en la tarjeta… {i + 1}/{len(tramos)}")
        np.savez(job["salida"], **out)
        return job["salida"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import torch
    if not torch.cuda.is_available():
        print("SIN_TARJETA", flush=True)
        sys.exit(3)
    T.acelerar_dtw()
    ordenes: queue.Queue = queue.Queue()

    def leer_entrada():
        for linea in sys.stdin:
            linea = linea.strip()
            if linea:
                ordenes.put(linea)
        ordenes.put(None)                            # (Reclaimer se cerró: la entrada se acaba)
    threading.Thread(target=leer_entrada, daemon=True).start()
    voz = Voz()
    print("PREPARADO", flush=True)
    quieto = 0.0
    while True:
        try:
            linea = ordenes.get(timeout=30.0)
        except queue.Empty:
            quieto += 30.0
            voz.audio = None                         # (el audio de la última orden no se queda ocupando memoria)
            voz.audio_ruta = ""
            if quieto >= ESPERA:
                break
            continue
        quieto = 0.0
        if linea is None:
            break
        try:
            job = json.loads(linea)
        except ValueError:
            continue
        cmd = job.get("cmd")
        if cmd == "salir":
            break
        try:
            if job.get("ffmpeg"):
                os.environ["PATH"] = os.path.dirname(job["ffmpeg"]) + os.pathsep + os.environ.get("PATH", "")
            if cmd == "cargar":
                voz.modelo(job.get("modelo") or "turbo", avisar=False)
                res = voz.nombre
            elif cmd == "transcribir":
                res = voz.transcribir(job)
            elif cmd == "rellenar":
                res = voz.rellenar(job)
            elif cmd == "emisiones":
                res = voz.emisiones(job)
            else:
                raise ValueError(f"orden desconocida: {cmd}")
            print(f"LISTO {res}", flush=True)
        except Exception as exc:  # noqa: BLE001 - la orden falla, el servidor sigue
            msg = " ".join(str(exc).split())[:300] or type(exc).__name__
            print(f"FALLO {type(exc).__name__}: {msg}", flush=True)
            if "out of memory" in msg.lower():       # (sin memoria en la tarjeta: se suelta todo)
                voz.whisper = voz.alineador = None
                torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
