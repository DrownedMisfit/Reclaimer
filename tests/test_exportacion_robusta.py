"""
Prueba de la EXPORTACIÓN ROBUSTA (temporales, archivos a medias, cola) y de la INSTANCIA ÚNICA:
  · cada guion de filtros tiene su carpeta de textos y su .ass propios (dos exportaciones a la vez no se pisan) y
    cleanup_script borra todo; el 📸 fotograma no deja nada junto a la imagen;
  · la cola escribe en «<nombre>.parcial.mp4»: cancelar no pisa el video bueno que ya había; si sale bien, lo
    reemplaza; un trabajo que no se puede ni preparar falla y la cola sigue con el siguiente;
  · dos trabajos de la cola con la misma ruta: el segundo pasa a «<nombre> (2)»;
  · sweep_orphans borra los restos viejos (trozos en paralelo, guiones de la cola, textos) y deja los recientes;
  · instancia única: dos bloqueos sobre la misma carpeta de datos (el segundo no entra; otra carpeta sí) y la
    segunda le pasa el proyecto a la primera por QLocalSocket.
Usa una carpeta de datos TEMPORAL.
Ejecutar:  .venv/Scripts/python.exe tests/test_exportacion_robusta.py <carpeta_salida>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_TMPROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
os.environ["LOCALAPPDATA"] = _TMP          # (la copia del puente de Claude, también en la carpeta temporal)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, cond, timeout=120.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.02)
    return cond()


def proyecto_con_texto(segundos=3.0):
    from editoria.core.controller import ProjectController
    from editoria.core.model import Project
    ctrl = ProjectController()
    ctrl._replace(Project.new(), None)
    ctrl.add_text(0.0, segundos, "HOLA")
    ctrl.add_text(0.5, segundos - 0.5, "OTRO")
    return ctrl.project


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "exportacion_robusta"))
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import media as media_tools
    from editoria.export import ffmpeg_export as FE
    ff = media_tools.ffmpeg()

    # 1) Carpeta de textos y .ass propios por guion
    p = proyecto_con_texto()
    d = os.path.join(out, "guiones")
    os.makedirs(d, exist_ok=True)
    s1, s2 = os.path.join(d, "uno.txt"), os.path.join(d, "dos.txt")
    todos = {}
    for s in (s1, s2):
        args, _t = FE.build_command(p, FE.ExportOptions(path=os.path.join(d, "x.mp4"), width=320, height=180,
                                                        encoder="cpu"), ff, s)
        todos[s] = args
    assert FE.texts_dir(s1) != FE.texts_dir(s2)
    for s in (s1, s2):
        png0 = os.path.join(FE.texts_dir(s), "texto_0.png")
        assert os.path.isfile(png0) and png0 in todos[s], (s, todos[s])
    assert not os.path.exists(os.path.join(d, "editoria_textos")), "ya no hay carpeta de textos compartida"
    assert FE.ass_file(s1) == os.path.join(d, "uno.ass")
    FE.cleanup_script(s1)
    assert not os.path.exists(s1) and not os.path.exists(FE.texts_dir(s1)) and os.path.exists(FE.texts_dir(s2))
    FE.cleanup_script(s2)
    assert os.listdir(d) == [], os.listdir(d)
    print("✓ cada guion tiene su carpeta de textos y su .ass; cleanup_script lo borra todo")

    # 1b) 📸 El fotograma no deja temporales junto a la imagen
    from editoria.core.still import render_frame
    fdir = os.path.join(out, "fotograma")
    os.makedirs(fdir, exist_ok=True)
    png = render_frame(p, 1.0, os.path.join(fdir, "foto.png"), ff)
    assert os.path.isfile(png) and sorted(os.listdir(fdir)) == ["foto.png"], os.listdir(fdir)
    from editoria.core.paths import temp_dir
    assert not [n for n in os.listdir(str(temp_dir())) if n.startswith("editoria_fotograma_")], \
        os.listdir(str(temp_dir()))
    print("✓ 📸 el fotograma deja solo la imagen (ni editoria_textos ni .ass en la carpeta del proyecto)")

    # 2) Parcial: cancelar no pisa el bueno; si sale bien, lo reemplaza
    assert FE.partial_path(r"C:\a\video.mp4") == r"C:\a\video.parcial.mp4"
    assert FE.partial_path(r"C:\a\audio.wav") == r"C:\a\audio.parcial.wav"
    from editoria.ui.render_queue import RenderQueue
    q = RenderQueue()
    bueno = os.path.join(out, "bueno.mp4")
    with open(bueno, "wb") as f:
        f.write(b"EL VIDEO BUENO")
    largo = proyecto_con_texto(60.0)
    job = q.add(largo, FE.ExportOptions(path=bueno, width=1280, height=720, fps=30, encoder="cpu", max_quality=True),
                "prueba")
    assert job["opts"]["path"] == bueno, "sin otro trabajo con esa ruta, se queda como pediste"
    q.start()
    parcial = FE.partial_path(bueno)
    assert pump(app, lambda: os.path.exists(parcial) or job["status"] != "running", 60)
    q.stop()
    assert pump(app, lambda: not q.running, 60)
    pump(app, lambda: False, 0.5)
    assert job["status"] == "cancelled", job
    assert open(bueno, "rb").read() == b"EL VIDEO BUENO", "cancelar no debe tocar el video que ya había"
    assert not os.path.exists(parcial), "el parcial se borra al cancelar"
    script = os.path.join(str(temp_dir()), f"editoria_cola_{id(job)}.txt")
    assert not os.path.exists(script), "el guion de la cola se borra al terminar"
    print("✓ cancelar en la cola deja intacto el video bueno y borra el .parcial.mp4 y el guion")

    corto = proyecto_con_texto(2.0)
    roto_dir = os.path.join(out, "no_es_carpeta")
    with open(roto_dir, "w") as f:                  # un ARCHIVO donde haría falta una carpeta: no se puede preparar
        f.write("x")
    j_mal = q.add(corto, FE.ExportOptions(path=os.path.join(roto_dir, "sub", "v.mp4"), width=320, height=180,
                                          encoder="cpu"), "mal")
    j_ok = q.add(corto, FE.ExportOptions(path=bueno, width=320, height=180, fps=30, encoder="cpu"), "bien")
    q.start()
    assert pump(app, lambda: j_ok["status"] in ("done", "error") and not q.running, 120), (j_mal, j_ok)
    assert j_mal["status"] == "error" and j_mal["error"], j_mal
    assert j_ok["status"] == "done", j_ok
    assert open(bueno, "rb").read()[:14] != b"EL VIDEO BUENO" and os.path.getsize(bueno) > 1000
    assert not os.path.exists(parcial)
    print("✓ un trabajo que no se puede preparar falla y la cola sigue; si sale bien, reemplaza al anterior")

    # 3) Rutas de la cola sin duplicar
    q2 = RenderQueue()
    dup = os.path.join(out, "dup", "v.mp4")
    a = q2.add(corto, FE.ExportOptions(path=dup), "a")
    b = q2.add(corto, FE.ExportOptions(path=dup), "b")
    c = q2.add(corto, FE.ExportOptions(path=dup.upper()), "c")
    paths = [x["opts"]["path"] for x in (a, b, c)]
    assert paths[0] == dup and paths[1] == os.path.join(out, "dup", "v (2).mp4") and \
        paths[2].lower() == os.path.join(out, "dup", "v (3).mp4").lower(), paths
    a["status"] = "done"
    d2 = q2.add(corto, FE.ExportOptions(path=dup), "d")
    assert d2["opts"]["path"] == dup, "un trabajo ya terminado no ocupa la ruta"
    assert q2.busy() and q2.pending_count() == 3
    print("✓ dos trabajos de la cola con la misma ruta: el segundo pasa a « (2)», el tercero a « (3)»")

    # 4) sweep_orphans
    from editoria.ui import export_runner as ER
    tdir = str(temp_dir())
    viejos = ["exportar_trozos_0123abcd/trozo_000/filtro.txt", "editoria_cola_123.txt", "editoria_cola_123_textos/t.png",
              "editoria_export_filtro_subs/s.png", "editoria_fotograma_ab12.filtro.txt", "editoria_escucha_ab12.mp4"]
    ajenos = ["mio.txt", "exportar_trozos_nohex/x.txt"]
    recientes = ["exportar_trozos_ffff/x.txt", "editoria_cola_999.txt"]
    for rel in viejos + ajenos + recientes:
        path = os.path.join(tdir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("x")
    hace = time.time() - ER.ORPHAN_AGE - 60
    for rel in viejos + ajenos:                    # el archivo y sus carpetas, «viejos»
        partes = rel.split("/")
        for k in range(len(partes), 0, -1):
            os.utime(os.path.join(tdir, *partes[:k]), (hace, hace))
    ER.sweep_orphans()
    for rel in viejos:
        assert not os.path.exists(os.path.join(tdir, rel.split("/")[0])), rel
    for rel in ajenos + recientes:
        assert os.path.exists(os.path.join(tdir, rel.split("/")[0])), rel
    print("✓ sweep_orphans borra los restos viejos (trozos, guiones de la cola, textos, fotograma, escucha) "
          "y deja los recientes y los ajenos")

    # 5) Instancia única
    from editoria import app as A
    datos = os.path.join(_TMP, "instancia")
    otra = os.path.join(_TMP, "instancia_otra")
    l1 = A.bloquear_instancia(datos)
    assert l1 is not None and l1.isLocked()
    assert A.bloquear_instancia(datos) is None, "la segunda con la misma carpeta de datos no entra"
    l3 = A.bloquear_instancia(otra)
    assert l3 is not None, "con otra carpeta de datos (las pruebas) sí"
    l3.unlock()
    srv = A._escuchar_otras(datos)
    assert srv is not None and srv.isListening()
    eia = os.path.join(out, "mi proyecto.eia")
    codigo = ("import sys; sys.path.insert(0, %r)\n"
              "from PySide6.QtCore import QCoreApplication\n"
              "app = QCoreApplication([])\n"
              "from editoria import app as A\n"
              "sys.exit(0 if A._pasar_a_la_otra(%r, ['main.py', %r], 20000) else 3)\n") % (ROOT, datos, eia)
    proc = subprocess.Popen([sys.executable, "-c", codigo], env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert pump(app, lambda: proc.poll() is not None, 40), "la segunda no terminó"
    assert proc.returncode == 0, f"la segunda no recibió respuesta ({proc.returncode})"
    assert A._instancia.get("pendientes") == [os.path.abspath(eia)], A._instancia.get("pendientes")
    A._instancia["server"], A._instancia["lock"] = srv, l1
    A.soltar_instancia()                     # (lo que hace run() justo tras app.exec())
    assert not srv.isListening() and not l1.isLocked() and "lock" not in A._instancia
    l4 = A.bloquear_instancia(datos)
    assert l4 is not None, "al cerrarse la primera, la siguiente sí entra"
    l4.unlock()
    A._instancia["pendientes"] = []
    print("✓ instancia única: la segunda con los mismos datos no entra y le pasa su proyecto a la primera; "
          "al salir se suelta enseguida")

    # 6) Parciales de un cierre de golpe: se borran al arrancar solo los de un proceso que ya no vive
    muerto = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    muerto.wait()
    p_muerto = os.path.join(out, "golpe.parcial.mp4")
    p_vivo = os.path.join(out, "en_curso.parcial.mp4")
    for x in (p_muerto, p_vivo):
        with open(x, "wb") as f:
            f.write(b"a medias")
    ER.track_partial(p_vivo)
    rec_vivo = ER._partial_record(p_vivo)
    rec_muerto = ER._partial_record(p_muerto, muerto.pid)
    with open(rec_muerto, "w", encoding="utf-8") as f:
        f.write(p_muerto)
    ER.sweep_partials()
    assert not os.path.exists(p_muerto) and not os.path.exists(rec_muerto), "el del proceso muerto, fuera"
    assert os.path.exists(p_vivo) and os.path.exists(rec_vivo), "el de un proceso vivo no se toca"
    ER.discard_partial(p_vivo)
    assert not os.path.exists(p_vivo) and not os.path.exists(rec_vivo)
    print("✓ un .parcial.mp4 de un cierre de golpe se borra al arrancar (solo los apuntados y de un proceso muerto)")

    # 7) La cola evita la ruta de la ventana Exportar; reintento con el procesador solo si es del codificador
    from PySide6.QtCore import QObject

    class Dlg:
        _opts = FE.ExportOptions(path=os.path.join(out, "dlg.mp4"))

        def exportando(self):
            return True

    class Win(QObject):
        _export_dlg = Dlg()
    w = Win()
    q3 = RenderQueue(w)
    j3 = q3.add(corto, FE.ExportOptions(path=os.path.join(out, "dlg.mp4")), "x")
    assert j3["opts"]["path"] == os.path.join(out, "dlg (2).mp4"), j3["opts"]["path"]
    assert ER.looks_like_encoder_failure(["[h264_nvenc] OpenEncodeSessionEx failed: out of memory"])
    assert not ER.looks_like_encoder_failure(["av_interleaved_write_frame(): No space left on device"])
    assert not ER.looks_like_encoder_failure(["C:/x/clip.mp4: No such file or directory"])
    print("✓ la cola no escribe en el archivo que está haciendo la ventana Exportar; GPU→CPU solo si es del codificador")

    # 8) MCP: un archivo del puente viejo no tapa la copia del Reclaimer abierto
    import json
    import socket
    sys.path.insert(0, ROOT)
    import mcp_reclaimer as M
    from editoria.ui.claude_bridge import bridge_file, shared_bridge_file
    libre = socket.socket()
    libre.bind(("127.0.0.1", 0))
    puerto_muerto = libre.getsockname()[1]
    libre.close()
    vivo = socket.socket()
    vivo.bind(("127.0.0.1", 0))
    vivo.listen(1)
    with open(bridge_file(), "w", encoding="utf-8") as f:
        json.dump({"port": puerto_muerto, "token": "viejo", "pid": 1}, f)
    os.makedirs(os.path.dirname(shared_bridge_file()), exist_ok=True)
    with open(shared_bridge_file(), "w", encoding="utf-8") as f:
        json.dump({"port": vivo.getsockname()[1], "token": "bueno", "pid": 2}, f)
    conn, token = M._connect()
    assert conn is not None and token == "bueno", token
    conn.close()
    vivo.close()
    os.remove(shared_bridge_file())
    with open(bridge_file(), "w", encoding="utf-8") as f:
        json.dump({"pid": 1}, f)
    conn, motivo = M._connect()
    assert conn is None and "incompleto" in motivo, motivo
    os.remove(bridge_file())
    print("✓ MCP: prueba los archivos del puente en orden y se queda con el que conecta; incompleto → aviso en español")
    print("TODO OK")


if __name__ == "__main__":
    main()
