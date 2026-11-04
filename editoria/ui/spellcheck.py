"""
✍ Ortografía en los cuadros de texto que escribes TÚ (texto en pantalla, miniaturas, frases del edit). Nada que ver
con la transcripción.

  row = attach(cuadro)      # subrayado rojo ondulado + clic derecho con sugerencias; devuelve la fila «Ortografía: …»

El idioma (Mixto · Español (México) · English · Sin corregir) es el mismo para todos los cuadros y se recuerda.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QMenu, QWidget

from ..core import spelling as SP

KEY = "texto/ortografia"
_highlighters: "weakref.WeakSet[SpellHighlighter]" = weakref.WeakSet()
_combos: "weakref.WeakSet[QComboBox]" = weakref.WeakSet()


def current_lang() -> str:
    v = str(QSettings("EditorIA", "EditorIA").value(KEY, "mixto"))
    return v if v in SP.LANGS else "mixto"


def set_lang(lang: str):
    QSettings("EditorIA", "EditorIA").setValue(KEY, lang)
    SP.preload(lang)
    for c in list(_combos):                    # todos los cuadros con el mismo idioma
        try:
            i = c.findData(lang)
            if i >= 0 and c.currentIndex() != i:
                c.blockSignals(True)
                c.setCurrentIndex(i)
                c.blockSignals(False)
        except RuntimeError:
            pass
    _rehighlight_when_ready()


def _rehighlight_when_ready(tries: int = 60):
    """Los diccionarios se cargan en segundo plano (~0,8 s): en cuanto estén, se subraya."""
    if SP.ready(current_lang()) or current_lang() == "off" or tries <= 0:
        for h in list(_highlighters):
            try:
                h.rehighlight()
            except RuntimeError:
                pass
        return
    QTimer.singleShot(150, lambda: _rehighlight_when_ready(tries - 1))


class SpellHighlighter(QSyntaxHighlighter):
    """Subraya en rojo ondulado las palabras mal escritas."""

    def __init__(self, document):
        super().__init__(document)
        self.fmt = QTextCharFormat()
        self.fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self.fmt.setUnderlineColor(QColor("#ff4d4d"))
        _highlighters.add(self)

    def highlightBlock(self, text: str):
        lang = current_lang()
        if lang == "off" or not SP.ready(lang):
            return
        for a, b in SP.misspelled(text, lang):
            self.setFormat(a, b - a, self.fmt)


def _word_at(edit, pos):
    """(cursor que selecciona la palabra, palabra) bajo el ratón, o (None, "")."""
    cur = edit.cursorForPosition(pos)
    block = cur.block()
    text = block.text()
    k = cur.positionInBlock()
    for m in SP.WORD_RE.finditer(text):
        if m.start() <= k <= m.end():
            c = QTextCursor(block)
            c.setPosition(block.position() + m.start())
            c.setPosition(block.position() + m.end(), QTextCursor.KeepAnchor)
            return c, m.group()
    return None, ""


def _context_menu(edit, pos):
    from .help import exec_menu
    menu = QMenu(edit)
    lang = current_lang()
    cur, word = _word_at(edit, pos)
    if cur is not None and lang != "off" and SP.ready(lang) and not SP.is_ok(word, lang):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sugg = SP.suggest(word, lang)
        finally:
            QApplication.restoreOverrideCursor()
        title = menu.addAction(f"«{word}»: ¿quisiste decir…?")
        title.setEnabled(False)
        for s in sugg:
            menu.addAction(s, lambda s=s, c=cur: c.insertText(s))      # se deshace con Ctrl+Z del cuadro
        if not sugg:
            none = menu.addAction("(sin sugerencias)")
            none.setEnabled(False)
        menu.addSeparator()
        menu.addAction(f"📖 Añadir «{word}» al diccionario",
                       lambda w=word: (SP.add_word(w), _rehighlight_when_ready()))
        menu.addAction("Ignorar (mientras Reclaimer esté abierto)", lambda w=word: (SP.ignore(w), _rehighlight_when_ready()))
        menu.addSeparator()
    for a in edit.createStandardContextMenu().actions():    # cortar, copiar, pegar… de siempre
        a.setParent(menu)
        menu.addAction(a)
    exec_menu(menu, edit.viewport().mapToGlobal(pos))   # (la posición llega en coordenadas del área de texto)


def attach(edit) -> QWidget:
    """Añade la ortografía a un QPlainTextEdit / QTextEdit y devuelve la fila «✍ Ortografía: [idioma]»."""
    edit._spell = SpellHighlighter(edit.document())
    edit.setContextMenuPolicy(Qt.CustomContextMenu)
    edit.customContextMenuRequested.connect(lambda p, e=edit: _context_menu(e, p))
    SP.preload(current_lang())
    _rehighlight_when_ready()
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    lab = QLabel("✍ Ortografía")
    lab.setObjectName("dim")
    combo = QComboBox()
    for k, name in SP.LANGS.items():
        combo.addItem(name, k)
    combo.setCurrentIndex(max(0, combo.findData(current_lang())))
    combo.setToolTip("Corrige lo que escribes (no la transcripción). «Mixto»: vale el español de México y el inglés "
                     "(para cuando mezclas, p. ej. «el boss final del gameplay»).\nClic derecho en una palabra "
                     "subrayada: sugerencias, añadir al diccionario o ignorar.")
    combo.currentIndexChanged.connect(lambda _i, c=combo: set_lang(c.currentData()))
    _combos.add(combo)
    h.addWidget(lab)
    h.addWidget(combo, 1)
    return row
