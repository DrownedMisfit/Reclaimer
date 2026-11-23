"""
Prueba de la ◈ COLA ÚNICA DE ANÁLISIS (ui/cola_analisis.py):
  · prioridades: lo urgente (ALTA) adelanta a lo recién importado (MEDIA), que se pausa y sigue después; lo de BAJA solo
    con el PC libre y sin nada más urgente; pocos pesados a la vez;
  · cancelar uno en marcha o en cola; cancelar todo (stop_all);
  · pausa sola al reproducir y al exportar (lo ALTA sigue); la lectura única se congela de verdad (FFmpeg suspendido);
  · si alguien espera al archivo que la cola está leyendo, a ese trabajo se le sube la prioridad (sin bloqueos);
  · la interfaz no se bloquea mientras analiza;
  · estado consultable (en marcha, en cola, hechos, tiempo de cada análisis);
  · empezar al importar (prioridad MEDIA) y que abrir un proyecto NO analice nada.
Usa una carpeta de datos TEMPORAL y no abre ventanas. Ejecutar (por el turno):
  .venv/Scripts/python.exe tests/test_cola_analisis.py <carpeta>
"""
from __future__ import annotations

import os
import sys
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
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (ajustes en un .ini temporal: nunca el registro)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core import media as media_tools  # noqa: E402
from editoria.ui import cola_analisis as CA  # noqa: E402

FALLOS: list[str] = []
app = QApplication.instance() or QApplication(sys.argv)


def ok(cond, texto):
    print(("  ✓ " if cond else "  ✗ ") + texto, flush=True)
    if not cond:
        FALLOS.append(texto)


def pump(secs, hasta=None):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        if hasta is not None and hasta():
            return True
        time.sleep(0.01)
    return hasta() if hasta is not None else True


def contador(nombre, pasos=40, paso=0.05, registro=None):
    """Un trabajo de prueba: cuenta pasos (y apunta cuándo da cada uno), mirando control() en cada paso."""
    def fn(progress, control):
        for i in range(pasos):
            if control():
                from editoria.ai.base import Cancelled
                raise Cancelled()
            if registro is not None:
                registro.append((nombre, time.monotonic()))
            time.sleep(paso)
            progress((i + 1) / pasos, f"{nombre} {i + 1}/{pasos}")
        return nombre
    return fn


