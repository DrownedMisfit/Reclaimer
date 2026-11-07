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

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QMenu, QMessageBox, QTabBar

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
        self.bar.setContextMenuPolicy(Qt.CustomContextMenu)     # clic derecho: «↪ Mover este proyecto a…»
        self.bar.setProperty("own_menu", True)
        self.bar.customContextMenuRequested.connect(self._bar_menu)
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

    # ------------------------------------------------------------ mover el proyecto a otra pestaña
    @staticmethod
    def _label(fmt: str) -> str:
        return dict(TABS)[fmt].split("  ", 1)[-1]          # «🎬  YouTube» → «YouTube»

    @staticmethod
    def _work_name(path: str):
        """Nombre del proyecto guardado en ese archivo si tiene clips o medios; None si está vacío o no se lee."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not (data.get("clips") or data.get("media")):
            return None
        return str(data.get("name") or "Proyecto sin título")

    def _occupied(self, fmt: str):
        """Lo que hay ya en la pestaña fmt (nombre del proyecto), o None si está libre."""
        path = str(self.settings.value(self._key(fmt), "") or "")
        if path and os.path.exists(path):
            return os.path.splitext(os.path.basename(path))[0]
        if os.path.exists(ws_file(fmt)):
            return self._work_name(ws_file(fmt))
        return None

    def fill_move_menu(self, menu: QMenu):
        """Archivo → «↪ Mover este proyecto a»: las tres pestañas; la actual, deshabilitada."""
        menu.clear()
        for key, title in TABS:
            a = menu.addAction(title.replace("  ", " "))
            a.setEnabled(key != self.current)
            a.triggered.connect(lambda _=False, k=key: self.move_to(k))

    def _bar_menu(self, pos):
        """Clic derecho en las pestañas de trabajo: mover el proyecto a una de las otras dos."""
        from . import help as help_ui
        menu = QMenu(self.bar)
        for key, _title in TABS:
            if key != self.current:
                menu.addAction(f"↪ Mover este proyecto a «{self._label(key)}»").triggered.connect(
                    lambda _=False, k=key: self.move_to(k))
        help_ui.exec_menu(menu, self.bar.mapToGlobal(pos))
        menu.deleteLater()

    def move_to(self, fmt: str, ask: bool = True) -> bool:
        """Mueve el proyecto actual a la pestaña fmt cambiando su formato (Ctrl+Z lo devuelve).
        La pestaña de origen queda vacía. Si el destino ya tenía trabajo: copia de seguridad y se reemplaza."""
        if fmt == self.current or fmt not in KEYS:
            return False
        busy = self._busy()
        if busy:
            self.win.statusBar().showMessage(f"Espera a que termine (está {busy}) antes de mover el proyecto.", 7000)
            return False
        try:
            self.win.engine.pause()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self.win, "_thumb_page", None) is not None and getattr(self.win, "_thumb_editor", None):
            self.win._thumb_editor.close()
        c = self.ctrl
        src, dst = self.current, fmt
        dst_path = str(self.settings.value(self._key(dst), "") or "")
        occupied = self._occupied(dst)
        if occupied is not None and ask:
            r = QMessageBox.question(
                self.win, "Mover proyecto",
                f"La pestaña «{self._label(dst)}» ya tiene «{occupied}». Se guardará una copia de seguridad y "
                "este proyecto ocupará su lugar. ¿Continuar?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Yes:
                return False
        if occupied is not None:                 # lo que había en el destino, a las copias (no se borra un .eia con nombre)
            origin = dst_path if dst_path and os.path.exists(dst_path) else ws_file(dst)
            try:
                c.backup_now(origin, name=f"Proyecto ({dst})")
            except OSError as exc:               # sin copia no se reemplaza nada (no se pierde trabajo)
                QMessageBox.warning(self.win, "Mover proyecto",
                                    f"No se pudo guardar la copia de seguridad de «{occupied}», así que no se movió "
                                    f"nada.\n\n{exc}")
                return False
        # 3. formato del proyecto: un paso de deshacer (Ctrl+Z vuelve al formato anterior)
        c.set_project_format(dst)
        if c.project.format != dst:
            return False
        # 4. el historial se va con el proyecto
        old = self.stacks.get(dst)
        self.stacks[dst] = c.undo_stack
        self.stacks.pop(src, None)
        if old is not None and old is not c.undo_stack:
            c.undo_group.removeStack(old)
        # 5. asociaciones: el proyecto ocupa el destino; el origen queda vacío
        if c.path:
            self.settings.setValue(self._key(dst), c.path)
            if c.dirty:
                from .saving import _cfg
                if _cfg()["live"]:
                    c.save(c.path, backup=False)
        else:
            from ..core.controller import _atomic_write_json
            self.settings.setValue(self._key(dst), "")
            data = c.project.to_dict()
            data["_espacio"] = dst
            _atomic_write_json(ws_file(dst), data)
            c.undo_stack.setClean()
            c._media_dirty = False
            c.dirty_changed.emit()
        self.settings.setValue(self._key(src), "")
        if c.path and self._occupied(src) is not None:   # un proyecto sin nombre antiguo en el origen: a las copias
            try:
                c.backup_now(ws_file(src), name=f"Proyecto ({src})")
            except OSError:
                pass
        try:
            os.remove(ws_file(src))
        except OSError:
            pass
        if c.path:                               # con nombre: su .eia ya no es de la pestaña de origen
            try:
                os.remove(ws_file(dst))          # (el sin nombre que hubiera en el destino ya está en las copias)
            except OSError:
                pass
        # 6. cambiar la pestaña sin recargar el proyecto (ya es el bueno)
        self.current = dst
        self.started = True
        self.settings.setValue("espacios/actual", dst)
        c.workspace_file = ws_file(dst)
        self._set_bar(dst)
        self.switched.emit(dst)
        # 7. aviso
        ratio = "9:16" if c.project.height > c.project.width else "16:9"
        nombre = c.project.name or "Proyecto sin título"
        self.win.statusBar().showMessage(f"↪ «{nombre}» ahora está en {self._label(dst)} ({ratio}). "
                                         "Ctrl+Z devuelve el formato anterior.", 8000)
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
