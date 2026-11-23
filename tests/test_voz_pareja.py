"""
🎚 PRUEBA de la fase 9: voz pareja (el mismo volumen en cada frase), SOLO con ganancia (ni EQ ni compresor).
  · una voz de prueba con frases a −30 y −18 dBFS y un ruido de fondo muy bajo en las pausas;
  · tras igualar y exportar: el LUFS de cada frase queda a ±1,5 dB del de las demás (antes, 12 dB de diferencia) y el
    nivel típico (la mediana de las frases) no cambia;
  · los silencios NO suben (el ruido de fondo de las pausas, igual o más bajo);
  · ganancias dentro de ±6 dB, cambios solo en las pausas; ningún ecualizador ni compresor añadido;
  · un Ctrl+Z la quita; «Quitar» borra solo sus puntos; un clip con puntos de volumen tuyos no se toca.
  · (21/11, bloqueante del revisor) una narración LARGA fabricada (>40 frases, >150 puntos) exporta bien y la ganancia
    exportada es la de la curva; la curva en árbol, con 2000 puntos, da en FFmpeg lo mismo que value_at; dividir en 4
    y eliminar silencios deja a cada pieza SOLO sus puntos, con la misma ganancia en cada instante, y exporta bien;
  · reservas: lo muy bajo (−12 dB del típico) no sube, las frases cortas toman la ganancia de su vecina, entre frases
    vecinas como mucho 4 dB, nunca dos puntos en t=0, y repetir «Voz pareja» tras alargar un clip rehace sus puntos.
Datos aislados, sin ventanas. Ejecutar:  .venv/Scripts/python.exe tests/test_voz_pareja.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import wave


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")


_aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

import numpy as np  # noqa: E402

SR = 48000
FRASE, PAUSA, N = 1.6, 1.0, 6
# (de una frase a la siguiente, como mucho 3 dB: la voz pareja no separa más de 4 dB dos frases vecinas)
NIVELES = [-30.0, -27.0, -24.0, -21.0, -18.0, -21.0]


def fabricar(ruta: str):
    """Frases «de voz» (tonos con sílabas) a −30 y −18 dBFS RMS, pausas con ruido de fondo a −62 dBFS."""
    rng = np.random.default_rng(3)
    total = N * (FRASE + PAUSA) + PAUSA
    t = np.arange(int(total * SR)) / SR
    x = rng.normal(0, 1, len(t)) * 10 ** (-62 / 20)
    words, frases = [], []
    for k, nivel in enumerate(NIVELES):
        a = PAUSA + k * (FRASE + PAUSA)
        i0, i1 = int(a * SR), int((a + FRASE) * SR)
        tt = t[i0:i1] - a
        voz = sum(np.sin(2 * np.pi * f * tt + f) for f in (180, 360, 720, 1500))
        voz *= 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * tt) ** 2        # (sílabas)
        voz *= 10 ** (nivel / 20) / np.sqrt(np.mean(voz ** 2))
        x[i0:i1] += voz
        frases.append((a, a + FRASE))
        for j in range(4):                              # 4 palabras por frase (huecos de 0,05 s: misma frase)
            w0 = a + j * 0.4
            words.append([round(w0, 3), round(w0 + 0.35, 3), f"palabra{k}{j}", 1.0])
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return words, frases


def fabricar_larga(ruta: str, niveles: list, duraciones: list, pausa: float = 0.6):
    """Una narración larga: frases «de voz» con su nivel y su duración (palabras de 0,35 s), pausas con ruido bajo."""
    rng = np.random.default_rng(7)
    total = sum(duraciones) + pausa * (len(duraciones) + 1)
    t = np.arange(int(total * SR)) / SR
    x = rng.normal(0, 1, len(t)) * 10 ** (-62 / 20)
    words, frases = [], []
    a = pausa
    for k, (nivel, dur) in enumerate(zip(niveles, duraciones)):
        i0, i1 = int(a * SR), int((a + dur) * SR)
        tt = t[i0:i1] - a
        voz = sum(np.sin(2 * np.pi * f * tt + f) for f in (180, 360, 720, 1500))
        voz *= 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * tt) ** 2
        voz *= 10 ** (nivel / 20) / np.sqrt(np.mean(voz ** 2))
        x[i0:i1] += voz
        frases.append((a, a + dur))
        w0 = a
        while w0 < a + dur - 1e-6:
            w1 = min(w0 + 0.35, a + dur)
            words.append([round(w0, 3), round(w1, 3), f"p{k}_{len(words)}", 1.0])
            w0 = w1 + 0.05
        a += dur + pausa
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return words, frases


def reservas():
    """Las reservas del usuario, sobre ganancias() y puntos() directamente."""
    from editoria.core import voz_pareja as VP
    fr = [(k * 2.0, k * 2.0 + 1.2, 0, 0) for k in range(8)]
    fr[2] = (4.0, 4.3, 0, 0)                              # (una frase corta: 0,3 s, más cerca de la 1 que de la 3)
    dur = [b - a for a, b, _i, _j in fr]
    lv = [-24.0, -22.0, -18.0, -24.0, -40.0, -24.0, -24.0, -24.0]
    g = VP.ganancias(lv, dur, fr)
    assert abs(g[2] - g[1]) < 1e-6, ("la frase corta toma la ganancia de su vecina", g)
    assert g[4] <= 1e-6, ("lo que está 16 dB por debajo del típico no sube", g)
    corta = g[2]
    g = VP.ganancias([-30.0, -18.0] * 10, [2.0] * 20)
    assert max(abs(a - b) for a, b in zip(g, g[1:])) <= 4.01, ("vecinas a 4 dB como mucho", g)
    assert max(abs(x) for x in g) <= VP.LIMITE_DB + 1e-6
    kf = VP.puntos([(0.05, 1.0, 0, 0), (1.6, 2.5, 0, 0)], [3.0, -2.0])
    ts = [k["t"] for k in kf]
    assert ts.count(0.0) <= 1 and all(a < b for a, b in zip(ts, ts[1:])), ("nunca dos puntos en t=0", ts)
    print(f"✓ reservas: la frase corta toma la de su vecina ({corta:+.1f}), lo muy bajo no sube, vecinas a ≤ 4 dB y "
          f"un solo punto en t=0")


def arbol_ffmpeg(out: str):
    """La curva en árbol con 2000 puntos: FFmpeg da la misma ganancia que value_at (antes, >100 puntos = error)."""
    from editoria.core import curves as K
    from editoria.core import media as M
    rng = np.random.default_rng(1)
    ts = np.cumsum(rng.uniform(0.05, 0.6, 2000)) + 0.3
    kf = [{"t": round(float(t), 4), "v": round(float(v), 5)} for t, v in zip(ts, rng.uniform(0.5, 2.0, 2000))]
    sr, fr = 48000, 480                                    # (eval=frame: una ganancia por cada bloque de 10 ms)
    for src_in, dur in ((0.0, float(ts[-1]) + 1.0), (100.0, 60.0)):
        expr = K.ffmpeg_expr(kf, f"({K._num(src_in)}+t*1)", 1.0, src_in, src_in + dur)
        assert expr.count("if(") < 2100 and "if(lt" in expr
        guion = os.path.join(out, "arbol.txt")
        with open(guion, "w", encoding="utf-8") as f:
            f.write(f"[0:a]volume='{expr}':eval=frame[aout]")
        r = subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                            f"aevalsrc=0.25:s={sr}:n={fr}:d={dur}", "-/filter_complex", guion, "-map", "[aout]",
                            "-f", "f32le", "-acodec", "pcm_f32le", "-"], capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-600:]
        x = np.frombuffer(r.stdout, dtype=np.float32)
        idx = np.arange(0, len(x) - 1, fr)
        err = float(np.abs(x[idx] / 0.25 - np.array([K.value_at(kf, src_in + i / sr) for i in idx])).max())
        assert err < 1e-3, (src_in, err)
        print(f"✓ curva en árbol de {len(K.recortar(kf, src_in, src_in + dur))} puntos: FFmpeg = value_at en "
              f"{len(idx)} instantes (error máx {err:.1e})")


def narracion_larga(out: str, app):
    """El bloqueante del revisor: muchos puntos en un clip, dividir, eliminar silencios… y exportar."""
    import time
    from editoria.core import curves as K
    from editoria.core import media as M
    from editoria.core import voz_pareja as VP
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    rng = np.random.default_rng(11)
    nf = 46
    niveles = [float(x) for x in rng.uniform(-32, -18, nf)]
    niveles[20] = -48.0                                    # (palabras «sin voz real»: no se suben)
    duraciones = [1.2] * nf
    duraciones[9] = duraciones[30] = 0.3                   # (frases cortas: la ganancia de su vecina)
    voz = os.path.join(out, "larga.wav")
    words, frases = fabricar_larga(voz, niveles, duraciones)
    ctrl = ProjectController()
    (nid,) = ctrl.import_now([voz])
    t0 = time.time()
    while getattr(ctrl, "analyzing", False) and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.05)
    p = ctrl.project
    p.loudnorm = False
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([nid], a1.id, 0.0)
    ctrl.project.transcripts[nid] = {"words": words}
    ctrl.set_track_props(a1.id, "Pista sin efectos", fx={})

    def exportar(nombre):
        ruta = os.path.join(out, nombre)
        args, _t = build_command(ctrl.project, ExportOptions(path=ruta, audio_only=True, loudnorm=False), M.ffmpeg(),
                                 os.path.join(out, "fl.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, (nombre, r.stderr.decode(errors="replace")[-600:])
        return ruta
    base = M.decode_mono(exportar("larga_sin.wav"), 16000)

    msg = VP.igualar(ctrl)
    assert msg.startswith("✓"), msg
    narr = next(c for c in ctrl.project.clips.values() if c.media_id == nid)
    kf = [dict(k) for k in narr.vol_kf]
    ts = [k["t"] for k in kf]
    assert len(kf) > 150 and len(frases) > 40, (len(kf), len(frases))
    assert all(a < b for a, b in zip(ts, ts[1:])) and ts.count(0.0) <= 1, "ordenada, sin dos puntos en t=0"
    _kf, res = VP.calcular(ctrl.project, nid)
    gs = res["lista"]
    assert max(abs(a - b) for a, b in zip(gs, gs[1:])) <= 4.01, "vecinas a 4 dB como mucho"
    assert gs[20] <= 1e-6, ("lo muy bajo no sube", gs[20])
    print(f"✓ narración larga: {len(frases)} frases, {len(kf)} puntos; saltos ≤ 4 dB; lo muy bajo, {gs[20]:+.1f} dB")

    # exporta bien y la ganancia exportada es la de la curva (frase a frase, frente a la exportación sin igualar)
    igual = M.decode_mono(exportar("larga_igualada.wav"), 16000)
    peor = 0.0
    for (a, b), nivel in zip(frases, niveles):
        if b - a < 1.0 or nivel < -40:
            continue
        i0, i1 = int((a + 0.15) * 16000), int((b - 0.15) * 16000)
        med = 20 * np.log10(np.sqrt(np.mean(igual[i0:i1] ** 2)) / np.sqrt(np.mean(base[i0:i1] ** 2)))
        esperado = 20 * np.log10(K.value_at(kf, (a + b) / 2))
        peor = max(peor, abs(med - esperado))
    assert peor < 0.3, ("la ganancia exportada no es la de la curva", peor)
    print(f"✓ exporta bien con {len(kf)} puntos y la ganancia exportada es la de la curva (±{peor:.2f} dB)")

    # dividir en 4: cada pieza solo con SUS puntos y la misma ganancia en cada instante
    instantes = list(np.linspace(0.05, narr.end - 0.05, 400))
    antes = [K.gain(narr, t) for t in instantes]
    for t in (narr.end * 0.25 + 0.03, narr.end * 0.5 + 0.03, narr.end * 0.75 + 0.03):
        ctrl.split(t, None)
    piezas = sorted((c for c in ctrl.project.clips.values() if c.media_id == nid), key=lambda c: c.start)
    assert len(piezas) == 4, len(piezas)

    def solo_lo_suyo(c):
        a, b = K.tramo(c)
        fuera_a = [k for k in c.vol_kf if k["t"] < a]
        fuera_b = [k for k in c.vol_kf if k["t"] > b]
        return len(fuera_a) <= 1 and len(fuera_b) <= 1 and c.vol_kf == K.recortar(kf, a, b)
    assert all(solo_lo_suyo(c) for c in piezas), [len(c.vol_kf) for c in piezas]
    assert sum(len(c.vol_kf) for c in piezas) <= len(kf) + 8
    despues = [K.gain(next(c for c in piezas if c.start <= t < c.end), t) for t in instantes]
    assert max(abs(x - y) for x, y in zip(antes, despues)) < 1e-9, "la ganancia no cambia al dividir"
    print(f"✓ dividir en 4: puntos por pieza {[len(c.vol_kf) for c in piezas]} (antes {len(kf)} en cada una), la "
          f"misma ganancia en {len(instantes)} instantes")

    # eliminar silencios (casi todas las pausas): cada pieza, lo suyo; la ganancia por segundo del archivo, igual
    regiones = [(b + 0.15, a2 - 0.15) for (_a, b), (a2, _b2) in zip(frases, frases[1:])][::2]
    n = ctrl.remove_silence([c.id for c in piezas], regiones)
    piezas = [c for c in ctrl.project.clips.values() if c.media_id == nid]
    assert n and len(piezas) > 20, (n, len(piezas))
    assert all(solo_lo_suyo(c) for c in piezas)
    for c in piezas:
        a, b = K.tramo(c)
        for s in np.linspace(a, b, 7):
            assert abs(K.value_at(c.vol_kf, s) - K.value_at(kf, s)) < 1e-9, (c.id, s)
    total = sum(len(c.vol_kf) for c in piezas)
    exportar("larga_sin_silencios.wav")
    print(f"✓ eliminar silencios: {len(piezas)} piezas con {total} puntos en total (antes serían "
          f"{len(piezas) * len(kf)}), la misma curva y exporta bien")

    # alargar una pieza ya nivelada y repetir «Voz pareja»: sus puntos «voz» se rehacen, sin duplicar
    pz = max(piezas, key=lambda c: c.start)                # (la última: a su derecha no hay nada)
    fin = pz.end
    ctrl.trim_clip(pz.id, "right", fin - 0.5 * pz.duration)
    pz = ctrl.project.clips[pz.id]
    corto = len(pz.vol_kf)
    ctrl.trim_clip(pz.id, "right", fin)                    # (alargada otra vez: la curva es la de su tramo corto)
    pz = ctrl.project.clips[pz.id]
    assert abs(pz.end - fin) < 1e-3 and len(pz.vol_kf) == corto, (pz.end, fin, len(pz.vol_kf), corto)
    msg = VP.igualar(ctrl, [pz.id])
    assert msg.startswith("✓"), msg
    pz = ctrl.project.clips[pz.id]
    ts = [k["t"] for k in pz.vol_kf]
    assert pz.vol_kf == K.recortar(kf, *K.tramo(pz)) and len(set(ts)) == len(ts), "rehecho, sin duplicar"
    print(f"✓ repetir «Voz pareja» en una pieza: {len(pz.vol_kf)} puntos, los suyos (recortada tenía {corto})")


def pista_de_voz(out: str, app):
    """🎙 Grabación de OBS con 2 pistas (la 1, música constante; la 2, la voz con frases a distinto nivel), separada y
    puesta en la línea de tiempo: la voz pareja mide la pista que SUENA en el clip de voz (la 2), nunca la primera."""
    import time
    from editoria.core import curves as K
    from editoria.core import media as M
    from editoria.core import voz_pareja as VP
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_VIDEO
    voz = os.path.join(out, "obs_voz.wav")
    words, frases = fabricar(voz)                          # (mono: el micrófono)
    dur = N * (FRASE + PAUSA) + PAUSA
    t = np.arange(int(dur * SR)) / SR
    musica = np.stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 330 * t + 1.0)], axis=1) * 0.1   # (−20 dBFS)
    ruta_m = os.path.join(out, "obs_musica.wav")
    with wave.open(ruta_m, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((musica * 32767).astype(np.int16).tobytes())
    mp4 = os.path.join(out, "obs_2_pistas.mp4")
    r = subprocess.run([M.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=gray:s=320x180:r=30:d={dur:.2f}", "-i", ruta_m, "-i", voz, "-map", "0:v", "-map",
                        "1:a", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", mp4], capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-400:]
    ctrl = ProjectController()
    (vid,) = ctrl.import_now([mp4])
    t0 = time.time()
    while getattr(ctrl, "analyzing", False) and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.05)
    res = ctrl.separate_audio_tracks_now(vid)
    p = ctrl.project
    roles = {x["role"]: x["media_id"] for x in p.media[vid].audio_tracks}
    assert set(roles) == {"voz", "juego"}, res
    v1 = next(tr for tr in p.tracks if tr.kind == TRACK_VIDEO)
    ctrl.add_media([vid], v1.id, 0.0)
    p = ctrl.project
    p.transcripts[vid] = {"words": words}                  # (la transcripción es de la grabación, como en la app)
    clip_voz = next(c for c in p.clips.values() if c.media_id == roles["voz"])
    clip_juego = next(c for c in p.clips.values() if c.media_id == roles["juego"])
    msg = VP.igualar(ctrl)
    assert msg.startswith("✓"), msg
    p = ctrl.project
    kf = p.clips[clip_voz.id].vol_kf
    assert kf and not p.clips[clip_juego.id].vol_kf, "solo el clip de voz (el del juego no es narración)"
    medidas = [20 * np.log10(K.value_at(kf, (a + b) / 2)) for a, b in frases]
    esperado = [max(-6.0, min(6.0, -22.5 - x)) for x in NIVELES]   # (la mediana de las frases, −22,5 dB)
    peor = max(abs(m_ - e) for m_, e in zip(medidas, esperado))
    assert peor < 1.0, ("las ganancias no salen de la voz (pista 2)", [round(x, 1) for x in medidas], esperado)
    primera = VP.ganancias(VP.niveles(VP.leer(mp4), VP.SR, VP.frases(words), words), [FRASE] * N)
    assert max(primera) - min(primera) < 1.0, ("la pista 1 (música constante) daría ganancias ~iguales", primera)
    print(f"✓ OBS con 2 pistas: la voz pareja mide la pista de voz del clip: ganancias "
          f"{[round(x, 1) for x in medidas]} (esperadas {esperado}; midiendo la pista 1 saldrían "
          f"{[round(x, 1) for x in primera]})")


def rms_db(muestras, sr, a, b):
    s = muestras[int(a * sr):int(b * sr)]
    return 20 * np.log10(max(1e-9, float(np.sqrt(np.mean(np.square(s, dtype=np.float64))))))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "voz_pareja")
    os.makedirs(out, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from editoria.core import loudness as L
    from editoria.core import media as M
    from editoria.core import voz_pareja as VP
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO
    from editoria.export.ffmpeg_export import ExportOptions, build_command
    voz = os.path.join(out, "voz.wav")
    words, frases = fabricar(voz)
    ctrl = ProjectController()
    (nid,) = ctrl.import_now([voz])
    import time
    t0 = time.time()
    while getattr(ctrl, "analyzing", False) and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.05)
    p = ctrl.project
    p.loudnorm = False
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([nid], a1.id, 0.0)
    p = ctrl.project
    p.transcripts[nid] = {"words": words}
    narr = next(c for c in p.clips.values() if c.media_id == nid)
    ctrl.set_track_props(a1.id, "Pista sin efectos", fx={})   # (para medir solo la ganancia; la tuya no se toca)
    p = ctrl.project
    fx_pista = dict(p.track(a1.id).fx or {})

    def exportar(nombre):
        ruta = os.path.join(out, nombre)
        args, _t = build_command(ctrl.project, ExportOptions(path=ruta, audio_only=True, loudnorm=False), M.ffmpeg(),
                                 os.path.join(out, "f.txt"))
        r = subprocess.run(args, capture_output=True)
        assert r.returncode == 0, r.stderr.decode(errors="replace")[-600:]
        return ruta
    base = exportar("sin_igualar.wav")                   # (la misma exportación, sin voz pareja: la referencia)
    antes_exp = [L.measure(base, a, b)["lufs"] for a, b in frases]
    print("LUFS por frase exportando sin igualar:", [round(x, 1) for x in antes_exp])

    antes = [L.measure(voz, a, b)["lufs"] for a, b in frases]
    print("LUFS por frase antes:", [round(x, 1) for x in antes])
    assert max(antes) - min(antes) > 10, antes

    # ---------------------------------------------------------------- igualar (un Ctrl+Z)
    n0 = ctrl.undo_stack.index()
    msg = VP.igualar(ctrl)
    print(msg)
    p = ctrl.project
    narr = p.clips[narr.id]
    assert msg.startswith("✓") and ctrl.undo_stack.index() == n0 + 1, msg
    assert narr.vol_kf and all(k.get("voz") for k in narr.vol_kf)
    vs = [k["v"] for k in narr.vol_kf]
    assert min(vs) >= 10 ** (-6.01 / 20) and max(vs) <= 10 ** (6.01 / 20), (min(vs), max(vs))
    assert narr.eq is None and dict(p.track(a1.id).fx or {}) == fx_pista, "ni ecualizador ni compresor"
    from editoria.core import curves
    for a, b in frases:                                  # dentro de cada frase, la ganancia es FIJA (sin bombeo)
        g = [curves.value_at(narr.vol_kf, s) for s in np.linspace(a, b - 0.06, 9)]   # (hasta su última palabra)
        assert max(g) - min(g) < 1e-6, (a, g)

    # ---------------------------------------------------------------- exportar y medir
    salida = exportar("igualada.wav")
    despues = [L.measure(salida, a, b)["lufs"] for a, b in frases]
    print("LUFS por frase después:", [round(x, 1) for x in despues])
    assert max(antes_exp) - min(antes_exp) > 10, antes_exp
    assert max(despues) - min(despues) <= 3.0, despues          # (±1,5 dB)
    assert abs(float(np.median(despues)) - float(np.median(antes_exp))) <= 1.5, "el nivel típico no cambia"
    m0 = M.decode_mono(base, 16000)
    m1 = M.decode_mono(salida, 16000)
    for k in range(N + 1):                               # el centro de cada pausa (sin las rampas)
        a = k * (FRASE + PAUSA) + 0.2
        b = a + PAUSA - 0.4
        r0, r1 = rms_db(m0, 16000, a, b), rms_db(m1, 16000, a, b)
        assert r1 <= r0 + 0.5, ("el ruido de la pausa subió", k, round(r0, 1), round(r1, 1))
    print("✓ cada frase a ±1,5 dB, el nivel típico igual y los silencios sin subir")

    # ---------------------------------------------------------------- Ctrl+Z, quitar y puntos tuyos
    ctrl.undo_stack.undo()
    assert not ctrl.project.clips[narr.id].vol_kf, "un Ctrl+Z la quita"
    ctrl.undo_stack.redo()
    msg = VP.quitar(ctrl)
    assert msg.startswith("✓") and not ctrl.project.clips[narr.id].vol_kf, msg
    ctrl.set_clip_props([narr.id], "vol", vol_kf=[{"t": 2.0, "v": 0.7}])
    n0 = ctrl.undo_stack.index()
    msg = VP.igualar(ctrl)
    assert "tuyos" in msg and ctrl.undo_stack.index() == n0, msg
    assert ctrl.project.clips[narr.id].vol_kf == [{"t": 2.0, "v": 0.7}]
    print("✓ un Ctrl+Z la quita, «Quitar» borra solo lo suyo y tus puntos de volumen no se tocan")

    reservas()
    pista_de_voz(out, app)
    arbol_ffmpeg(out)
    narracion_larga(out, app)
    print("TODO OK")


if __name__ == "__main__":
    main()
