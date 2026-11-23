"""
Prueba de la ⚡ LECTURA ÚNICA (ai/lectura_unica.py): una sola descodificación alimenta a todos los análisis y cada
uno da LO MISMO que con su lectura de siempre:
  · movimiento, siluetas, escenas (también un trozo), imágenes negras, barras negras, pistas, huellas de los clips,
    entender a fondo, fotogramas de la miniatura y tira de la línea de tiempo;
  · video largo (umbral bajado): movimiento y tira con solo fotogramas clave, igual que antes;
  · se puede cancelar (FFmpeg se cierra, nada a medias en la caché) y pausar (FFmpeg congelado);
  · lo nuevo que se guarda en disco es poco.
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar (por el turno):
  .venv/Scripts/python.exe tests/test_lectura_unica.py <carpeta>
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time


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
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))
    return tmp


TMP = _aislar_datos()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from editoria.ai import lectura_unica as LU  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402
from editoria.core.paths import cache_dir  # noqa: E402

FALLOS: list[str] = []
REAL = os.path.join(RAIZ, "Descargas", "fallout 4", "Fallout 4 - Announcement Trailer [XW7Of3g2JME].mp4")


def ok(cond, texto):
    print(("  ✓ " if cond else "  ✗ ") + texto, flush=True)
    if not cond:
        FALLOS.append(texto)


def vaciar_cache():
    d = os.path.join(os.environ["EDITORIA_DATOS"], "cache")
    for raiz, _dirs, files in os.walk(d):
        if os.path.basename(raiz) == "equipo":
            continue
        for f in files:
            try:
                os.remove(os.path.join(raiz, f))
            except OSError:
                pass
    from editoria.ai import library_understanding
    library_understanding._DEEP_MEM.clear()


def video_sintetico(carpeta: str) -> str:
    """60 s, 1280x720 H.264: cortes de escena, barras arriba/abajo y a los lados, un tramo negro y movimiento."""
    out = os.path.join(carpeta, "sintetico.mp4")
    W, H = 1280, 720
    trozos = [f"testsrc2=s={W}x{H}:r=30:d=9", f"mandelbrot=s={W}x{H}:r=30,trim=duration=9",
              f"color=c=black:s={W}x{H}:r=30:d=2", f"life=s={W}x{H}:r=30:mold=10:ratio=0.1,trim=duration=10",
              f"cellauto=s={W}x{H}:r=30:rule=110,trim=duration=8", f"smptehdbars=s={W}x{H}:r=30:d=6",
              f"rgbtestsrc=s={W}x{H}:r=30:d=6", f"testsrc=s={W}x{H}:r=30:d=10"]
    filtros = []
    for i, t in enumerate(trozos):
        extra = f",scale={W}:536,pad={W}:{H}:0:92:black" if i in (1, 3) else \
            (f",scale=960:{H},pad={W}:{H}:160:0:black" if i in (4, 6) else "")
        filtros.append(f"{t},format=yuv420p{extra},setsar=1[v{i}]")
    graph = ";".join(filtros) + ";" + "".join(f"[v{i}]" for i in range(len(trozos))) + \
        f"concat=n={len(trozos)}:v=1:a=0[out]"
    r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-filter_complex", graph,
                               "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast", "-g", "90",
                               "-pix_fmt", "yuv420p", out], timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    return out


def todos(path, dur):
    """Todos los análisis por sus funciones de siempre (con la lectura única encendida o apagada)."""
    from editoria.ai import clip_analysis, edit_maker, silhouette_id, thumb_frames
    from editoria.ai import library_understanding as LUd
    from editoria.core import black_bars, black_frames, scene_cuts, scene_pool
    from editoria.ui import filmstrip
    r, t = {}, {}

    def mide(k, fn):
        t0 = time.perf_counter()
        r[k] = fn()
        t[k] = time.perf_counter() - t0
    mide("movimiento", lambda: edit_maker.motion_profile(path, dur))
    mide("siluetas", lambda: silhouette_id.index_media(path, dur))
    mide("a_fondo", lambda: LUd.analyze_deep(path, "video", dur))
    mide("clip", lambda: clip_analysis.analyze_clip(path, "video", dur))
    mide("escenas", lambda: scene_pool.scenes_of(path, dur))
    mide("escenas_trozo", lambda: scene_cuts.detect(path, dur * 0.25, dur * 0.75, "alta"))
    mide("barras", lambda: black_bars.detect(path, dur))
    mide("negros", lambda: black_frames.detect(path, dur))
    mide("miniatura", lambda: thumb_frames.find([{"media_id": "m", "path": path, "kind": "video",
                                                  "duration": dur}], "", 12))
    mide("tira", lambda: filmstrip.make_sprite(path, dur))
    r["tira_img"] = _leer_jpg(r["tira"])
    r["pistas"] = clip_analysis.simple_cues(path, dur)
    return r, t


def _leer_jpg(p):
    if not p or not os.path.exists(p):
        return None
    import cv2
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


def coseno(a, b):
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    return float((a * b).sum(-1).min() / 1.0) if a.shape == b.shape else -1.0


def comparar(nombre, viejo, nuevo):
    print(f"\n— {nombre}: comparación con la lectura de siempre")
    m0, m1 = viejo["movimiento"], nuevo["movimiento"]
    ok(len(m0["motion"]) == len(m1["motion"]) and np.allclose(m0["motion"], m1["motion"], atol=1e-4)
       and np.array_equal(m0["cut"], m1["cut"]) and np.allclose(m0["bright"], m1["bright"], atol=1e-5),
       f"movimiento igual ({len(m1['motion'])} medidas, cortes {int(m1['cut'].sum())})")
    t0, b0 = viejo["siluetas"]
    t1, b1 = nuevo["siluetas"]
    ok(np.array_equal(t0, t1) and np.array_equal(b0, b1), f"siluetas iguales ({len(t1)} fotogramas)")
    d0, d1 = viejo["a_fondo"], nuevo["a_fondo"]
    same_shape = d0["vecs"].shape == d1["vecs"].shape
    cs = coseno(d0["vecs"], d1["vecs"]) if same_shape else -1
    ok(same_shape and cs > 0.999 and np.allclose(d0["shots"], d1["shots"]) and d0["letterbox"] == d1["letterbox"],
       f"entender a fondo igual (huellas: parecido mínimo {cs:.5f}; {len(d1['shots'])} planos; "
       f"bandas {d1['letterbox']:.2f})")
    c0, c1 = viejo["clip"], nuevo["clip"]
    csc = coseno(c0["vecs"], c1["vecs"]) if c0["vecs"].shape == c1["vecs"].shape else -1
    ok(c0["type"] == c1["type"] and c0["tags"] == c1["tags"] and csc > 0.98,
       f"huellas de los clips: mismo tipo ({c1['type']}) y etiquetas {c1['tags']} (parecido mínimo {csc:.4f})")
    p0, p1 = viejo["pistas"], nuevo["pistas"]
    ok(p0.get("type") == p1.get("type") and p0.get("view") == p1.get("view"),
       f"pistas iguales (tipo {p1.get('type')}, vista {p1.get('view')})")
    ok(viejo["escenas"] == nuevo["escenas"], f"escenas iguales ({len(nuevo['escenas'])})")
    ok(viejo["escenas_trozo"] == nuevo["escenas_trozo"],
       f"cortes en un trozo (sensibilidad alta) iguales ({len(nuevo['escenas_trozo'])})")
    a0, a1 = viejo["barras"], nuevo["barras"]
    ok((a0 is None and a1 is None) or (a0 is not None and a1 is not None and
                                       max(abs(x - y) for x, y in zip(a0, a1)) <= 0.005),
       f"barras negras iguales ({a0} / {a1})")
    n0, n1 = viejo["negros"], nuevo["negros"]
    ok(len(n0) == len(n1) and all(abs(x[0] - y[0]) <= 0.04 and abs(x[1] - y[1]) <= 0.04 for x, y in zip(n0, n1)),
       f"imágenes negras iguales ({n0} / {n1})")
    i0, i1 = viejo["tira_img"], nuevo["tira_img"]
    dif = float(np.abs(i0.astype(np.int16) - i1.astype(np.int16)).mean()) if i0 is not None and i1 is not None \
        and i0.shape == i1.shape else 999
    ok(dif < 3.0, f"tira de la línea de tiempo igual (diferencia media {dif:.2f} de 255)")
    k0 = {round(c.time) for c in viejo["miniatura"]}
    k1 = {round(c.time) for c in nuevo["miniatura"]}
    comun = len(k0 & k1) / max(1, len(k0))
    ok(comun >= 0.75, f"miniatura: {len(k1)} propuestas, {comun:.0%} las mismas que antes")


def miniatura_etapa1(path, dur):
    """Las puntuaciones de cada fotograma (antes de CLIP) son EXACTAMENTE las de antes."""
    from editoria.ai import thumb_frames
    viejo = []
    for t, rgb in thumb_frames._frames(path, 0.0, dur, None):
        got = thumb_frames.score_frame(rgb)
        if got is not None:
            viejo.append([round(t, 2), float(got[0]), got[1]])
    nuevo = thumb_frames.load_scored(path)
    ok(nuevo is not None and len(viejo) == len(nuevo) and all(
        a[0] == b[0] and abs(a[1] - b[1]) < 1e-6 and a[2] == b[2] for a, b in zip(viejo, nuevo)),
        f"miniatura: puntuación de cada fotograma igual ({len(viejo)} fotogramas válidos)")


def probar_video(nombre, path):
    dur = media_tools.probe(path)["duration"]
    print(f"\n▶ {nombre} ({dur:.0f} s)")
    vaciar_cache()
    LU.ACTIVA = False
    t0 = time.perf_counter()
    viejo, tv = todos(path, dur)
    total_viejo = time.perf_counter() - t0
    vaciar_cache()
    LU.ACTIVA = True
    t0 = time.perf_counter()
    inf = LU.asegurar(path, dur, list(LU.TODOS), extras=[])
    t_pasada = time.perf_counter() - t0
    ok(inf.get("ok") and not inf.get("fallos"), f"una sola lectura sin fallos ({inf.get('fallos')})")
    ok(not LU.falta(path, dur), f"todo hecho de una vez (falta: {LU.falta(path, dur)})")
    t0 = time.perf_counter()
    nuevo, tn = todos(path, dur)
    t_despues = time.perf_counter() - t0
    comparar(nombre, viejo, nuevo)
    miniatura_etapa1(path, dur)
    print(f"\n  tiempos — antes: {total_viejo:.1f} s (cada análisis leyendo el video) · ahora: lectura única "
          f"{t_pasada:.1f} s + {t_despues:.1f} s usando lo guardado")
    for k in tv:
        print(f"     {k:<16} antes {tv[k]:6.2f} s   ahora (de la caché) {tn[k]:6.2f} s")
    print("     informe:", inf.get("analisis"))
    return total_viejo, t_pasada + t_despues


def probar_largo(path):
    """Con el umbral de «video largo» bajado a 30 s: movimiento y tira con solo fotogramas clave, igual que antes."""
    from editoria.ai import edit_maker
    from editoria.ui import filmstrip
    dur = media_tools.probe(path)["duration"]
    print("\n▶ video «largo» (umbral bajado a 30 s)")
    viejo_lv, viejo_fl, viejo_lu = edit_maker.LONG_VIDEO, filmstrip.LONG, LU.LARGO
    edit_maker.LONG_VIDEO = filmstrip.LONG = LU.LARGO = 30
    try:
        vaciar_cache()
        LU.ACTIVA = False
        m0 = edit_maker.motion_profile(path, dur)
        s0 = _leer_jpg(filmstrip.make_sprite(path, dur))
        vaciar_cache()
        LU.ACTIVA = True
        inf = LU.asegurar(path, dur, ["movimiento"])
        ok(inf.get("claves") and set(inf.get("analisis", {})) == {"movimiento", "tira"},
           f"solo con fotogramas clave hace movimiento y tira ({inf.get('analisis')})")
        m1 = edit_maker.motion_profile(path, dur)
        s1 = _leer_jpg(filmstrip.make_sprite(path, dur))
        ok(np.allclose(m0["motion"], m1["motion"], atol=1e-4) and np.array_equal(m0["cut"], m1["cut"]),
           "movimiento (fotogramas clave) igual")
        dif = float(np.abs(s0.astype(np.int16) - s1.astype(np.int16)).mean()) if s0 is not None and s1 is not None \
            and s0.shape == s1.shape else 999
        ok(dif < 3.0, f"tira (fotogramas clave) igual ({dif:.2f})")
        # y en una lectura completa de un video largo, movimiento y tira siguen siendo de fotogramas clave (select=key)
        vaciar_cache()
        inf = LU.asegurar(path, dur, ["escenas", "movimiento", "tira"], extras=[])
        ok(not inf.get("claves"), "con escenas, la lectura es completa")
        m2 = edit_maker.motion_profile(path, dur)
        s2 = _leer_jpg(filmstrip.make_sprite(path, dur))
        ok(np.allclose(m0["motion"], m2["motion"], atol=1e-4) and np.array_equal(m0["cut"], m2["cut"]),
           "movimiento de un video largo en la lectura completa = el de fotogramas clave")
        dif = float(np.abs(s0.astype(np.int16) - s2.astype(np.int16)).mean()) if s0 is not None and s2 is not None \
            and s0.shape == s2.shape else 999
        ok(dif < 3.0, f"tira de un video largo en la lectura completa igual ({dif:.2f})")
    finally:
        edit_maker.LONG_VIDEO, filmstrip.LONG, LU.LARGO = viejo_lv, viejo_fl, viejo_lu


def probar_cancelar_y_pausar(path):
    print("\n▶ cancelar y pausar")
    dur = media_tools.probe(path)["duration"]
    vaciar_cache()
    stop = {"v": False}
    err = {}

    def run():
        try:
            LU.asegurar(path, dur, ["escenas", "siluetas", "negros"], extras=[], cancelled=lambda: stop["v"])
        except Exception as e:  # noqa: BLE001
            err["e"] = e
    th = threading.Thread(target=run)
    th.start()
    time.sleep(0.4)
    t0 = time.perf_counter()
    stop["v"] = True
    th.join(10)
    ok(not th.is_alive() and err.get("e").__class__.__name__ == "Cancelled",
       f"cancelar para enseguida ({time.perf_counter() - t0:.2f} s) con Cancelled")
    ok(not LU.hecho("escenas", path, dur) and not LU.hecho("siluetas", path, dur),
       "nada a medias en la caché tras cancelar")
    restos = os.listdir(str(cache_dir("lectura_unica")))
    ok(not restos, f"sin archivos temporales ({restos})")
    # pausa: mientras está en pausa, FFmpeg no avanza (se pausa desde el principio: la lectura dura menos de 1 s)
    vaciar_cache()
    marcas = []
    pausa = {"v": True}

    def prog(f, _t):
        marcas.append((time.perf_counter(), f))
    th = threading.Thread(target=lambda: LU.asegurar(path, dur, ["escenas", "negros", "siluetas"], extras=[],
                                                     progress=prog, pausado=lambda: pausa["v"]))
    t0 = time.perf_counter()
    th.start()
    time.sleep(2.0)
    f_pausa = max((f for _t, f in marcas), default=0.0)
    hecho_en_pausa = LU.hecho("escenas", path, dur)
    pausa["v"] = False
    th.join(120)
    total = time.perf_counter() - t0
    ok(f_pausa == 0.0 and not hecho_en_pausa and th is not None,
       f"en pausa no avanza (progreso {f_pausa:.2f} tras 2 s; nada guardado)")
    ok(LU.hecho("escenas", path, dur) and LU.hecho("siluetas", path, dur), f"al reanudar termina ({total:.1f} s)")


def probar_barras(carpeta):
    """Videos con barras de verdad (en todo el video): la zona con imagen sale igual que con -ss … cropdetect."""
    from editoria.core import black_bars
    print("\n▶ barras negras de verdad")
    casos = {"cine.mp4": "mandelbrot=s=1280x536:r=30,trim=duration=24,format=yuv420p,pad=1280:720:0:92:black",
             "cuatro_tercios.mp4": "life=s=960x720:r=30:mold=10:ratio=0.2,trim=duration=24,format=yuv420p,"
                                   "pad=1280:720:160:0:black",
             "fundido.mp4": "testsrc2=s=960x720:r=30:d=24,fade=in:0:150,fade=out:st=9:d=8,format=yuv420p,"
                            "pad=1280:720:160:0:black",
             "sin_barras.mp4": "testsrc2=s=1280x720:r=30:d=24"}
    for nombre, src in casos.items():
        out = os.path.join(carpeta, nombre)
        r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", src,
                                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out], timeout=120)
        assert r.returncode == 0, r.stderr[-300:]
        dur = media_tools.probe(out)["duration"]
        vaciar_cache()
        LU.ACTIVA = False
        a0 = black_bars.detect(out, dur)
        crops0 = [black_bars._crop_at(out, t) for t in black_bars.sample_times(dur)]
        vaciar_cache()
        LU.ACTIVA = True
        crops1 = []
        orig = LU._ultimo_crop
        LU._ultimo_crop = lambda m: crops1.append(orig(m)) or crops1[-1]
        try:
            LU.asegurar(out, dur, ["barras"], extras=[])
        finally:
            LU._ultimo_crop = orig
        a1 = black_bars.cached(out)[1]
        # El resultado (a0 / a1) tiene que ser EXACTO. Cada tramo, con ±4 px: «life» es aleatorio en cada pasada y sus
        # filas del borde a veces quedan negras un fotograma; -ss y trim pueden caer a un fotograma de distancia y
        # cropdetect da 718 en vez de 720 (intermitente: 1 de cada 5 pasadas, también sin la lectura única nueva)
        casi = len(crops0) == len(crops1) and all(
            (x is None) == (y is None) and (x is None or all(abs(u - v) <= 4 for u, v in zip(x, y)))
            for x, y in zip(crops0, crops1))
        ok(a0 == a1 and casi, f"{nombre}: barras {a1} (antes {a0}); los 8 tramos iguales (±4 px)"
                              + ("" if casi else f" ✗ {crops0} / {crops1}"))


HIJO_HUERFANO = r"""
import os, sys, threading, time, tempfile, atexit, shutil
tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=os.path.join(r"{raiz}", "_pruebas_tmp"))
atexit.register(shutil.rmtree, tmp, True)
os.environ["LOCALAPPDATA"] = tmp
os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
sys.path.insert(0, r"{raiz}")
from editoria.ai import lectura_unica as LU
path = r"{video}"
threading.Thread(target=lambda: LU.asegurar(path, 0, ["escenas", "siluetas"], extras=[], pausado=lambda: True),
                 daemon=True).start()
