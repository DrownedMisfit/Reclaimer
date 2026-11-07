"""Utilidades compartidas por la interfaz: colores, formato de tiempo, tipo de arrastre."""
from __future__ import annotations

from PySide6.QtGui import QColor

SEGMENT_MIME = "application/x-reclaimer-segment"   # un trozo: id|desde|hasta
MEDIA_MIME = "application/x-editoria-media"
EFFECT_MIME = "application/x-reclaimer-effect"     # un efecto (look:… · trans:… · sfx:… · file:…) para soltar en un clip

COLORS = {
    # Estilo DaVinci Resolve
    "bg": QColor("#1e1e20"),
    "panel": QColor("#28282b"),
    "panel_alt": QColor("#232325"),
    "line": QColor("#36363a"),
    "text": QColor("#dcdce0"),
    "text_dim": QColor("#a4a4ab"),
    "accent": QColor("#e8742f"),
    "playhead": QColor("#e5413c"),
    "selection": QColor("#ec3a32"),   # todo lo seleccionado (clips, transición, rectángulo): UN solo color, rojo
    "clip_sel": QColor("#ec3a32"),    # contorno del clip seleccionado: rojo sólido, como en Resolve
    "clip_video": QColor("#3f6a94"),
    "clip_image": QColor("#6f5a9a"),
    "clip_audio": QColor("#2f7a57"),
    "clip_text": QColor("#9a6a2a"),
    "clip_disabled": QColor("#4a4a4f"),
    "ai": QColor("#ffb020"),
    "locked": QColor("#d9a400"),
    "missing": QColor("#b03a30"),
}


# Colores de cada tipo de sugerencia de la IA
SUGGESTION_COLORS = {
    "silence": QColor("#e5534b"),
    "noise": QColor("#39c5cf"),
    "filler": QColor("#e3b341"),
    "repeat": QColor("#f0883e"),
    "retake": QColor("#b083f0"),
    "doubt": QColor("#8b949e"),
    "clipping": QColor("#ff3dbb"),
    "manual": QColor("#f85149"),
    "zoom": QColor("#ffd166"),
}


def fmt_tc(t: float, fps: float = 30.0) -> str:
    """Timecode como en DaVinci Resolve: 75.5 s a 30 fps -> '00:01:15:15' (horas:min:seg:fotograma)."""
    fps = max(1.0, fps)
    total_frames = int(round(max(0.0, t) * fps))
    f = total_frames % int(round(fps))
    s = total_frames // int(round(fps))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}:{f:02d}"


def fmt_time(t: float, frac: bool = True) -> str:
    """75.5 -> '01:15.50' (o '1:01:15.50' si dura más de una hora)."""
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    sec = f"{s:05.2f}" if frac else f"{int(s):02d}"
    if h >= 1:
        return f"{int(h)}:{int(m):02d}:{sec}"
    return f"{int(m):02d}:{sec}"


def lazy_refresh(widget, fn):
    """⚡ Devuelve un «refrescar» para conectar a los avisos de cambio (project_changed…): si el panel está a la vista,
    se refresca una sola vez aunque lleguen varios avisos seguidos; si está oculto (otra pestaña, panel cerrado),
    no gasta nada y se refresca solo al volver a verse. Antes, cada edición rehacía también los paneles ocultos."""
    from PySide6.QtCore import QEvent, QObject, QTimer

    class _Lazy(QObject):
        def __init__(self):
            super().__init__(widget)
            self.pending = False
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(0)
            self.timer.timeout.connect(self.run)
            widget.installEventFilter(self)

        def __call__(self, *_a):
            self.pending = True
            if widget.isVisible():
                self.timer.start()

        def run(self):
            if self.pending and widget.isVisible():
                self.pending = False
                fn()

        def eventFilter(self, obj, ev):
            if obj is widget and ev.type() == QEvent.Show and self.pending:
                self.timer.start()
            return False

    return _Lazy()


def pick_color(initial, parent=None, title: str = "Color", alpha: bool = False) -> QColor:
    """Selector de color. Se abre sobre la VENTANA, no sobre el botón: el botón de color pinta su fondo del color
    elegido con una hoja de estilo, y un diálogo hijo suyo la heredaba (salía todo rojo, con el rojo elegido)."""
    from PySide6.QtWidgets import QColorDialog
    opts = QColorDialog.ColorDialogOption.ShowAlphaChannel if alpha else QColorDialog.ColorDialogOption(0)
    win = parent.window() if parent is not None else None
    return QColorDialog.getColor(QColor(initial), win, title, opts)


def modo_archivo_suelto(parent) -> str | None:
    """🔑 Un archivo suelto del Explorador en una palabra clave: «enlazar» (no copia) o «copiar». Pregunta una vez y
    recuerda la elección (QSettings «palabras_clave/soltar_archivo»). None si cancela."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QCheckBox, QMessageBox
    st = QSettings("EditorIA", "EditorIA")
    guardado = str(st.value("palabras_clave/soltar_archivo", "") or "")
    if guardado in ("enlazar", "copiar"):
        return guardado
    box = QMessageBox(parent)
    box.setWindowTitle("Archivo suelto")
    box.setText("¿Qué hago con el archivo?")
    b_enl = box.addButton("Enlazar (no copia, recomendado para videos grandes)", QMessageBox.AcceptRole)
    b_enl.setToolTip("La palabra apunta al archivo donde está. No ocupa más disco y no se mueve nada.")
    b_cop = box.addButton("Copiar a la carpeta de la palabra", QMessageBox.AcceptRole)
    b_cop.setToolTip("Hace una copia del archivo dentro de la carpeta de Reclaimer de esa palabra.")
    box.addButton("Cancelar", QMessageBox.RejectRole).setToolTip("No añade el archivo.")
    recordar = QCheckBox("Recordar mi elección")
    box.setCheckBox(recordar)
    box.exec()
    pulsado = box.clickedButton()
    if pulsado is b_enl:
        modo = "enlazar"
    elif pulsado is b_cop:
        modo = "copiar"
    else:
        return None
    if recordar.isChecked():
        st.setValue("palabras_clave/soltar_archivo", modo)
    return modo
