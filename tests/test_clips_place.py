"""
Prueba de «🎬 Clips» (panel por carpetas de palabra), sin red y sin ventanas:
  · menciones con distintivo: 📁 n (tiene carpeta) / ＋ (aún no), y la carpeta de una palabra que no es juego conocido;
  · marcas de la mención en la línea de tiempo (banderitas, clic = ir, ✕ las quita; se quedan al cambiar de pestaña);
  · cuadrícula de la carpeta con miniaturas (imágenes y fotogramas de video); crear carpeta; soltar archivos;
  · «📍 Poner donde lo dices» con 1 archivo y con 2 (reparto por momentos, un solo paso de deshacer);
  · «⏵ Poner en el cabezal» (botón y menú); menú del clic derecho; «Quitar» a la Papelera (sustituida, nunca real);
  · sin la parte opcional (se simula su ausencia): el panel no muestra ninguna pestaña ni botón de ella;
  · compuesto (⧉).
La carpeta raíz de la prueba está en _pruebas_tmp. En esta prueba no se busca nada fuera del equipo.
Ejecutar:  .venv/Scripts/python.exe tests/test_clips_place.py _pruebas_tmp/test_clips_place   (QT_QPA_PLATFORM=offscreen)
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# los modelos ya instalados (caras, etc.) se leen de la carpeta del programa; no se instala nada
os.environ.setdefault("EDITORIA_MODELOS", os.path.join(_RAIZ, "datos", "modelos"))
_TMPROOT = os.path.join(_RAIZ, "_pruebas_tmp")
os.makedirs(_TMPROOT, exist_ok=True)
_TMP = tempfile.mkdtemp(prefix="reclaimer_datos_", dir=_TMPROOT)
atexit.register(shutil.rmtree, _TMP, True)
os.environ["LOCALAPPDATA"] = _TMP
os.environ["EDITORIA_DATOS"] = os.path.join(_TMP, "EditorIA")
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban)

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # «✓» y «📁» al imprimir
except (AttributeError, ValueError):
    pass

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QHideEvent, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit,  # noqa: E402
                               QPushButton, QScrollBar, QTabWidget)

from editoria.core import media as MEDIA  # noqa: E402
from editoria.core import overlay  # noqa: E402
from editoria.core.controller import ProjectController  # noqa: E402
from editoria.core.model import KIND_AUDIO, KIND_VIDEO, TRACK_VIDEO, Clip, MediaItem, Project  # noqa: E402
from editoria.ui import clips_panel as CP  # noqa: E402
from editoria.ui import help as AYUDA  # noqa: E402
from editoria.ui.clips_panel import ClipsPanel  # noqa: E402
from editoria.ui.timeline import TimelineWidget  # noqa: E402

NARRACION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.wav")
TRANSCRIPCION = os.path.join(_RAIZ, "tests", "assets", "narracion_prueba.transcripcion.json")
CARA_MODELO = os.path.join(_RAIZ, "datos", "modelos", "caras", "face_detection_yunet_2023mar.onnx")
RAIZ_CLIPS = os.path.join(_TMPROOT, "test_clips_place_carpetas")     # la carpeta raíz de la prueba (se rehace)
DUR_VIDEO = 12.0

app = None


def _esperar(panel, segundos: float = 15.0):
    """Deja terminar el hilo de la carpeta (miniaturas) para que no pise la prueba."""
    t0 = time.time()
    trabajos = [panel._job_carpeta]
    while time.time() - t0 < segundos and any(j is not None and j.isRunning() for j in trabajos):
        app.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)


def _video_prueba() -> str:
    ruta = os.path.join(_TMP, "gen.mp4")
    subprocess.run([MEDIA.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-t", str(DUR_VIDEO), "-pix_fmt", "yuv420p", ruta], check=True, timeout=180,
                   creationflags=0x08000000)
    return ruta


def _imagen_prueba() -> str:
    ruta = os.path.join(_TMP, "imagen_prueba.png")
    img = QImage(320, 180, QImage.Format_RGB32)
    img.fill(QColor(200, 120, 40))
    assert img.save(ruta, "PNG"), "no pude crear la imagen de prueba"
    return ruta


def _preparar_carpetas(video: str, imagen: str):
    """La carpeta raíz de la prueba: «Fortnite» (video + imagen + un .txt que no cuenta), «Combate» (un video)."""
    shutil.rmtree(RAIZ_CLIPS, ignore_errors=True)
    for sub in ("Fortnite", "Combate"):
        os.makedirs(os.path.join(RAIZ_CLIPS, sub))
    shutil.copy(video, os.path.join(RAIZ_CLIPS, "Fortnite", "gen.mp4"))
    shutil.copy(imagen, os.path.join(RAIZ_CLIPS, "Fortnite", "imagen.png"))
    with open(os.path.join(RAIZ_CLIPS, "Fortnite", "notas.txt"), "w", encoding="utf-8") as f:
        f.write("no es material")
    shutil.copy(video, os.path.join(RAIZ_CLIPS, "Combate", "clip_combate.mp4"))


def _palabras() -> list:
    """Transcripción real de la narración (una COPIA en memoria): «Fortnite» dos veces y «Minecraft» una vez."""
    with open(TRANSCRIPCION, encoding="utf-8") as f:
        words = json.load(f)["words"]
    for i in (12, 20):
        words[i][2] = "Fortnite"
    words[30][2] = "Minecraft"
    return words


def _proyecto(video: str) -> Project:
    p = Project.new()                      # pistas: V2, V1, A1
    words = _palabras()
    dur_nar = float(words[-1][1]) + 1.0
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur_nar, probed=True)
    p.media["vid"] = MediaItem(id="vid", path=video, kind=KIND_VIDEO, name="gen.mp4", duration=DUR_VIDEO,
                               width=320, height=180, fps=25.0, probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    v2, v1, a1 = p.tracks
    p.clips["cn"] = Clip(id="cn", media_id="nar", track_id=a1.id, start=0.0, source_in=0.0, duration=dur_nar)
    p.clips["cv"] = Clip(id="cv", media_id="vid", track_id=v1.id, start=0.0, source_in=0.0, duration=DUR_VIDEO)
    return p


def _fila(panel, term: str) -> int:
    return next(i for i in range(panel.lista_menciones.count())
                if panel.lista_menciones.item(i).text().startswith(term + " ·"))


def _elegir(panel, term: str):
    panel.lista_menciones.setCurrentRow(-1)
    panel.lista_menciones.setCurrentRow(_fila(panel, term))
    _esperar(panel)


def _item(panel, sufijo: str):
    return next(panel.lista_carpeta.item(i) for i in range(panel.lista_carpeta.count())
                if panel.lista_carpeta.item(i).data(Qt.UserRole).endswith(sufijo))


def _seleccionar(panel, *sufijos):
    """Selecciona en la cuadrícula los archivos que acaban en esos sufijos (siempre desde la lista viva)."""
    panel.lista_carpeta.clearSelection()
    for suf in sufijos:
        _item(panel, suf).setSelected(True)


def _mid_de(ctrl, ruta: str) -> str:
    norm = os.path.normcase(os.path.abspath(ruta))
    return next(m.id for m in ctrl.project.media.values() if os.path.normcase(os.path.abspath(m.path)) == norm)


def _mmss(t):
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def _nuevos(ctrl, antes: set) -> list:
    return [c for cid, c in ctrl.project.clips.items() if cid not in antes]


def _sin_solapes(ctrl, clips: list) -> bool:
    for a in clips:
        for b in clips:
            if a is not b and a.track_id == b.track_id and a.start < b.end - 1e-6 and b.start < a.end - 1e-6:
                return False
    return True


def prueba_menciones(panel):
    textos = [panel.lista_menciones.item(i).text() for i in range(panel.lista_menciones.count())]
    fortnite = next(t for t in textos if t.startswith("Fortnite ·"))
    combate = next(t for t in textos if t.startswith("Combate ·"))
    minecraft = next(t for t in textos if t.startswith("Minecraft ·"))
    assert fortnite.endswith("📁 2"), fortnite           # video + imagen (el .txt no cuenta)
    assert combate.endswith("📁 1"), combate              # palabra que no es juego conocido, solo por su carpeta
    assert minecraft.endswith("＋"), minecraft            # aún sin carpeta
    assert panel.lista_menciones.item(0).text().split(" · ")[0] in ("Fortnite", "Combate"), textos
    con = [t for t in textos if "📁" in t]
    sin = [t for t in textos if t.endswith("＋")]
    assert con and sin and textos.index(con[-1]) < textos.index(sin[0]), "las menciones con carpeta van primero"
    print("✓ menciones: «Fortnite» 📁 2, «Combate» 📁 1 (sale en minúscula en la narración y no es juego conocido), "
          "«Minecraft» ＋ (sin carpeta); las de carpeta van primero")


def prueba_marcas(ctrl, panel, timeline):
    _elegir(panel, "Fortnite")
    esperadas = [float(h["tl"]) for h in panel.mencion["hits"] if h["tl"] is not None]
    assert len(esperadas) == 2, esperadas
    recibidas = []
    panel.hints_changed.connect(recibidas.append)
    panel.hints_changed.connect(timeline.set_hint_marks)
    panel._elegir_mencion(_fila(panel, "Fortnite"), buscar=False)     # volver a elegirla: emite las marcas
    marcas = recibidas[-1]
    assert [round(t, 2) for t, _ in marcas] == [round(t, 2) for t in esperadas], marcas
    assert all(txt == "🎬 Fortnite" for _, txt in marcas), marcas
    assert timeline.hint_marks == marcas, timeline.hint_marks
    t0 = marcas[0][0]
    pos = QPointF(timeline.x_for(t0) + 4, timeline.TOPIC_H + 5)
    assert timeline.hint_mark_at(pos) == 0, "la banderita no responde al punto"
    seeks = []
    timeline.seek_requested.connect(seeks.append)
    ev = QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    timeline.mousePressEvent(ev)
    assert seeks and abs(seeks[0] - t0) < 0.01, seeks
    panel._quitar_marcas()                                          # ✕
    assert recibidas[-1] == [] and timeline.hint_marks == [], recibidas[-1]
    panel._elegir_mencion(_fila(panel, "Fortnite"), buscar=False)   # tras ✕ no vuelven solas
    assert recibidas[-1] == [], "tras ✕ no deben volver solas"
    panel._elegir_mencion(_fila(panel, "Fortnite"), buscar=True)
    _esperar(panel)
    assert recibidas[-1] and len(recibidas[-1]) == 2
    panel.hideEvent(QHideEvent())                                   # pasar a otra pestaña: las marcas SE QUEDAN
    assert timeline.hint_marks and len(timeline.hint_marks) == 2, "al cambiar de pestaña deben quedarse"
    print(f"✓ marcas: {len(marcas)} banderitas «🎬 Fortnite» en {[_mmss(t) for t, _ in marcas]}; "
          "clic en la banderita = seek; ✕ las quita; al cambiar de pestaña se quedan")


def prueba_carpeta(ctrl, panel):
    _elegir(panel, "Fortnite")
    assert panel.pestanas is None or panel.pestanas.currentIndex() == 0
    assert panel.lista_carpeta.count() == 2, panel.lista_carpeta.count()
    assert panel.btn_crear.isHidden(), "con carpeta no hay botón de crear"
    assert all(not panel.lista_carpeta.item(i).icon().isNull() for i in range(2)), "faltan miniaturas"
    print("✓ cuadrícula: 2 archivos de «Fortnite» (imagen y fotograma de video), con miniatura; el .txt no sale")

    # arrastrar fuera (a la línea de tiempo): la URL del archivo
    urls = panel.lista_carpeta.mimeData([_item(panel, ".png")]).urls()
    assert urls and urls[0].toLocalFile().endswith("imagen.png"), urls

    # sin carpeta: el botón «＋ Crear carpeta»
    _elegir(panel, "Minecraft")
    assert not panel.btn_crear.isHidden() and "Crear carpeta" in panel.btn_crear.text(), panel.btn_crear.text()
    assert panel.lista_carpeta.count() == 0
    panel._crear_carpeta()
    assert os.path.isdir(os.path.join(RAIZ_CLIPS, "Minecraft")), "debe crearse la carpeta"
    _esperar(panel)
    assert panel.btn_crear.isHidden(), "ya creada: sin botón"
    print("✓ crear carpeta: «Minecraft» se crea en la carpeta raíz y el botón desaparece")

    # soltar archivos sobre la fila de «Minecraft» (sin elegirla antes) → se copian a su carpeta
    # (Desde el cambio «enlazar o copiar» se pregunta una vez; aquí se responde «copiar» para lo de siempre.)
    _modo_original = CP.modo_archivo_suelto
    CP.modo_archivo_suelto = lambda parent: "copiar"
    try:
        _elegir(panel, "Combate")
        soltado = os.path.join(_TMP, "soltado.png")
        shutil.copy(os.path.join(RAIZ_CLIPS, "Fortnite", "imagen.png"), soltado)
        panel._soltar_archivos([soltado], _fila(panel, "Minecraft"))
        _esperar(panel)
        assert os.path.isfile(os.path.join(RAIZ_CLIPS, "Minecraft", "soltado.png")), "el archivo debe copiarse"
        assert panel.lista_carpeta.count() == 1 and panel.mencion["term"] == "Combate", "sigue la palabra elegida"
        # soltar sobre la cuadrícula de la palabra elegida (Combate) y repetir el mismo archivo no duplica
        otro = os.path.join(_TMP, "otro.mp4")
        shutil.copy(os.path.join(_TMP, "gen.mp4"), otro)
        panel._soltar_archivos([otro])
        _esperar(panel)
        assert os.path.isfile(os.path.join(RAIZ_CLIPS, "Combate", "otro.mp4"))
        assert panel.lista_carpeta.count() == 2
        panel._soltar_archivos([os.path.join(RAIZ_CLIPS, "Combate", "otro.mp4")])     # ya está dentro: no se copia
        _esperar(panel)
        assert len(os.listdir(os.path.join(RAIZ_CLIPS, "Combate"))) == 2
    finally:
        CP.modo_archivo_suelto = _modo_original
    print("✓ soltar: archivos del Explorador → carpeta de la palabra (se crea si falta); lo ya dentro no se copia")
    _elegir(panel, "Fortnite")


def prueba_poner(ctrl, panel):
    p = ctrl.project
    v2, v1, a1 = p.tracks
    _elegir(panel, "Fortnite")
    if panel.pestanas is not None:
        panel.pestanas.setCurrentIndex(0)
    ruta_video = _item(panel, "gen.mp4").data(Qt.UserRole)
    ruta_imagen = _item(panel, "imagen.png").data(Qt.UserRole)
    ctrl.import_now([ruta_video])                  # ya en Medios: así se cuenta solo lo que pone el 📍
    marcados = panel._hits_marcados()
    assert len(marcados) == 2, len(marcados)
    tiempos = sorted(float(h["tl"]) for h in marcados)

    # 1) un archivo → UN clip por momento, en UN paso de deshacer
    _seleccionar(panel, "gen.mp4")
    antes = set(ctrl.project.clips)
    pila = ctrl.undo_stack.index()
    panel.btn_poner_mio.click()
    assert ctrl.undo_stack.index() == pila + 1, "debe ser UN solo paso de deshacer"
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 2, [c.id for c in nuevos]
    for c in nuevos:
        tr = ctrl.project.track(c.track_id)
        assert tr.kind == TRACK_VIDEO and c.media_id == _mid_de(ctrl, ruta_video), (tr.name, c.media_id)
        assert ctrl.project.track_index(c.track_id) < ctrl.project.track_index(v1.id), "debe ir por encima de V1"
        assert c.volume == 0.0, "en silencio (B-roll)"
        assert any(abs(c.start - t) < 0.01 for t in tiempos), (c.start, tiempos)
        vd = overlay.voice_duration(ctrl.project, c.start)
        esperada = 4.0 if vd is None else min(6.0, max(2.0, vd))
        assert abs(c.duration - esperada) < 1e-6 and 2.0 <= c.duration <= 6.0, (c.duration, vd)
        assert abs(c.source_in - min(3.0, 0.1 * DUR_VIDEO)) < 1e-6, c.source_in
    assert _sin_solapes(ctrl, nuevos)
    print(f"✓ poner (1 archivo): 2 clips en {[round(c.start, 2) for c in nuevos]} s, en silencio, "
          f"un solo Ctrl+Z")
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == antes, "el deshacer debe quitar todos los clips de una vez"

    # 2) dos archivos (video + imagen) → reparto: momento 1 → archivo 1, momento 2 → archivo 2; un solo Ctrl+Z
    ctrl.import_now([ruta_imagen])
    _seleccionar(panel, "gen.mp4", "imagen.png")
    antes = set(ctrl.project.clips)
    pila = ctrl.undo_stack.index()
    panel.btn_poner_mio.click()
    assert ctrl.undo_stack.index() == pila + 1, (
        "el reparto debe ser UN solo paso de deshacer", pila, ctrl.undo_stack.index(),
        [(c.media_id, round(c.start, 2)) for c in _nuevos(ctrl, antes)], panel.lista_carpeta.count())
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 2, [(c.media_id, c.start) for c in nuevos]
    por_archivo = {c.media_id: c for c in nuevos}
    assert set(por_archivo) == {_mid_de(ctrl, ruta_video), _mid_de(ctrl, ruta_imagen)}, por_archivo.keys()
    assert _sin_solapes(ctrl, nuevos)
    print("✓ poner (2 archivos): reparto por momentos (uno de cada), en UN solo Ctrl+Z")
    ctrl.undo_stack.undo()
    assert set(ctrl.project.clips) == antes

    # 3) V2 ocupada en ese tramo → otra pista por encima de V1
    t1 = tiempos[0]
    ocupante = Clip(id="occ", media_id="vid", track_id=v2.id, start=t1 - 0.5, source_in=0.0, duration=10.0)
    ctrl.project.clips["occ"] = ocupante
    antes = set(ctrl.project.clips)
    _seleccionar(panel, "gen.mp4")
    panel._poner_mis([ruta_video], [marcados[0]])
    nuevos = _nuevos(ctrl, antes)
    assert len(nuevos) == 1, [c.id for c in nuevos]
    assert nuevos[0].track_id != v2.id and ctrl.project.track(nuevos[0].track_id).kind == TRACK_VIDEO
    assert ctrl.project.track_index(nuevos[0].track_id) < ctrl.project.track_index(v1.id)
    assert _sin_solapes(ctrl, nuevos + [ocupante])
    print("✓ V2 ocupada: el clip va a otra pista por encima de V1 (sin solapes)")
    ctrl.undo_stack.undo()
    ctrl.project.clips.pop("occ", None)

    # 4) ⏵ Poner en el cabezal: botón y menú del clic derecho
    class _Cabezal:
        playhead = round(tiempos[0] + 7.3, 2)
    panel.timeline = _Cabezal()
    _seleccionar(panel, "gen.mp4")
    for via in ("botón", "menú"):
        antes = set(ctrl.project.clips)
        if via == "botón":
            panel.btn_cabezal_mio.click()
        else:
            menu = panel._menu_carpeta(_item(panel, "gen.mp4"))
            next(a for a in menu.actions() if a.text().startswith("⏵ Poner en el cabezal")).trigger()
        nuevos = _nuevos(ctrl, antes)
        assert len(nuevos) == 1, (via, [c.id for c in nuevos])
        assert abs(nuevos[0].start - _Cabezal.playhead) < 1e-6, (via, nuevos[0].start)
        assert CP.DURACION_MIN - 1e-6 <= nuevos[0].duration <= CP.DURACION_MAX + 1e-6, nuevos[0].duration
        ctrl.undo_stack.undo()
        assert set(ctrl.project.clips) == antes
    print(f"✓ ⏵ Poner en el cabezal (botón y menú): el clip empieza en {_Cabezal.playhead} s")
    panel.timeline = None


def prueba_menu_y_papelera(ctrl, panel):
    _elegir(panel, "Fortnite")
    it = _item(panel, "gen.mp4")
    ruta = it.data(Qt.UserRole)
    menu = panel._menu_carpeta(it)
    textos = [a.text() for a in menu.actions()]
    esperado = ["📍 Poner donde lo dices", "⏵ Poner en el cabezal", "▶ Abrir", "📂 Mostrar en la carpeta",
                "🗑 Quitar de la carpeta (a la Papelera)…"]
    assert textos == esperado, textos

    # clic derecho: se abre con AYUDA.exec_menu (sustituido: no se abre ningún menú)
    abiertos = []
    original_menu = AYUDA.exec_menu
    AYUDA.exec_menu = lambda m, pos: abiertos.append([a.text() for a in m.actions()])
    panel.lista_carpeta.itemAt = lambda _pos: it
    try:
        panel._clic_derecho(panel.lista_carpeta, panel.lista_carpeta.viewport().rect().center())
    finally:
        AYUDA.exec_menu = original_menu
        del panel.lista_carpeta.itemAt
    assert abiertos == [esperado], abiertos

    # ▶ Abrir y 📂 Mostrar: openUrl sustituido (no se abre el Explorador)
    llamadas = []

    class _Abridor:
        @staticmethod
        def openUrl(url):
            llamadas.append(url.toLocalFile())
            return True

    original = CP.QDesktopServices
    CP.QDesktopServices = _Abridor
    try:
        menu.actions()[2].trigger()
        menu.actions()[3].trigger()
    finally:
        CP.QDesktopServices = original
    norm = lambda r: os.path.normcase(os.path.normpath(r))   # Qt usa / y Windows \ : se compara normalizado
    assert [norm(x) for x in llamadas] == [norm(ruta), norm(os.path.dirname(ruta))], llamadas

    # Papelera: sustituida. Responde «No» (nada), luego «Sí» (la ruta llega a la función, que es falsa)
    enviados = []

    class _Caja:
        Yes, No = 0x4000, 0x10000
        respuesta = No

        @classmethod
        def question(cls, *_a, **_k):
            return cls.respuesta

    original_papelera, original_caja = CP._a_papelera, CP.QMessageBox
    CP._a_papelera = lambda r: (enviados.append(r) or True)
    CP.QMessageBox = _Caja
    try:
        menu.actions()[4].trigger()
        assert enviados == [], "con «No» no se manda nada"
        _Caja.respuesta = _Caja.Yes
        menu.actions()[4].trigger()
    finally:
        CP._a_papelera, CP.QMessageBox = original_papelera, original_caja
    assert enviados == [ruta], enviados
    assert os.path.isfile(ruta), "el archivo real sigue en su sitio (la Papelera está sustituida)"
    print("✓ menú del clic derecho: 5 opciones (poner, cabezal, abrir, mostrar, quitar); "
          "«Quitar» pregunta y, si sí, llama a la Papelera (sustituida)")



def prueba_sin_parte_opcional(ctrl):
    """Sin la parte opcional (HAY_INTERNET False) el panel no tiene pestañas ni botones ni textos de ella."""
    original = CP.HAY_INTERNET
    CP.HAY_INTERNET = False
    try:
        sin = ClipsPanel(ctrl)
        assert sin.pestanas is None and not sin.findChildren(QTabWidget), "sin la parte opcional no hay pestañas"
        for tipo in (QComboBox, QLineEdit, QPlainTextEdit):
            assert not sin.findChildren(tipo), tipo
        # los botones y textos de esa parte llevan estos iconos: ninguno debe salir sin ella
        marcas = ("🌐", "⬇", "🔎", "🔍", "🚫", "📋")
        textos = [w.text() for tipo in (QLabel, QPushButton, QCheckBox) for w in sin.findChildren(tipo)]
        assert not any(m in txt for txt in textos for m in marcas), textos
        sin.deleteLater()
    finally:
        CP.HAY_INTERNET = original
    print("✓ sin la parte opcional (simulado): ninguna pestaña, botón ni texto de ella; «Mi carpeta» sigue funcionando")


def prueba_compuesto(app_ctrl_cls, video: str):
    """Narración dentro de un clip compuesto (⧉): los momentos siguen saliendo (no «cortado»)."""
    ctrl = app_ctrl_cls()
    p = Project.new()
    words = _palabras()
    dur_nar = float(words[-1][1]) + 1.0
    v2, v1, a1 = p.tracks
    p.media["nar"] = MediaItem(id="nar", path=NARRACION, kind=KIND_AUDIO, name="narracion_prueba.wav",
                               duration=dur_nar, probed=True)
    p.media["cmp"] = MediaItem(id="cmp", path=video, kind=KIND_VIDEO, name="compuesto", duration=dur_nar,
                               probed=True)
    p.transcripts = {"nar": {"language": "es", "words": words}}
    p.compounds = {"cmp": {"a": 0.0, "clips": [{"media_id": "nar", "source_in": 0.0, "speed": 1.0,
                                                 "duration": dur_nar, "start": 0.0}]}}
    p.clips["cc"] = Clip(id="cc", media_id="cmp", track_id=v1.id, start=2.0, source_in=0.0, duration=dur_nar)
    ctrl.project = p
    panel = ClipsPanel(ctrl)
    panel.ensure_fresh()                                  # el panel no se ve aquí: se calcula al pedirlo
    _elegir(panel, "Fortnite")
    hits = panel.mencion["hits"]
    assert len(hits) == 2 and all(h["tl"] is not None for h in hits), hits
    for h in hits:
        assert abs(h["tl"] - (h["src"] + 2.0)) < 0.02, (h["src"], h["tl"])
    ctrl.project.clips.pop("cc")
    panel.recalcular()
    _elegir(panel, "Fortnite")
    assert all(h["tl"] is None for h in panel.mencion["hits"]), panel.mencion["hits"]
    print("✓ compuesto: con la narración dentro de un ⧉ los momentos salen a 2 s + su segundo; cortado sin él")
    panel.deleteLater()
    app.processEvents()


def main():
    global app
    app = QApplication.instance() or QApplication(sys.argv)
    ajustes = QSettings("EditorIA", "EditorIA")
    # sin red: esta prueba no busca clips (si la parte opcional existe, su búsqueda se anula aquí)
    ClipsPanel._buscar = lambda self, *_a, **_k: None
    try:
        video = _video_prueba()
        imagen = _imagen_prueba()
        _preparar_carpetas(video, imagen)
        ajustes.setValue(CP.RAIZ_CLAVE, RAIZ_CLIPS)          # la carpeta raíz de la prueba (en _pruebas_tmp)
        ctrl = ProjectController()
        ctrl.project = _proyecto(video)
        panel = ClipsPanel(ctrl)
        timeline = TimelineWidget(ctrl, QScrollBar())
        timeline.resize(1200, 400)
        assert panel.raiz == RAIZ_CLIPS, panel.raiz
        panel.ensure_fresh()                                  # el panel no se ve aquí: se calcula al pedirlo
        prueba_menciones(panel)
        prueba_marcas(ctrl, panel, timeline)
        prueba_carpeta(ctrl, panel)
        prueba_poner(ctrl, panel)
        prueba_menu_y_papelera(ctrl, panel)
        prueba_sin_parte_opcional(ctrl)
        prueba_compuesto(ProjectController, video)
        timeline.deleteLater()
        panel.deleteLater()
        app.processEvents()
    finally:
        ajustes.remove(CP.RAIZ_CLAVE)
    print("TODO OK")


if __name__ == "__main__":
    main()
