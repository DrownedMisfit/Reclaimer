"""
✏ Corregir un subtítulo desde el visor: doble clic sobre su texto → campo flotante con esa frase (la palabra
pulsada, seleccionada). Enter guarda, Esc cancela. Corrige la TRANSCRIPCIÓN (la misma que el panel Texto) y se
deshace con un solo Ctrl+Z.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit

from ..ai import word_fix


def correct(ctrl, media_id: str, indices: list[int], text: str) -> str | None:
    """Cambia las palabras `indices` de la transcripción por `text`. Es un solo paso de deshacer (lo pone el
    controlador, con el nombre «Corregir subtítulo»). Devuelve un aviso si no se pudo (o None)."""
    tr = ctrl.project.transcripts.get(media_id)
    if not tr:
        return "No encuentro la transcripción de este subtítulo."
    words = tr.get("words", [])
    idx = sorted(i for i in set(indices) if 0 <= i < len(words))
    new = text.split()
    if not idx or not new:
        return None
    old = [words[i][2] for i in idx]
    if [word_fix.core(o) for o in old] == [word_fix.core(n) for n in new]:
        return None                                       # nada cambió
    if len(new) == len(idx):                               # mismo número de palabras: cada una conserva sus tiempos
        texts = {i: word_fix.with_punct(words[i][2], n) for i, n in zip(idx, new)
                 if word_fix.core(words[i][2]) != word_fix.core(n)}
        ctrl.edit_word_texts(media_id, texts, label="Corregir subtítulo")
    elif idx == list(range(idx[0], idx[-1] + 1)):          # cambia el número: las nuevas se reparten en su tramo
        ctrl.edit_words(media_id, idx, " ".join(new), label="Corregir subtítulo")
    else:
        return "Este subtítulo tiene palabras separadas por un corte: cambia la misma cantidad de palabras."
    return None


class SubtitleEditor(QLineEdit):
    """Campo flotante encima del visor (hijo del visor). Enter = guardar · Esc = cancelar."""

    def __init__(self, ctrl, host):
        super().__init__(host)
        self._ctrl = ctrl
        self._ctx: tuple[str, list[int]] | None = None
        self.setToolTip("Corregir el subtítulo · Enter = guardar · Esc = cancelar")
        self.setMinimumHeight(26)
        self.hide()

    def open(self, media_id: str, indices: list[int], clicked: int, rect):
        """Muestra el campo con la frase de esos índices y selecciona la palabra pulsada."""
        words = self._ctrl.project.transcripts.get(media_id, {}).get("words", [])
        idx = [i for i in indices if 0 <= i < len(words)]
        if not idx:
            return
        text = " ".join(words[i][2] for i in idx)
        self._ctx = (media_id, idx)
        self.setText(text)
        start, length = 0, len(text)
        pos = 0
        for i in idx:
            tok = words[i][2]
            if i == clicked:
                start, length = pos, len(tok)
                break
            pos += len(tok) + 1
        host = self.parentWidget()
        w = max(300, min(max(rect.width(), 300) + 60, host.width() - 16))
        x = min(max(4, rect.center().x() - w // 2), host.width() - w - 4)
        y = rect.top() - 38
        if y < 4:
            y = rect.bottom() + 8
        self.setGeometry(int(x), int(y), int(w), 28)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self.setSelection(start, length)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()
        elif e.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if self._ctx is not None:          # clic fuera = cancelar (no guarda a medias)
            self._cancel()

    def _cancel(self):
        self._ctx = None
        self.hide()
        if self.parentWidget() is not None:
            self.parentWidget().setFocus()

    def _commit(self):
        ctx, self._ctx = self._ctx, None
        text = self.text()
        self.hide()
        if self.parentWidget() is not None:
            self.parentWidget().setFocus()
        if ctx is None:
            return
        media_id, idx = ctx
        msg = correct(self._ctrl, media_id, idx, text)
        if msg:
            self._ctrl.message.emit(msg)
