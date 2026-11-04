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

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
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


class _WordView(QTextBrowser):
    word_double_clicked = Signal(int)
    cut_requested = Signal()        # Supr / Retroceso con texto seleccionado

    def mouseDoubleClickEvent(self, e):
        href = self.anchorAt(e.position().toPoint())
        if href.startswith("w"):
            self.word_double_clicked.emit(int(href[1:]))
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.textCursor().hasSelection():
            self.cut_requested.emit()
            return
        super().keyPressEvent(e)


class TranscriptPanel(QWidget):
    moments_requested = Signal(str, float)   # frase y dónde va en la línea de tiempo
    def __init__(self, ctrl, engine, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.engine = engine
        self.media_id: str | None = None
        self._starts: list[float] = []
        self._spans: list[tuple[float, float, int]] = []   # (t_ini, t_fin, índice) en la timeline
        self._pos: dict[int, tuple[int, int]] = {}         # índice -> (posición, longitud) en el texto
        self._current = -1

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
        self.search.setToolTip("Enter = siguiente")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._find_next)

        self.view = _WordView()
        self.view.setOpenLinks(False)
        self.view.setOpenExternalLinks(False)
        self.view.anchorClicked.connect(self._on_anchor)
        self.view.word_double_clicked.connect(self._edit_word)
        self.view.cut_requested.connect(lambda: self._cross_words(self._words_at(None)))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
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
                             "Selecciona texto y pulsa Supr = tacharlo tú · Ctrl+Z deshace")
        page_tr = QWidget()
        pl = QVBoxLayout(page_tr)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        pl.addWidget(self.search)
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
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._rebuild)
        ctrl.project_changed.connect(self._timer.start)
        ctrl.transcript_changed.connect(lambda mid: mid == self.media_id and self._timer.start())
        engine.time_changed.connect(self._highlight)
        self._rebuild()

    def set_media(self, media_id: str):
        self.media_id = media_id or None
        self._rebuild()
        self._cap_lazy()
        self._sum_lazy()

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
        p = self.ctrl.project
        tr = p.transcripts.get(self.media_id) if self.media_id else None
        bar = self.view.verticalScrollBar()
        scroll = bar.value()
        doc = self.view.document()
        doc.clear()
        self._pos.clear()
        self._spans = []
        self._current = -1
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
        cur = QTextCursor(doc)
        cur.beginEditBlock()  # todo el texto de una vez (mucho más rápido)
        plain = QTextCharFormat()
        plain.setForeground(QColor("#e6e8ec"))
        stamp = QTextCharFormat()
        stamp.setForeground(QColor("#6b7280"))
        stamp.setFontPointSize(8.5)
        segments = tr.get("segments") or [[0, 0, 0, len(words)]]
        for n, (_s, _e, a, b) in enumerate(segments):
            if n:
                cur.insertBlock()
            t0 = index.time((words[a][0] + words[a][1]) / 2) if a < len(words) else None
            cur.insertText((fmt_time(t0, frac=False) if t0 is not None else "cortado") + "  ", stamp)
            for i in range(a, min(b, len(words))):
                w = words[i]
                mid = (w[0] + w[1]) / 2
                t = index.time(mid)
                fmt = QTextCharFormat(plain)
                fmt.setAnchor(True)
                fmt.setAnchorHref(f"w{i}")
                if t is None:
                    fmt.setForeground(QColor("#5c6370"))
                    fmt.setFontStrikeOut(True)
                else:
                    self._spans.append((t - (mid - w[0]), t + (w[1] - mid), i))
                if i in marks:
                    c = QColor(SUGGESTION_COLORS.get(marks[i], QColor("#888")))
                    c.setAlpha(70)
                    fmt.setBackground(c)
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
                self._pos[i] = (pos, len(w[2]))
                cur.insertText(" ", plain)
        cur.endEditBlock()
        self._spans.sort()
        self._starts = [s[0] for s in self._spans]
        bar.setValue(scroll)
        self._highlight(self.engine.time)

    def _highlight(self, t: float):
        if not self._spans:
            return
        k = bisect.bisect_right(self._starts, t) - 1
        idx = self._spans[k][2] if k >= 0 and t <= self._spans[k][1] + 0.15 else -1
        if idx == self._current:
            return
        self._current = idx
        if idx < 0 or idx not in self._pos:
            self.view.setExtraSelections([])
            return
        pos, length = self._pos[idx]
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

    def _on_anchor(self, url):
        href = url.toString()
        if href.startswith("w"):
            idx = int(href[1:])
            t = self._time_of(idx)
            if t is None:
                self.ctrl.message.emit("Esa palabra está cortada (no está en la timeline).")
                return
            self.engine.user_seek(max(0.0, t - 0.05))
            self._toggle_word(idx)

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

    def _cross_words(self, idxs: list[int]):
        """✂ Tachar tú lo seleccionado: se quitará con «Cortar lo tachado»."""
        words = self.ctrl.project.transcripts.get(self.media_id, {}).get("words", [])
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
                self.ctrl.edit_word(self.media_id, idx, text)
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

    def _words_at(self, pos) -> list[int]:
        """Palabras seleccionadas con el ratón o, si no hay selección, la que está bajo el cursor."""
        cur = self.view.textCursor()
        if cur.hasSelection():
            a, b = cur.selectionStart(), cur.selectionEnd()
            idxs = sorted(i for i, (p0, n) in self._pos.items() if p0 < b and p0 + n > a)
            if idxs:
                return idxs
        if pos is None:
            return []
        href = self.view.anchorAt(pos)
        return [int(href[1:])] if href.startswith("w") else []

    def _context_menu(self, pos):
        idxs = self._words_at(pos)
        if not idxs or not self.media_id:
            menu = QMenu(self)
            add_help_action(menu, "texto", self.window())
            help_ui.exec_menu(menu, self.view.viewport().mapToGlobal(pos))
            return
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
            menu.addAction("Ir a esta palabra", lambda: self._seek_word(idxs[0]))
        menu.addSeparator()
        phrase = " ".join(words[i][2] for i in idxs).strip(" .,;:¡!¿?")
        at = self._time_of(idxs[0])
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

    def _seek_word(self, idx: int):
        t = self._time_of(idx)
        if t is not None:
            self.engine.user_seek(t)

    def _find_next(self):
        q = self.search.text().strip()
        if not q:
            return
        if not self.view.find(q):
            self.view.moveCursor(QTextCursor.Start)  # volver a empezar desde arriba
            if not self.view.find(q):
                self.ctrl.message.emit(f"No se encontró «{q}».")
                return
        cur = self.view.textCursor()
        pos = cur.selectionStart()
        for idx, (p0, n) in self._pos.items():
            if p0 <= pos < p0 + n + 1:
                t = self._time_of(idx)
                if t is not None:
                    self.engine.user_seek(t)
                break

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