def prioridades():
    print("\n▶ prioridades")
    c = CA.cola()
    c.max_pesados = 1
    reg = []
    CA._segundos_sin_usar = lambda: 0.0          # alguien está usando el PC
    tm = c.poner(contador("media", registro=reg), "media", CA.MEDIA, clave="m")
    tb = c.poner(contador("baja", pasos=10, registro=reg), "baja", CA.BAJA, clave="b")
    pump(0.6)
    ok(tm.estado == "en marcha" and tb.estado == "en cola", f"la MEDIA empieza y la BAJA espera ({tm.estado}, {tb.estado})")
    ta = c.poner(contador("alta", pasos=30, registro=reg), "alta", CA.ALTA, clave="a")
    pump(0.4)
    ok(ta.estado == "en marcha" and tm.estado == "en pausa", f"llega una ALTA: arranca y la MEDIA se pausa "
                                                             f"({ta.estado}, {tm.estado}: {tm.motivo_pausa})")
    n_media = sum(1 for n, _ in reg if n == "media")
    pump(0.3)
    ok(sum(1 for n, _ in reg if n == "media") == n_media, "la MEDIA en pausa no avanza")
    pump(5, lambda: ta.estado == "hecho")
    pump(0.4)
    ok(ta.estado == "hecho" and tm.estado == "en marcha", f"acaba la ALTA y la MEDIA sigue ({tm.estado})")
    pump(5, lambda: tm.estado == "hecho")
    pump(0.5)
    ok(tm.estado == "hecho" and tm.resultado == "media", "la MEDIA termina (no perdió lo hecho)")
    ok(tb.estado == "en cola", "la BAJA sigue esperando: el PC no está libre")
    CA._segundos_sin_usar = lambda: 999.0        # nadie toca el PC
    pump(5, lambda: tb.estado == "hecho")
    ok(tb.estado == "hecho", "con el PC libre, la BAJA se hace")
    orden = [n for n, _ in reg]
    primera = {n: orden.index(n) for n in ("media", "alta", "baja")}
    ultima_alta = max(i for i, n in enumerate(orden) if n == "alta")
    ok(primera["media"] < primera["alta"] < primera["baja"] and ultima_alta < primera["baja"],
       "orden: media → alta (adelanta) → resto de media → baja")
    dur = tm.duracion()
    ok(dur is not None and 1.5 < dur < 3.5, f"«cuánto tardó» sin contar la pausa ({dur:.2f} s; 40 pasos de 0,05 s)")
    c.max_pesados = max(1, min(3, (os.cpu_count() or 4) // 8))


def cancelar():
    print("\n▶ cancelar")
    c = CA.cola()
    c.max_pesados = 1
    t1 = c.poner(contador("uno", pasos=200), "uno", CA.MEDIA)
    t2 = c.poner(contador("dos", pasos=200), "dos", CA.MEDIA)
    pump(0.4)
    ok(t1.estado == "en marcha" and t2.estado == "en cola", "uno en marcha y otro en cola")
    c.cancelar(t2)
    pump(0.1)
    ok(t2.estado == "cancelado" and t2 not in c._trabajos, "cancelar uno en cola: fuera al momento")
    t0 = time.time()
    c.cancelar(t1)
    pump(3, lambda: t1.estado == "cancelado")
    ok(t1.estado == "cancelado", f"cancelar uno en marcha: para en {time.time() - t0:.2f} s")
    # en pausa también se puede cancelar
    t3 = c.poner(contador("tres", pasos=200), "tres", CA.MEDIA)
    pump(0.3)
    CA.al_reproducir(True)
    pump(0.3)
    ok(t3.estado == "en pausa", f"al reproducir, se pausa ({t3.estado})")
    c.cancelar(t3)
    pump(3, lambda: t3.estado == "cancelado")
    ok(t3.estado == "cancelado", "y en pausa también se cancela")
    CA.al_reproducir(False)
    pump(0.2)


def pausa_reproducir_exportar():
    print("\n▶ pausa al reproducir y al exportar")
    c = CA.cola()
    c.max_pesados = 2
    reg = []
    tm = c.poner(contador("media", pasos=60, registro=reg), "media", CA.MEDIA)
    ta = c.poner(contador("alta", pasos=60, registro=reg), "alta", CA.ALTA)
    pump(0.4)
    CA.al_reproducir(True)
    pump(0.3)
    a0 = sum(1 for n, _ in reg if n == "alta")
    m0 = sum(1 for n, _ in reg if n == "media")
    pump(0.6)
    ok(tm.estado == "en pausa" and sum(1 for n, _ in reg if n == "media") == m0,
       f"reproduciendo: la MEDIA espera ({tm.motivo_pausa})")
    ok(ta.estado == "en marcha" and sum(1 for n, _ in reg if n == "alta") > a0, "la ALTA sigue (la esperas tú)")
    CA.al_reproducir(False)
    pump(0.3)
    ok(tm.estado == "en marcha", "al parar, sigue")
    # exportar: con un QProcess de verdad
    from PySide6.QtCore import QProcess
    proc = QProcess()
    CA.exportacion_empieza(proc)
    proc.start(sys.executable, ["-c", "import time; time.sleep(1.2)"])
    pump(0.4)
    ok(tm.estado == "en pausa" and "exportación" in tm.motivo_pausa, f"exportando: espera ({tm.motivo_pausa})")
    pump(4, lambda: proc.state() == QProcess.NotRunning)
    pump(0.4)
    ok(tm.estado in ("en marcha", "hecho"), f"acaba la exportación: sigue ({tm.estado})")
    # un QProcess que no llega a arrancar tampoco deja la cola en pausa para siempre
    p2 = QProcess()
    CA.exportacion_empieza(p2)
    p2.start("no_existe_este_programa_xyz.exe", [])
    pump(1.0, lambda: CA._AVISOS.get("exportación", 0) == 0)
    ok(CA._AVISOS.get("exportación", 0) == 0, "una exportación que no arranca no deja la pausa puesta")
    pump(8, lambda: tm.estado == "hecho" and ta.estado == "hecho")
    ok(tm.estado == "hecho" and ta.estado == "hecho", "terminan los dos")


def editando_y_dos_motores():
    print("\n▶ pausa mientras editas; dos visores")
    c = CA.cola()
    c.max_pesados = 2
    reg = []
    tm = c.poner(contador("media", pasos=80, registro=reg), "media", CA.MEDIA)
    ta = c.poner(contador("alta", pasos=80, registro=reg), "alta", CA.ALTA)
    pump(0.3)
    viejo = CA._usuario_editando
    CA._usuario_editando = lambda: True
    pump(0.8)
    m0 = sum(1 for n, _ in reg if n == "media")
    a0 = sum(1 for n, _ in reg if n == "alta")
    pump(0.5)
    ok(tm.estado == "en pausa" and tm.motivo_pausa == "estás editando" and
       sum(1 for n, _ in reg if n == "media") == m0, f"editando: lo automático espera ({tm.motivo_pausa})")
    ok(sum(1 for n, _ in reg if n == "alta") > a0, "lo que esperas tú (ALTA) sigue")
    CA._usuario_editando = viejo
    pump(0.8)
    ok(tm.estado == "en marcha", "al dejar de editar, sigue")
    CA.al_reproducir(True, "visor 1")
    CA.al_reproducir(True, "visor 2")
    CA.al_reproducir(False, "visor 1")
    pump(0.4)
    ok(tm.estado == "en pausa", "con dos visores, parar uno no quita la pausa")
    CA.al_reproducir(False, "visor 2")
    pump(0.4)
    ok(tm.estado == "en marcha", "al parar los dos, sigue")
    c.cancelar(tm)
    c.cancelar(ta)
    pump(2, lambda: tm.estado == "cancelado" and ta.estado == "cancelado")


def modo_ligero():
    print("\n▶ modo ligero (equipo modesto)")
    from editoria.core import hw
    os.environ["RECLAIMER_EQUIPO"] = "ram=8,nucleos=4,vram=4"
    viejo = hw._equipo
    hw._equipo = None
    try:
        q = CA.quiero_al_importar()
        ok(not {"clip", "miniatura", "a_fondo"} & set(q) and not CA.quiero_con_pc_libre(),
           f"al importar, solo lo barato: sin CLIP, caras ni «a fondo» ({q})")
        from editoria.ai import lectura_unica as LU
        ok(not {"clip", "miniatura", "a_fondo"} & set(LU.extras_por_defecto()), "y los extras, igual")
    finally:
        os.environ.pop("RECLAIMER_EQUIPO", None)
        hw._equipo = viejo


def video(carpeta, nombre="v.mp4", dur=40):
    out = os.path.join(carpeta, nombre)
    if not os.path.exists(out):
        r = media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                                   f"testsrc2=s=1280x720:r=30:d={dur}", "-c:v", "libx264", "-preset", "veryfast",
                                   "-pix_fmt", "yuv420p", out], timeout=120)
        assert r.returncode == 0, r.stderr[-300:]
    return out


