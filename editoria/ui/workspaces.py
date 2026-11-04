"""
🗂 Pestañas de trabajo: «🎬 YouTube» (videos 16:9), «🎵 Edits» y «📱 Shorts», cada una con SU proyecto.

  · Al cambiar de pestaña se guarda lo que llevabas y se abre el proyecto de la otra tal como lo dejaste.
      - Con nombre (guardado en un .eia): se guarda en su archivo (como el guardado en vivo).
      - Sin nombre: se guarda en datos/espacios/<pestaña>.eia (no se pierde aunque cierres Reclaimer).
  · Al abrir Reclaimer vuelves a la pestaña en la que estabas, con su proyecto.
  · Ctrl+N = proyecto nuevo EN la pestaña actual; abrir un .eia lo pone en la pestaña de su tipo.
  · Nada se pierde: si un proyecto sin nombre se sustituye (nuevo / abrir), antes se guarda una copia de seguridad
    (Archivo → «⟲ Recuperar una copia»).
  Cada pestaña tiene SU historial de deshacer: al volver a ella, Ctrl+Z sigue deshaciendo lo que hiciste allí
  (mientras Reclaimer esté abierto; al cerrarlo, el trabajo queda guardado pero el historial empieza de nuevo).
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QMessageBox, QTabBar

from ..core.paths import app_data_dir

TABS = [("youtube", "🎬  YouTube"), ("edit", "🎵  Edits"), ("short", "📱  Shorts")]
KEYS = [k for k, _ in TABS]


def ws_file(fmt: str) -> str:
    d = app_data_dir() / "espacios"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{fmt}.eia")


class Workspaces(QObject):
    switched = Signal(str)

    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.settings = QSettings("EditorIA", "EditorIA")
        self.current = "youtube"
        self.bar = QTabBar()
        self.bar.setObjectName("workspacetabs")
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setUsesScrollButtons(False)     # las tres siempre a la vista
        self.bar.setDocumentMode(True)
        for key, title in TABS:
            self.bar.addTab(title)
        self.bar.setTabToolTip(0, "Videos de YouTube (16:9) · Ctrl+1\nCada pestaña tiene su propio proyecto: al "
                                  "cambiar, se guarda lo que llevas y se abre el otro tal como lo dejaste.")
        self.bar.setTabToolTip(1, "Edits musicales (9:16) · Ctrl+2\nSu proyecto (y su Ctrl+Z) van aparte.")
        self.bar.setTabToolTip(2, "YouTube Shorts (9:16) · Ctrl+3\nSu proyecto (y su Ctrl+Z) van aparte.")
        self.bar.setStyleSheet(
            "QTabBar#workspacetabs::tab { padding: 4px 14px; margin: 0 2px; color: #9da2ab; border: none; "
            "border-bottom: 2px solid transparent; background: transparent; }"
            "QTabBar#workspacetabs::tab:selected { color: #f0f1f4; border-bottom: 2px solid #e8833a; }"
            "QTabBar#workspacetabs::tab:hover:!selected { color: #d6d9df; }")
        self._guard = False
        self.started = False                     # hasta start() (al abrir Reclaimer) no toca nada guardado
        self.stacks: dict = {}                   # historial de deshacer de cada pestaña (en memoria)
        self.bar.currentChanged.connect(self._tab_changed)
        self.ctrl.workspace_file = None

    # ------------------------------------------------------------ estado
    def _key(self, fmt: str) -> str:
        return f"espacios/{fmt}/ruta"

    def _set_bar(self, fmt: str):
        self._guard = True
        self.bar.setCurrentIndex(KEYS.index(fmt))
        self._guard = False

    def start(self):
        """Al abrir Reclaimer: la pestaña donde estabas, con su proyecto."""
        self.started = True
        fmt = str(self.settings.value("espacios/actual", "youtube"))
        self.current = fmt if fmt in KEYS else "youtube"
        self._set_bar(self.current)
        self.restore(self.current)

    def _has_work(self) -> bool:
        p = self.ctrl.project
        return bool(p.clips or p.media)

    def store(self, ask: bool = True) -> bool:
        """Guarda el proyecto de la pestaña actual. False si cancelaste."""
        c = self.ctrl
        self.stacks[self.current] = c.undo_stack          # su historial de deshacer queda con ella
        if c.path:
            self.settings.setValue(self._key(self.current), c.path)
            if c.dirty:
                from .saving import _cfg
                if _cfg()["live"]:
                    c.save(c.path, backup=False)
                elif ask and not self.win._confirm_discard():
                    return False
                if c.dirty:                      # elegiste «no guardar»: ese historial ya no vale
                    self.stacks.pop(self.current, None)
            return True
        self.settings.setValue(self._key(self.current), "")
        from ..core.controller import _atomic_write_json
        data = c.project.to_dict()
        data["_espacio"] = self.current
        _atomic_write_json(ws_file(self.current), data)
        c.undo_stack.setClean()
        c._media_dirty = False
        c.dirty_changed.emit()
        return True

    def restore(self, fmt: str):
        """Abre el proyecto de esa pestaña (o uno nuevo de su tipo), con SU historial de deshacer."""
        c = self.ctrl
        path = str(self.settings.value(self._key(fmt), "") or "")
        c.workspace_file = ws_file(fmt)
        c._switching = True
        try:
            st = self.stacks.get(fmt)
            self.stacks[fmt] = c.use_undo_stack(st)
            keep = st is not None
            try:
                if path and os.path.exists(path):
                    c.load(path, keep_undo=keep)
                    return
                if os.path.exists(ws_file(fmt)):
                    c.load_workspace(ws_file(fmt), keep_undo=keep)
                    return
            except (OSError, ValueError) as exc:
                self.win.statusBar().showMessage(f"⚠ No se pudo abrir el proyecto de esta pestaña: {exc}", 9000)
            self._new(fmt)
        finally:
            c._switching = False
            c.dirty_changed.emit()

    def _new(self, fmt: str):
        c = self.ctrl
        c.new_project()
        if fmt != "youtube":
            c.set_project_format(fmt)
        c.undo_stack.clear()
        c.undo_stack.setClean()
        c.dirty_changed.emit()

    def _busy(self) -> str:
        w = self.win
        for name, job in (("transcribiendo", getattr(getattr(w, "voice", None), "job", None)),
                          ("analizando con la IA", getattr(getattr(w, "ai_panel", None), "job", None))):
            if job is not None:
                return name
        return ""

    # ------------------------------------------------------------ cambiar
    def _tab_changed(self, idx: int):
        if self._guard or idx < 0:
            return
        if not self.switch(KEYS[idx]):
            self._set_bar(self.current)

    def switch(self, fmt: str) -> bool:
        if fmt == self.current:
            return True
        self.started = True
        busy = self._busy()
        if busy:
            self.win.statusBar().showMessage(f"Espera a que termine (está {busy}) antes de cambiar de pestaña.", 7000)
            return False
        try:
            self.win.engine.pause()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self.win, "_thumb_page", None) is not None and getattr(self.win, "_thumb_editor", None):
            self.win._thumb_editor.close()        # 🖼 la miniatura se guarda en ESTE proyecto antes de cambiar
        if not self.store():
            return False
        # 🗂 biblioteca común: lo que tenías en Medios aquí también estará en la otra pestaña (el usuario: «cuando me
        # paso de Shorts a YouTube y ya tengo medios, esos no se trasladan»). Sin generadores ni clips compuestos:
        # esos son de cada proyecto.
        p = self.ctrl.project
        carry = [m for m in p.media.values() if not getattr(m, "gen", None) and m.id not in (p.compounds or {})
                 and m.id not in self.ctrl.missing]
        self.current = fmt
        self.settings.setValue("espacios/actual", fmt)
        self._set_bar(fmt)
        self.restore(fmt)
        added = self.ctrl.adopt_media(carry)
        self.switched.emit(fmt)
        title = dict(TABS)[fmt].split("  ", 1)[-1]
        self.win.statusBar().showMessage(f"{title}: «{self.ctrl.project.name}». La otra pestaña quedó guardada."
                                         + (f" {added} medio(s) de la otra pestaña ya están aquí." if added else ""),
                                         6000)
        return True

    def _backup_unnamed(self):
        """Antes de sustituir un proyecto SIN nombre con trabajo: una copia de seguridad (se puede recuperar)."""
        c = self.ctrl
        if c.path or not self._has_work():
            return
        try:
            self.store(ask=False)
            dest = c.backup_now(ws_file(self.current), name=f"{c.project.name or 'Proyecto'} ({self.current})")
            self.win.statusBar().showMessage(f"💾 El proyecto sin nombre anterior quedó en las copias de seguridad "
                                             f"({os.path.basename(dest)}).", 9000)
        except OSError:
            pass

    def new_here(self):
        """Ctrl+N: proyecto nuevo en esta pestaña."""
        c = self.ctrl
        if c.path and c.dirty and not self.win._confirm_discard():
            return
        self._backup_unnamed()
        self.settings.setValue(self._key(self.current), "")
        try:
            os.remove(ws_file(self.current))
        except OSError:
            pass
        self._new(self.current)

    def reset_here(self) -> str:
        """🔄 Reinicio de proyecto: guarda una copia de seguridad de lo que hay y deja esta pestaña vacía (sin preguntar:
        ya preguntó quien llama). Devuelve la ruta de la copia."""
        import json
        import time
        from ..core.paths import backups_dir
        c = self.ctrl
        name = (c.project.name or "Proyecto").replace("/", "-").replace("\\", "-")
        dest = str(backups_dir() / f"{name}_antes del reinicio_{time.strftime('%Y%m%d_%H%M%S')}.eia")
        data = c.project.to_dict()
        data["_autosave_of"] = c.path
        with open(dest, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False))
        c.path = None                        # el .eia que tuviera no se toca: lo vacío es un proyecto nuevo
        self.settings.setValue(self._key(self.current), "")
        try:
            os.remove(ws_file(self.current))
        except OSError:
            pass
        self._new(self.current)
        return dest

    def open_into(self, path: str) -> bool:
        """Abrir un .eia: va a la pestaña de su tipo (la actual queda guardada)."""
        try:
            with open(path, encoding="utf-8") as f:
                fmt = json.load(f).get("format", "youtube")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.win, "No se pudo abrir", str(exc))
            return False
        fmt = fmt if fmt in KEYS else "youtube"
        if fmt != self.current:
            if self._busy():
                self.win.statusBar().showMessage("Espera a que termine la tarea en curso.", 6000)
                return False
            if not self.store():
                return False
            self.current = fmt
            self.settings.setValue("espacios/actual", fmt)
            self._set_bar(fmt)
            # el proyecto que esa pestaña tenía: si no tenía nombre y había trabajo, a las copias
            old = str(self.settings.value(self._key(fmt), "") or "")
            if not old and os.path.exists(ws_file(fmt)):
                try:
                    self.ctrl.backup_now(ws_file(fmt), name=f"Proyecto ({fmt})")
                except OSError:
                    pass
        else:
            c = self.ctrl
            if c.path and c.dirty and not self.win._confirm_discard():
                return False
            self._backup_unnamed()
        self.ctrl.workspace_file = ws_file(fmt)
        if self.stacks.get(fmt) is not self.ctrl.undo_stack:
            self.stacks[fmt] = self.ctrl.use_undo_stack(None)   # proyecto nuevo en esa pestaña: historial nuevo
        try:
            self.ctrl.load(path)
        except (OSError, ValueError) as exc:
            self.restore(fmt)                  # esta pestaña vuelve a lo suyo
            QMessageBox.warning(self.win, "No se pudo abrir", str(exc))
            return False
        self.settings.setValue(self._key(fmt), path)
        self.switched.emit(fmt)
        return True
