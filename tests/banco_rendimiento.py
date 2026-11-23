"""
🏋 BANCO DE RENDIMIENTO PESADO de Reclaimer (no es una prueba normal: no empieza por test_, no corre con las demás).

Un proyecto sintético GRANDE (más de 1 h, miles de clips, 4 pistas de video y 4 de audio, H.264 1080p, HEVC 4K, AV1,
imágenes, narración larga con su transcripción, cientos de marcadores y palabras clave, efectos, textos y transiciones)
y las medidas que más nota el usuario, sin ventanas visibles (offscreen):

  arranque y abrir el proyecto · pintar la línea de tiempo al desplazar y al hacer zoom (ms por fotograma, FPS) ·
  arrastrar y recortar un clip · scrub del cabezal (hasta ver el fotograma) · reproducir 10 s de 4K (fotogramas
  perdidos) · exportar 60 s (velocidad) · RAM y CPU en reposo (60 s quieto) y en uso · los 10 puntos más calientes
  (cProfile).

Dos fases, cada una por el turno (cada ejecución dura menos de 15 min):
  BANCO_MODO=generar  .venv/Scripts/python.exe <turno.py> tests/banco_rendimiento.py   → _pruebas_tmp/banco/
      (se puede repetir: lo ya hecho se salta. FFmpeg con la mitad de los núcleos y prioridad baja, con pausas)
  .venv/Scripts/python.exe <turno.py> tests/banco_rendimiento.py                         → mide
      escribe notas_claude/BANCO_RENDIMIENTO.json (historial) y notas_claude/BANCO_RENDIMIENTO.md (tabla, comparación
      con la medida anterior y referencia aproximada de Resolve).
Opcional: BANCO_RAPIDO=1 (reposo de 15 s en vez de 60, sin perfilado).
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANCO = os.path.join(RAIZ, "_pruebas_tmp", "banco")
MEDIOS = os.path.join(BANCO, "medios")
PROYECTO = os.path.join(BANCO, "banco.eia")
NOTAS_JSON = os.path.join(RAIZ, "notas_claude", "BANCO_RENDIMIENTO.json")
NOTAS_MD = os.path.join(RAIZ, "notas_claude", "BANCO_RENDIMIENTO.md")
DURACION = 3900.0            # 65 min de línea de tiempo
HILOS = max(1, (os.cpu_count() or 4) // 2)     # FFmpeg: como mucho la mitad de los núcleos


def _aislar_datos():
    import atexit
    import shutil
    tmproot = os.path.join(RAIZ, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(RAIZ, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ====================================================================== 1) generar el material
FUENTES_VIDEO = [   # (nombre, filtro lavfi, segundos, códec) — generadores BARATOS (mandelbrot/life a 1080p iban a 5 fps)
    ("h264_1080_a.mp4", "testsrc2=s=1920x1080:r=30", 300, "h264"),
    ("h264_1080_b.mp4", "testsrc2=s=1920x1080:r=30,hue=h=t*25", 300, "h264"),
    ("h264_1080_c.mp4", "rgbtestsrc=s=1920x1080:r=30,hue=h=t*15", 300, "h264"),
    ("h264_1080_d.mp4", "smptehdbars=s=1920x1080:r=30,hue=h=t*10", 300, "h264"),
    ("hevc_4k_a.mp4", "testsrc2=s=3840x2160:r=30", 60, "hevc"),
    ("hevc_4k_b.mp4", "testsrc2=s=3840x2160:r=30,hue=h=t*30", 45, "hevc"),
    ("av1_1080_a.mp4", "testsrc=s=1920x1080:r=30", 120, "av1"),
    ("av1_1080_b.mp4", "smptehdbars=s=1920x1080:r=30,hue=h=t*20", 120, "av1"),
]
CODECS = {"h264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "33"],
          "hevc": ["-c:v", "libx265", "-preset", "ultrafast", "-crf", "30", "-x265-params", f"pools={HILOS}:log-level=error"],
          "av1": ["-c:v", "libsvtav1", "-preset", "12", "-crf", "40"]}


def _ff(args: list[str], timeout: float = 1200):
    from editoria.core import media as media_tools
    from editoria.export.parallel import lower_priority
    p = subprocess.Popen([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y"] + args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lower_priority(p.pid)                              # (que el PC siga respondiendo mientras genera)
    _err = p.communicate(timeout=timeout)[1]
    if p.returncode != 0:
        raise RuntimeError(_err.decode(errors="replace")[-600:])


def _hecho(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def generar():
    os.makedirs(MEDIOS, exist_ok=True)
    t_total = time.time()
    for nombre, src, dur, codec in FUENTES_VIDEO:
        out = os.path.join(MEDIOS, nombre)
        if _hecho(out):
            continue
        t0 = time.time()
        # sonido de juego (tono que cambia) para que los videos tengan audio, como una grabación
        _ff(["-f", "lavfi", "-i", f"{src},format=yuv420p", "-f", "lavfi", "-i",
             "sine=f=220:sample_rate=48000,volume=0.2", "-t", str(dur), "-threads", str(HILOS)] + CODECS[codec] +
            ["-g", "60", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-shortest", out + ".tmp.mp4"])
        os.replace(out + ".tmp.mp4", out)
        print(f"  {nombre}: {time.time() - t0:.0f} s", flush=True)
        time.sleep(3)                                  # (pausa entre bloques pesados)
    for i in range(30):                                # imágenes
        out = os.path.join(MEDIOS, f"imagen_{i:02d}.png")
        if not _hecho(out):
            _ff(["-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=1,hue=h={i * 12}", "-frames:v", "1", out])
    nar = os.path.join(MEDIOS, "narracion.m4a")        # 65 min de voz real (la narración de prueba en bucle)
    if not _hecho(nar):
        _ff(["-stream_loop", "-1", "-i", os.path.join(RAIZ, "tests", "assets", "narracion_prueba.wav"),
             "-t", str(DURACION), "-ac", "1", "-c:a", "aac", "-b:a", "48k", nar + ".tmp.m4a"])
        os.replace(nar + ".tmp.m4a", nar)
    mus = os.path.join(MEDIOS, "musica.m4a")           # 10 min de «música»
    if not _hecho(mus):
        _ff(["-f", "lavfi", "-i", "aevalsrc=0.15*sin(2*PI*(220+40*floor(mod(t\\,8)))*t)+0.1*sin(2*PI*330*t)"
             "*gt(mod(t\\,0.5)\\,0.25):s=48000:d=600", "-ac", "2", "-c:a", "aac", "-b:a", "96k", mus + ".tmp.m4a"])
        os.replace(mus + ".tmp.m4a", mus)
    for i in range(6):                                 # efectos de sonido
        out = os.path.join(MEDIOS, f"sfx_{i}.wav")
        if not _hecho(out):
            _ff(["-f", "lavfi", "-i", f"sine=f={300 + 150 * i}:d=0.6,afade=t=out:st=0.2:d=0.4", "-ar", "48000", out])
    crear_proyecto()
    print(f"material listo en {BANCO} ({_tamano_mb(MEDIOS):.0f} MB) en {time.time() - t_total:.0f} s", flush=True)


def _tamano_mb(d: str) -> float:
    return sum(os.path.getsize(os.path.join(r, f)) for r, _ds, fs in os.walk(d) for f in fs) / 1e6


PALABRAS_CLAVE = [f"{a} {b}" for a in ("Halcón", "Titán", "Reina", "Ciudad", "Fortaleza", "Nave", "Bosque", "Guerra",
                                       "Torre", "Isla", "Dragón", "Legión", "Sombra", "Imperio", "Abismo")
                  for b in ("Roja", "Eterna", "Perdida", "de Hierro", "del Norte", "Oscura", "Final", "Prima",
                            "de Cristal", "Salvaje", "Dorada", "Sin Nombre", "Antigua", "Rota", "Nueva",
                            "del Sur", "Gris", "Celeste", "de Fuego", "Helada")]     # 300


def crear_proyecto():
    """El proyecto: 65 min, 4 pistas de video y 4 de audio, ~2450 clips (~1630 de video), ~5400 palabras."""
    from editoria.core import media as media_tools
    from editoria.core.model import (KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TEXT_DEFAULTS, TRACK_AUDIO, TRACK_VIDEO,
                                     Clip, Marker, MediaItem, Project, Track, new_id)
    rnd = random.Random(7)
    p = Project.new()
    p.name = "Banco de rendimiento"
    p.fps = 30.0
    p.tracks = [Track(new_id(), TRACK_VIDEO, n) for n in ("V4", "V3", "V2", "V1")] + \
        [Track(new_id(), TRACK_AUDIO, n, role=r) for n, r in (("A1", "voz"), ("A2", "musica"), ("A3", "efectos"),
                                                               ("A4", ""))]
    V4, V3, V2, V1, A1, A2, A3, A4 = (t.id for t in p.tracks)

    def media(nombre: str) -> MediaItem:
        path = os.path.join(MEDIOS, nombre)
        info = media_tools.probe(path)
        kind = KIND_IMAGE if nombre.endswith(".png") else KIND_AUDIO if nombre.endswith((".m4a", ".wav")) \
            else KIND_VIDEO
        m = MediaItem(new_id(), path, kind, nombre, duration=0.0 if kind == KIND_IMAGE else float(info["duration"]),
                      width=info["width"], height=info["height"], fps=info["fps"], has_audio=info["has_audio"],
                      channels=int(info.get("channels", 0)), probed=True)
        p.media[m.id] = m
        return m
    vids = [media(n) for n, *_r in FUENTES_VIDEO]
    imgs = [media(f"imagen_{i:02d}.png") for i in range(30)]
    nar, mus = media("narracion.m4a"), media("musica.m4a")
    sfx = [media(f"sfx_{i}.wav") for i in range(6)]

    def clip(m, track, start, dur, src=0.0, **kw):
        c = Clip(new_id(), m.id if m else "", track, round(start, 3), round(src, 3), round(dur, 3), **kw)
        p.clips[c.id] = c
        return c
    # V1: el video principal, un plano tras otro (H.264, AV1 y de vez en cuando HEVC 4K), con transiciones y efectos
    t, k = 0.0, 0
    while t < DURACION - 1:
        m = vids[4] if k % 25 == 12 else rnd.choice(vids[:4] + vids[6:])
        d = min(rnd.uniform(4.5, 8.0), DURACION - t)
        if m is vids[4] and k == 12:
            d = 14.0                                       # (al menos un plano 4K largo para la prueba de reproducción)
        src = rnd.uniform(0, max(0.0, m.duration - d - 0.1))
        fx = {}
        if k % 9 == 0 and k:
            fx["trans"] = {"type": rnd.choice(["fade", "dissolve", "flash"]), "dur": 0.5}
        if k % 13 == 0:
            fx["shake"] = 0.4
        if k % 17 == 0:
            fx["flash"] = 0.12
        link = new_id()
        clip(m, V1, t, d, src, fx=fx or None, link=link,
             color={"exposure": 0.2, "saturation": 1.1} if k % 21 == 0 else None)
        if m.has_audio and k % 2 == 0:                     # su sonido de juego, vinculado (A4)
            clip(m, A4, t, d, src, link=link, volume=0.4)
        t += d
        k += 1
    # V2: B-roll cada ~10 s (imágenes y videos), algunos en ventana (PiP)
    t = 5.0
    while t < DURACION - 4:
        m = rnd.choice(imgs + vids[:4])
        d = rnd.uniform(2.5, 4.0)
        src = 0.0 if m.kind == KIND_IMAGE else rnd.uniform(0, m.duration - d - 0.1)
        clip(m, V2, t, d, src, layout={"x": 0.6, "y": 0.55, "w": 0.35, "h": 0.35} if rnd.random() < 0.3 else None,
             fx={"fade_in": 0.2, "fade_out": 0.2})
        t += rnd.uniform(8.0, 12.0)
    # V3: textos
    t = 2.0
    n = 0
    while t < DURACION - 3:
        clip(None, V3, t, 3.0, text=dict(TEXT_DEFAULTS, content=f"{PALABRAS_CLAVE[n % 300]} — rótulo {n}"))
        t += rnd.uniform(6.0, 10.0)
        n += 1
    # V4: superposiciones (imágenes pequeñas)
    for t in range(15, int(DURACION) - 5, 30):
        clip(rnd.choice(imgs), V4, float(t), 2.5, layout={"x": 0.05, "y": 0.05, "w": 0.2, "h": 0.2})
    # A1: la narración, en trozos (como tras quitar silencios), A2 música, A3 efectos
    t = 0.0
    while t < DURACION - 0.5:
        d = min(rnd.uniform(8, 18), DURACION - t)
        clip(nar, A1, t, d, t)
        t += d
    for t in range(0, int(DURACION), 600):
        clip(mus, A2, float(t), min(600.0, DURACION - t), 0.0, volume=0.25)
    for _ in range(200):
        clip(rnd.choice(sfx), A3, rnd.uniform(0, DURACION - 1), 0.6)
    # marcadores (300, uno por palabra clave) y transcripción falsa de la narración (la de prueba, repetida, con
    # palabras clave metidas)
    for i in range(300):
        p.markers.append(Marker(new_id(), round(i * DURACION / 300, 2), label=f"🔑 {PALABRAS_CLAVE[i]}"))
    p.kw_choices = {PALABRAS_CLAVE[i].lower(): rnd.choice(["gameplay", "cinematic", "image"]) for i in range(300)}
    base = json.load(open(os.path.join(RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json"),
                          encoding="utf-8"))["words"]
    words, off, j = [], 0.0, 0
    while off < DURACION - 33:
        for w in base:
            words.append([round(w[0] + off, 3), round(w[1] + off, 3), w[2], w[3]])
        kw = PALABRAS_CLAVE[j % 300].split()
        words.append([round(off + 31.0, 3), round(off + 31.5, 3), kw[0], 0.99])
        words.append([round(off + 31.5, 3), round(off + 32.1, 3), " ".join(kw[1:]) + ".", 0.99])
        off += 32.346
        j += 1
    segs = [{"start": words[i][0], "end": words[min(i + 11, len(words) - 1)][1],
             "text": " ".join(w[2] for w in words[i:i + 12])} for i in range(0, len(words), 12)]
    p.transcripts[nar.id] = {"language": "es", "model": "banco", "words": words, "segments": segs}
    with open(PROYECTO, "w", encoding="utf-8") as f:
        json.dump(p.to_dict(), f, ensure_ascii=False)
    nv = sum(1 for c in p.clips.values() if p.track(c.track_id).kind == TRACK_VIDEO)
    print(f"proyecto: {len(p.clips)} clips ({nv} de video), {len(p.markers)} marcadores, {len(words)} palabras, "
          f"{p.duration() / 60:.1f} min", flush=True)


# ====================================================================== 2) medir
class _Proceso:
    """CPU y RAM de este proceso (sin psutil)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE      # (sin esto el asa -1 se corta a 32 bits: todo daba 0)
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        self.h = k32.GetCurrentProcess()

    def cpu(self) -> float:
        ct, wt = self.ct, self.wt
        c, e, k, u = (wt.FILETIME() for _ in range(4))
        ct.windll.kernel32.GetProcessTimes(self.h, ct.byref(c), ct.byref(e), ct.byref(k), ct.byref(u))
        f = lambda t: (t.dwHighDateTime << 32 | t.dwLowDateTime) / 1e7   # noqa: E731
        return f(k) + f(u)

    def ram_mb(self) -> float:
        ct, wt = self.ct, self.wt

        class PMC(ct.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ct.c_size_t),
                        ("WorkingSetSize", ct.c_size_t), ("QuotaPeakPagedPoolUsage", ct.c_size_t),
                        ("QuotaPagedPoolUsage", ct.c_size_t), ("QuotaPeakNonPagedPoolUsage", ct.c_size_t),
                        ("QuotaNonPagedPoolUsage", ct.c_size_t), ("PagefileUsage", ct.c_size_t),
                        ("PeakPagefileUsage", ct.c_size_t)]
        m = PMC()
        m.cb = ct.sizeof(PMC)
        ct.windll.psapi.GetProcessMemoryInfo(self.h, ct.byref(m), m.cb)
        return m.WorkingSetSize / 1e6


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def medir():
    import cProfile
    rapido = os.environ.get("BANCO_RAPIDO") == "1"
    if not _hecho(PROYECTO):
        print("✗ falta el material: BANCO_MODO=generar primero")
        sys.exit(2)
    pr = _Proceso()
    res: dict = {"cuando": time.strftime("%Y-%m-%d %H:%M"), "nucleos": os.cpu_count()}
    perfiles: dict[str, cProfile.Profile] = {}
    t0 = time.perf_counter()
    import _ajustes  # noqa: F401  (ajustes en un .ini temporal: nunca el registro)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui.main_window import MainWindow
    res["arranque_importar_s"] = round(time.perf_counter() - t0, 2)

    def pump(secs):
        end = time.perf_counter() + secs
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)

    def asentar(maximo=30.0, quieto=0.5):
        """Hasta que la ventana deja de tener trabajo pendiente (o maximo)."""
        t = time.perf_counter()
        ult = time.perf_counter()
        while time.perf_counter() - t < maximo:
            a = time.perf_counter()
            app.processEvents()
            if time.perf_counter() - a > 0.02:
                ult = time.perf_counter()
            if time.perf_counter() - ult > quieto:
                break
            time.sleep(0.005)
        return time.perf_counter() - t

    t0 = time.perf_counter()
    win = MainWindow()
    win.resize(1920, 1080)
    win.show()
    app.processEvents()
    res["arranque_ventana_s"] = round(time.perf_counter() - t0, 2)
    asentar(10)
    print(f"arranque: importar {res['arranque_importar_s']} s, ventana {res['arranque_ventana_s']} s", flush=True)
    # ---------------------------------------------------------------- abrir el proyecto
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    win.open_project(PROYECTO)
    app.processEvents()
    res["abrir_proyecto_s"] = round(time.perf_counter() - t0, 2)
    win.timeline.repaint()
    prof.disable()
    perfiles["abrir proyecto"] = prof
    res["abrir_hasta_quieto_s"] = round(time.perf_counter() - t0 + asentar(30), 2)
    ctrl = win.ctrl
    p = ctrl.project
    res["clips"] = len(p.clips)
    res["palabras"] = sum(len(t.get("words", [])) for t in p.transcripts.values())
    print(f"abrir: {res['abrir_proyecto_s']} s (hasta quieto {res['abrir_hasta_quieto_s']} s), {len(p.clips)} clips",
          flush=True)
    pump(2)
    # ---------------------------------------------------------------- pintar la línea de tiempo
    tl = win.timeline
    cpu0, w0 = pr.cpu(), time.perf_counter()
    ram_uso = [pr.ram_mb()]

    def pintar(n, cambio):
        ts = []
        for i in range(n):
            cambio(i)
            a = time.perf_counter()
            tl.repaint()
            ts.append((time.perf_counter() - a) * 1000)
            app.processEvents()
        return ts
    tl.pps = 30.0
    tl.scroll = 600.0
    prof = cProfile.Profile()
    prof.enable()
    desplazar = pintar(120, lambda i: setattr(tl, "scroll", 600.0 + i * 2.0))
    prof.disable()
    perfiles["desplazar la línea de tiempo"] = prof
    zooms = [30.0 * (0.85 ** k) for k in range(25)] + [30.0 * (0.85 ** (24 - k)) for k in range(25)]
    prof = cProfile.Profile()
    prof.enable()
    zoom = pintar(len(zooms), lambda i: setattr(tl, "pps", zooms[i]))
    prof.disable()
    perfiles["zoom de la línea de tiempo"] = prof
    tl.scroll = 0.0
    tl.pps = max(0.05, (tl.width() - tl.HEADER_W) / max(1.0, p.duration()))
    todo = pintar(20, lambda i: setattr(tl, "scroll", 0.0))
    tl.pps = 30.0
    tl.scroll = 600.0
    tl.repaint()
    ram_uso.append(pr.ram_mb())
    for nombre, xs in (("desplazar", desplazar), ("zoom", zoom), ("todo_a_la_vista", todo)):
        med = _pct(xs, 0.5)
        res[f"linea_{nombre}_ms_mediana"] = round(med, 1)
        res[f"linea_{nombre}_ms_p95"] = round(_pct(xs, 0.95), 1)
        res[f"linea_{nombre}_fps"] = round(1000 / max(med, 0.01), 1)
    print(f"línea de tiempo: desplazar {res['linea_desplazar_ms_mediana']} ms ({res['linea_desplazar_fps']} FPS), "
          f"zoom {res['linea_zoom_ms_mediana']} ms, todo a la vista {res['linea_todo_a_la_vista_ms_mediana']} ms",
          flush=True)
    pump(3)                                                  # (pausa)
    # ---------------------------------------------------------------- arrastrar y recortar
    from editoria.core.model import TRACK_VIDEO
    v1 = [t for t in p.tracks if t.kind == TRACK_VIDEO][-1]
    cand = [c for c in p.clips_on(v1.id) if 620 < c.start < 700]
    arr, rec = [], []
    prof = cProfile.Profile()
    prof.enable()
    for i, c in enumerate(cand[:8]):
        a = time.perf_counter()
        try:
            ctrl.move_clips({c.id: (c.start + 0.2, v1.id)})
        except Exception as e:  # noqa: BLE001
            res.setdefault("avisos", []).append(f"mover: {e}")
        tl.repaint()
        arr.append((time.perf_counter() - a) * 1000)
        app.processEvents()
        a = time.perf_counter()
        try:
            cc = p.clips.get(c.id)
            if cc is not None:
                ctrl.trim_clip(cc.id, "right", cc.end - 0.3)
        except Exception as e:  # noqa: BLE001
            res.setdefault("avisos", []).append(f"recortar: {e}")
        tl.repaint()
        rec.append((time.perf_counter() - a) * 1000)
        app.processEvents()
    a = time.perf_counter()
    ctrl.undo_stack.undo()
    tl.repaint()
    deshacer = (time.perf_counter() - a) * 1000
    prof.disable()
    perfiles["arrastrar y recortar"] = prof
    res["arrastrar_ms_mediana"] = round(_pct(arr, 0.5), 1)
    res["recortar_ms_mediana"] = round(_pct(rec, 0.5), 1)
    res["deshacer_ms"] = round(deshacer, 1)
    print(f"arrastrar {res['arrastrar_ms_mediana']} ms, recortar {res['recortar_ms_mediana']} ms, "
          f"deshacer {res['deshacer_ms']} ms", flush=True)
    pump(3)
    # ---------------------------------------------------------------- scrub y reproducción
    eng = win.engine
    llegadas: list[tuple[float, int, int]] = []          # (cuándo, startTime en µs, qué video de la capa)
    canvas = win.preview.canvas
    lay = canvas.layer(v1.id)
    for k, v in enumerate(getattr(lay, "videos", [])):
        v.videoSink().videoFrameChanged.connect(
            lambda f, k=k: llegadas.append((time.perf_counter(), int(f.startTime()), k)))
    from editoria.core.model import KIND_AUDIO as _KA, KIND_VIDEO as _KV
    from editoria.ui.preview import _full_frame
    encima = [t for t in p.tracks if t.kind == TRACK_VIDEO][:-1]      # (las pistas de video por encima de V1)

    def v1_se_ve(t: float) -> bool:
        """V1 se ve en t: nada opaco a pantalla completa encima (la misma regla del visor). Si una imagen la tapa,
        el visor enseña la imagen al momento y V1 no tiene por qué dar fotogramas: ni scrub ni «perdidos» ahí."""
        for tr in encima:
            c = None if tr.hidden else p.clip_at(tr.id, t)
            m = p.media_of(c) if c is not None and c.enabled else None
            if m is not None and m.kind != _KA and _full_frame(p, c):
                return False
        return True

    def fotograma_bueno(n0: int, src_t: float, fps: float):
        """La primera llegada, desde n0, del fotograma CORRECTO en el video visible de la capa (un fotograma del
        plano que se precarga en otro reproductor, o uno provisional, no cuenta)."""
        for a, st, k in llegadas[n0:]:
            if k == lay.active and (st < 0 or abs(st / 1e6 - src_t) <= 1.5 / max(1.0, fps)):
                return a
        return None
    rnd = random.Random(3)
    scrubs, sin_imagen = [], 0
    prof = cProfile.Profile()
    prof.enable()
    for _ in range(15):
        while True:            # un punto con video en V1 a la vista (con una imagen encima, la imagen sale al momento)
            t = rnd.uniform(60, p.duration() - 60)
            c1 = p.clip_at(v1.id, t)
            m1 = p.media_of(c1) if c1 is not None else None
            if m1 is not None and m1.kind == _KV and v1_se_ve(t):
                break
        src_t, fps1 = c1.src_at(t - c1.start), m1.fps or 30.0
        n0 = len(llegadas)
        a = time.perf_counter()
        eng.seek(t)
        fin = a + 2.0
        while time.perf_counter() < fin and fotograma_bueno(n0, src_t, fps1) is None:
            app.processEvents()
            time.sleep(0.001)
        llego = fotograma_bueno(n0, src_t, fps1)
        if llego is not None:
            scrubs.append((llego - a) * 1000)
        else:
            sin_imagen += 1
        pump(0.15)
    prof.disable()
    perfiles["scrub del cabezal"] = prof
    res["scrub_ms_mediana"] = round(_pct(scrubs, 0.5), 1) if scrubs else None
    res["scrub_ms_p95"] = round(_pct(scrubs, 0.95), 1) if scrubs else None
    res["scrub_sin_imagen_en_2s"] = sin_imagen
    print(f"scrub: {res['scrub_ms_mediana']} ms (p95 {res['scrub_ms_p95']}), sin imagen en 2 s: {sin_imagen}/15",
          flush=True)
    c4k = next((c for c in p.clips_on(v1.id) if (p.media_of(c) and p.media_of(c).width >= 3840
                                                 and c.duration >= 10)), None)
    if c4k is not None:
        t_ini = c4k.start + 0.5
        eng.seek(t_ini)
        pump(1.5)
        llegadas.clear()
        cpu_a, w_a = pr.cpu(), time.perf_counter()
        eng.play()
        pump(10.0)
        eng.pause()
        cpu_rep = (pr.cpu() - cpu_a) / (time.perf_counter() - w_a)
        fps_media = p.media_of(c4k).fps or 30.0
        s0 = c4k.src_at(t_ini - c4k.start)
        # ⚠ Antes se esperaban 300 (10 s × 30), pero ~4 s de ese tramo los tapa una imagen a pantalla completa de V2
        # (ahí V1 no tiene que dar imagen: el visor ni lo decodifica). Ahora: solo los fotogramas en los que V1 se ve,
        # y solo cuentan los de ese tramo del 4K (una vez cada uno).
        vistos = [n for n in range(int(10 * fps_media)) if v1_se_ve(t_ini + (n + 0.5) / fps_media)]
        esperados = len(vistos)
        bien = {int(round((st / 1e6 - s0) * fps_media)) for _a, st, _k in llegadas if st >= 0}
        unicos = len(bien & set(vistos))
        res["reproducir_4k_recibidos"] = len({st for _a, st, _k in llegadas})
        res["reproducir_4k_fotogramas"] = unicos
        res["reproducir_4k_esperados"] = esperados
        res["reproducir_4k_perdidos"] = max(0, esperados - unicos)
        res["reproducir_4k_cpu_nucleos"] = round(cpu_rep, 2)
        ram_uso.append(pr.ram_mb())
        print(f"reproducir 10 s de 4K: {unicos}/{esperados} fotogramas a la vista ({res['reproducir_4k_perdidos']} "
              f"perdidos; {res['reproducir_4k_recibidos']} recibidos en total), CPU {cpu_rep:.2f} núcleos", flush=True)
    res["uso_cpu_pct"] = round(100 * (pr.cpu() - cpu0) / (time.perf_counter() - w0) / (os.cpu_count() or 1), 1)
    res["uso_ram_mb_max"] = round(max(ram_uso), 0)
    pump(3)
    # ---------------------------------------------------------------- exportar 60 s
    try:
        from editoria.core import media as media_tools
        from editoria.core.project_tools import slice_project
        from editoria.export.ffmpeg_export import ExportOptions, build_command
        q = slice_project(p, 600.0, 660.0)
        out = os.path.join(TMP, "export.mp4")
        script = os.path.join(TMP, "filtro.txt")
        for enc in ("gpu", "cpu"):
            args, dur = build_command(q, ExportOptions(path=out, width=1920, height=1080, fps=30, encoder=enc,
                                                       low_priority=True), media_tools.ffmpeg(), script)
            a = time.perf_counter()
            r = subprocess.run(args, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            dt = time.perf_counter() - a
            if r.returncode == 0:
                res["exportar_60s_s"] = round(dt, 1)
                res["exportar_x_tiempo_real"] = round(dur / max(dt, 0.01), 2)
                res["exportar_codificador"] = enc
                break
        print(f"exportar 60 s: {res.get('exportar_60s_s')} s ({res.get('exportar_x_tiempo_real')}× tiempo real, "
              f"{res.get('exportar_codificador')})", flush=True)
    except Exception as e:  # noqa: BLE001
        res.setdefault("avisos", []).append(f"exportar: {e}")
    pump(5)
    # ---------------------------------------------------------------- reposo
    quieto = 15.0 if rapido else 60.0
    cpu_a, w_a = pr.cpu(), time.perf_counter()
    pump(quieto)
    dt = time.perf_counter() - w_a
    res["reposo_s"] = quieto
    res["reposo_cpu_pct_total"] = round(100 * (pr.cpu() - cpu_a) / dt / (os.cpu_count() or 1), 2)
    res["reposo_cpu_pct_un_nucleo"] = round(100 * (pr.cpu() - cpu_a) / dt, 1)
    res["reposo_ram_mb"] = round(pr.ram_mb(), 0)
    print(f"reposo {quieto:.0f} s: CPU {res['reposo_cpu_pct_total']} % del PC ({res['reposo_cpu_pct_un_nucleo']} % de "
          f"un núcleo), RAM {res['reposo_ram_mb']} MB", flush=True)
    # ---------------------------------------------------------------- puntos calientes
    res["calientes"] = [] if rapido else _calientes(perfiles)
    ctrl.undo_stack.setClean()
    ctrl._media_dirty = False
    win.close()
    pump(0.5)
    _guardar(res)


# cuánto lo nota el usuario (por bloque): lo que pasa a cada fotograma o al tocar algo pesa más que abrir
PESO = {"desplazar la línea de tiempo": 5.0, "zoom de la línea de tiempo": 4.0, "arrastrar y recortar": 4.0,
        "scrub del cabezal": 3.0, "abrir proyecto": 1.0}


def _calientes(perfiles: dict) -> list[dict]:
    import pstats
    filas = {}
    for bloque, prof in perfiles.items():
        st = pstats.Stats(prof)
        for (fichero, linea, fn), (_cc, nc, tt, ct, _callers) in st.stats.items():
            if "editoria" not in fichero.replace("\\", "/"):
                continue
            rel = fichero.replace("\\", "/").split("editoria/", 1)[-1]
            k = (rel, linea, fn)
            d = filas.setdefault(k, {"funcion": f"{rel}:{linea} {fn}", "propio_s": 0.0, "total_s": 0.0,
                                     "llamadas": 0, "bloques": {}, "nota": 0.0})
            d["propio_s"] += tt
            d["total_s"] = max(d["total_s"], ct)
            d["llamadas"] += nc
            d["bloques"][bloque] = round(d["bloques"].get(bloque, 0) + tt, 3)
            d["nota"] += tt * PESO.get(bloque, 1.0)
    top = sorted(filas.values(), key=lambda d: -d["nota"])[:10]
    for d in top:
        d["propio_s"] = round(d["propio_s"], 3)
        d["total_s"] = round(d["total_s"], 3)
        d["nota"] = round(d["nota"], 3)
    return top


REFERENCIA = {   # cómo se siente Resolve (aproximado, en un PC parecido) y objetivo
    "arranque_ventana_s": ("≈ 8–15 s (Resolve tarda en abrir)", "< 5 s"),
    "abrir_proyecto_s": ("≈ 2–5 s un proyecto de 1 h", "< 3 s"),
    "linea_desplazar_fps": ("60 FPS", "60 FPS (≤ 16,7 ms por fotograma)"),
    "linea_zoom_fps": ("60 FPS", "60 FPS"),
    "linea_todo_a_la_vista_fps": ("≈ 30–60 FPS", "≥ 30 FPS"),
    "arrastrar_ms_mediana": ("instantáneo (< 16 ms)", "< 16 ms"),
    "recortar_ms_mediana": ("instantáneo (< 16 ms)", "< 16 ms"),
    "deshacer_ms": ("< 50 ms", "< 50 ms"),
    "scrub_ms_mediana": ("< 50 ms (con caché, casi inmediato)", "< 50 ms"),
    "reproducir_4k_perdidos": ("0 con GPU (HEVC 4K por hardware)", "0"),
    "exportar_x_tiempo_real": ("≈ 3–6× en 1080p con GPU", "≥ 3×"),
    "reposo_cpu_pct_total": ("< 1 %", "< 2 %"),
    "reposo_ram_mb": ("≈ 1–2 GB (Resolve usa mucha)", "< 1,5 GB"),
}
NOMBRES = {
    "arranque_importar_s": "Arranque: cargar el programa (s)", "arranque_ventana_s": "Arranque: abrir la ventana (s)",
    "abrir_proyecto_s": "Abrir el proyecto de 65 min (s)", "abrir_hasta_quieto_s": "Abrir hasta quedar quieto (s)",
    "linea_desplazar_ms_mediana": "Desplazar la línea: ms por fotograma (mediana)",
    "linea_desplazar_ms_p95": "Desplazar la línea: ms por fotograma (p95)",
    "linea_desplazar_fps": "Desplazar la línea: FPS equivalentes",
    "linea_zoom_ms_mediana": "Zoom: ms por fotograma (mediana)", "linea_zoom_ms_p95": "Zoom: ms (p95)",
    "linea_zoom_fps": "Zoom: FPS equivalentes",
    "linea_todo_a_la_vista_ms_mediana": "Todo el proyecto a la vista: ms por fotograma",
    "linea_todo_a_la_vista_fps": "Todo a la vista: FPS equivalentes",
    "arrastrar_ms_mediana": "Arrastrar un clip: latencia (ms)", "recortar_ms_mediana": "Recortar un clip: latencia (ms)",
    "deshacer_ms": "Deshacer (ms)", "scrub_ms_mediana": "Scrub: hasta ver el fotograma (ms, mediana)",
    "scrub_ms_p95": "Scrub (ms, p95)", "scrub_sin_imagen_en_2s": "Scrub: sin imagen en 2 s (de 15)",
    "reproducir_4k_esperados": "Reproducir 10 s de HEVC 4K: fotogramas a la vista (V1 sin tapar)",
    "reproducir_4k_perdidos": "Reproducir 10 s de HEVC 4K: fotogramas perdidos",
    "reproducir_4k_cpu_nucleos": "Reproducir 4K: CPU (núcleos)",
    "exportar_60s_s": "Exportar 60 s (s)", "exportar_x_tiempo_real": "Exportar: × tiempo real",
    "uso_cpu_pct": "CPU en uso (% del PC)", "uso_ram_mb_max": "RAM en uso (MB, máx.)",
    "reposo_cpu_pct_total": "Reposo 60 s: CPU (% del PC)", "reposo_cpu_pct_un_nucleo": "Reposo: CPU (% de un núcleo)",
    "reposo_ram_mb": "Reposo: RAM (MB)",
}


def _guardar(res: dict):
    hist = []
    try:
        with open(NOTAS_JSON, encoding="utf-8") as f:
            hist = json.load(f)
    except (OSError, ValueError):
        pass
    anterior = hist[-1] if hist else None
    base = hist[0] if hist else res
    hist.append(res)
    with open(NOTAS_JSON, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    lineas = ["# Banco de rendimiento de Reclaimer", "",
              "Proyecto sintético de 65 min (`_pruebas_tmp/banco/`, generado con `BANCO_MODO=generar`): "
              f"{res.get('clips')} clips en 4 pistas de video y 4 de audio (H.264 1080p, HEVC 4K, AV1, imágenes), "
              f"narración de 65 min con {res.get('palabras')} palabras transcritas, 300 marcadores y palabras clave, textos, efectos y "
              "transiciones. Medido offscreen por el turno con `tests/banco_rendimiento.py` (se puede repetir: compara "
              "con la medida anterior; historial en `BANCO_RENDIMIENTO.json`).", "",
              f"Medida: {res['cuando']} · {res['nucleos']} hilos de CPU · línea base: {base.get('cuando')}", "",
              "| Métrica | Línea base | Anterior | Ahora | Resolve (aprox.) | Objetivo |",
              "|---|---|---|---|---|---|"]
    # (el 20/11 cambió cómo se miden reproducir y scrub: su línea base es la primera medida con la regla nueva —con el
    #  código de antes—, y entre paréntesis lo que daba la regla vieja, para que no se compare 113 con 3 sin más)
    base_nueva = next((h for h in hist if "reproducir_4k_recibidos" in h), res)
    for k, nombre in NOMBRES.items():
        if k not in res:
            continue
        ref, obj = REFERENCIA.get(k, ("", ""))
        ant = anterior.get(k, "") if anterior else ""
        b = base.get(k, "")
        if k.startswith(("reproducir_4k", "scrub_")) and base_nueva is not base:
            b = f"{base_nueva.get(k, '')}" + (f" (regla vieja: {base.get(k)})" if base.get(k, "") != "" else "")
        lineas.append(f"| {nombre} | {b} | {ant} | **{res.get(k)}** | {ref} | {obj} |")
    lineas += ["", "Notas: offscreen (sin ventana ni GPU de pantalla): el visor se pinta en memoria, sin superficie de "
               "la tarjeta; la tarjeta solo cuenta para decodificar (motor propio con D3D11VA). Perfilado solo con "
               "cProfile (py-spy no está instalado). Línea de tiempo pintada con repaint() (1920×1080), sin contar el "
               "tiempo del sistema de ventanas.",
               "",
               "Cómo se mide la reproducción y el scrub (corregido el 20/11 noche): en el tramo de 4K, ~4 s los tapa "
               "una imagen de V2 a pantalla completa, y ahí V1 no tiene que dar imagen (el visor ni lo decodifica). "
               "Antes se esperaban 300 fotogramas y salían «113 perdidos» que en realidad estaban tapados; ahora solo "
               "cuentan los fotogramas en los que V1 se ve (181), cada uno una vez y solo los de ese tramo. El scrub "
               "salta a puntos con video de V1 a la vista y espera el fotograma CORRECTO en el video visible de la "
               "capa (uno del plano que se precarga en otro reproductor, o uno provisional, no cuenta). Medido con "
               "la regla nueva y el código de antes (BANCO_RAPIDO): scrub 71,7 ms (p95 94) y 3 de 15 sin imagen "
               "(los AV1, que Qt no decodifica sin tarjeta), 4K 1 perdido de 181 con 1,23 núcleos, reposo 1268 MB."]
    if res.get("avisos"):
        lineas += ["", "Avisos: " + "; ".join(res["avisos"])]
    if res.get("calientes"):
        lineas += ["", "## Los 10 puntos más calientes (cProfile, ordenados por lo que más notaría el usuario)", "",
                   "Nota = tiempo propio × peso del bloque (desplazar ×5, zoom ×4, arrastrar/recortar ×4, scrub ×3, "
                   "abrir ×1).", "",
                   "| # | Función | Propio (s) | Llamadas | Dónde | Nota |", "|---|---|---|---|---|---|"]
        for i, d in enumerate(res["calientes"], 1):
            donde = ", ".join(f"{b} {s:.2f} s" for b, s in sorted(d["bloques"].items(), key=lambda kv: -kv[1]))
            lineas.append(f"| {i} | `{d['funcion']}` | {d['propio_s']} | {d['llamadas']} | {donde} | {d['nota']} |")
    with open(NOTAS_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")
    print(f"\nguardado en {NOTAS_MD}")


if __name__ == "__main__":
    if os.environ.get("BANCO_MODO") == "generar":
        generar()
    else:
        medir()
