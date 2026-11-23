"""
⚡ Reproducción rápida cuidando el equipo (sin ventanas visibles):
  · 🔋 core/energia.py: con la batería (simulada), 2 hilos y la cola de análisis espera con lo automático (MEDIA);
    enchufado, nunca más de la mitad de los núcleos;
  · motor propio (core/live_video.py): saltos EXACTOS también justo antes de una imagen clave con fotogramas B (HEVC
    de x265: antes «no da imagen» y volvía a Qt); en pausa no convierte los fotogramas anteriores al pedido (antes,
    hasta 45 por salto); reproduciendo, la memoria no crece (lo visto se suelta) y lo pesado pasa a la tarjeta gráfica
    (si la hay) sin perder fotogramas; una petición nueva cada 15 ms con la imagen clave a 2 s no hace saltar sin fin;
  · visor (pista mixta, la de por defecto): en pausa el fotograma exacto lo da el motor propio (rápido) y al reproducir
    lo normal vuelven los reproductores de Qt (con su sonido) sin negro; lo PESADO (> 1440p) y el AV1 se reproducen con
    el motor propio; los fotogramas llevan su tiempo (startTime) como los de Qt.
Ejecutar (por el turno):  .venv/Scripts/python.exe tests/test_reproduccion_rapida.py <carpeta>
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_rapida_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["EDITORIA_SIN_SONIDO"] = "1"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (ajustes en un .ini temporal: nunca el registro)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from editoria.core import media as M  # noqa: E402

FFMPEG = M.ffmpeg()
FALLOS: list[str] = []
FPS = 30


def ok(cond, texto):
    print(("  ✓ " if cond else "  ✗ ") + texto, flush=True)
    if not cond:
        FALLOS.append(texto)


def ff(args):
    subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-y"] + args, check=True, creationflags=M.NO_WINDOW)


def brillo_video(ruta, w, h, dur, codec, base=0):
    """Fotograma N con brillo (base + N·4) mod 256 (así se sabe qué fotograma se ve). GOP de 1 s (30)."""
    enc = {"h264": ["-c:v", "libx264", "-preset", "ultrafast", "-qp", "0"],
           "hevc": ["-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "bframes=3:keyint=30:min-keyint=30:"
                    "log-level=error:pools=2", "-qp", "0"],
           "av1": ["-c:v", "libsvtav1", "-preset", "12", "-crf", "20"]}[codec]
    ff(["-f", "lavfi", "-i", f"nullsrc=s={w}x{h}:r={FPS}:d={dur},geq=lum='mod({base}+N*4\\,256)':cb=128:cr=128"]
       + enc + ["-g", "30", "-pix_fmt", "yuv420p", "-threads", "2", ruta])


def rgb(y: int) -> int:
    return int(round(min(255.0, max(0.0, (y - 16) * 255 / 219))))


def centro(data, w, h):
    return data[(h // 2 * w + w // 2) * 4]


# ------------------------------------------------------------------ 🔋 energía
def energia():
    print("\n▶ 🔋 cuidar el equipo")
    from editoria.core import energia as E
    os.environ["RECLAIMER_BATERIA"] = "1"
    ok(E.en_bateria() and E.hilos_decodificar(2160) == 2 and E.hilos_ffmpeg() == 2,
       "con la batería: 2 hilos para decodificar y para FFmpeg")
    os.environ["RECLAIMER_BATERIA"] = "0"
    mitad = max(1, (os.cpu_count() or 4) // 2)
    ok(not E.en_bateria() and E.hilos_decodificar(2160) <= mitad and E.hilos_decodificar(1080) <= min(4, mitad)
       and E.hilos_ffmpeg() <= mitad, f"enchufado: nunca más de la mitad de los núcleos ({E.hilos_decodificar(2160)}, "
                                      f"{E.hilos_decodificar(1080)}, {E.hilos_ffmpeg()} de {os.cpu_count()})")
    del os.environ["RECLAIMER_BATERIA"]
    v = E.en_bateria()                  # (de verdad: GetSystemPowerStatus; un PC de sobremesa → False)
    ok(isinstance(v, bool), f"GetSystemPowerStatus responde (con la batería: {v})")


def cola_bateria():
    print("\n▶ 🔋 la cola de análisis con la batería")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import cola_analisis as CA

    def pump(s, hasta=None):
        fin = time.time() + s
        while time.time() < fin:
            app.processEvents()
            if hasta is not None and hasta():
                return
            time.sleep(0.01)
    c = CA.cola()
    viejo = CA._segundos_sin_usar, CA._usuario_editando
    CA._segundos_sin_usar = lambda: 0.0          # alguien usa el PC
    CA._usuario_editando = lambda: False
    os.environ["RECLAIMER_BATERIA"] = "1"
    tm = c.poner(lambda _p, _c: "hecho", "media con batería", CA.MEDIA, clave="bat_m")
    ta = c.poner(lambda _p, _c: "hecho", "alta con batería", CA.ALTA, clave="bat_a")
    pump(3, lambda: ta.estado == "hecho")
    pump(0.6)
    ok(ta.estado == "hecho" and tm.estado in ("en cola", "en pausa"),
       f"con la batería, lo que esperas tú (ALTA) se hace y lo automático (MEDIA) espera ({ta.estado}, {tm.estado})")
    os.environ["RECLAIMER_BATERIA"] = "0"
    pump(4, lambda: tm.estado == "hecho")
    ok(tm.estado == "hecho", f"enchufado, lo automático sigue ({tm.estado})")

    def lento(_p, control):
        for _ in range(200):
            if control():
                return "cancelado"
            time.sleep(0.02)
        return "hecho"
    tl = c.poner(lento, "media larga", CA.MEDIA, clave="bat_l")
    pump(2, lambda: tl.estado == "en marcha")
    os.environ["RECLAIMER_BATERIA"] = "1"
    pump(2, lambda: tl.estado == "en pausa")
    ok(tl.estado == "en pausa" and "batería" in (tl.motivo_pausa or ""),
       f"al desenchufar, lo automático en marcha se pausa y lo dice: «{tl.motivo_pausa}»")
    c.cancelar(tl)
    pump(1)
    del os.environ["RECLAIMER_BATERIA"]
    CA._segundos_sin_usar, CA._usuario_editando = viejo


# ------------------------------------------------------------------ motor propio
def esperar(s, t, max_s=3.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < max_s:
        fr = s.frame_at(t)
        if fr is not None and abs(fr[0] - t) < 0.5 / FPS + 1e-3:
            return fr, time.perf_counter() - t0
        time.sleep(0.002)
    return None, max_s


def motor(hevc):
    print("\n▶ 🎞 motor propio (HEVC 1600×900 con fotogramas B, imagen clave cada 1 s)")
    from editoria.core import live_video as LV
    from editoria.core.live_video import FrameSource
    s = FrameSource(hevc)
    malos, peor = [], 0.0
    for n in (29, 59, 31, 89, 58, 60, 119, 12):     # 29, 59, 89, 119: justo antes de una imagen clave (la trampa)
        s.want(n / FPS, False, (320, 180))
        c0 = s.convertidos
        fr, dt = esperar(s, n / FPS)
        peor = max(peor, dt)
        if fr is None or abs(centro(fr[3], fr[1], fr[2]) - rgb((n * 4) % 256)) > 4:
            malos.append(n)
        time.sleep(0.05)
        ok(s.convertidos - c0 <= LV.BEHIND_N + 1, f"salto a {n}: {s.convertidos - c0} conversiones (antes hasta 46)") \
            if n == 59 else None
    ok(not malos and not s.error, f"en pausa, el fotograma EXACTO también justo antes de una imagen clave "
                                  f"(fallos: {malos or 'ninguno'}; el peor {peor * 1000:.0f} ms; error: {s.error})")
    ok(s.hw is None, f"en pausa decodifica con el procesador (salta antes): {s.hw}")
    # reproducir: una petición cada 15 ms durante 2,5 s
    s.want(0.2, False, (320, 180))
    esperar(s, 0.2)
    s0, buenos, n, mem = s.seeks, 0, 0, 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 2.5:
        t = 0.2 + (time.perf_counter() - t0)
        s.want(t, True, (320, 180))
        fr = s.frame_at(t)
        buenos += fr is not None and abs(fr[0] - t) <= 1.5 / FPS
        n += 1
        mem = max(mem, s._bytes)
        time.sleep(0.015)
    tope = (LV.ATRAS_S + LV.AHEAD_S + 1.2) * FPS * 320 * 180 * 4
    ok(buenos >= 0.9 * n and s.seeks - s0 <= 3, f"reproduciendo: {buenos}/{n} a tiempo, {s.seeks - s0} saltos")
    ok(mem <= tope, f"reproduciendo, la memoria no crece: {mem / 1e6:.1f} MB (tope {tope / 1e6:.1f})")
    if LV.dispositivo_grafica():
        ok(s.hw == LV.dispositivo_grafica(), f"reproduciendo lo pesado, pasa a la tarjeta gráfica ({s.hw})")
    else:
        print("  · (sin tarjeta para decodificar con PyAV: se queda con el procesador)")
    s.close(1.0)
    # la imagen clave a 2 s y peticiones cada 15 ms: antes saltaba sin fin («no da imagen en ese punto»)
    s = FrameSource(hevc)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.5:
        s.want(1.9 + (time.perf_counter() - t0), True, (320, 180))
        time.sleep(0.015)
    ok(not s.error and s.frame_at(1.9 + 1.4) is not None or s.frame_at(3.2) is not None,
       f"reproducir desde lejos de la imagen clave no se atasca (error: {s.error}, saltos {s.seeks})")
    s.close(1.0)


# ------------------------------------------------------------------ el visor
def visor(h264, grande, av1):
    print("\n▶ 🖥 visor: pista mixta")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core.model import KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, Project
    from editoria.ui import preview as PV
    from editoria.ui.main_window import MainWindow

    def pump(s, hasta=None):
        fin = time.time() + s
        while time.time() < fin:
            app.processEvents()
            if hasta is not None and hasta():
                return True
            time.sleep(0.005)
        return False
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(1.0)
    eng = win.engine
    # «Silencios» y «Huecos»: abajo, en la barra del transporte; con el visor estrecho, solo el icono (nombre en el tip)
    pv = win.preview
    qs = list(pv.quick.values())
    ok(all(pv.transport.isAncestorOf(b) and not b.icon().isNull() for b in qs)
       and not any(pv.header.isAncestorOf(b) for b in qs), "«Silencios» y «Huecos» están abajo, con su icono monocromo")
    estados = []                                    # (de ancho a estrecho: nombres → solo iconos → dos filas)
    for w in range(3000, 300, -10):
        pv._ajustar_rapidos(w)
        e = ("dos filas" if pv._dos_filas else "iconos" if qs[0].text() == "" else "nombres")
        if not estados or estados[-1] != e:
            estados.append(e)
    ok(estados == ["nombres", "iconos", "dos filas"], f"al estrecharse: {' → '.join(estados)}")
    ok([b.text() for b in qs] == ["Silencios", "Huecos"] and pv.transport_fila2.isVisibleTo(pv.transport),
       "en dos filas, abajo con sus nombres (y el transporte con todo el ancho arriba)")
    ok(qs[0].toolTip().startswith("✂ Eliminar silencio"), "la explicación, en el tooltip")
    pv._rapidos_cortos = None
    pv._ajustar_rapidos()

    def transporte_entero(ancho_ventana):
        win.resize(ancho_ventana, 900)
        pump(0.8)
        pv._ajustar_rapidos()
        pump(0.3)
        fila = pv.transport_row
        escondidos = [w for _t, w, pr in fila._items if _t == "w" and pr is not None and w.isHidden()]
        vel = pv.btn_speed
        cortados = [b for b in qs if b.text() and b.width() < b.sizeHint().width() - 1]
        return (not escondidos and vel.isVisible() and vel.width() >= vel.sizeHint().width() - 1 and not cortados,
                f"{ancho_ventana} px: visor {pv.width()} px, fila {fila.width()}/{fila.sizeHint().width()}, "
                f"velocidad {vel.width()}/{vel.sizeHint().width()}, escondidos {len(escondidos)}, "
                f"{'dos filas' if pv._dos_filas else 'una fila'}, {'iconos' if qs[0].text() == '' else 'nombres'}")
    for ancho_v in (1366, 1600, 1920):
        bien, txt = transporte_entero(ancho_v)
        ok(bien, "nada del transporte escondido ni cortado (la velocidad, siempre): " + txt)
    win.resize(1400, 900)
    pump(0.5)
    p = Project.new()
    p.fps = FPS
    v1 = [tr for tr in p.tracks if tr.kind == TRACK_VIDEO][-1]
    for mid, ruta, w, h in (("mh", h264, 640, 360), ("mg", grande, 2880, 1620), ("ma", av1, 640, 360)):
        p.media[mid] = MediaItem(id=mid, path=ruta, kind=KIND_VIDEO, name=os.path.basename(ruta), duration=4.0,
                                 width=w, height=h, fps=FPS, probed=True)
    p.clips["ch"] = Clip("ch", "mh", v1.id, 0.0, 0.0, 4.0)
    p.clips["cg"] = Clip("cg", "mg", v1.id, 4.0, 0.0, 4.0)
    p.clips["ca"] = Clip("ca", "ma", v1.id, 8.0, 0.0, 4.0)
    win.ctrl._replace(p, None)
    win.ctrl.missing = set()
    pump(1.0)
    lay = win.preview.canvas.layer(v1.id)
    ok(len(lay.videos) == PV.VIDEO_POOL + PV.PROPIO_POOL, f"la capa tiene {len(lay.videos)} videos ({PV.VIDEO_POOL} de Qt + {PV.PROPIO_POOL} del motor propio)")
    llegadas = []
    for k, v in enumerate(lay.videos):
        v.videoSink().videoFrameChanged.connect(lambda f, k=k: llegadas.append((time.perf_counter(), f.startTime(), k)))

    def visto():
        img = lay.videos[lay.active].videoSink().videoFrame().toImage()
        return None if img.isNull() else img.pixelColor(img.width() // 2, img.height() // 2).red()

    def saltar(t, n_esperado):
        n0 = len(llegadas)
        a = time.perf_counter()
        eng.seek(t)
        bien = pump(3, lambda: any(k == lay.active and abs(st / 1e6 - n_esperado / FPS) <= 0.6 / FPS
                                   for _a, st, k in llegadas[n0:]))
        return bien, (time.perf_counter() - a) * 1000
    tiempos = []
    for n in (45, 100, 12, 73):
        bien, ms = saltar(n / FPS + 0.001, n)
        tiempos.append(ms)
        ok(bien and lay.active >= PV.VIDEO_POOL and visto() is not None and abs(visto() - rgb((n * 4) % 256)) <= 5,
           f"en pausa, fotograma {n} exacto del motor propio en {ms:.0f} ms (video {lay.active}, brillo {visto()})")
    lane = eng._vlanes[v1.id]
    ok(isinstance(lane, PV._MixedVideoLane), f"la pista es la mixta ({type(lane).__name__})")
    llamadas = []                                   # (en pausa quieta, nadie debe pedir drive sin parar)
    drive0 = lane.drive
    lane.drive = lambda *a, **k: (llamadas.append(1), drive0(*a, **k))[1]

    def colocado():
        qt = lane.slots[lane.active]
        return qt.path == h264 and abs(qt.want_pos - 73 / FPS) < 0.05
    pump(1.5, colocado)                             # (el cabezal quieto: Qt se coloca en su punto, sin enseñarse)
    ok(colocado() and lay.active >= PV.VIDEO_POOL,
       "con el cabezal quieto, el reproductor de Qt se coloca en su punto sin enseñarse")
    n0 = len(llamadas)
    pump(1.0)
    ok(len(llamadas) - n0 <= 3 and not lane._qt_timer.isActive(),     # (sin parar serían ~33 por segundo)
       f"en pausa quieta no se repite drive ({len(llamadas) - n0} llamadas en 1 s) ni queda nada pendiente")
    del lane.drive
    eng.seek(1.0)
    pump(0.4)
    n0 = len(llegadas)
    eng.play()
    vio_negro = False
    fin = time.time() + 1.2
    while time.time() < fin:
        app.processEvents()
        img = lay.videos[lay.active].videoSink().videoFrame()
        vio_negro |= not img.isValid()
        time.sleep(0.005)
    ok(lay.active < PV.VIDEO_POOL and lane.modo == "qt" and not vio_negro,
       f"al reproducir lo normal, lo enseña el reproductor de Qt (video {lay.active}) sin negro por el camino")
    ok(sum(1 for _a, _s, k in llegadas[n0:] if k < PV.VIDEO_POOL) >= 15, "y los fotogramas de Qt van llegando")
    eng.pause()
    pump(0.5)
    ok(lane.modo == "propio" and lay.active >= PV.VIDEO_POOL, "al pausar, vuelve el motor propio (fotograma exacto)")
    # lo pesado (> 1440p): con el motor propio también al reproducir
    eng.seek(4.5)
    pump(1.5)
    n0 = len(llegadas)
    eng.play()
    pump(1.5)
    propios = sum(1 for _a, _s, k in llegadas[n0:] if k >= PV.VIDEO_POOL)
    ok(lane.propio(grande) and lay.active >= PV.VIDEO_POOL and propios >= 25,
       f"lo pesado (2880×1620) se reproduce con el motor propio ({propios} fotogramas en 1,5 s)")
    own = lane.own
    srcs = [sx for i, sx in own.src.items() if own.paths[i] == grande]
    from editoria.core import live_video as LV
    if LV.dispositivo_grafica() and srcs:
        ok(srcs[0].hw == LV.dispositivo_grafica(), f"y con la tarjeta gráfica ({srcs[0].hw})")
    eng.pause()
    # AV1: Qt sin tarjeta no lo decodifica; el motor propio sí
    pump(1.0, lambda: PV._CODEC.get(av1, "") not in ("",))
    bien, ms = saltar(8.0 + 20 / FPS + 0.001, 20)
    ok(bien and lane.propio(av1), f"el AV1 se ve con el motor propio (fotograma exacto en {ms:.0f} ms)")
    # ✂ un fotograma suelto (alargar un clip): el 110 del H.264, aunque el cabezal está en el AV1
    a = time.perf_counter()
    ok(eng.mostrar_fotograma("mh", 110 / FPS), "mostrar_fotograma acepta el medio en pausa")

    def suelto():
        pm = eng._suelto["img"].pixmap()
        if pm.isNull():
            return None
        img = pm.toImage()
        return img.pixelColor(img.width() // 2, img.height() // 2).red()
    pump(2, lambda: suelto() is not None and abs(suelto() - rgb((110 * 4) % 256)) <= 5)
    ms = (time.perf_counter() - a) * 1000
    ok(eng._suelto["caja"].isVisible() and suelto() is not None and abs(suelto() - rgb((110 * 4) % 256)) <= 5,
       f"✂ el visor enseña el fotograma suelto pedido (110) encima de todo en {ms:.0f} ms (brillo {suelto()})")
    a = time.perf_counter()
    eng.mostrar_fotograma("mh", 111 / FPS)
    pump(1, lambda: suelto() is not None and abs(suelto() - rgb((111 * 4) % 256)) <= 5)
    ok(abs(suelto() - rgb((111 * 4) % 256)) <= 5, f"el siguiente, al mover el ratón: {(time.perf_counter() - a) * 1000:.0f} ms")
    eng.soltar_fotograma()
    ok(not eng._suelto["caja"].isVisible(), "al soltar, el visor vuelve al cabezal")
    ok(not eng.mostrar_fotograma("no_existe", 1.0), "un medio que no existe: no hace nada")
    # ⚡ interruptores visibles (menú del modo del visor): apagar «en pausa» vuelve a los reproductores de siempre
    pv.act_motor_pausa.setChecked(False)
    pump(0.2)
    eng.seek(1.5)
    pump(1.5)
    ok(not lane.pausa_propia and lane.modo == "qt" and lay.active < PV.VIDEO_POOL,
       f"«⚡ Motor propio en pausa» apagado: en pausa, el reproductor de siempre (video {lay.active})")
    pv.act_motor_pausa.setChecked(True)
    pv.act_motor_pesados.setChecked(False)
    pump(0.2)
    ok(not lane.clasificar(grande, p.media["mg"]), "«⚡ Motor propio para lo pesado» apagado: el 4K, con Qt")
    pv.act_motor_pesados.setChecked(True)
    win.ctrl.undo_stack.setClean()
    win.ctrl._media_dirty = False
    win.close()
    pump(0.3)


def color_sin_etiqueta():
    """🎨 Un 720p SIN etiqueta de color: el motor propio lo enseña como lo verá cualquiera en lo exportado (que lleva el
    mismo YUV etiquetado BT.709), y uno de 480 líneas sin etiqueta sigue como BT.601."""
    print("\n▶ 🎨 color de un video sin etiqueta")
    import numpy as np
    from editoria.core.live_video import FrameSource
    for w, h in ((1280, 720), (854, 480)):
        sin = os.path.join(TMP, f"sin_{h}.mp4")
        ff(["-f", "lavfi", "-i", f"smptebars=s={w}x{h}:r=30:d=1", "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p",
            "-g", "15", sin])
        etiq = os.path.join(TMP, f"exportado_{h}.mp4")     # (lo exportado: el mismo YUV, con la etiqueta de la exportación)
        matriz = "bt709" if h > 576 else "smpte170m"
        ff(["-i", sin, "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", "-colorspace", matriz, etiq])
        ref = subprocess.run([FFMPEG, "-v", "error", "-i", etiq, "-frames:v", "1", "-vf",
                              f"scale=in_color_matrix={'bt709' if h > 576 else 'bt601'}:in_range=tv,format=rgba",
                              "-f", "rawvideo", "-"], capture_output=True, creationflags=M.NO_WINDOW).stdout
        ref = np.frombuffer(ref, np.uint8).reshape(h, w, 4).astype(int)
        s = FrameSource(sin)
        s.want(0.0, False, (w, h))
        fr, _dt = esperar(s, 0.0)
        s.close(1.0)
        if fr is None:
            ok(False, f"{h}p sin etiqueta: sin fotograma")
            continue
        a = np.frombuffer(fr[3], np.uint8).reshape(fr[2], fr[1], 4).astype(int)
        dif = max(int(abs(a[h // 4, int((k + 0.5) * w / 7), :3] - ref[h // 4, int((k + 0.5) * w / 7), :3]).max())
                  for k in range(7))
        ok(dif <= 8, f"{h}p sin etiqueta = lo exportado ({'BT.709' if h > 576 else 'BT.601'}): diferencia máxima {dif} "
                     f"(verde {tuple(a[h // 4, int(3.5 * w / 7), :3])})")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TMP, "salida")
    os.makedirs(out, exist_ok=True)
    hevc = os.path.join(TMP, "b.mp4")
    h264 = os.path.join(TMP, "h.mp4")
    grande = os.path.join(TMP, "g.mp4")
    av1 = os.path.join(TMP, "a.mp4")
    brillo_video(hevc, 1600, 900, 4, "hevc")
    brillo_video(h264, 640, 360, 4, "h264")
    brillo_video(grande, 2880, 1620, 4, "hevc", base=64)
    brillo_video(av1, 640, 360, 4, "av1", base=32)
    energia()
    cola_bateria()
    color_sin_etiqueta()
    motor(hevc)
    visor(h264, grande, av1)
    print()
    if FALLOS:
        print(f"✗ {len(FALLOS)} fallos")
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
