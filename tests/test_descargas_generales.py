"""
🌐 Panel «Descargas» (búsqueda libre en internet, sin palabra clave) — SIN RED (descarga simulada):
  · lo bajado va a la carpeta general (recordada) y entra en Medios en «🌐 Descargas»; el contador «Descargas en cola (n)»;
  · «Descargado»: la lista de la carpeta con miniatura; poner en el cabezal (Ctrl+Z);
  · «Mover a…»: Medios · Carpetas de palabra clave ▸ [palabra] · Otra carpeta…; mover a una palabra mueve el archivo y
    sus clips siguen viéndose; «Agregar a memes»;
  · (Fable) la categoría que pusiste se respeta (releer no la pisa; «A Medios» solo la pone a los nuevos); mover un
    archivo abierto no congela y explica por qué no se movió; «Carpeta: …» entera (varias líneas); sin textos de
    palabra clave; al pasar el ratón, los fotogramas en la misma casilla (sin ventanas flotantes).
Ejecutar:  .venv/Scripts/python.exe tests/test_descargas_generales.py <carpeta_salida>
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
_TMP = tempfile.mkdtemp(prefix="reclaimer_descargas_", dir=_TMPROOT)
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402


def pump(app, s):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.01)


def esperar(app, cond, s=20.0):
    t0 = time.time()
    while time.time() - t0 < s:
        if cond():
            return True
        pump(app, 0.05)
    return cond()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_TMPROOT, "test_descargas_generales")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.core import keyword_folders as KF
    from editoria.core import media as M
    from editoria.core import memes as MEMES
    from editoria.ui import clips_panel as CP
    from editoria.ui import descargas_generales as DG
    ff = M.ffmpeg()
    video = os.path.join(out, "fuente.mp4")
    if not os.path.exists(video):
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", video], check=True)
    st = QSettings("EditorIA", "EditorIA")
    general = os.path.join(_TMP, "Descargas generales")
    st.setValue(DG.CLAVE, general)
    raiz_kw = os.path.join(_TMP, "Clips por palabra")
    KF.create_folder(raiz_kw, "Gato")
    st.setValue(CP.RAIZ_CLAVE, raiz_kw)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1920, 1040)
    win.show()
    pump(app, 0.8)
    ctrl = win.ctrl
    pan = win.descargas_web
    try:
        assert pan.raiz == general
        assert pan.btn_carpeta.text().startswith("Carpeta: ") and general in pan.btn_carpeta.toolTip()
        assert pan.btn_descargas_barra.toolTip(), "«Descargas» con su ayuda desde el principio"
        assert pan.btn_cabezal_d.toolTip(), "«Poner en el cabezal» con su ayuda"
        if DG.HAY_INTERNET:
            for nombre in ("btn_poner", "btn_poner_desc", "lbl_mods"):
                assert getattr(pan, nombre).isHidden(), nombre
            tips = [w.toolTip() for w in pan.findChildren(__import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget)
                    if not w.isHidden()]
            assert not [t for t in tips if "de la palabra" in t or "esta palabra" in t], \
                [t for t in tips if "palabra" in t][:3]
        # «Carpeta: …» con el nombre ENTERO: si no cabe, en varias líneas (ningún texto cortado)
        largo = os.path.join(_TMP, "una carpeta con un nombre larguísimo para ver que se recorta bien " * 2)
        pan.raiz = largo
        pan._pintar_carpeta()
        pan.pestanas.setCurrentIndex(pan.pestanas.count() - 1)   # (22/11: la carpeta va en su pestaña «Carpeta»)
        pump(app, 0.1)
        pan.btn_carpeta.resize(150, pan.btn_carpeta.height())
        pump(app, 0.1)
        fm = pan.btn_carpeta.fontMetrics()
        lineas = pan.btn_carpeta.text().split("\n")
        assert "…" not in pan.btn_carpeta.text() and len(lineas) > 1, pan.btn_carpeta.text()
        assert all(fm.horizontalAdvance(x) <= pan.btn_carpeta.width() for x in lineas), lineas
        assert "".join(lineas).replace(" ", "") == pan.btn_carpeta.texto_completo().replace(" ", ""), \
            "el nombre ENTERO, en varias líneas (ningún texto cortado)"
        assert pan.btn_carpeta.texto_completo().endswith("bien ") or "larguísimo" in pan.btn_carpeta.texto_completo()
        pan.raiz = general
        pan._pintar_carpeta()
        print("✓ textos: ayudas en todos los botones, nada de «palabra clave»; «Carpeta: …» entera, en varias líneas")
        if DG.HAY_INTERNET:
            n = [0]

            def bajar(u, t, k, p_, c, a=True, nav=None):
                n[0] += 1
                time.sleep(0.6)                                   # (se ve «Descargas (1)» mientras baja)
                destino = os.path.join(k, f"bajado {n[0]}.mp4")
                shutil.copyfile(video, destino)
                with open(os.path.splitext(destino)[0] + ".creditos.json", "w", encoding="utf-8") as f:
                    f.write('{"title": "x", "url": "https://x", "term": ""}')
                return destino
            pan._bajar_trabajo = bajar
            pan.termino = "lo que sea"
            d = pan._bajar_resultado({"title": "Un video", "url": "https://x"})
            assert d is not None
            pump(app, 0.2)
            assert pan.btn_descargas_barra.text() in ("Descargas en cola (1)", "En cola (1)"), \
                pan.btn_descargas_barra.text()
            assert esperar(app, lambda: d.estado == "listo", 20), d.estado
            ruta = d.ruta
            assert os.path.dirname(ruta) == general and os.path.isfile(ruta), ruta
            assert d.media_id and ctrl.project.media[d.media_id].category == DG.CATEGORIA
            assert pan.btn_descargas_barra.text() in ("Descargas en cola", "En cola")
            print("✓ lo bajado (sin palabra clave) va a la carpeta general y a Medios «🌐 Descargas»; contador de la "
                  "cola")
        else:
            os.makedirs(general, exist_ok=True)
            ruta = os.path.join(general, "bajado 1.mp4")
            shutil.copyfile(video, ruta)
            print("· este equipo no tiene la parte de internet: solo lo ya descargado")
        pan.refrescar()
        pump(app, 0.2)
        assert pan.lista.count() == 1 and pan.lista.item(0).data(0x0100) == ruta
        assert esperar(app, lambda: not pan.lista.item(0).icon().isNull(), 15), "miniatura"
        pan.lista.setCurrentRow(0)
        n0 = len(ctrl.project.clips)
        pan.poner_en_cabezal(pan.elegidos())
        assert len(ctrl.project.clips) > n0
        ctrl.undo_stack.undo()
        print("✓ «Descargado»: la carpeta con miniatura; poner en el cabezal (Ctrl+Z)")

        # 🖼 al pasar el ratón por un video: sus fotogramas en la MISMA casilla (ninguna ventana flotante). (Los
        #   movimientos van directos a la lista: con la ventana entera offscreen, QTest se los da a otra ventana)
        from PySide6.QtCore import QEvent as _QE
        from PySide6.QtCore import QPointF as _QPF
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QMouseEvent
        win.docks["descargas_web"].show()
        win.docks["descargas_web"].raise_()
        pan.pestanas.setCurrentIndex(pan.pestanas.count() - 1)
        pump(app, 0.4)
        vp = pan.lista.viewport()

        def mover(x, y):
            app.sendEvent(vp, QMouseEvent(_QE.MouseMove, _QPF(x, y), vp.mapToGlobal(_QPF(x, y)), _Qt.NoButton,
                                          _Qt.NoButton, _Qt.NoModifier))
        ventanas = {id(w) for w in app.topLevelWidgets() if w.isVisible()}
        it0 = pan.lista.item(0)
        k0 = it0.icon().cacheKey()
        r0 = pan.lista.visualItemRect(it0)
        mover(r0.center().x(), r0.center().y())
        assert esperar(app, lambda: pan.lista._scrub.tira is not None, 20), "la tira del video llega"
        mover(r0.center().x() + 1, r0.center().y())
        assert it0.icon().cacheKey() != k0, "la casilla enseña un fotograma"
        assert {id(w) for w in app.topLevelWidgets() if w.isVisible()} <= ventanas, "sin ventanas flotantes"
        app.sendEvent(vp, _QE(_QE.Leave))
        assert it0.icon().cacheKey() == k0, "al salir, la miniatura de siempre"
        print("✓ al pasar el ratón: los fotogramas del video en su misma casilla, sin ventanas flotantes")
        if DG.HAY_INTERNET:
            assert pan.lista_descargas.viewMode() == pan.lista_descargas.ViewMode.IconMode
            assert d.lbl.wordWrap() and "Un video" in d.lbl.text() and not d.mini.pixmap().isNull()
            assert pan.creditos_txt.isHidden() and not pan.btn_ver_creditos.isChecked(), "créditos plegados"
            pan.btn_ver_creditos.click()
            assert not pan.creditos_txt.isHidden()
            pan.btn_ver_creditos.click()
            print("✓ Descargas en rejilla de miniaturas (título entero, en varias líneas); créditos plegados")

        # compacto: en cada modo, los resultados se llevan casi todo el alto; ningún botón estirado
        if DG.HAY_INTERNET:
            from PySide6.QtWidgets import QPushButton
            suelto = DG.DescargasGenerales(ctrl)
            suelto.resize(440, 900)
            suelto.show()
            pump(app, 0.4)
            alto_normal = QPushButton("Buscar").sizeHint().height()
            for modo in ("video", "png", "imagen"):
                suelto.pestanas.setCurrentIndex(0)
                suelto.poner_modo_busqueda(modo)
                pump(app, 0.3)
                zona = suelto.pestanas_net if modo == "video" else suelto._nav_vacio
                parte = zona.height() / suelto.height()
                assert parte >= 0.75, (modo, round(parte, 2), zona.height(), suelto.height())
                altos = [(b.text(), b.height()) for b in suelto.findChildren(QPushButton) if b.isVisible()]
                gordos = [x for x in altos if x[1] > 2 * alto_normal]
                assert not gordos, (modo, gordos, alto_normal)
                print(f"  · {modo}: resultados {parte:.0%} del alto; botones ≤ {max(h for _t, h in altos)} px")
            suelto.close()
            suelto.deleteLater()
            print("✓ una sola fila de búsqueda arriba y el resto del alto para los resultados, en los tres modos")

        # «Mover a…»
        esperar(app, lambda: not ctrl.analyzing, 60)          # (lo que se analiza al importarlo tiene el archivo abierto)
        menu = QMenu()
        sub = DG.menu_mover(menu, ctrl, lambda: [ruta], pan)
        textos = [a.text() for a in sub.actions()]
        assert textos[0].startswith("Medios") and "Carpetas de palabra clave" in textos and "Otra carpeta…" in textos
        kw = next(a.menu() for a in sub.actions() if a.menu() is not None)
        assert any(a.text().startswith("Gato") for a in kw.actions()), [a.text() for a in kw.actions()]
        mid = next(m.id for m in ctrl.project.media.values() if os.path.normcase(m.path) == os.path.normcase(ruta))
        next(a for a in kw.actions() if a.text().startswith("Gato")).trigger()
        nueva = os.path.join(raiz_kw, "Gato", os.path.basename(ruta))
        assert esperar(app, lambda: not DG.moviendo(), 20)
        if not os.path.isfile(nueva):
            try:
                os.rename(ruta, ruta + ".x")
                os.rename(ruta + ".x", ruta)
                motivo = "se puede renombrar"
            except OSError as exc:
                motivo = str(exc)
            raise AssertionError(f"no se movió a la carpeta de la palabra: {motivo}")
        assert not os.path.exists(ruta)
        assert os.path.isfile(os.path.splitext(nueva)[0] + ".creditos.json") or not DG.HAY_INTERNET
        assert os.path.normcase(ctrl.project.media[mid].path) == os.path.normcase(nueva), "en Medios, la ruta nueva"
        print("✓ «Mover a…» → Carpetas de palabra clave ▸ «Gato»: el archivo (y sus créditos) se mueven y Medios sigue "
              "encontrándolo")

        # categoría respetada: releer la carpeta no la pisa; «A Medios» solo pone «🌐 Descargas» a los nuevos
        os.makedirs(general, exist_ok=True)
        mia = os.path.join(general, "mia.mp4")
        shutil.copyfile(video, mia)
        (id_mia,) = ctrl.import_now([mia])
        ctrl.set_media_props([id_mia], category="Mi categoría")
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        pan.refrescar()
        pump(app, 0.3)
        assert ctrl.project.media[id_mia].category == "Mi categoría", "releer no pisa tu categoría"
        assert ctrl.undo_stack.isClean() and not ctrl._media_dirty, "releer no ensucia el proyecto"
        nueva2 = os.path.join(general, "nueva.mp4")
        shutil.copyfile(video, nueva2)
        ids = DG.a_medios(ctrl, [mia, nueva2])
        id_nueva = next(i for i in ids if i != id_mia)
        assert ctrl.project.media[id_mia].category == "Mi categoría"
        assert ctrl.project.media[id_nueva].category == DG.CATEGORIA, ctrl.project.media[id_nueva].category
        print("✓ categoría respetada: releer no la pisa ni ensucia el proyecto; «A Medios» solo marca los nuevos")

        # mover un archivo ABIERTO en otro programa: no congela y explica por qué
        esperar(app, lambda: not ctrl.analyzing, 60)
        abierto = open(nueva2, "rb")                    # (Windows no deja moverlo mientras esté abierto)
        res = {}
        try:
            t0 = time.monotonic()
            job = DG.mover(ctrl, [nueva2], os.path.join(_TMP, "otra"), lambda n, f: res.update(n=n, f=f), pan)
            assert job is not None and time.monotonic() - t0 < 0.5, "vuelve enseguida (trabaja en segundo plano)"
            huecos, ult = [], time.monotonic()
            while "f" not in res and time.monotonic() - t0 < 15:
                app.processEvents()
                ahora = time.monotonic()
                huecos.append(ahora - ult)
                ult = ahora
                time.sleep(0.01)
        finally:
            abierto.close()
        assert res.get("n") == [] and res.get("f"), res
        assert "abierto en otro programa" in res["f"][0][1], res["f"]
        assert max(huecos) < 0.5, f"la ventana no se congela ({max(huecos):.2f} s)"
        assert os.path.isfile(nueva2)
        menu2 = QMenu()
        sub2 = DG.menu_mover(menu2, ctrl, lambda: [nueva2], pan)
        sub2.actions()[0].trigger()                     # (Medios: ya cerrado, ahora sí)
        assert esperar(app, lambda: not DG.moviendo(), 20)
        print(f"✓ mover un archivo abierto: no congela (hueco máx. {max(huecos):.2f} s) y dice «{res['f'][0][1]}»")

        # usos al quitar
        assert DG.usos(ctrl, [ctrl.project.media[mid].path]) == 0
        ctrl.add_media([mid], None, 30.0)
        assert DG.usos(ctrl, [ctrl.project.media[mid].path]) == 1, "se avisa: se usa en este proyecto"
        ctrl.undo_stack.undo()

        # «Agregar a memes»
        from editoria.ui import memes_panel as MP
        job = MP.agregar_medios(pan, ctrl, [mid], preguntar=False, nombre="Bajado y gracioso", etiquetas="web")
        assert job is not None and esperar(app, lambda: any(m["nombre"] == "Bajado y gracioso"
                                                             for m in MEMES.listar()), 20)
        print("✓ «Agregar a memes» desde lo descargado")
    finally:
        ctrl.undo_stack.setClean()
        ctrl._media_dirty = False
        win.close()
        pump(app, 0.3)
        st.remove(DG.CLAVE)
        st.remove(CP.RAIZ_CLAVE)
    print("TODO OK")


if __name__ == "__main__":
    main()
