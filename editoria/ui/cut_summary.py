"""
📋 Resumen de lo que se va a quitar (pestaña «Texto» → «📋 Resumen»).

En vez de leer toda la transcripción: solo los sitios donde hay algo que quitar, agrupados — frases que se repiten,
que se medio repiten o que suenan parecido (con las tomas y lo que dijiste después), muletillas por palabra
(«¿no?» × 37), palabras repetidas, lo que tachaste tú, silencios y lo que la escucha literal recuperó.
Casilla marcada = se quita al pulsar «✂ Cortar lo tachado»; desmarcada = se queda. Doble clic = escucharlo.
"""
from __future__ import annotations

import bisect
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..ai import voice_cleanup
from ..core import mapping
from ..core.model import SUG_PENDING
from .common import fmt_time

IDS = Qt.UserRole              # ids de las sugerencias que controla la fila
PLAY = Qt.UserRole + 1         # tramos (del archivo) que se escuchan con doble clic
KEY = Qt.UserRole + 2          # para recordar qué grupos estaban abiertos

GROUPS = [("igual", "🔁 Se repite"), ("medio", "≈ Se medio repite"), ("parecido", "〜 Suena parecido"),
          ("filler", "💬 Muletillas"), ("repeat", "🔂 Palabras repetidas o cortadas"), ("manual", "✂ Tachado a mano"),
          ("silence", "🔇 Silencios largos"), ("noise", "🌬 Respiraciones y ruidos"),
          ("recovered", "⧉ Lo que Whisper se había saltado (lo recuperó la escucha literal)")]