def _prioridad(proc):
    if proc is None:
        return 0
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetPriorityClass(int(proc._handle)))
    except Exception:  # noqa: BLE001
        return 0


def lectura_por_la_cola():
    print("\n▶ la lectura única por la cola: pausa de verdad, interfaz fluida, estado y tiempos")
    from editoria.ai import lectura_unica as LU
    c = CA.cola()
    c.max_pesados = 1
    v = video(TMP, "lectura.mp4", 120)
    dur = media_tools.probe(v)["duration"]
    quiero = ["movimiento", "siluetas", "escenas", "negros", "tira"]
    # la interfaz no se bloquea: un temporizador cada 10 ms no debe retrasarse mucho
    huecos = []
    ult = {"t": time.perf_counter()}

    def tic():
        now = time.perf_counter()
        huecos.append(now - ult["t"])
        ult["t"] = now
    tim = QTimer()
    tim.setInterval(10)
    tim.timeout.connect(tic)
    tim.start()
    t = CA.analizar_archivo(v, dur, CA.MEDIA, quiero)
    ok(t is not None and t.prioridad == CA.MEDIA, "en la cola con prioridad MEDIA")
    pump(0.05)
    CA.al_reproducir(True)           # (enseguida: la lectura de un video corto dura menos de un segundo)
    pump(0.5)
    p0 = t.progreso
    pump(1.2)
    prio = _prioridad(LU.EN_MARCHA.get(v))
    ok(prio == 0x4000, f"FFmpeg de un trabajo automático en prioridad baja ({hex(prio or 0)})")
    ok(t.estado == "en pausa" and abs(t.progreso - p0) < 1e-6 and p0 < 0.99, f"reproduciendo: la lectura se congela "
                                                               f"(progreso {p0:.2f} → {t.progreso:.2f})")
    # alguien (p. ej. «Entender a fondo») necesita ese archivo: espera, y a la cola se le sube la prioridad
    res = {}

    def otro():
        res["inf"] = LU.asegurar(v, dur, ["escenas"])
    th = threading.Thread(target=otro)
    th.start()
    pump(1.5, lambda: t.prioridad == CA.ALTA)
    ok(t.prioridad == CA.ALTA, "quien espera ese archivo le sube la prioridad a ALTA")
    vistas = set()

    def mira():
        pr = _prioridad(LU.EN_MARCHA.get(v))
        if pr:
            vistas.add(pr)
        return 0x20 in vistas or t.estado == "hecho"
    pump(3.0, mira)
    ok(0x20 in vistas, f"al subir a ALTA, FFmpeg pasa a prioridad normal ({[hex(x) for x in vistas]})")
    pump(1.0, lambda: t.estado == "en marcha")
    ok(t.estado in ("en marcha", "hecho"), "y sigue aunque se esté reproduciendo (lo esperan)")
    pump(60, lambda: t.estado == "hecho" and not th.is_alive())
    CA.al_reproducir(False)
    th.join(5)
    ok(t.estado == "hecho" and res.get("inf") == {}, "termina; el que esperaba encuentra todo hecho (sin leer otra vez)")
    ok(not LU.falta(v, dur, quiero), "todo lo pedido, guardado")
    tim.stop()
    peor = max(huecos[5:]) if len(huecos) > 5 else 0
    ok(peor < 0.25, f"la interfaz no se bloquea (peor espera del temporizador: {peor * 1000:.0f} ms)")
    e = c.estado()
    hecho = next((h for h in e["hechos"] if h["id"] == t.id), None)
    ok(hecho is not None and set(quiero) <= set(hecho.get("analisis", {})) and hecho.get("segundos"),
       f"estado consultable: tiempo total {hecho and hecho.get('segundos')} s y por análisis "
       f"{hecho and hecho.get('analisis')}")
    ok(any(nombre == t.titulo and an for nombre, _s, an in c.tiempos()), "lista «cuánto tardó cada análisis»")
    # lo que ya está hecho no vuelve a la cola
    ok(CA.analizar_archivo(v, dur, CA.MEDIA, quiero) is None, "lo ya analizado no se repite")


