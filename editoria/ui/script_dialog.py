"""
📜 «Montaje desde el guion» (como AI IntelliScript de DaVinci Resolve 20).

Pegas el guion (una oración por línea), eliges la narración y «Analizar»: cada línea se busca en lo que dijiste y
se elige su mejor toma. «✓ Montar» hace TODO en un solo paso de deshacer: quita las tomas descartadas (ripple en
todas las pistas), pone marcadores (⚠ falta / ✎ improvisado / ♪ música / 📝 nota) y coloca los [CLIP: x] e [IMG: x].
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..ai import script_assembly as SA
from ..core import keyword_folders as KF
from ..core import mapping, overlay
from ..core.controller import EPS
from ..core.model import KIND_IMAGE, KIND_VIDEO, Marker, new_id
from .common import fmt_time
from .help import set_help

MAX_CLIP = 6.0                     # un clip de una etiqueta dura lo que la línea, como mucho esto
RAIZ_CLAVE = "clips/carpeta_raiz"  # la misma carpeta que el panel de clips por palabra
COLOR = {"falta": "#ff5a5a", "impro": "#ffd166", "music": "#b58cff", "nota": "#9ad0ff"}


def _tl(p, mid: str, s: float) -> float | None:
    """Momento de la línea de tiempo donde suena el segundo s del archivo (tolera un pelo de margen)."""
    for d in (0.0, 0.02, -0.02, 0.05, -0.05, 0.1, -0.1, 0.2):
        t = mapping.map_time(p, mid, s + d)
        if t is not None:
            return t
    return None


class ScriptDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.ctrl = win.ctrl
        self.state: dict | None = None      # resultado del análisis
        self.setWindowTitle("📜 Montaje desde el guion")
        self.resize(980, 640)
        set_help(self, "montaje_guion")
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Escribe o pega el guion: una oración por línea. Etiquetas entre corchetes: "
                             "[CLIP: fortnite]  [IMG: titular.png]  [MÚSICA: tensa]  [NOTA: …]"))
        self.script = QPlainTextEdit()
        self.script.setPlaceholderText("Hola a todos, bienvenidos a este análisis.\n"
                                       "El combate se siente bastante lento. [CLIP: fortnite]\n")
        self.script.setMinimumHeight(140)
        lay.addWidget(self.script)

        row = QHBoxLayout()
        self.btn_open = QPushButton("📂 Abrir .txt…")
        self.btn_open.clicked.connect(self._open_txt)
        self.media = QComboBox()
        self.btn_analyze = QPushButton("🔍 Analizar")
        self.btn_analyze.clicked.connect(self.analyze)
        row.addWidget(self.btn_open)
        row.addWidget(QLabel("Narración:"))
        row.addWidget(self.media, 1)
        row.addWidget(self.btn_analyze)
        lay.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Línea", "Texto", "Toma", "Tiempo", "Estado", "▶"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        self.info = QLabel("Pulsa «Analizar» para ver qué encontré en la narración.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_montar = QPushButton("✓ Montar")
        self.btn_montar.setEnabled(False)
        self.btn_montar.clicked.connect(self.montar)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_montar)
        lay.addLayout(bottom)

        self._fill_media()

    # ------------------------------------------------------------------ datos
    def _fill_media(self):
        p = self.ctrl.project
        voz = self.win.voice.media_id() if hasattr(self.win, "voice") else None
        opts = [(m.name, m.id) for m in p.media.values()
                if (p.transcripts.get(m.id) or {}).get("words")]
        self.media.clear()
        for name, mid in opts:
            self.media.addItem(name, mid)
        if voz:
            i = self.media.findData(voz)
            if i >= 0:
                self.media.setCurrentIndex(i)
        if not opts:
            self.info.setText("No hay narración con transcripción. Transcríbela primero (panel Voz).")

    def _open_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir guion", "", "Texto (*.txt)")
        if path:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    self.script.setPlainText(f.read())
            except OSError as exc:
                QMessageBox.warning(self, "Montaje desde el guion", f"No se pudo abrir: {exc}")

    # ------------------------------------------------------------------ analizar
    def analyze(self):
        mid = self.media.currentData()
        if not mid:
            QMessageBox.information(self, "Montaje desde el guion",
                                    "Elige una narración con transcripción (panel Voz → Transcribir).")
            return
        p = self.ctrl.project
        words = p.transcripts[mid]["words"]
        lines = SA.parse_script(self.script.toPlainText())
        if not lines:
            QMessageBox.information(self, "Montaje desde el guion", "Escribe el guion: una oración por línea.")
            return
        aligned, impro = SA.align_script(lines, words)
        chosen = SA.choose_takes(aligned)
        choice = {}
        for c in chosen:
            takes = aligned[c["i"]] or []
            choice[c["i"]] = next((j for j, t in enumerate(takes) if t is c["chosen"]), None)
        self.state = {"mid": mid, "words": words, "lines": lines, "aligned": aligned, "impro": impro,
                      "choice": choice}
        self._fill_table()
        self.btn_montar.setEnabled(True)

    def _takes(self, k: int) -> list:
        return self.state["aligned"][k] or []

    def _fill_table(self):
        st = self.state
        t = self.table
        t.setRowCount(0)
        self._rows = {}
        for ln in st["lines"]:
            k = ln["i"]
            r = t.rowCount()
            t.insertRow(r)
            self._rows[k] = r
            takes = self._takes(k)
            tags = " ".join(f"[{x['kind'].upper()}: {x['value']}]" for x in ln["tags"])
            text = ln["text"] or "(solo etiquetas)"
            t.setItem(r, 0, QTableWidgetItem(str(k + 1)))
            t.setItem(r, 1, QTableWidgetItem(text + (f"  {tags}" if tags else "")))
            combo = QComboBox()
            for j, tk in enumerate(takes):
                combo.addItem(f"Toma {j + 1} · {fmt_time(tk['start'])} ({round(tk['score'] * 100)}%)", j)
            if not takes:
                combo.addItem("—", None)
            combo.setEnabled(bool(takes))
            ch = st["choice"].get(k)
            if ch is not None:
                combo.setCurrentIndex(ch)
            combo.currentIndexChanged.connect(lambda _i, kk=k, cb=combo: self._pick(kk, cb.currentData()))
            t.setCellWidget(r, 2, combo)
            btn = QPushButton("▶")
            btn.setEnabled(bool(takes))
            btn.clicked.connect(lambda _=False, kk=k: self._play_choice(kk))
            t.setCellWidget(r, 5, btn)
            self._status(k)
        for im in st["impro"]:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem("—"))
            t.setItem(r, 1, QTableWidgetItem(f"«{im['text']}»"))
            t.setItem(r, 2, QTableWidgetItem("—"))
            t.setItem(r, 3, QTableWidgetItem(fmt_time(im["start"])))
            it = QTableWidgetItem("✎ improvisado: se deja, marcado")
            it.setForeground(_color(COLOR["impro"]))
            t.setItem(r, 4, it)
            btn = QPushButton("▶")
            btn.clicked.connect(lambda _=False, a=im["start"], b=im["end"]: self._play(a, b))
            t.setCellWidget(r, 5, btn)
        t.resizeRowsToContents()
        self._info()

    def _status(self, k: int):
        """Actualiza solo la fila de la línea k (sin reconstruir la tabla)."""
        st = self.state
        r = self._rows[k]
        takes = self._takes(k)
        ch = st["choice"].get(k)
        t = self.table
        empty = st["lines"][k]["text"] == ""
        if empty:
            cells = ("—", "sin texto", None)
        elif ch is None:
            it = QTableWidgetItem("⚠ falta: no la encontré en la narración")
            it.setForeground(_color(COLOR["falta"]))
            cells = ("—", it, None)
        else:
            extra = f" · quita {len(takes) - 1}" if len(takes) > 1 else ""
            cells = (fmt_time(takes[ch]["start"]), f"✓{extra}", None)
        t.setItem(r, 3, QTableWidgetItem(cells[0]))
        if isinstance(cells[1], QTableWidgetItem):
            t.setItem(r, 4, cells[1])
        else:
            t.setItem(r, 4, QTableWidgetItem(cells[1]))

    def _info(self):
        st = self.state
        n_cut = sum(len(self._takes(k)) - 1 for k, j in st["choice"].items() if j is not None)
        n_missing = sum(1 for ln in st["lines"] if ln["text"] and st["choice"].get(ln["i"]) is None)
        self.info.setText(f"{len(st['lines'])} líneas · {n_cut} tomas se quitarán · {n_missing} faltan · "
                          f"{len(st['impro'])} improvisados (se dejan, marcados).")

    def _pick(self, k: int, j):
        if self.state is None:
            return
        self.state["choice"][k] = j
        self._status(k)
        self._info()

    def _play(self, a: float, b: float):
        p = self.ctrl.project
        parts = mapping.map_range(p, self.state["mid"], a, b)
        if not parts:
            self.ctrl.message.emit("Ese fragmento no está en la línea de tiempo.")
            return
        self.win.engine.play_ranges([(parts[0][1] - 0.3, parts[-1][2] + 0.3)])

    def _play_choice(self, k: int):
        j = self.state["choice"].get(k)
        if j is None:
            return
        tk = self._takes(k)[j]
        self._play(tk["start"], tk["end"])

    # ------------------------------------------------------------------ montar
    def _resolve(self, kind: str, value: str) -> str | None:
        """El medio para una etiqueta: primero la carpeta por palabra, luego un medio cuyo nombre la contenga.
        Si el archivo aún no está en el proyecto, se importa (la biblioteca no es parte del deshacer)."""
        p = self.ctrl.project
        want = KF.norm(value)
        if not want:
            return None
        root = QSettings("EditorIA", "EditorIA").value(RAIZ_CLAVE, "") or KF.default_root()
        folder = KF.match(value, KF.list_folders(root))
        if folder:
            for path in folder["files"]:
                if KF.kind_for_path(path) != kind:
                    continue
                norm_path = os.path.normcase(os.path.abspath(path))
                hit = next((m for m in p.media.values()
                            if os.path.normcase(os.path.abspath(m.path)) == norm_path), None)
                if hit is None:
                    ids = self.ctrl.import_now([path])
                    hit = next((p.media[i] for i in ids if i in p.media and p.media[i].kind == kind), None)
                if hit is not None:
                    return hit.id
        for m in p.media.values():
            if m.kind == kind and want in KF.norm(m.name):
                return m.id
        return None

    def montar(self):
        st = self.state
        if st is None:
            return
        ctrl = self.ctrl
        mid, words = st["mid"], st["words"]
        # 1) Medios de las etiquetas (antes del paso de deshacer; importar no es parte del deshacer)
        plan_tags = {}
        for ln in st["lines"]:
            for tg in ln["tags"]:
                if tg["kind"] in ("clip", "img"):
                    kind = KIND_VIDEO if tg["kind"] == "clip" else KIND_IMAGE
                    plan_tags[(ln["i"], tg["value"])] = (kind, self._resolve(kind, tg["value"]))
        # 2) Tramos a quitar (del archivo) y marcas
        cuts, n_descartadas = [], 0
        for k in range(len(st["lines"])):
            takes = self._takes(k)
            j = st["choice"].get(k)
            for jj, tk in enumerate(takes):
                if jj != j:
                    cuts.append(SA.cut_span(words, tk["a_idx"], tk["b_idx"]))
                    n_descartadas += 1
        lines = st["lines"]
        missing = [ln for ln in lines if st["choice"].get(ln["i"]) is None and ln["text"]]
        if not any(st["choice"].get(ln["i"]) is not None for ln in lines):
            QMessageBox.information(self, "Montaje desde el guion", "No encontré ninguna línea del guion.")
            return
        p = ctrl.project
        if mid not in p.media or not mapping.clips_of_media(p, mid):
            ctrl.message.emit("La narración no está en la línea de tiempo: añádela y vuelve a montar.")
            return
        # tramos de la timeline a quitar (calculados antes de cortar nada)
        spans = []
        for a, b in cuts:
            spans += [(ta, tb) for _c, ta, tb in mapping.map_range(p, mid, a, b)]
        spans.sort()
        merged = []
        for ta, tb in spans:
            if merged and ta <= merged[-1][1] + EPS:
                merged[-1][1] = max(merged[-1][1], tb)
            else:
                merged.append([ta, tb])
        # TODO el montaje va en UN solo paso de deshacer: cada corte, marcador y colocación es un paso dentro de la macro
        idx_antes = ctrl.undo_stack.index()
        ctrl.undo_stack.beginMacro("Montaje desde el guion")
        try:
            # a) quitar las tomas descartadas (ripple en todas las pistas), de atrás hacia delante
            for ta, tb in reversed(merged):           # lo anterior no se mueve
                ctrl._edit("Quitar toma descartada", lambda q, ta=ta, tb=tb: ctrl._ripple_delete(q, ta, tb))
            p = ctrl.project
            # b) posiciones de cada línea ya en la línea de tiempo (después de cortar)
            pos = {}
            for ln in lines:
                j = st["choice"].get(ln["i"])
                if j is None:
                    continue
                tk = self._takes(ln["i"])[j]
                a = _tl(p, mid, tk["start"])
                b = _tl(p, mid, tk["end"])
                if a is not None:
                    pos[ln["i"]] = (a, b if b is not None and b > a else a + 0.5)
            markers = []
            n_falta = 0
            miss_t = {}                                  # dónde iría cada línea que falta
            for ln in missing:
                prev = [pos[k][1] for k in pos if k < ln["i"]]
                nxt = [pos[k][0] for k in pos if k > ln["i"]]
                if prev:
                    t = max(prev) + 0.05
                elif nxt:
                    t = max(0.0, min(nxt) - 0.5)
                else:
                    t = 0.0
                miss_t[ln["i"]] = t
                markers.append((t, f"⚠ Falta: «{ln['text'][:60]}»", COLOR["falta"]))
                n_falta += 1
            for im in st["impro"]:
                t = _tl(p, mid, im["start"])
                if t is not None:
                    markers.append((t, f"✎ Improvisado: «{im['text'][:60]}»", COLOR["impro"]))
            # c) etiquetas [CLIP]/[IMG] con el controlador («📍 Poner donde lo dices»), cada una un paso dentro de la macro
            n_etq = n_no = 0
            for ln in lines:
                if ln["i"] in pos:
                    a, b = pos[ln["i"]]
                elif ln["i"] in miss_t:
                    a = b = miss_t[ln["i"]]
                else:                                    # línea solo con etiquetas: va justo tras la anterior
                    prv = [pos[k][1] for k in pos if k < ln["i"]]
                    a = b = max(prv) if prv else 0.0
                for tg in ln["tags"]:
                    if tg["kind"] == "music":
                        markers.append((a or 0.0, f"♪ Música: {tg['value']}", COLOR["music"]))
                    elif tg["kind"] == "nota":
                        markers.append((a or 0.0, f"📝 Nota: {tg['value']}", COLOR["nota"]))
                    elif tg["kind"] in ("clip", "img"):
                        _kind, mdid = plan_tags.get((ln["i"], tg["value"]), (None, None))
                        d = min(MAX_CLIP, b - a) if ln["i"] in pos else 0.0
                        if mdid is None or ln["i"] not in pos or d < 0.5:
                            n_no += 1
                            continue
                        ids = ctrl.place_clip_at(mdid, [a], [d], 0.0)
                        if not ids:
                            n_no += 1
                            continue
                        q = ctrl.project
                        c = q.clips.get(ids[0])
                        if c is not None and q.media[mdid].kind == KIND_IMAGE and \
                                overlay.visual_under(q, c.track_id, c.start, c.start + c.duration):
                            ctrl.set_image_style([c.id], "auto")   # «Encima, fondo desenfocado y sombra», como antes
                        n_etq += 1
            # d) marcadores (un paso dentro de la macro)
            if markers:
                def poner_marcadores(q):
                    for t, label, color in markers:
                        q.markers.append(Marker(new_id(), max(0.0, t), label, color=color))
                    q.markers.sort(key=lambda m: m.time)
                ctrl._edit("Marcadores del guion", poner_marcadores)
        finally:
            ctrl.undo_stack.endMacro()
        if ctrl.undo_stack.index() == idx_antes:
            ctrl.message.emit("📜 Montaje desde el guion: no cambió nada.")
            return
        n_lineas = len(lines)
        msg = (f"📜 {n_lineas} líneas · {n_descartadas} tomas quitadas · {n_falta} faltan · "
               f"{len(st['impro'])} improvisados · {n_etq} etiquetas colocadas")
        if n_no:
            msg += f" · {n_no} etiquetas sin medio o sin sitio"
        ctrl.message.emit(msg)
        self.info.setText(msg + "   (Ctrl+Z deshace todo el montaje de una vez)")
        self.accept()


def _color(hexcode: str):
    from PySide6.QtGui import QBrush, QColor
    return QBrush(QColor(hexcode))


def open_script_dialog(win) -> None:
    """Abre la ventana (modal)."""
    dlg = ScriptDialog(win)
    dlg.exec()
