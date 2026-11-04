"""
Ventana «🔬 Entender mi biblioteca a fondo»: la IA revisa cada imagen y cada segundo de tus
videos, aprende quién y qué aparece (Jefe Maestro, Cortana, Locust…) y lo usa para elegir
el B-roll cuando lo nombras. Aquí ves lo que entendió y editas los apodos.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..ai import library_understanding as LU
from ..core import media as media_tools
from ..core.model import KIND_IMAGE, KIND_VIDEO
from ..core.paths import cache_dir
from . import help as help_ui
from .common import fmt_time
from .jobs import BackgroundJob


def glossary_text() -> str:
    return str(QSettings("EditorIA", "EditorIA").value("ia/glosario", LU.STARTER_GLOSSARY))


def snapshot(ctrl) -> dict:
    """Lo que hace falta para trabajar en segundo plano (sin tocar el proyecto desde otro hilo)."""
    p = ctrl.project
    media = [{"media_id": m.id, "path": m.path, "kind": m.kind, "duration": m.duration, "name": m.name,
              "tags": list(m.tags), "meta": " ".join([m.name, m.category] + list(m.tags))}
             for m in p.media.values() if m.kind in (KIND_VIDEO, KIND_IMAGE) and m.id not in ctrl.missing]
    words = [w for tr in p.transcripts.values() for w in tr.get("words", [])]
    return {"media": media, "words": words}


def understand(snap: dict, glossary: str, progress, cancelled, partial=None, deep: bool = True) -> dict:
    """Análisis a fondo de todo + entidades + índice + miniaturas de los mejores momentos."""
    media = snap["media"]
    data = {}
    total = sum(max(1.0, m["duration"]) for m in media) or 1.0
    done = 0.0
    for m in media:
        if cancelled():
            from ..ai.base import Cancelled
            raise Cancelled()
        base = done / total
        share = max(1.0, m["duration"]) / total

        def prog(f, _t, base=base, share=share, name=m["name"]):
            progress(0.9 * (base + share * f), f"🔬 Revisando «{name}» segundo a segundo…")
        prog(0.0, "")
        try:
            res = LU.analyze_deep(m["path"], m["kind"], m["duration"], prog, cancelled) if deep \
                else LU.load_deep(m["path"])
        except Exception:  # noqa: BLE001 - un archivo roto no detiene el resto
            res = None
        done += max(1.0, m["duration"])
        if res is None:
            continue
        if partial:
            partial((m["media_id"], res))
        data[m["media_id"]] = dict(res, kind=m["kind"], duration=m["duration"])
    progress(0.92, "◈ Aprendiendo quién y qué aparece…")
    ents = LU.build_entities(media, snap["words"], glossary)
    meta = {m["media_id"]: m["meta"] for m in media}
    index = LU.build_index(ents, data, meta)
    # Miniaturas de los 3 mejores momentos de cada nombre (para que veas si acertó)
    thumbs: dict[tuple[str, float], str] = {}
    paths = {m["media_id"]: m["path"] for m in media}
    folder = cache_dir("entidades")
    for name, hits in index.items():
        for h in hits[:3]:
            key = (h.media_id, round(h.time, 1))
            out = os.path.join(str(folder), f"{media_tools.cache_key(paths[h.media_id])}_{h.time:.1f}.jpg")
            if not os.path.exists(out):
                media_tools.run_quiet([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{h.time:.2f}",
                                       "-i", paths[h.media_id], "-frames:v", "1", "-vf", "scale=160:-2", out],
                                      timeout=30)
            if os.path.exists(out):
                thumbs[key] = out
    progress(1.0, "Listo")
    return {"entities": ents, "index": index, "thumbs": thumbs, "n_media": len(data),
            "n_shots": sum(len(d.get("shots", [])) for d in data.values() if d["kind"] != "image")}


class UnderstandDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.job: BackgroundJob | None = None
        self.setWindowTitle("🔬 Entender mi biblioteca a fondo")
        self.resize(820, 680)
        help_ui.set_help(self, "entender")
        lay = QVBoxLayout(self)
        intro = QLabel("La IA revisa cada imagen y cada segundo de tus videos y aprende <b>quién y qué aparece</b>. "
                       "Luego, cuando nombras a alguien en tu narración, el B-roll muestra un plano donde sale. "
                       "Truco: añade a la biblioteca imágenes con el nombre de lo que muestran "
                       "(«jefe maestro.png», «cortana.jpg»): le enseñan cómo es y lo encuentra en tus videos.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nombre", "Aparece", "Lo sé por"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 180)
        self.tree.setIconSize(QSize(96, 54))
        split.addWidget(self.tree)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Nombres y apodos (uno por línea):\n«Jefe Maestro = Master Chief, John-117»"))
        self.gloss = QPlainTextEdit(glossary_text())
        rl.addWidget(self.gloss, 1)
        split.addWidget(right)
        split.setSizes([540, 260])
        lay.addWidget(split, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        btns = QHBoxLayout()
        self.btn_quick = QPushButton("Actualizar nombres")
        self.btn_quick.setToolTip("Vuelve a calcular quién aparece dónde (rápido) con los apodos que escribiste.")
        self.btn_quick.clicked.connect(lambda: self.start(deep=False))
        btns.addWidget(self.btn_quick)
        btns.addStretch(1)
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self._close)
        self.btn_go = QPushButton("🔬  Entender a fondo")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(lambda: self.start(deep=True))
        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_go)
        lay.addLayout(btns)
        if ctrl.understanding:
            self._show(ctrl.understanding)
        else:
            n = len(snapshot(ctrl)["media"])
            self.status.setText(f"{n} imágenes y videos en la biblioteca. Pulsa «Entender a fondo» "
                                "(≈1 minuto por cada hora de video; puedes dejarlo trabajando).")

    def start(self, deep: bool = True):
        if self.job is not None:
            return
        QSettings("EditorIA", "EditorIA").setValue("ia/glosario", self.gloss.toPlainText())
        snap = snapshot(self.ctrl)
        if not snap["media"]:
            self.status.setText("Primero importa tus imágenes y videos en el panel de medios.")
            return
        gloss = self.gloss.toPlainText()
        self.btn_go.setEnabled(False)
        self.btn_quick.setEnabled(False)
        self.btn_close.setText("Cancelar")
        self.bar.show()
        self.job = BackgroundJob(lambda prog, canc, part: understand(snap, gloss, prog, canc, part, deep),
                                 self, with_partial=True)
        self.job.progress.connect(lambda f, t: (self.bar.setValue(int(f * 1000)), self.status.setText(t)))
        self.job.partial.connect(lambda r: self.ctrl.set_deep_analysis(*r))
        self.job.done.connect(self._done)
        self.job.failed.connect(self._failed)
        self.job.start()

    def _done(self, res: dict):
        self.job = None
        self.ctrl.understanding = res
        self.ctrl.message.emit("🔬 La IA entendió tu biblioteca: el B-roll ya usa lo que aprendió.")
        self._reset_buttons()
        self._show(res)

    def _failed(self, msg: str):
        self.job = None
        self._reset_buttons()
        self.status.setText("✗ " + msg)

    def _reset_buttons(self):
        self.bar.hide()
        self.btn_go.setEnabled(True)
        self.btn_quick.setEnabled(True)
        self.btn_close.setText("Cerrar")

    def _show(self, res: dict):
        self.tree.clear()
        p = self.ctrl.project
        thumbs = res.get("thumbs", {})
        index = res.get("index", {})
        src_label = {"glosario": "glosario", "imagen": "tu imagen", "narración": "lo dices", "": "—"}
        for e in sorted(res.get("entities", []), key=lambda e: -len(index.get(e.name, []))):
            hits = index.get(e.name, [])
            kinds = {}
            for h in hits:
                m = p.media.get(h.media_id)
                k = "imagen" if (m and m.kind == KIND_IMAGE) else ((m.ai_type or "video").lower() if m else "?")
                kinds[k] = kinds.get(k, 0) + 1
            where = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])) or "no lo encontré"
            names = e.name + (f"  ({', '.join(e.aliases[:2])})" if e.aliases else "")
            src = src_label.get(e.source, e.source) + (f" + {len(e.refs)} imagen(es)" if e.refs and e.source != "imagen" else "")
            top = QTreeWidgetItem([names, f"{len(hits)} · {where}" if hits else where, src])
            if not hits:
                top.setForeground(1, Qt.gray)
            self.tree.addTopLevelItem(top)
            for h in hits[:3]:
                m = p.media.get(h.media_id)
                label = (m.name if m else "?") + ("" if (m and m.kind == KIND_IMAGE) else f"  ·  {fmt_time(h.time)}")
                it = QTreeWidgetItem([label, f"seguridad {min(99, int(h.score * 10))}", ""])
                th = thumbs.get((h.media_id, round(h.time, 1)))
                if th:
                    it.setIcon(0, QIcon(QPixmap(th)))
                top.addChild(it)
        found = sum(1 for e in res.get("entities", []) if index.get(e.name))
        self.status.setText(f"✓ {res.get('n_media', 0)} archivos revisados ({res.get('n_shots', 0)} planos de video). "
                            f"Reconozco {found} nombres en tus clips. Despliega uno para ver dónde aparece.")

    def _close(self):
        if self.job is not None:
            self.job.cancel()
            return
        QSettings("EditorIA", "EditorIA").setValue("ia/glosario", self.gloss.toPlainText())
        self.accept()

    def closeEvent(self, e):
        if self.job is not None:
            self.job.cancel()
            self.job.wait(5000)
        super().closeEvent(e)