for _ in range(200):
    if path in LU.EN_MARCHA:
        break
    time.sleep(0.05)
time.sleep(0.5)
print("ffmpeg=" + str(LU.EN_MARCHA[path].pid), flush=True)
print("tmp=" + tmp, flush=True)
time.sleep(120)
"""


def _vivo(pid: int) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259                          # STILL_ACTIVE


def probar_ilegible(carpeta):
    print("\n▶ un archivo que FFmpeg no puede leer")
    from editoria.ai.base import Cancelled
    roto = os.path.join(carpeta, "roto.mp4")
    with open(roto, "wb") as f:
        f.write(os.urandom(300_000))
    quiero = ["movimiento", "siluetas", "escenas", "negros", "tira", "a_fondo"]
    t0 = time.perf_counter()
    inf = LU.asegurar_o_seguir(roto, 60.0, quiero)
    dt = time.perf_counter() - t0
    ok(dt < 2.0 and not any(LU.hecho(n, roto, 60.0) for n in quiero),
       f"acaba enseguida sin guardar nada ({dt:.2f} s; antes, 60 s por cada tubería sin abrir) {inf and inf.get('ok')}")
    t0 = time.perf_counter()
    err = None
    try:
        LU.asegurar(roto, 60.0, quiero, extras=[], cancelled=lambda: True)
    except Cancelled as e:
        err = e
    dt = time.perf_counter() - t0
    ok(err is not None and dt < 2.0, f"y cancelar responde ({dt:.2f} s)")
    restos = os.listdir(str(cache_dir("lectura_unica")))
    ok(not restos, f"sin temporales ni tuberías colgadas ({restos})")


def probar_huerfano(video):
    """Si Reclaimer muere con la lectura EN PAUSA (FFmpeg suspendido), Windows cierra también FFmpeg (Job Object)."""
    import subprocess
    print("\n▶ Reclaimer muere con la lectura en pausa")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=os.path.join(RAIZ, "_pruebas_tmp"),
                                     encoding="utf-8") as f:
        f.write(HIJO_HUERFANO.format(raiz=RAIZ, video=video))
        script = f.name
    hijo = subprocess.Popen([sys.executable, script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=dict(os.environ, PYTHONUTF8="1"))
    try:
        pid, tmpd = 0, ""
        t0 = time.time()
        while time.time() - t0 < 60 and not (pid and tmpd):
            ln = hijo.stdout.readline()
            if not ln:
                break
            if ln.startswith("ffmpeg="):
                pid = int(ln.strip()[7:])
            elif ln.startswith("tmp="):
                tmpd = ln.strip()[4:]
        ok(pid and _vivo(pid), f"FFmpeg en marcha (en pausa) con pid {pid}")
        hijo.kill()                                   # (como el Administrador de tareas)
        hijo.wait(10)
        t0 = time.time()
        while pid and _vivo(pid) and time.time() - t0 < 5:
            time.sleep(0.1)
        ok(pid and not _vivo(pid), f"al matar Reclaimer, FFmpeg muere también ({time.time() - t0:.1f} s)")
        if tmpd:
            __import__("shutil").rmtree(tmpd, True)
    finally:
        if hijo.poll() is None:
            hijo.kill()
        os.remove(script)


def probar_disco(path):
    dur = media_tools.probe(path)["duration"]
    from editoria.ai import thumb_frames
    from editoria.core import scene_cuts
    LU.asegurar(path, dur, ["miniatura", "escenas"], extras=[])
    nuevo = os.path.getsize(thumb_frames._scored_path(path)) + os.path.getsize(scene_cuts._whole_file(path))
    por_hora = nuevo * 3600 / dur / 1e6
    ok(por_hora < 2.0, f"caché nueva: {nuevo / 1024:.0f} KB ({por_hora:.2f} MB por hora de video)")


def main():
    salida = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "_pruebas_tmp", "test_lectura_unica")
    os.makedirs(salida, exist_ok=True)
    print("disponibles:", [n for n in LU.TODOS if LU.disponible(n)])
    sint = video_sintetico(TMP)
    probar_video("sintético", sint)
    probar_largo(sint)
    probar_barras(TMP)
    probar_cancelar_y_pausar(sint)
    probar_ilegible(TMP)
    probar_huerfano(sint)
    probar_disco(sint)
    if os.path.exists(REAL):
        probar_video("tráiler real (AV1 1080p)", REAL)
        probar_disco(REAL)
    else:
        print("(sin el tráiler real: solo el sintético)")
    print("\n" + ("✓ TODO BIEN" if not FALLOS else f"✗ {len(FALLOS)} FALLOS:\n  " + "\n  ".join(FALLOS)))
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
