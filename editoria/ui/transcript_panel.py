"""
Panel «Texto»: la transcripción sincronizada con la timeline.

- La palabra que está sonando se resalta.
- Clic en una palabra: el cabezal salta a ese momento.
- Doble clic: corregir la palabra (los tiempos no cambian).
- Las palabras ya cortadas aparecen tachadas en gris; las que tienen una sugerencia, coloreadas.
- ✂ Editar con el texto: lo que se va a quitar sale TACHADO EN ROJO. Clic en lo tachado = se queda; clic en algo
  sugerido sin tachar = se tacha; selecciona texto y pulsa Supr = lo tachas tú. «✂ Cortar lo tachado» lo quita del
  video (en todas las pistas, un solo Ctrl+Z).
- «📋 Resumen»: solo los sitios con algo que quitar (ui/cut_summary.py).
"""
from __future__ import annotations

import bisect
import os
import unicodedata

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from ..ai import repetition_detection, voice_cleanup, word_fix
from ..core import mapping, subtitles
from ..core.model import SUG_PENDING
from . import help as help_ui
from .common import SUGGESTION_COLORS, fmt_time
from .help import add_help_action, set_help
from .voice_panel import cut_kinds

STRUCK = QColor("#ff7b72")      # lo que se va a quitar


def _norm(s: str) -> str:
    """Para buscar: minúsculas, sin tildes y sin signos («Análisis.» → «analisis»)."""
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(ch for ch in s if ch.isalnum())


class _An:
    """Una aparición de la palabra i (índice en la transcripción) en el texto. tm = momento de la línea de tiempo
    donde suena su centro; a/b = principio y fin (None si está cortada). k = su posición en el texto, en el orden de
    la línea de tiempo. cid = el clip donde está (si hay copias, distingue cuál)."""
    __slots__ = ("i", "cid", "tm", "a", "b", "seg", "k", "p0", "n")

    def __init__(self, i, cid, tm, a, b, seg):
        self.i, self.cid, self.tm, self.a, self.b, self.seg = i, cid, tm, a, b, seg
        self.k = self.p0 = None
        self.n = 0


class _WordView(QTextBrowser):
    word_double_clicked = Signal(int)
    cut_requested = Signal()        # Supr / Retroceso con texto seleccionado
    clip_keys = None                # def(evento, probar) -> bool: Ctrl+X/C/V y Esc de «mover con el texto» (el panel)

    def event(self, e):
        # Ctrl+X/C/V de las palabras: que no los tome el atajo de la línea de tiempo (solo cuando aplican aquí)
        if e.type() == QEvent.ShortcutOverride and self.clip_keys and self.clip_keys(e, True):
            e.accept()
            return True
        return super().event(e)

    def mouseDoubleClickEvent(self, e):
        href = self.anchorAt(e.position().toPoint())
        if href.startswith("w"):
            self.word_double_clicked.emit(int(href[1:]))
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if self.clip_keys and self.clip_keys(e, False):
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.textCursor().hasSelection():
            self.cut_requested.emit()
            return
        super().keyPressEvent(e)


