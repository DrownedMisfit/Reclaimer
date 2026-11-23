"""
Fase 2 «Inspector contextual» (notas_claude/PROPUESTA_INTERFAZ.md c y e):
  · pestañas FIJAS Video · Audio · Efectos · Transición · Texto · Archivo · Proyecto: las que no aplican, apagadas
    (visibles); al elegir algo se pone delante la que toca (nada → Proyecto);
  · secciones plegables en el orden de la tabla, las 3 primeras abiertas, y se recuerda lo que abres;
  · ● apaga / enciende un ajuste del clip SIN perder sus valores; ↺ lo deja de fábrica (con ratón real);
  · video, audio, texto, transición, varios clips y nada: < 50 ms en elegir.
Ejecutar:  .venv/Scripts/python.exe tests/test_inspector_contextual.py <carpeta_salida>
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_inspector_", dir=_TMPROOT)
__import__("atexit").register(__import__("shutil").rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import (KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Clip,  # noqa: E402
                                 MediaItem, new_id)


def pump(app, s=0.05):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.005)


def clic(w):
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.rect().center())


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from editoria.ui import inspector_secciones as SEC
    from editoria.ui.inspector import InspectorPanel
    st = QSettings("EditorIA", "EditorIA")
    for k in st.allKeys():
        if k.startswith(SEC.CLAVE_AJUSTES):
            st.remove(k)
    ctrl = ProjectController()
    p = ctrl.project
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO)
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    mv = MediaItem(new_id(), "/falso/v.mp4", KIND_VIDEO, "un video.mp4", duration=60.0, width=1280, height=720,
                   has_audio=True, probed=True)
    mi = MediaItem(new_id(), "/falso/i.png", KIND_IMAGE, "una imagen.png", width=800, height=600, probed=True)
    ma = MediaItem(new_id(), "/falso/a.wav", KIND_AUDIO, "narración.wav", duration=60.0, probed=True)
    for m in (mv, mi, ma):
        p.media[m.id] = m
    cv = Clip(new_id(), mv.id, v1.id, 0.0, 0.0, 10.0)
    cv2 = Clip(new_id(), mv.id, v1.id, 10.0, 10.0, 10.0, fx={"trans": {"type": "fade", "dur": 0.5}})
    ci = Clip(new_id(), mi.id, v1.id, 30.0, 0.0, 5.0)
    ca = Clip(new_id(), ma.id, a1.id, 0.0, 0.0, 10.0)
    for c in (cv, cv2, ci, ca):
        p.clips[c.id] = c
    ctrl.project_changed.emit()
    ct = ctrl.add_text(40.0, 3.0, "Un texto")
    ct = ct if isinstance(ct, str) else next(c.id for c in p.clips.values() if c.text is not None)
    ins = InspectorPanel(ctrl)
    ins.resize(460, 1400)
    ins.show()
    pump(app, 0.3)
    tabs = ins.clip_tabs
    nombres = [tabs.tabText(i) for i in range(tabs.count())]
    assert nombres == ["Video", "Audio", "Efectos", "Transición", "Texto", "Archivo", "Proyecto"], nombres

    def activas():
        return {SEC.PESTANAS[i][0] for i in range(tabs.count()) if tabs.isTabEnabled(i)}

    def vis(clave):
        return not ins.secciones[clave].isHidden()

    casos = {
        "nada": ([], "proyecto", {"proyecto"}),
        "video": ([cv.id], "video", {"video", "audio", "efectos", "archivo", "proyecto"}),
        "imagen": ([ci.id], "video", {"video", "efectos", "archivo", "proyecto"}),
        "audio": ([ca.id], "audio", {"audio", "efectos", "archivo", "proyecto"}),
        "texto": ([ct], "texto", {"texto", "archivo", "proyecto"}),
        "varios": ([cv.id, ca.id, ci.id], None, {"video", "audio", "efectos", "archivo", "proyecto"}),
    }
    for nombre, (ids, pestana, act) in casos.items():
        ins.set_selection(ids)
        pump(app)
        assert tabs.count() == 7 and all(tabs.isTabVisible(i) for i in range(7)), "las pestañas nunca desaparecen"
        assert activas() == act, (nombre, activas())
        if pestana:
            assert ins.pestana_activa() == pestana, (nombre, ins.pestana_activa())
    ins.set_transition(cv2.id)
    pump(app)
    assert ins.pestana_activa() == "transicion" and activas() == {"transicion", "proyecto"}, activas()
    print("✓ pestañas fijas: las 7 siempre visibles; cada selección enciende las suyas y pone delante la que toca "
          "(nada → Proyecto, video → Video, audio → Audio, texto → Texto, transición → Transición)")

    # secciones en orden y las 3 primeras abiertas
    ins.set_selection([cv.id])
    pump(app)
    orden = [k for k in ("transformar", "recorte", "encuadre", "composicion", "velocidad", "mejorar", "seguimiento",
                         "color") if vis(k) and ins._pag["video"].isAncestorOf(ins.secciones[k])]
    pg = ins._pag["video"]
    ys = [ins.secciones[k].mapTo(pg, ins.secciones[k].rect().topLeft()).y() for k in orden]
    assert ys == sorted(ys), (orden, ys)
    assert [ins.secciones[k].is_open() for k in ("transformar", "recorte", "encuadre")] == [True] * 3
    assert not ins.secciones["composicion"].is_open() and not ins.secciones["color"].is_open()
    ins.set_selection([ca.id])
    pump(app)
    assert ins.secciones["velocidad"].isVisibleTo(ins) and ins._pag["audio"].isAncestorOf(ins.speed_sec), \
        "con sonido, la velocidad va en Audio (debajo del ecualizador)"
    ins.set_selection([ct])
    pump(app)
    assert [ins.secciones[k].is_open() for k in ("texto_contenido", "texto_fuente", "texto_posicion")] == [True] * 3
    for k in ("texto_trazo", "texto_sombra", "texto_fondo", "texto_desenfocar", "texto_borroso", "texto_animacion",
              "texto_plantilla", "texto_pegar"):
        assert vis(k), k
    ins.set_selection([])
    pump(app)
    for k in ("formato", "sonoridad", "mezcla", "narracion", "subtitulos"):
        assert vis(k), k
    print("✓ secciones en el orden de la tabla, las 3 primeras abiertas; Texto con todo lo del panel de texto; "
          "Proyecto con formato, sonoridad, mezcla y música, narración y subtítulos")

    # recordar lo abierto (clic real en la cabecera)
    ins.set_selection([cv.id])
    pump(app)
    sc = ins.secciones["composicion"]
    clic(sc.head)
    pump(app)
    assert sc.is_open() and str(st.value(f"{SEC.CLAVE_AJUSTES}/composicion")).lower() == "true"
    ins2 = InspectorPanel(ctrl)
    assert ins2.secciones["composicion"].is_open(), "se recuerda lo que abriste"
    ins2.deleteLater()
    print("✓ lo que abres se recuerda")

    # ● y ↺ con ratón real: Composición
    ctrl.set_clip_props([cv.id], "opacidad", opacity=0.5, blend="screen")
    ins.set_selection([cv.id])
    pump(app)
    clic(sc.boton)                                   # apagar
    pump(app)
    c = p.clips[cv.id]
    assert c.opacity == 1.0 and c.blend == "normal" and SEC.apagada(c, "composicion"), (c.opacity, c.blend, c.fx)
    assert not sc.boton.isChecked() and not sc.body.isEnabled(), "apagada: gris"
    clic(sc.boton)                                   # encender: vuelve lo de antes
    pump(app)
    c = p.clips[cv.id]
    assert c.opacity == 0.5 and c.blend == "screen" and not SEC.apagada(c, "composicion"), (c.opacity, c.fx)
    clic(sc.btn_reset)
    pump(app)
    c = p.clips[cv.id]
    assert c.opacity == 1.0 and c.blend == "normal"
    ctrl.undo_stack.undo()
    assert p.clips[cv.id].opacity == 0.5, "↺ = un Ctrl+Z"
    print("✓ ● Composición: apagar la deja normal sin perder nada, encender la devuelve; ↺ de fábrica (un Ctrl+Z)")

    # ● Volumen (silenciar) y recorte con números
    ins.set_selection([ca.id])
    pump(app)
    ctrl.set_clip_props([ca.id], "vol", volume=0.7)
    pump(app)
    clic(ins.secciones["volumen"].boton)
    pump(app)
    assert p.clips[ca.id].volume == 0.0
    clic(ins.secciones["volumen"].boton)
    pump(app)
    assert abs(p.clips[ca.id].volume - 0.7) < 1e-9
    ins.set_selection([cv.id])
    pump(app)
    ins.crop_spins["l"].setValue(20)
    pump(app)
    assert abs(((p.clips[cv.id].layout or {}).get("crop") or {}).get("l", 0) - 0.2) < 1e-6, p.clips[cv.id].layout
    clic(ins.secciones["recorte"].boton)
    pump(app)
    assert not (p.clips[cv.id].layout or {}).get("crop"), p.clips[cv.id].layout
    clic(ins.secciones["recorte"].boton)
    pump(app)
    assert abs(p.clips[cv.id].layout["crop"]["l"] - 0.2) < 1e-6
    assert abs(ins.crop_spins["l"].value() - 20) < 0.01
    print("✓ ● Volumen silencia y devuelve el volumen; Recorte con números, ● lo quita y lo devuelve")

    # texto: ● de Sombra (y lo de antes: tw["shadow"])
    ins.set_selection([ct])
    pump(app)
    clic(ins.secciones["texto_sombra"].boton)
    pump(app)
    assert p.clips[ct].text.get("shadow") is True, p.clips[ct].text.get("shadow")
    ins.tw["shadow"][0].setChecked(False)
    pump(app)
    assert p.clips[ct].text.get("shadow") is False
    print("✓ Texto: el ● de Sombra la enciende y la apaga")

    # (1) ● de Trazo y de Fundido (texto: van por set_text_props) y (7) Desenfocar conserva su valor
    ctrl.set_text_props(ct, stroke_size=5.0, fade=0.4, blur_under=0.7)
    ins.set_selection([ct])
    pump(app)
    for clave, campo, antes in (("texto_trazo", "stroke_size", 5.0), ("texto_animacion", "fade", 0.4),
                                ("texto_desenfocar", "blur_under", 0.7)):
        b = ins.secciones[clave].boton
        assert b.isEnabled() and b.isChecked(), clave
        clic(b)
        pump(app)
        assert not p.clips[ct].text[campo], (clave, p.clips[ct].text[campo])
        clic(ins.secciones[clave].boton)
        pump(app)
        assert abs(float(p.clips[ct].text[campo]) - antes) < 1e-9, (clave, p.clips[ct].text[campo])
    print("✓ ● de Trazo, Fundido y Desenfocar lo de debajo: se apagan y vuelven con su valor")

    # transición: tipo y duración desde el Inspector; ● la quita sin perderla
    ins.set_transition(cv2.id)
    pump(app)
    i = ins.trans_tipo.findData("zoomin")
    ins.trans_tipo.setCurrentIndex(i)
    ins.trans_tipo.activated.emit(i)
    pump(app)
    assert p.clips[cv2.id].fx["trans"]["type"] == "zoomin"
    assert not ins.secciones["transicion"].boton.isEnabled(), "(8) la transición no tiene ● (🗑 Quitar y ↺)"
    clic(ins.secciones["transicion"].btn_reset)
    pump(app)
    assert p.clips[cv2.id].fx["trans"]["type"] == "fade"
    print("✓ Transición: tipo desde el Inspector; ↺ la deja como siempre; sin ● (no deja transiciones huérfanas)")

    # (3) sin pasos vacíos en Ctrl+Z: encender algo que ya está encendido no hace nada
    ins.set_selection([cv.id])
    pump(app)
    n0 = ctrl.undo_stack.count()
    ins._sec_encendida("composicion", True)
    assert ctrl.undo_stack.count() == n0, "ningún paso vacío"
    # (4) Transformar no devuelve un recorte que sigue apagado
    ctrl.set_clip_props([cv.id], "caja", layout={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "crop": {"l": 0.2}})
    pump(app)
    clic(ins.secciones["recorte"].boton)
    pump(app)
    clic(ins.secciones["transformar"].boton)
    pump(app)
    assert not (p.clips[cv.id].layout or {}).get("w", 1) < 1, p.clips[cv.id].layout
    clic(ins.secciones["transformar"].boton)
    pump(app)
    lay = p.clips[cv.id].layout
    assert lay["w"] == 0.5 and not lay.get("crop"), ("el recorte sigue apagado", lay)
    clic(ins.secciones["recorte"].boton)
    pump(app)
    assert p.clips[cv.id].layout["crop"]["l"] == 0.2
    print("✓ sin pasos vacíos en Ctrl+Z; Transformar y Recorte se apagan y encienden cada uno por su lado")

    # (3) un clip bloqueado: ni ● ni ↺
    ctrl.set_clip_props([cv.id], "bloquear", locked=True)
    ins.set_selection([ca.id])
    ins.set_selection([cv.id])
    pump(app)
    for k in ("transformar", "composicion", "color"):
        assert not ins.secciones[k].boton.isEnabled() and not ins.secciones[k].btn_reset.isEnabled(), k
    assert not ins.frame_box.isEnabled() and not ins.transform_box.isEnabled()
    ctrl.set_clip_props([cv.id], "desbloquear", locked=False)
    pump(app)
    assert ins.secciones["composicion"].boton.isEnabled()
    print("✓ clip bloqueado: sus ●/↺ y sus controles, apagados")

    # varios: volumen común
    ins.set_selection([cv.id, ca.id])
    pump(app)
    assert vis("varios_audio") and vis("varios_archivo")
    ins.multi_volume.setValue(50)
    pump(app)
    assert p.clips[cv.id].volume == 0.5 and p.clips[ca.id].volume == 0.5
    assert ins.secciones["escena"].isHidden(), "(5) sin «Escena y clip compuesto» con varios"
    ins.set_selection([cv.id])                      # (2) al volver a un video, todas sus secciones
    pump(app)
    for k in ("encuadre", "mejorar", "seguimiento", "transformar", "composicion", "color"):
        assert not ins.secciones[k].isHidden(), k
    print("✓ Varios clips: secciones comunes (volumen para todos); al volver a un video vuelven todas las suyas")

    # rapidez: < 50 ms en elegir
    tiempos = {}
    for nombre, ids in (("video", [cv.id]), ("audio", [ca.id]), ("texto", [ct]), ("imagen", [ci.id]),
                        ("varios", [cv.id, ca.id]), ("nada", []), ("transición", None)):
        ms = []
        for _ in range(6):
            ins.set_selection([])
            pump(app, 0.01)
            t0 = time.perf_counter()
            if ids is None:
                ins.set_transition(cv2.id)
            else:
                ins.set_selection(ids)
            ms.append((time.perf_counter() - t0) * 1000)
            pump(app, 0.01)
        tiempos[nombre] = statistics.median(ms)
    print("  tiempos (mediana, ms):", {k: round(v, 1) for k, v in tiempos.items()})
    lentos = {k: v for k, v in tiempos.items() if v >= 50}
    assert not lentos, lentos
    print("✓ elegir video / audio / texto / imagen / varios / nada / transición: todo < 50 ms")
    ins.close()

    # (6) dentro de la ventana de verdad (con el tema y la ayuda F1)
    from editoria.ui.main_window import MainWindow
    from editoria.ui.theme import apply_dark_theme
    apply_dark_theme(app)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    pump(app, 0.5)
    c2 = win.ctrl
    q = c2.project
    w1 = next(t for t in q.tracks if t.kind == TRACK_VIDEO)
    b1 = next(t for t in q.tracks if t.kind == TRACK_AUDIO)
    for m in (mv, ma):
        q.media[m.id] = m
    xv = Clip(new_id(), mv.id, w1.id, 0.0, 0.0, 10.0)
    xa = Clip(new_id(), ma.id, b1.id, 0.0, 0.0, 10.0)
    for c in (xv, xa):
        q.clips[c.id] = c
    c2.project_changed.emit()
    xt = c2.add_text(20.0, 3.0, "Otro texto")
    xt = xt if isinstance(xt, str) else next(c.id for c in q.clips.values() if c.text is not None)
    pump(app, 0.3)
    insw = win.inspector
    t_win = {}
    for nombre, ids in (("video", [xv.id]), ("audio", [xa.id]), ("texto", [xt]), ("varios", [xv.id, xa.id]),
                        ("nada", [])):
        ms = []
        for _ in range(5):
            insw.set_selection([])
            pump(app, 0.02)
            t0 = time.perf_counter()
            insw.set_selection(ids)
            ms.append((time.perf_counter() - t0) * 1000)
            pump(app, 0.02)
        t_win[nombre] = statistics.median(ms)
    print("  en la ventana (mediana, ms):", {k: round(v, 1) for k, v in t_win.items()})
    assert all(v < 50 for v in t_win.values()), t_win
    c2.undo_stack.setClean()
    c2._media_dirty = False
    win.close()
    pump(app, 0.2)
    print("✓ dentro de la ventana: elegir cualquier cosa < 50 ms")
    print("TODO OK")


if __name__ == "__main__":
    main()