def al_importar():
    print("\n▶ empezar al importar")
    os.environ["RECLAIMER_ANALIZAR_AL_IMPORTAR"] = "1"
    from editoria.core.controller import ProjectController
    c = CA.cola()
    c.max_pesados = 1
    ctrl = ProjectController(None)
    from editoria.ui.ai_manager import ClipAnalysisManager
    mgr = ClipAnalysisManager(ctrl)
    v1 = video(TMP, "importado.mp4", 20)
    vistos = []
    c.terminado.connect(lambda t: vistos.append(t))
    CA._segundos_sin_usar = lambda: 0.0          # alguien usa el PC: lo de BAJA espera
    k = os.path.normcase(os.path.abspath(v1))
    ctrl.import_now([v1])
    pump(4, lambda: c.buscar_archivo(v1) or any(t.archivo == k for t in vistos))
    todos = c.buscar_archivo(v1) + [t for t in vistos if t.archivo == k]
    t = next((x for x in todos if x.prioridad == CA.MEDIA), None)
    ok(t is not None, "al importar un video, empieza su análisis (MEDIA)")
    lento = next((x for x in todos if x.prioridad == CA.BAJA), None)
    if CA.quiero_con_pc_libre():
        ok(lento is not None and "a_fondo" not in (t.clave[2] if t else ()),
           "«entender a fondo» (CLIP de cada segundo) va aparte, en BAJA: solo con el PC libre")
    pump(60, lambda: t is not None and t.estado == "hecho")
    ok(t is not None and t.estado == "hecho", "lo barato termina solo")
    if lento is not None:
        pump(1.5)
        ok(lento.estado == "en cola", f"lo de BAJA sigue esperando mientras se usa el PC ({lento.estado})")
        c.cancelar(lento)
    CA._segundos_sin_usar = lambda: 999.0
    del mgr
    os.environ.pop("RECLAIMER_ANALIZAR_AL_IMPORTAR", None)


