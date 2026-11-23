"""
😂 Memes (biblioteca persistente entre proyectos) y la fila de interruptores por pestaña de trabajo:
  · core/memes: guardar un TRAMO de un clip (con/sin audio) o un archivo entero; buscar por nombre/etiqueta, filtrar
    por tipo y audio; renombrar, etiquetar y quitar (Papelera falsa); el índice se queda en disco;
  · ventana: paneles «Memes» y «Descargas» con su interruptor; en Medios, «😂 Memes» siempre al final y sin repetir;
    doble clic = a Medios y al cabezal (Ctrl+Z lo quita); el panel: rejilla, buscar, poner en el cabezal, quitar;
  · clic derecho en un clip → «Agregar a memes…» guarda SOLO su tramo;
  · los interruptores del edit musical solo en la pestaña «Edits»;
  · (Fable) índice roto → se aparta y se rehace con los archivos; archivos sueltos adoptados; dos «Agregar» con el
    mismo nombre a la vez no chocan; una entrada vieja sin archivo no resucita; el tramo respeta velocidad y reversa
    (congelado = fotograma; parte de audio = solo sonido); FFmpeg cancelable; quitar un meme usado avisa, lo suelta
    del visor y deja sus clips como «no encontrado» (y en Medios sigue saliendo para volver a enlazarlo).
Ejecutar:  .venv/Scripts/python.exe tests/test_memes.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_memes_", dir=_TMPROOT)
__import__("atexit").register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PAPELERA = os.path.join(_TMP, "papelera_falsa")
os.makedirs(PAPELERA, exist_ok=True)


def _papelera(ruta: str) -> bool:
    if not os.path.exists(ruta):
        return False
    shutil.move(ruta, os.path.join(PAPELERA, f"{len(os.listdir(PAPELERA))}_{os.path.basename(ruta)}"))
    return True


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s=30.0):
    t0 = time.time()
    while time.time() - t0 < s:
        if cond():
            return True
        pump(app, 0.05)
    return cond()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_memes")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import media as M
    from editoria.core import memes as MEMES
    from editoria.ui import memes_panel as MP
    MP._a_papelera = _papelera
    ff = M.ffmpeg()
    video = os.path.join(out, "fuente.mp4")
    if not os.path.exists(video):
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:v", "libx264", "-preset",
                        "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video], check=True)
    png = os.path.join(out, "imagen.png")
    im = QImage(200, 120, QImage.Format_RGB32)
    im.fill(QColor("orange"))
    im.save(png)

    # --- núcleo
    assert MEMES.carpeta().startswith(os.environ["EDITORIA_DATOS"]), MEMES.carpeta()
    t = MEMES.agregar_tramo(video, 1.0, 1.5, "Risa fuerte", "risa, sorpresa", audio=False, origen="prueba")
    assert os.path.isfile(t["ruta"]) and abs(t["duracion"] - 1.5) < 0.15 and t["audio"] is False, t
    t2 = MEMES.agregar_tramo(video, 2.0, 1.0, "Con sonido", ["grito"], audio=True)
    assert t2["audio"] is True and abs(t2["duracion"] - 1.0) < 0.15, t2
    i = MEMES.agregar_archivo(png, "Cara naranja", "cara")
    assert i["tipo"] == "image"
    assert len(MEMES.listar()) == 3
    assert [m["nombre"] for m in MEMES.buscar("risa")] == ["Risa fuerte"]
    assert [m["nombre"] for m in MEMES.buscar("SORPRESA")] == ["Risa fuerte"], "por etiqueta, sin mayúsculas"
    assert [m["nombre"] for m in MEMES.buscar(tipo="image")] == ["Cara naranja"]
    assert {m["nombre"] for m in MEMES.buscar(audio=True)} == {"Con sonido"}
    MEMES.renombrar(i["id"], "Cara feliz")
    MEMES.etiquetar(i["id"], "cara, feliz")
    assert MEMES.buscar("feliz")[0]["nombre"] == "Cara feliz"
    with open(os.path.join(MEMES.carpeta(), MEMES.INDICE), encoding="utf-8") as f:
        assert "Cara feliz" in f.read(), "el índice se guarda en disco (sigue ahí en el siguiente proyecto)"
    print("✓ núcleo: tramo con/sin audio, archivo entero, buscar por nombre/etiqueta, filtros, renombrar, etiquetar; "
          "índice en disco")

    # --- (Fable) robustez del núcleo
    import glob
    import threading
    indice = os.path.join(MEMES.carpeta(), MEMES.INDICE)
    with open(indice, "w", encoding="utf-8") as f:
        f.write('[{"id": "x", "archivo": ')                        # (cortado a medias: un corte de luz)
    lista = MEMES.listar()
    assert len(lista) == 3 and {m["tipo"] for m in lista} == {"video", "image"}, lista
    assert glob.glob(indice + ".roto-*"), "el índice roto se guarda aparte"
    MEMES.renombrar(next(m["id"] for m in lista if m["tipo"] == "image"), "Cara feliz")
    MEMES.etiquetar(next(m["id"] for m in MEMES.listar() if m["nombre"] == "Cara feliz"), "cara, feliz")
    for m in MEMES.listar():
        if m["tipo"] == "video":
            MEMES.renombrar(m["id"], "Risa fuerte" if not m["audio"] else "Con sonido")
    print("✓ índice roto: se aparta («memes.json.roto-…») y se rehace con los archivos; no se pierde ninguno")
    suelto = os.path.join(MEMES.carpeta(), "suelto.png")
    shutil.copyfile(png, suelto)
    assert any(m["ruta"] == suelto for m in MEMES.listar()), "un archivo suelto de la carpeta se adopta"
    MEMES.quitar(next(m["id"] for m in MEMES.listar() if m["ruta"] == suelto), _papelera)
    shutil.rmtree(PAPELERA)
    os.makedirs(PAPELERA)
    # dos «Agregar» con el mismo nombre a la vez
    res, errores = [], []

    def agregar():
        try:
            res.append(MEMES.agregar_tramo(video, 0.5, 1.0, "Doble", audio=False))
        except Exception as exc:  # noqa: BLE001
            errores.append(exc)
    hilos = [threading.Thread(target=agregar) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    assert not errores and len(res) == 2 and res[0]["ruta"] != res[1]["ruta"], (errores, res)
    assert all(os.path.isfile(r["ruta"]) for r in res) and len([m for m in MEMES.listar() if m["nombre"] == "Doble"]) == 2
    assert not [f for f in os.listdir(MEMES.carpeta()) if ".part" in f], "sin temporales a medias"
    for r in res:
        MEMES.quitar(r["id"], _papelera)
    print("✓ dos «Agregar» con el mismo nombre a la vez: dos archivos distintos, los dos en la biblioteca")
    # una entrada vieja sin archivo no resucita
    z = MEMES.agregar_archivo(png, "Zombi")
    os.remove(z["ruta"])
    z2 = MEMES.agregar_archivo(png, "Zombi")
    with open(indice, encoding="utf-8") as f:
        import json as _json
        crudo = _json.load(f)
    assert [m["id"] for m in crudo if m["archivo"] == os.path.basename(z2["ruta"])] == [z2["id"]], crudo
    assert len([m for m in MEMES.listar() if m["nombre"] == "Zombi"]) == 1
    MEMES.quitar(z2["id"], _papelera)
    print("✓ una entrada vieja sin archivo no resucita al agregar otro con el mismo nombre")
    # velocidad y reversa
    rapido = MEMES.agregar_tramo(video, 1.0, 2.0, "Rápido", audio=True, velocidad=2.0)
    assert abs(rapido["duracion"] - 1.0) < 0.15, rapido["duracion"]
    lento = MEMES.agregar_tramo(video, 1.0, 1.0, "Lento", audio=True, velocidad=0.5)
    assert abs(lento["duracion"] - 2.0) < 0.2, lento["duracion"]

    def cuadro(ruta, t):
        dst = os.path.join(out, f"cuadro_{os.path.basename(ruta)}_{t:.2f}.png")
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", ruta, "-frames:v", "1", dst],
                       check=True)
        return QImage(dst).scaled(64, 36)

    def dif(a, b):
        return sum(abs(QColor(a.pixel(x, y)).lightness() - QColor(b.pixel(x, y)).lightness())
                   for x in range(0, 64, 4) for y in range(0, 36, 4))
    normal = MEMES.agregar_tramo(video, 1.0, 1.0, "Normal", audio=False)
    reves = MEMES.agregar_tramo(video, 1.0, 1.0, "Revés", audio=False, reversa=True)
    r0, n_fin, n0 = cuadro(reves["ruta"], 0.0), cuadro(normal["ruta"], 0.95), cuadro(normal["ruta"], 0.0)
    assert dif(r0, n_fin) < dif(r0, n0), "al revés: empieza por donde acaba el normal"
    congelado = MEMES.agregar_tramo(video, 2.0, 0.0, "Quieto", velocidad=0.0)
    assert congelado["tipo"] == "image" and congelado["ruta"].endswith(".png"), congelado
    sonido = MEMES.agregar_tramo(video, 1.0, 1.0, "Solo sonido", solo_audio=True)
    assert sonido["tipo"] == "audio" and sonido["ruta"].endswith(".m4a") and sonido["audio"], sonido
    for m in (rapido, lento, normal, reves, congelado, sonido):
        MEMES.quitar(m["id"], _papelera)
    print("✓ el tramo respeta velocidad (×2 → la mitad; ×0,5 → el doble) y reversa; congelado = fotograma; parte de "
          "audio = solo sonido")
    # FFmpeg cancelable: no deja nada a medias
    from editoria.ai.base import Cancelled
    t_cancel = time.monotonic() + 0.3
    try:
        MEMES.agregar_tramo(video, 0.0, 6.0, "Cancelado", audio=True, velocidad=0.5, reversa=True,
                            cancelado=lambda: time.monotonic() > t_cancel)
        cancelado_ok = False
    except Cancelled:
        cancelado_ok = True
    assert cancelado_ok or any(m["nombre"] == "Cancelado" for m in MEMES.listar())
    if cancelado_ok:
        assert not [f for f in os.listdir(MEMES.carpeta()) if ".part" in f or f.startswith("Cancelado")], \
            os.listdir(MEMES.carpeta())
        assert not any(m["nombre"] == "Cancelado" for m in MEMES.listar())
        print("✓ cancelar el corte de FFmpeg lo para y no deja nada a medias")
    else:
        MEMES.quitar(next(m["id"] for m in MEMES.listar() if m["nombre"] == "Cancelado"), _papelera)
        print("· (el corte acabó antes de poder cancelarlo)")
    shutil.rmtree(PAPELERA)
    os.makedirs(PAPELERA)
    assert len(MEMES.listar()) == 3, [m["nombre"] for m in MEMES.listar()]

    # --- ventana
    from editoria.core.model import TRACK_VIDEO
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1920, 1040)
    win.show()
    pump(app, 0.8)
    ctrl = win.ctrl
    try:
        for k in ("memes", "descargas_web"):
            assert k in win.docks and k in win.interruptores, k
            d = win.docks[k]
            assert d.allowedAreas() == (Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        izq = [k for k, _n in win.INTERRUPTORES_IZQ]
        assert "descargas_web" in izq and "memes" in izq, izq            # (a la izquierda; el orden, la barra)
        print("✓ paneles «Memes» y «Descargas» con su interruptor (a la izquierda)")

        # interruptores por pestaña de trabajo
        win.workspaces.switch("youtube")
        pump(app, 0.4)
        assert win.interruptores["edit_opts"].isHidden() and win.interruptores["edit_clips"].isHidden(), \
            "en Video horizontal no salen los del edit musical"
        win.workspaces.switch("edit")
        pump(app, 0.6)
        assert not win.interruptores["edit_opts"].isHidden() and not win.interruptores["edit_clips"].isHidden()
        win.workspaces.switch("youtube")
        pump(app, 0.6)
        assert win.interruptores["edit_opts"].isHidden()
        assert not win.interruptores["memes"].isHidden() and not win.interruptores["media"].isHidden()
        print("✓ la fila de interruptores enseña solo los paneles de la pestaña de trabajo (el edit musical, en Edits)")

        # Medios: «😂 Memes» al final, sin repetir
        lib = win.library
        lib._rebuild()
        pump(app, 0.3)
        top = lib.tree.topLevelItem(lib.tree.topLevelItemCount() - 1)
        from editoria.ui.library import MEMES_SECTION, ROLE_MEDIA, ROLE_PATH
        assert top.data(0, Qt.UserRole + 1) == MEMES_SECTION and top.childCount() == 3, top.text(0)
        it = next(top.child(k) for k in range(top.childCount()) if top.child(k).data(0, ROLE_PATH) == t["ruta"])
        n0 = len(ctrl.project.clips)
        lib._on_double_click(it, 0)
        pump(app, 0.5)
        assert len(ctrl.project.clips) > n0, "doble clic = en el cabezal"
        mid = next(m.id for m in ctrl.project.media.values() if os.path.normcase(m.path) == os.path.normcase(t["ruta"]))
        assert ctrl.project.media[mid].category == MEMES.CATEGORIA
        lib._rebuild()
        pump(app, 0.2)
        cats = [lib.tree.topLevelItem(k).data(0, Qt.UserRole + 1) for k in range(lib.tree.topLevelItemCount())]
        assert cats[-1] == MEMES_SECTION and cats.count(MEMES.CATEGORIA) == 0, ("sin repetir", cats)
        top = lib.tree.topLevelItem(lib.tree.topLevelItemCount() - 1)
        assert any(top.child(k).data(0, ROLE_MEDIA) == mid for k in range(top.childCount())), "ya en Medios, en su sitio"
        ctrl.undo_stack.undo()
        pump(app, 0.2)
        assert len(ctrl.project.clips) == n0, "Ctrl+Z lo quita"
        print("✓ Medios: «😂 Memes» siempre al final, sin repetir; doble clic = a Medios y al cabezal; Ctrl+Z")

        # clic derecho en un clip → «Agregar a memes…»: SOLO su tramo
        (vid,) = ctrl.import_now([video])
        v1 = next(tr for tr in ctrl.project.tracks if tr.kind == TRACK_VIDEO)
        cid = next(c for c in ctrl.add_media([vid], v1.id, 20.0) if ctrl.project.clips[c].track_id == v1.id)
        c = ctrl.project.clips[cid]
        c.source_in, c.duration = 2.5, 2.0               # (un tramo concreto del archivo)
        import inspect
        from editoria.ui import timeline as TLM
        assert "Agregar a memes" in inspect.getsource(TLM), "la opción está en el clic derecho de los clips"
        antes = len(MEMES.listar())
        job = MP.agregar_clip(win.timeline, ctrl, cid, preguntar=False, nombre="Tramo", etiquetas="corte", audio=True)
        assert job is not None and esperar(app, lambda: len(MEMES.listar()) == antes + 1, 40)
        m = next(x for x in MEMES.listar() if x["nombre"] == "Tramo")
        assert abs(m["duracion"] - 2.0) < 0.15 and m["audio"] is True, m
        print(f"✓ «Agregar a memes…» desde un clip: solo su tramo ({m['duracion']:.2f} s, con audio)")
        c.speed, c.duration = 2.0, 1.0                  # (a ×2: 2 s del archivo en 1 s)
        job = MP.agregar_clip(win.timeline, ctrl, cid, preguntar=False, nombre="Tramo rápido", audio=False)
        assert job is not None and esperar(app, lambda: any(x["nombre"] == "Tramo rápido" for x in MEMES.listar()), 40)
        m2 = next(x for x in MEMES.listar() if x["nombre"] == "Tramo rápido")
        assert abs(m2["duracion"] - 1.0) < 0.15, m2
        from editoria.core.model import TRACK_AUDIO
        a1 = next((tr for tr in ctrl.project.tracks if tr.kind == TRACK_AUDIO), None)
        enlazado = next((x for x in ctrl.project.clips.values() if x.media_id == vid and a1 is not None
                         and x.track_id == a1.id), None)
        if enlazado is not None:
            job = MP.agregar_clip(win.timeline, ctrl, enlazado.id, preguntar=False, nombre="Su sonido")
            assert job is not None and esperar(app, lambda: any(x["nombre"] == "Su sonido" for x in MEMES.listar()), 40)
            m3 = next(x for x in MEMES.listar() if x["nombre"] == "Su sonido")
            assert m3["tipo"] == "audio", m3
            print("✓ clic derecho en la parte de AUDIO de un video: solo su sonido")
        c.speed, c.duration = 1.0, 2.0
        print(f"✓ un clip a ×2 se guarda como se ve ({m2['duracion']:.2f} s)")

        # panel Memes
        pan = win.memes
        assert esperar(app, lambda: pan.rejilla.count() == len(MEMES.listar()), 5), pan.rejilla.count()
        pan.buscador.setText("corte")                  # (la etiqueta de «Tramo»)
        pump(app, 0.2)
        assert pan.rejilla.count() == 1
        pan.buscador.setText("")
        pan.filtro_tipo.setCurrentIndex(pan.filtro_tipo.findData("image"))
        pump(app, 0.2)
        assert pan.rejilla.count() == 1
        pan.filtro_tipo.setCurrentIndex(0)
        pump(app, 0.2)
        assert esperar(app, lambda: all(not pan.rejilla.item(k).icon().isNull() for k in range(pan.rejilla.count())),
                       20), "miniaturas con duración"
        pan.rejilla.setCurrentRow(0)
        n0 = len(ctrl.project.clips)
        pan.poner_en_cabezal(pan.elegidos())
        assert len(ctrl.project.clips) > n0
        ctrl.undo_stack.undo()
        # quitar uno USADO en la línea de tiempo: avisa, lo suelta y sus clips salen como «no encontrado»
        from editoria.ui import descargas_generales as DG
        k_usado = next(k for k in range(pan.rejilla.count()) if pan.rejilla.item(k).text() == "Tramo rápido")
        usado = pan.rejilla.item(k_usado).data(Qt.UserRole)
        pan.rejilla.clearSelection()
        pan.rejilla.item(k_usado).setSelected(True)
        pan.poner_en_cabezal(pan.elegidos())
        assert DG.usos(ctrl, [usado["ruta"]]) == 1, "se avisaría: «1 se usa en este proyecto»"
        pump(app, 0.3)
        pan.rejilla.clearSelection()
        k_usado = next(k for k in range(pan.rejilla.count()) if pan.rejilla.item(k).text() == "Tramo rápido")
        pan.rejilla.item(k_usado).setSelected(True)
        assert pan.quitar(preguntar=False) == 1, pan.estado.text()
        id_usado = next(mm.id for mm in ctrl.project.media.values()
                        if os.path.normcase(mm.path) == os.path.normcase(usado["ruta"]))
        assert id_usado in ctrl.missing, "sus clips salen como «no encontrado»"
        lib._rebuild()
        pump(app, 0.2)
        top = lib.tree.topLevelItem(lib.tree.topLevelItemCount() - 1)
        assert top.data(0, Qt.UserRole + 1) == MEMES_SECTION
        assert any(top.child(k).data(0, ROLE_MEDIA) == id_usado for k in range(top.childCount())), \
            "sigue en Medios («😂 Memes») para volver a enlazarlo o quitarlo"
        print("✓ quitar un meme usado: se suelta, va a la Papelera, sus clips salen «no encontrado» y sigue en Medios")
        shutil.rmtree(PAPELERA)
        os.makedirs(PAPELERA)
        pan.rejilla.clearSelection()
        k_cara = next(k for k in range(pan.rejilla.count()) if pan.rejilla.item(k).text() == "Cara feliz")
        pan.rejilla.item(k_cara).setSelected(True)
        assert pan.quitar(preguntar=False) == 1 and not any(x["nombre"] == "Cara feliz" for x in MEMES.listar())
        assert len(os.listdir(PAPELERA)) == 1
        pump(app, 0.4)
        assert pan.rejilla.count() == len(MEMES.listar())
        print("✓ panel Memes: rejilla con miniaturas, buscar, filtrar, poner en el cabezal (Ctrl+Z) y quitar (Papelera)")

        # otro proyecto: siguen ahí
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        ctrl.new_project()
        pump(app, 0.4)
        lib._rebuild()
        top = lib.tree.topLevelItem(lib.tree.topLevelItemCount() - 1)
        assert top is not None and top.data(0, Qt.UserRole + 1) == MEMES_SECTION and top.childCount() == len(MEMES.listar())
        print("✓ proyecto nuevo: los memes siguen en Medios y en su panel")
    finally:
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.3)
    print("TODO OK")


if __name__ == "__main__":
    main()