class TranscriptPanel(QWidget):
    moments_requested = Signal(str, float)   # frase y dónde va en la línea de tiempo
    search_marks_changed = Signal(list)      # 🔎 [(segundo, texto)] de cada aparición de la búsqueda (o [])

    def __init__(self, ctrl, engine, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.media_id: str | None = None
        self._starts: list[float] = []
        self._spans: list[tuple[float, float, int]] = []   # (t_ini, t_fin, índice) en la timeline
        self._pos: dict[int, tuple[int, int]] = {}         # índice -> (posición, longitud) en el texto
        self._current = -1
        self._dirty = True                                 # el texto se dibuja al verse (o si otro lo necesita)
        self._sig_built = None                             # lo que había al dibujar el texto (ver _firma)
        self._hits: list[tuple[int, float]] = []           # 🔎 apariciones en la timeline: (índice, segundo)
        self._hit_i = -1                                   # la aparición actual (-1 = ninguna)
        self._clip: dict | None = None                     # ✂/⧉ palabras recortadas o copiadas, pendientes de pegar
        self._anc: list[_An] = []                          # apariciones en el texto, en orden de la línea de tiempo
        self._key_k: dict = {}                             # (palabra, segundo de la timeline) -> aparición

        title = QLabel("Transcripción")
        title.setObjectName("title")
        self.btn_srt = QPushButton("Exportar .srt")
        self.btn_srt.setToolTip("Exportar los subtítulos (.srt) ajustados a la línea de tiempo: YouTube los acepta "
                                "directamente.")
        self.btn_srt.clicked.connect(self.export_srt)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.btn_srt)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Buscar en lo que dices…")
        self.search.setToolTip("Enter = siguiente · Mayús+Enter = anterior · sin distinguir mayúsculas ni tildes")
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)              # Enter / Mayús+Enter (ver eventFilter)
        self.search.textChanged.connect(lambda _t="": self._refresh_hits(reset=True))
        self.search_count = QLabel("")
        self.search_count.setToolTip("Qué aparición estás viendo y cuántas hay en la línea de tiempo")
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("Aparición anterior (Mayús+Enter)")
        self.btn_prev.clicked.connect(lambda: self._find_step(-1))
        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("Aparición siguiente (Enter)")
        self.btn_next.clicked.connect(lambda: self._find_step(1))
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.search_count)
        search_row.addWidget(self.btn_prev)
        search_row.addWidget(self.btn_next)

        self.view = _WordView()
        self.view.setOpenLinks(False)
        self.view.setOpenExternalLinks(False)
        self.view.anchorClicked.connect(self._on_anchor)
        self.view.word_double_clicked.connect(self._edit_at)
        self.view.cut_requested.connect(lambda: self._cross_words(self._words_at(None)))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.clip_keys = self._clip_key
        self.view.setProperty("own_menu", True)
        set_help(self, "texto")
        self.view.setStyleSheet("QTextBrowser { background: #16171a; border: 1px solid #2f3137; border-radius: 7px; "
                                "padding: 8px; }")
        f = QFont("Segoe UI", 11)
        self.view.document().setDefaultFont(f)


        # Tres vistas: la transcripción entera, «📋 Resumen» (solo lo que se puede quitar) y «📺 En pantalla» (los
        # bloques que salen en el video, sincronizados)
        from PySide6.QtWidgets import QButtonGroup, QStackedWidget
        from .captions_view import CaptionView
        from .cut_summary import CutSummary
        self.captions = CaptionView(ctrl, engine, lambda: self.media_id)
        self.summary = CutSummary(ctrl, engine, lambda: self.media_id, cut_kinds)
        # (la explicación, al pasar el ratón: en el panel solo el texto)
        self.view.setToolTip("Clic = ir a esa palabra · clic derecho = corregirla, volver a escucharla…\n"
                             "Tachado en rojo = se quitará · clic en lo tachado = se queda\n"
                             "Selecciona texto y pulsa Supr = tacharlo tú · Ctrl+Z deshace\n"
                             "Selecciona palabras · Ctrl+X = mover ese trozo · Ctrl+C = copiarlo · pon el cursor "
                             "donde vaya · Ctrl+V = pegarlo · Esc = cancelar")
        page_tr = QWidget()
        pl = QVBoxLayout(page_tr)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        pl.addLayout(search_row)
        pl.addWidget(self.view, 1)
        self.pages = QStackedWidget()
        self.pages.addWidget(page_tr)
        self.pages.addWidget(self.captions)
        self.pages.addWidget(self.summary)
        vrow = QHBoxLayout()
        vrow.setSpacing(4)
        self.view_btns = QButtonGroup(self)
        for k, (txt, tip) in ((0, ("Texto", "Todo lo que dices, con la palabra que suena resaltada y lo que se va a "
                                            "quitar tachado en rojo.")),
                              (2, ("Resumen", "Solo los sitios donde hay algo que quitar: frases que se repiten, "
                                              "que se medio repiten o que suenan parecido, muletillas… "
                                              "Casilla marcada = se quita.")),
                              (1, ("En pantalla", "Los bloques de texto que salen en el video (a lo mucho 3 "
                                                  "palabras en los Shorts): lo que suena ahora, grande y en "
                                                  "naranja; clic = ir ahí; doble clic = corregir."))):
            b = QPushButton(txt)
            b.setCheckable(True)
            b.setToolTip(tip)
            self.view_btns.addButton(b, k)
            vrow.addWidget(b)
        self.view_btns.idClicked.connect(self._set_view)
        vrow.addStretch()
        self.btn_cut = QPushButton("✂ Cortar")
        self.btn_cut.setObjectName("primary")
        self.btn_cut.setToolTip("Cortar lo tachado: quita del video todo lo tachado en rojo (en todas las pistas, "
                                "cerrando los huecos). Un Ctrl+Z lo deshace; en «Limpieza → Sugerencias → Aplicadas» "
                                "puedes devolver cualquier corte.")
        self.btn_cut.clicked.connect(self.cut_marked)
        vrow.addWidget(self.btn_cut)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(top)
        lay.addLayout(vrow)
        lay.addWidget(self.pages, 1)
        from .common import lazy_refresh
        self._cap_lazy = lazy_refresh(self.captions, self.captions.rebuild)
        self._sum_lazy = lazy_refresh(self.summary, self.summary.rebuild)
        ctrl.project_changed.connect(self._cap_lazy)
        ctrl.transcript_changed.connect(self._cap_lazy)
        ctrl.project_changed.connect(self._sum_lazy)
        ctrl.transcript_changed.connect(self._sum_lazy)
        engine.time_changed.connect(self.captions.highlight)
        view = str(QSettings("EditorIA", "EditorIA").value("texto/vista", "pantalla"))
        self._set_view({"pantalla": 1, "resumen": 2}.get(view, 0))

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._rebuild_si_visible)
        ctrl.project_changed.connect(self._timer.start)
        ctrl.transcript_changed.connect(self._on_transcript_changed)
        ctrl.project_changed.connect(lambda: self.search.text().strip() and self._refresh_hits(reset=False))
        engine.time_changed.connect(self._highlight)

    def _on_transcript_changed(self, mid: str):
        """La transcripción cambió: se vuelve a dibujar aunque la firma sea la misma (las listas pueden cambiar en sitio)."""
        if mid == self.media_id:
            self._dirty = True
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:                                    # cambió mientras estaba oculto: al verse, se pone al día
            self._rebuild()

    def _firma(self):
        """Todo lo que decide el texto dibujado. Si no cambia, no hace falta reconstruirlo (⚡ con miles de palabras:
        cada cambio de la timeline lo rehacía entero)."""
        p = self.ctrl.project
        mid = self.media_id
        tr = p.transcripts.get(mid) if mid else None
        st = p.subtitles
        sug = tuple((getattr(s, "id", None), s.status, s.kind, s.start, s.end, getattr(s, "alt_start", None),
                     getattr(s, "alt_end", None)) for s in p.suggestions if s.media_id == mid)
        same_st = st.media_id == mid
        return (mid, tr.get("words") if tr else None, tr.get("segments") if tr else None,
                mapping.media_layout_key(p, mid) if mid else None, sug,
                tuple(st.emphasis) if same_st else (), st.highlight,
                tuple(sorted(cut_kinds())))

    def _rebuild_si_visible(self):
        """Con el panel oculto no se reconstruye el texto (cuesta): se marca pendiente y se hace al mostrarse."""
        if not self._dirty and self._firma() == self._sig_built:
            return                                         # nada cambió en lo que se ve
        if self.isVisible():
            self._rebuild()
        else:
            self._dirty = True

    def ensure_built(self):
        """Para quien necesite el texto dibujado ya, esté o no visible el panel."""
        if self._dirty or self._firma() != self._sig_built:
            self._rebuild()

    def set_media(self, media_id: str):
        self.media_id = media_id or None
        self._clip = None                                  # lo recortado era de otra narración
        self._dirty = True
        if self.isVisible():
            self._rebuild()
        self._cap_lazy()
        self._sum_lazy()
        self._refresh_hits(reset=False)

    def refresh(self):
        """Cambiaron las reglas de qué se quita (casillas de ⚡): se vuelve a dibujar lo tachado."""
        self._timer.start()
        self._sum_lazy()

    def _set_view(self, k: int):
        self.pages.setCurrentIndex(k)
        self.view_btns.button(k).setChecked(True)
        QSettings("EditorIA", "EditorIA").setValue("texto/vista", {1: "pantalla", 2: "resumen"}.get(k, "transcripcion"))
        if k == 1:
            self._cap_lazy()
        elif k == 2:
            self._sum_lazy()

    # -------------------------------------------------------------- dibujo
    def _rebuild(self):
        self._dirty = False
        self._sig_built = self._firma()                    # (sin esto, cada consulta volvía a dibujar y perdía la selección)
        p = self.ctrl.project
        tr = p.transcripts.get(self.media_id) if self.media_id else None
        bar = self.view.verticalScrollBar()
        scroll = bar.value()
        doc = self.view.document()
        doc.clear()
        self._pos.clear()
        self._spans = []
        self._current = -1
        self._anc = []
        self._key_k = {}
        self.view.setExtraSelections([])
        self.btn_srt.setEnabled(bool(tr))
        if not tr:
            self.btn_cut.setEnabled(False)
            self.btn_cut.setText("✂ Cortar")
            self.view.setHtml("<p style='color:#71747d; margin-top:18px' align='center'>Sin transcripción<br>"
                              "<span style='font-size:9pt'>Transcríbela en «Limpieza»</span></p>")
            return
        words = tr.get("words", [])
        index = mapping.SourceIndex(p, self.media_id)
        # Qué palabras tienen una sugerencia pendiente y cuáles se van a quitar (tachadas en rojo)
        marks: dict[int, str] = {}
        struck: set[int] = set()
        mids = [(w[0] + w[1]) / 2 for w in words]
        on = cut_kinds()
        n_cut, secs = 0, 0.0
        for s in p.suggestions:
            if s.media_id == self.media_id and s.status == SUG_PENDING:
                spans = [(s.start, s.end)]
                if s.kind == "retake" and s.alt_start is not None:
                    spans.append((s.alt_start, s.alt_end))
                cut = voice_cleanup.will_cut(s, on)
                ca, cb = voice_cleanup.cut_range(s)
                if cut:
                    n_cut += 1
                    secs += cb - ca
                for a, b in spans:
                    for i in range(bisect.bisect_left(mids, a), bisect.bisect_right(mids, b)):
                        marks.setdefault(i, s.kind)
                        if cut and (a, b) == (ca, cb):
                            struck.add(i)
        self.btn_cut.setText(f"✂ Cortar ({n_cut} · ~{secs:.0f} s)" if n_cut else "✂ Cortar")
        self.btn_cut.setEnabled(bool(n_cut))

        st = p.subtitles
        emphasis = set(st.emphasis) if st.media_id == self.media_id else set()
        clip = self._clip if self._clip and self._clip["mid"] == self.media_id else None
        cur = QTextCursor(doc)
        cur.beginEditBlock()  # todo el texto de una vez (mucho más rápido)
        plain = QTextCharFormat()
        plain.setForeground(QColor("#e6e8ec"))
        stamp = QTextCharFormat()
        stamp.setForeground(QColor("#6b7280"))
        stamp.setFontPointSize(8.5)
        # El texto sale en el orden de la línea de tiempo; un párrafo por cada tramo seguido de un mismo segmento
        pres, segments = self._layout(tr)
        self._anc = pres
        grupos: list[list] = []        # [segmento, primera palabra del segmento (si no tiene apariciones), apariciones]
        for an in pres:
            if not grupos or grupos[-1][0] != an.seg:
                grupos.append([an.seg, None, []])
            grupos[-1][2].append(an)
        con_texto = {g[0] for g in grupos}
        for n, seg in enumerate(segments):          # segmentos sin palabras: su párrafo vacío, en su sitio
            if n not in con_texto:
                k_mas = next((j for j, g in enumerate(grupos) if g[0] > n), len(grupos))
                grupos.insert(k_mas, [n, seg[2], []])
        for gi, (_n, a_vacio, apariciones) in enumerate(grupos):
            if gi:
                cur.insertBlock()
            if apariciones:
                t0 = apariciones[0].tm
            elif a_vacio is not None and a_vacio < len(words):
                t0 = index.time((words[a_vacio][0] + words[a_vacio][1]) / 2)
            else:
                t0 = None
            cur.insertText((fmt_time(t0, frac=False) if t0 is not None else "cortado") + "  ", stamp)
            for an in apariciones:
                i = an.i
                w = words[i]
                fmt = QTextCharFormat(plain)
                fmt.setAnchor(True)
                fmt.setAnchorHref(f"w{an.k}")
                if an.a is None:
                    fmt.setForeground(QColor("#5c6370"))
                    fmt.setFontStrikeOut(True)
                else:
                    self._spans.append((an.a, an.b, an.k))
                    self._key_k.setdefault((i, round(an.tm, 3)), an.k)
                if i in marks:
                    c = QColor(SUGGESTION_COLORS.get(marks[i], QColor("#888")))
                    c.setAlpha(70)
                    fmt.setBackground(c)
                if clip and clip["i0"] <= i <= clip["i1"]:      # ✂/⧉ lo que vas a mover o copiar: fondo atenuado
                    fmt.setBackground(QColor("#3d3520" if not clip["copy"] else "#1f2f45"))
                    fmt.setForeground(QColor("#9ca3af"))
                if i in struck:
                    fmt.setFontStrikeOut(True)
                    fmt.setForeground(STRUCK)
                if i in emphasis:
                    fmt.setFontWeight(QFont.Bold)
                    fmt.setForeground(QColor(st.highlight))
                if len(w) > 3 and w[3] < 0.35:
                    fmt.setUnderlineStyle(QTextCharFormat.DotLine)
                    fmt.setUnderlineColor(QColor("#8b949e"))
                pos = cur.position()
                cur.insertText(w[2], fmt)
                an.p0, an.n = pos, len(w[2])
                self._pos.setdefault(i, (pos, an.n))       # (la primera aparición de cada palabra)
                cur.insertText(" ", plain)
        cur.endEditBlock()
        self._spans.sort()
        self._starts = [s[0] for s in self._spans]
        bar.setValue(scroll)
        self._highlight(self.engine.time)

    def _layout(self, tr: dict) -> tuple[list, list]:
        """Orden en que se muestra el texto = orden de la línea de tiempo. Cada clip de la narración aporta sus palabras
        (en su orden de sonido); las cortadas van junto a su vecina de archivo anterior (o en su segmento). Una palabra
        copiada sale una vez por cada copia, cada una con su tiempo. Devuelve (apariciones, segmentos)."""
        p = self.ctrl.project
        words = tr.get("words", [])
        n_w = len(words)
        segments = tr.get("segments") or [[0, 0, 0, n_w]]
        seg_of = [-1] * n_w
        for n, seg in enumerate(segments):
            for i in range(max(0, seg[2]), min(seg[3], n_w)):
                seg_of[i] = n
        mids = [(w[0] + w[1]) / 2 for w in words]
        vivas: list[_An] = []
        for c in mapping.clips_of_media(p, self.media_id):
            lo = bisect.bisect_left(mids, c.source_in - mapping.TOL)
            hi = bisect.bisect_left(mids, c.source_in + c.src_len)
            for i in range(lo, hi):
                if seg_of[i] < 0:
                    continue
                tm = mapping.map_time(p, self.media_id, mids[i], [c])
                if tm is None:
                    continue
                w = words[i]
                vivas.append(_An(i, c.id, tm, tm - (mids[i] - w[0]), tm + (w[1] - mids[i]), seg_of[i]))
        vivas.sort(key=lambda x: (x.tm, x.i))
        vistos: set = set()
        L: list[_An] = []                         # (sin repetir la misma aparición: pistas de vídeo y audio enlazadas)
        for an in vivas:
            clave = (an.i, round(an.tm, 3))
            if clave not in vistos:
                vistos.add(clave)
                L.append(an)
        primera: dict[int, int] = {}
        for k, an in enumerate(L):
            primera.setdefault(an.i, k)
        despues: dict[int, list] = {}             # cortadas que van justo detrás de la aparición k
        antes: dict[int, list] = {}               # cortadas que van justo delante de la aparición k
        cola: list = []
        i = 0
        while i < n_w:
            if seg_of[i] < 0 or i in primera:
                i += 1
                continue
            s = seg_of[i]
            j = i                                 # tramo cortado seguido del mismo segmento
            while j + 1 < n_w and seg_of[j + 1] == s and (j + 1) not in primera:
                j += 1
            tramo = [_An(x, None, None, None, None, s) for x in range(i, j + 1)]
            if i >= 1 and seg_of[i - 1] == s:     # tras su vecina de archivo anterior
                despues.setdefault(primera[i - 1], []).extend(tramo)
            elif j + 1 < n_w and seg_of[j + 1] == s:
                antes.setdefault(primera[j + 1], []).extend(tramo)
            else:                                 # sin vecina en su segmento: al principio de su segmento
                k_mas = next((k for k, an in enumerate(L) if an.seg > s), None)
                if k_mas is None:
                    cola.extend(tramo)
                else:
                    antes.setdefault(k_mas, []).extend(tramo)
            i = j + 1
        pres: list[_An] = []
        for k, an in enumerate(L):
            pres.extend(antes.get(k, []))
            pres.append(an)
            pres.extend(despues.get(k, []))
        pres.extend(cola)
        for k, an in enumerate(pres):
            an.k = k
        return pres, segments

    def _highlight(self, t: float):
        if self._dirty or not self._spans:      # texto pendiente de dibujar: se resalta al reconstruirlo
            return
        k = bisect.bisect_right(self._starts, t) - 1
        idx = self._spans[k][2] if k >= 0 and t <= self._spans[k][1] + 0.15 else -1
        if idx == self._current:
            return
        self._current = idx
        if idx < 0 or idx >= len(self._anc) or self._anc[idx].p0 is None:
            self.view.setExtraSelections([])
            return
        pos, length = self._anc[idx].p0, self._anc[idx].n
        sel = QTextEdit.ExtraSelection()
        cur = QTextCursor(self.view.document())
        cur.setPosition(pos)
        cur.setPosition(pos + length, QTextCursor.KeepAnchor)
        sel.cursor = cur
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#3b6fd8"))
        fmt.setForeground(QColor("white"))
        sel.format = fmt
        self.view.setExtraSelections([sel])
        if self.engine.playing:
            rect = self.view.cursorRect(cur)
            if not self.view.viewport().rect().adjusted(0, 20, 0, -20).contains(rect):
                bar = self.view.verticalScrollBar()
                bar.setValue(bar.value() + rect.top() - self.view.viewport().height() // 3)

    # ------------------------------------------------------------ acciones
    def _time_of(self, idx: int) -> float | None:
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        if not 0 <= idx < len(words):
            return None
        w = words[idx]
        mid = (w[0] + w[1]) / 2
        t = mapping.map_time(self.ctrl.project, self.media_id, mid)
        return None if t is None else t - (mid - w[0])

    def _edit_at(self, k: int):
        if 0 <= k < len(self._anc):
            self._edit_word(self._anc[k].i)

    def _on_anchor(self, url):
        href = url.toString()
        if href.startswith("w") and href[1:].isdigit() and int(href[1:]) < len(self._anc):
            an = self._anc[int(href[1:])]          # (la aparición pulsada: su tiempo en la línea de tiempo)
            if an.a is None:
                self.ctrl.message.emit("Esa palabra está cortada (no está en la timeline).")
                return
            self.engine.user_seek(max(0.0, an.a - 0.05))
            self._toggle_word(an.i)

    # ------------------------------------------------------- ✂ tachar con el texto
    def _covering(self, idx: int) -> list[tuple[object, tuple[float, float], bool]]:
        """Sugerencias pendientes que se pueden cortar y tocan esa palabra: (sugerencia, tramo de la palabra, ¿ese
        tramo se va a quitar?). En las tomas repetidas cada toma es un tramo."""
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        if not 0 <= idx < len(words):
            return []
        mid = (words[idx][0] + words[idx][1]) / 2
        on = cut_kinds()
        out = []
        for s in self.ctrl.project.suggestions:
            if s.media_id != self.media_id or s.status != SUG_PENDING or not s.cuttable:
                continue
            spans = [(s.start, s.end)] + ([(s.alt_start, s.alt_end)] if s.kind == "retake" and s.alt_start is not None
                                          else [])
            cut = voice_cleanup.will_cut(s, on)
            ca, cb = voice_cleanup.cut_range(s)
            for a, b in spans:
                if a <= mid <= b:
                    out.append((s, (a, b), cut and (a, b) == (ca, cb)))
        return out

    def _toggle_word(self, idx: int) -> bool:
        """Clic en una palabra con sugerencia: lo tachado se queda; lo sugerido sin tachar se tacha. En una toma
        repetida, tocar la toma que se queda la tacha a ella (y se queda la otra)."""
        cov = self._covering(idx)
        if not cov:
            return False
        crossed = [s for s, _span, c in cov if c]
        if crossed:
            self.ctrl.set_cross([s.id for s in crossed], False)
            return True
        s, (a, b), _c = min(cov, key=lambda x: x[1][1] - x[1][0])     # la sugerencia más pequeña
        if s.kind == "retake":
            self.ctrl.choose_take(s.id, 2 if (a, b) == (s.start, s.end) else 1)
        else:
            self.ctrl.set_cross([s.id], True)
        return True

    def _seguido(self, idxs: list[int]) -> bool:
        """¿Las palabras son un trozo seguido del texto (sin saltos por el orden nuevo)?"""
        self.ensure_built()
        rango = {i: r for r, i in enumerate(sorted(self._pos))}
        rs = sorted({rango[i] for i in idxs if i in rango})
        return bool(rs) and rs[-1] - rs[0] + 1 == len(rs)

    def _cross_words(self, idxs: list[int]):
        """✂ Tachar tú lo seleccionado: se quitará con «Cortar lo tachado»."""
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        if idxs and self.media_id and not self._seguido(idxs):
            self.ctrl.message.emit("Selecciona un trozo seguido del texto para tacharlo.")
            return
        idxs = [i for i in idxs if 0 <= i < len(words) and self._time_of(i) is not None]
        if not idxs or not self.media_id:
            return
        i0, i1 = idxs[0], idxs[-1]
        start = max(0.0, words[i0][0] - 0.02)
        end = repetition_detection._cut_end(words, i1)
        self.ctrl.add_manual_cut(self.media_id, start, end, " ".join(words[i][2] for i in range(i0, i1 + 1)))
        self.view.moveCursor(QTextCursor.Start)

    def cut_marked(self):
        """✂ Quita del video todo lo tachado (lo mismo que «⚡ Limpiar automáticamente», con tus cambios)."""
        on = cut_kinds()
        sugs = [s for s in self.ctrl.project.suggestions if s.media_id == self.media_id and
                voice_cleanup.will_cut(s, on)]
        if not sugs:
            self.ctrl.message.emit("No hay nada tachado que cortar.")
            return
        secs = sum(b - a for a, b in (voice_cleanup.cut_range(s) for s in sugs))
        if QMessageBox.question(self, "Cortar lo tachado",
                                f"Se quitarán {len(sugs)} fragmentos (~{secs:.0f} s) en TODAS las pistas, cerrando "
                                "los huecos.\n\nUn Ctrl+Z lo deshace todo; en «Limpieza → Sugerencias → Aplicadas» "
                                "puedes devolver cualquier corte.") != QMessageBox.Yes:
            return
        n = self.ctrl.apply_suggestions([s.id for s in sugs]) or 0
        if n:
            self.ctrl.message.emit(f"✂ {n} fragmentos quitados del video (~{secs:.0f} s).")

    def _edit_word(self, idx: int):
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        if 0 <= idx < len(words):
            old = words[idx][2]
            text, ok = QInputDialog.getText(self, "Corregir palabra", "Texto correcto:", text=old)
            if ok and text.strip() and text.strip() != old:
                new = text.strip()
                if word_fix.core(new) == new:        # escrita sin signos: conserva los de la original («análisis.»)
                    new = word_fix.with_punct(old, new)
                self.ctrl.edit_word(self.media_id, idx, new)
                word_fix.remember(old, text)

    # ------------------------------------------------------------ ✎ corregir una palabra (clic derecho)
    def _same_words(self, idx: int) -> list[int]:
        """Dónde más sale esa misma palabra (sin mirar mayúsculas ni signos)."""
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        k = word_fix.core(words[idx][2]).lower()
        return [i for i, w in enumerate(words) if word_fix.core(w[2]).lower() == k]

    def _replace_word(self, idx: int, new: str, everywhere: bool = False):
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        if not 0 <= idx < len(words):
            return
        old = words[idx][2]
        idxs = self._same_words(idx) if everywhere else [idx]
        n = self.ctrl.edit_word_texts(self.media_id, {i: word_fix.with_punct(words[i][2], new) for i in idxs})
        word_fix.remember(old, new)
        if everywhere:
            self.ctrl.message.emit(f"✎ «{word_fix.core(old)}» → «{word_fix.core(new)}» en {n} sitios.")

    def _edit_all(self, idx: int, suggestion: str = ""):
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        n = len(self._same_words(idx))
        text, ok = QInputDialog.getText(self, "Cambiar en todo el texto",
                                        f"Las {n} veces que sale «{word_fix.core(words[idx][2])}», cambiarlas por:",
                                        text=suggestion or word_fix.core(words[idx][2]))
        if ok and text.strip() and word_fix.core(text) != word_fix.core(words[idx][2]):
            self._replace_word(idx, text, everywhere=True)

    def _fix_options(self, word: str) -> list[tuple[str, str]]:
        """Lo que se puede proponer al momento: cómo la corregiste antes y, si no existe, la ortografía."""
        from ..core import spelling as SP
        from .spellcheck import current_lang
        opts = [(r, "como antes") for r in word_fix.learned(word)[:3]]
        c, lang = word_fix.core(word), current_lang()
        if c and lang != "off" and SP.ready(lang) and not SP.is_ok(c, lang):
            seen = {o.lower() for o, _w in opts}
            opts += [(s, "") for s in SP.suggest(c, lang, 4) if s.lower() not in seen]
        return opts[:6]

    def _add_fix_actions(self, menu: QMenu, idx: int, gpos):
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        w = words[idx][2]
        opts = self._fix_options(w)
        if opts:
            menu.addAction(f"Cambiar «{word_fix.core(w)}» por:").setEnabled(False)     # (título)
            for r, why in opts:
                menu.addAction(r + (f"    ({why})" if why else ""), lambda r=r: self._replace_word(idx, r))
        menu.addAction("🎙 Volver a escuchar esta palabra", lambda: self._relisten(idx, gpos))
        menu.addAction("✎ Escribir la correcta…", lambda: self._edit_word(idx))
        n = len(self._same_words(idx))
        if n > 1:
            menu.addAction(f"Cambiar en todo el texto ({n} veces)…", lambda: self._edit_all(idx))
        menu.addAction(f"Tener en cuenta «{word_fix.core(w)}» al transcribir", lambda: self._add_vocab(w))

    def _add_vocab(self, word: str):
        new = word_fix.add_vocabulary(word)
        self.ctrl.message.emit(f"«{word_fix.core(word)}» " + ("se tendrá en cuenta en las próximas transcripciones."
                                                             if new else "ya estaba entre tus palabras."))

    def _relisten(self, idx: int, gpos):
        """🎙 Whisper vuelve a escuchar solo ese trocito (de varias maneras) y te propone lo que oye."""
        p = self.ctrl.project
        tr = p.transcripts.get(self.media_id) or {}
        m = p.media.get(self.media_id)
        words = [list(w) for w in tr.get("words", [])]
        if m is None or not 0 <= idx < len(words):
            return
        job = getattr(self, "_fix_job", None)
        if job is not None and job.isRunning():
            self.ctrl.message.emit("Ya estoy escuchando otra palabra; un momento.")
            return
        from .jobs import BackgroundJob
        path, model, lang, old = m.path, tr.get("model") or "large-v3-turbo", tr.get("language") or "es", words[idx][2]
        self._fix_job = BackgroundJob(lambda progress, cancelled: word_fix.alternatives(
            path, words, idx, model, lang, progress, cancelled), self)
        self._fix_job.done.connect(lambda alts: self._show_alternatives(idx, old, alts, gpos))
        self._fix_job.failed.connect(lambda msg: self.ctrl.message.emit(f"No se pudo volver a escuchar: {msg}"))
        self.ctrl.message.emit(f"🎙 Escuchando otra vez «{word_fix.core(old)}»…")
        self._fix_job.start()

    def _show_alternatives(self, idx: int, old: str, alts: list, gpos):
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        if not 0 <= idx < len(words) or words[idx][2] != old:
            return                                       # (mientras tanto la cambiaste tú)
        self.ctrl.message.emit(f"🎙 «{word_fix.core(old)}»: {len(alts)} alternativa(s)." if alts else
                               f"🎙 En «{word_fix.core(old)}» no oigo otra cosa: escríbela tú si está mal.")
        menu = QMenu(self)
        menu.addAction(f"Lo que se oye en «{word_fix.core(old)}»:").setEnabled(False)
        for a in alts:
            menu.addAction(a, lambda a=a: self._replace_word(idx, a))
        if not alts:
            menu.addAction("No oigo nada distinto").setEnabled(False)
        menu.addSeparator()
        menu.addAction("✎ Escribir la correcta…", lambda: self._edit_word(idx))
        if alts and len(self._same_words(idx)) > 1:
            menu.addAction(f"Cambiar en todo el texto ({len(self._same_words(idx))} veces)…",
                           lambda: self._edit_all(idx, alts[0]))
        help_ui.exec_menu(menu, gpos)

    def _sel_ks(self) -> list[int]:
        """Apariciones (índices en el texto) que tocan la selección."""
        cur = self.view.textCursor()
        if not cur.hasSelection():
            return []
        a, b = cur.selectionStart(), cur.selectionEnd()
        return [an.k for an in self._anc if an.p0 is not None and an.p0 < b and an.p0 + an.n > a]

    def _anchors_at(self, pos) -> list[int]:
        """Apariciones seleccionadas con el ratón o, si no hay selección, la que está bajo el cursor."""
        self.ensure_built()
        ks = self._sel_ks()
        if ks or pos is None:
            return ks
        href = self.view.anchorAt(pos)
        return [int(href[1:])] if href.startswith("w") else []

    def _words_at(self, pos) -> list[int]:
        """Palabras (índices en la transcripción) de esas apariciones."""
        return sorted({self._anc[k].i for k in self._anchors_at(pos)})

    def _context_menu(self, pos):
        ks = self._anchors_at(pos)
        idxs = sorted({self._anc[k].i for k in ks})
        if not idxs or not self.media_id:
            menu = QMenu(self)
            if self._clip:
                menu.addAction("📋 Pegar aquí (Ctrl+V)", lambda: self._paste(self._word_at(pos)))
                menu.addSeparator()
            add_help_action(menu, "texto", self.window())
            help_ui.exec_menu(menu, self.view.viewport().mapToGlobal(pos))
            return
        cid = self._anc[ks[0]].cid                          # de qué clip es (si hay copias)
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
        st = self.ctrl.project.subtitles
        same_source = st.media_id == self.media_id
        all_emph = same_source and all(i in st.emphasis for i in idxs)
        label = " ".join(words[i][2] for i in idxs[:6]) + (" …" if len(idxs) > 6 else "")
        menu = QMenu(self)
        gpos = self.view.viewport().mapToGlobal(pos)
        if len(idxs) == 1:                                   # ✎ lo primero: corregirla
            self._add_fix_actions(menu, idxs[0], gpos)
            menu.addSeparator()
        menu.addAction("✂ Cortar para mover (Ctrl+X)", lambda: self._clip_words(idxs, False, cid))
        menu.addAction("⧉ Copiar (Ctrl+C)", lambda: self._clip_words(idxs, True, cid))
        if self._clip:
            menu.addAction("📋 Pegar aquí (Ctrl+V)", lambda: self._paste(self._word_at(pos)))
        menu.addSeparator()
        cov = [c for i in idxs for c in self._covering(i)]
        crossed = list({s.id: s for s, _span, c in cov if c}.values())
        if crossed:
            menu.addAction(f"✓ Que se quede «{label}» (quitar el tachado)",
                           lambda: self.ctrl.set_cross([s.id for s in crossed], False))
        takes = [(s, span) for s, span, _c in cov if s.kind == "retake"]
        if takes:
            s, span = takes[0]
            keep = 1 if span == (s.start, s.end) else 2
            menu.addAction("⭐ Quedarme con ESTA toma (tachar la otra)", lambda: self.ctrl.choose_take(s.id, keep))
            menu.addAction("Mantener las dos tomas", lambda: self.ctrl.set_cross([s.id], False))
        menu.addAction(f"✂ Tachar «{label}» (se quitará del video)  Supr", lambda: self._cross_words(idxs))
        menu.addSeparator()
        if all_emph:
            menu.addAction(f"Quitar resaltado de «{label}»", lambda: self.ctrl.set_emphasis(idxs, False))
        else:
            menu.addAction(f"⭐ Resaltar en subtítulos: «{label}»", lambda: self._emphasize(idxs))
        if len(idxs) == 1:
            menu.addAction("Ir a esta palabra", lambda: self._seek_anchor(ks[0]))
        menu.addSeparator()
        phrase = " ".join(words[i][2] for i in idxs).strip(" .,;:¡!¿?")
        at = self._anc[ks[0]].a
        menu.addAction(f"🔎 Buscar material para «{label}» (IA)",
                       lambda: self.moments_requested.emit(phrase, -1.0 if at is None else at))
        add_help_action(menu, "texto", self.window())
        help_ui.exec_menu(menu, self.view.viewport().mapToGlobal(pos))

    def _emphasize(self, idxs: list[int]):
        st = self.ctrl.project.subtitles
        if st.media_id != self.media_id:  # los subtítulos pasan a salir de esta narración
            self.ctrl.set_subtitle_style("Texto de los subtítulos", media_id=self.media_id, emphasis=[])
        self.ctrl.set_emphasis(idxs, True)
        if not self.ctrl.project.subtitles.enabled:
            self.ctrl.message.emit("Palabra resaltada. Activa los subtítulos en la pestaña «Subtítulos» "
                                   "para verla en el video.")

    def _seek_anchor(self, k: int):
        if 0 <= k < len(self._anc) and self._anc[k].a is not None:
            self.engine.user_seek(self._anc[k].a)

    # ------------------------------------------- ✂ mover / ⧉ copiar un trozo con el texto (Ctrl+X/C/V)
    def _tl_span(self, i0: int, i1: int, cid=None) -> tuple[float, float] | None:
        """Tramo de la línea de tiempo del trozo de palabras i0..i1 (una aparición seguida en el texto; «cid» = el clip
        de donde se cogió, si hay copias), con sus pausas: desde la mitad de la pausa de antes hasta la de después.
        None si una punta está cortada o no es un trozo seguido."""
        self.ensure_built()
        p = self.ctrl.project
        words = (p.transcripts.get(self.media_id) or {}).get("words", [])
        n = i1 - i0 + 1
        if not 0 <= i0 <= i1 < len(words):
            return None
        an = self._anc
        buenos = [k for k, x in enumerate(an) if x.i == i0 and x.a is not None and k + n <= len(an)
                  and an[k + n - 1].b is not None and all(an[k + t].i == i0 + t for t in range(n))]
        if not buenos:
            return None
        k0 = next((k for k in buenos if an[k].cid == cid), buenos[0]) if cid is not None else buenos[0]
        k1 = k0 + n - 1
        a, b = an[k0].a, an[k1].b
        pe = an[k0 - 1].b if k0 > 0 else None
        a = (pe + a) / 2 if pe is not None and pe <= a + 0.01 else max(0.0, a - 0.05)
        nx = an[k1 + 1].a if k1 + 1 < len(an) else None
        b = (b + nx) / 2 if nx is not None and nx >= b - 0.01 else b + 0.05
        return (a, b) if b - a > 0.05 else None

    def _tl_insert_boundary(self, k: int) -> float | None:
        """Momento de la línea de tiempo donde cae el hueco delante de la aparición k (en la pausa entre la de antes
        y ella). None si esa parte está cortada."""
        an = self._anc
        if not an:
            return None
        pred = an[k - 1] if k > 0 else None
        succ = an[k] if k < len(an) else None
        pe = pred.b if pred is not None else None
        ns = succ.a if succ is not None else None
        if pred is None:
            return ns
        if succ is None:
            return pe
        if pe is not None and ns is not None and ns >= pe - 0.01:
            return (pe + ns) / 2
        return ns if ns is not None else pe

    def _tl_insert_at(self, j: int) -> float | None:
        """Momento donde cae el hueco ANTES de la palabra j (su primera aparición en el texto)."""
        self.ensure_built()
        k = next((k for k, x in enumerate(self._anc) if x.i == j), len(self._anc))
        return self._tl_insert_boundary(k)

    def _boundary_at(self, pos_char: int) -> int:
        """Delante de qué aparición cae una posición del texto (la más cercana: el lado de la palabra donde está)."""
        self.ensure_built()
        for k, an in enumerate(self._anc):
            if an.p0 is None:
                continue
            if pos_char < an.p0:
                return k
            if pos_char <= an.p0 + an.n:
                return k if pos_char - an.p0 < an.n / 2 else k + 1
        return len(self._anc)

    def _word_at(self, pos) -> int | None:
        """Palabra bajo el ratón (para «Pegar aquí» con el menú del clic derecho); None = en el cursor."""
        href = self.view.anchorAt(pos)
        return int(href[1:]) if href.startswith("w") else None

    def _clip_words(self, idxs: list[int], copy: bool, cid=None):
        """Ctrl+X (mover) o Ctrl+C (copiar) de las palabras seleccionadas: quedan marcadas hasta pegar (Ctrl+V)."""
        if not idxs or not self.media_id:
            return
        i0, i1 = min(idxs), max(idxs)
        if self._tl_span(i0, i1, cid) is None:
            self.ctrl.message.emit("Esas palabras están cortadas o no forman un trozo seguido del texto.")
            return
        self._clip = {"mid": self.media_id, "i0": i0, "i1": i1, "copy": copy, "cid": cid}
        self._rebuild()
        words = self.ctrl.project.transcripts[self.media_id]["words"]
        label = " ".join(words[i][2] for i in range(i0, min(i1, i0 + 5) + 1)) + (" …" if i1 - i0 > 4 else "")
        self.ctrl.message.emit(("⧉ Copiado" if copy else "✂ Recortado") + f" «{label}». Pon el cursor en el texto y "
                               "pulsa Ctrl+V (Esc cancela).")

    def _clear_clip(self, redraw: bool = True):
        if self._clip is None:
            return
        self._clip = None
        if redraw and self.media_id:
            self._rebuild()

    def _paste(self, k: int | None = None):
        """Ctrl+V: pega lo recortado/copiado delante de la aparición k (o donde está el cursor)."""
        clip = self._clip
        if clip is None:
            self.ctrl.message.emit("Nada recortado ni copiado: selecciona palabras y pulsa Ctrl+X (mover) o Ctrl+C.")
            return
        if clip["mid"] != self.media_id:
            self._clear_clip(redraw=False)
            self.ctrl.message.emit("Lo recortado es de otra narración: se ha olvidado.")
            return
        self.ensure_built()
        span = self._tl_span(clip["i0"], clip["i1"], clip.get("cid"))
        if span is None:
            self._clear_clip()
            self.ctrl.message.emit("Esas palabras ya no están en la línea de tiempo.")
            return
        if k is None:
            k = self._boundary_at(self.view.textCursor().selectionStart())
        to = self._tl_insert_boundary(k)
        if to is None:
            self.ctrl.message.emit("No se puede pegar ahí: esa parte está cortada.")
            return
        if self.ctrl.move_range(span[0], span[1], to, copy=clip["copy"]):
            if clip["copy"]:
                self.ctrl.message.emit("⧉ Copia pegada (puedes volver a pegarla con Ctrl+V).")
            else:
                self._clear_clip()
                self.ctrl.message.emit("✂ Trozo movido con el texto (Ctrl+Z lo deshace).")

    def _clip_key(self, e, probar: bool) -> bool:
        """Ctrl+X/C con palabras seleccionadas, Ctrl+V con algo recortado y Esc para cancelar. Solo actúa con el foco
        en este texto; en el resto de la app siguen valiendo Ctrl+X/C/V de los clips. probar=True: solo pregunta."""
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        k = e.key()
        if k in (Qt.Key_X, Qt.Key_C) and ctrl and self.view.textCursor().hasSelection():
            if probar:
                return True
            self.ensure_built()
            ks = self._sel_ks()
            if ks:
                self._clip_words(sorted({self._anc[x].i for x in ks}), k == Qt.Key_C, self._anc[ks[0]].cid)
            return True
        if k == Qt.Key_V and ctrl and self._clip is not None:
            if not probar:
                self._paste(None)
            return True
        if k == Qt.Key_Escape and self._clip is not None:
            if not probar:
                self._clear_clip()
                self.ctrl.message.emit("Cancelado.")
            return True
        return False

    # ------------------------------------------------------- 🔎 buscar lo que dijiste
    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._find_step(-1 if ev.modifiers() & Qt.ShiftModifier else 1)
            return True
        return super().eventFilter(obj, ev)

    def focus_search(self):
        """Ctrl+F: el panel Texto con el buscador listo (si hay texto seleccionado en la transcripción, se busca)."""
        self._set_view(0)
        cur = self.view.textCursor()
        sel = cur.selectedText().replace(" ", " ").strip() if cur.hasSelection() else ""
        if sel:
            self.search.setText(sel)
        self.search.setFocus()
        self.search.selectAll()

    def _buscar(self, toks: list[str]) -> list[tuple[tuple[int, float], float]]:
        """Todas las apariciones de la frase (sin mirar mayúsculas, tildes ni signos) que están en la timeline, en
        orden de la línea de tiempo: ((palabra, segundo de la timeline de esa aparición), segundo donde empieza).
        Las palabras cortadas no cuentan."""
        p = self.ctrl.project
        tr = p.transcripts.get(self.media_id) if self.media_id else None
        if not toks or not tr:
            return []
        words = tr.get("words", [])
        seq = [(i, n) for i, n in ((i, _norm(w[2])) for i, w in enumerate(words)) if n]
        pres, _segs = self._layout(tr)
        por_palabra: dict[int, list] = {}
        for an in pres:
            if an.a is not None:
                por_palabra.setdefault(an.i, []).append(an)
        k, out = len(toks), []
        for j in range(len(seq) - k + 1):
            if all(seq[j + x][1] == toks[x] for x in range(k)):
                for an in por_palabra.get(seq[j][0], []):
                    out.append(((an.i, round(an.tm, 3)), an.a))
        out.sort(key=lambda h: h[1])
        return out

    def _refresh_hits(self, reset: bool):
        """Recalcula las apariciones y las manda a la regla de la timeline. reset=True: texto nuevo (vuelve a la
        primera y la selecciona en el texto, sin mover el cabezal)."""
        toks = [t for t in (_norm(x) for x in self.search.text().split()) if t]
        self._hits = self._buscar(toks)
        if not self._hits:
            self._hit_i = -1
        elif reset or self._hit_i < 0:
            self._hit_i = 0 if reset else self._hit_i
        else:
            self._hit_i = min(self._hit_i, len(self._hits) - 1)
        label = " ".join(self.search.text().split())[:24]
        self.search_marks_changed.emit([(t, "🔎 " + label) for _i, t in self._hits])
        self._update_count(bool(toks))
        if reset and self._hit_i >= 0:
            self._select_hit()

    def _update_count(self, hay_texto: bool):
        n = len(self._hits)
        if not hay_texto:
            txt = ""
        elif n == 0:
            txt = "sin resultados"
        elif self._hit_i >= 0:
            txt = f"{self._hit_i + 1} de {n}"
        else:
            txt = f"{n} en total"
        self.search_count.setText(txt)
        self.btn_prev.setEnabled(n > 0)
        self.btn_next.setEnabled(n > 0)

    def _select_hit(self):
        """Marca en el texto la aparición actual (sin mover el cabezal)."""
        if not 0 <= self._hit_i < len(self._hits):
            return
        self.ensure_built()
        k = self._key_k.get(self._hits[self._hit_i][0])
        if k is None or self._anc[k].p0 is None:
            return
        pos, n = self._anc[k].p0, self._anc[k].n
        cur = QTextCursor(self.view.document())
        cur.setPosition(pos)
        cur.setPosition(pos + n, QTextCursor.KeepAnchor)
        self.view.setTextCursor(cur)
        self.view.ensureCursorVisible()

    def _find_step(self, d: int):
        """Enter / ▶: la siguiente aparición (Mayús+Enter / ◀: la anterior). Salta el cabezal a ella."""
        if not self.search.text().strip():
            return
        self._refresh_hits(reset=False)                 # por si la timeline cambió desde la última vez
        n = len(self._hits)
        if n == 0:
            self.ctrl.message.emit(f"No aparece «{self.search.text().strip()}» en la línea de tiempo.")
            return
        self._hit_i = (self._hit_i + d) % n if self._hit_i >= 0 else (0 if d > 0 else n - 1)
        self.engine.user_seek(max(0.0, self._hits[self._hit_i][1] - 0.05))
        self._select_hit()
        self._update_count(True)

    def export_srt(self):
        if not self.media_id:
            return
        cues = subtitles.build_cues(self.ctrl.project, self.media_id)
        if not cues:
            self.ctrl.message.emit("No hay texto en la timeline para crear subtítulos.")
            return
        settings = QSettings("EditorIA", "EditorIA")
        start = os.path.join(settings.value("last_dir", os.path.expanduser("~")),
                             f"{self.ctrl.project.name}.srt")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar subtítulos", start, "Subtítulos (*.srt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(subtitles.to_srt(cues))
        self.ctrl.message.emit(f"Subtítulos guardados ({len(cues)} bloques): {path}")