def abrir_no_analiza():
    print("\n▶ abrir un proyecto no analiza nada")
    os.environ["RECLAIMER_ANALIZAR_AL_IMPORTAR"] = "1"
    from editoria.core.controller import ProjectController
    from editoria.ui.ai_manager import ClipAnalysisManager
    c = CA.cola()
    # un proyecto guardado con un video, hecho con la importación apagada
    os.environ["RECLAIMER_ANALIZAR_AL_IMPORTAR"] = "0"
    ctrl0 = ProjectController(None)
    v3 = video(TMP, "viejo.mp4", 15)
    ctrl0.import_now([v3])
    ruta = os.path.join(TMP, "viejo.eia")
    ctrl0.save(ruta)
    pump(2)
    os.environ["RECLAIMER_ANALIZAR_AL_IMPORTAR"] = "1"
    ctrl = ProjectController(None)
    mgr = ClipAnalysisManager(ctrl)
    antes = {t.id for t in c._trabajos} | {t.id for t in c._hechos}
    ctrl.load(ruta)
    pump(3.5)
    nuevos = [t for t in list(c._trabajos) + list(c._hechos) if t.id not in antes]
    ok(not nuevos, f"abrir el proyecto no pone nada en la cola ({[t.titulo for t in nuevos]})")
    del mgr
    os.environ.pop("RECLAIMER_ANALIZAR_AL_IMPORTAR", None)


def cerrar_limpio():
    print("\n▶ cerrar con trabajos en marcha y en pausa")
    from editoria.ui.task_window import stop_all
    c = CA.cola()
    c.max_pesados = 1
    t1 = c.poner(contador("larga", pasos=400), "larga", CA.MEDIA)
    t2 = c.poner(contador("alta", pasos=400), "alta", CA.ALTA)
    pump(0.5)
    ok(t1.estado == "en pausa" and t2.estado == "en marcha", "una en pausa y otra en marcha")
    t0 = time.time()
    vivos = stop_all(3000)
    pump(1.0, lambda: t1.estado == "cancelado" and t2.estado == "cancelado")
    ok(not vivos and t1.estado == "cancelado" and t2.estado == "cancelado",
       f"stop_all las para todas ({time.time() - t0:.2f} s)")
    ok(c.poner(contador("tarde"), "tarde") is None, "con la cola cerrada no entra nada nuevo")


def main():
    prioridades()
    cancelar()
    pausa_reproducir_exportar()
    editando_y_dos_motores()
    modo_ligero()
    lectura_por_la_cola()
    abrir_no_analiza()
    al_importar()
    cerrar_limpio()
    print("\n" + ("✓ TODO BIEN" if not FALLOS else f"✗ {len(FALLOS)} FALLOS:\n  " + "\n  ".join(FALLOS)))
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
