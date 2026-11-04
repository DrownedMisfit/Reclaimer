"""
«🎨 Mi estilo» (taller de miniaturas): de dónde aprende la IA tu estilo y qué aprendió.

  · Mis miniaturas: carpetas con TUS miniaturas terminadas (solo se leen, nunca se tocan).
  · Referencias: miniaturas de otros que te gustan (solo se estudian sus números; no se copian).
  · 🔍 Analizar estilo: lee el texto (OCR local), caras y colores, y guarda un perfil.
"""
from __future__ import annotations

import json
import os
import re
import time

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QProgressBar, QPushButton, QVBoxLayout)

KEY = "miniatura/estilo"
DEFAULT_FOLDERS: list[str] = []


def load() -> dict:
    try:
        st = json.loads(str(QSettings("EditorIA", "EditorIA").value(KEY, "{}")))
    except ValueError:
        st = {}
    if "carpetas" not in st:
        st["carpetas"] = [f for f in DEFAULT_FOLDERS if os.path.isdir(f)] or _detect_folders()
    st.setdefault("referencias", [])
    st.setdefault("usar", True)
    return st


def save(st: dict):
    QSettings("EditorIA", "EditorIA").setValue(KEY, json.dumps(st))


def _detect_folders() -> list[str]:
    """Carpetas que se llaman «miniaturas»/«thumbnails» cerca de la raíz de los discos (solo como sugerencia)."""
    out = []
    for drive in ("C:\\", "D:\\", "E:\\"):
        if not os.path.isdir(drive):
            continue
        try:
            level1 = [os.path.join(drive, d) for d in os.listdir(drive)]
        except OSError:
            continue
        for d in level1:
            if not os.path.isdir(d) or os.path.basename(d).startswith(("$", "Windows", "Program")):
                continue
            cands = [d]
            try:
                cands += [os.path.join(d, x) for x in os.listdir(d)]
            except OSError:
                pass
            for c in cands:
                if os.path.basename(c).lower() in ("miniaturas", "thumbnails", "miniatures") and os.path.isdir(c):
                    out.append(c)
    return out[:4]


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


