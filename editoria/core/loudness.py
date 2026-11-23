"""
Medir el volumen de un trozo de sonido (para «Normalizar volumen…», como en Resolve):
  measure(path, a, b) -> {"peak": dBFS del pico, "lufs": volumen percibido (LUFS integrado)}
gain_for(m, mode, target) -> cuántos dB subir/bajar:
  mode "peak"  → que el pico quede en target (p. ej. −1 dBFS)
  mode "lufs"  → que el volumen percibido quede en target (p. ej. −14 LUFS, lo de YouTube), sin pasar de −1 dBFS
📊 Sonoridad para plataformas (botón «LUFS» de la barra del visor y de Escenas; ui/transport_extra.py):
  measure_project(p, progress, cancelled) -> la mezcla ENTERA del proyecto (la misma que se exporta, sin normalizar)
      medida con el ebur128 de FFmpeg: {"lufs", "peak" (pico verdadero, dBTP), "lra", "dur"}. Sin escribir archivos.
  suggest(m, target, ceiling) -> cuántos dB subir o bajar para YouTube / Shorts / TikTok / Instagram (−14 LUFS,
      pico verdadero ≤ −1 dBTP): {"silencio", "db", "db_lufs", "limitado", "lufs_final", "pico_final"}
  plan_ganancia(p, db) -> lo que de VERDAD se puede cambiar: solo los clips que suenan (clips_que_suenan), con el tope
      de 400 % por clip y sin tocar lo bloqueado: {"db", "cambios" {id: volumen nuevo}, "topados", "bloqueados"}
  huella_sonido(p) -> para saber si el proyecto cambió mientras se medía (entonces no se aplica nada)
"""
from __future__ import annotations

import os
import re

from . import media as media_tools

TARGET_LUFS = -14.0       # YouTube (y Shorts, TikTok, Instagram: todas normalizan cerca de −14)
CEILING_DBTP = -1.0       # pico verdadero máximo recomendado
SILENCE_LUFS = -69.0      # ebur128 da −70 LUFS si no hay nada (todo por debajo de su puerta)


def _summary(txt: str) -> dict | None:
    """Lee el resumen final del ebur128 de FFmpeg: I (LUFS integrado), LRA y el pico (verdadero si se pidió)."""
    summary = txt[txt.rfind("Summary:"):] if "Summary:" in txt else txt
    mi = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", summary)
    mp = re.search(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS", summary)
    if not mi or not mp:
        return None
    to_f = lambda s: -120.0 if "inf" in s else float(s)   # noqa: E731
    out = {"lufs": to_f(mi.group(1)), "peak": to_f(mp.group(1))}
    ml = re.search(r"LRA:\s*(-?[\d.]+)\s*LU", summary)
    if ml:
        out["lra"] = float(ml.group(1))
    return out


def measure(path: str, a: float, b: float) -> dict | None:
    dur = max(0.05, b - a)
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-hide_banner", "-ss", f"{max(0.0, a):.3f}",
                               "-t", f"{dur:.3f}", "-i", path, "-vn", "-af", "ebur128=peak=true",
                               "-f", "null", "-"], timeout=600)
    return _summary(r.stderr.decode(errors="replace"))


def gain_for(m: dict, mode: str, target: float, ceiling: float = CEILING_DBTP) -> float:
    if m["peak"] <= -100:           # silencio: no se toca
        return 0.0
    if mode == "peak":
        return target - m["peak"]
    g = target - m["lufs"]
    return min(g, ceiling - m["peak"])   # sin saturar


def has_sound(project) -> bool:
    """¿Suena algo en el proyecto? (clips activos con sonido en pistas que se oyen; los clips de escena, desplegados)."""
    from . import escena_clip
    from .model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO
    p = escena_clip.expandir(project)
    for tr in p.tracks:
        if tr.kind not in (TRACK_AUDIO, TRACK_VIDEO) or not p.audible(tr):
            continue
        for c in p.clips_on(tr.id):
            m = p.media_of(c)
            if c.enabled and m is not None and c.volume > 0 and c.speed > 0 and \
                    (m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio)):
                return True
    return False


