"""
Timeline multipista dibujada a mano.

Interacciones:
  - Clic en la regla o en zona vacía: mover el cabezal. Clic en un hueco entre clips: seleccionarlo
    (Supr lo elimina y lo de detrás se desplaza a la izquierda, sin pisar nada).
  - Arrastrar desde una zona vacía: rectángulo de selección (Ctrl: añadir a la selección).
  - Al mover clips, se detienen al tocar otro clip: nunca lo tapan sin querer.
  - Arrastrar archivos desde Windows (videos, audios, imágenes): se añaden donde los sueltes.
  - Clic en un clip: seleccionar (Ctrl+clic: añadir a la selección). Con la selección vinculada 🔗,
    la imagen y el sonido de un video se seleccionan, mueven, recortan y cortan juntos
    (Alt+clic: solo uno de los dos, como en Resolve).
  - Arrastrar un clip: moverlo (también a otra pista del mismo tipo).
  - Arrastrar el borde de un clip: recortarlo.
  - Rueda: desplazarse.  Ctrl+rueda: zoom.  Mayús+rueda: subir/bajar pistas.
  - Clic derecho: menú contextual.
  - Arrastrar desde la biblioteca: añadir clips.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QElapsedTimer, QEvent, QLineF, QPointF, QRect, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QInputDialog, QMenu, QScrollBar, QToolTip, QWidget

from ..core import cut_check, mapping, transform
from ..core.media import PEAK_RATE
from ..core.model import (KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, ORIGIN_AI, SUG_APPLIED, SUG_PENDING, TRACK_AUDIO,
                          TRACK_TEXT, TRACK_VIDEO)
from . import help as help_ui
from .common import COLORS, EFFECT_MIME, MEDIA_MIME, SEGMENT_MIME, SUGGESTION_COLORS, fmt_tc, fmt_time
from .help import add_help_action


class TimelineWidget(QWidget):
    seek_requested = Signal(float)
    effect_dropped = Signal(str, list)
    cutout_requested = Signal(str)        # ✂ recortar sujeto con IA (lo abre la ventana principal)
    silhouette_requested = Signal(str)    # 👤 enseñar un personaje por su silueta
    dialogue_requested = Signal(list)     # 🗣 solo los diálogos de estos clips de sonido
    keywords_requested = Signal(list)     # 🔑 buscar palabras clave en estos archivos
    scene_cuts_requested = Signal(list, str)   # ✂ cortar en los cambios de escena (clips, sensibilidad)
    topics_requested = Signal(str)        # ◎ quedarme con unos temas / mandarlos a Medios (tema pulsado)    # un efecto soltado encima de un clip (y de los seleccionados con él)
    moments_requested = Signal(str, float)   # buscar material para una frase (y dónde ponerlo)
    gap_ai_requested = Signal(str, float, float, bool)   # hueco (pista, desde, hasta): sugerir / rellenar
    similar_requested = Signal(str)
    example_requested = Signal(str)       # 🎯 usar este clip como ejemplo de lo que busco
    effect_mark_clicked = Signal(int)     # ⭐ clic en una propuesta de «Mis efectos para la IA»          # buscar momentos parecidos a este clip
    impact_requested = Signal(list)          # dar más impacto visual a estos clips
    broll_range_requested = Signal(float, float)   # rehacer el B-roll de este tramo
    selection_changed = Signal(list)
    compound_requested = Signal(list)     # ⧉ cocinar estos clips en uno (lo hace la ventana principal)
    track_requested = Signal(str)         # 🎯 seguir un personaje u objeto en este clip
    suggestion_clicked = Signal(str)
    cut_issues_changed = Signal(int)      # cuántos cortes de audio pueden estar mal (líneas rojas)
    cut_issue_clicked = Signal(int)       # clic en una línea roja: índice en cut_issues

    NEW_ZONE = 26   # franja de abajo: suelta ahí algo y se crea una pista nueva
    HEADER_W = 170
    RULER_H = 46
    TOPIC_H = 18    # franja de temas (arriba de la regla)
    TRACK_H = 54
    EDGE_PX = 7
    SNAP_PX = 10
    DRAG_START_PX = 4
    NUDGE_PX = 18          # ⇆ Alt + rueda: píxeles que avanza el clip por cada paso de la rueda (según el zoom)
    NUDGE_TAU_MS = 38.0    # suavidad: cuánto tarda en alcanzar el destino (constante de tiempo)
    NUDGE_COMMIT_MS = 450  # sin girar este rato: se aplica el movimiento

    def __init__(self, ctrl, hbar: QScrollBar, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.hbar = hbar
        self.pps = 30.0          # píxeles por segundo (zoom)
        self.scroll = 0.0        # segundo que aparece en el borde izquierdo
        self.playhead = 0.0
        self.selected: set[str] = set()
        self._drag: dict | None = None
        self._seek_val: float | None = None     # seek pedido al arrastrar: se agrupa (ver _seek_soon)
        self._seek_armed = False
        self._tindex: dict | None = None        # {pista: (índice, pista)} mientras se pinta (ver paintEvent)
        self._drop: tuple[int | None, float] | None = None
        self._fx_drop: list[str] | None = None      # clips que recibirán el efecto que arrastras
        self._pix_cache: dict[tuple[str, int], QPixmap] = {}
        from .filmstrip import Filmstrips
        self.filmstrips = Filmstrips(self)        # tira de fotogramas a lo largo de cada clip de video
        self.filmstrips.ready.connect(lambda _m: self.update())
        # Sugerencias de la IA dibujadas sobre la timeline (se recalculan al cambiar el proyecto)
        self._sug_spans: list[tuple[int, float, float, str, str, str]] = []  # pista, ini, fin, tipo, id, texto
        self._cut_marks: list[tuple[int, float, str]] = []                   # pista, momento, texto
        self.highlight_sug = ""
        self._hover_topic = ""
        self.gap: tuple[str, float, float] | None = None   # hueco seleccionado: (pista, inicio, fin)
        # 🎚 Canales (pistas) seleccionados, como en Resolve: dividir (S) y juntar (Ctrl++) trabajan en ellos, no en un
        # trozo concreto. Clic en un clip o en su pista = su canal; vacío = toda la línea de tiempo
        self.channels: set[str] = set()
        self.sel_trans: str | None = None   # transición seleccionada (id del clip de la DERECHA del corte)
        self.sel_fx: str | None = None      # ✦ pastilla «fx» seleccionada (id del clip): Supr = quitar sus efectos
        self._fx_chips: dict[str, QRectF] = {}
        self._trans_preview: tuple[str, float] | None = None
        self.tool = "select"      # select | blade (cuchilla) | trim (recorte avanzado, como el modo Trim de Resolve)
        self.curves = False       # «〰 Curvas»: ver y editar las curvas de volumen (audio) y opacidad (video)
        self.preview_regions: list[tuple[float, float]] = []   # lo que «Eliminar silencio» va a quitar
        self.preview_voice: list[tuple[float, float]] = []     # ⚠ …y donde eso cae sobre tu voz (en rojo)
        self.preview_tracks: list[str] | None = None           # pistas que se cortan (None = todas, como antes)
        self.effect_marks: list[tuple[float, str]] = []         # ⭐ propuestas de efectos (tiempo, texto)
        self.effect_current = -1
        self.hint_marks: list[tuple[float, str]] = []           # 🎬 «Dijiste…»: (tiempo, nombre) (no se guarda)
        self.hint_selected = -1                                 # 🔑 banderita elegida con clic (-1 = ninguna)
        self.snapping = True      # imán
        self._rhythm_pts: dict = {}   # golpes de la música para el imán (se recalculan al cambiar algo)
        # Selección vinculada y forma de onda (se recuerdan entre sesiones)
        st = QSettings("EditorIA", "EditorIA")
        self.snap_rhythm = str(st.value("timeline/iman_ritmo", "true")).lower() == "true"
        self.linked = str(st.value("timeline/vinculado", "true")).lower() == "true"
        self.wave_style = str(st.value("timeline/onda_estilo", "espejo"))      # espejo | rectificada | contorno | no
        self.wave_db = str(st.value("timeline/onda_db", "false")).lower() == "true"
        self.wave_silence = str(st.value("timeline/onda_silencios", "true")).lower() == "true"
        self.wave_words = str(st.value("timeline/onda_palabras", "true")).lower() == "true"
        self.audio_h = int(st.value("timeline/alto_audio", 54))
        self.video_h = int(st.value("timeline/alto_video", 54))
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setProperty("own_menu", True)
        ctrl.project_changed.connect(self._on_project_changed)
        ctrl.project_replaced.connect(self._on_replaced)
        ctrl.media_changed.connect(self.update)
        ctrl.rhythm_changed.connect(self._on_rhythm)
        # Cortes de audio que pueden estar mal (líneas rojas): se recalculan un poco después de cada cambio
        self.cut_issues: list[dict] = []
        self._cut_timer = QTimer(self)
        self._cut_timer.setSingleShot(True)
        self._cut_timer.setInterval(400)
        self._cut_timer.timeout.connect(self.refresh_cut_issues)
        ctrl.project_changed.connect(self._schedule_cut_check)
        ctrl.media_changed.connect(self._schedule_cut_check)
        ctrl.transcript_changed.connect(lambda _m: self._schedule_cut_check())
        ctrl.peaks_changed.connect(self.update)                  # llegó una forma de onda: se dibuja
        ctrl.peaks_changed.connect(self._schedule_cut_check)     # y los cortes se revisan con su voz
        self._rueda_fin = QTimer(self)            # tras la última tanda de pasos de rueda: repintado completo
        self._rueda_fin.setSingleShot(True)
        self._rueda_fin.setInterval(150)
        self._rueda_fin.timeout.connect(self.update)
        # ⇆ Alt + rueda sobre un clip elegido: se desliza en la línea de tiempo (mismo tamaño), suave (ver _nudge_*)
        self._nudge: dict | None = None
        self._nudge_anim = QTimer(self)               # animación: el clip va hacia donde le lleva la rueda
        self._nudge_anim.setTimerType(Qt.PreciseTimer)
        self._nudge_anim.setInterval(8)
        self._nudge_anim.timeout.connect(self._nudge_step)
        self._nudge_fin = QTimer(self)                # al dejar de girar: se aplica (un solo Ctrl+Z)
        self._nudge_fin.setSingleShot(True)
        self._nudge_fin.setInterval(self.NUDGE_COMMIT_MS)
        self._nudge_fin.timeout.connect(self._nudge_commit)
        self._nudge_prev_armed = False
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)   # Qt desplaza píxeles (QWidget.scroll) solo si es opaco
        hbar.valueChanged.connect(self._on_hbar)
        self._on_project_changed()

    # ------------------------------------------------------- coordenadas
    def x_for(self, t: float) -> float:
        return self.HEADER_W + (t - self.scroll) * self.pps

    def t_for(self, x: float) -> float:
        return self.scroll + (x - self.HEADER_W) / self.pps

    # ------------------------------------------------ regla fija al desplazar en vertical
    def _vt(self) -> int:
        """Parte más alta visible de este widget (px): la regla, la franja de temas y el cabezal se quedan ahí."""
        return max(0, -self.y())

    def _rmap(self, pt: QPointF) -> QPointF:
        """Punto del ratón en coordenadas de la regla: lo que cae en la regla fija (vt..vt+RULER_H) pasa a 0..RULER_H,
        así las comprobaciones de «y < RULER_H» de siempre siguen valiendo."""
        vt = self._vt()
        if vt and vt <= pt.y() < vt + self.RULER_H:
            return QPointF(pt.x(), pt.y() - vt)
        return pt

    def _scroll_area(self):
        from PySide6.QtWidgets import QScrollArea
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        return w

    def _hook_scroll(self):
        """Al desplazar en vertical, repintar (la regla se mueve con la vista). Se conecta una sola vez."""
        if self.__dict__.get("_vsb_hooked"):
            return
        sa = self._scroll_area()
        if sa is not None:
            self._vsb_hooked = True
            sa.verticalScrollBar().valueChanged.connect(lambda _v: self.update())

    def showEvent(self, e):
        super().showEvent(e)
        self._hook_scroll()

    ui_k = 1.0       # tamaño de letra de la línea de tiempo (Ventana → Tamaño de letra → Global)

    def set_text_scale(self, k: float):
        """Letra más grande en la línea de tiempo: también crecen cabeceras, regla y pistas para que quepa."""
        self.ui_k = k
        self.HEADER_W = int(round(170 * k))
        self.RULER_H = int(round(46 * k))
        self.TOPIC_H = int(round(18 * k))
        f = QFont("Segoe UI")
        f.setPointSizeF(9 * k)
        self.setFont(f)
        self._pix_cache.clear()
        if hasattr(self, "_update_scrollbar"):
            self._update_scrollbar()
        self.updateGeometry()
        self.update()

    def _f(self, pt: float, bold: bool = False, family: str | None = None) -> QFont:
        # ⚡ Se crean una vez (antes, una por clip en cada repintado)
        key = (pt, bold, family, self.ui_k, self.font().key())
        cache = self.__dict__.setdefault("_font_cache", {})
        f = cache.get(key)
        if f is None:
            f = QFont(family) if family else QFont(self.font())
            f.setPointSizeF(pt * self.ui_k)
            if bold:
                f.setBold(True)
            if len(cache) > 64:
                cache.clear()
            cache[key] = f
        return QFont(f)

    def set_effect_marks(self, marks, current: int = -1):
        """⭐ Las propuestas de «Mis efectos para la IA»: rombos dorados sobre las pistas."""
        self.effect_marks = list(marks or [])
        self.effect_current = current
        self.update()

    def effect_mark_at(self, pos: QPointF) -> int:
        vt = self._vt()     # (pos en coordenadas reales: los rombos van justo debajo de la regla fija)
        if not self.effect_marks or not (vt + self.RULER_H - 2 <= pos.y() <= vt + self.RULER_H + 16 * self.ui_k):
            return -1
        best = min(range(len(self.effect_marks)), key=lambda i: abs(self.x_for(self.effect_marks[i][0]) - pos.x()))
        return best if abs(self.x_for(self.effect_marks[best][0]) - pos.x()) <= 7 else -1

    def set_hint_marks(self, marks):
        """🎬 Marcas de «Dijiste…»: banderita en la regla y línea discontinua. [] = quitarlas. No se guardan."""
        prev = self.hint_marks[self.hint_selected] if 0 <= getattr(self, "hint_selected", -1) < len(
            self.hint_marks) else None
        self.hint_marks = [(float(t), str(s)) for t, s in (marks or [])]
        # 🔑 la palabra clave elegida sigue elegida si sigue ahí (si no, ninguna)
        self.hint_selected = self.hint_marks.index(prev) if prev in self.hint_marks else -1
        self.update()

    def select_hint(self, i: int):
        """🔑 Elige la banderita i (clic en ella): la biblioteca puede «Añadir en la palabra clave seleccionada»."""
        self.hint_selected = i if 0 <= i < len(self.hint_marks) else -1
        self.update()

    @staticmethod
    def hint_word(label: str) -> str:
        """El texto de la palabra sin el icono de su origen («🎬 PlayStation» → «PlayStation»)."""
        s = str(label).strip()
        for pre in ("🎬", "🔎"):
            if s.startswith(pre):
                s = s[len(pre):].strip()
        return s

    def keyword_target(self, playhead: float | None = None, near: float = 0.5):
        """🔑 La palabra clave a la que añadir: la banderita elegida; si no hay ninguna elegida, la que esté justo en
        el cabezal (±near s; al hacer clic en una banderita el cabezal va ahí). None si no hay ninguna.
        Devuelve {"word", "t", "times"}: «times» = todas las marcas con ese mismo texto (sin repetir instantes)."""
        i = getattr(self, "hint_selected", -1)
        if not (0 <= i < len(self.hint_marks)):
            i = -1
            if playhead is not None and self.hint_marks:
                j = min(range(len(self.hint_marks)), key=lambda k: abs(self.hint_marks[k][0] - playhead))
                if abs(self.hint_marks[j][0] - playhead) <= near:
                    i = j
        if i < 0:
            return None
        t, label = self.hint_marks[i]
        word = self.hint_word(label)
        key = word.casefold()
        times: list[float] = []
        for tt, ll in sorted(self.hint_marks):
            if self.hint_word(ll).casefold() == key and not any(abs(tt - x) < 0.05 for x in times):
                times.append(tt)          # (la misma aparición puede venir de 🎬 Clips y de 🔎 Buscar a la vez)
        return {"word": word, "t": t, "times": times}

    def _hint_rect(self, i: int):
        """Rectángulo de la banderita i en la regla; None si no se ve."""
        from PySide6.QtGui import QFontMetrics
        t, label = self.hint_marks[i]
        x = self.x_for(t)
        if x < self.HEADER_W or x > self.width():
            return None
        w = QFontMetrics(self._f(8)).horizontalAdvance(label) + int(10 * self.ui_k)
        return QRectF(x + 1, self.TOPIC_H + 1, w, int(15 * self.ui_k))

    def hint_mark_at(self, pos: QPointF) -> int:
        if not self.hint_marks or not (self.TOPIC_H <= pos.y() <= self.TOPIC_H + 16 * self.ui_k):
            return -1
        for i in range(len(self.hint_marks)):
            r = self._hint_rect(i)
            if r is not None and r.contains(pos):
                return i
        return -1

    def set_preview_regions(self, regions, voice=None, tracks=None):
        self.preview_regions = list(regions or [])
        self.preview_voice = list(voice or [])
        self.preview_tracks = None if tracks is None else list(tracks)
        self.update()

    def set_curves(self, on: bool):
        self.curves = bool(on)
        self.update()

    # ---------------------------------------------------------------- curvas de volumen / opacidad
    def _curve_kind(self, c) -> str | None:
        tr = self.ctrl.project.track(c.track_id)
        if c.text is not None or tr is None:
            return None
        if tr.kind == TRACK_AUDIO:
            return "vol"
        return "op" if tr.kind == TRACK_VIDEO else None

    def _curve_area(self, c, r: QRectF) -> QRectF:
        top = r.top() + 15 * self.ui_k + 3
        return QRectF(r.left(), top, r.width(), max(6.0, r.bottom() - 3 - top))

    @staticmethod
    def _db_norm(g: float) -> float:
        """Volumen → altura (0–1) en una escala de dB de -40 a +6 (como en Resolve)."""
        db = 20 * math.log10(max(g, 1e-4))
        return min(1.0, max(0.0, (db + 40) / 46))

    @staticmethod
    def _norm_db(y: float) -> float:
        db = y * 46 - 40
        return 0.0 if y <= 0.001 else 10 ** (db / 20)

    def _curve_value(self, c, kind: str, local: float) -> float:
        from ..core import curves as K
        img = self.ctrl.project.media_of(c) is not None and self.ctrl.project.media_of(c).kind == KIND_IMAGE
        s = K.src_time(c, local, img)
        if kind == "vol":
            return self._db_norm(c.volume * K.value_at(c.vol_kf, s))
        return max(0.0, min(1.0, c.opacity * K.value_at(c.op_kf, s)))

    def _kf_local(self, c, s: float) -> float | None:
        """De un punto (segundo del archivo) a su instante dentro del clip."""
        m = self.ctrl.project.media_of(c)
        if m is not None and m.kind == KIND_IMAGE:
            return s
        if c.speed <= 0:
            return None
        return (c.source_in + c.src_len - s) / c.speed if c.reverse else (s - c.source_in) / c.speed

    def _paint_curve(self, p: QPainter, c, r: QRectF):
        kind = self._curve_kind(c)
        if kind is None:
            return
        kf = c.vol_kf if kind == "vol" else c.op_kf
        if not (self.curves or kf):
            return
        a = self._curve_area(c, r)
        x0, x1 = max(r.left(), float(self.HEADER_W)), min(r.right(), float(self.width()))
        if x1 <= x0:
            return
        pts = []
        step = 3.0
        x = x0
        while x <= x1:
            v = self._curve_value(c, kind, (x - r.left()) / self.pps)
            pts.append(QPointF(x, a.bottom() - v * a.height()))
            x += step
        col = QColor("#ffd166") if kind == "vol" else QColor("#7fd1ff")
        p.setPen(QPen(col, 1.6 if self.curves else 1.0))
        p.drawPolyline(QPolygonF(pts))
        for k in kf:
            loc = self._kf_local(c, k["t"])
            if loc is None or not (-1e-6 <= loc <= c.duration + 1e-6):
                continue
            xk = r.left() + loc * self.pps
            yk = a.bottom() - self._curve_value(c, kind, loc) * a.height()
            p.setBrush(col)
            p.setPen(QPen(QColor("black"), 1))
            p.drawEllipse(QPointF(xk, yk), 4, 4)

    def _curve_hit(self, c, pos: QPointF):
        """(«punto», índice) si el clic cae en un punto; («línea», None) si cae cerca de la línea."""
        kind = self._curve_kind(c)
        if kind is None:
            return None, None
        r = self.clip_rect(c)
        a = self._curve_area(c, r)
        kf = c.vol_kf if kind == "vol" else c.op_kf
        for i, k in enumerate(kf):
            loc = self._kf_local(c, k["t"])
            if loc is None:
                continue
            xk = r.left() + loc * self.pps
            yk = a.bottom() - self._curve_value(c, kind, loc) * a.height()
            if abs(pos.x() - xk) <= 6 and abs(pos.y() - yk) <= 6:
                return "point", i
        y_line = a.bottom() - self._curve_value(c, kind, (pos.x() - r.left()) / self.pps) * a.height()
        if abs(pos.y() - y_line) <= 7 and a.top() - 4 <= pos.y() <= a.bottom() + 4:
            return "line", None
        return None, None

    def _curve_level_at(self, c, kind: str, pos: QPointF) -> float:
        """Valor de la curva (sin el nivel general) que corresponde a la altura del ratón."""
        a = self._curve_area(c, self.clip_rect(c))
        y = min(1.0, max(0.0, (a.bottom() - pos.y()) / max(a.height(), 1.0)))
        if kind == "vol":
            return min(2.0, self._norm_db(y) / max(c.volume, 1e-4))
        return min(1.0, y / max(c.opacity, 1e-4))

    def _curve_press(self, clip, pos: QPointF, e) -> bool:
        """Clic con «〰 Curvas»: punto = arrastrarlo (clic derecho = borrarlo); línea = punto nuevo
        (Mayús+arrastrar la línea = subir o bajar toda la curva)."""
        from ..core import curves as K
        what, idx = self._curve_hit(clip, pos)
        if what is None:
            return False
        kind = self._curve_kind(clip)
        kf = [dict(k) for k in (clip.vol_kf if kind == "vol" else clip.op_kf)]
        m = self.ctrl.project.media_of(clip)
        img = m is not None and m.kind == KIND_IMAGE
        if e.button() == Qt.RightButton:
            if what == "point":
                del kf[idx]
                self.ctrl.set_curve(clip.id, kind, kf, text="Quitar punto de la curva")
            return True
        if what == "line" and (e.modifiers() & Qt.ShiftModifier):
            self._drag = {"type": "curve_level", "clip": clip.id, "kind": kind}
            return True
        if what == "line":
            local = (pos.x() - self.clip_rect(clip).left()) / self.pps
            s = K.src_time(clip, local, img)
            kf = K.upsert(kf, s, self._curve_level_at(clip, kind, pos))
            self.ctrl.set_curve(clip.id, kind, kf, text="Punto en la curva")
            clip = self.ctrl.project.clips[clip.id]
            kf = clip.vol_kf if kind == "vol" else clip.op_kf
            idx = min(range(len(kf)), key=lambda i: abs(kf[i]["t"] - s))
        self._drag = {"type": "curve_point", "clip": clip.id, "kind": kind, "idx": idx, "img": img}
        return True

    def _curve_move(self, d, pos: QPointF):
        from ..core import curves as K
        c = self.ctrl.project.clips.get(d["clip"])
        if c is None:
            return
        kind = d["kind"]
        if d["type"] == "curve_level":
            a = self._curve_area(c, self.clip_rect(c))
            y = min(1.0, max(0.0, (a.bottom() - pos.y()) / max(a.height(), 1.0)))
            level = self._norm_db(y) if kind == "vol" else y
            self.ctrl.set_curve(c.id, kind, level=level, text="Nivel de la curva")
            return
        kf = [dict(k) for k in (c.vol_kf if kind == "vol" else c.op_kf)]
        if not (0 <= d["idx"] < len(kf)):
            return
        local = min(max((pos.x() - self.clip_rect(c).left()) / self.pps, 0.0), c.duration)
        s = K.src_time(c, local, d["img"])
        lo = kf[d["idx"] - 1]["t"] + 0.01 if d["idx"] > 0 else -1e9
        hi = kf[d["idx"] + 1]["t"] - 0.01 if d["idx"] + 1 < len(kf) else 1e9
        kf[d["idx"]] = {"t": round(min(max(s, lo), hi), 4), "v": round(self._curve_level_at(c, kind, pos), 4)}
        self.ctrl.set_curve(c.id, kind, kf, text="Mover punto de la curva")

    # ---- ⊞ Vistas: «Principal» (tu montaje) y «Composición» (sus pistas ⊞ Composición / ⊞ Fondo, con el audio para
    # cuadrar el tiempo). Es el MISMO proyecto (el visor y la exportación lo usan todo); solo cambia lo que ves aquí.
    COMP_ROLES = ("comp", "fondo")

    def has_comp(self) -> bool:
        return any(t.role in self.COMP_ROLES for t in self.ctrl.project.tracks)

    def _shown(self) -> list[bool]:
        """Qué pistas se ven en la vista actual. Se calcula una vez por cambio (track_h se llama miles de veces por
        dibujo): se borra al cambiar el proyecto o la vista."""
        out = self.__dict__.get("_shown_cache")
        tracks = self.ctrl.project.tracks
        if out is not None and len(out) == len(tracks):
            return out
        comp = [t.role in self.COMP_ROLES for t in tracks]
        mode = (getattr(self, "_view", "main") if any(comp) else "all")
        if mode == "all":
            out = [True] * len(tracks)
        elif mode == "comp":
            out = [c or t.kind == TRACK_AUDIO for c, t in zip(comp, tracks)]
        else:
            out = [not c for c in comp]
        self._shown_cache = out
        return out

    def view_mode(self) -> str:
        return getattr(self, "_view", "main") if self.has_comp() else "all"

    def set_view(self, mode: str):
        self._view = mode if mode in ("main", "comp") else "main"
        self._ty_cache = None
        self._shown_cache = None
        self.update()
        cb = getattr(self, "view_changed_cb", None)
        if cb:
            cb(self._view)

    def track_shown(self, i: int) -> bool:
        sh = self._shown()
        return 0 <= i < len(sh) and sh[i]

    def track_h(self, i: int) -> float:
        """Alto de la pista i (las de audio pueden ser más altas para ver mejor la onda). 0 = no se ve en esta vista."""
        tracks = self.ctrl.project.tracks
        sh = self.__dict__.get("_shown_cache") or self._shown()
        if not (0 <= i < len(sh) and sh[i]):
            return 0.0
        h = self.audio_h if 0 <= i < len(tracks) and tracks[i].kind == TRACK_AUDIO else self.video_h
        return h * max(1.0, self.ui_k)

    def track_y(self, i: int) -> float:
        cache = getattr(self, "_ty_cache", None)
        if cache is not None and 0 <= i < len(cache):
            return cache[i]
        return self.RULER_H + sum(self.track_h(k) for k in range(i))

    def track_index_at(self, y: float) -> int | None:
        if y < self.RULER_H:
            return None
        top = self.RULER_H
        for i in range(len(self.ctrl.project.tracks)):
            h = self.track_h(i)
            if top <= y < top + h:
                return i
            top += h
        return None

    def _ti(self, track_id: str) -> int:
        """Índice de una pista; mientras se dibuja usa la tabla de paintEvent (sin recorrer todas las pistas)."""
        if self._tindex is not None and track_id in self._tindex:
            return self._tindex[track_id][0]
        return self.ctrl.project.track_index(track_id)

    def _track_obj(self, track_id: str):
        """La pista (objeto); igual que _ti, con la tabla de paintEvent cuando hay una."""
        if self._tindex is not None and track_id in self._tindex:
            return self._tindex[track_id][1]
        return self.ctrl.project.track(track_id)

    def clip_rect(self, c, start: float | None = None, track_i: int | None = None,
                  duration: float | None = None) -> QRectF:
        i = self._ti(c.track_id) if track_i is None else track_i
        s = c.start if start is None else start
        d = c.duration if duration is None else duration
        x1, x2 = self.x_for(s), self.x_for(s + d)
        return QRectF(x1, self.track_y(i) + 3, max(2.0, x2 - x1), self.track_h(i) - 6)

    # ------------------------------------------------------------ estado
    def _on_replaced(self):
        self._shown_cache = None
        self.selected.clear()
        self.selection_changed.emit([])
        self.scroll = 0.0
        self.fit()

    def _on_project_changed(self):
        self._shown_cache = None
        if getattr(self, "_nudge", None) is not None:   # otro cambio a mitad del ⇆ Alt + rueda: se descarta
            self._nudge_cancel()
        self._rhythm_pts.clear()
        if self.sel_trans is not None:   # la transición seleccionada ya no existe
            from ..core import transitions as _TR
            c = self.ctrl.project.clips.get(self.sel_trans)
            if c is None or _TR.of(c) is None:
                self.sel_trans = None
        if self.gap is not None:   # el hueco seleccionado ya no existe (o cambió)
            tr = self.ctrl.project.track(self.gap[0])
            g = self.ctrl.gap_at(tr.id, (self.gap[1] + self.gap[2]) / 2) if tr else None
            if g is None or abs(g[0] - self.gap[1]) > 1e-3 or abs(g[1] - self.gap[2]) > 1e-3:
                self.gap = None
        n = len(self.ctrl.project.tracks)
        self.setMinimumHeight(int(self.track_y(n)) + self.NEW_ZONE + 4)
        before = set(self.selected)
        self.selected &= set(self.ctrl.project.clips)
        if before != self.selected:
            self.selection_changed.emit(sorted(self.selected))
        self._compute_suggestions()
        self._update_scrollbar()
        self.update()

    def _compute_suggestions(self):
        p = self.ctrl.project
        spans, marks, cache = [], [], {}
        for s in p.suggestions:
            if s.status not in (SUG_PENDING, SUG_APPLIED):
                continue
            clips = cache.setdefault(s.media_id, mapping.clips_of_media(p, s.media_id))
            if not clips:
                continue
            if s.status == SUG_PENDING:
                for c, ta, tb in mapping.map_range(p, s.media_id, s.start, s.end, clips):
                    spans.append((p.track_index(c.track_id), ta, tb, s.kind, s.id, s.label))
            elif s.applied_start is not None:  # solo los cortes tienen marca ✂
                found = mapping.find_cut(p, s.media_id, s.applied_start, s.applied_end, clips)
                if found:
                    c = found[0] or found[1]
                    marks.append((p.track_index(c.track_id), found[2],
                                  f"✂ IA quitó: {s.label} ({s.applied_end - s.applied_start:.2f} s)"))
        self._sug_spans, self._cut_marks = spans, marks

    def set_highlight_suggestion(self, sid: str):
        self.highlight_sug = sid
        for i, ta, _tb, _k, s_id, _l in self._sug_spans:
            if s_id == sid:
                x = self.x_for(ta)
                if not (self.HEADER_W <= x <= self.width() - 40):
                    self.scroll = max(0.0, ta - (self.width() - self.HEADER_W) * 0.3 / self.pps)
                    self._update_scrollbar()
                break
        self.update()

    def suggestion_at(self, pos: QPointF):
        i = self.track_index_at(pos.y())
        if i is None:
            return None
        t = self.t_for(pos.x())
        for ti, ta, tb, _k, sid, label in self._sug_spans:
            if ti == i and ta <= t <= tb:
                return sid, label
        for ti, tc, label in self._cut_marks:
            if ti == i and abs(self.x_for(tc) - pos.x()) <= 4:
                return None, label
        return None

    # ------------------------------------------- cortes de audio que pueden estar mal (líneas rojas)
    def _schedule_cut_check(self, *_a):
        self._cut_timer.start()

    def refresh_cut_issues(self) -> int:
        """Recalcula los cortes de audio que pueden estar mal (ver core/cut_check.py). Devuelve cuántos son."""
        self._cut_timer.stop()
        peaks = self.ctrl.peaks
        new = cut_check.check(self.ctrl.project, lambda mid: peaks.get(mid))

        def sig(lst):
            return [(i["track_id"], round(i["t"], 4), i["key"], tuple(i["reasons"])) for i in lst]

        if sig(new) != sig(self.cut_issues):
            self.cut_issues = new
            self.cut_issues_changed.emit(len(new))
            self.update()
        return len(new)

    def cut_issue_at(self, pos: QPointF) -> int | None:
        """Índice del aviso de corte bajo el ratón (a ±5 px de su línea roja o de su triángulo de la regla)."""
        if not self.cut_issues:
            return None
        proj = self.ctrl.project
        for k, iss in enumerate(self.cut_issues):
            if abs(pos.x() - self.x_for(iss["t"])) > 5:
                continue
            ti = proj.track_index(iss["track_id"])
            if ti < 0 or self.track_h(ti) <= 0:
                continue
            if self.RULER_H - 16 <= pos.y() <= self.track_y(ti) + self.track_h(ti):
                return k
        return None

    def _paint_cut_issues(self, p: QPainter):
        """Línea roja a toda la altura de su pista de audio (y un poco por encima) + triángulo en la regla."""
        proj = self.ctrl.project
        W = self.width()
        red = QColor("#ff3b30")
        for iss in self.cut_issues:
            x = self.x_for(iss["t"])
            if x < self.HEADER_W - 2 or x > W + 2:
                continue
            ti = proj.track_index(iss["track_id"])
            if ti < 0 or self.track_h(ti) <= 0:
                continue
            y = self.track_y(ti)
            p.setPen(QPen(red, 2))
            p.drawLine(QLineF(x, y - 5, x, y + self.track_h(ti)))
            # (el triángulo de arriba va en la regla, ver _paint_ruler)

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            ci = self.cut_issue_at(self._rmap(QPointF(e.pos())))
            if ci is not None:
                iss = self.cut_issues[ci]
                QToolTip.showText(e.globalPos(), "Corte de audio que puede estar mal:\n• "
                                  + "\n• ".join(iss["reasons"]) + "\nClic = revisar y ajustar este corte", self)
                return True
        return super().event(e)

    def set_tool(self, tool: str):
        self.tool = tool
        self.setCursor(Qt.SplitHCursor if tool == "blade" else Qt.ArrowCursor)

    def _on_rhythm(self):
        self._rhythm_pts.clear()
        self.update()

    def set_snap_rhythm(self, on: bool):
        """El imán también pega los clips a los golpes y al drop de la música."""
        self.snap_rhythm = bool(on)
        self._rhythm_pts.clear()
        QSettings("EditorIA", "EditorIA").setValue("timeline/iman_ritmo", "true" if on else "false")

    def set_snapping(self, on: bool):
        self.snapping = bool(on)

    def set_linked(self, on: bool):
        self.linked = on
        QSettings("EditorIA", "EditorIA").setValue("timeline/vinculado", on)
        self.update()

    def set_wave(self, **opts):
        """Opciones de la forma de onda: style, db, silence, audio_h."""
        st = QSettings("EditorIA", "EditorIA")
        if "style" in opts:
            self.wave_style = opts["style"]
            st.setValue("timeline/onda_estilo", self.wave_style)
        if "db" in opts:
            self.wave_db = bool(opts["db"])
            st.setValue("timeline/onda_db", self.wave_db)
        if "silence" in opts:
            self.wave_silence = bool(opts["silence"])
            st.setValue("timeline/onda_silencios", self.wave_silence)
        if "words" in opts:
            self.wave_words = bool(opts["words"])
            st.setValue("timeline/onda_palabras", self.wave_words)
        if "audio_h" in opts:
            self.audio_h = int(opts["audio_h"])
            st.setValue("timeline/alto_audio", self.audio_h)
            self._on_project_changed()
        if "video_h" in opts:
            self.video_h = int(opts["video_h"])
            st.setValue("timeline/alto_video", self.video_h)
            self._on_project_changed()
        self.update()

    def _with_links(self, ids, alt: bool = False) -> list[str]:
        """Con la selección vinculada, la imagen y el sonido van juntos (Alt: solo el clip)."""
        return self.ctrl.linked_ids(ids) if (self.linked and not alt) else list(ids)

    def _dest_track(self, c, d) -> int:
        """Pista a la que va c al arrastrar: solo cambian de pista los clips del mismo tipo de pista
        que el que agarraste (su sonido vinculado se queda en su pista de audio)."""
        proj = self.ctrl.project
        i = proj.track_index(c.track_id)
        if d.get("dtrack") and proj.tracks[i].kind == d.get("kind0"):
            return i + d["dtrack"]
        return i

    def _clips_in_rect(self, rect: QRectF) -> list[str]:
        """Clips que toca el rectángulo de selección (de cualquier tipo: video, audio, texto…)."""
        out = []
        for c in self.ctrl.project.clips.values():
            if self.clip_rect(c).intersects(rect):
                out.append(c.id)
        return out

    def _safe_dt(self, d: dict, dt: float, dtrack: int) -> float:
        """Desplazamiento más cercano al pedido con el que ningún clip movido tapa a otro:
        al arrastrar, los clips se detienen al tocar el siguiente (como un imán)."""
        proj = self.ctrl.project
        ids = set(d["ids"])
        moving = [proj.clips[i] for i in d["ids"] if i in proj.clips]
        dd = dict(d, dtrack=dtrack)
        dest = {c.id: proj.tracks[self._dest_track(c, dd)].id for c in moving}
        others: dict[str, list] = {}
        for tid in set(dest.values()):
            others[tid] = [o for o in proj.clips_on(tid) if o.id not in ids]

        def ok(x: float) -> bool:
            for c in moving:
                a, b = c.start + x, c.end + x
                if a < -1e-6:
                    return False
                if any(o.start < b - 1e-6 and o.end > a + 1e-6 for o in others[dest[c.id]]):
                    return False
            return True
        if ok(dt):
            return dt
        cands = [0.0]
        for c in moving:
            for o in others[dest[c.id]]:
                cands += [o.end - c.start, o.start - c.end]
        cands = sorted((x for x in cands if ok(x)), key=lambda x: abs(x - dt))
        return cands[0] if cands else d.get("dt", 0.0)

    def set_selection(self, ids):
        had_extra = self.sel_trans is not None or self.sel_fx is not None or (ids and self.gap is not None)
        self.sel_trans = None
        self.sel_fx = None
        if ids:
            self.gap = None
        old = self.selected
        self.selected = set(ids) & set(self.ctrl.project.clips)
        self.selection_changed.emit(sorted(self.selected))
        changed = old ^ self.selected
        if had_extra or len(changed) > 80:
            self.update()
            return
        # Solo se repintan los clips que cambian (con cientos de clips, seleccionar era repintarlo todo)
        from PySide6.QtGui import QRegion
        reg = QRegion()
        p = self.ctrl.project
        for cid in changed:
            c = p.clips.get(cid)
            if c is not None and p.track_index(c.track_id) >= 0:
                reg += self.clip_rect(c).adjusted(-4, -4, 4, 4).toAlignedRect()
        if not reg.isEmpty():
            self.update(reg)

    def select_all(self):
        self.set_selection(self.ctrl.project.clips.keys())

    def set_playhead(self, t: float, follow: bool = False):
        old_x = self.x_for(self.playhead)
        self.playhead = t
        scrolled = False
        if follow:
            x = self.x_for(t)
            if x > self.width() - 40 or x < self.HEADER_W:
                self.scroll = max(0.0, t - (self.width() - self.HEADER_W) * 0.15 / self.pps)
                self._update_scrollbar()
                scrolled = True
        if scrolled:
            self.update()
            return
        # Solo cambió el cabezal: se repinta su franja (antes y ahora) y los medidores de las pistas, no toda la
        # línea de tiempo (con cientos de clips, eso hacía ir lento todo al reproducir)
        from PySide6.QtCore import QRect
        new_x = self.x_for(t)
        w = int(16 * max(1.0, self.ui_k))
        for x in {int(old_x), int(new_x)}:
            self.update(QRect(x - w, 0, 2 * w, self.height()))
        self._update_meters()

    def _meter_rect(self, i: int):
        """Zona del vúmetro de la pista i en su cabecera (solo hay fondo de cabecera alrededor)."""
        y, th = self.track_y(i), self.track_h(i)
        return QRectF(self.HEADER_W - 7, y + 3, 5, th - 6).toAlignedRect()

    def _update_meters(self):
        """⚡ Al mover el cabezal: solo se repintan los vúmetros, y solo si cambió su nivel (antes, toda la columna de
        cabeceras —nombres, botones, iconos— en cada paso del cabezal)."""
        from ..core import meters
        try:
            levels = meters.track_levels(self.ctrl.project, self.ctrl.peaks, self.playhead)
        except Exception:  # noqa: BLE001 - un medidor nunca debe molestar
            levels = {}
        q = {k: round(meters.to_db(v)) for k, v in levels.items()}
        if q == self.__dict__.get("_meter_q"):
            return
        self._meter_q = q
        for i in range(len(self.ctrl.project.tracks)):
            if self.track_h(i) > 20:
                self.update(self._meter_rect(i))

    # -------------------------------------------------------- zoom/scroll
    def _content_seconds(self) -> float:
        return max(self.ctrl.project.duration() + 30.0, 60.0)

    def _update_scrollbar(self):
        view_w = max(1, self.width() - self.HEADER_W)
        total_px = int(self._content_seconds() * self.pps)
        maximum = max(0, total_px - view_w)
        self.scroll = min(self.scroll, maximum / self.pps)
        self.hbar.blockSignals(True)
        self.hbar.setRange(0, maximum)
        self.hbar.setPageStep(view_w)
        self.hbar.setSingleStep(max(10, view_w // 20))
        self.hbar.setValue(int(self.scroll * self.pps))
        self.hbar.blockSignals(False)

    def _on_hbar(self, v: int):
        """Rueda y barra de desplazamiento. Si el paso es de píxeles enteros, se mueven los píxeles ya dibujados
        (QWidget.scroll) y solo se repintan la regla y los bordes; si no (arrastres, vistas previas, paso enorme),
        repintado completo. Al parar la rueda, un repintado completo por si quedó algo sin actualizar."""
        new = v / self.pps
        dxf = (self.scroll - new) * self.pps
        self.scroll = new
        dx = int(round(dxf))
        W, H = self.width(), self.height()
        self._rueda_fin.start()
        if (abs(dxf - dx) > 1e-3 or dx == 0 or abs(dx) >= W - self.HEADER_W - 24 or self._drag is not None
                or self._nudge is not None
                or self._drop is not None or self._fx_drop or self.preview_regions or self.preview_voice):
            self.update()
            return
        area = QRect(self.HEADER_W, 0, W - self.HEADER_W, H)
        QWidget.scroll(self, dx, 0, area)          # (self.scroll es un float: tapa el método de QWidget)
        m = 12
        self.update(QRect(self.HEADER_W, self._vt(), W - self.HEADER_W, self.RULER_H + 1))   # la regla fija
        self.update(QRect(self.HEADER_W, 0, m, H))
        self.update(QRect(W - m, 0, m, H))
        for cid in list(self._fx_chips):            # las pastillas «fx» ya dibujadas se desplazan con su clip
            self._fx_chips[cid] = self._fx_chips[cid].translated(dx, 0)

    def zoom(self, factor: float, anchor_x: float | None = None):
        if anchor_x is None:
            anchor_x = self.x_for(self.playhead)
            if not (self.HEADER_W <= anchor_x <= self.width()):
                anchor_x = self.HEADER_W + (self.width() - self.HEADER_W) / 2
        t_anchor = self.t_for(anchor_x)
        self.pps = min(max(self.pps * factor, 0.5), 2000.0)
        self.scroll = max(0.0, t_anchor - (anchor_x - self.HEADER_W) / self.pps)
        self._update_scrollbar()
        self.update()

    def fit(self):
        dur = max(self.ctrl.project.duration(), 10.0)
        self.pps = min(max((self.width() - self.HEADER_W - 30) / dur, 0.5), 2000.0)
        self.scroll = 0.0
        self._update_scrollbar()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scrollbar()

    def wheelEvent(self, e):
        dy = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(1.25 ** (dy / 120), e.position().x())
        elif e.modifiers() & Qt.ShiftModifier:
            e.ignore()  # que lo gestione el área de scroll vertical
            return
        elif e.modifiers() & Qt.AltModifier:     # Alt + rueda: las pistas suben / bajan (scroll vertical)
            if self._nudge_wheel(e, dy):        # … salvo encima de un clip elegido: el clip se desliza
                e.accept()
                return
            sa = self._scroll_area()
            if sa is None:
                e.ignore()
                return
            vb = sa.verticalScrollBar()
            vb.setValue(vb.value() - int(dy))    # dy: el eje que traiga la rueda (en Windows, Alt la pasa a X)
        else:
            self.hbar.setValue(self.hbar.value() - int(dy))
        e.accept()

    # ------------------------------------------------------------- ⇆ Alt + rueda: deslizar el clip elegido
    def _nudge_wheel(self, e, dy: float) -> bool:
        """⇆ Alt + rueda encima de un clip elegido: los clips elegidos (con su sonido vinculado) se deslizan hacia
        atrás o hacia delante sin cambiar de tamaño. Suave (se anima hacia el destino), se detiene al tocar otro clip,
        se pega un instante a las palabras clave y al cabezal, y el visor enseña el cuadro en vivo. Al dejar de girar
        (o al soltar Alt) se aplica en un solo paso de Ctrl+Z. False = no es el caso (la rueda hace lo de siempre)."""
        if not dy:
            return False
        if self._nudge is None:
            if self._drag is not None:
                return False
            pos = self._rmap(e.position())
            if pos.y() < self.RULER_H:
                return False
            c, _zone = self.clip_at(pos)
            if c is None or c.id not in self.selected or not self._nudge_begin(c):
                return False
        n = self._nudge
        paso = -float(dy) / 120.0 * self.NUDGE_PX / max(self.pps, 1e-6)   # rueda arriba = antes (como el scroll)
        n["target"] = min(max(n["target"] + paso, n["lo"]), n["hi"])
        self._nudge_fin.start()
        if not self._nudge_anim.isActive():
            n["clock"].restart()
            self._nudge_anim.start()
        return True

    def _nudge_begin(self, anchor) -> bool:
        proj = self.ctrl.project
        ids = [i for i in sorted(self.selected) if i in proj.clips]
        clips = [proj.clips[i] for i in ids]
        if not clips:
            return False
        for c in clips:
            tr = proj.track(c.track_id)
            if c.locked or (tr is not None and tr.locked):
                self.ctrl.message.emit("🔒 Ese clip (o su pista) está bloqueado: no se puede mover.")
                return False
        sel = set(ids)
        lo, hi = -min(c.start for c in clips), math.inf      # nunca antes del segundo 0
        for c in clips:                                      # ni encima de otro clip: se detiene al tocarlo
            for o in proj.clips_on(c.track_id):
                if o.id in sel:
                    continue
                if o.end <= c.start + 1e-6:
                    lo = max(lo, o.end - c.start)
                elif o.start >= c.end - 1e-6:
                    hi = min(hi, o.start - c.end)
        lo, hi = min(lo, 0.0), max(hi, 0.0)
        p0 = float(self.playhead)
        mags = sorted({float(t) for t, _l in self.hint_marks} | {p0})    # 🔑 palabras clave y el cabezal
        d = {"type": "move", "active": True, "nudge": True, "ids": ids, "anchor": anchor.id,
             "dt": 0.0, "dtrack": 0, "kind0": None}
        clock = QElapsedTimer()
        clock.start()
        self._nudge = {"d": d, "ids": ids, "a0": anchor.start, "a1": anchor.end, "lo": lo, "hi": hi,
                       "target": 0.0, "cur": 0.0, "mags": np.asarray(mags, dtype=float), "p0": p0,
                       "clock": clock, "previewed": False}
        return True

    def _nudge_snap(self, x: float) -> float:
        """Imán suave: si el principio o el final del clip pasa cerca (SNAP_PX) de una palabra clave o del cabezal,
        se queda ahí hasta que la rueda lo saca."""
        n = self._nudge
        arr = n["mags"]
        if not self.snapping or not len(arr):
            return x
        best = None
        for edge in (n["a0"], n["a1"]):
            t = edge + x
            i = int(np.searchsorted(arr, t))
            for j in (i - 1, i):
                if 0 <= j < len(arr):
                    dpx = abs(float(arr[j]) - t) * self.pps
                    if dpx <= self.SNAP_PX and (best is None or dpx < best[0]):
                        best = (dpx, float(arr[j]) - edge)
        return best[1] if best else x

    def _nudge_step(self):
        """Un fotograma de la animación (cada ~8 ms): se acerca al destino con suavizado exponencial, que no depende
        de lo que tarde cada paso. Solo se repinta lo que cambia (ver _update_drag)."""
        n = self._nudge
        if n is None:
            self._nudge_anim.stop()
            return
        ms = max(1, n["clock"].restart())
        k = 1.0 - math.exp(-ms / self.NUDGE_TAU_MS)
        n["cur"] += (n["target"] - n["cur"]) * k
        if abs(n["target"] - n["cur"]) * self.pps < 0.3:
            n["cur"] = n["target"]
        dt = min(max(self._nudge_snap(n["cur"]), n["lo"]), n["hi"])
        d = n["d"]
        if abs(dt - d["dt"]) * self.pps >= 0.05:
            d["dt"] = dt
            self._update_drag(d)
            self._nudge_preview()
        if n["cur"] == n["target"]:
            self._nudge_anim.stop()

    def _nudge_preview(self):
        if not self._nudge_prev_armed:
            self._nudge_prev_armed = True
            QTimer.singleShot(24, self._nudge_flush_preview)

    def _nudge_time(self) -> float:
        """Qué instante enseña el visor: el cabezal si el clip (ya deslizado) pasa por él; si no, su borde más
        cercano al cabezal (su primer cuadro si queda a la derecha, el último si queda a la izquierda)."""
        n = self._nudge
        a, b = n["a0"] + n["d"]["dt"], n["a1"] + n["d"]["dt"]
        p0 = n["p0"]
        if a <= p0 < b:
            return p0
        fr = 1.0 / max(1.0, float(self.ctrl.project.fps or 30))
        return a if p0 < a else max(a, b - fr)

    def _nudge_flush_preview(self):
        """El visor enseña el cuadro en vivo: los clips se ponen en su sitio nuevo SOLO durante la llamada al visor
        (síncrona, en este mismo hilo) y vuelven enseguida; nada más ve el cambio hasta que se aplica."""
        self._nudge_prev_armed = False
        n = self._nudge
        if n is None:
            return
        eng = getattr(self.window(), "engine", None)
        if eng is not None and getattr(eng, "playing", False):
            return                                   # reproduciendo: no se salta el cabezal
        proj = self.ctrl.project
        dt = n["d"]["dt"]
        orig: dict[str, float] = {}
        try:
            for cid in n["ids"]:
                c = proj.clips.get(cid)
                if c is not None:
                    orig[cid] = c.start
                    c.start = c.start + dt
            n["previewed"] = True
            self.seek_requested.emit(self._nudge_time())
        finally:
            for cid, s0 in orig.items():
                c = proj.clips.get(cid)
                if c is not None:
                    c.start = s0

    def _nudge_stop(self) -> dict | None:
        n, self._nudge = self._nudge, None
        self._nudge_anim.stop()
        self._nudge_fin.stop()
        return n

    def _nudge_cancel(self):
        n = self._nudge_stop()
        if n is not None:
            self.update()

    def _nudge_commit(self):
        """Aplica el deslizamiento (un solo Ctrl+Z) y el visor vuelve al cabezal de antes."""
        n = self._nudge_stop()
        if n is None:
            return
        proj = self.ctrl.project
        dt = n["d"]["dt"]
        if abs(dt) > 1e-6:
            moves = {cid: (proj.clips[cid].start + dt, proj.clips[cid].track_id)
                     for cid in n["ids"] if cid in proj.clips}
            if moves:
                self.ctrl.move_clips(moves)
        self.update()
        if n.get("previewed"):
            self.seek_requested.emit(n["p0"])

    # ------------------------------------------------------------- dibujo
    def paintEvent(self, _e):
        if _e.rect().contains(self.rect()):      # solo en repintado completo: en uno parcial, las demás siguen
            self._fx_chips = {}
        self._hook_scroll()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        vtop = self._vt()          # la regla, la franja de temas y el cabezal se pintan en la parte visible
        proj = self.ctrl.project
        self._tindex = {t_.id: (k, t_) for k, t_ in enumerate(proj.tracks)}   # ⚡ pistas por id (una vez por dibujo)
        p.fillRect(self.rect(), COLORS["bg"])

        # Fondos de pista
        for i, tr in enumerate(proj.tracks):
            th = self.track_h(i)
            if th <= 0:
                continue
            y = self.track_y(i)
            bg = QColor("#20242b") if tr.kind != TRACK_AUDIO else QColor("#1e2420")
            p.fillRect(QRectF(self.HEADER_W, y, W - self.HEADER_W, th), bg)
            if tr.id in self.channels:              # 🎚 canal seleccionado
                p.fillRect(QRectF(self.HEADER_W, y, W - self.HEADER_W, th), QColor(255, 255, 255, 13))
            if tr.locked:
                p.fillRect(QRectF(self.HEADER_W, y, W - self.HEADER_W, th),
                           QBrush(QColor(217, 164, 0, 40), Qt.BDiagPattern))
            p.setPen(COLORS["line"])
            p.drawLine(QLineF(0, y + th, W, y + th))

        # Clips
        p.save()
        p.setClipRect(QRectF(self.HEADER_W, self.RULER_H, W - self.HEADER_W, H - self.RULER_H))
        d = self._nudge["d"] if self._nudge is not None else self._drag
        moving = d and d["type"] == "move" and d.get("active")
        # Rendimiento con muchos clips: cuántos clips comparten cada vínculo (una vez, no clip contra clip) y
        # solo se dibujan los que tocan la zona que hay que repintar (al moverse el cabezal es una franja)
        from collections import Counter
        self._links = Counter(c.link for c in proj.clips.values() if c.link)
        reg = _e.region()             # la zona EXACTA a repintar (no el rectángulo que la engloba)
        self._ty_cache = None
        ys, y = [], float(self.RULER_H)
        for k in range(len(proj.tracks)):     # la altura de cada pista, una vez por dibujo
            ys.append(y)
            y += self.track_h(k)
        self._ty_cache = ys
        hidden = {t.id for k, t in enumerate(proj.tracks) if self.track_h(k) <= 0}
        # ⚡ Antes de calcular nada, fuera los clips que caen fuera (en tiempo) de la zona a repintar: con cientos de
        # clips y el zoom de trabajo solo se ven unos pocos
        br = reg.boundingRect()
        self._paint_x = (br.left() - 2, br.right() + 2)     # las ondas solo se dibujan en esta franja
        t_lo = self.t_for(br.left() - 4) - 0.5 / max(self.pps, 1e-6)
        t_hi = self.t_for(br.right() + 4) + 0.5 / max(self.pps, 1e-6)
        for c in proj.clips.values():
            if c.track_id in hidden:
                continue
            if (c.start > t_hi or c.start + c.duration < t_lo) and not (moving and c.id in d["ids"]):
                continue
            rc = self.clip_rect(c)
            if not reg.intersects(rc.toAlignedRect().adjusted(-2, -2, 2, 2)):
                if not (moving and c.id in d["ids"]):
                    continue
            if moving and c.id in d["ids"]:
                if not d.get("nudge"):           # (⇆ Alt + rueda: el clip se desliza, no deja copia atenuada)
                    self._paint_clip(p, c, self.clip_rect(c), dim=True)
            elif d and d["type"] == "trim" and d.get("active") and (c.id == d["clip"] or c.id in d.get("partners", [])):
                continue                              # se dibuja abajo, ya recortado
            else:
                self._paint_clip(p, c, self.clip_rect(c))
        if moving:
            for cid in d["ids"]:
                c = proj.clips.get(cid)
                if c:
                    self._paint_clip(p, c, self.clip_rect(c, c.start + d["dt"], self._dest_track(c, d)),
                                     ghost=not d.get("nudge"))
        if d and d["type"] == "trim" and d.get("active"):
            for cid in [d["clip"]] + d.get("partners", []):
                c = proj.clips.get(cid)
                if c:
                    s, e = (d["new_start"], c.end) if d["edge"] == "left" else (c.start, d["new_end"])
                    if e - s > 1e-4:
                        self._paint_clip(p, self._trimmed(c, s, e), self.clip_rect(c, s, duration=e - s))
        # Recortes avanzados: cómo quedará
        if d and d.get("active") and d["type"] in ("ripple", "roll", "slide", "slip"):
            if d["type"] == "ripple":
                c = proj.clips.get(d["clip"])
                if c:
                    if d["edge"] == "left":
                        r = self.clip_rect(c, c.start, duration=c.end - d["t"])
                    else:
                        r = self.clip_rect(c, c.start, duration=d["t"] - c.start)
                    p.setPen(QPen(QColor("#ffd166"), 2, Qt.DashLine))
                    p.setBrush(QColor(255, 209, 102, 40))
                    p.drawRoundedRect(r, 4, 4)
                    p.drawText(r.adjusted(4, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "ripple")
            elif d["type"] == "roll":
                x = self.x_for(d["t"])
                c = proj.clips.get(d["right"])
                i = proj.track_index(c.track_id) if c else -1
                if i >= 0:
                    p.setPen(QPen(QColor("#ffd166"), 3))
                    p.drawLine(QLineF(x, self.track_y(i), x, self.track_y(i) + self.track_h(i)))
            elif d["type"] == "slide":
                c = proj.clips.get(d["clip"])
                if c:
                    r = self.clip_rect(c, c.start + d["dt"])
                    p.setPen(QPen(QColor("#ffd166"), 2, Qt.DashLine))
                    p.setBrush(QColor(255, 209, 102, 40))
                    p.drawRoundedRect(r, 4, 4)
            elif d["type"] == "slip":
                c = proj.clips.get(d["clip"])
                if c:
                    r = self.clip_rect(c)
                    p.setPen(QColor("#ffd166"))
                    p.drawText(r.adjusted(4, 16, 0, 0), Qt.AlignLeft | Qt.AlignTop, f"slip {d['dt']:+.2f} s")
        # Transiciones: una pajarita sobre el corte (ancho = su duración)
        from ..core import transitions as TR
        for i, tr in enumerate(proj.tracks):
            if tr.kind != TRACK_VIDEO or self.track_h(i) <= 0:
                continue
            y = self.track_y(i)
            for left, right, t in TR.pairs(proj, tr.id):
                xc = self.x_for(right.start)
                dur = t["dur"]
                if self._trans_preview and self._trans_preview[0] == right.id:
                    dur = self._trans_preview[1]
                hw = max(7.0, dur * self.pps / 2)
                if xc + hw < self.HEADER_W or xc - hw > W:
                    continue
                r = QRectF(xc - hw, y + 17, 2 * hw, self.track_h(i) - 21)
                sel = right.id == self.sel_trans
                p.setPen(QPen(COLORS["selection"], 2.5) if sel else QPen(QColor(255, 255, 255, 200), 1))
                p.setBrush(QColor(236, 58, 50, 140) if sel else QColor(90, 100, 120, 170))
                p.drawRoundedRect(r, 3, 3)
                if sel:          # asas en los bordes: arrastrar = más larga / más corta
                    p.fillRect(QRectF(r.left() - 1, r.center().y() - 7, 3, 14), QColor("white"))
                    p.fillRect(QRectF(r.right() - 2, r.center().y() - 7, 3, 14), QColor("white"))
                if self._trans_preview and self._trans_preview[0] == right.id:
                    p.setPen(QColor("#ffd2b8"))
                    p.drawText(QRectF(r.center().x() - 40, r.top() - 15, 80, 14), Qt.AlignCenter, f"{dur:.2f} s")
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                p.drawLine(QLineF(r.topLeft(), r.bottomRight()))
                p.drawLine(QLineF(r.bottomLeft(), r.topRight()))
                if r.width() > 60:
                    p.setPen(QColor("white"))
                    p.drawText(r.adjusted(2, 0, -2, 0), Qt.AlignCenter, TR.NAMES.get(t["type"], ""))
        # Sugerencias pendientes de la IA (zonas de color) y cortes aplicados (✂)
        for i, ta, tb, kind, sid, _label in self._sug_spans:
            x1, x2 = self.x_for(ta), self.x_for(tb)
            if x2 < self.HEADER_W or x1 > W:
                continue
            col = QColor(SUGGESTION_COLORS.get(kind, QColor("#888")))
            r = QRectF(x1, self.track_y(i) + 18, max(2.0, x2 - x1), self.track_h(i) - 21)
            fill = QColor(col)
            fill.setAlpha(110 if sid == self.highlight_sug else 60)
            p.fillRect(r, fill)
            p.setPen(QPen(QColor("white") if sid == self.highlight_sug else col, 2 if sid == self.highlight_sug else 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        for i, tc, _label in self._cut_marks:
            x = self.x_for(tc)
            if x < self.HEADER_W or x > W:
                continue
            y = self.track_y(i)
            p.setPen(QPen(COLORS["ai"], 2))
            p.drawLine(QLineF(x, y + 16, x, y + self.track_h(i) - 3))
            p.setPen(Qt.NoPen)
            p.setBrush(COLORS["ai"])
            p.drawPolygon(QPolygonF([QPointF(x - 5, y + 16), QPointF(x + 5, y + 16), QPointF(x, y + 23)]))
        n_tr = len(proj.tracks)
        zy = self.track_y(n_tr)
        if self._drop is not None:      # mientras arrastras: la franja para una pista nueva
            hot = self._drop[0] == "new"
            zr = QRectF(self.HEADER_W + 4, zy + 3, W - self.HEADER_W - 8, self.NEW_ZONE - 6)
            p.fillRect(zr, QColor(232, 116, 47, 70 if hot else 22))
            p.setPen(QPen(COLORS["selection"] if hot else QColor("#6b6f78"), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(zr)
            p.setPen(QColor("#ffd2b8") if hot else QColor("#9a9ea8"))
            p.drawText(zr, Qt.AlignCenter, "➕ Suelta aquí para crear una pista nueva")
        if self._drop and isinstance(self._drop[0], int):
            i, t = self._drop
            x = self.x_for(t)
            p.fillRect(QRectF(x, self.track_y(i) + 3, 80, self.track_h(i) - 6), QColor(79, 140, 255, 90))
            p.setPen(QPen(COLORS["accent"], 2))
            p.drawLine(QLineF(x, self.track_y(i), x, self.track_y(i) + self.track_h(i)))
        if self._fx_drop:              # arrastrando un efecto: estos clips lo recibirán
            p.setBrush(QColor(120, 220, 160, 45))
            p.setPen(QPen(QColor("#7be0a8"), 2))
            for cid in self._fx_drop:
                c = proj.clips.get(cid)
                gi = proj.track_index(c.track_id) if c else -1
                if gi >= 0:
                    r = QRectF(self.x_for(c.start), self.track_y(gi) + 1, max(3.0, (c.end - c.start) * self.pps),
                               self.track_h(gi) - 2)
                    p.drawRect(r)
            p.setBrush(Qt.NoBrush)
        # Hueco seleccionado
        if self.gap is not None:
            tid, ga, gb = self.gap
            gi = proj.track_index(tid)
            if gi >= 0:
                r = QRectF(self.x_for(ga), self.track_y(gi) + 3, max(2.0, (gb - ga) * self.pps), self.track_h(gi) - 6)
                p.fillRect(r, QColor(232, 116, 47, 55))
                p.setPen(QPen(COLORS["selection"], 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
                if r.width() > 70:
                    p.setPen(QColor("#ffd2b8"))
                    p.drawText(r, Qt.AlignCenter, "hueco · Supr")
        # Rectángulo de selección
        if d and d["type"] == "marquee" and "x1" in d:
            r = QRectF(QPointF(d["x0"], d["y0"]), QPointF(d["x1"], d["y1"])).normalized()
            p.fillRect(r, QColor(255, 255, 255, 28))
            p.setPen(QPen(QColor(255, 255, 255, 170), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
        # Líneas de marcadores
        for m in proj.markers:
            x = self.x_for(m.time)
            c = QColor(m.color)
            c.setAlpha(70 if m.kind != "topic" else 45)
            p.setPen(QPen(c, 1, Qt.DashLine))
            p.drawLine(QLineF(x, self.RULER_H, x, H))
        # ⭐ Propuestas de efectos: rombo dorado y línea fina
        for i, (t, _label) in enumerate(self.effect_marks):
            x = self.x_for(t)
            if x < self.HEADER_W or x > W:
                continue
            cur = i == self.effect_current
            p.setPen(QPen(QColor(242, 179, 61, 200 if cur else 90), 1.5 if cur else 1, Qt.DotLine))
            p.drawLine(QLineF(x, self.RULER_H, x, H))
            s = (7 if cur else 5) * self.ui_k
            y = vtop + self.RULER_H + 7 * self.ui_k
            p.setPen(QPen(QColor("#1b1b1b"), 1))
            p.setBrush(QColor("#ffd166") if cur else QColor("#f2b33d"))
            p.drawPolygon(QPolygonF([QPointF(x, y - s), QPointF(x + s, y), QPointF(x, y + s), QPointF(x - s, y)]))
        # 🎬 Marcas de «Dijiste…»: línea fina discontinua cian (solo las que se ven)
        for t, _label in self.hint_marks:
            x = self.x_for(t)
            if x < self.HEADER_W or x > W:
                continue
            p.setPen(QPen(QColor(64, 200, 230, 170), 1, Qt.DashLine))
            p.drawLine(QLineF(x, self.RULER_H, x, H))
        # Tramo marcado con I / O: un velo suave sobre las pistas
        rng = proj.marked_range()
        if rng:
            xa, xb = self.x_for(rng[0]), self.x_for(rng[1])
            p.fillRect(QRectF(xa, self.RULER_H, xb - xa, H - self.RULER_H), QColor(255, 255, 255, 13))
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for xm, t in ((xa, proj.mark_in), (xb, proj.mark_out)):
                if t is not None:
                    p.drawLine(QLineF(xm, self.RULER_H, xm, H))
        d = self._drag
        if d and d["type"] == "topic_edge" and d.get("active"):
            x = self.x_for(d["new_t"])
            p.setPen(QPen(QColor("white"), 2))
            p.drawLine(QLineF(x, vtop, x, H))
        p.restore()
        self._paint_cut_issues(p)           # líneas rojas: cortes de audio que pueden estar mal

        # Cabeceras: nada si no se repinta esa zona; solo los vúmetros si es lo único que toca (al mover el cabezal)
        from PySide6.QtCore import QRect as _QR
        from PySide6.QtGui import QRegion as _QRg
        hreg = reg.intersected(_QR(0, 0, int(self.HEADER_W), H))
        mreg = _QRg()
        for i in range(len(proj.tracks)):
            if self.track_h(i) > 20:
                mreg = mreg.united(self._meter_rect(i))
        meters_only = not hreg.isEmpty() and hreg.subtracted(mreg).isEmpty()
        if hreg.isEmpty():
            pass
        elif meters_only:
            self._paint_meters(p)
        else:
            self._paint_headers(p)
        self._paint_grip(p)
        p.save()                             # la regla (con sus temas, marcas y corchetes) va fija arriba de lo visible
        p.translate(0, vtop)
        self._paint_ruler(p)
        p.restore()
        self._paint_preview(p, W, H)     # «✂ Eliminar silencio»: se pinta encima de la regla y los clips

        # Cabezal (su triángulo, en la regla fija)
        x = self.x_for(self.playhead)
        if x >= self.HEADER_W:
            p.setPen(QPen(COLORS["playhead"], 2))
            p.drawLine(QLineF(x, vtop, x, H))
            p.setBrush(COLORS["playhead"])
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(x - 6, vtop), QPointF(x + 6, vtop), QPointF(x, vtop + 9)]))
        p.end()
        self._ty_cache = None
        self._tindex = None

    def _paint_preview(self, p: QPainter, W: float, H: float):
        """Vista previa de «✂ Eliminar silencio» (como DaVinci Resolve): en las pistas que se cortan, el tramo que se
        va a quitar se oscurece solo donde hay clip y lleva bordes finos; el resto se queda normal. Las demás pistas
        solo llevan una marca fina arriba, en la regla, porque también se moverán. Sin preview_tracks (llamadas
        antiguas), oscurece todo el alto."""
        if not self.preview_regions and not self.preview_voice:
            return
        proj = self.ctrl.project
        vx0, vx1 = float(self.HEADER_W), float(W)
        black = QColor(0, 0, 0, 150)
        edge = QColor(255, 255, 255, 170)
        red = QColor(229, 65, 60, 150)

        def span(a, b):
            """Tramo [a, b] en píxeles, recortado a la vista y de al menos 1 px; None si queda fuera."""
            xa, xb = self.x_for(a), self.x_for(b)
            if xb < vx0 or xa > vx1:
                return None
            x1, x2 = max(xa, vx0), min(xb, vx1)
            return x1, max(1.0, x2 - x1)

        def edge_line(x, y0, y1):
            if vx0 <= x <= vx1:
                p.setPen(QPen(edge, 1))
                p.drawLine(QLineF(x, y0, x, y1))

        if self.preview_tracks is None:                       # llamada sin pistas: todo el alto
            top = float(self.RULER_H)
            for a, b in self.preview_regions:
                sp = span(a, b)
                if sp is None:
                    continue
                p.fillRect(QRectF(sp[0], top, sp[1], H - top), black)
                edge_line(self.x_for(a), top, H)
                edge_line(self.x_for(b), top, H)
            for a, b in self.preview_voice:
                sp = span(a, b)
                if sp is not None:
                    p.fillRect(QRectF(sp[0], top, max(2.0, sp[1]), H - top), red)
            return

        cut = set(self.preview_tracks)
        for k, tr in enumerate(proj.tracks):                  # pistas que se cortan: oscurecer solo donde hay clip
            if tr.id not in cut or self.track_h(k) <= 0:
                continue
            y, th = self.track_y(k), self.track_h(k)
            for a, b in self.preview_regions:
                if span(a, b) is None:
                    continue
                for c in proj.clips_on(tr.id):
                    s, e = max(c.start, a), min(c.end, b)
                    if e <= s:
                        continue
                    sp = span(s, e)
                    if sp is None:
                        continue
                    p.fillRect(QRectF(sp[0], y, sp[1], th), black)
                    if s == a:
                        edge_line(self.x_for(a), y, y + th)
                    if e == b:
                        edge_line(self.x_for(b), y, y + th)
            for a, b in self.preview_voice:                   # ⚠ se cortaría voz: en rojo, solo en esta banda
                sp = span(a, b)
                if sp is not None:
                    p.fillRect(QRectF(sp[0], y, max(2.0, sp[1]), th), red)
        if any(t.id not in cut for t in proj.tracks):         # las demás pistas: marca fina arriba, en la regla
            for a, b in self.preview_regions:
                sp = span(a, b)
                if sp is not None:
                    p.fillRect(QRectF(sp[0], self._vt(), sp[1], 2), QColor(220, 220, 220, 110))

    def _paint_ruler(self, p: QPainter):
        W = self.width()
        T = self.TOPIC_H
        p.fillRect(QRectF(0, 0, W, self.RULER_H), COLORS["panel"])
        p.fillRect(QRectF(0, 0, W, T), QColor("#1d2026"))
        p.setPen(COLORS["line"])
        p.drawLine(QLineF(0, self.RULER_H - 0.5, W, self.RULER_H - 0.5))
        step = next((s for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200)
                     if s * self.pps >= 95), 1800)
        minor = step / 5
        f = self._f(8)
        p.setFont(f)
        # ⚡ Solo la franja que se repinta (al mover el cabezal, unos pocos píxeles): con margen a la izquierda para
        # que los números que empiezan antes y entran en la franja salgan enteros
        lo, hi = getattr(self, "_paint_x", (0.0, float(W)))
        t = math.floor(max(self.scroll, self.t_for(lo - 110)) / minor) * minor
        end = min(self.t_for(W), self.t_for(hi + 4))
        k = round(t / minor)
        while t <= end:
            x = self.x_for(t)
            if x >= self.HEADER_W:
                if k % 5 == 0:
                    p.setPen(COLORS["text_dim"])
                    p.drawLine(QLineF(x, self.RULER_H - 12, x, self.RULER_H))
                    label = fmt_tc(t, self.ctrl.project.fps)
                    p.drawText(QPointF(x + 3, T + 12), label)
                elif minor * self.pps >= 6:
                    p.setPen(COLORS["line"])
                    p.drawLine(QLineF(x, self.RULER_H - 5, x, self.RULER_H))
            k += 1
            t = k * minor
        # Temas de la narración: bandas de color arriba
        bold = QFont(f)
        bold.setBold(True)
        p.setFont(bold)
        for m in self.ctrl.project.markers:
            if m.kind != "topic" or m.end is None:
                continue
            x1, x2 = max(self.x_for(m.time), float(self.HEADER_W)), min(self.x_for(m.end), float(W))
            if x2 <= x1:
                continue
            c = QColor(m.color)
            fill = QColor(c)
            fill.setAlpha(150 if m.id == self._hover_topic else 105)
            r = QRectF(x1 + 1, 1, x2 - x1 - 2, T - 2)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor("white"))
            label = ("✎ " if m.origin != "ai" else "") + m.label
            p.drawText(r.adjusted(5, 0, -3, 0), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(label, Qt.ElideRight, int(r.width() - 8)))
        p.setFont(f)
        # Marcadores puntuales
        for m in self.ctrl.project.markers:
            if m.kind == "topic":
                continue
            x = self.x_for(m.time)
            if x < self.HEADER_W - 2 or x > W:
                continue
            color = QColor(m.color)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawPolygon(QPolygonF([QPointF(x, self.RULER_H), QPointF(x - 5, self.RULER_H - 9),
                                     QPointF(x - 5, T + 14), QPointF(x + 5, T + 14),
                                     QPointF(x + 5, self.RULER_H - 9)]))
            if m.label:
                p.setPen(color)
                p.drawText(QPointF(x + 8, self.RULER_H - 4), m.label)
        # Entrada y salida (I / O): banda en la regla con corchetes
        proj = self.ctrl.project
        rng = proj.marked_range()
        if rng:
            xa, xb = max(self.x_for(rng[0]), float(self.HEADER_W)), min(self.x_for(rng[1]), float(W))
            if xb > xa:
                y0 = self.RULER_H - 9
                p.fillRect(QRectF(xa, y0, xb - xa, 8), QColor(200, 205, 215, 85))
                p.setPen(QPen(QColor("#e8e8e8"), 2))
                for xm, t, sgn in ((self.x_for(rng[0]), proj.mark_in, 1), (self.x_for(rng[1]), proj.mark_out, -1)):
                    if t is not None and self.HEADER_W <= xm <= W:
                        p.drawLine(QLineF(xm, y0 - 3, xm, self.RULER_H))
                        p.drawLine(QLineF(xm, y0 - 3, xm + 5 * sgn, y0 - 3))
        # 🎬 Banderitas de «Dijiste…» (clic = ir ahí)
        for i in range(len(self.hint_marks)):
            r = self._hint_rect(i)
            if r is None:
                continue
            sel = i == self.hint_selected            # 🔑 la elegida: más clara y con borde blanco
            p.setPen(QPen(QColor("#ffffff"), 2) if sel else Qt.NoPen)
            p.setBrush(QColor(150, 235, 255, 255) if sel else QColor(64, 200, 230, 235))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QColor("#0b1f24"))
            p.drawText(r, Qt.AlignCenter, self.hint_marks[i][1])
        # ✂ Cortes de audio que pueden estar mal: triángulo rojo en la regla (la línea va en las pistas)
        for iss in self.cut_issues:
            x = self.x_for(iss["t"])
            if x < self.HEADER_W - 2 or x > W + 2:
                continue
            ti = proj.track_index(iss["track_id"])
            if ti < 0 or self.track_h(ti) <= 0:
                continue
            top = self.RULER_H - 14
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ff3b30"))
            p.drawPolygon(QPolygonF([QPointF(x - 6, top), QPointF(x + 6, top), QPointF(x, top + 11)]))
        # Esquina de cabecera
        p.fillRect(QRectF(0, 0, self.HEADER_W, self.RULER_H), COLORS["panel"])
        p.setPen(COLORS["text_dim"])
        p.drawText(QRectF(10, 0, self.HEADER_W - 10, T), Qt.AlignVCenter, "Temas")
        self._place_corner()

    def _corner_buttons(self):
        """«➕ Pista», «🎞 ↕» (alto de las pistas de video) y «🔊 ↕» (alto de las de audio), encima de los nombres."""
        if getattr(self, "_corner", None) is not None:
            return self._corner
        from PySide6.QtWidgets import QToolButton
        add = QToolButton(self)
        add.setText("➕ Pista")
        add.setToolTip("Agregar una pista a la línea de tiempo\n(también: arrastra algo a la franja de abajo)")
        add.setPopupMode(QToolButton.InstantPopup)
        madd = QMenu(add)
        madd.addAction("🎞 Pista de video", lambda: self._add_track(TRACK_VIDEO))
        madd.addAction("🔊 Pista de audio", lambda: self._add_track(TRACK_AUDIO))
        add.setMenu(madd)
        self._size_btn = {}
        out = [add]
        for key, icon, what in (("video_h", "🎞", "video"), ("audio_h", "🔊", "audio")):
            b = _SizeButton(self, key, f"{icon} ↕", what)
            self._size_btn[key] = b
            out.append(b)
        for b in out:
            b.setAutoRaise(True)
            b.setStyleSheet("QToolButton { color: #c9ccd3; padding: 1px 3px; } QToolButton::menu-indicator { width: 0; }")
        self._corner = tuple(out)
        return self._corner

    def _place_corner(self):
        add, bv, ba = self._corner_buttons()
        T = self.TOPIC_H
        h = max(18, int(self.RULER_H - T - 4))
        W = self.HEADER_W - 8
        wa = int(W * 0.40)
        ws = int((W - wa - 4) / 2)
        y = self._vt() + T + 2          # los botones de la esquina van con la regla fija
        add.setGeometry(4, y, wa, h)
        bv.setGeometry(6 + wa, y, ws, h)
        ba.setGeometry(8 + wa + ws, y, ws, h)
        for b in (add, bv, ba):
            if not b.isVisible():
                b.show()

    def _add_track(self, kind: str):
        self.ctrl.add_track(kind)
        win = self.window()
        if hasattr(win, "_ensure_timeline_size"):      # que se vean todas las pistas
            win._ensure_timeline_size()

    def _set_track_size(self, key: str, h: int, fit: bool = True):
        self.set_wave(**{key: max(28, min(160, int(h)))})
        b = getattr(self, "_size_btn", {}).get(key)
        if b is not None:
            b.sync()
        if not fit:            # mientras arrastras la barrita: solo las pistas (la ventana se ajusta al soltar)
            return
        win = self.window()
        if hasattr(win, "_sync_wave_menu"):            # el menú Ver › alto de las pistas, al día
            win._sync_wave_menu()
        if hasattr(win, "_ensure_timeline_size"):
            win._ensure_timeline_size()

    def set_channels(self, ids, mode: str = "set"):
        """🎚 Elige los canales: "set" (solo estos), "add" (añadir) o "toggle" (quitar/poner)."""
        ids = set(ids)
        if mode == "add":
            ids |= self.channels
        elif mode == "toggle":
            ids ^= self.channels
        if ids != self.channels:
            self.channels = ids
            self.update()

    def channel_ids(self) -> list[str]:
        """Los canales seleccionados que siguen existiendo (en orden); vacío = toda la línea de tiempo."""
        tracks = self.ctrl.project.tracks
        self.channels &= {t.id for t in tracks}
        return [t.id for t in tracks if t.id in self.channels]

    @staticmethod
    def _trimmed(c, s: float, e: float):
        """El clip como quedará recortado a [s, e]: lo de dentro NO se estira; por el borde que mueves desaparece (o
        aparece) el contenido, como en Resolve."""
        if abs(s - c.start) < 1e-9 and abs(e - c.end) < 1e-9:
            return c
        src = c.source_in + ((c.end - e) if c.reverse else (s - c.start)) * c.speed
        return replace(c, start=s, duration=max(1e-3, e - s), source_in=max(0.0, src))

    def _header_buttons(self, i: int) -> tuple[QRectF, QRectF]:
        k = self.ui_k
        b = 22 * k
        y = self.track_y(i) + min(self.track_h(i) - b, 16 * k)
        return (QRectF(self.HEADER_W - 58 * k, y, b, b), QRectF(self.HEADER_W - 32 * k, y, b, b))

    def _solo_rect(self, i: int) -> QRectF:
        k = self.ui_k
        b = 22 * k
        y = self.track_y(i) + min(self.track_h(i) - b, 16 * k)
        return QRectF(self.HEADER_W - 84 * k, y, b, b)

    def track_badge(self, i: int) -> tuple[str, str]:
        """Insignia y nombre como en Resolve: ('V1', 'Video'), ('A1', 'Narración'), ('T1', 'Textos')."""
        tracks = self.ctrl.project.tracks
        tr = tracks[i]
        same = [t.id for t in tracks if t.kind == tr.kind]
        if tr.kind == TRACK_VIDEO:
            n = len(same) - same.index(tr.id)          # V1 es la de abajo
            letter, default = "V", "Video"
        elif tr.kind == TRACK_AUDIO:
            n = same.index(tr.id) + 1
            letter, default = "A", "Audio"
        else:
            n = len(same) - same.index(tr.id)
            letter, default = "T", "Textos"
        name = tr.name.split("·", 1)[1].strip() if "·" in tr.name else (
            default if re.fullmatch(r"[VAT]\d*", tr.name.strip()) else tr.name)
        return f"{letter}{n}", name

    H_MIN, H_MAX = 28, 160          # alto de las pistas (igual que los botones 🎞↕ / 🔊↕)

    def _grip_rect(self) -> QRectF:
        """↕ La barrita de la izquierda de las pistas: arrastrar arriba = pistas más grandes; abajo = más pequeñas."""
        return QRectF(0, self.RULER_H, max(7.0, 7 * self.ui_k), max(0.0, self.height() - self.RULER_H))

    def _paint_grip(self, p: QPainter):
        g = self._grip_rect()
        if g.height() < 20:
            return
        hot = getattr(self, "_drag", None) and self._drag.get("type") == "track_zoom" or getattr(self, "_grip_hover", False)
        p.fillRect(g, QColor("#1b1b1e"))
        p.fillRect(QRectF(g.right() - 1, g.top(), 1, g.height()), QColor("#141416"))
        knob = QRectF(g.left() + 1.5, g.center().y() - 26, g.width() - 3, 52)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#5a5a62") if hot else QColor("#3a3a40"))
        p.drawRoundedRect(knob, 2.5, 2.5)
        p.setPen(QPen(QColor("#9a9aa3") if hot else QColor("#6e6e76"), 1))
        for dy in (-8, -3, 2, 7):
            y = knob.center().y() + dy
            p.drawLine(QLineF(knob.left() + 1.5, y, knob.right() - 1.5, y))

    def _paint_meters(self, p: QPainter):
        """Solo los vúmetros de las cabeceras (lo mismo que dibuja _paint_headers en esa zona)."""
        from ..core import meters
        try:
            levels = meters.track_levels(self.ctrl.project, self.ctrl.peaks, self.playhead)
        except Exception:  # noqa: BLE001
            levels = {}
        for i, tr in enumerate(self.ctrl.project.tracks):
            th = self.track_h(i)
            if th <= 20:
                continue
            y = self.track_y(i)
            p.fillRect(QRectF(self._meter_rect(i)), QColor("#252527"))
            if tr.id in levels:
                db = meters.to_db(levels[tr.id])
                frac = min(1.0, max(0.0, (db + 60) / 60))
                bar = QRectF(self.HEADER_W - 6, y + 4, 3, th - 8)
                p.fillRect(bar, QColor("#1a1a1c"))
                hfill = bar.height() * frac
                col = QColor("#e5484d") if db > -3 else QColor("#f2b33d") if db > -12 else QColor("#3fb950")
                p.fillRect(QRectF(bar.left(), bar.bottom() - hfill, bar.width(), hfill), col)

    def _paint_headers(self, p: QPainter):
        from ..core import meters
        try:
            levels = meters.track_levels(self.ctrl.project, self.ctrl.peaks, self.playhead)
        except Exception:  # noqa: BLE001 - un medidor nunca debe impedir dibujar la timeline
            levels = {}
        emoji = self._f(9, family="Segoe UI Emoji")
        small = self._f(8)
        bold = self._f(8, bold=True)
        from collections import Counter
        per_track = Counter(c.track_id for c in self.ctrl.project.clips.values())   # una pasada, no una por pista
        for i, tr in enumerate(self.ctrl.project.tracks):
            y = self.track_y(i)
            th = self.track_h(i)
            if th <= 0:
                continue
            r = QRectF(0, y, self.HEADER_W, th)
            p.fillRect(r, QColor("#2f333b") if tr.id in self.channels else QColor("#252527"))
            if tr.id in self.channels:
                p.fillRect(QRectF(self._grip_rect().right(), y, 3 * self.ui_k, th), QColor("#9a9ea8"))
            p.setPen(QColor("#141416"))
            p.drawLine(QLineF(0, y + th - 0.5, self.HEADER_W, y + th - 0.5))
            badge, name = self.track_badge(i)
            color = (COLORS["clip_text"] if tr.kind == TRACK_TEXT else
                     COLORS["clip_video"] if tr.kind == TRACK_VIDEO else COLORS["clip_audio"])
            k = self.ui_k
            br = QRectF(8 * k, y + 8 * k, 28 * k, 18 * k)
            p.setPen(QPen(color.lighter(130), 1))
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 70))
            p.drawRoundedRect(br, 3, 3)
            p.setFont(bold)
            p.setPen(QColor("#e6e6e8"))
            p.drawText(br, Qt.AlignCenter, badge)
            p.setFont(small)
            p.setPen(COLORS["text"])
            name_w = int(self.HEADER_W - (128 if tr.kind == TRACK_AUDIO else 100) * k)   # deja sitio a S/M
            p.drawText(QRectF(42 * k, y + 6 * k, name_w, 20 * k), Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, name_w))
            n_clips = per_track.get(tr.id, 0)
            p.setPen(COLORS["text_dim"])
            p.drawText(QRectF(8 * k, y + 28 * k, self.HEADER_W - 70 * k, 18 * k), Qt.AlignVCenter,
                       f"{n_clips} clip" + ("s" if n_clips != 1 else ""))
            lock_r, vis_r = self._header_buttons(i)
            # Candado
            # Candado: solo resalta (ámbar) si la pista está BLOQUEADA (eso sí impide editar); libre = gris discreto
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#5a4510") if tr.locked else QColor("#323235"))
            p.drawRoundedRect(lock_r, 3, 3)
            self._paint_lock(p, lock_r, tr.locked)
            # Video: ojo · Audio: M (silenciar), como en Resolve
            if tr.kind == TRACK_AUDIO:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#b23a32") if tr.muted else QColor("#323235"))
                p.drawRoundedRect(vis_r, 3, 3)
                p.setFont(bold)
                p.setPen(QColor("white") if tr.muted else COLORS["text_dim"])
                p.drawText(vis_r, Qt.AlignCenter, "M")
                sr = self._solo_rect(i)          # S = solo (como en Resolve)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#c9a227") if tr.solo else QColor("#323235"))
                p.drawRoundedRect(sr, 3, 3)
                p.setPen(QColor("black") if tr.solo else COLORS["text_dim"])
                p.drawText(sr, Qt.AlignCenter, "S")
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#4a2a28") if tr.hidden else QColor("#323235"))
                p.drawRoundedRect(vis_r, 3, 3)
                p.setFont(emoji)
                p.setPen(QColor("#e6e6e8"))
                p.drawText(vis_r, Qt.AlignCenter, "🚫" if tr.hidden else "👁")
            # Nivel de sonido de la pista en el cabezal (verde → amarillo → rojo)
            if tr.id in levels and th > 20:
                db = meters.to_db(levels[tr.id])
                frac = min(1.0, max(0.0, (db + 60) / 60))
                bar = QRectF(self.HEADER_W - 6, y + 4, 3, th - 8)
                p.fillRect(bar, QColor("#1a1a1c"))
                hfill = bar.height() * frac
                col = QColor("#e5484d") if db > -3 else QColor("#f2b33d") if db > -12 else QColor("#3fb950")
                p.fillRect(QRectF(bar.left(), bar.bottom() - hfill, bar.width(), hfill), col)
        p.setPen(QColor("#141416"))
        p.drawLine(QLineF(self.HEADER_W - 0.5, self.RULER_H, self.HEADER_W - 0.5, self.height()))

    def _thumb(self, media_id: str, h: int) -> QPixmap | None:
        path = self.ctrl.thumbs.get(media_id)
        if not path:
            return None
        key = (media_id, h)
        if key not in self._pix_cache:
            self._pix_cache[key] = QPixmap(path).scaledToHeight(h, Qt.SmoothTransformation)
        return self._pix_cache[key]

    def _paint_strip(self, p: QPainter, c, r: QRectF, strip, bar_h: float):
        """Los fotogramas del clip a lo largo de él: cada trozo enseña el fotograma de ese momento
        (con su recorte, velocidad, marcha atrás o congelado)."""
        pix, step, tile_w = strip
        th = max(4.0, r.height() - bar_h - 2)
        s = th / pix.height()
        tw = max(8.0, tile_w * s)
        n = max(1, int(round(pix.width() / tile_w)))
        top = r.top() + bar_h + 1
        x0 = max(r.left(), float(self.HEADER_W))
        x1 = min(r.right(), float(self.width()))
        k = int(max(0.0, (x0 - r.left()) // tw))
        x = r.left() + k * tw
        while x < x1:
            t_src = c.src_at(((x + tw / 2) - r.left()) / max(1e-6, self.pps))
            i = min(max(0, n - 2), max(0, int(t_src / step)))     # (el último hueco de la tira va vacío)
            p.drawPixmap(QRectF(x, top, tw, th), pix, QRectF(i * tile_w, 0, tile_w, pix.height()))
            x += tw

    def _paint_clip(self, p: QPainter, c, r: QRectF, dim=False, ghost=False):
        if r.right() < self.HEADER_W or r.left() > self.width():
            return
        proj = self.ctrl.project
        m = proj.media_of(c)
        kind = m.kind if m else ("text" if c.text else "video")
        tr = self._track_obj(c.track_id)
        if tr is not None and tr.kind == TRACK_AUDIO and m is not None:
            kind = KIND_AUDIO        # el sonido de un video, separado en una pista de audio
        missing = c.text is None and (m is None or m.id in self.ctrl.missing)
        base = (COLORS["missing"] if missing else
                COLORS["clip_disabled"] if not c.enabled and c.text else
                COLORS["clip_text"] if c.text else
                COLORS["clip_disabled"] if not c.enabled else
                QColor(c.label) if c.label else
                COLORS["clip_audio"] if kind == KIND_AUDIO else
                COLORS["clip_image"] if kind == KIND_IMAGE else COLORS["clip_video"])
        p.save()
        if dim:
            p.setOpacity(0.35)
        elif ghost:
            p.setOpacity(0.75)
        p.setPen(Qt.NoPen)
        p.setBrush(base.darker(130))
        if r.width() < 7:       # muy alejado: el clip mide 1–6 px; solo su color (rápido con cientos de clips)
            p.fillRect(r, COLORS["clip_sel"] if c.id in self.selected else
                       COLORS["ai"].darker(115) if c.origin == ORIGIN_AI else
                       base.darker(130) if not c.locked else base.darker(160))
            p.restore()
            return
        if 7 <= r.width() < 40 and not dim and not ghost:
            # ⚡ Zoom alejado: un clip de 7–40 px solo lleva color, onda o tira y su borde (sin texto ni iconos)
            p.drawRoundedRect(r, 4, 4)
            p.save()
            p.setClipRect(r.adjusted(1, 1, -1, -1), Qt.IntersectClip)
            if kind == KIND_AUDIO and r.width() >= 12 and m and m.id in self.ctrl.peaks and self.wave_style != "no":
                self._paint_wave(p, c, r, self.ctrl.peaks[m.id], base.lighter(150), m.duration)
            elif kind == KIND_VIDEO and r.width() >= 12 and m and not missing:
                strip = self.filmstrips.get(m)
                if strip is not None:
                    self._paint_strip(p, c, r, strip, 15 * self.ui_k)
            p.restore()
            p.setBrush(Qt.NoBrush)
            sel = c.id in self.selected
            if c.origin == ORIGIN_AI and not sel:
                p.setPen(QPen(COLORS["ai"], 2))
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
            if sel:
                p.setPen(QPen(COLORS["clip_sel"], 2))
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
            p.restore()
            return
        p.drawRoundedRect(r, 4, 4)
        p.setClipRect(r.adjusted(1, 1, -1, -1), Qt.IntersectClip)

        # Contenido: forma de onda o miniatura
        if kind == KIND_AUDIO:
            if m and m.id in self.ctrl.peaks and self.wave_style != "no":
                self._paint_wave(p, c, r, self.ctrl.peaks[m.id], base.lighter(150), m.duration)
            if m and self.wave_words and self.pps >= self.WORDS_PPS:
                self._paint_words(p, c, r, m)
            rh = self.ctrl.rhythm.get(m.id) if m else None
            if rh and not c.retimed:
                self._paint_rhythm(p, c, r, rh)
            elif m and self.ctrl.beats.get(m.id) and self.pps > 8 and not c.retimed:
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                for b in self.ctrl.beats[m.id]:
                    if c.source_in <= b < c.source_in + c.duration:
                        xb = r.left() + (b - c.source_in) * self.pps
                        p.drawLine(QLineF(xb, r.top() + 16, xb, r.top() + 24))
            if m and m.id in self.ctrl.rhythm_busy:
                p.setPen(QColor(255, 255, 255, 170))
                p.setFont(self._f(7))
                p.drawText(QRectF(r.left() + 4, r.bottom() - 15 * self.ui_k, max(0.0, r.width() - 8),
                                  14 * self.ui_k), Qt.AlignLeft | Qt.AlignVCenter, "🥁 escuchando el ritmo…")
        elif m:
            bar_h = 15 * self.ui_k
            strip = self.filmstrips.get(m) if kind == KIND_VIDEO and not missing else None
            if strip is not None:
                self._paint_strip(p, c, r, strip, bar_h)
            else:
                pix = self._thumb(m.id, int(r.height() - bar_h - 3))
                if pix and r.width() > 30:
                    if kind == KIND_IMAGE:        # una imagen: la misma miniatura a lo largo del clip
                        x = r.left() + 2
                        x_end = min(r.right(), self.width())
                        while x < x_end:
                            if x + pix.width() > self.HEADER_W:
                                p.drawPixmap(QPointF(x, r.top() + bar_h + 1), pix)
                            x += pix.width() + 1
                    else:
                        p.drawPixmap(QPointF(r.left() + 2, r.top() + bar_h + 1), pix)

        # Barra de título
        bar_h = 15 * self.ui_k
        p.fillRect(QRectF(r.left(), r.top(), r.width(), bar_h), base)
        f = self._f(8)
        p.setFont(f)
        p.setPen(QColor("white"))
        linked = bool(c.link) and getattr(self, "_links", {}).get(c.link, 0) > 1
        badges = ("🔗 " if linked else "") + ("🔒 " if c.locked else "") + ("📝 " if c.note else "") +             ("🔍 " if transform.is_zoomed(c.zoom_kf) else "") + ("🎞 " if c.layout_kf else ("◫ " if c.layout else "")) +             (("❄ " if c.speed <= 0 else f"{c.speed * 100:g}% ") if c.speed != 1.0 else "") + ("◀ " if c.reverse else "")
        if c.text:
            name = "T  " + str(c.text.get("content", "")).replace("\n", " ")
        else:
            name = (m.name if m else "¿?") if not missing else f"⚠ NO ENCONTRADO: {m.name if m else ''}"
        from ..core import effects as _EFX
        fx_keys = _EFX.visible_of(c.fx) if c.text is None else []
        chip_w = 0.0
        if fx_keys and r.width() > 46 and not ghost:      # ✦ pastilla «fx»: este clip lleva efectos (clic = elegir)
            chip_w = 18 + (9 if len(fx_keys) > 1 else 0)
            right = r.right() - (26 if c.origin == ORIGIN_AI and r.width() > 40 else 3)
            chip = QRectF(right - chip_w, r.top() + 1.5, chip_w, bar_h - 3)
            on = c.id == self.sel_fx
            p.setPen(QPen(COLORS["clip_sel"], 1.5) if on else Qt.NoPen)
            p.setBrush(QColor("#ffffff") if on else QColor(205, 208, 215, 215))
            p.drawRoundedRect(chip, 3, 3)
            p.setPen(QColor("#17181b"))
            cf = self._f(7)
            cf.setBold(True)
            p.setFont(cf)
            p.drawText(chip, Qt.AlignCenter, "fx" + (f"{len(fx_keys)}" if len(fx_keys) > 1 else ""))
            self._fx_chips[c.id] = chip
            p.setFont(f)
            p.setPen(QColor("white"))
        p.drawText(QRectF(r.left() + 4, r.top(), r.width() - 8 - chip_w, bar_h), Qt.AlignVCenter,
                   p.fontMetrics().elidedText(badges + name, Qt.ElideRight, int(r.width() - 30 - chip_w)))
        if c.locked:
            p.fillRect(r, QBrush(QColor(217, 164, 0, 60), Qt.BDiagPattern))
        self._paint_curve(p, c, r)
        self._paint_fades(p, c, r, bar_h)
        # Fotogramas clave del zoom: rombos abajo
        if len(c.zoom_kf) >= 2 and r.width() > 12:
            p.setPen(QPen(QColor("black"), 1))
            p.setBrush(QColor("#ffd166"))
            yk = r.bottom() - 6
            for k in c.zoom_kf:
                if kind == KIND_IMAGE:
                    local = k["t"]
                elif c.speed <= 0:
                    continue
                elif c.reverse:
                    local = (c.source_in + c.src_len - k["t"]) / c.speed
                else:
                    local = (k["t"] - c.source_in) / c.speed
                xk = r.left() + local * self.pps
                if r.left() - 1 <= xk <= r.right() + 1:
                    p.drawPolygon(QPolygonF([QPointF(xk, yk - 5), QPointF(xk + 5, yk),
                                             QPointF(xk, yk + 5), QPointF(xk - 5, yk)]))
        # 🎞 Claves de posición y tamaño: rombos azules (encima de los del zoom)
        if c.layout_kf and r.width() > 12:
            p.setPen(QPen(QColor("black"), 1))
            p.setBrush(QColor("#5ad1ff"))
            yk = r.bottom() - 17
            for k in c.layout_kf:
                if kind == KIND_IMAGE:
                    local = k["t"]
                elif c.speed <= 0:
                    continue
                elif c.reverse:
                    local = (c.source_in + c.src_len - k["t"]) / c.speed
                else:
                    local = (k["t"] - c.source_in) / c.speed
                xk = r.left() + local * self.pps
                if r.left() - 1 <= xk <= r.right() + 1:
                    p.drawPolygon(QPolygonF([QPointF(xk, yk - 5), QPointF(xk + 5, yk),
                                             QPointF(xk, yk + 5), QPointF(xk - 5, yk)]))
        p.restore()

        # Bordes: seleccionado = rojo sólido por FUERA (como Resolve); IA = naranja por DENTRO: se ven los dos.
        # Todos del mismo grosor (2 px).
        p.save()
        p.setBrush(Qt.NoBrush)
        sel = c.id in self.selected
        if c.origin == ORIGIN_AI and not sel:     # seleccionado: solo el rojo (un solo color)
            p.setPen(QPen(COLORS["ai"], 2))
            p.drawRoundedRect(r.adjusted(3.5, 3.5, -3.5, -3.5) if sel else r.adjusted(1, 1, -1, -1), 3, 3)
            badge = QRectF(r.right() - 22, r.top() + 1, 20, 13)
            if r.width() > 40:
                p.fillRect(badge, COLORS["ai"])
                p.setPen(QColor("black"))
                f = self._f(7)
                f.setBold(True)
                p.setFont(f)
                p.drawText(badge, Qt.AlignCenter, "IA")
        if sel:
            p.setPen(QPen(COLORS["clip_sel"], 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
        self._paint_fade_handles(p, c, r, sel)
        p.restore()

    @staticmethod
    def _paint_lock(p: QPainter, r: QRectF, locked: bool):
        """Un candado dibujado (no el emoji, que siempre se ve amarillo como si avisara de algo)."""
        col = QColor("#ffc53d") if locked else QColor("#8a8a91")
        s = min(r.width(), r.height())
        bw, bh = s * 0.46, s * 0.32
        body = QRectF(r.center().x() - bw / 2, r.center().y() - bh / 2 + s * 0.12, bw, bh)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(body, 1.5, 1.5)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, max(1.4, s * 0.08)))
        aw = bw * 0.62
        arc = QRectF(body.center().x() - aw / 2, body.top() - bh * 0.85, aw, bh * 1.5)
        if locked:
            p.drawArc(arc, 0, 180 * 16)                       # cerrado
        else:
            p.drawArc(arc.translated(aw * 0.45, -bh * 0.18), 0, 180 * 16)   # abierto (el arco a un lado)

    # ------------------------------------------------------------ fundidos (como en Resolve)
    FADE_KEYS = ("fade_in", "fade_out")

    def _fade_len(self, c, key: str) -> float:
        return max(0.0, float((c.fx or {}).get(key, 0) or 0)) if c.text is None else 0.0

    def _paint_fades(self, p: QPainter, c, r: QRectF, bar_h: float):
        """El fundido se ve como un triángulo oscuro: la imagen va a negro / el sonido baja hasta el silencio."""
        top = r.top() + bar_h
        for key in self.FADE_KEYS:
            fw = min(r.width(), self._fade_len(c, key) * self.pps)
            if fw < 1.5:
                continue
            if key == "fade_in":
                pts = [QPointF(r.left(), top), QPointF(r.left() + fw, top), QPointF(r.left(), r.bottom())]
                line = (QPointF(r.left(), r.bottom()), QPointF(r.left() + fw, top))
            else:
                pts = [QPointF(r.right() - fw, top), QPointF(r.right(), top), QPointF(r.right(), r.bottom())]
                line = (QPointF(r.right() - fw, top), QPointF(r.right(), r.bottom()))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 125))
            p.drawPolygon(QPolygonF(pts))
            p.setPen(QPen(QColor(255, 255, 255, 150), 1))
            p.drawLine(QLineF(*line))

    def _fade_handle_rects(self, c, r: QRectF) -> dict:
        """Los tiradores de las esquinas de arriba (donde empieza/acaba el fundido)."""
        if c.text is not None or r.width() < 34:
            return {}
        hw = 8.0
        xi = r.left() + min(r.width() / 2 - hw, self._fade_len(c, "fade_in") * self.pps)
        xo = r.right() - min(r.width() / 2 - hw, self._fade_len(c, "fade_out") * self.pps)
        return {"fade_in": QRectF(xi, r.top() + 1, hw, 9), "fade_out": QRectF(xo - hw, r.top() + 1, hw, 9)}

    def _paint_fade_handles(self, p: QPainter, c, r: QRectF, sel: bool):
        if not (sel or c.id == getattr(self, "_hover_clip", "")) or getattr(self, "_drag", None) and                 self._drag.get("type") == "move":
            return
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor("white"))
        for rr in self._fade_handle_rects(c, r).values():
            p.drawRoundedRect(rr, 2.5, 2.5)

    def fade_handle_at(self, pos: QPointF):
        """(clip, "fade_in"/"fade_out") si el ratón está sobre un tirador de fundido."""
        proj = self.ctrl.project
        for cid in list(self.selected) + [getattr(self, "_hover_clip", "")]:
            c = proj.clips.get(cid)
            if c is None:
                continue
            r = self.clip_rect(c)
            for key, rr in self._fade_handle_rects(c, r).items():
                if rr.adjusted(-4, -4, 4, 4).contains(pos):
                    return c, key
        return None, None

    SILENCE = 10 ** (-45 / 20)   # por debajo de -45 dB se considera silencio

    WAVE_CACHE_MAX = 400       # ondas ya dibujadas que se guardan (las de los clips que más se ven)
    WAVE_CACHE_W = 6000        # más anchas (un clip enorme con mucho zoom): se dibuja solo lo visible, sin guardar

    WORDS_PPS = 45      # zoom (píxeles por segundo) desde el que se ven las palabras sobre la onda

    def _paint_words(self, p: QPainter, c, r: QRectF, m):
        """📝 Las palabras sobre la onda (de la transcripción; con el alineador, al centésimo): una raya fina donde
        empieza cada una y su texto, para ver de un vistazo dónde empieza y acaba cada palabra al cortar."""
        words = (self.ctrl.project.transcripts.get(m.id) or {}).get("words") or []
        if not words or c.speed <= 0 or c.reverse:
            return
        import bisect
        a, b = c.source_in, c.source_in + c.src_len
        starts = [float(w[0]) for w in words]
        k = max(0, bisect.bisect_left(starts, a) - 1)
        x_lo, x_hi = max(r.left(), float(self.HEADER_W)), min(r.right(), float(self.width()))
        top, bottom = r.top() + 15 * self.ui_k, r.bottom() - 1
        f = self._f(7)
        p.save()
        p.setFont(f)
        fm = p.fontMetrics()
        line = QPen(QColor(255, 255, 255, 80), 1)
        end_pen = QPen(QColor(255, 255, 255, 40), 1, Qt.DotLine)
        last_text_x = -1e9
        for w in words[k:]:
            ws, we = float(w[0]), float(w[1])
            if ws >= b:
                break
            if we <= a:
                continue
            xs = r.left() + (ws - a) / c.speed * self.pps
            xe = r.left() + (we - a) / c.speed * self.pps
            if xe < x_lo or xs > x_hi:
                continue
            if ws >= a:
                p.setPen(line)
                p.drawLine(QLineF(xs, top, xs, bottom))
            if self.pps >= 2 * self.WORDS_PPS and we <= b:
                p.setPen(end_pen)
                p.drawLine(QLineF(xe, top + 10 * self.ui_k, xe, bottom))
            text = str(w[2]).strip() if len(w) > 2 else ""
            room = xe - max(xs, last_text_x)
            if text and room > 12 and xs + 2 > last_text_x:
                t = fm.elidedText(text, Qt.ElideRight, int(max(10.0, xe - xs - 3)))
                p.setPen(QColor(255, 255, 255, 200))
                p.drawText(QPointF(max(xs, r.left()) + 2, top + fm.ascent()), t)
                last_text_x = xs + fm.horizontalAdvance(t) + 4
        p.restore()

    def _paint_wave(self, p: QPainter, c, r: QRectF, peaks: np.ndarray, color: QColor, media_dur: float = 0.0):
        """Forma de onda del clip. Estilos (menú Timeline → Forma de onda): espejo, rectificada
        (desde abajo, como en Resolve) o contorno; escala lineal o en dB (se ven mejor los sonidos
        bajos); silencios sombreados y una marca donde termina el sonido.
        ⚡ Cada onda se dibuja UNA vez y se guarda como imagen: al editar, hacer zoom, desplazar o reproducir solo se
        copia (antes se volvía a calcular píxel a píxel en cada repintado). Se rehace sola si cambia lo que la afecta."""
        w, h = int(np.ceil(r.width())), int(np.ceil(r.height()))
        if len(peaks) == 0 or w <= 0 or h <= 0:
            return
        if w <= self.WAVE_CACHE_W:
            dpr = self.devicePixelRatioF()
            key = (c.id, id(peaks), len(peaks), round(c.source_in, 4), round(c.duration, 4), c.speed, c.reverse,
                   round(c.volume, 4), round(self.pps, 4), w, h, self.wave_style, self.wave_db, self.wave_silence,
                   color.rgba(), self.ui_k, dpr)
            cache = self.__dict__.setdefault("_wave_cache", {})
            pix = cache.pop(key, None)
            if pix is None:
                pix = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
                pix.setDevicePixelRatio(dpr)
                pix.fill(Qt.transparent)
                q = QPainter(pix)
                q.setRenderHint(QPainter.Antialiasing)
                self._draw_wave(q, c, QRectF(0, 0, r.width(), r.height()), peaks, color, 0.0, float(w),
                                (0.0, float(w)), True)
                q.end()
                while len(cache) >= self.WAVE_CACHE_MAX:
                    cache.pop(next(iter(cache)))
            cache[key] = pix              # al final: la más reciente (las más viejas salen primero)
            p.drawPixmap(QPointF(r.left(), r.top()), pix)
            return
        x0 = max(r.left(), float(self.HEADER_W))
        x1 = min(r.right(), float(self.width()))
        self._draw_wave(p, c, r, peaks, color, x0, x1, getattr(self, "_paint_x", (x0, x1)), r.right() <= self.width())

    def _draw_wave(self, p: QPainter, c, r: QRectF, peaks: np.ndarray, color: QColor, x0: float, x1: float,
                   draw_x: tuple[float, float], end_ok: bool):
        """Dibuja la onda calculada entre x0 y x1, pero solo pinta la franja draw_x."""
        npx = int(x1 - x0)
        if npx <= 0 or len(peaks) == 0:
            return
        xs = np.arange(npx, dtype=np.float64) + x0
        # Con velocidad, cada píxel recorre speed× más archivo; hacia atrás, se lee en espejo
        xr = (r.left() + r.right()) - xs[::-1] if c.reverse else xs
        src_t = c.source_in + (xr - r.left()) / self.pps * c.speed
        idx = np.clip((src_t * PEAK_RATE).astype(np.int64), 0, len(peaks) - 1)
        if PEAK_RATE / self.pps > 1.0:
            raw = np.maximum.reduceat(peaks, idx)  # máximo de cada tramo de píxel
            raw[-1] = peaks[idx[-1]]
        else:
            raw = peaks[idx]
        if c.reverse:
            raw = np.asarray(raw)[::-1]
        raw = np.clip(np.asarray(raw, np.float64) * c.volume, 0, 1.5)
        if self.wave_db:
            vals = np.clip((20 * np.log10(np.maximum(raw, 1e-6)) + 60) / 60, 0, 1)
        else:
            vals = np.clip(raw, 0, 1) ** 0.7
        top, bottom = r.top() + 16 * self.ui_k, r.bottom() - 2
        mid, half = (top + bottom) / 2, (bottom - top) / 2
        silent = raw < self.SILENCE
        # ⚡ Se calcula todo el clip (para saber dónde acaba el sonido) pero solo se DIBUJA la franja que se repinta
        # (al reproducir, la del cabezal: unos pocos píxeles en vez de todo el ancho de cada clip)
        lo, hi = draw_x
        k0, k1 = max(0, int(np.floor(lo - x0))), min(npx, int(np.ceil(hi - x0)) + 1)
        if k1 <= k0:
            k0, k1 = 0, 0
        # Silencios: zonas más oscuras (tramos de 3 píxeles o más)
        if self.wave_silence and silent.any():
            shade = QColor(0, 0, 0, 70)
            edges = np.diff(np.concatenate(([0], silent.astype(np.int8), [0])))
            for a_, b_ in zip(np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]):
                if b_ - a_ >= 3 and b_ > k0 and a_ < k1:
                    p.fillRect(QRectF(xs[a_], top, b_ - a_, bottom - top), shade)
        dx, dv = xs[k0:k1], vals[k0:k1]
        if self.wave_style == "contorno":
            # (el contorno se dibuja con un píxel más a cada lado para que las líneas empalmen)
            j0, j1 = max(0, k0 - 1), min(npx, k1 + 1)
            up = QPolygonF([QPointF(x, mid - v * half) for x, v in zip(xs[j0:j1], vals[j0:j1])])
            down = QPolygonF([QPointF(x, mid + v * half) for x, v in zip(xs[j0:j1], vals[j0:j1])])
            p.setPen(QPen(color, 1.2))
            p.drawPolyline(up)
            p.drawPolyline(down)
        elif self.wave_style == "rectificada":
            p.setPen(QPen(color, 1))
            p.drawLines([QLineF(x, bottom, x, bottom - v * (bottom - top)) for x, v in zip(dx, dv)])
        else:
            p.setPen(QPen(color, 1))
            p.drawLines([QLineF(x, mid - v * half, x, mid + v * half) for x, v in zip(dx, dv)])
        hot = np.nonzero(raw[k0:k1] >= 0.98)[0]
        if len(hot):   # saturación: en rojo
            p.setPen(QPen(QColor("#ff4d4d"), 1))
            for j in hot:
                x, v = dx[j], dv[j]
                if self.wave_style == "rectificada":
                    p.drawLine(QLineF(x, bottom, x, bottom - v * (bottom - top)))
                else:
                    p.drawLine(QLineF(x, mid - v * half, x, mid + v * half))
        # Dónde termina el sonido: si el clip acaba en silencio (más de medio segundo), una marca
        if self.wave_silence and len(silent) and silent[-1] and end_ok:
            nz = np.nonzero(~silent)[0]
            if len(nz):
                xe = xs[nz[-1]] + 1
                if (r.right() - xe) / self.pps >= 0.5:
                    p.setPen(QPen(QColor("#ffd166"), 1, Qt.DashLine))
                    p.drawLine(QLineF(xe, top, xe, bottom))
                    if r.right() - xe > 70:
                        f = self._f(7)
                        p.setFont(f)
                        p.setPen(QColor("#ffd166"))
                        p.drawText(QPointF(xe + 3, bottom - 3), "fin del sonido")

    # ------------------------------------------------------- hit testing
    def clip_at(self, pos: QPointF):
        i = self.track_index_at(pos.y())
        if i is None or pos.x() < self.HEADER_W:
            return None, None
        tr = self.ctrl.project.tracks[i]
        for c in self.ctrl.project.clips_on(tr.id):
            x1, x2 = self.x_for(c.start), self.x_for(c.end)
            if x1 - 1 <= pos.x() <= x2 + 1:
                edge = min(self.EDGE_PX, (x2 - x1) / 3)
                if pos.x() - x1 <= edge:
                    return c, "left"
                if x2 - pos.x() <= edge:
                    return c, "right"
                return c, "body"
        return None, None

    def marker_at(self, pos: QPointF):
        if not (self.TOPIC_H <= pos.y() <= self.RULER_H):
            return None
        for m in self.ctrl.project.markers:
            if m.kind != "topic" and abs(self.x_for(m.time) - pos.x()) <= 6:
                return m
        return None

    def topic_at(self, pos: QPointF):
        """(tema, zona) en la franja de temas: zona 'edge' = borde de inicio (se puede arrastrar)."""
        if pos.y() >= self.TOPIC_H:
            return None, None
        t = self.t_for(pos.x())
        topics = [m for m in self.ctrl.project.markers if m.kind == "topic" and m.end is not None]
        for i, m in enumerate(topics):
            if i > 0 and abs(self.x_for(m.time) - pos.x()) <= 5:
                return m, "edge"
        for m in topics:
            if m.time <= t < m.end:
                return m, "body"
        return None, None

    def _snap_targets(self, exclude: set[str]) -> list[float]:
        pts = [0.0, self.playhead]
        for c in self.ctrl.project.clips.values():
            if c.id not in exclude:
                pts += [c.start, c.end]
        pts += [m.time for m in self.ctrl.project.markers]
        if self.snap_rhythm and self.ctrl.rhythm:
            key = frozenset(exclude)
            if key not in self._rhythm_pts:
                rt = self.ctrl.rhythm_on_timeline(exclude=set(exclude))
                self._rhythm_pts = {key: rt["beats"] + rt["drops"]}   # solo el último (cambia al arrastrar otro)
            pts += self._rhythm_pts[key]
        return pts

    def _paint_rhythm(self, p: QPainter, c, r: QRectF, rh: dict):
        """El ritmo sobre la canción: rayita en cada golpe, más larga al empezar cada compás, punto naranja
        en los golpes fuertes y una línea roja 💥 en el drop."""
        lo, hi = c.source_in, c.source_in + c.duration
        vis_a = lo + max(0.0, (0 - r.left())) / self.pps
        vis_b = lo + (self.width() - r.left()) / self.pps
        down = set(rh.get("downbeats", []))
        strong = set(rh.get("strong", []))
        top = r.top() + 16 * self.ui_k
        p.save()
        for b in rh.get("beats", []):
            if b < max(lo, vis_a) or b >= min(hi, vis_b):
                continue
            xb = r.left() + (b - lo) * self.pps
            if b in down:
                p.setPen(QPen(QColor(255, 255, 255, 210), 1.4))
                p.drawLine(QLineF(xb, top, xb, top + 12 * self.ui_k))
            elif self.pps > 10:
                p.setPen(QPen(QColor(255, 255, 255, 110), 1))
                p.drawLine(QLineF(xb, top, xb, top + 6 * self.ui_k))
            if b in strong and self.pps > 6:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#f2a03d"))
                p.drawEllipse(QPointF(xb, top + 15 * self.ui_k), 2.2, 2.2)
        d = rh.get("drop")
        if d is not None and lo <= d < hi:
            xd = r.left() + (d - lo) * self.pps
            p.setPen(QPen(QColor("#e5413c"), 2))
            p.drawLine(QLineF(xd, r.top() + 15 * self.ui_k, xd, r.bottom() - 1))
            p.setFont(self._f(7))
            p.drawText(QPointF(xd + 3, r.bottom() - 4), "💥 drop")
        p.restore()

    STICKY_PX = 16

    def _track_edges(self, c) -> list[float]:
        """Bordes de los demás clips de la pista de c (una vez por arrastre)."""
        edges = set()
        for o in self.ctrl.project.clips_on(c.track_id):
            if o.id != c.id:
                edges.update((o.start, o.end))
        return sorted(edges)

    def _sticky_edge(self, c, t: float, edges: list[float] | None = None):
        """Con el imán: al alargar un clip se queda «pegado» un momento justo donde choca con el siguiente
        (o con el anterior), para que sepas dónde está; si sigues arrastrando, se lo come."""
        if edges is None:
            edges = self._track_edges(c)
        near = [e for e in edges if abs(e - t) * self.pps <= self.STICKY_PX]
        return min(near, key=lambda e: abs(e - t)) if near else None

    def _snap(self, t: float, targets: list[float]) -> float:
        if not self.snapping:
            return t
        best = None
        for s in targets:
            dpx = abs(s - t) * self.pps
            if dpx <= self.SNAP_PX and (best is None or dpx < best[0]):
                best = (dpx, s)
        return best[1] if best else t

    # ------------------------------------------------------------- ratón
    def mousePressEvent(self, e):
        if self._nudge is not None:      # ⇆ un clic aplica el deslizamiento pendiente
            self._nudge_commit()
        apos = e.position()             # (real: los rombos de efectos van bajo la regla fija)
        pos = self._rmap(apos)          # (en la regla fija, y dentro de la regla = como siempre)
        self.setFocus()
        if e.button() == Qt.LeftButton and self._grip_rect().contains(pos):     # ↕ tamaño de las pistas
            self._drag = {"type": "track_zoom", "y0": pos.y(), "v0": self.video_h, "a0": self.audio_h}
            self.update()
            return
        if pos.x() < self.HEADER_W:
            self._header_click(pos, e)
            return
        ci = self.cut_issue_at(pos) if e.button() == Qt.LeftButton else None
        if ci is not None:          # línea roja: el cabezal va al corte y se abre su ajuste
            self.seek_requested.emit(max(0.0, self.cut_issues[ci]["t"]))
            self.cut_issue_clicked.emit(ci)
            return
        k = self.effect_mark_at(apos) if e.button() == Qt.LeftButton else -1
        if k >= 0:
            self.effect_mark_clicked.emit(k)
            return
        h = self.hint_mark_at(pos) if e.button() == Qt.LeftButton else -1
        if h >= 0:                  # 🎬 banderita de «Dijiste…»: el cabezal va ahí (y queda elegida 🔑)
            self.select_hint(h)
            self.seek_requested.emit(max(0.0, self.hint_marks[h][0]))
            return
        if pos.y() < self.RULER_H:
            topic, tzone = self.topic_at(pos)
            if e.button() == Qt.RightButton:
                m = self.marker_at(pos) or topic
                if m:
                    self._marker_menu(m, e.globalPosition().toPoint())
                return
            if tzone == "edge":  # arrastrar el borde entre dos temas
                self._drag = {"type": "topic_edge", "marker": topic.id, "x0": pos.x(), "new_t": topic.time}
                return
            self._drag = {"type": "scrub"}
            self.seek_requested.emit(max(0.0, self.t_for(pos.x())))
            return
        hit = self.trans_at(pos) if self.tool != "blade" else None
        if hit is not None:      # la transición (encima del corte): clic = seleccionarla
            rid, r, edge = hit
            self.select_transition(rid)
            if e.button() == Qt.RightButton:
                self._trans_menu(rid, e.globalPosition().toPoint())
                return
            if e.button() == Qt.LeftButton and edge:
                self._drag = {"type": "trans_dur", "id": rid, "xc": r.center().x()}
            return
        fxc = self.fx_chip_at(pos) if self.tool != "blade" else None
        if fxc is not None:      # ✦ la pastilla «fx»: clic = seleccionarla (Supr = quitar), clic derecho = elegir
            self.select_fx(fxc)
            if e.button() == Qt.RightButton:
                self._fx_menu(fxc, e.globalPosition().toPoint())
            return
        fc, fkey = self.fade_handle_at(pos) if (e.button() == Qt.LeftButton and self.tool != "blade") else (None, None)
        if fc is not None:       # tirador de fundido (esquina de arriba): arrastrar = fundido más largo / corto
            if fc.id not in self.selected:
                self.set_selection([fc.id])
            self._drag = {"type": "fade", "clip": fc.id, "key": fkey, "orig": dict(fc.fx or {}) or None,
                          "val": self._fade_len(fc, fkey)}
            return
        clip, zone = self.clip_at(pos)
        sug = self.suggestion_at(pos)
        if sug and sug[0] and e.button() == Qt.LeftButton:
            self.suggestion_clicked.emit(sug[0])
        if self.curves and clip is not None and zone == "body" and self._curve_press(clip, pos, e):
            if clip.id not in self.selected:
                self.set_selection([clip.id])
            return
        if clip is not None and e.button() in (Qt.LeftButton, Qt.RightButton):
            self.set_channels([clip.track_id], "add" if e.modifiers() & Qt.ControlModifier else "set")
        if e.button() == Qt.RightButton:
            if clip and clip.id not in self.selected:
                self.set_selection([clip.id])
            self._clip_menu(clip, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        alt = bool(e.modifiers() & Qt.AltModifier)
        if self.tool == "blade" and clip is not None:
            t = self._snap(self.t_for(pos.x()), [self.playhead])
            self.ctrl.split(t, self._with_links([clip.id], alt))
            return
        if clip is None:
            # Zona vacía: clic = cabezal (y, si es un hueco, seleccionarlo); arrastrar = rectángulo
            self._drag = {"type": "empty", "x0": pos.x(), "y0": pos.y(),
                          "add": bool(e.modifiers() & Qt.ControlModifier), "alt": alt,
                          "base": set(self.selected)}
            return
        group = self._with_links([clip.id], alt)
        mods = e.modifiers()
        ctrl_m, shift_m = bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier)
        adv = self._advanced_drag(clip, zone, pos, ctrl_m, shift_m)
        if adv is not None:
            if clip.id not in self.selected:
                self.set_selection(group)
            self._drag = adv
            return
        if ctrl_m:
            self.set_selection(self.selected - set(group) if clip.id in self.selected
                               else self.selected | set(group))
            return
        if clip.id not in self.selected or (alt and len(self.selected) > 1):
            self.set_selection(group)
        if zone in ("left", "right"):
            proj = self.ctrl.project
            partners = []
            if self.linked and not alt:
                partners = [o.id for o in self.ctrl.partners(proj, clip)
                            if (abs(o.start - clip.start) < 1e-3 if zone == "left" else abs(o.end - clip.end) < 1e-3)]
            lims = [self.ctrl.trim_limits(i, overwrite=True) for i in [clip.id] + partners]
            limits = (max(l[0] for l in lims), min(l[1] for l in lims), max(l[2] for l in lims),
                      min(l[3] for l in lims))
            self._drag = {"type": "trim", "clip": clip.id, "edge": zone, "x0": pos.x(),
                          "new_start": clip.start, "new_end": clip.end, "limits": limits,
                          "partners": partners, "linked": self.linked and not alt}
        else:
            tr0 = self.ctrl.project.track(clip.track_id)
            self._drag = {"type": "move", "anchor": clip.id, "x0": pos.x(), "y0": pos.y(),
                          "ids": sorted(self.selected), "dt": 0.0, "dtrack": 0,
                          "track0": self.track_index_at(pos.y()), "kind0": tr0.kind if tr0 else None}

    def _neighbor(self, clip, edge: str):
        """El clip pegado a ese borde (para el «roll»)."""
        for o in self.ctrl.project.clips_on(clip.track_id):
            if o.id == clip.id:
                continue
            if edge == "left" and abs(o.end - clip.start) < 1e-3:
                return o
            if edge == "right" and abs(o.start - clip.end) < 1e-3:
                return o
        return None

    def _advanced_drag(self, clip, zone, pos, ctrl_m: bool, shift_m: bool):
        """Recortes avanzados. Herramienta ⇿ Recorte: borde = ripple, Mayús+borde (en un corte) = roll,
        centro = slip, Mayús+centro = slide. Con la herramienta normal: Ctrl+borde = ripple,
        Ctrl+Mayús+borde = roll."""
        trim_tool = self.tool == "trim"
        if zone in ("left", "right") and (trim_tool or ctrl_m):
            nb = self._neighbor(clip, zone)
            if shift_m and nb is not None:
                right = clip if zone == "left" else nb
                return {"type": "roll", "right": right.id, "x0": pos.x(), "t": right.start,
                        "limits": self.ctrl.roll_limits(right.id)}
            return {"type": "ripple", "clip": clip.id, "edge": zone, "x0": pos.x(),
                    "t": clip.start if zone == "left" else clip.end,
                    "limits": self.ctrl.ripple_limits(clip.id, zone), "linked": self.linked}
        if zone == "body" and trim_tool:
            if shift_m:
                return {"type": "slide", "clip": clip.id, "x0": pos.x(), "dt": 0.0,
                        "limits": self.ctrl.slide_limits(clip.id)}
            return {"type": "slip", "clip": clip.id, "x0": pos.x(), "dt": 0.0}
        return None

    def _drag_rects(self, d) -> list[QRectF]:
        """Dónde se dibuja ahora mismo lo que mueve el arrastre (fantasmas, recortes, rectángulo del ripple)."""
        proj = self.ctrl.project
        out: list[QRectF] = []
        if d["type"] == "move":
            for cid in d["ids"]:
                c = proj.clips.get(cid)
                if c is not None:
                    out.append(self.clip_rect(c, c.start + d["dt"], self._dest_track(c, d)))
                    out.append(self.clip_rect(c))
        elif d["type"] == "trim":
            for cid in [d["clip"]] + d.get("partners", []):
                c = proj.clips.get(cid)
                if c is not None:
                    s, e = (d["new_start"], c.end) if d["edge"] == "left" else (c.start, d["new_end"])
                    a, b = min(s, c.start), max(e, c.end)
                    out.append(self.clip_rect(c, a, duration=b - a))
        elif d["type"] == "slide":
            c = proj.clips.get(d["clip"])
            if c is not None:
                out += [self.clip_rect(c, c.start + d["dt"]), self.clip_rect(c)]
        elif d["type"] == "ripple":
            c = proj.clips.get(d["clip"])
            if c is not None:
                dur = c.end - d["t"] if d["edge"] == "left" else d["t"] - c.start
                out += [self.clip_rect(c, c.start, duration=max(0.0, dur)), self.clip_rect(c)]
        return out

    def _update_drag(self, d):
        """⚡ Un arrastre repinta solo donde estaban sus dibujos y donde están ahora, no toda la línea de tiempo en
        cada movimiento. Al empezar (los originales se atenúan) y con selecciones enormes, se repinta entera."""
        from PySide6.QtGui import QRegion
        rects = self._drag_rects(d)
        old = d.get("_rects")
        d["_rects"] = rects
        if old is None or len(d.get("ids", ())) > 40:
            self.update()
            return
        if old == rects:
            return
        reg = QRegion()
        for r in old + rects:
            reg = reg.united(QRegion(r.adjusted(-6, -6, 6, 6).toAlignedRect()))
        self.update(reg)

    def _snap_arr(self, excl: set[str]) -> np.ndarray:
        """Destinos del imán como array ordenado, una vez por arrastre (sin el cabezal: _snap_fast lo mira en vivo)."""
        if not self.snapping:
            return np.empty(0)
        tg = self._snap_targets(excl)
        try:
            tg.remove(self.playhead)
        except ValueError:
            pass
        return np.sort(np.asarray(tg, dtype=float))

    def _snap_fast(self, t: float, arr: np.ndarray) -> float:
        """Igual que _snap, pero con búsqueda binaria en el array de _snap_arr (el más cercano está junto a t)."""
        if not self.snapping:
            return t
        cand = [self.playhead]
        n = len(arr)
        if n:
            i = int(np.searchsorted(arr, t))
            cand += [float(arr[j]) for j in (i - 1, i) if 0 <= j < n]
        best = None
        for s in cand:
            dpx = abs(s - t) * self.pps
            if dpx <= self.SNAP_PX and (best is None or dpx < best[0]):
                best = (dpx, s)
        return best[1] if best else t

    def _seek_soon(self, t: float):
        """Al arrastrar, el visor se pide como mucho cada 16 ms (basta con el último valor)."""
        self._seek_val = t
        if not self._seek_armed:
            self._seek_armed = True
            QTimer.singleShot(16, self._flush_seek)

    def _flush_seek(self):
        self._seek_armed = False
        if self._seek_val is not None:
            t, self._seek_val = self._seek_val, None
            self.seek_requested.emit(t)

    def mouseMoveEvent(self, e):
        d = self._drag
        # Arrastres de zona/marquesina/zoom de pistas: coordenadas reales; el resto, con la regla fija
        pos = e.position() if d is not None and d["type"] in ("track_zoom", "marquee", "empty") \
            else self._rmap(e.position())
        if d is not None and d["type"] == "track_zoom":     # arriba = más grandes · abajo = más pequeñas
            f = 2 ** ((d["y0"] - pos.y()) / 160.0)
            self.video_h = int(min(self.H_MAX, max(self.H_MIN, d["v0"] * f)))
            self.audio_h = int(min(self.H_MAX, max(self.H_MIN, d["a0"] * f)))
            self._on_project_changed()
            self.update()
            return
        if d is None:
            hov = self._grip_rect().contains(pos)
            if hov != getattr(self, "_grip_hover", False):
                self._grip_hover = hov
                self.update()
            if hov:
                self.setCursor(Qt.SizeVerCursor)
                self.setToolTip("Arrastra hacia ARRIBA = pistas más grandes · hacia ABAJO = más pequeñas")
                return
        if d is not None and d["type"] == "fade":           # arrastrando un tirador de fundido
            c = self.ctrl.project.clips.get(d["clip"])
            if c is not None:
                r = self.clip_rect(c)
                raw = (pos.x() - r.left()) if d["key"] == "fade_in" else (r.right() - pos.x())
                other = self._fade_len(c, "fade_out" if d["key"] == "fade_in" else "fade_in")
                fps = float(self.ctrl.project.fps or 30.0)
                v = max(0.0, min(raw / max(1e-6, self.pps), c.duration - other - 1.0 / fps))
                v = round(round(v * fps) / fps, 4)             # de fotograma en fotograma
                d["val"] = v
                fx = dict(d["orig"] or {})
                if v > 0:
                    fx[d["key"]] = v
                else:
                    fx.pop(d["key"], None)
                c.fx = fx or None                              # solo para verlo; se guarda al soltar (Ctrl+Z)
                self.setToolTip(f"{'Fundido de entrada' if d['key'] == 'fade_in' else 'Fundido de salida'}: "
                                f"{v:.2f} s")
                self.update()
            return
        if d is None:
            hc, _z = self.clip_at(pos)
            hid = hc.id if hc is not None else ""
            if hid != getattr(self, "_hover_clip", ""):
                self._hover_clip = hid
                self.update()
            fc, fkey = self.fade_handle_at(pos)
            if fc is not None and self.tool != "blade":
                self.setCursor(Qt.SizeHorCursor)
                self.setToolTip("Arrastra = " + ("fundido de entrada (desde negro / el sonido sube)"
                                                 if fkey == "fade_in" else
                                                 "fundido de salida (a negro / el sonido baja)"))
                return
        if d is not None and d["type"] == "trans_dur":     # arrastrando un borde de la transición
            from ..core import transitions as TR
            c = self.ctrl.project.clips.get(d["id"])
            prev = TR.previous(self.ctrl.project, c) if c else None
            if c is not None and prev is not None:
                raw = 2 * abs(pos.x() - d["xc"]) / max(1e-6, self.pps)
                d["new"] = round(TR.clamp_dur(round(raw * 20) / 20, prev, c), 3)   # de 0,05 en 0,05 s
                self._trans_preview = (d["id"], d["new"])
                self.update()
            return
        if d is None and self.tool != "blade" and self.fx_chip_at(pos) is not None:
            from ..core import effects as _EFX
            c_ = self.ctrl.project.clips.get(self.fx_chip_at(pos))
            names = ", ".join(self._fx_name(k) for k in _EFX.visible_of(c_.fx if c_ else None))
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f"✦ Efectos: {names}\nclic = seleccionar (Supr = quitarlos todos) · clic derecho = quitar "
                            "uno")
            return
        if d is None and self.tool != "blade":
            hit = self.trans_at(pos)
            if hit is not None:
                self.setCursor(Qt.SizeHorCursor if hit[2] else Qt.PointingHandCursor)
                self.setToolTip("⧉ Transición · clic = seleccionar (Supr o Ctrl+X = quitar) · "
                                "arrastra un borde = más larga / más corta · clic derecho = reemplazar, duración…")
                return
        if d is None:
            clip, zone = self.clip_at(pos)
            if self.tool == "trim":
                if zone in ("left", "right"):
                    roll = bool(e.modifiers() & Qt.ShiftModifier) and self._neighbor(clip, zone) is not None
                    self.setCursor(Qt.SplitHCursor if roll else Qt.SizeHorCursor)
                else:
                    self.setCursor(Qt.SizeAllCursor if clip else Qt.ArrowCursor)
                self.setToolTip("⇿ Recorte: borde = ripple (mueve lo de detrás) · Mayús+borde = mover el corte (roll)\n"
                                "centro = cambiar la parte visible (slip) · Mayús+centro = deslizar (slide)" if clip else "")
                return
            if self.tool == "blade":
                self.setCursor(Qt.SplitHCursor)
            else:
                self.setCursor(Qt.SizeHorCursor if zone in ("left", "right") else
                               Qt.OpenHandCursor if clip else Qt.ArrowCursor)
            topic, tzone = self.topic_at(pos)
            if tzone == "edge":
                self.setCursor(Qt.SizeHorCursor)
            hover = topic.id if topic else ""
            if hover != self._hover_topic:
                self._hover_topic = hover
                self.update()
            m = self.marker_at(pos)
            sug = None if m else self.suggestion_at(pos)
            if topic:
                tip = (f"{topic.label}  ({fmt_time(topic.time, False)} – {fmt_time(topic.end, False)})\n"
                       "Doble clic: renombrar · Clic derecho: más opciones · Arrastra el borde para ajustarlo")
            else:
                tip = m.label if m else (sug[1] if sug else "")
                if not tip and clip is None and pos.x() > self.HEADER_W:
                    gi = self.track_index_at(pos.y())
                    if gi is not None:
                        g = self.ctrl.gap_at(self.ctrl.project.tracks[gi].id, max(0.0, self.t_for(pos.x())))
                        if g:
                            tip = (f"Hueco de {g[1] - g[0]:.1f} s · clic = marcarlo · Supr = eliminarlo\n"
                                   "Clic derecho = eliminar todos los huecos de la pista")
            self.setToolTip(tip)
            return
        if d["type"] == "scrub":
            self._seek_soon(max(0.0, self.t_for(pos.x())))
            return
        if d["type"] in ("curve_point", "curve_level"):
            self._curve_move(d, pos)
            return
        if d["type"] in ("empty", "marquee"):
            if d["type"] == "empty":
                if abs(pos.x() - d["x0"]) < self.DRAG_START_PX and abs(pos.y() - d["y0"]) < self.DRAG_START_PX:
                    return
                d["type"] = "marquee"
                self.gap = None
            d["x1"], d["y1"] = pos.x(), pos.y()
            hit = self._clips_in_rect(QRectF(QPointF(d["x0"], d["y0"]), QPointF(pos.x(), pos.y())).normalized())
            hit = set(self._with_links(hit, d["alt"]))
            self.selected = (d["base"] | hit) if d["add"] else hit
            self.update()
            return
        if not d.get("active"):
            if abs(pos.x() - d["x0"]) < self.DRAG_START_PX and \
                    abs(pos.y() - d.get("y0", pos.y())) < self.DRAG_START_PX:
                return
            d["active"] = True
        proj = self.ctrl.project
        if d["type"] == "topic_edge":
            if "_snap" not in d:
                d["_snap"] = self._snap_arr(set())
            d["new_t"] = max(0.0, self._snap_fast(self.t_for(pos.x()), d["_snap"]))
            self.setCursor(Qt.SizeHorCursor)
        elif d["type"] == "move":
            anchor = proj.clips[d["anchor"]]
            dt = (pos.x() - d["x0"]) / self.pps
            if "_snap" not in d:
                d["_snap"] = self._snap_arr(set(d["ids"]))
            snapped_start = self._snap_fast(anchor.start + dt, d["_snap"])
            snapped_end = self._snap_fast(anchor.end + dt, d["_snap"])
            if snapped_start != anchor.start + dt:
                dt = snapped_start - anchor.start
            elif snapped_end != anchor.end + dt:
                dt = snapped_end - anchor.end
            # No permitir que ningún clip quede antes del segundo 0
            dt = max(dt, -min(proj.clips[i].start for i in d["ids"]))
            dtrack = 0
            ti = self.track_index_at(pos.y())
            if ti is not None and d["track0"] is not None:
                dtrack = ti - d["track0"]
                for cid in d["ids"]:
                    src = proj.track_index(proj.clips[cid].track_id)
                    if proj.tracks[src].kind != d.get("kind0"):
                        continue   # su sonido vinculado no cambia de pista
                    dst = src + dtrack
                    if not (0 <= dst < len(proj.tracks)) or \
                            proj.tracks[dst].kind != proj.tracks[src].kind:
                        dtrack = 0
                        break
            d["dt"], d["dtrack"] = self._safe_dt(d, dt, dtrack), dtrack
            self.setCursor(Qt.ClosedHandCursor)
        elif d["type"] in ("ripple", "roll"):
            lo, hi = d["limits"]
            if "_snap" not in d:
                d["_snap"] = self._snap_arr({d.get("clip"), d.get("right")})
            t = self._snap_fast(self.t_for(pos.x()), d["_snap"])
            d["t"] = min(max(t, lo), hi)
            self._seek_soon(d["t"])
        elif d["type"] == "slip":
            d["dt"] = (pos.x() - d["x0"]) / self.pps
            c = proj.clips[d["clip"]]
            self.setToolTip(f"Slip: {d['dt']:+.2f} s · empieza en el segundo {max(0.0, c.src_at(0) + d['dt'] * c.speed):.2f} del archivo")
        elif d["type"] == "slide":
            lo, hi = d["limits"]
            d["dt"] = min(max((pos.x() - d["x0"]) / self.pps, lo), hi)
        elif d["type"] == "trim":
            c = proj.clips[d["clip"]]
            lmin, lmax, rmin, rmax = d["limits"]
            t = self.t_for(pos.x())
            if "_snap" not in d:
                d["_edges"] = self._track_edges(c)
                d["_snap"] = self._snap_arr({c.id})
            sticky = self._sticky_edge(c, t, d["_edges"]) if self.snapping else None
            t = sticky if sticky is not None else self._snap_fast(t, d["_snap"])
            if d["edge"] == "left":
                d["new_start"], d["new_end"] = min(max(t, lmin), lmax), c.end
            else:
                d["new_start"], d["new_end"] = c.start, min(max(t, rmin), rmax)
            self._seek_soon(d["new_start"] if d["edge"] == "left" else d["new_end"])
        if d["type"] in ("move", "trim", "slide", "ripple"):
            self._update_drag(d)
        else:
            self.update()

    def mouseReleaseEvent(self, e):
        self._flush_seek()                  # el último seek pendiente del arrastre, al momento
        d, self._drag = self._drag, None
        self.setCursor(Qt.ArrowCursor)
        if d and d["type"] == "track_zoom":                  # se recuerda (igual que con 🎞↕ / 🔊↕)
            self.set_wave(video_h=self.video_h, audio_h=self.audio_h)
            return
        if d and d["type"] == "fade":
            c = self.ctrl.project.clips.get(d["clip"])
            if c is not None:
                new = c.fx
                c.fx = d["orig"]                               # lo de antes, para que Ctrl+Z vuelva ahí
                if (new or {}) != (d["orig"] or {}):
                    name = "Fundido de entrada" if d["key"] == "fade_in" else "Fundido de salida"
                    self.ctrl.set_clip_props([c.id], name, fx=dict(new) if new else None)
            self.update()
            return
        if d and d["type"] == "trans_dur":
            self._trans_preview = None
            from ..core import transitions as TR
            c = self.ctrl.project.clips.get(d["id"])
            cur = TR.of(c) if c else None
            if cur and "new" in d and abs(d["new"] - float(cur["dur"])) > 1e-3:
                self.ctrl.set_transition([d["id"]], cur["type"], d["new"])
            self.update()
            return
        if d and d["type"] == "marquee":
            self.selection_changed.emit(sorted(self.selected))
            self.update()
            return
        if d and d["type"] == "empty":   # clic sin arrastrar en una zona vacía
            pos = e.position()
            t = max(0.0, self.t_for(pos.x()))
            i = self.track_index_at(pos.y())
            tr = self.ctrl.project.tracks[i] if i is not None else None
            g = self.ctrl.gap_at(tr.id, t) if tr is not None else None
            if not d["add"]:
                self.set_selection([])
            self.set_channels([tr.id] if tr is not None else [], "add" if d["add"] else "set")
            self.gap = (tr.id, g[0], g[1]) if g else None
            self.seek_requested.emit(t)
            self.update()
            return
        if not d or not d.get("active"):
            self.update()
            return
        proj = self.ctrl.project
        if d["type"] == "move" and (abs(d["dt"]) > 1e-6 or d["dtrack"]):
            moves = {}
            for cid in d["ids"]:
                c = proj.clips[cid]
                moves[cid] = (c.start + d["dt"], proj.tracks[self._dest_track(c, d)].id)
            self.ctrl.move_clips(moves)
        elif d["type"] == "trim":
            t = d["new_start"] if d["edge"] == "left" else d["new_end"]
            self.ctrl.trim_clip(d["clip"], d["edge"], t, linked=d.get("linked", True), overwrite=True)
        elif d["type"] == "topic_edge":
            self.ctrl.move_topic_start(d["marker"], d["new_t"])
        elif d["type"] == "ripple":
            self.ctrl.ripple_trim(d["clip"], d["edge"], d["t"], linked=d.get("linked", True))
        elif d["type"] == "roll":
            self.ctrl.roll_edit(d["right"], d["t"])
        elif d["type"] == "slip" and abs(d["dt"]) > 1e-6:
            self.ctrl.slip_clip(d["clip"], d["dt"])
        elif d["type"] == "slide" and abs(d["dt"]) > 1e-6:
            self.ctrl.slide_clip(d["clip"], d["dt"])
        self.update()

    def mouseDoubleClickEvent(self, e):
        pos = self._rmap(e.position())
        if pos.x() < self.HEADER_W and pos.y() >= self.RULER_H:   # doble clic en el nombre: renombrar
            i = self.track_index_at(pos.y())
            if i is not None:
                self._rename_track(self.ctrl.project.tracks[i])
                return
        m = self.marker_at(pos) or self.topic_at(pos)[0]
        if m:
            self._rename_marker(m)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Alt and self._nudge is not None:   # ⇆ al soltar Alt se aplica ya
            self._nudge_commit()
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        if self._nudge is not None:
            self._nudge_commit()
        super().focusOutEvent(e)

    def leaveEvent(self, _e):
        if self._nudge is not None:
            self._nudge_commit()
        if getattr(self, "_hover_clip", ""):
            self._hover_clip = ""
            self.update()
        if self._hover_topic:
            self._hover_topic = ""
            self.update()

    def _header_click(self, pos: QPointF, e):
        i = self.track_index_at(pos.y())
        if i is None:
            return
        tr = self.ctrl.project.tracks[i]
        if e.button() == Qt.RightButton:
            self._track_menu(tr, e.globalPosition().toPoint())
            return
        lock_r, vis_r = self._header_buttons(i)
        if tr.kind == TRACK_AUDIO and self._solo_rect(i).contains(pos):
            self.ctrl.set_track_props(tr.id, "Solo de pista", solo=not tr.solo)
            return
        if lock_r.contains(pos):
            self.ctrl.set_track_props(tr.id, "Desbloquear pista" if tr.locked else "Bloquear pista",
                                      locked=not tr.locked)
        elif vis_r.contains(pos):
            if tr.kind != TRACK_AUDIO:
                self.ctrl.set_track_props(tr.id, "Mostrar/ocultar pista", hidden=not tr.hidden)
            else:
                self.ctrl.set_track_props(tr.id, "Silenciar pista", muted=not tr.muted)
        elif e.button() == Qt.LeftButton:            # 🎚 el canal: clic = solo este (otra vez = ninguno); Ctrl = añadir
            if e.modifiers() & Qt.ControlModifier:
                self.set_channels([tr.id], "toggle")
            else:
                self.set_channels([] if self.channels == {tr.id} else [tr.id])

    # ------------------------------------------------------------- menús
    CLIP_LABELS = [("Naranja", "#e8742f"), ("Amarillo", "#d9b43a"), ("Lima", "#9fc24a"), ("Verde", "#4f9d5d"),
                   ("Verde azulado", "#3c9a94"), ("Azul", "#3f6fb5"), ("Morado", "#7a5bb8"), ("Rosa", "#c4598f"),
                   ("Marrón", "#8a5a3c"), ("Gris", "#6b6f78")]

    def _clip_menu(self, clip, global_pos):
        """Clic derecho en un clip: ordenado y limpio como el de DaVinci Resolve (y lo nuestro al final)."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        if clip and clip.id not in self.selected:
            self.set_selection(self.ctrl.linked_ids([clip.id]) if self.linked else [clip.id])
        ids = sorted(self.selected)
        win = self.window()
        has = lambda name: hasattr(win, name)   # noqa: E731
        if clip:
            proj = self.ctrl.project
            sel = sorted(self.selected) if clip.id in self.selected else [clip.id]
            # --- compuesto
            if self.ctrl.is_compound(clip.id):
                menu.addAction("Deshacer clip compuesto", lambda: self.set_selection(self.ctrl.break_compound(clip.id)))
            else:
                menu.addAction("Crear clip compuesto…", lambda: self.compound_requested.emit(sel))
            menu.addSeparator()
            # --- portapapeles
            if has("_copy"):
                menu.addAction("Copiar\tCtrl+C", lambda: win._copy(False))
                pa = menu.addAction("Pegar\tCtrl+V", win._paste)
                pi = menu.addAction("Pegar e insertar\tCtrl+Mayús+V", win._paste_insert)
                menu.addAction("Insertar espacio", win._insert_gap)
                pt = menu.addAction("Pegar atributos…\tAlt+V", win._paste_attributes)
                menu.addAction("Eliminar atributos…", win._remove_attributes)
                for a in (pa, pi, pt):
                    a.setEnabled(bool(getattr(self.ctrl, "clipboard", None)))
                menu.addAction("Cortar\tCtrl+X", lambda: win._copy(True))
                menu.addAction("Cortar y propagar\tCtrl+Mayús+X", win._cut_ripple)
            menu.addSeparator()
            # --- eliminar
            menu.addAction("Eliminar seleccionados\tSupr", lambda: self.ctrl.delete_clips(ids))
            menu.addAction("Eliminar y propagar\tMayús+Supr", lambda: self.ctrl.delete_clips(ids, ripple=True))
            kinds = {proj.track(proj.clips[i].track_id).kind for i in self.ctrl.linked_ids(ids) if i in proj.clips}
            if TRACK_AUDIO in kinds and TRACK_VIDEO in kinds and has("_delete_part"):   # imagen + sonido juntos
                menu.addAction("Eliminar solo el audio", lambda: win._delete_part("audio"))
                menu.addAction("Eliminar solo el video", lambda: win._delete_part("video"))
            menu.addSeparator()
            # --- el clip
            act_on = menu.addAction("Activar/desactivar clip\tD", lambda: win._toggle_enabled())
            act_on.setCheckable(True)
            act_on.setChecked(all(proj.clips[i].enabled for i in ids))
            any_locked = any(proj.clips[i].locked for i in ids)
            all_locked = all(proj.clips[i].locked for i in ids)     # igual que Ctrl+L: si hay mezcla, bloquea
            lk = menu.addAction("Bloquear clip\tCtrl+L", lambda: self.ctrl.set_clip_props(
                ids, "Bloquear clip", locked=not all_locked))
            lk.setCheckable(True)
            lk.setChecked(any_locked)
            menu.addAction("Dividir en el cabezal\tS", lambda: self.ctrl.split(self.playhead, ids))
            vids_sc = [i for i in ids if i in proj.clips and proj.clips[i].text is None
                       and proj.media_of(proj.clips[i]) is not None and proj.media_of(proj.clips[i]).kind == KIND_VIDEO
                       and proj.track(proj.clips[i].track_id).kind == TRACK_VIDEO]
            if vids_sc:
                sc = menu.addMenu("✂ Cortar en los cambios de escena")
                sc.addAction("Cortes claros (cambio de plano o de escena)",
                             lambda: self.scene_cuts_requested.emit(vids_sc, "normal"))
                sc.addAction("También cambios más suaves (menú de pausa, fundidos)",
                             lambda: self.scene_cuts_requested.emit(vids_sc, "alta"))
                sc.addSeparator()
                sc.addAction("⚑ Solo poner marcadores en cada cambio",
                             lambda: self.scene_cuts_requested.emit(vids_sc, "normal+marcas"))
            menu.addAction("Cambiar duración…\tCtrl+D", win._change_duration)
            m_ = proj.media_of(clip)
            fol = [i for i in ids if i in proj.clips and proj.clips[i].text is None
                   and proj.track(proj.clips[i].track_id).kind == TRACK_VIDEO
                   and proj.media_of(proj.clips[i]) is not None and proj.media_of(proj.clips[i]).kind == KIND_VIDEO
                   and proj.media_of(proj.clips[i]).width > proj.media_of(proj.clips[i]).height * 1.1
                   and proj.height > proj.width]
            if fol and has("follow_action"):       # 🎯 Shorts / edits: llenar en vertical siguiendo la acción
                menu.addAction("🎯 Encuadre vertical que sigue la acción", lambda: win.follow_action(fol))
                if any((proj.clips[i].layout or {}).get("follow") for i in fol):
                    menu.addAction("Quitar «sigue la acción» (recorte centrado)",
                                   lambda: [self.ctrl.set_follow(i, None, "Quitar «sigue la acción»") for i in fol])
            if m_ is not None and (m_.gen or {}).get("kind") in ("solid", "linear", "radial") and has("open_generator"):
                gens = [i for i in ids if i in proj.clips and (getattr(proj.media_of(proj.clips[i]), "gen", None) or {})
                        .get("kind") in ("solid", "linear", "radial")]
                menu.addAction("🟦 Cambiar color…", lambda: win.open_generator(dict(m_.gen), gens))
            if clip.text is None and m_ is not None and m_.kind != "image":
                menu.addAction("Cambiar velocidad…", win._change_speed)
                self._speed_menu(menu, clip, ids)
            if any(proj.track(proj.clips[i].track_id).kind == TRACK_AUDIO or
                   (proj.media_of(proj.clips[i]) and proj.media_of(proj.clips[i]).has_audio) for i in ids):
                menu.addSeparator()
                menu.addAction("Normalizar volumen…", win._normalize)
                if has("open_silence"):
                    sa = menu.addAction("✂ Eliminar silencios (y juntar lo de detrás)…	Ctrl+Mayús+Supr", win.open_silence)
                    sa.setToolTip("Quita los silencios de este audio y pega lo de detrás (como el ripple de Resolve). "
                                  "La IA reconoce tu voz: no se come el principio ni el final de las palabras.")
            menu.addSeparator()
            cm = menu.addMenu("Color de clip")
            for name, col in self.CLIP_LABELS:
                pm = QPixmap(12, 12)
                pm.fill(QColor(col))
                a = cm.addAction(QIcon(pm), name, lambda c_=col: win._set_label(ids, c_))
                a.setCheckable(True)
                a.setChecked(clip.label == col)
            cm.addSeparator()
            cm.addAction("Sin color", lambda: win._set_label(ids, ""))
            menu.addSeparator()
            # --- vínculo
            sel_c = [proj.clips[i] for i in ids if i in proj.clips]
            if any(c.link and self.ctrl.partners(proj, c) for c in sel_c):
                menu.addAction("Desvincular audio y video", lambda: self.ctrl.unlink_clips(ids))
            elif len(sel_c) >= 2:
                menu.addAction("Vincular clips", lambda: self.ctrl.link_clips(ids))
            can_sep = [c.id for c in sel_c if not c.link and proj.track(c.track_id).kind == TRACK_VIDEO
                       and proj.media_of(c) is not None and proj.media_of(c).has_audio]
            if can_sep:
                menu.addAction("Separar el audio a una pista de audio", lambda: self.ctrl.separate_audio(can_sep))
            menu.addSeparator()
            # --- buscar / información
            menu.addAction("Buscar en el panel multimedia\tAlt+F", win._find_in_media)
            menu.addAction("Atributos del clip…", win._clip_info)
            if len(ids) == 1:
                menu.addAction("Nota…", lambda: self._edit_note(clip))
            menu.addSeparator()
            # --- lo nuestro: imagen, transición, seguimiento, ritmo, IA
            vis_ids = [i for i in ids if proj.clips[i].text is None and
                       proj.track(proj.clips[i].track_id).kind == TRACK_VIDEO]
            self._transition_menu(menu, clip, global_pos)
            if vis_ids:
                tm = menu.addMenu("Transformar imagen")
                for key, (name, *_rest) in self.ctrl.TRANSFORMS.items():
                    a = tm.addAction(name, lambda k=key: self.ctrl.transform_clips(vis_ids, k))
                    a.setToolTip("Otro aspecto (color, grano, viñeta y encuadre con zoom): la imagen deja de ser "
                                 "una copia tal cual. Se puede volver al original.")
                tm.setToolTipsVisible(True)
                tm.addSeparator()
                back = tm.addAction("Volver al original", lambda: self.ctrl.restore_original(vis_ids))
                back.setEnabled(any((proj.clips[i].fx or {}).get("orig") for i in vis_ids))
            if m_ is not None and m_.kind != KIND_AUDIO and clip.text is None:
                menu.addAction("Seguir personaje u objeto…", lambda: self.track_requested.emit(clip.id))
            self._rhythm_menu(menu, sel_c)
            ai = menu.addMenu("✨ IA")
            if m_ is not None and m_.kind == KIND_VIDEO and clip.text is None and                     proj.track(clip.track_id).kind == TRACK_VIDEO:
                ai.addAction("✂ Recortar sujeto / quitar el fondo…", lambda: self.cutout_requested.emit(clip.id))
                if has("open_subject_fx"):
                    ai.addAction("✨ Efectos solo al personaje…", lambda: win.open_subject_fx(clip.id))
                ai.addAction("👤 Enseñar este personaje (silueta)…", lambda: self.silhouette_requested.emit(clip.id))
                if (clip.fx or {}).get("subject_mask"):
                    sm = clip.fx["subject_mask"]
                    ai.addAction("⇄ Invertir el recorte (sujeto ↔ fondo)", lambda: self.ctrl.set_clip_props(
                        [clip.id], "Invertir recorte", fx=dict(clip.fx, subject_mask=dict(sm, invert=not sm.get("invert")))))
                    ai.addAction("Quitar el recorte", lambda: self.ctrl.set_clip_props(
                        [clip.id], "Quitar recorte", fx={k: v for k, v in clip.fx.items() if k != "subject_mask"} or None))
                ai.addSeparator()
            snd = [i for i in self.ctrl.linked_ids(ids) if i in proj.clips and
                   proj.track(proj.clips[i].track_id).kind == TRACK_AUDIO]
            mids_kw = list(dict.fromkeys(proj.clips[i].media_id for i in self.ctrl.linked_ids(ids)
                                         if i in proj.clips and proj.clips[i].text is None))
            if mids_kw:
                ai.addAction("🔑 Buscar palabras clave…", lambda: self.keywords_requested.emit(mids_kw))
            if snd:
                if any((proj.clips[i].fx or {}).get("orig_media") for i in snd):
                    ai.addAction("🗣 Volver al sonido original (con el fondo)", lambda: self.ctrl.restore_dialogue(snd))
                else:
                    ai.addAction("🗣 Separar los diálogos del ruido de fondo", lambda: self.dialogue_requested.emit(snd))
                ai.addSeparator()
            self._add_ideas(ai, ids or [clip.id])
            self._add_image_style(ai, ids or [clip.id])
            if proj.track(clip.track_id).kind != TRACK_AUDIO:
                ai.addAction("Buscar momentos parecidos a este clip", lambda: self.similar_requested.emit(clip.id))
                ai.addAction("Usar como ejemplo de lo que busco (aprende con ✓/✗)…",
                             lambda: self.example_requested.emit(clip.id))
            self._add_phrase_action(ai)
            ai.addSeparator()
            vis = [i for i in ids if proj.track(proj.clips[i].track_id).kind == TRACK_VIDEO]
            if vis:
                ai.addAction(f"Dar más impacto visual a {'este clip' if len(vis) == 1 else f'estos {len(vis)} clips'}",
                             lambda: self.impact_requested.emit(vis))
            a = min(proj.clips[i].start for i in ids)
            b = max(proj.clips[i].end for i in ids)
            ai.addAction(f"Rehacer el B-roll de esta parte ({fmt_time(a, False)}–{fmt_time(b, False)})",
                         lambda: self.broll_range_requested.emit(a, b))
        else:
            pos = self.mapFromGlobal(global_pos)
            i = self.track_index_at(pos.y())
            tr = self.ctrl.project.tracks[i] if i is not None else None
            g = self.ctrl.gap_at(tr.id, max(0.0, self.t_for(pos.x()))) if tr is not None else None
            if g:
                self.gap = (tr.id, g[0], g[1])
                self.update()
                menu.addAction(f"⌫ Eliminar este hueco ({g[1] - g[0]:.1f} s)\tSupr",
                               lambda: self.delete_gap())
            if tr is not None:
                menu.addAction("⇤ Eliminar todos los huecos de esta pista",
                               lambda: self.ctrl.close_all_gaps(tr.id))
                menu.addSeparator()
            ai = menu.addMenu("✨ IA")
            if g is not None and tr is not None:
                self._add_gap_ai(ai, tr, g)
            else:
                self._add_phrase_action(ai)
            t_here = max(0.0, self.t_for(pos.x()))     # donde hiciste clic (no el cabezal)
            menu.addAction("Añadir marcador aquí", lambda: self.ctrl.add_marker(t_here))
            menu.addAction("T Añadir texto aquí", lambda: self._add_text_here(t_here))
        add_help_action(menu, "timeline", self.window())
        help_ui.exec_menu(menu, global_pos)

    def _rhythm_menu(self, menu, sel):
        """🥁 Ritmo de las canciones seleccionadas (clips de sonido)."""
        proj = self.ctrl.project
        aud = [c for c in sel if proj.track(c.track_id).kind == TRACK_AUDIO and c.text is None
               and proj.media_of(c) is not None]
        if not aud:
            return
        menu.addSeparator()
        mids = {c.media_id for c in aud}
        done = [c for c in aud if c.media_id in self.ctrl.rhythm]
        if mids - set(self.ctrl.rhythm):
            busy = mids & self.ctrl.rhythm_busy
            act = menu.addAction("🥁 Escuchando el ritmo…" if busy == mids - set(self.ctrl.rhythm)
                                 else "🥁 Reconocer el ritmo (golpes, compases, drop)",
                                 lambda: self.ctrl.analyze_rhythm(mids))
            act.setEnabled(not busy)
        if done:
            from ..ai import rhythm
            r = self.ctrl.rhythm[done[0].media_id]
            info = menu.addAction(f"🥁 {rhythm.summary(r)}")
            info.setEnabled(False)
            menu.addAction("📍 Poner marcadores en el drop y en cada parte",
                           lambda: self.ctrl.add_rhythm_markers([c.id for c in done]))
            menu.addAction("🔁 Volver a escuchar el ritmo", lambda: self.ctrl.analyze_rhythm(
                {c.media_id for c in done}, force=True))

    def _speed_menu(self, menu, clip, ids):
        proj = self.ctrl.project
        m = proj.media_of(clip)
        if clip.text is not None or m is None or m.kind == "image":
            return
        sm = menu.addMenu("🐢 Velocidad")
        for pct in (25, 50, 75, 100, 150, 200, 400):
            a = sm.addAction(f"{pct} %", lambda v=pct: self.ctrl.set_speed(ids, speed=v / 100))
            a.setCheckable(True)
            a.setChecked(abs(clip.speed * 100 - pct) < 0.5)
        sm.addSeparator()
        a = sm.addAction("◀ Hacia atrás", lambda: self.ctrl.set_speed(ids, reverse=not clip.reverse))
        a.setCheckable(True)
        a.setChecked(clip.reverse)
        if proj.track(clip.track_id).kind == TRACK_VIDEO and m.kind == "video":
            sm.addAction("❄ Congelar la imagen desde el cabezal\tMayús+R",
                         lambda: self.ctrl.freeze_frame(self.playhead, clip.id))
            if 0 < clip.speed < 0.999:
                a = sm.addAction("✨ Cámara lenta suave (inventa fotogramas)",
                                 lambda: self.ctrl.set_clip_props(ids, "Cámara lenta suave", smooth=not clip.smooth))
                a.setCheckable(True)
                a.setChecked(clip.smooth)
        if clip.speed > 0:
            rm = sm.addMenu("📈 Rampa de velocidad")
            for key, (name, _f) in self.ctrl.RAMPS.items():
                rm.addAction(name, lambda k=key: self._ramp(clip.id, k))

    def _ramp(self, clip_id: str, key: str):
        created = self.ctrl.speed_ramp(clip_id, key)
        if isinstance(created, list):
            self.set_selection(created)

    def _add_image_style(self, menu, ids):
        """🖼 Estilo de imagen: para las imágenes encima de un video (encima y desenfocado, esquina, costados,
        pantalla completa o sin animación) y ⏱ volver a ajustar la duración a la frase."""
        from ..core import overlay
        proj = self.ctrl.project
        imgs = []
        for i in ids:
            c = proj.clips.get(i)
            m = proj.media_of(c) if c is not None else None
            if c is None or m is None or m.kind != KIND_IMAGE or c.text is not None:
                continue
            if proj.track(c.track_id).kind != TRACK_VIDEO:
                return
            imgs.append(i)
        if not imgs:
            return
        sub = menu.addMenu("🖼 Estilo de imagen")
        for key, name in overlay.STYLES:
            sub.addAction(name, lambda k=key, ii=list(imgs): self.ctrl.set_image_style(ii, k))
        sub.addSeparator()
        sub.addAction("⏱ Ajustar a la frase", lambda ii=list(imgs): self.ctrl.set_image_style(ii, "phrase"))
        menu.addSeparator()

    def _add_ideas(self, menu, ids):
        """✨ Ideas para lo seleccionado: cómo meterlo (entrada, sombra, contorno, dónde), con un clic."""
        from ..ai import ideas
        proj = self.ctrl.project
        ordered = sorted((i for i in ids if i in proj.clips), key=lambda i: proj.clips[i].start)
        opts = ideas.ideas_for(proj, ordered)
        if not opts:
            return
        sub = menu.addMenu("✨ Ideas para esto")
        for o in opts:
            a = sub.addAction(o["label"], lambda ch=o["changes"], lab=o["label"]:
                              self.ctrl.batch_clip_props(ch, "✨ " + lab.split("·")[0].strip()))
            if o["tip"]:
                a.setToolTip(o["tip"])
                a.setStatusTip(o["tip"])
        sub.setToolTipsVisible(True)
        menu.addSeparator()

    def trans_at(self, pos) -> tuple[str, QRectF, str | None] | None:
        """La transición bajo el ratón: (id del clip de la derecha, su rectángulo, borde "l"/"r" o None)."""
        from ..core import transitions as TR
        proj = self.ctrl.project
        for i, tr in enumerate(proj.tracks):
            if tr.kind != TRACK_VIDEO or self.track_h(i) <= 0:
                continue
            y = self.track_y(i)
            if not (y + 17 <= pos.y() <= y + self.track_h(i) - 4):
                continue
            for _l, right, t in TR.pairs(proj, tr.id):
                xc = self.x_for(right.start)
                hw = max(7.0, t["dur"] * self.pps / 2)
                r = QRectF(xc - hw, y + 17, 2 * hw, self.track_h(i) - 21)
                if r.left() - 4 <= pos.x() <= r.right() + 4:
                    grip = min(7.0, r.width() / 4)
                    edge = "l" if pos.x() < r.left() + grip else ("r" if pos.x() > r.right() - grip else None)
                    return right.id, r, edge
        return None

    # ------------------------------------------------------------ ✦ pastilla «fx» (efectos del clip)
    def fx_chip_at(self, pos) -> str | None:
        for cid, r in self._fx_chips.items():
            if r.adjusted(-2, -2, 2, 2).contains(pos):
                return cid
        return None

    def select_fx(self, cid: str | None):
        self.set_selection([])
        self.sel_fx = cid
        self.update()

    @staticmethod
    def _fx_name(key: str) -> str:
        from .effects_panel import LOOKS as _L
        names = {k: t for k, t, _v, _h in _L}
        return names.get(key, {"shake": "≋ Temblor", "flash": "✦ Destello", "letterbox": "▭ Barras de cine",
                               "invert": "◑ Negativo"}.get(key, key))

    def delete_fx(self) -> bool:
        """Supr con la pastilla «fx» seleccionada: se quitan los efectos de ese clip (Ctrl+Z los devuelve)."""
        from ..core import effects as _EFX
        cid = self.sel_fx
        c = self.ctrl.project.clips.get(cid) if cid else None
        self.sel_fx = None
        if c is None or not _EFX.visible_of(c.fx):
            return False
        self.ctrl.set_clip_props([cid], "✦ Quitar efectos", fx=_EFX.without(c.fx, _EFX.visible_of(c.fx)))
        self.update()
        return True

    def _fx_menu(self, cid: str, global_pos):
        """Clic derecho en la pastilla «fx»: quitar un efecto concreto o todos."""
        from ..core import effects as _EFX
        c = self.ctrl.project.clips.get(cid)
        keys = _EFX.visible_of(c.fx) if c else []
        if not keys:
            return
        menu = QMenu(self)
        menu.addAction("Efectos de este clip:").setEnabled(False)
        for k in keys:
            menu.addAction(f"✕  Quitar {self._fx_name(k)}", lambda k=k: self.ctrl.set_clip_props(
                [cid], "✦ Quitar efecto", fx=_EFX.without(self.ctrl.project.clips[cid].fx, [k])))
        menu.addSeparator()
        menu.addAction("✕  Quitar todos los efectos   Supr", self.delete_fx)
        from . import help as _help
        _help.exec_menu(menu, global_pos)

    def select_transition(self, rid: str | None):
        self.set_selection([])
        self.sel_trans = rid
        self.update()

    def delete_transition(self) -> bool:
        """Supr / Ctrl+X con una transición seleccionada: se quita (los clips quedan igual)."""
        rid = self.sel_trans
        if not rid or rid not in self.ctrl.project.clips:
            self.sel_trans = None
            return False
        self.ctrl.set_transition([rid], None)
        self.sel_trans = None
        self.update()
        return True

    def _trans_menu(self, rid: str, global_pos):
        """Clic derecho en una transición: reemplazarla, su duración, quitarla y cómo las hace la IA."""
        from ..core import transitions as TR
        c = self.ctrl.project.clips.get(rid)
        cur = TR.of(c) if c else None
        if cur is None:
            return
        menu = QMenu(self)
        rm = menu.addMenu("🔁 Reemplazar por")
        for key, name, desc in TR.CATALOG:
            a = rm.addAction(name, lambda k=key: self.ctrl.set_transition([rid], k, float(cur["dur"])))
            a.setToolTip(desc)
            a.setCheckable(True)
            a.setChecked(cur["type"] == key)
        dm = menu.addMenu(f"⏱ Duración ({float(cur['dur']):.2f} s)")
        dm.addAction("➕ Más larga (+0,25 s)",
                     lambda: self.ctrl.set_transition([rid], cur["type"], float(cur["dur"]) + 0.25))
        dm.addAction("➖ Más corta (−0,25 s)",
                     lambda: self.ctrl.set_transition([rid], cur["type"], max(TR.MIN_DUR, float(cur["dur"]) - 0.25)))
        dm.addSeparator()
        for d in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
            a = dm.addAction(f"{d:g} s", lambda v=d: self.ctrl.set_transition([rid], cur["type"], v))
            a.setCheckable(True)
            a.setChecked(abs(float(cur["dur"]) - d) < 0.01)
        menu.addAction("✕ Quitar transición  (Supr / Ctrl+X)", lambda: (self.select_transition(rid),
                                                                       self.delete_transition()))
        menu.addSeparator()
        am = menu.addMenu("🤖 Las transiciones que pone la IA")
        sc = TR.ai_scale()
        for v, name in TR.AI_SCALES:
            a = am.addAction(f"{name} (×{v:g})", lambda vv=v: self._set_ai_trans_scale(vv))
            a.setCheckable(True)
            a.setChecked(abs(sc - v) < 0.01)
        am.addSeparator()
        n_ai = sum(1 for o in self.ctrl.project.clips.values() if ((o.fx or {}).get("trans") or {}).get("ai"))
        a = am.addAction(f"Aplicar ya a las {n_ai} que puso la IA", lambda: self.ctrl.rescale_ai_transitions(TR.ai_scale()))
        a.setEnabled(n_ai > 0)
        menu.exec(global_pos)

    def _set_ai_trans_scale(self, v: float):
        from ..core import transitions as TR
        TR.set_ai_scale(v)
        n = self.ctrl.rescale_ai_transitions(v)       # también las que ya puso (un Ctrl+Z las devuelve)
        win = self.window()
        if hasattr(win, "statusBar"):
            win.statusBar().showMessage(f"🤖 Transiciones de la IA: ×{v:g}" + (f" · {n} ajustadas" if n else ""), 6000)

    def _transition_menu(self, menu, clip, global_pos):
        """Transición en el corte más cercano al clic (inicio o final del clip)."""
        from ..core import transitions as TR
        proj = self.ctrl.project
        if not TR.is_visual(proj, clip):
            return
        x = self.mapFromGlobal(global_pos).x()
        nxt = next((o for o in proj.clips_on(clip.track_id) if abs(o.start - clip.end) < 1e-3), None)
        prev = TR.previous(proj, clip)
        near_end = nxt is not None and (prev is None or abs(x - self.x_for(clip.end)) < abs(x - self.x_for(clip.start)))
        right = nxt if near_end else (clip if prev is not None else None)
        if right is None or not TR.is_visual(proj, right):
            return
        cur = TR.of(right)
        tm = menu.addMenu("⧉ Transición " + ("al final" if near_end else "al inicio"))
        dur = float(cur["dur"]) if cur else 0.5
        for key, name, desc in TR.CATALOG:
            a = tm.addAction(name, lambda k=key: self.ctrl.set_transition([right.id], k, dur))
            a.setToolTip(desc)
            a.setCheckable(True)
            a.setChecked(bool(cur) and cur["type"] == key)
        if cur:
            tm.addSeparator()
            dm = tm.addMenu("Duración")
            for d in (0.25, 0.5, 1.0, 1.5, 2.0):
                a = dm.addAction(f"{d:g} s", lambda v=d: self.ctrl.set_transition([right.id], cur["type"], v))
                a.setCheckable(True)
                a.setChecked(abs(cur["dur"] - d) < 0.01)
            tm.addAction("✕ Quitar transición", lambda: self.ctrl.set_transition([right.id], None))

    def phrase_at(self, t: float) -> tuple[str, float] | None:
        """La frase de tu narración que suena en el instante t: (texto, inicio en la timeline)."""
        from ..core.subtitles import timeline_words
        p = self.ctrl.project
        for mid in p.transcripts:
            words = timeline_words(p, mid)
            if not words:
                continue
            k = next((i for i, w in enumerate(words) if w[0] <= t + 0.4 and w[1] >= t - 0.4), None)
            if k is None:
                continue
            a = k
            while a > 0 and not words[a - 1][2].rstrip().endswith((".", "?", "!", "…")) and k - a < 15:
                a -= 1
            b = k
            while b < len(words) - 1 and not words[b][2].rstrip().endswith((".", "?", "!", "…")) and b - k < 15:
                b += 1
            return " ".join(w[2] for w in words[a:b + 1]), words[a][0]
        return None

    def _add_gap_ai(self, menu, tr, g):
        """Hueco: sugerencias de tu biblioteca según lo que DICES durante ese hueco (no donde esté el cabezal)."""
        a, b = g
        said = []
        t = a
        while t < b:
            ph = self.phrase_at(t)
            if ph and ph[0] not in said:
                said.append(ph[0])
            t += 0.5
        text = " ".join(said)
        short = text if len(text) < 50 else text[:47] + "…"
        if tr.kind == TRACK_VIDEO:
            act = menu.addAction(f"💡 Ver sugerencias para este hueco ({b - a:.1f} s)",
                                 lambda: self.gap_ai_requested.emit(tr.id, a, b, False))
            act.setEnabled(bool(text))
            act = menu.addAction("⚡ Rellenar este hueco con lo mejor (según lo que digo)",
                                 lambda: self.gap_ai_requested.emit(tr.id, a, b, True))
            act.setEnabled(bool(text))
        if text:
            menu.addAction(f"🔎 Buscar en Medios: «{short}»", lambda: self.moments_requested.emit(text, a))
        else:
            act = menu.addAction("💡 Sugerencias (en este hueco no hablas o falta transcribir tu voz)")
            act.setEnabled(False)

    def _add_phrase_action(self, menu):
        ph = self.phrase_at(self.playhead)
        if ph:
            text, at = ph
            short = text if len(text) < 50 else text[:47] + "…"
            menu.addAction(f"🔎 Buscar material para lo que digo aquí: «{short}»",
                           lambda: self.moments_requested.emit(text, at))
        else:
            act = menu.addAction("🔎 Buscar material para lo que digo aquí (transcribe antes tu voz)")
            act.setEnabled(False)

    def delete_gap(self) -> bool:
        """Elimina el hueco seleccionado (Supr). Devuelve True si había uno."""
        if self.gap is None:
            return False
        tid, a, b = self.gap
        self.gap = None
        self.ctrl.close_gap(tid, a, b)
        self.update()
        return True

    def _add_text_here(self, t: float | None = None):
        created = self.ctrl.add_text(self.playhead if t is None else t, 4.0, "Texto")
        if isinstance(created, str):
            self.set_selection([created])

    def _edit_note(self, clip):
        text, ok = QInputDialog.getMultiLineText(self, "Nota del clip",
                                                 "Nota o instrucción para este clip:", clip.note)
        if ok:
            self.ctrl.set_clip_props([clip.id], "Editar nota", note=text.strip())

    def _track_menu(self, tr, global_pos):
        menu = QMenu(self)
        menu.addAction("Renombrar pista…", lambda: self._rename_track(tr))
        menu.addAction("⇤ Eliminar todos los huecos de esta pista", lambda: self.ctrl.close_all_gaps(tr.id))
        if tr.kind == TRACK_AUDIO:
            menu.addAction("⇤ Eliminar los huecos de TODAS las pistas de audio",
                           lambda: self.ctrl.close_gaps_on("audio"))
        menu.addAction("🔓 Desbloquear" if tr.locked else "🔒 Bloquear pista",
                       lambda: self.ctrl.set_track_props(tr.id, "Bloquear pista", locked=not tr.locked))
        menu.addSeparator()
        menu.addAction("Añadir pista de video", lambda: self.ctrl.add_track(TRACK_VIDEO))
        menu.addAction("Añadir pista de audio", lambda: self.ctrl.add_track(TRACK_AUDIO))
        menu.addAction("Eliminar esta pista (si está vacía)", lambda: self.ctrl.remove_track(tr.id))
        add_help_action(menu, "timeline", self.window())
        help_ui.exec_menu(menu, global_pos)

    TRACK_SUGGESTIONS = {
        TRACK_AUDIO: [("Narración", "voz"), ("Voz", "voz"), ("Música", "musica"), ("Efectos", "efectos"),
                      ("Ambiente", ""), ("Diálogos", ""), ("Audio del juego", "")],
        TRACK_VIDEO: [("Gameplay", ""), ("B-roll", ""), ("Cinemáticas", ""), ("Imágenes", ""), ("Capturas", "")],
    }

    def _rename_track(self, tr):
        """Renombrar a tu gusto; los nombres típicos salen como sugerencia (y dan su papel a la pista:
        «Música» baja sola cuando hablas, «Efectos» recibe los sonidos…)."""
        sugg = self.TRACK_SUGGESTIONS.get(tr.kind, [])
        cur = self.track_badge(self.ctrl.project.tracks.index(tr))[1]
        items = [cur] + [n for n, _r in sugg if n != cur]
        name, ok = QInputDialog.getItem(self, "Renombrar pista", "Nombre (escribe el que quieras o elige uno):",
                                        items, 0, True)
        name = (name or "").strip()
        if not ok or not name:
            return
        role = next((r for n, r in sugg if n.lower() == name.lower()), None)
        props = {"name": name}
        if role is not None and tr.kind == TRACK_AUDIO:
            props["role"] = role
            if role == "musica" and tr.duck_db is None:
                props["duck_db"] = -12.0
            if role == "voz" and not tr.fx:
                props["fx"] = {"eq": True, "compress": True}     # voz más clara (se quita en el inspector)
        self.ctrl.set_track_props(tr.id, "Renombrar pista", **props)

    def _marker_menu(self, m, global_pos):
        menu = QMenu(self)
        if m.kind == "topic":
            menu.addAction("Cambiar tema…", lambda: self._rename_marker(m))
            menu.addAction("Ir al inicio del tema", lambda: self.seek_requested.emit(m.time))
            menu.addAction("Quitar este tema (se une al anterior)", lambda: self.ctrl.remove_topic(m.id))
            menu.addAction("Quitar todos los temas", self.ctrl.remove_all_topics)
            menu.addSeparator()
            menu.addAction("◎ Temas: quedarme o mandar a Medios…", lambda: self.topics_requested.emit(m.label))
        else:
            menu.addAction("Renombrar marcador…", lambda: self._rename_marker(m))
            menu.addAction("Ir al marcador", lambda: self.seek_requested.emit(m.time))
            menu.addAction("Eliminar marcador", lambda: self.ctrl.remove_marker(m.id))
        help_ui.exec_menu(menu, global_pos)

    def _rename_marker(self, m):
        if m.kind == "topic":
            from ..ai.topic_detection import TOPICS, topic_color
            names = list(TOPICS)
            if m.label not in names:
                names.insert(0, m.label)
            text, ok = QInputDialog.getItem(self, "Tema", "Tema de esta parte (puedes escribir otro):",
                                            names, names.index(m.label), True)
            if ok and text.strip():
                label = text.strip().upper()
                self.ctrl.update_marker(m.id, label=label, color=topic_color(label), origin="user")
            return
        text, ok = QInputDialog.getText(self, "Marcador", "Texto del marcador:", text=m.label)
        if ok:
            self.ctrl.update_marker(m.id, label=text.strip())

    # ------------------------------------------- arrastrar desde biblioteca
    @staticmethod
    def _file_paths(md) -> list[str]:
        """Archivos de video, audio o imagen arrastrados desde Windows."""
        from ..core.model import kind_for_path
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and kind_for_path(u.toLocalFile())]

    def _fx_targets(self, pos) -> list[str]:
        c, _part = self.clip_at(pos)
        if c is None:
            return []
        return sorted(self.selected) if c.id in self.selected else [c.id]

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(EFFECT_MIME):
            e.acceptProposedAction()
            return
        if e.mimeData().hasFormat(SEGMENT_MIME) or e.mimeData().hasFormat(MEDIA_MIME) or \
                self._file_paths(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        pos = self._rmap(e.position())
        if e.mimeData().hasFormat(EFFECT_MIME):     # un efecto: se ilumina el clip (o la selección) que lo recibe
            self._fx_drop = self._fx_targets(pos)
            self.update()
            e.acceptProposedAction()
            return
        t = max(0.0, self._snap(self.t_for(pos.x()), self._snap_targets(set())))
        i = self.track_index_at(pos.y())
        if i is None and pos.y() >= self.track_y(len(self.ctrl.project.tracks)) and \
                not e.mimeData().hasFormat(SEGMENT_MIME):
            i = "new"          # debajo de la última pista: pista nueva
        self._drop = (i, t)
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, _e):
        self._drop = None
        self._fx_drop = None
        self.update()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(EFFECT_MIME):
            ids = self._fx_targets(self._rmap(e.position()))
            self._fx_drop = None
            self.update()
            e.acceptProposedAction()
            key = md.data(EFFECT_MIME).data().decode()
            if ids and key:
                self.set_selection(ids)
                self.effect_dropped.emit(key, ids)
            return
        if md.hasFormat(SEGMENT_MIME):      # un momento arrastrado desde «🔎 Momentos»
            mid, a, b = md.data(SEGMENT_MIME).data().decode().split("|")
            _i, t = self._drop or (None, 0.0)
            self._drop = None
            cid = self.ctrl.place_segment(mid, float(a), max(0.2, float(b) - float(a)), "insert", t)
            if isinstance(cid, str):
                self.set_selection([cid])
            e.acceptProposedAction()
            self.update()
            return
        if md.hasFormat(MEDIA_MIME):
            ids = [i for i in md.data(MEDIA_MIME).data().decode().split(",") if i]
        else:   # desde el Explorador de Windows: se importan al momento y se colocan
            ids = self.ctrl.import_now(self._file_paths(md))
        i, t = self._drop or (None, 0.0)
        self._drop = None
        if i == "new":
            created = self.ctrl.add_media(ids, None, t, new_track=True)
            win = self.window()
            if hasattr(win, "_ensure_timeline_size"):
                win._ensure_timeline_size()
        else:
            track_id = self.ctrl.project.tracks[i].id if i is not None else None
            proj = self.ctrl.project
            imgs = [x for x in ids if proj.media.get(x) is not None and proj.media[x].kind == KIND_IMAGE]
            if track_id is not None and imgs and len(imgs) == len(ids) and proj.track(track_id).kind == TRACK_VIDEO:
                # 🖼 imagen sobre un video: dura lo que dura la frase, con su estilo (core/overlay.py)
                created = self.ctrl.add_image_overlay(imgs, track_id, t)
            else:
                created = self.ctrl.add_media(ids, track_id, t)
        if isinstance(created, list):
            self.set_selection(created)
        e.acceptProposedAction()
        self.update()