class _DropList(QListWidget):
    """Lista de carpetas / imágenes que acepta que se las arrastres desde Windows."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def add_path(self, path: str) -> bool:
        p = os.path.normpath(path)
        ok = os.path.isdir(p) or (os.path.isfile(p) and p.lower().endswith(IMAGE_EXT))
        if ok and not self.findItems(p, Qt.MatchExactly):
            self.addItem(p)
            return True
        return False

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.isLocalFile():
                    self.add_path(u.toLocalFile())
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class StyleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 Mi estilo de miniaturas")
        self.resize(640, 620)
        self.st = load()
        self.job = None
        lay = QVBoxLayout(self)
        intro = QLabel("La IA estudia <b>tus</b> miniaturas para que las propuestas se parezcan a tu estilo: "
                       "cuántas palabras usas, tamaño y lado del texto, color, contorno, la palabra clave en otro "
                       "color, el tamaño de la cara y tus colores. Todo local; tus archivos solo se leen.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.own = self._list_group(lay, "📁 Mis miniaturas (carpetas)", self.st["carpetas"], folders_only=True)
        self.refs = self._list_group(lay, "⭐ Referencias que me gustan (de otros canales; no se copian)",
                                     self.st["referencias"], folders_only=False)

        row = QHBoxLayout()
        self.btn = QPushButton("🔍 Analizar estilo")
        self.btn.setObjectName("primary")
        self.btn.setMinimumHeight(34)
        self.btn.clicked.connect(self.analyze)
        row.addWidget(self.btn)
        self.use = QCheckBox("Usar mi estilo en las propuestas")
        self.use.setChecked(bool(self.st.get("usar", True)))
        row.addWidget(self.use)
        row.addStretch(1)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("dim")
        lay.addWidget(self.status)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary, 1)
        bb = QDialogButtonBox()
        bb.addButton("Cerrar", QDialogButtonBox.RejectRole)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._show_summary()

    def _list_group(self, parent_lay, title, items, folders_only):
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        lst = _DropList()               # (también se pueden ARRASTRAR carpetas e imágenes desde Windows)
        lst.setMaximumHeight(90)
        lst.addItems(items)
        lst.setToolTip("Arrastra aquí carpetas o imágenes desde tus carpetas de Windows, o usa los botones.")
        v.addWidget(lst)
        row = QHBoxLayout()
        b = QPushButton("➕ Carpeta…")
        b.clicked.connect(lambda: self._add_folder(lst))
        row.addWidget(b)
        b2 = QPushButton("➕ Imágenes…")       # (también en «Mis miniaturas»: antes solo había carpetas)
        b2.clicked.connect(lambda: self._add_files(lst))
        row.addWidget(b2)
        b3 = QPushButton("Quitar")
        b3.clicked.connect(lambda: [lst.takeItem(lst.row(i)) for i in lst.selectedItems()])
        row.addWidget(b3)
        row.addStretch(1)
        v.addLayout(row)
        parent_lay.addWidget(box)
        return lst

    def _add_folder(self, lst):
        start = lst.item(lst.count() - 1).text() if lst.count() else os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self.window(), "Elegir carpeta", start)
        if d:
            lst.add_path(d)

    def _add_files(self, lst):
        files, _ = QFileDialog.getOpenFileNames(self.window(), "Elegir miniaturas", "",
                                                "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp)")
        for f in files:
            lst.add_path(f)

    @staticmethod
    def _items(lst) -> list[str]:
        return [lst.item(i).text() for i in range(lst.count())]

    def _store(self):
        self.st["carpetas"] = self._items(self.own)
        self.st["referencias"] = self._items(self.refs)
        self.st["usar"] = self.use.isChecked()
        save(self.st)

    def analyze(self):
        from ..ai import thumb_style as S
        from .jobs import BackgroundJob
        if self.job is not None:
            self.job.cancel()
            return
        self._store()
        own, refs = list(self.st["carpetas"]), list(self.st["referencias"])
        if not own and not refs:
            self.status.setText("Añade primero una carpeta con tus miniaturas (o referencias).")
            return

        def work(progress, cancelled):
            a = S.list_images(own)
            b = S.list_images(refs)
            total = max(1, len(a) + len(b))

            def prog(base, n):
                return lambda f, t: progress((base + f * n) / total, t)
            p_own = S.build_profile(a, prog(0, len(a)), cancelled) if a else {}
            p_ref = S.build_profile(b, prog(len(a), len(b)), cancelled) if b else {}
            return p_own, p_ref

        self.btn.setText("■ Detener")
        self.bar.setValue(0)
        self.bar.show()
        self.job = BackgroundJob(work, self)
        self.job.progress.connect(lambda f, t: (self.bar.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.done.connect(self._done)
        self.job.failed.connect(lambda m: (self._end(), self.status.setText("✗ " + m)))
        self.job.start()

    def _end(self):
        self.job = None
        self.btn.setText("🔍 Analizar estilo")
        self.bar.hide()

    def _done(self, res):
        self._end()
        p_own, p_ref = res
        self.st["propio"], self.st["refs"] = p_own, p_ref
        self.st["fecha"] = time.strftime("%Y-%m-%d %H:%M")
        save(self.st)
        self.status.setText(f"✓ Listo ({(p_own or {}).get('n', 0)} tuyas · {(p_ref or {}).get('n', 0)} referencias). "
                            "Las próximas propuestas ya usan lo aprendido.")
        self._show_summary()

    def _show_summary(self):
        from ..ai import thumb_style as S
        parts = []
        for key, who in (("propio", "Tu estilo"), ("refs", "Tus referencias")):
            prof = self.st.get(key) or {}
            for fmt, name in (("youtube", "YouTube"), ("short", "Shorts")):
                d = S.describe(prof, fmt)
                if d:   # los colores, como muestras (no como códigos)
                    d = re.sub(r"#[0-9A-Fa-f]{6}", lambda m: f"<span style='background:{m.group(0)}'>&nbsp;&nbsp;&nbsp;"
                               "&nbsp;</span>", d)
                    pal = "".join(f"<span style='background:{c}'>&nbsp;&nbsp;&nbsp;&nbsp;</span> "
                                  for c in (prof[fmt].get("palette") or [])[:5])
                    parts.append(f"<b>{who} · {name}</b>: {d}<br>{pal}")
        if parts:
            when = self.st.get("fecha", "")
            self.summary.setText("<br><br>".join(parts) + (f"<br><br><span style='color:#9aa1ad'>Analizado: {when}"
                                                           "</span>" if when else ""))
        else:
            self.summary.setText("<i>Aún no he estudiado tu estilo. Elige tus carpetas y pulsa «Analizar».</i>")

    def done(self, r):
        if self.job is not None:
            self.job.cancel()
            self.job.wait(5000)
            self.job = None
        self._store()
        super().done(r)
