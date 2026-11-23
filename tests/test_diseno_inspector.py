"""
🎨 PRUEBA del diseño nuevo en el Inspector (tanda 2, 20/11): secciones Video, Audio, Texto y Color.
  1) los números son ValorDeslizable (deslizador fino + número que se escribe o se arrastra) y se usan igual que los
     QSpinBox de antes (enteros, centésimas del color, «—» en el mínimo, foco en el número);
  2) filas etiqueta/control (FilaInspector), iconos monocromos (sin emojis de color en botones ni títulos) y cada
     botón de solo icono con su tooltip;
  3) cambiar un número cambia el clip (opacidad, recorte, color, volumen, velocidad, zoom, texto) igual que antes;
  4) ningún texto cortado a 200, 360 y 520 px (la misma revisión que test_paneles_sin_cortes).
Ejecutar:  .venv/Scripts/python.exe tests/test_diseno_inspector.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
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


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401

from PySide6.QtWidgets import (QAbstractButton, QApplication, QDoubleSpinBox, QGroupBox, QLabel,  # noqa: E402
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

# emojis de color que ya no deben verse en botones ni títulos (los símbolos monocromos ⊕ ↔ ↕ ◀ sí valen)
EMOJIS = ("🎨", "✨", "👁", "📈", "❄", "🎧", "⭐", "🔗", "🛠", "↺", "⯇", "⯈", "◆")


def pump(app, s=0.1):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def prueba_valor(D):
    v = D.ValorDeslizable(10, 400, 5, 0, "%", entero=True)
    got = []
    v.valueChanged.connect(got.append)
    v.setValue(50)
    assert v.value() == 50 and isinstance(v.value(), int) and got == [50] and isinstance(got[0], int)
    assert v.campo.text() == "50 %"
    c = D.ValorDeslizable(-200, 200, 2, 2, "", entero=True, factor=100)
    c.setValue(40)
    assert c.value() == 40 and c.campo.text() == "0,40", c.campo.text()
    c.campo.escrito.emit("-0,5")
    assert c.value() == -50, c.value()
    e = D.ValorDeslizable(0.0, 5.0, 0.05, 2, "s")
    e.setSpecialValueText("—")
    assert e.campo.text() == "—" and e.maximum() == 5.0
    e.setValue(0.5)
    assert e.campo.text() == "0,50 s"
    s = D.ValorDeslizable(0, 1, 0.1, 2)
    s.setSuffix(" dB")
    s.setDecimals(1)
    s.setValue(0.25)
    assert s.campo.text().endswith("dB") and s.focusProxy() is s.campo
    print("✓ 1) ValorDeslizable se usa como un QSpinBox (enteros), con centésimas («0,40»), «—» en el mínimo, "
          "setSuffix/setDecimals y el foco en el número")


def main():
    import faulthandler
    faulthandler.dump_traceback_later(420, exit=True)   # (si algo se quedara esperando, no ocupa el turno)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("_pruebas_tmp", "test_diseno_inspector")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import diseno as D
    from editoria.ui import theme as T
    T.apply_dark_theme(app)
    prueba_valor(D)
    import test_paneles_sin_cortes as SC
    SC.contar_pintados()
    from editoria.core.controller import ProjectController
    from editoria.core.model import KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, new_id
    from editoria.ui import responsive as R
    from editoria.ui.inspector import InspectorPanel
    ctrl = ProjectController()
    p = ctrl.project
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    mv = MediaItem(new_id(), "/falso/v.mp4", KIND_VIDEO, "un video con un nombre bastante largo.mp4", duration=60.0,
                   width=1280, height=720, has_audio=True, probed=True)
    p.media[mv.id] = mv
    cv = Clip(new_id(), mv.id, v1.id, 0.0, 0.0, 10.0)
    p.clips[cv.id] = cv
    ctrl.project_changed.emit()
    ct = ctrl.add_text(40.0, 3.0, "Un texto")
    ct = ct if isinstance(ct, str) else next(c.id for c in p.clips.values() if c.text is not None)
    ins = InspectorPanel(ctrl)
    caja = QWidget()
    lay = QVBoxLayout(caja)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(ins)
    R.adaptar(caja)
    for s_ in ins.secciones.values():
        s_.set_open(True, save=False)

    # ---- 2) controles del diseño y sin emojis de color
    claves = {"video": ("transformar", "recorte", "encuadre", "composicion", "mejorar", "color"),
              "audio": ("volumen", "velocidad"), "texto": ()}
    for pestana, ids in (("video", [cv.id]), ("audio", [cv.id]), ("texto", [ct])):
        ins.set_selection(ids)
        ins.ir_a(pestana)
        caja.setFixedWidth(360)
        caja.setFixedHeight(4200)
        caja.show()
        pump(app, 0.3)
        pagina = ins._pag[pestana]
        viejos = [w for w in pagina.findChildren(QSlider) + pagina.findChildren(QSpinBox) +
                  pagina.findChildren(QDoubleSpinBox) if w.isVisibleTo(caja)
                  and not any(isinstance(a, D.ValorDeslizable) for a in _antepasados(w))
                  and "ecualizador" not in _seccion_de(w, ins)
                  and not type(w).__module__.endswith("color_wheels")]    # (las ruedas de color: su propio dibujo)
        assert not viejos, f"{pestana}: quedan números viejos {[type(w).__name__ for w in viejos]}"
        textos = [w.text() for w in pagina.findChildren(QLabel) + pagina.findChildren(QAbstractButton)
                  if w.isVisibleTo(caja)] + [g.title() for g in pagina.findChildren(QGroupBox) if g.isVisibleTo(caja)]
        malos = [t for t in textos if any(e in t for e in EMOJIS)]
        assert not malos, f"{pestana}: emojis de color o símbolos viejos {malos}"
        for b in pagina.findChildren(D.BotonIcono):
            if b.isVisibleTo(caja):
                assert b.toolTip().strip(), f"{pestana}: botón de icono «{b.nombre_icono()}» sin tooltip"
        n_filas = sum(1 for f in pagina.findChildren(D.FilaInspector) if f.isVisibleTo(caja))
        assert n_filas >= {"video": 6, "audio": 3, "texto": 6}[pestana], (pestana, n_filas)
        for k in claves[pestana]:
            assert k in ins.secciones and not ins.secciones[k].isHidden(), (pestana, k)
        print(f"✓ 2) {pestana.capitalize()}: {n_filas} filas etiqueta/control, números deslizables, iconos "
              "monocromos con tooltip y sin emojis de color")

    # ---- 3) los números cambian el clip igual que antes
    ins.set_selection([cv.id])
    ins.ir_a("video")
    pump(app, 0.2)
    ins.opacity.setValue(70)
    assert abs(p.clips[cv.id].opacity - 0.7) < 1e-6, p.clips[cv.id].opacity
    ins.crop_spins["l"].setValue(20)
    pump(app)
    assert abs(ins.crop_spins["l"].value() - 20) < 0.01
    ins.color_sliders["exposure"].setValue(40)
    assert abs((p.clips[cv.id].color or {}).get("exposure", 0) - 0.4) < 1e-6, p.clips[cv.id].color
    assert ins.color_sliders["exposure"].campo.text() == "+0,40", ins.color_sliders["exposure"].campo.text()
    ins.zoom.setValue(150)
    pump(app)
    ins.ir_a("audio")
    pump(app, 0.2)
    ins.volume.setValue(50)
    pump(app)
    assert abs(p.clips[cv.id].volume - 0.5) < 1e-6, p.clips[cv.id].volume
    ins.focus_speed()
    pump(app, 0.2)
    assert ins.speed.hasFocus() or not ins.speed.isVisible(), "R: el foco en el número de la velocidad"
    ins.speed.setValue(50)
    pump(app, 0.2)
    assert abs(p.clips[cv.id].speed - 0.5) < 1e-6, p.clips[cv.id].speed
    ins.set_selection([ct])
    ins.ir_a("texto")
    pump(app, 0.2)
    ins.text_size.setValue(12.0)
    pump(app, 0.2)
    assert abs(float(p.clips[ct].text.get("size", 0)) - 12.0) < 1e-6, p.clips[ct].text.get("size")
    print("✓ 3) opacidad, recorte, color (centésimas), zoom, volumen, velocidad (R = foco en su número) y tamaño "
          "del texto cambian el clip igual que antes")

    # ---- 3b) arrastrar = UN solo Ctrl+Z (12 movimientos), y la velocidad se aplica al soltar
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    st = ctrl.undo_stack

    def arrastre_deslizador(vd, n=12):
        vd.deslizador.empieza.emit()
        for i in range(1, n + 1):
            vd.deslizador.movido.emit(0.2 + 0.6 * i / n)
        vd.deslizador.termina.emit()
        pump(app, 0.05)

    def arrastre_numero(vd, n=12):
        vd.campo.empieza.emit()
        for _ in range(n):
            vd.campo.arrastrado.emit(1.0)
        vd.campo.termina.emit()
        pump(app, 0.05)

    ins.set_selection([cv.id])
    ins.ir_a("audio")
    pump(app, 0.2)
    ctrl.set_clip_props([cv.id], "Estabilizar (prueba)", fx={"stab": {"amount": 0.5}})
    ins.set_selection([])
    ins.set_selection([cv.id])
    pump(app, 0.2)
    casos = [("Volumen", ins.volume, arrastre_deslizador), ("Volumen (número)", ins.volume, arrastre_numero),
             ("Reducir ruido", ins.denoise, arrastre_deslizador), ("Estabilizar", ins.stab_amount, arrastre_deslizador)]
    casos += [(f"Efecto {k}", sp, arrastre_deslizador) for k, sp in ins.fx_spins.items()]
    for nombre, vd, arrastrar in casos:
        antes = st.index()
        valor0 = vd.value()
        arrastrar(vd)
        assert vd.value() != valor0, (nombre, "el arrastre no cambió nada")
        assert st.index() == antes + 1, f"{nombre}: {st.index() - antes} pasos de deshacer por un arrastre (debe ser 1)"
        st.undo()
        pump(app, 0.05)
        st.redo()
    llamadas = []
    real = ctrl.set_speed
    ctrl.set_speed = lambda *a, **k: (llamadas.append(k.get("speed")), real(*a, **k))[1]
    antes = st.index()
    arrastre_deslizador(ins.speed)
    del ctrl.set_speed
    assert len(llamadas) == 1 and st.index() == antes + 1, (llamadas, st.index() - antes)
    assert abs(p.clips[cv.id].speed - ins.speed.value() / 100) < 1e-6, (p.clips[cv.id].speed, ins.speed.value())
    # con el ratón de verdad (pulsar, mover 12 veces, soltar): también un solo paso
    antes = st.index()
    sl = ins.volume.deslizador
    ins.volume.show()
    QTest.mousePress(sl, Qt.LeftButton, Qt.NoModifier, QPoint(10, sl.height() // 2))
    for i in range(12):
        QTest.mouseMove(sl, QPoint(12 + 6 * i, sl.height() // 2))
    QTest.mouseRelease(sl, Qt.LeftButton, Qt.NoModifier, QPoint(84, sl.height() // 2))
    pump(app, 0.05)
    assert st.index() <= antes + 1 and not ins.volume.arrastrando(), (st.index() - antes)
    print(f"✓ 3b) arrastrar 12 veces = 1 Ctrl+Z en Volumen (deslizador y número), Reducir ruido, Estabilizar y los "
          f"{len(ins.fx_spins)} efectos; la Velocidad se aplica una sola vez, al soltar (su ripple, una vez)")
    # retoques: Balance «C / I30 / D30», color con signo, «Toda la pantalla», rueda con foco
    ins.pan.setValue(-30)
    assert ins.pan.campo.text() == "I30", ins.pan.campo.text()
    ins.pan.setValue(0)
    assert ins.pan.campo.text() == "C"
    ins.pan.campo.escrito.emit("D25")
    assert ins.pan.value() == 25, ins.pan.value()
    ins.color_sliders["exposure"].setValue(40)
    assert ins.color_sliders["exposure"].campo.text() == "+0,40", ins.color_sliders["exposure"].campo.text()
    zs = ins.tw["zone_size"][0]
    zs.setValue(100)
    assert zs.campo.text() == "Toda la pantalla" and zs.campo.width() >= zs.campo.minimumSizeHint().width() - 1
    print("✓ Balance «C / I30 / D30», color con signo «+0,40» y «Toda la pantalla» en el fondo borroso")

    # ---- 4) nada cortado (y el panel se deja poner a 200 px)
    for pestana, ids in (("video", [cv.id]), ("audio", [cv.id]), ("texto", [ct])):
        ins.set_selection(ids)
        ins.ir_a(pestana)
        pump(app, 0.2)
        assert caja.minimumSizeHint().width() <= 200, f"{pestana}: el Inspector pide {caja.minimumSizeHint().width()} px"
        for ancho in (200, 360, 520):
            caja.setFixedWidth(ancho)
            caja.setFixedHeight(4200)
            pump(app, 0.25)
            cortes, vistos = {}, set()
            SC.revisar(caja, cortes, vistos, f"Inspector {pestana} {ancho} px")
            assert not cortes, "\n".join(cortes.values())
            for v in ins._pag[pestana].findChildren(D.ValorDeslizable):
                if v.isVisibleTo(caja):
                    assert v.campo.width() >= v.campo.minimumSizeHint().width() - 1, \
                        (pestana, ancho, v.campo.text(), v.campo.width())
            caja.grab().save(os.path.join(out, f"inspector_{pestana}_{ancho}.png"))
    print("✓ 4) Video, Audio y Texto sin cortes a 200, 360 y 520 px (los números siempre enteros)")
    ctrl.undo_stack.setClean()
    print("TODO OK")


def _antepasados(w):
    p = w.parentWidget()
    while p is not None:
        yield p
        p = p.parentWidget()


def _seccion_de(w, ins) -> str:
    for k, s_ in ins.secciones.items():
        if s_.isAncestorOf(w):
            return k
    return ""


if __name__ == "__main__":
    main()