def measure_project(project, progress=None, cancelled=None) -> dict | None:
    """📊 La sonoridad de la mezcla entera (la misma que sale al exportar, SIN el «normalizar a −14 LUFS» final), con
    el pico verdadero (dBTP). FFmpeg mezcla y mide de una vez (ebur128 al final del mismo filtro): nada en el disco
    salvo el guion del filtro. Bloquea: llamarlo desde un hilo (BackgroundJob). None si no se pudo medir."""
    import subprocess
    import uuid

    from ..export.ffmpeg_export import ExportOptions, build_command
    from .paths import temp_dir
    base = os.path.join(str(temp_dir()), f"sonoridad_{uuid.uuid4().hex[:8]}")
    script, log = base + ".txt", base + ".log"
    try:
        args, total = build_command(project, ExportOptions(path="-", audio_only=True, loudnorm=False),
                                    media_tools.ffmpeg(), script)
        with open(script, encoding="utf-8") as f:
            filtro = f.read()
        if "[aout]" not in filtro or "-map" not in args:
            return None
        with open(script, "w", encoding="utf-8") as f:
            f.write(filtro + ";\n[aout]ebur128=peak=true:framelog=quiet[amed]")
        i = args.index("-map")
        args[i + 1] = "[amed]"
        j = args.index("-c:a", i)
        args = args[:j] + ["-f", "null", "-"]          # (el audio no se guarda: solo se mide)
        with open(log, "wb") as err:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
                                    creationflags=media_tools.NO_WINDOW)
            try:
                for raw in proc.stdout:                 # (-progress pipe:1: «out_time_us=…» cada medio segundo)
                    if cancelled is not None and cancelled():
                        proc.kill()
                        break
                    line = raw.decode(errors="replace").strip()
                    if progress is not None and line.startswith("out_time_us=") and total > 0:
                        try:
                            s = int(line.split("=", 1)[1]) / 1e6
                        except ValueError:
                            continue
                        progress(min(0.99, s / total), f"📊 Midiendo la sonoridad… {int(100 * min(1.0, s / total))} %")
            finally:
                proc.wait()
        if cancelled is not None and cancelled():
            return None
        with open(log, encoding="utf-8", errors="replace") as f:
            res = _summary(f.read())
        if res is not None:
            res["dur"] = float(total)
        return res
    finally:
        for f in (script, log):
            try:
                os.remove(f)
            except OSError:
                pass


TOPE_CLIP = 4.0           # volumen máximo de un clip (400 %, +12 dB): el mismo que el Inspector


def suena(p, c) -> bool:
    """¿Este clip se oye en la exportación? (las mismas reglas que export/ffmpeg_export): activo, con volumen y
    velocidad, en una pista que se oye (ni silenciada ni fuera del «solo»), y con sonido: audio, o video con audio en
    su pista de video SOLO si su sonido no está separado en una pista de audio (c.link). Imágenes y textos, nunca."""
    from .model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO
    tr, m = p.track(c.track_id), p.media_of(c)
    if tr is None or m is None or not c.enabled or c.volume <= 0 or c.speed <= 0 or not p.audible(tr):
        return False
    if tr.kind == TRACK_AUDIO:
        return m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and bool(m.has_audio))
    if tr.kind == TRACK_VIDEO:
        return m.kind == KIND_VIDEO and bool(m.has_audio) and not c.link
    return False


def clips_que_suenan(p) -> list:
    return [c for c in p.clips.values() if suena(p, c)]


def plan_ganancia(p, db: float) -> dict:
    """📊 Subir/bajar db dB TODO lo que suena, tal y como se puede de verdad: cada clip × 10^(db/20) hasta su tope
    (TOPE_CLIP: «topados» = los que no llegan) y sin tocar los bloqueados (clip o pista: «bloqueados»).
    cambios = {id del clip: volumen nuevo} (lo que aplicará controller.project_gain, en un solo Ctrl+Z)."""
    f = 10 ** (float(db) / 20)
    cambios, topados, bloqueados = {}, [], []
    for c in clips_que_suenan(p):
        tr = p.track(c.track_id)
        if c.locked or (tr is not None and tr.locked):
            bloqueados.append(c.id)
            continue
        v = c.volume * f
        if v > TOPE_CLIP + 1e-6:
            topados.append(c.id)
            v = TOPE_CLIP
        cambios[c.id] = round(max(0.0, v), 4)
    return {"db": float(db), "cambios": cambios, "topados": topados, "bloqueados": bloqueados}


def aplicar_plan(p, plan: dict) -> int:
    """Pone los volúmenes del plan en ese proyecto (una COPIA: para medir cómo quedará antes de preguntar)."""
    n = 0
    for cid, v in plan["cambios"].items():
        c = p.clips.get(cid)
        if c is not None:
            c.volume = v
            n += 1
    return n


def huella_sonido(p) -> str:
    """Lo que decide cómo suena la mezcla (pistas, clips, escenas y compuestos): si cambia mientras se mide, la
    medición ya no vale y la ganancia no se aplica."""
    import json
    from .model import fast_asdict
    return json.dumps({"tracks": [fast_asdict(t) for t in p.tracks],
                       "clips": sorted((fast_asdict(c) for c in p.clips.values()), key=lambda d: str(d.get("id"))),
                       "compounds": p.compounds, "scenes": p.scenes, "loudnorm": p.loudnorm},
                      sort_keys=True, default=str)


def suggest(m: dict | None, target: float = TARGET_LUFS, ceiling: float = CEILING_DBTP) -> dict:
    """Cuántos dB subir (+) o bajar (−) TODO el sonido para llegar a target LUFS sin que el pico verdadero pase de
    ceiling dBTP (como gain_for «lufs»). limitado = el pico no deja llegar al objetivo (haría falta un limitador)."""
    if m is None or m.get("lufs", -120.0) <= SILENCE_LUFS or m.get("peak", -120.0) <= -100:
        return {"silencio": True, "db": 0.0, "db_lufs": 0.0, "limitado": False}
    db_lufs = target - m["lufs"]
    db = gain_for(m, "lufs", target, ceiling)
    return {"silencio": False, "db": round(db, 1), "db_lufs": round(db_lufs, 1), "limitado": db < db_lufs - 0.05,
            "lufs_final": round(m["lufs"] + db, 1), "pico_final": round(m["peak"] + db, 1)}
