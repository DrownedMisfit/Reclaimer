"""
🔖 Marcas de OBS (interfaz). Las marcas que pusiste con una tecla mientras grababas en OBS (capítulos del MP4):

  · «🔖 Leer marcas de OBS» (clic derecho en Medios, o Editar): las pone como marcadores rojos en la línea de tiempo,
    en su sitio (si un tramo ya se quitó, en el corte más cercano). No duplica las que ya están. Un solo Deshacer.
  · «🔖 Fallos marcados» (panel pequeño, no modal): por cada marca, el tramo que propone quitar (la frase que se
    decía justo antes). ◀ Anterior / Siguiente, ▶ Escuchar, ✓ Quitar (con ripple en todas las pistas), ✓ Quitar todos
    (un solo Deshacer), Dejar.
La lógica de tiempos está en core/obs_markers.py (suggest_cut) y core/mapping.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from ..core import mapping, obs_markers
from ..core.model import KIND_IMAGE, ORIGIN_USER, Marker, new_id

MARK_COLOR = "#e5484d"          # rojo: las marcas de OBS se distinguen de los demás marcadores
AYUDA_OBS = ('OBS: Ajustes → Salida → Grabación → formato MP4 híbrido, y asigna una tecla a '
             '"Añadir marcador de capítulo"')
AYUDA_LARGA = ("Las marcas son capítulos del archivo: OBS (30.2 o posterior) los escribe si la grabación es «MP4 "
               "híbrido». Pulsa la tecla mientras grabas cada vez que te equivoques (con el complemento «Additional "
               "Chapter Hotkeys» les puedes poner nombre, p. ej. «NG»).")


def _tc(t: float) -> str:
    """0:12,4 (formato de la barra de estado en español)."""
    m, s = divmod(max(0.0, t), 60.0)
    return f"{int(m)}:{s:04.1f}".replace(".", ",")


def narration_ids(p) -> list[str]:
    """El archivo que tiene la narración: el primero con transcripción que esté en la línea de tiempo."""
    con_texto = [mid for mid, tr in p.transcripts.items() if mid in p.media and (tr or {}).get("words")]
    en_linea = {c.media_id for c in p.clips.values()}
    pref = [m for m in con_texto if m in en_linea] or con_texto
    if not pref:
        pref = [mid for mid, m in p.media.items() if m.category == "Narración" and m.kind != KIND_IMAGE]
    return pref[:1]


def _tl_time(p, mid: str, t: float) -> float | None:
    """Momento de la línea de tiempo del segundo t del archivo; si se quitó, el corte más cercano."""
    tt = mapping.map_time(p, mid, t)
    if tt is not None:
        return tt
    best = None
    for c in mapping.clips_of_media(p, mid):
        lo, hi = c.source_in, c.source_in + c.src_len
        pos_lo, pos_hi = (c.end, c.start) if c.reverse else (c.start, c.end)
        for f, tl in ((lo, pos_lo), (hi, pos_hi)):
            if best is None or abs(f - t) < best[0]:
                best = (abs(f - t), tl)
    return best[1] if best else None


def _juntar(tramos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for x, y in sorted(tramos):
        if out and x <= out[-1][1] + 1e-3:
            out[-1] = (out[-1][0], max(out[-1][1], y))
        else:
            out.append((x, y))
    return [(x, y) for x, y in out if y - x > 1e-3]


def _tramos_tl(p, mid: str, a: float, b: float) -> list[tuple[float, float]]:
    """Tramo [a, b] del archivo en la línea de tiempo (hay una copia por pista: se junta)."""
    piezas = [(min(x, y), max(x, y)) for _c, x, y in mapping.map_range(p, mid, a, b)]
    return _juntar(piezas)


def leer_marcas(win, media_ids=None) -> int:
    """Lee las marcas de OBS de esos archivos (o del de la narración) y las pone como marcadores rojos.
    Devuelve cuántas marcas hay. Abre el panel «Fallos marcados»."""
    ctrl = win.ctrl
    p = ctrl.project
    ids = [m for m in (media_ids or narration_ids(p)) if m in p.media]
    if not ids:
        win.statusBar().showMessage("🔖 No hay ningún archivo de narración en la línea de tiempo.", 8000)
        return 0
    marcas = []
    for mid in ids:
        m = p.media[mid]
        if m.kind == KIND_IMAGE:
            continue
        palabras = (p.transcripts.get(mid) or {}).get("words") or []
        for ch in obs_markers.read_chapters(m.path):
            a, b = obs_markers.suggest_cut(ch["t"], palabras)
            marcas.append({"mid": mid, "t": ch["t"], "title": ch["title"], "a": a, "b": b,
                           "tl": _tl_time(p, mid, ch["t"]), "mk": None})
    if not marcas:
        win.statusBar().showMessage("🔖 Sin marcas de OBS en este archivo. " + AYUDA_OBS, 15000)
        return 0

    nuevas = {"n": 0}

    def fn(pp):
        for mk in marcas:
            if mk["tl"] is None:
                continue
            dup = next((x for x in pp.markers if x.label == mk["title"] and abs(x.time - mk["tl"]) < 0.05), None)
            if dup is not None:
                mk["mk"] = dup.id
                continue
            marker_id = new_id()
            pp.markers.append(Marker(marker_id, round(max(0.0, mk["tl"]), 4), mk["title"], color=MARK_COLOR,
                                     origin=ORIGIN_USER))
            mk["mk"] = marker_id
            nuevas["n"] += 1
        pp.markers.sort(key=lambda x: x.time)

    ctrl._edit("🔖 Marcas de OBS", fn)          # un solo paso de Deshacer (método interno del controlador)
    win._obs_marks = marcas
    fallos_panel(win).set_marks(marcas)
    extra = f" · {nuevas['n']} nuevas" if nuevas["n"] != len(marcas) else ""
    win.statusBar().showMessage(f"🔖 {len(marcas)} marcas de OBS{extra}", 9000)
    return len(marcas)


def fallos_panel(win) -> "FallosPanel":
    panel = getattr(win, "_obs_fallos", None)
    if panel is None:
        panel = FallosPanel(win)
        win._obs_fallos = panel
    return panel


def abrir_fallos(win):
    """Menú «Fallos marcados»: con las marcas ya leídas, o leyéndolas ahora."""
    if not getattr(win, "_obs_marks", None):
        leer_marcas(win)
        return
    fallos_panel(win).set_marks(win._obs_marks)


class FallosPanel(QFrame):
    def __init__(self, win):
        super().__init__(win, Qt.Tool)
        self.win = win
        self.ctrl = win.ctrl
        self.engine = win.engine
        self.timeline = win.timeline
        self.marks: list[dict] = []
        self.k = 0
        self.setWindowTitle("Fallos marcados")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)

        head = QHBoxLayout()
        titulo = QLabel("🔖 Fallos marcados (marcas de OBS)")
        titulo.setStyleSheet("font-weight: bold;")
        head.addWidget(titulo)
        head.addStretch()
        self.counter = QLabel()
        head.addWidget(self.counter)
        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.setToolTip("Fallo anterior")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        head.addWidget(self.btn_prev)
        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.setToolTip("Fallo siguiente")
        self.btn_next.clicked.connect(lambda: self._step(1))
        head.addWidget(self.btn_next)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setMaximumHeight(130)
        self.list.setToolTip("Todas las marcas: clic en una para ir ahí")
        self.list.itemClicked.connect(lambda it: self._goto(self.list.row(it)))
        lay.addWidget(self.list)

        self.propuesta = QLabel()
        self.propuesta.setWordWrap(True)
        self.propuesta.setStyleSheet("color: #7fd1ae; font-weight: bold;")
        self.propuesta.setToolTip("El tramo que se quitaría: la frase que se decía justo antes de la marca, "
                                  "hasta la marca (o hasta la palabra siguiente, si la marca cayó en una pausa).")
        lay.addWidget(self.propuesta)

        fila = QHBoxLayout()
        self.btn_listen = QPushButton("▶ Escuchar")
        self.btn_listen.setToolTip("Reproduce desde 2 s antes de la marca")
        self.btn_listen.clicked.connect(self._listen)
        fila.addWidget(self.btn_listen)
        self.btn_cut = QPushButton("✓ Quitar")
        self.btn_cut.setToolTip("Quita ese tramo de la narración (cierra el hueco en todas las pistas). "
                                "Ctrl+Z lo devuelve.")
        self.btn_cut.clicked.connect(self._cut_one)
        fila.addWidget(self.btn_cut)
        self.btn_keep = QPushButton("Dejar")
        self.btn_keep.setToolTip("Deja este fallo tal cual: quita la marca de la lista y de la línea de tiempo")
        self.btn_keep.clicked.connect(self._keep)
        fila.addWidget(self.btn_keep)
        lay.addLayout(fila)

        self.btn_all = QPushButton("✓ Quitar todos")
        self.btn_all.setToolTip("Quita los tramos de todas las marcas de una vez. Todo en un solo paso de Deshacer "
                                "(Ctrl+Z)")
        self.btn_all.clicked.connect(self._cut_all)
        lay.addWidget(self.btn_all)
        ayuda = QLabel("¿Por qué no hay marcas?")
        ayuda.setStyleSheet("color: #8a8f99;")
        ayuda.setToolTip(AYUDA_LARGA + "\n\n" + AYUDA_OBS)
        lay.addWidget(ayuda)

        self.ctrl.project_changed.connect(self._refresh)
        self.ctrl.project_replaced.connect(lambda: self.set_marks([]))

    # ------------------------------------------------------------------ datos
    def set_marks(self, marks: list[dict]):
        self.marks = list(marks)
        self.k = 0
        self._refresh()
        if marks:
            self.show()
            self.raise_()

    def _current(self) -> dict | None:
        return self.marks[self.k] if 0 <= self.k < len(self.marks) else None

    def _info(self, mk: dict):
        """(momento de la línea de tiempo de la marca, tramos a quitar en la línea de tiempo), con lo que hay ahora."""
        p = self.ctrl.project
        if mk["mid"] not in p.media:
            return None, []
        return _tl_time(p, mk["mid"], mk["t"]), _tramos_tl(p, mk["mid"], mk["a"], mk["b"])

    def _refresh(self, *_):
        p = self.ctrl.project
        self.marks = [mk for mk in self.marks if mk["mid"] in p.media]
        if self.k >= len(self.marks):
            self.k = max(0, len(self.marks) - 1)
        self.list.blockSignals(True)
        self.list.clear()
        for mk in self.marks:
            tl, regs = self._info(mk)
            pos = _tc(tl) if tl is not None else "—"
            estado = "" if regs else " (nada que quitar)"
            self.list.addItem(QListWidgetItem(f"{pos} · {mk['title']}{estado}"))
        if self.marks:
            self.list.setCurrentRow(self.k)
        self.list.blockSignals(False)
        n = len(self.marks)
        self.counter.setText(f"{self.k + 1} de {n}" if n else "Ninguna marca")
        for b in (self.btn_prev, self.btn_next, self.btn_all):
            b.setEnabled(n > 0)
        mk = self._current()
        for b in (self.btn_listen, self.btn_cut, self.btn_keep):
            b.setEnabled(mk is not None)
        if mk is None:
            self.propuesta.setText("No quedan marcas. Lee otra vez las de OBS desde Editar o Medios.")
            return
        _tl, regs = self._info(mk)
        if regs:
            self.propuesta.setText(f"Quitar {_tc(regs[0][0])}–{_tc(regs[-1][1])} (la frase anterior) · "
                                   f"{mk['title']}")
        else:
            self.propuesta.setText(f"{mk['title']}: no hay tramo que quitar (ya quitado, o no hay voz antes).")

    # ------------------------------------------------------------ navegación
    def _goto(self, k: int):
        if not (0 <= k < len(self.marks)):
            return
        self.k = k
        tl, _regs = self._info(self.marks[k])
        if tl is not None:
            self.engine.user_seek(tl)
            self.timeline.set_playhead(tl, follow=True)
        self._refresh()

    def _step(self, paso: int):
        if self.marks:
            self._goto((self.k + paso) % len(self.marks))

    # ------------------------------------------------------------- acciones
    def _listen(self):
        mk = self._current()
        if mk is None:
            return
        tl, _regs = self._info(mk)
        if tl is not None:
            self.engine.play_ranges([(max(0.0, tl - 2.0), tl + 2.0)])

    def _quitar_marcas(self, mks: list[dict], regs: list[tuple[float, float]], texto: str) -> bool:
        """Quita los tramos (ripple en todas las pistas) y las marcas rojas de esas marcas: un solo Deshacer."""
        stack = self.ctrl.undo_stack
        stack.beginMacro(texto)
        try:
            ok = True
            if regs:
                ok = self.ctrl.remove_silence([], regs, scope="all") is not None
            if ok:
                for mk in mks:
                    if mk.get("mk"):
                        self.ctrl.remove_marker(mk["mk"])
        finally:
            stack.endMacro()
        return ok

    def _cut_one(self):
        mk = self._current()
        if mk is None:
            return
        _tl, regs = self._info(mk)
        if not regs:
            self.marks.remove(mk)
            self.win.statusBar().showMessage("Ese tramo ya no está en la línea de tiempo.", 6000)
            self._refresh()
            return
        if self._quitar_marcas([mk], regs, "Quitar fallo de OBS"):
            self.marks.remove(mk)
            self.win.statusBar().showMessage(f"✂ Quitado {_tc(regs[0][0])}–{_tc(regs[-1][1])}. "
                                             "Ctrl+Z lo devuelve.", 7000)
        self._refresh()

    def _cut_all(self):
        regs: list[tuple[float, float]] = []
        con_tramo: list[dict] = []
        for mk in self.marks:
            _tl, r = self._info(mk)
            if r:
                regs += r
                con_tramo.append(mk)
        if not regs:
            self.win.statusBar().showMessage("No hay tramos que quitar: ya no están en la línea de tiempo.", 6000)
            return
        regs = _juntar(regs)
        total = sum(y - x for x, y in regs)
        if self._quitar_marcas(self.marks, regs, "Quitar fallos de OBS"):
            self.win.statusBar().showMessage(f"✂ {len(con_tramo)} fallos quitados ({total:.1f} s). "
                                             "Ctrl+Z los devuelve todos.", 9000)
            self.marks = []
            self.k = 0
        self._refresh()

    def _keep(self):
        mk = self._current()
        if mk is None:
            return
        if mk.get("mk"):
            self.ctrl.remove_marker(mk["mk"])
        self.marks.remove(mk)
        self._refresh()