def _short(text: str, n: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _quoted(label: str) -> str:
    m = re.search(r"«(.*)»", label)
    return m.group(1) if m else label


def group_of(s) -> str:
    if s.kind == "retake":
        return (s.data or {}).get("level") or "medio"
    return s.kind


class CutSummary(QWidget):
    def __init__(self, ctrl, engine, media_id_fn, cut_kinds_fn, parent=None):
        super().__init__(parent)
        self.ctrl, self.engine = ctrl, engine
        self._media_id, self._cut_kinds = media_id_fn, cut_kinds_fn
        self.info = QLabel()
        self.info.setObjectName("dim")
        self.info.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Qué", "Dónde"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._on_changed)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.setStyleSheet("QTreeWidget { background: #1b1d22; border: none; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.info)
        lay.addWidget(self.tree, 1)

    # ------------------------------------------------------------------ construir
    def _when(self, mid: str, a: float) -> str:
        t = mapping.map_time(self.ctrl.project, mid, a)
        return fmt_time(t) if t is not None else "—"

    def _item(self, parent, text: str, when: str = "", ids=None, play=None, checked: bool | None = None,
              tip: str = "", dim: bool = False) -> QTreeWidgetItem:
        it = QTreeWidgetItem(parent, [text, when])
        it.setData(0, IDS, list(ids or []))
        it.setData(0, PLAY, list(play or []))
        if checked is not None:
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        if tip:
            it.setToolTip(0, tip)
        if dim:
            it.setForeground(0, QColor("#8b949e"))
        return it

    def _context(self, words, mids, a: float, b: float) -> str:
        """La palabra (o palabras) con un poco de lo que va antes y después: «…lo que pasó, [¿no?] y entonces…»."""
        i0, i1 = bisect.bisect_left(mids, a), bisect.bisect_right(mids, b)
        before = " ".join(w[2] for w in words[max(0, i0 - 5):i0])
        inside = " ".join(w[2] for w in words[i0:i1])
        after = " ".join(w[2] for w in words[i1:i1 + 3])
        return _short(f"…{before} [{inside}] {after}…", 80)

    def rebuild(self):
        mid = self._media_id()
        p = self.ctrl.project
        opened = {self.tree.topLevelItem(i).data(0, KEY) for i in range(self.tree.topLevelItemCount())
                  if self.tree.topLevelItem(i).isExpanded()}
        first = self.tree.topLevelItemCount() == 0
        self.tree.blockSignals(True)
        self.tree.clear()
        tr = p.transcripts.get(mid) if mid else None
        words = (tr or {}).get("words", [])
        mids = [(w[0] + w[1]) / 2 for w in words]
        on = self._cut_kinds()
        sugs = [s for s in p.suggestions if s.media_id == mid and s.status == SUG_PENDING and s.cuttable]
        by_group: dict[str, list] = {}
        for s in sugs:
            by_group.setdefault(group_of(s), []).append(s)
        n_cut = secs = 0.0
        for key, title in GROUPS:
            items = by_group.get(key, [])
            rec = (tr or {}).get("recovered", []) if key == "recovered" else []
            if not items and not rec:
                continue
            top = QTreeWidgetItem(self.tree, [f"{title} ({len(items) or len(rec)})", ""])
            top.setData(0, KEY, key)
            top.setData(0, IDS, [s.id for s in items])
            top.setFirstColumnSpanned(True)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            if key in ("igual", "medio", "parecido"):
                for s in sorted(items, key=lambda s: s.start):
                    self._retake_row(top, s, mid, voice_cleanup.will_cut(s, on))
            elif key == "filler":
                self._filler_rows(top, items, mid, words, mids, on)
            elif key in ("silence", "noise"):
                cut = [s for s in items if voice_cleanup.will_cut(s, on)]
                total = sum(s.end - s.start for s in items)
                row = self._item(top, f"{len(items)} en total · {total:.1f} s", ids=[s.id for s in items],
                                 checked=len(cut) == len(items))
                if cut and len(cut) < len(items):
                    row.setCheckState(0, Qt.PartiallyChecked)
                for s in sorted(items, key=lambda s: s.start):
                    self._item(row, _short(s.label), self._when(mid, s.start), [s.id], [(s.start, s.end)],
                               voice_cleanup.will_cut(s, on), s.detail)
            elif key == "recovered":
                for a, b, heard, how in rec:
                    where = "Whisper lo escribió al volver a escuchar" if how == "whisper" else \
                        "escrito tal cual se oyó (puede tener faltas)"
                    self._item(top, f"«{_short(heard)}»", self._when(mid, a), play=[(a, b)], tip=where, dim=True)
            else:
                for s in sorted(items, key=lambda s: s.start):
                    a, b = s.start, s.end
                    text = self._context(words, mids, a, b) if words else _short(s.label)
                    self._item(top, text, self._when(mid, a), [s.id], [(a, b)], voice_cleanup.will_cut(s, on),
                               s.label + ("\n" + s.detail if s.detail else ""))
            top.setExpanded(key in opened or (first and key in ("igual", "medio", "parecido")))
            for s in items:
                if voice_cleanup.will_cut(s, on):
                    n_cut += 1
                    a, b = voice_cleanup.cut_range(s)
                    secs += b - a
        self.tree.blockSignals(False)
        if not tr:
            self.info.setText("Todavía no hay transcripción. Ve a «Limpieza» → «Transcribir y analizar».")
        elif not sugs:
            self.info.setText("No hay nada pendiente que quitar.")
        else:
            self.info.setText(f"Se quitarán {int(n_cut)} cosas (~{secs:.0f} s) al pulsar «✂ Cortar lo tachado». "
                              "Casilla marcada = se quita · desmarcada = se queda · doble clic = escuchar.")

    def _retake_row(self, top, s, mid, cut: bool):
        data = s.data or {}
        takes = data.get("takes") or []
        best_txt = next((t for t, b in takes if b), "")
        ca, cb = voice_cleanup.cut_range(s)
        words = self.ctrl.project.transcripts.get(mid, {}).get("words", [])
        gone = " ".join(w[2] for w in words if ca <= (w[0] + w[1]) / 2 <= cb) or \
            next((t for t, b in takes if not b), s.label)
        text = f"✗ «{_short(gone, 45)}»  →  ⭐ «{_short(best_txt, 45)}»" if best_txt else _short(s.label)
        play = [(s.start, s.end)] + ([(s.alt_start, s.alt_end)] if s.alt_start is not None else [])
        row = self._item(top, text, self._when(mid, min(s.start, s.alt_start or s.start)),
                         [s.id], play, cut, s.label + ("\n\n" + s.detail if s.detail else ""))
        for k, (t, b) in enumerate(takes):
            self._item(row, f"{'⭐ se queda' if b else '✗ sobra'} · Toma {k + 1}: «{_short(t, 90)}»", dim=not b)
        if data.get("after"):
            self._item(row, f"Después dijiste: «{_short(data['after'], 90)}»", dim=True)
        if data.get("reason"):
            self._item(row, f"Por qué: {_short(data['reason'], 100)}", dim=True)

    def _filler_rows(self, top, items, mid, words, mids, on):
        by_word: dict[str, list] = {}
        for s in items:
            by_word.setdefault(_quoted(s.label).lower().strip(" ,.¿?¡!"), []).append(s)
        for word, ss in sorted(by_word.items(), key=lambda kv: -len(kv[1])):
            cut = [s for s in ss if voice_cleanup.will_cut(s, on)]
            row = self._item(top, f"«{_quoted(ss[0].label)}» × {len(ss)}", ids=[s.id for s in ss],
                             checked=len(cut) == len(ss), tip=ss[0].label + ("\n" + ss[0].detail if ss[0].detail
                                                                              else ""))
            if cut and len(cut) < len(ss):
                row.setCheckState(0, Qt.PartiallyChecked)
            for s in sorted(ss, key=lambda s: s.start):
                text = self._context(words, mids, s.start, s.end) if words else _short(s.label)
                self._item(row, text, self._when(mid, s.start), [s.id], [(s.start, s.end)],
                           voice_cleanup.will_cut(s, on))

    # ------------------------------------------------------------------ acciones
    def _on_changed(self, it: QTreeWidgetItem, col: int):
        ids = it.data(0, IDS) or []
        if col != 0 or not ids or not it.flags() & Qt.ItemIsUserCheckable:
            return
        state = it.checkState(0)
        if state == Qt.PartiallyChecked:
            return
        self.ctrl.set_cross(ids, state == Qt.Checked)

    def _on_double(self, it: QTreeWidgetItem, _col: int):
        mid = self._media_id()
        spans = it.data(0, PLAY) or []
        if not spans and it.parent() is not None:
            spans = it.parent().data(0, PLAY) or []
        ranges = []
        for a, b in spans:
            parts = mapping.map_range(self.ctrl.project, mid, a, b)
            if parts:
                ranges.append((parts[0][1] - (0.2 if len(spans) > 1 else 1.0),
                               parts[-1][2] + (0.2 if len(spans) > 1 else 1.0)))
        if ranges:
            self.engine.play_ranges(ranges)
        else:
            self.ctrl.message.emit("Ese fragmento no está en la línea de tiempo.")