from PySide6.QtWidgets import QToolButton as _QToolButton  # noqa: E402


class _SizeButton(_QToolButton):
    """Botón «🎞 ↕» / «🔊 ↕»: clic = barrita para dejar esas pistas del alto exacto que quieras (y tamaños
    rápidos) · rueda del ratón encima = más grandes / más pequeñas."""

    def __init__(self, tl, key: str, text: str, what: str):
        super().__init__(tl)
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidgetAction
        self.tl, self.key = tl, key
        self.setText(text)
        self.setToolTip(f"Alto de las pistas de {what}: clic = elegir el tamaño · rueda encima = más / menos")
        self.setPopupMode(_QToolButton.InstantPopup)
        menu = QMenu(self)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel()
        lay.addWidget(self.label)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(28, 160)
        self.slider.setMinimumWidth(190)
        self.slider.valueChanged.connect(lambda v: self.tl._set_track_size(self.key, v, fit=False))
        self.slider.sliderReleased.connect(lambda: self.tl._set_track_size(self.key, self.slider.value()))
        lay.addWidget(self.slider)
        row = QHBoxLayout()
        for name, h in (("Pequeñas", 36), ("Normales", 54), ("Grandes", 80), ("Enormes", 110)):
            b = QPushButton(name)
            b.setObjectName("flat")
            b.clicked.connect(lambda _=False, hh=h: self.tl._set_track_size(self.key, hh))
            row.addWidget(b)
        lay.addLayout(row)
        act = QWidgetAction(menu)
        act.setDefaultWidget(box)
        menu.addAction(act)
        menu.aboutToShow.connect(self.sync)
        menu.aboutToHide.connect(lambda: self.tl._set_track_size(self.key, getattr(self.tl, self.key)))
        self.setMenu(menu)
        self.what = what
        self.sync()

    def sync(self):
        h = int(getattr(self.tl, self.key))
        self.label.setText(f"Alto de las pistas de {self.what}: <b>{h} px</b>")
        if self.slider.value() != h:
            self.slider.blockSignals(True)
            self.slider.setValue(h)
            self.slider.blockSignals(False)

    def wheelEvent(self, e):
        step = 6 if e.angleDelta().y() > 0 else -6
        self.tl._set_track_size(self.key, int(getattr(self.tl, self.key)) + step)
        e.accept()
