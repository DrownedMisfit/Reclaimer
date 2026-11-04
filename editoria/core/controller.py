"""
Controlador del proyecto: TODAS las modificaciones de la timeline pasan por aquí.

- Cada modificación se registra en la pila de deshacer/rehacer.
- Ninguna operación puede tocar pistas o clips bloqueados (🔒).
- La biblioteca (archivos importados) no forma parte del deshacer.

Más adelante, la IA usará exactamente estas mismas funciones (con origin="ai"),
así que sus cambios también serán reversibles y respetarán los bloqueos.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QUndoCommand, QUndoGroup, QUndoStack

from . import mapping
from . import media as media_tools
from .model import (DEFAULT_IMAGE_DURATION, KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, ORIGIN_AI, ORIGIN_USER,
                    SUG_APPLIED, SUG_PENDING, SUG_REJECTED, TEXT_DEFAULTS, TRACK_AUDIO, TRACK_TEXT,
                    TRACK_VIDEO, Clip, Marker,
                    MediaItem, Project, Suggestion, Track, kind_for_path, new_id)
from .organize import classify
from .paths import autosave_path, backups_dir

EPS = 1e-6
MIN_CLIP = 0.05  # duración mínima de un clip (segundos)


class EditError(Exception):
    """Error esperado de edición (p. ej. tocar algo bloqueado). Se muestra al usuario."""


def pack_state(state: dict) -> bytes:
    """Estado de la timeline comprimido para el historial (≈ 15–20 veces más pequeño que en memoria)."""
    import zlib
    return zlib.compress(json.dumps(state, separators=(",", ":")).encode("utf-8"), 1)   # (nivel 1: el más rápido)


def unpack_state(data: bytes) -> dict:
    import zlib
    return json.loads(zlib.decompress(data).decode("utf-8"))


class _RenameCommand(QUndoCommand):
    """Cambiar el nombre del video/proyecto (Ctrl+Z lo deshace)."""

    def __init__(self, ctrl, old: str, new: str):
        super().__init__(f"Nombre: {new}")
        self.ctrl, self.old, self.new = ctrl, old, new

    def redo(self):
        self.ctrl.project.name = self.new
        self.ctrl.project_changed.emit()

    def undo(self):
        self.ctrl.project.name = self.old
        self.ctrl.project_changed.emit()


class _StateCommand(QUndoCommand):
    """Un paso de deshacer: guarda (comprimido) el estado de la timeline antes y después del cambio.
    El «después» de un paso y el «antes» del siguiente son el mismo objeto: no se guarda dos veces."""

    def __init__(self, ctrl: "ProjectController", before: bytes, after: bytes, text: str,
                 merge_id: int = -1):
        super().__init__(text)
        self._ctrl, self._before, self._after = ctrl, before, after
        self._first = True
        self._merge_id = merge_id
        self._time = time.monotonic()

    def id(self) -> int:
        return self._merge_id

    def mergeWith(self, other) -> bool:
        """Cambios seguidos del mismo tipo (p. ej. ajustar el tamaño) cuentan como un solo paso."""
        if other.id() != self._merge_id or other.text() != self.text() or other._time - self._time > 3.0:
            return False
        self._after = other._after
        self._time = other._time
        return True

    def redo(self):
        if self._first:  # el cambio ya se aplicó al crearse
            self._first = False
            return
        self._ctrl._apply_packed(self._after)

    def undo(self):
        self._ctrl._apply_packed(self._before)


class _AnalysisSignals(QObject):
    done = Signal(str, object)
    rhythm = Signal(str, object)


class _RhythmTask(QRunnable):
    """Reconoce el ritmo de una canción en segundo plano (golpes, compases, drop, partes)."""

    def __init__(self, media_id: str, path: str, signals: _AnalysisSignals):
        super().__init__()
        self.media_id, self.path, self.signals = media_id, path, signals

    def run(self):
        try:
            from ..ai import rhythm
            res = rhythm.analyze(self.path)
        except Exception as exc:  # noqa: BLE001 - se informa al usuario
            res = {"error": str(exc)}
        try:
            self.signals.rhythm.emit(self.media_id, res)
        except RuntimeError:          # se cerró Reclaimer mientras se analizaba
            pass


class _AnalyzeTask(QRunnable):
    """Analiza un archivo en segundo plano (no congela la interfaz)."""

    def __init__(self, media_id: str, path: str, kind: str, signals: _AnalysisSignals):
        super().__init__()
        self.media_id, self.path, self.kind, self.signals = media_id, path, kind, signals

    def run(self):
        result: dict = {}
        try:
            info = media_tools.probe(self.path)
            result["info"] = info
            if self.kind in (KIND_VIDEO, KIND_IMAGE):
                result["thumb"] = media_tools.thumbnail(self.path, self.kind, info["duration"])
            if self.kind == KIND_AUDIO or (self.kind == KIND_VIDEO and info.get("has_audio")):
                result["peaks"] = media_tools.waveform_peaks(self.path)
            # (las pistas de OBS ya no se separan solas al importar: el usuario lo pide con «⋮ → 🎵 Separar audio»)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se informa al usuario
            result["error"] = str(exc)
        try:
            self.signals.done.emit(self.media_id, result)
        except RuntimeError:          # se cerró Reclaimer mientras se analizaba
            pass


def _json_default(o):
    """Números de numpy (p. ej. tiempos que vienen de la IA) → número normal; nunca falla al guardar."""
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"{type(o).__name__} no se puede guardar")


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # ⚡ Sin sangría y de una vez: así Python usa su codificador rápido (en C). Antes era ~6 veces más lento y el
        # guardado en vivo (cada vez que paras de editar) congelaba un momento el programa en los proyectos grandes
        f.write(json.dumps(data, ensure_ascii=False, default=_json_default))   # de una vez (no en miles de trocitos)
    os.replace(tmp, path)


class ProjectController(QObject):
    project_changed = Signal()   # cambió la timeline (clips, pistas, marcadores, ajustes)
    media_changed = Signal()     # cambió la biblioteca
    project_replaced = Signal()  # proyecto nuevo o abierto
    clips_placed = Signal(list)  # clips que se acaban de poner desde Medios (p. ej. para ✂ cortarlos por escena)
    transcript_changed = Signal(str)  # media_id
    dirty_changed = Signal()
    message = Signal(str)        # mensaje para la barra de estado
    rhythm_changed = Signal()    # se reconoció el ritmo de alguna canción
    saved = Signal(str)          # se guardó el proyecto (ruta)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = Project.new()
        self.path: str | None = None
        # Un historial de deshacer por pestaña de trabajo (🗂 YouTube · Edits · Shorts): el grupo sigue al activo
        # (Deshacer/Rehacer, guardado en vivo y aprendizaje escuchan al grupo, no a un historial concreto)
        self.undo_group = QUndoGroup(self)
        self.undo_group.cleanChanged.connect(self._on_clean_changed)
        self._switching = False
        self.undo_stack = self.new_undo_stack()
        self.undo_group.setActiveStack(self.undo_stack)
        self._media_dirty = False
        # Datos de trabajo (no se guardan en el proyecto)
        self.thumbs: dict[str, str] = {}
        self.peaks: dict[str, np.ndarray] = {}
        self.missing: set[str] = set()
        self.analyzing: set[str] = set()
        self.clip_vecs: dict[str, tuple[np.ndarray, np.ndarray]] = {}  # huellas IA de cada clip
        self.clip_shots: dict = {}       # planos de cada clip (análisis a fondo)
        self.understanding: dict | None = None   # lo que la IA entendió: entidades e índice
        self.beats: dict[str, list[float]] = {}   # golpes de la música (segundos del archivo)
        self.rhythm: dict[str, dict] = {}          # ritmo reconocido de cada canción (ai/rhythm.py)
        self.rhythm_busy: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(4, (os.cpu_count() or 4) // 4)))
        self._signals = _AnalysisSignals(self)
        self._signals.done.connect(self._on_analyzed)
        self._signals.rhythm.connect(self._on_rhythm)
        self.project_changed.connect(self._auto_rhythm)

    # ------------------------------------------------------------------ estado
    def shutdown(self, wait_ms: int = 3000) -> bool:
        """Al cerrar: se descartan los análisis de archivos pendientes y se espera al que esté en marcha.
        False si alguno no terminó a tiempo (entonces Reclaimer sale sin destruir su hilo: si no, se caía al cerrar
        justo después de importar o grabar algo)."""
        self._pool.clear()
        return bool(self._pool.waitForDone(wait_ms))

    def new_undo_stack(self) -> QUndoStack:
        st = QUndoStack(self)
        st.setUndoLimit(300)
        self.undo_group.addStack(st)
        return st

    def use_undo_stack(self, st: QUndoStack | None = None) -> QUndoStack:
        """🗂 Activa el historial de deshacer de una pestaña (o uno nuevo)."""
        st = st if st is not None else self.new_undo_stack()
        if st not in self.undo_group.stacks():
            self.undo_group.addStack(st)
        self.undo_stack = st
        self._last_packed = None            # la caché de «antes» era del historial anterior
        self.undo_group.setActiveStack(st)
        self.dirty_changed.emit()
        return st

    @property
    def dirty(self) -> bool:
        return self._media_dirty or not self.undo_stack.isClean()

    def _on_clean_changed(self, _clean: bool):
        self.dirty_changed.emit()

    def _set_media_dirty(self):
        if not self._media_dirty:
            self._media_dirty = True
            self.dirty_changed.emit()

    def _apply_state(self, state: dict):
        self.project.apply_timeline_state(state)
        self.project_changed.emit()

    split_av = True   # al poner un video, su sonido va a una pista de audio, vinculado (como en Resolve)
    proxy_level = "full"   # resolución de la línea de tiempo en el visor: full | half | quarter

    def preview_path(self, m) -> str:
        """Archivo que reproduce el visor: la copia ligera si se eligió «Media»/«Un cuarto» y ya existe.
        (Exportar usa siempre m.path, el original.)"""
        from .proxies import has_proxy, proxy_path
        if self.proxy_level != "full" and m.kind == KIND_VIDEO and has_proxy(m.path, self.proxy_level):
            return proxy_path(m.path, self.proxy_level)
        return m.path

    def _edit(self, text: str, fn, merge_id: int = -1):
        """Aplica fn(project) como un único paso de deshacer. Si algo falla, no cambia nada."""
        before = self.project.timeline_state()
        try:
            result = fn(self.project)
        except EditError as exc:
            self.project.apply_timeline_state(before)
            self.message.emit(str(exc))
            return None
        after = self.project.timeline_state()
        if after == before:
            return None
        # El «antes» casi siempre es el «después» del paso anterior: se reutiliza ya comprimido
        last = getattr(self, "_last_packed", None)
        if last is not None and last[0] == before:
            packed_before = last[1]
        else:
            packed_before = pack_state(before)
        packed_after = pack_state(after)
        self._last_packed = (after, packed_after)
        self.undo_stack.push(_StateCommand(self, packed_before, packed_after, text, merge_id))
        self.project_changed.emit()
        return True if result is None else result

    def _apply_packed(self, data: bytes):
        state = unpack_state(data)
        self._last_packed = (state, data)
        self._apply_state(state)

    def history_size(self) -> tuple[int, int]:
        """(pasos en el historial, bytes que ocupan): para el diagnóstico."""
        seen, total = set(), 0
        for i in range(self.undo_stack.count()):
            cmd = self.undo_stack.command(i)
            for b in (getattr(cmd, "_before", b""), getattr(cmd, "_after", b"")):
                if isinstance(b, bytes) and id(b) not in seen:
                    seen.add(id(b))
                    total += len(b)
        return self.undo_stack.count(), total

    # ---------------------------------------------------------------- reglas
    @staticmethod
    def _check_track(p: Project, track_id: str) -> Track:
        tr = p.track(track_id)
        if tr is None:
            raise EditError("La pista ya no existe.")
        if tr.locked:
            raise EditError(f"🔒 La pista «{tr.name}» está bloqueada.")
        return tr

    def _check_clip(self, p: Project, c: Clip):
        self._check_track(p, c.track_id)
        if c.locked:
            raise EditError("🔒 Ese clip está bloqueado. Desbloquéalo para modificarlo.")

    @staticmethod
    def track_kind_for(m: MediaItem) -> str:
        return TRACK_AUDIO if m.kind == KIND_AUDIO else TRACK_VIDEO

    @staticmethod
    def _is_image(p: Project, c: Clip) -> bool:
        m = p.media_of(c)
        return bool(m and m.kind == KIND_IMAGE)

    def _clear_range(self, p: Project, track_id: str, a: float, b: float, exclude=()):
        """Deja libre el tramo [a, b) de una pista recortando lo que haya (modo sobrescribir)."""
        for c in p.clips_on(track_id):
            if c.id in exclude or c.end <= a + EPS or c.start >= b - EPS:
                continue
            if c.locked:
                raise EditError("🔒 Esa operación taparía un clip bloqueado.")
            shift_src = not self._is_image(p, c)
            if c.start >= a - EPS and c.end <= b + EPS:
                del p.clips[c.id]
            elif c.start < a and c.end > b:  # el hueco cae en medio: se parte en dos
                right = replace(c, id=new_id(), start=b, duration=c.end - b,
                                source_in=c.piece_src(b - c.start, c.duration) if shift_src else 0.0)
                if shift_src:
                    c.source_in = c.piece_src(0.0, a - c.start)
                c.duration = a - c.start
                p.clips[right.id] = right
            elif c.start < a:
                if shift_src:
                    c.source_in = c.piece_src(0.0, a - c.start)
                c.duration = a - c.start
            else:
                cut = b - c.start
                if shift_src:
                    c.source_in = c.piece_src(cut, c.duration)
                c.start = b
                c.duration -= cut

    def _auto_layout(self, p: Project, m: MediaItem | None, track_id: str) -> dict | None:
        """Al AÑADIR un clip: sin efectos automáticos (el usuario: «no espero que porque sea 9:16 tenga una imagen
        arriba y abajo»). Se ve entero con su forma; en una pista de ENCIMA, lo que sobra alrededor es transparente
        (se ve lo de debajo, como en Resolve). El fondo con la propia imagen es un efecto que pones tú: ▦ Relleno."""
        from . import transform
        if m is None or m.kind == KIND_AUDIO or not m.width or not m.height:
            return None
        if abs(m.width / m.height - p.width / p.height) < 0.02:
            return None                       # misma forma que la pantalla: la llena
        vtracks = [t.id for t in p.tracks if t.kind == TRACK_VIDEO and t.role != "fondo"]
        if vtracks and track_id != vtracks[-1]:
            return dict(transform.FULL, bg="none")
        return None

    def _edit_auto_layout(self, p: Project, m: MediaItem | None, track_id: str) -> dict | None:
        """Edits musicales con «automático» (lo eliges en su ventana): horizontales con reflejo (edits) o fondo
        desenfocado (Shorts); capturas de pistas superiores, en el centro."""
        from . import transform
        if p.format not in ("short", "edit") or m is None or m.kind == KIND_AUDIO or not m.width or not m.height:
            return None
        if m.width / m.height <= (p.width / p.height) * 1.15:
            return None  # ya es vertical: llena la pantalla
        vtracks = [t.id for t in p.tracks if t.kind == TRACK_VIDEO]
        if m.kind == KIND_IMAGE and vtracks and track_id != vtracks[-1]:
            return dict(transform.LAYOUTS["Centro (superpuesta)"])
        return dict(transform.MIRROR if p.format == "edit" else transform.BLURFILL)

    def set_project_format(self, fmt: str):
        """Video de YouTube (16:9), YouTube Short o edit musical (9:16): resolución, encuadres y subtítulos."""
        from .model import FORMATS
        from .subtitles import PRESETS

        def fn(p: Project):
            p.format = fmt
            _label, p.width, p.height = FORMATS[fmt]
            p.fps = 60.0              # fluidez: siempre 60 fotogramas por segundo (Edit, Short y YouTube)
            auto = {"blurfill", "mirrorfill"}
            for c in p.clips.values():
                if c.text is not None or c.locked:
                    continue
                if c.layout is None or (c.layout.get("fit") in auto and c.origin == ORIGIN_AI):
                    c.layout = self._auto_layout(p, p.media_of(c), c.track_id)
            st = p.subtitles
            if fmt in ("short", "edit") and st.preset == "YouTube clásico":
                from .subtitles import SHORTS
                for k, v in PRESETS[SHORTS].items():
                    setattr(st, k, v)
                st.preset = SHORTS
            elif fmt == "youtube" and st.preset in ("Mis Shorts", "Shorts · 3 palabras"):
                for k, v in PRESETS["YouTube clásico"].items():
                    setattr(st, k, v)
                st.preset = "YouTube clásico"

        return self._edit("Tipo de proyecto: " + FORMATS[fmt][0].split(" ", 1)[1], fn)

    # ---------------------------------------------- imagen y sonido vinculados
    AV_TRACK = "Audio de video"

    def _av_track(self, p: Project, a: float, b: float) -> str:
        """Pista de audio libre en [a, b) para el sonido de un video (justo debajo de las de video,
        como en Resolve). Si no hay, se crea."""
        for t in p.tracks:
            if t.kind == TRACK_AUDIO and t.name.endswith(self.AV_TRACK) and not t.locked and \
                    not any(c.start < b - EPS and c.end > a + EPS for c in p.clips_on(t.id)):
                return t.id
        n = sum(1 for t in p.tracks if t.kind == TRACK_AUDIO and t.name.endswith(self.AV_TRACK))
        tr = Track(new_id(), TRACK_AUDIO, self.AV_TRACK if n == 0 else f"{n + 1} · {self.AV_TRACK}")
        last_av = max((i for i, t in enumerate(p.tracks) if t.kind == TRACK_AUDIO and t.name.endswith(self.AV_TRACK)),
                      default=None)
        if last_av is None:
            last_av = max((i for i, t in enumerate(p.tracks) if t.kind in (TRACK_VIDEO, TRACK_TEXT)), default=-1)
        p.tracks.insert(last_av + 1, tr)
        return tr.id

    def _link_audio(self, p: Project, vc: Clip, m: MediaItem | None, volume: float = 1.0,
                    dialogue: dict | None = None) -> str | None:
        """Crea el clip de sonido de un clip de video (en una pista de audio) y los vincula.
        dialogue = {video: archivo con solo los diálogos}: entonces suena ese (🗣 sin ruido de fondo)."""
        if m is None or m.kind != KIND_VIDEO or not m.has_audio or not self.split_av:
            return None
        tr = p.track(vc.track_id)
        if tr is None or tr.kind != TRACK_VIDEO:
            return None
        link = vc.link or new_id()
        vc.link = link
        obs = [t for t in (m.audio_tracks or []) if t.get("media_id") in p.media and t["media_id"] not in self.missing]
        if len(obs) >= 2 and not (dialogue or {}).get(m.id):
            # 🎙/🎮 OBS: tu voz y el juego, cada uno en su pista (vinculados con la imagen)
            first = None
            for t in sorted(obs, key=lambda x: x["role"] != "juego"):        # primero el juego, luego tu voz
                tid = self._obs_track_for(p, t["role"], vc.start, vc.end)
                ac = Clip(new_id(), t["media_id"], tid, vc.start, vc.source_in, vc.duration, volume=volume,
                          origin=vc.origin, note=vc.note, link=link, speed=vc.speed, reverse=vc.reverse)
                p.clips[ac.id] = ac
                first = first or ac.id
            return first
        src_id = (dialogue or {}).get(m.id) if (dialogue or {}).get(m.id) in p.media else m.id
        ac = Clip(new_id(), src_id, self._av_track(p, vc.start, vc.end), vc.start, vc.source_in, vc.duration,
                  volume=volume, origin=vc.origin, note=vc.note, link=link, speed=vc.speed, reverse=vc.reverse)
        if src_id != m.id:
            ac.fx = {"orig_media": m.id}
        p.clips[ac.id] = ac
        return ac.id

    @staticmethod
    def partners(p: Project, c: Clip) -> list[Clip]:
        """Los otros clips vinculados a c (su sonido o su imagen)."""
        if not c.link:
            return []
        return [o for o in p.clips.values() if o.link == c.link and o.id != c.id]

    def linked_ids(self, ids) -> list[str]:
        """Los clips indicados más los vinculados a ellos."""
        p = self.project
        out = list(dict.fromkeys(ids))
        for cid in list(out):
            c = p.clips.get(cid)
            if c is not None:
                out += [o.id for o in self.partners(p, c) if o.id not in out]
        return out

    def unlink_clips(self, clip_ids: list[str]):
        """Desvincula imagen y sonido: luego se pueden mover por separado."""
        def fn(p: Project):
            for cid in self.linked_ids(clip_ids):
                if cid in p.clips:
                    p.clips[cid].link = ""

        return self._edit("Desvincular audio y video", fn)

    def link_clips(self, clip_ids: list[str]):
        """Vincula los clips elegidos (p. ej. una imagen y un sonido) para moverlos juntos."""
        def fn(p: Project):
            clips = [p.clips[i] for i in clip_ids if i in p.clips]
            if len(clips) < 2:
                raise EditError("Elige al menos dos clips (por ejemplo, una imagen y un sonido) para vincularlos.")
            link = new_id()
            for c in clips:
                c.link = link

        return self._edit("Vincular clips", fn)

    def separate_audio(self, clip_ids: list[str]):
        """Pasa el sonido de clips de video (que lo llevaban dentro) a una pista de audio, vinculado."""
        def fn(p: Project):
            created = []
            for cid in clip_ids:
                c = p.clips.get(cid)
                if c is None or self.partners(p, c):
                    continue
                self._check_clip(p, c)
                was = self.split_av
                self.split_av = True
                try:
                    ac = self._link_audio(p, c, p.media_of(c), c.volume)
                finally:
                    self.split_av = was
                if ac:
                    created.append(ac)
            if not created:
                raise EditError("Esos clips no tienen sonido (o ya lo tienen separado).")
            return created

        return self._edit("Separar audio", fn)

    def _compatible_track(self, p: Project, m: MediaItem, preferred: str | None) -> str:
        want = self.track_kind_for(m)
        tr = p.track(preferred) if preferred else None
        if tr and tr.kind == want:
            self._check_track(p, tr.id)
            return tr.id
        candidates = [t for t in p.tracks if t.kind == want]
        if want == TRACK_VIDEO:
            candidates.reverse()  # V1 (la de abajo) primero
        for t in candidates:
            if not t.locked:
                return t.id
        raise EditError("No hay ninguna pista libre (sin bloquear) para ese tipo de archivo.")

    # ------------------------------------------------------------ edición
    def _free_track(self, p: Project, kind: str, preferred: str, a: float, b: float) -> str:
        """Una pista de ese tipo libre en [a, b): la preferida si lo está; si no, la libre más cercana;
        si no hay ninguna, se crea una nueva. Así nunca se tapa un clip sin querer."""
        def free(t):
            return not t.locked and not any(c.start < b - EPS and c.end > a + EPS for c in p.clips_on(t.id))
        tr = p.track(preferred)
        if tr is not None and free(tr):
            return tr.id
        same = [t for t in p.tracks if t.kind == kind]
        i0 = p.track_index(preferred)
        for t in sorted(same, key=lambda t: abs(p.track_index(t.id) - i0)):
            if free(t):
                return t.id
        n = len(same) + 1
        if kind == TRACK_VIDEO:
            first = next((i for i, t in enumerate(p.tracks) if t.kind == TRACK_VIDEO), 0)
            nt = Track(new_id(), TRACK_VIDEO, f"V{n}")
            p.tracks.insert(first, nt)
        else:
            last = max((i for i, t in enumerate(p.tracks) if t.kind == kind), default=len(p.tracks) - 1)
            nt = Track(new_id(), kind, f"A{n}" if kind == TRACK_AUDIO else f"T{n}")
            p.tracks.insert(last + 1, nt)
        return nt.id

    def _new_track_for(self, p: Project, kind: str) -> str:
        """Una pista nueva de ese tipo: las de video arriba de todo (encima de las demás imágenes, como en
        Resolve); las de audio, al final."""
        n = sum(1 for t in p.tracks if t.kind == kind) + 1
        if kind == TRACK_VIDEO:
            first = next((i for i, t in enumerate(p.tracks) if t.kind == TRACK_VIDEO), 0)
            nt = Track(new_id(), TRACK_VIDEO, f"V{n}")
            p.tracks.insert(first, nt)
        else:
            nt = Track(new_id(), kind, f"A{n}" if kind == TRACK_AUDIO else f"T{n}")
            p.tracks.append(nt)
        return nt.id

    def add_media(self, media_ids: list[str], track_id: str | None, start: float,
                  origin: str = ORIGIN_USER, overwrite: bool = False, new_track: bool = False):
        """Coloca uno o varios archivos en la timeline, uno detrás de otro.
        Si el sitio está ocupado, va a otra pista libre del mismo tipo (o a una nueva): nunca tapa
        un clip sin querer. overwrite=True: sobrescribe lo que haya (modo antiguo).
        new_track=True (soltar debajo de la última pista): cada tipo de archivo va a una pista NUEVA."""
        def fn(p: Project):
            t = max(0.0, start)
            created = []
            fresh: dict[str, str] = {}         # tipo de pista -> la pista nueva creada en este paso
            for mid in media_ids:
                m = p.media.get(mid)
                if m is None:
                    continue
                if mid in self.missing:
                    raise EditError(f"No se encuentra el archivo «{m.name}».")
                if m.kind == KIND_IMAGE:
                    dur = DEFAULT_IMAGE_DURATION
                elif m.duration > 0:
                    dur = m.duration
                else:
                    raise EditError(f"Todavía se está analizando «{m.name}». Prueba en un momento.")
                if new_track:
                    kind = self.track_kind_for(m)
                    if kind not in fresh:
                        fresh[kind] = self._new_track_for(p, kind)
                    tid = fresh[kind]
                else:
                    tid = self._compatible_track(p, m, track_id)
                if overwrite:
                    self._clear_range(p, tid, t, t + dur)
                else:
                    tid = self._free_track(p, p.track(tid).kind, tid, t, t + dur)
                c = Clip(new_id(), mid, tid, t, 0.0, dur, origin=origin, layout=self._auto_layout(p, m, tid))
                p.clips[c.id] = c
                created.append(c.id)
                ac = self._link_audio(p, c, m)   # el sonido, debajo y vinculado (como en Resolve)
                if ac:
                    created.append(ac)
                t += dur
            return created

        n = len(media_ids)
        created = self._edit("Añadir clip" if n == 1 else f"Añadir {n} clips", fn)
        if created:
            self.clips_placed.emit(list(created))
        return created

    def insert_ranges(self, items: list[dict], track_id: str, text: str, origin: str = ORIGIN_USER,
                      only_gaps: bool = False, volume: float = 1.0):
        """
        Inserta trozos concretos de archivos: items = [{media_id, start, source_in, duration}].
        only_gaps=True: solo rellena huecos vacíos (nunca tapa lo que ya hay en la pista).
        Devuelve los ids de los clips creados.
        """
        def fn(p: Project):
            tr = self._check_track(p, track_id)
            created = []
            for it in sorted(items, key=lambda d: d["start"]):
                m = p.media.get(it["media_id"])
                if m is None or self.track_kind_for(m) != tr.kind:
                    continue
                a, dur, src = it["start"], it["duration"], it.get("source_in", 0.0)
                if only_gaps:
                    others = p.clips_on(track_id)
                    if any(o.start < a + EPS and o.end > a + EPS for o in others):
                        continue  # el inicio ya está ocupado
                    nxt = min((o.start for o in others if o.start >= a + EPS), default=math.inf)
                    dur = min(dur, nxt - a)
                    if dur < MIN_CLIP * 4:
                        continue
                else:
                    self._clear_range(p, track_id, a, a + dur)
                c = Clip(new_id(), m.id, track_id, a, 0.0 if m.kind == KIND_IMAGE else src, dur,
                         volume=volume, origin=origin, note=it.get("note", ""),
                         layout=self._auto_layout(p, m, track_id))
                p.clips[c.id] = c
                created.append(c.id)
                if volume > 0:   # con sonido: se separa a una pista de audio, vinculado
                    ac = self._link_audio(p, c, m, volume)
                    if ac:
                        created.append(ac)
            if not created:
                raise EditError("No había huecos libres donde insertar (la IA no tapa tus clips).")
            return created

        return self._edit(text, fn)

    def move_clips(self, moves: dict[str, tuple[float, str]]):
        """moves = {clip_id: (nuevo_inicio, nueva_pista)}"""
        def fn(p: Project):
            clips = [p.clips[cid] for cid in moves if cid in p.clips]
            for c in clips:
                self._check_clip(p, c)
                dest = self._check_track(p, moves[c.id][1])
                if dest.kind != p.track(c.track_id).kind:
                    raise EditError("Un clip de audio no puede ir a una pista de video (ni al revés).")
            for c in clips:
                del p.clips[c.id]
            for c in clips:
                new_start, new_track = moves[c.id]
                new_start = max(0.0, new_start)
                self._clear_range(p, new_track, new_start, new_start + c.duration)
                c.start, c.track_id = new_start, new_track
                p.clips[c.id] = c

        return self._edit("Mover clip" if len(moves) == 1 else f"Mover {len(moves)} clips", fn)

    def trim_limits(self, clip_id: str, overwrite: bool = False) -> tuple[float, float, float, float]:
        """Límites para recortar un clip: (izq_mín, izq_máx, der_mín, der_máx).
        overwrite=True: al alargarlo se come lo de al lado (solo lo limita el material del archivo)."""
        p = self.project
        c = p.clips[clip_id]
        m = p.media_of(c)
        others = [o for o in p.clips_on(c.track_id) if o.id != c.id]
        prev_end = max((o.end for o in others if o.end <= c.start + EPS), default=0.0)
        next_start = min((o.start for o in others if o.start >= c.end - EPS), default=math.inf)
        if overwrite:
            prev_end, next_start = 0.0, math.inf
        if m is None or m.kind == KIND_IMAGE or m.duration <= 0 or c.speed <= 0:
            left_min, right_max = prev_end, next_start      # imagen o fotograma congelado: sin límite
        else:
            before = c.source_in / c.speed                              # material antes del trozo usado
            after = max(0.0, m.duration - c.source_in - c.src_len) / c.speed   # y después
            if c.reverse:
                before, after = after, before
            left_min = max(prev_end, c.start - before)
            right_max = min(next_start, c.end + after)
        return left_min, c.end - MIN_CLIP, c.start + MIN_CLIP, right_max

    def trim_clip(self, clip_id: str, edge: str, t: float, linked: bool = True, overwrite: bool = False):
        """Recorta un borde. linked=True: también el mismo borde de su imagen/sonido vinculado.
        overwrite=True: si lo alargas, se come los clips de al lado (como «sobrescribir» de Resolve)."""
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            group = [c]
            if linked:
                for o in self.partners(p, c):
                    same = abs(o.start - c.start) < EPS if edge == "left" else abs(o.end - c.end) < EPS
                    if same and not o.locked and not p.track(o.track_id).locked:
                        group.append(o)
            for x in group:
                self._check_clip(p, x)
            lims = [self.trim_limits(x.id, overwrite) for x in group]
            if edge == "left":
                new = min(max(t, max(l[0] for l in lims)), min(l[1] for l in lims))
            else:
                new = min(max(t, max(l[2] for l in lims)), min(l[3] for l in lims))
            if overwrite:          # lo que queda debajo del trozo alargado se recorta (o desaparece)
                ids = {x.id for x in group}
                for x in group:
                    if edge == "left" and new < x.start - EPS:
                        self._clear_range(p, x.track_id, new, x.start, exclude=ids)
                    elif edge == "right" and new > x.end + EPS:
                        self._clear_range(p, x.track_id, x.end, new, exclude=ids)
            for x in group:
                if edge == "left":
                    delta = new - x.start
                    if not self._is_image(p, x):
                        x.source_in = max(0.0, x.piece_src(delta, x.duration))
                    x.start = new
                    x.duration -= delta
                else:
                    if not self._is_image(p, x):
                        x.source_in = max(0.0, x.piece_src(0.0, new - x.start))
                    x.duration = new - x.start

        return self._edit("Recortar clip", fn)

    # ------------------------------------------------- recortes avanzados (modo Recorte de Resolve)
    def _handles(self, p: Project, c: Clip) -> tuple[float, float]:
        """Material libre del archivo antes y después del clip (en segundos de la timeline)."""
        from .transitions import handles
        return handles(p, c)

    def _aligned_partners(self, p: Project, c: Clip, edge: str) -> list[Clip]:
        out = []
        for o in self.partners(p, c):
            same = abs(o.start - c.start) < EPS if edge == "left" else abs(o.end - c.end) < EPS
            if same and not o.locked and not p.track(o.track_id).locked:
                out.append(o)
        return out

    def ripple_limits(self, clip_id: str, edge: str) -> tuple[float, float]:
        """Rango para el borde en un recorte «ripple»: (mínimo, máximo) en tiempo de la timeline.
        Borde izquierdo: el valor es dónde empezaría el contenido (el clip no se mueve)."""
        p = self.project
        c = p.clips[clip_id]
        group = [c] + self._aligned_partners(p, c, edge)
        hb = min(self._handles(p, x)[0] for x in group)
        ha = min(self._handles(p, x)[1] for x in group)
        if edge == "left":
            return c.start - hb, c.end - MIN_CLIP
        return c.start + MIN_CLIP, c.end + ha

    def ripple_trim(self, clip_id: str, edge: str, t: float, linked: bool = True):
        """Recorte «ripple» (como en Resolve): el clip cambia de largo y TODO lo que viene detrás en su pista
        (y en la de su sonido vinculado) se mueve con él: ni huecos ni clips tapados.
        Borde izquierdo: se quita/añade material al principio y el clip se queda donde estaba."""
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            group = [c] + (self._aligned_partners(p, c, edge) if linked else [])
            for x in group:
                self._check_clip(p, x)
            lo, hi = self.ripple_limits(clip_id, edge)
            nt = min(max(t, lo), hi)
            delta = (nt - c.start) if edge == "left" else (nt - c.end)   # izq: + = quitar; der: + = alargar
            if abs(delta) < EPS:
                return
            shift = -delta if edge == "left" else delta
            moved = {x.id for x in group}
            for x in group:
                old_end = x.end
                img = self._is_image(p, x)
                if edge == "left":
                    if not img:
                        if delta >= 0:
                            x.source_in = x.piece_src(delta, x.duration)
                        else:   # se añade material antes: el trozo empieza antes en el archivo
                            x.source_in = max(0.0, x.source_in + (0.0 if x.reverse else delta * x.speed))
                    x.duration -= delta
                    if x.reverse and delta < 0 and not img:
                        pass    # al revés, el material añadido al inicio es el FINAL del archivo (source_in igual)
                else:
                    if not img and x.reverse:
                        if delta <= 0:
                            x.source_in = x.piece_src(0.0, x.duration + delta)
                        else:
                            x.source_in = max(0.0, x.source_in - delta * x.speed)
                    x.duration += delta
                for o in p.clips_on(x.track_id):
                    if o.id in moved or o.start < old_end - EPS:
                        continue
                    if o.locked:
                        raise EditError("🔒 Hay un clip bloqueado detrás: no se puede mover.")
                    o.start = max(0.0, o.start + shift)

        return self._edit("Recorte ripple", fn)

    def roll_limits(self, right_id: str) -> tuple[float, float]:
        p = self.project
        right = p.clips[right_id]
        left = next((o for o in p.clips_on(right.track_id) if abs(o.end - right.start) < 1e-3 and o.id != right.id),
                    None)
        if left is None:
            return right.start, right.start
        lo = max(left.start + MIN_CLIP, right.start - self._handles(p, right)[0])
        hi = min(right.end - MIN_CLIP, left.end + self._handles(p, left)[1])
        return lo, hi

    def roll_edit(self, right_id: str, t: float):
        """«Roll»: mueve el corte entre dos clips pegados; uno se alarga y el otro se acorta, nada más se mueve."""
        def fn(p: Project):
            right = p.clips.get(right_id)
            left = next((o for o in p.clips_on(right.track_id) if abs(o.end - right.start) < 1e-3
                         and o.id != right.id), None) if right else None
            if right is None or left is None:
                raise EditError("Ahí no hay un corte entre dos clips pegados.")
            self._check_clip(p, left)
            self._check_clip(p, right)
            lo, hi = self.roll_limits(right_id)
            nt = min(max(t, lo), hi)
            delta = nt - right.start
            if abs(delta) < EPS:
                return
            pairs = [(left, right)]
            for lp in self._aligned_partners(p, left, "right"):     # su sonido: el mismo corte
                rp = next((o for o in p.clips_on(lp.track_id) if abs(o.start - lp.end) < 1e-3 and o.id != lp.id), None)
                if rp is not None and not rp.locked:
                    pairs.append((lp, rp))
            for L, R in pairs:
                img_l, img_r = self._is_image(p, L), self._is_image(p, R)
                if not img_l and L.reverse:
                    L.source_in = (L.piece_src(0.0, L.duration + delta) if delta < 0
                                   else max(0.0, L.source_in - delta * L.speed))
                L.duration += delta
                if not img_r:
                    if delta >= 0:
                        R.source_in = R.piece_src(delta, R.duration)
                    elif not R.reverse:
                        R.source_in = max(0.0, R.source_in + delta * R.speed)
                R.start += delta
                R.duration -= delta

        return self._edit("Mover el corte (roll)", fn)

    def slip_clip(self, clip_id: str, dt: float):
        """«Slip»: el clip no se mueve ni cambia de largo; cambia QUÉ parte del archivo enseña.
        dt en segundos de la timeline (+ = ver material de más adelante)."""
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            group = [c] + [o for o in self.partners(p, c) if abs(o.start - c.start) < EPS and abs(o.end - c.end) < EPS]
            for x in group:
                self._check_clip(p, x)
                if self._is_image(p, x) or x.speed <= 0:
                    raise EditError("Una imagen o un fotograma congelado no tiene más material que enseñar.")
            hb = min(self._handles(p, x)[0] for x in group)
            ha = min(self._handles(p, x)[1] for x in group)
            d = min(max(dt, -hb), ha)
            if abs(d) < EPS:
                return
            for x in group:
                x.source_in = max(0.0, x.source_in + (-d if x.reverse else d) * x.speed)

        return self._edit("Cambiar la parte visible (slip)", fn)

    def slide_limits(self, clip_id: str) -> tuple[float, float]:
        p = self.project
        c = p.clips[clip_id]
        others = [o for o in p.clips_on(c.track_id) if o.id != c.id]
        prev = next((o for o in others if abs(o.end - c.start) < 1e-3), None)
        nxt = next((o for o in others if abs(o.start - c.end) < 1e-3), None)
        if prev is not None:
            lo = -(prev.duration - MIN_CLIP)
            hi_prev = self._handles(p, prev)[1]
        else:
            lo = -(c.start - max((o.end for o in others if o.end <= c.start + EPS), default=0.0))
            hi_prev = math.inf
        if nxt is not None:
            hi = nxt.duration - MIN_CLIP
            lo_next = -self._handles(p, nxt)[0]
        else:
            hi = min((o.start for o in others if o.start >= c.end - EPS), default=math.inf) - c.end
            lo_next = -math.inf
        return max(lo, lo_next), min(hi, hi_prev)

    def slide_clip(self, clip_id: str, dt: float):
        """«Slide»: el clip se desliza entre sus vecinos sin cambiar lo que enseña; el de delante se
        alarga/acorta y el de detrás también, así no quedan huecos ni se mueve nada más.
        Su sonido vinculado hace lo mismo en su pista."""
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            group = [c] + [o for o in self.partners(p, c) if abs(o.start - c.start) < EPS and abs(o.end - c.end) < EPS
                           and not o.locked]
            lims = [self.slide_limits(x.id) for x in group]
            d = min(max(dt, max(l[0] for l in lims)), min(l[1] for l in lims))
            if abs(d) < EPS:
                return
            for x in group:
                self._slide_one(p, x, d)

        return self._edit("Deslizar entre vecinos (slide)", fn)

    def _slide_one(self, p: Project, c: Clip, d: float):
        self._check_clip(p, c)
        others = [o for o in p.clips_on(c.track_id) if o.id != c.id]
        prev = next((o for o in others if abs(o.end - c.start) < 1e-3), None)
        nxt = next((o for o in others if abs(o.start - c.end) < 1e-3), None)
        for o in (prev, nxt):
            if o is not None:
                self._check_clip(p, o)
        if prev is not None:
            if not self._is_image(p, prev) and prev.reverse:
                prev.source_in = (prev.piece_src(0.0, prev.duration + d) if d < 0
                                  else max(0.0, prev.source_in - d * prev.speed))
            prev.duration += d
        if nxt is not None:
            if not self._is_image(p, nxt):
                if d >= 0:
                    nxt.source_in = nxt.piece_src(d, nxt.duration)
                elif not nxt.reverse:
                    nxt.source_in = max(0.0, nxt.source_in + d * nxt.speed)
            nxt.start += d
            nxt.duration -= d
        c.start += d

    def split(self, t: float, clip_ids: list[str] | None = None):
        """Corta en el tiempo t. Sin selección, corta todo lo que no esté bloqueado."""
        def fn(p: Project):
            if clip_ids:
                targets = [p.clips[cid] for cid in clip_ids if cid in p.clips]
            else:
                targets = [c for c in p.clips.values()
                           if not c.locked and not p.track(c.track_id).locked]
            targets = [c for c in targets if c.start + MIN_CLIP < t < c.end - MIN_CLIP]
            if not targets:
                raise EditError("No hay ningún clip bajo el cabezal para cortar.")
            created = []
            target_ids = {c.id for c in targets}
            relink: dict[str, str] = {}
            for c in targets:
                self._check_clip(p, c)
                both = any(o.id in target_ids for o in self.partners(p, c))
                fx = dict(c.fx or {})   # transición y efectos «de entrada» se quedan en la izquierda
                rfx = {k: v for k, v in fx.items() if k not in self.START_FX}
                lfx = {k: v for k, v in fx.items() if k != "fade_out"}
                right = replace(c, id=new_id(), start=t, duration=c.end - t, fx=rfx or None,
                                source_in=0.0 if self._is_image(p, c) else c.piece_src(t - c.start, c.duration),
                                link=relink.setdefault(c.link, new_id()) if (c.link and both) else "")
                if not self._is_image(p, c):
                    c.source_in = c.piece_src(0.0, t - c.start)
                c.duration = t - c.start
                c.fx = lfx or None
                p.clips[right.id] = right
                created.append(right.id)
            return created

        return self._edit("Dividir clip", fn)

    # ------------------------------------------------- transiciones (Disolver, fundido, barrido…)
    def cut_near(self, t: float, tol: float = 1.0) -> str | None:
        """El corte entre dos clips pegados más cercano a t (devuelve el clip de la derecha)."""
        from . import transitions
        p = self.project
        best = None
        for tr in p.tracks:
            if tr.kind != TRACK_VIDEO:
                continue
            for c in p.clips_on(tr.id):
                if transitions.is_visual(p, c) and transitions.previous(p, c) is not None:
                    d = abs(c.start - t)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, c.id)
        return best[1] if best else None

    def transition_targets(self, ids, t: float) -> list[str]:
        """Dónde poner la transición: al inicio de cada clip seleccionado que tiene otro pegado delante
        (o al final, si es el de la izquierda); sin selección, en el corte más cercano al cabezal."""
        from . import transitions
        p = self.project
        out = []
        for cid in ids:
            c = p.clips.get(cid)
            if c is None or not transitions.is_visual(p, c):
                continue
            if transitions.previous(p, c) is not None:
                out.append(c.id)
            else:
                nxt = next((o for o in p.clips_on(c.track_id) if abs(o.start - c.end) < 1e-3), None)
                if nxt is not None and transitions.is_visual(p, nxt):
                    out.append(nxt.id)
        if not out:
            near = self.cut_near(t)
            if near:
                out.append(near)
        return list(dict.fromkeys(out))

    def rescale_ai_transitions(self, scale: float) -> int:
        """Las transiciones que puso la IA, con la nueva escala (más cortas / más largas). Un paso de deshacer."""
        from . import transitions

        def fn(p: Project):
            n = 0
            for c in p.clips.values():
                t = (c.fx or {}).get("trans")
                if not isinstance(t, dict) or not t.get("ai") or c.locked:
                    continue
                prev = transitions.previous(p, c)
                if prev is None:
                    continue
                base = float(t.get("base", t.get("dur", 0.5)))
                c.fx = dict(c.fx, trans=dict(t, dur=round(transitions.clamp_dur(base * scale, prev, c), 3), base=base))
                n += 1
            return n
        res = self._edit("Duración de las transiciones de la IA", fn)
        return res if isinstance(res, int) else 0

    def set_transition(self, right_ids: list[str], ttype: str | None, dur: float = 0.5):
        """Pone (o quita, con ttype=None) una transición en el corte que hay al inicio de cada clip."""
        from . import transitions

        def fn(p: Project):
            n = 0
            for rid in right_ids:
                c = p.clips.get(rid)
                prev = transitions.previous(p, c) if c else None
                if c is None or prev is None:
                    continue
                self._check_clip(p, c)
                self._check_clip(p, prev)
                fx = dict(c.fx or {})
                if ttype:
                    fx["trans"] = {"type": ttype, "dur": round(transitions.clamp_dur(dur, prev, c), 3)}
                else:
                    fx.pop("trans", None)
                c.fx = fx or None
                n += 1
            if not n:
                raise EditError("No hay un corte entre dos clips pegados ahí. Pon el cabezal cerca de un corte "
                                "o selecciona el clip que empieza en el corte.")
            return n

        if ttype:
            from .transitions import NAMES
            label = f"Transición: {NAMES.get(ttype, ttype)}"
        else:
            label = "Quitar transición"
        return self._edit(label, fn)

    # ------------------------------------------------- entrada / salida (I / O)
    def set_mark(self, which: str, t: float | None):
        """Marca de entrada («in») o salida («out») en t; None la quita. No es un cambio de edición:
        no entra en deshacer (como en Resolve), pero se guarda con el proyecto."""
        p = self.project
        if which == "in":
            p.mark_in = None if t is None else max(0.0, t)
            if p.mark_in is not None and p.mark_out is not None and p.mark_out <= p.mark_in:
                p.mark_out = None
        else:
            p.mark_out = None if t is None else max(0.0, t)
            if p.mark_in is not None and p.mark_out is not None and p.mark_in >= p.mark_out:
                p.mark_in = None
        self._set_media_dirty()
        self.project_changed.emit()

    def clear_marks(self):
        self.project.mark_in = self.project.mark_out = None
        self._set_media_dirty()
        self.project_changed.emit()

    def delete_marked(self):
        """Quita el tramo entre la entrada y la salida de TODAS las pistas y cierra el hueco."""
        rng = self.project.marked_range()
        if rng is None:
            raise EditError("Marca primero la entrada (I) y la salida (O) del tramo que quieres quitar.")
        a, b = rng

        def fn(p: Project):
            self._ripple_delete(p, a, b)
            p.mark_in, p.mark_out = a, None

        return self._edit("Quitar el tramo marcado", fn)

    # ------------------------------------------------- velocidad (como «Cambiar velocidad» de Resolve)
    def set_speed(self, clip_ids: list[str], speed: float | None = None, reverse: bool | None = None,
                  ripple: bool = True):
        """Cambia la velocidad (0.1–4 = 10 %–400 %) y/o el sentido de los clips (y de su sonido vinculado).
        El trozo del archivo no cambia: el clip se alarga o se acorta. ripple=True: lo que viene detrás
        en esas pistas se mueve para no taparlo ni dejar hueco."""
        def fn(p: Project):
            ids = self.linked_ids(clip_ids)
            clips = [p.clips[i] for i in ids if i in p.clips]
            clips = [c for c in clips if c.text is None and not self._is_image(p, c)]
            if not clips:
                raise EditError("Selecciona uno o varios clips de video o audio.")
            self._retime(p, clips, {c.id: (speed, reverse) for c in clips}, ripple)

        label = "Velocidad del clip" if speed is not None else ("Reproducir al revés" if reverse else "Sentido normal")
        return self._edit(label, fn)

    def _retime(self, p: Project, clips: list[Clip], what: dict[str, tuple], ripple: bool):
        """Aplica {id: (velocidad|None, al_revés|None)} pista por pista y en orden, acumulando cuánto se
        alarga o acorta cada clip para mover lo de detrás (así varios clips seguidos siguen pegados)."""
        for c in clips:
            self._check_clip(p, c)
        targets = {c.id for c in clips}
        for tid in {c.track_id for c in clips}:
            acc = 0.0
            for o in p.clips_on(tid):
                if o.id in targets:
                    if ripple:
                        o.start = max(0.0, o.start + acc)
                    old_end = o.end
                    sp, rev = what[o.id]
                    if sp is not None:
                        sp = min(4.0, max(0.1, float(sp)))
                        src = o.src_len if o.speed > 0 else o.duration
                        o.speed = sp
                        o.duration = max(MIN_CLIP, src / sp)
                    if rev is not None:
                        o.reverse = bool(rev)
                    d = o.end - old_end
                    if not ripple and d > EPS:
                        nxt = next((x for x in p.clips_on(tid) if x.id != o.id and x.start >= old_end - EPS), None)
                        if nxt is not None and nxt.start < o.end - EPS:
                            raise EditError("Más lento taparía el clip de detrás: deja espacio o activa "
                                            "«mover lo de detrás».")
                    if ripple:
                        acc += d
                elif ripple and abs(acc) > EPS:
                    if o.locked:
                        raise EditError("🔒 Hay un clip bloqueado detrás: no se puede mover.")
                    o.start = max(0.0, o.start + acc)

    # ------------------------------------------------- copiar / pegar (y pegar atributos, como en Resolve)
    def copy_clips(self, ids, cut: bool = False) -> int:
        """Copia EXACTAMENTE los clips seleccionados. cut=True: además los borra (Ctrl+X). (Antes se añadía siempre
        su imagen/sonido vinculado: el usuario seleccionaba un clip y Ctrl+X se llevaba también su audio. Lo que va
        junto ya lo decide la selección: con la selección vinculada 🔗 activa, al elegir uno se eligen los dos; con
        Alt+clic, solo ese.)"""
        p = self.project
        clips = [p.clips[i] for i in dict.fromkeys(ids) if i in p.clips]
        if not clips:
            raise EditError("Selecciona los clips que quieres copiar.")
        base = min(c.start for c in clips)
        from dataclasses import asdict
        self.clipboard = [(asdict(c), c.start - base) for c in clips]
        if cut:
            self.delete_clips([c.id for c in clips])
        return len(clips)

    # ------------------------------------------------- clic derecho como en Resolve
    def _push_after(self, p: Project, t: float, dur: float):
        """Abre un espacio de dur segundos en t en todas las pistas sin candado: parte lo que cruza t y mueve
        todo lo de detrás (y los marcadores)."""
        open_tracks = {tr.id for tr in p.tracks if not tr.locked}
        for c in list(p.clips.values()):
            if c.track_id in open_tracks and c.start < t - EPS and c.end > t + EPS:
                self._split_at(p, c, t)
        for c in p.clips.values():
            if c.track_id in open_tracks and c.start >= t - EPS:
                if c.locked:
                    raise EditError("🔒 Hay un clip bloqueado detrás: no se puede abrir el espacio.")
                c.start += dur
        for mk in p.markers:
            if mk.time >= t - EPS:
                mk.time += dur

    def insert_gap(self, clip_ids) -> None:
        """«Insertar espacio»: un hueco del largo de la selección justo donde empieza, en todas las pistas."""
        cl = [self.project.clips[i] for i in clip_ids if i in self.project.clips]
        if not cl:
            raise EditError("Selecciona los clips.")
        a, b = min(c.start for c in cl), max(c.end for c in cl)
        return self._edit("Insertar espacio", lambda p: self._push_after(p, a, b - a))

    def paste_insert(self, t: float) -> list[str]:
        """«Pegar e insertar» (Ctrl+Mayús+V): abre sitio en el cabezal y pega ahí (lo de detrás se mueve)."""
        items = list(getattr(self, "clipboard", []) or [])
        if not items:
            raise EditError("No hay nada copiado (Ctrl+C).")
        span = max(off + d["duration"] for d, off in items)

        def fn(p: Project):
            self._push_after(p, t, span)
            return self._paste_into(p, t, items)

        return self._edit("Pegar e insertar", fn)

    def remove_attributes(self, ids, attrs: list[str]) -> int:
        """«Eliminar atributos…»: los ajustes elegidos vuelven a como estaban de fábrica."""
        def fn(p: Project):
            targets = [p.clips[i] for i in self.linked_ids(ids) if i in p.clips and p.clips[i].text is None]
            for c in targets:
                self._check_clip(p, c)
            for c in targets:
                fx = dict(c.fx or {})
                if "efectos" in attrs:
                    fx = {k: v for k, v in fx.items() if k == "trans"}
                if "transicion" in attrs:
                    fx.pop("trans", None)
                c.fx = fx or None
                if "encuadre" in attrs:
                    c.zoom_kf, c.layout, c.layout_kf = [], None, []
                if "color" in attrs:
                    c.color = None
                if "opacidad" in attrs:
                    c.opacity, c.blend, c.op_kf = 1.0, "normal", []
                if "audio" in attrs:
                    c.volume, c.pan, c.eq, c.vol_kf = 1.0, 0.0, None, []
            if "velocidad" in attrs:
                movable = [c for c in targets if not self._is_image(p, c) and c.retimed]
                self._retime(p, movable, {c.id: (1.0, False) for c in movable}, True)
            return len(targets)

        return self._edit("Eliminar atributos", fn)

    def change_duration(self, clip_ids, dur: float) -> None:
        """«Cambiar duración…» (Ctrl+D): el clip dura eso; lo de detrás en su pista se mueve (como Resolve)."""
        def fn(p: Project):
            for cid in clip_ids:
                c = p.clips.get(cid)
                if c is None:
                    continue
                group = [c] + [o for o in self.partners(p, c)
                               if abs(o.start - c.start) < EPS and abs(o.end - c.end) < EPS]
                for x in group:
                    self._check_clip(p, x)
                m = p.media_of(c)
                new = max(MIN_CLIP, float(dur))
                if m is not None and m.kind != KIND_IMAGE and m.duration > 0 and c.speed > 0:
                    new = min(new, (m.duration - c.source_in) / c.speed if not c.reverse else new)
                for x in group:
                    old_end, delta = x.end, new - x.duration
                    for o in p.clips_on(x.track_id):
                        if o.id != x.id and o.start >= old_end - EPS:
                            if o.locked:
                                raise EditError("🔒 Hay un clip bloqueado detrás.")
                            o.start += delta
                    x.duration = new

        return self._edit("Cambiar duración", fn)

    def normalize_volume(self, clip_ids, mode: str = "lufs", target: float = -14.0) -> int:
        """«Normalizar volumen…»: mide cada clip (su trozo del archivo) y le pone el volumen para llegar al
        objetivo: pico (dBFS) o volumen percibido (LUFS, sin saturar)."""
        from . import loudness
        gains = {}
        for cid in clip_ids:
            c = self.project.clips.get(cid)
            m = self.project.media_of(c) if c else None
            if c is None or m is None or not (m.kind == KIND_AUDIO or m.has_audio) or c.speed <= 0:
                continue
            a = min(c.source_in, c.source_in + c.src_len)
            r = loudness.measure(m.path, a, a + abs(c.src_len))
            if r is not None:
                gains[cid] = loudness.gain_for(r, mode, target)
        if not gains:
            raise EditError("Esos clips no tienen sonido que medir.")

        def fn(p: Project):
            for cid, g in gains.items():
                c = p.clips[cid]
                self._check_clip(p, c)
                c.volume = round(min(4.0, max(0.0, 10 ** (g / 20))), 4)
            return len(gains)

        return self._edit("Normalizar volumen", fn)

    def delete_part(self, clip_ids, kind: str):
        """Borra solo el SONIDO (kind="audio") o solo la IMAGEN ("video") de los clips y sus vinculados."""
        p = self.project
        want = TRACK_AUDIO if kind == "audio" else TRACK_VIDEO
        ids = [i for i in self.linked_ids(clip_ids) if i in p.clips and p.track(p.clips[i].track_id)
               and p.track(p.clips[i].track_id).kind == want]
        if not ids:
            raise EditError("Esos clips no tienen " + ("sonido" if kind == "audio" else "imagen") + " aparte.")
        return self.delete_clips(ids)

    def paste_clips(self, t: float) -> list[str]:
        """Pega lo copiado en el cabezal, en sus pistas si están libres; si no, en otra libre (o nueva):
        nunca tapa nada."""
        items = list(getattr(self, "clipboard", []) or [])
        if not items:
            raise EditError("No hay nada copiado (Ctrl+C).")
        return self._edit("Pegar", lambda p: self._paste_into(p, t, items))

    def _paste_into(self, p: Project, t: float, items) -> list[str]:
        """Pega los clips copiados en t (en su pista si está libre; si no, en otra): nunca tapa nada."""
        created = []
        relink: dict[str, str] = {}
        by_track: dict[str, list] = {}
        for d, off in items:
            if d["media_id"] not in p.media and not d.get("text"):
                continue
            by_track.setdefault(d["track_id"], []).append((d, off))
        for tid, group in by_track.items():
            a = t + min(off for _d, off in group)
            b = t + max(off + d["duration"] for d, off in group)
            tr = p.track(tid)
            kind = tr.kind if tr else (TRACK_AUDIO if p.media[group[0][0]["media_id"]].kind == KIND_AUDIO
                                        else TRACK_VIDEO)
            dest = self._free_track(p, kind, tid if tr else "", a, b)
            for d, off in group:
                c = Clip(**{k: v for k, v in d.items() if k in Clip.__dataclass_fields__})
                c.id, c.track_id, c.start = new_id(), dest, t + off
                c.locked, c.origin = False, ORIGIN_USER
                c.zoom_kf = [dict(k) for k in c.zoom_kf]
                c.layout_kf = [dict(k) for k in c.layout_kf]
                if c.link:
                    c.link = relink.setdefault(c.link, new_id())
                p.clips[c.id] = c
                created.append(c.id)
        if not created:
            raise EditError("Los clips copiados ya no están en la biblioteca.")
        return created

    ATTRIBUTES = {"efectos": "Efectos de imagen y fundidos", "encuadre": "Encuadre, zoom y posición en pantalla",
                  "audio": "Volumen, balance y ecualizador", "velocidad": "Velocidad y sentido",
                  "transicion": "Transición de entrada", "color": "Color (exposición, contraste, LUT…)",
                  "opacidad": "Opacidad y modo de fusión"}

    def paste_attributes(self, ids, attrs: list[str], ripple: bool = True) -> int:
        """Pega en los clips elegidos los ajustes del primer clip copiado (Alt+V en Resolve)."""
        items = list(getattr(self, "clipboard", []) or [])
        if not items:
            raise EditError("Copia primero (Ctrl+C) el clip cuyos ajustes quieres repetir.")
        src = items[0][0]

        def fn(p: Project):
            targets = [p.clips[i] for i in self.linked_ids(ids) if i in p.clips]
            targets = [c for c in targets if c.text is None and c.id != src["id"]]
            if not targets:
                raise EditError("Selecciona los clips que recibirán los ajustes.")
            for c in targets:
                self._check_clip(p, c)
            vis = lambda c: p.track(c.track_id).kind == TRACK_VIDEO   # noqa: E731
            sfx = dict(src.get("fx") or {})
            for c in targets:
                if "efectos" in attrs:
                    fx = {k: v for k, v in sfx.items() if k != "trans"}
                    if (c.fx or {}).get("trans"):
                        fx["trans"] = c.fx["trans"]
                    c.fx = fx or None
                if "transicion" in attrs and vis(c):
                    fx = dict(c.fx or {})
                    if sfx.get("trans"):
                        fx["trans"] = dict(sfx["trans"])
                    else:
                        fx.pop("trans", None)
                    c.fx = fx or None
                if "encuadre" in attrs and vis(c) and not self._is_image(p, c):
                    kf = []
                    for k in src.get("zoom_kf") or []:   # las claves van en tiempo del archivo: se trasladan
                        k = dict(k)
                        if len(src.get("zoom_kf") or []) > 1:
                            k["t"] = k["t"] - src["source_in"] + c.source_in
                        kf.append(k)
                    c.zoom_kf = kf
                    lkf = []                              # 🎞 posición/tamaño animados: igual, trasladados
                    for k in src.get("layout_kf") or []:
                        k = dict(k)
                        k["t"] = k["t"] - src["source_in"] + c.source_in
                        lkf.append(k)
                    c.layout_kf = lkf
                    c.layout = dict(src["layout"]) if src.get("layout") else None
                elif "encuadre" in attrs and vis(c):
                    c.layout = dict(src["layout"]) if src.get("layout") else None
                if "color" in attrs and vis(c):
                    c.color = dict(src["color"]) if src.get("color") else None
                if "opacidad" in attrs and vis(c):
                    c.opacity, c.blend = src.get("opacity", 1.0), src.get("blend", "normal")
                if "audio" in attrs:
                    c.volume = src.get("volume", 1.0)
                    c.pan = src.get("pan", 0.0)
                    c.eq = dict(src["eq"]) if src.get("eq") else None
            if "velocidad" in attrs:
                movable = [c for c in targets if not self._is_image(p, c)]
                self._retime(p, movable, {c.id: (src.get("speed", 1.0) or 1.0, bool(src.get("reverse")))
                                          for c in movable}, ripple)
            return len(targets)

        return self._edit("Pegar atributos", fn)

    RAMPS = {   # nombre → velocidades relativas de cada tramo (el material usado es el mismo)
        "rapido_lento_rapido": ("Rápido → lento → rápido", [2.2, 1.6, 0.9, 0.4, 0.3, 0.4, 0.9, 1.6, 2.2]),
        "entrar_lento": ("Entrar en cámara lenta", [1.0, 0.85, 0.65, 0.45, 0.32, 0.25, 0.25, 0.25]),
        "salir_lento": ("Salir de cámara lenta", [0.25, 0.25, 0.25, 0.32, 0.45, 0.65, 0.85, 1.0]),
        "acelerar": ("Acelerar", [1.0, 1.2, 1.5, 1.9, 2.4, 3.0, 3.6]),
        "frenar": ("Frenar", [3.6, 3.0, 2.4, 1.9, 1.5, 1.2, 1.0]),
    }

    def speed_ramp(self, clip_id: str, preset: str, ripple: bool = True, smooth: bool | None = None):
        """Rampa de velocidad: el clip (y su sonido vinculado) se divide en tramos seguidos con velocidades
        que cambian poco a poco. Usa el mismo trozo del archivo; lo de detrás se mueve si cambia la duración."""
        name, factors = self.RAMPS[preset]

        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None or c.text is not None or self._is_image(p, c) or c.speed <= 0:
                raise EditError("La rampa necesita un clip de video o audio (no una imagen ni un fotograma congelado).")
            group = [c] + [o for o in self.partners(p, c) if abs(o.start - c.start) < EPS and abs(o.end - c.end) < EPS]
            for x in group:
                self._check_clip(p, x)
            n = len(factors)
            new_dur = sum((c.src_len / n) / max(0.05, c.speed * f) for f in factors)
            delta = new_dur - c.duration
            if ripple and abs(delta) > EPS:
                for tid in {x.track_id for x in group}:
                    for o in p.clips_on(tid):
                        if o.id in {x.id for x in group} or o.start < c.end - EPS:
                            continue
                        if o.locked:
                            raise EditError("🔒 Hay un clip bloqueado detrás: no se puede mover.")
                        o.start += delta
            elif not ripple and delta > EPS:
                for x in group:
                    nxt = next((o for o in p.clips_on(x.track_id) if o.id != x.id and o.start >= x.end - EPS), None)
                    if nxt is not None and nxt.start < x.start + new_dur - EPS:
                        raise EditError("La rampa alarga el clip y taparía el de detrás: activa «mover lo de detrás».")
            links = {}
            created = []
            for x in group:
                base_speed, step_src = x.speed, x.src_len / n
                fx = dict(x.fx or {})
                t = x.start
                order = list(range(n))
                for k, f in enumerate(factors):
                    sp = max(0.05, min(8.0, base_speed * f))
                    j = order[k]
                    src = x.source_in + ((n - 1 - j) if x.reverse else j) * step_src
                    piece = replace(x, id=new_id() if k else x.id, start=t, duration=step_src / sp,
                                    source_in=src, speed=sp,
                                    smooth=(sp < 0.999) if smooth is None else (smooth and sp < 0.999),
                                    link=(links.setdefault((x.link, k), new_id()) if x.link else ""))
                    pfx = {kk: v for kk, v in fx.items() if kk not in ("fade_in", "fade_out", "trans", "flash", "shake")}
                    if k == 0:
                        pfx.update({kk: fx[kk] for kk in ("fade_in", "trans", "flash", "shake") if kk in fx})
                    if k == n - 1 and "fade_out" in fx:
                        pfx["fade_out"] = fx["fade_out"]
                    piece.fx = pfx or None
                    p.clips[piece.id] = piece
                    created.append(piece.id)
                    t += piece.duration
            return created

        return self._edit(f"Rampa de velocidad: {name}", fn)

    def split_at_times(self, clip_id: str, times: list[float], label: str = "Cortes de escena") -> int:
        """Corta un clip (y su sonido vinculado) en varios momentos de la timeline, en un solo paso de deshacer."""
        p = self.project
        c = p.clips.get(clip_id)
        if c is None:
            return 0
        ids = [c.id] + [o.id for o in self.partners(p, c)]
        ts = sorted({t for t in times if c.start + MIN_CLIP < t < c.end - MIN_CLIP}, reverse=True)
        if not ts:
            raise EditError("No hay cortes dentro del clip.")
        self.undo_stack.beginMacro(label)
        try:
            for t in ts:                # del final al principio: el trozo de la izquierda conserva su id
                self.split(t, ids)
        finally:
            self.undo_stack.endMacro()
        return len(ts)

    # ------------------------------------------------- 🎬 escenas sin usar (panel IA → Inicio)
    def song_span(self) -> tuple[float, float] | None:
        """Dónde está la canción en la línea de tiempo: la de una pista de audio con su ritmo reconocido; si no, el
        último edit musical; si no, todo lo que tiene audio."""
        p = self.project
        for c in sorted(p.clips.values(), key=lambda c: c.start):
            tr = p.track(c.track_id)
            m = p.media_of(c)
            if tr is not None and tr.kind == TRACK_AUDIO and m is not None and self.rhythm.get(m.id) and c.enabled:
                return c.start, c.end
        if p.edits:
            e = p.edits[-1]
            return float(e["base"]), float(e["base"]) + float(e["duration"])
        aud = [(c.start, c.end) for c in p.clips.values()
               if (tr := p.track(c.track_id)) is not None and tr.kind == TRACK_AUDIO and c.enabled]
        return (min(a for a, _b in aud), max(b for _a, b in aud)) if aud else None

    def place_scene_items(self, items: list[dict], text: str, clear: tuple[float, float] | None = None) -> list[str]:
        """🎬 Escenas elegidas a mano → planos en la pista de video principal (sin su sonido: suena lo de debajo).
        clear = vaciar antes ese tramo de la pista («Desde cero»). Un solo paso de Ctrl+Z."""
        from . import scene_pool

        def fn(p: Project):
            v1 = scene_pool.main_video_track(p)
            if v1 is None:
                raise EditError("Hace falta una pista de video.")
            self._check_track(p, v1.id)
            if clear is not None:
                self._clear_range(p, v1.id, clear[0], clear[1])
            lay_mode = (p.edits[-1].get("layout") or "auto") if p.edits else "auto"   # como el edit (fondo, espejo…)
            out = []
            for it in items:
                m = p.media.get(it["media_id"])
                if m is None:
                    continue
                self._clear_range(p, v1.id, it["start"], it["start"] + it["duration"])
                c = Clip(new_id(), m.id, v1.id, it["start"], it["source_in"], it["duration"], volume=0.0,
                         layout=self._edit_layout(p, m, v1.id, lay_mode))
                p.clips[c.id] = c
                out.append(c.id)
            return out
        return self._edit(text, fn)

    # ------------------------------------------------- ⚡ ráfaga de cortes (a mano, al ritmo de la canción)
    def song_beats(self, a: float, b: float) -> list[float]:
        """Golpes de la canción (en la línea de tiempo) entre a y b: la de una pista de audio con su ritmo reconocido."""
        p = self.project
        out: list[float] = []
        for c in p.clips.values():
            tr = p.track(c.track_id)
            m = p.media_of(c)
            rh = self.rhythm.get(m.id) if m else None
            if tr is None or tr.kind != TRACK_AUDIO or not rh or not c.enabled or c.speed <= 0 or c.reverse:
                continue
            if c.end <= a or c.start >= b:
                continue
            for s in rh.get("beats", []):
                t = c.start + (s - c.source_in) / c.speed
                if max(a, c.start) - 1e-3 <= t <= min(b, c.end) + 1e-3:
                    out.append(round(t, 4))
            if out:
                break
        return sorted(set(out))

    def burst_cuts(self, a: float, b: float, per_beat: int = 2, clip_ids: list[str] | None = None) -> int:
        """⚡ Ráfaga: corta la imagen entre a y b al ritmo de la canción (per_beat cortes por golpe: 2 = medio golpe,
        4 = cuarto) y cada trozo salta a OTRO plano (otro video del proyecto, o otro momento del mismo), para que los
        cortes se vean. El sonido no se toca (la imagen se separa de su sonido). Un solo paso de Ctrl+Z."""
        beats = self.song_beats(a - 1.0, b + 1.0)
        if len(beats) < 2:
            raise EditError("⚡ La ráfaga va al ritmo de la canción: pon antes una canción en una pista de audio "
                            "(y espera a que Reclaimer reconozca su ritmo 🥁).")
        grid: list[float] = []
        for x, y in zip(beats, beats[1:]):
            for k in range(per_beat):
                g = x + (y - x) * k / per_beat
                if a + 1e-3 < g < b - 1e-3:
                    grid.append(round(g, 4))
        if not grid:
            raise EditError("⚡ No hay golpes de la canción en ese tramo.")
        rng = np.random.default_rng(int(a * 1000) % 2**31)

        def fn(p: Project):
            targets = []
            for cid in (clip_ids or []):
                c = p.clips.get(cid)
                tr = p.track(c.track_id) if c else None
                if c and tr and tr.kind == TRACK_VIDEO and c.text is None and c.end > a and c.start < b:
                    targets.append(c)
            if not targets:          # sin selección: el clip de video de más arriba que se ve en ese tramo
                for tr in p.tracks:
                    if tr.kind != TRACK_VIDEO or tr.hidden:
                        continue
                    c = p.clip_at(tr.id, a + 1e-3)
                    if c is not None and c.text is None:
                        targets.append(c)
                        break
            if not targets:
                raise EditError("⚡ No hay ningún clip de video en el cabezal para la ráfaga.")
            pool = [m for m in p.media.values() if m.kind == KIND_VIDEO and m.id not in self.missing and m.duration > 1]
            n = 0
            for c in targets:
                self._check_clip(p, c)
                for o in self.partners(p, c):      # la imagen se separa de su sonido (que sigue igual)
                    o.link = ""
                c.link = ""
                pieces = [c]
                cut_at = set(grid) | {round(b, 4)}       # también al final: después de la ráfaga sigue como estaba
                for t in sorted(g for g in cut_at if c.start + MIN_CLIP < g < c.end - MIN_CLIP):
                    cur = pieces[-1]
                    right = replace(cur, id=new_id(), start=t, duration=cur.end - t,
                                    source_in=cur.piece_src(t - cur.start, cur.duration),
                                    fx={k: v for k, v in (cur.fx or {}).items() if k not in self.START_FX} or None)
                    cur.source_in = cur.piece_src(0.0, t - cur.start)
                    cur.duration = t - cur.start
                    cur.fx = {k: v for k, v in (cur.fx or {}).items() if k != "fade_out"} or None
                    p.clips[right.id] = right
                    pieces.append(right)
                    n += 1
                last_mid = c.media_id
                for k, pc in enumerate(pieces[1:], 1):
                    if pc.start >= b - 1e-3:
                        break
                    if pc.start <= a + 1e-3:
                        continue
                    others = [m for m in pool if m.id != last_mid] or pool
                    m = others[int(rng.integers(len(others)))] if others else None
                    if m is None:
                        continue
                    need = pc.duration * max(pc.speed, 0.01)
                    lo, hi = 0.5, max(0.5, m.duration - need - 0.5)
                    pc.media_id = m.id
                    pc.source_in = round(float(rng.uniform(lo, hi)) if hi > lo else 0.0, 3)
                    pc.zoom_kf, pc.layout_kf = [], []
                    last_mid = m.id
            if not n:
                raise EditError("⚡ Ese tramo es demasiado corto para una ráfaga.")
            return n
        return self._edit("⚡ Ráfaga de cortes", fn)

    def add_markers(self, times: list[float], label: str = "Corte de escena") -> int:
        def fn(p: Project):
            for i, t in enumerate(sorted(times)):
                p.markers.append(Marker(new_id(), max(0.0, t), f"{label} {i + 1}", color="#7fd1ff"))
            p.markers.sort(key=lambda m: m.time)
            return len(times)

        return self._edit(f"Marcadores: {label.lower()}s", fn)

    def freeze_frame(self, t: float, clip_id: str | None = None):
        """Congela la imagen desde el cabezal hasta el final del clip (Mayús+R en Resolve).
        El sonido sigue como estaba."""
        def fn(p: Project):
            c = p.clips.get(clip_id or "")
            if c is None:
                vids = [tr for tr in p.tracks if tr.kind == TRACK_VIDEO and not tr.hidden]
                c = next((x for tr in vids for x in [p.clip_at(tr.id, t)]
                          if x is not None and x.text is None and not self._is_image(p, x)), None)
            if c is None or self._is_image(p, c) or p.track(c.track_id).kind != TRACK_VIDEO:
                raise EditError("Pon el cabezal sobre un clip de video (o selecciónalo) para congelar su imagen.")
            self._check_clip(p, c)
            t0 = min(max(t, c.start), c.end - MIN_CLIP)
            frame = c.src_at(t0 - c.start)
            if t0 - c.start > MIN_CLIP:
                right = replace(c, id=new_id(), start=t0, duration=c.end - t0, link="")
                c.source_in = c.piece_src(0.0, t0 - c.start)
                c.duration = t0 - c.start
                p.clips[right.id] = right
                c = right
            c.link = ""          # su sonido queda como estaba (ya no se mueven juntos)
            c.speed, c.reverse, c.source_in = 0.0, False, frame
            c.zoom_kf = [dict(k) for k in c.zoom_kf]
            return c.id

        return self._edit("Congelar fotograma", fn)

    def delete_clips(self, clip_ids: list[str], ripple: bool = False):
        """Borra clips de la timeline (el archivo original sigue en la biblioteca).
        ripple=True: además cierra el hueco moviendo lo que viene detrás en esa pista."""
        def fn(p: Project):
            clips = sorted((p.clips[cid] for cid in clip_ids if cid in p.clips),
                           key=lambda c: c.start, reverse=True)
            if not clips:
                return
            for c in clips:
                self._check_clip(p, c)
            for c in clips:
                del p.clips[c.id]
                if ripple:
                    for o in p.clips_on(c.track_id):
                        if o.start >= c.end - EPS:
                            if o.locked:
                                raise EditError("🔒 No se puede cerrar el hueco: hay un clip bloqueado detrás.")
                            o.start -= c.duration
            # Temas que se quedan sin sonido debajo (borraste la narración de la que salieron): fuera también
            aud = [x for x in p.clips.values() if p.track(x.track_id) and p.track(x.track_id).kind == TRACK_AUDIO]
            p.markers = [m for m in p.markers if m.kind != "topic" or
                         any(x.start < (m.end or m.time) - EPS and x.end > m.time + EPS for x in aud)]

        n = len(clip_ids)
        text = "Eliminar y cerrar hueco" if ripple else ("Eliminar clip" if n == 1 else f"Eliminar {n} clips")
        return self._edit(text, fn)

    def place_segment(self, media_id: str, src: float, dur: float, mode: str, t: float = 0.0,
                      target: str | None = None, note: str = "", volume: float = 0.0):
        """Coloca un trozo de un archivo (un momento encontrado por la IA) en la línea de tiempo:
          mode="insert"  → en el instante t, en una pista de video libre (nunca tapa nada),
          mode="after"   → justo detrás del clip «target»,
          mode="replace" → sustituye el contenido del clip «target» (misma posición y duración).
        Devuelve el id del clip."""

        def fn(p: Project):
            m = p.media.get(media_id)
            if m is None:
                raise EditError("Ese archivo ya no está en la biblioteca.")
            img = m.kind == KIND_IMAGE
            s0 = 0.0 if img else max(0.0, src)
            d = dur if img else min(dur, max(0.1, m.duration - s0))
            if mode == "replace":
                c = p.clips.get(target or "")
                if c is None or c.text is not None:
                    raise EditError("Selecciona en la línea de tiempo el clip que quieres reemplazar.")
                self._check_clip(p, c)
                if p.track(c.track_id).kind != TRACK_VIDEO:
                    raise EditError("Solo se puede reemplazar un clip de video o imagen.")
                new_d = c.duration if img else min(c.duration, max(0.1, m.duration - s0))
                for x in [c] + [o for o in self.partners(p, c) if p.track(o.track_id).kind == TRACK_AUDIO]:
                    self._check_clip(p, x)
                    if x is not c:   # su sonido vinculado era el del clip anterior: ya no corresponde
                        del p.clips[x.id]
                c.link = ""
                c.media_id, c.source_in, c.duration = m.id, s0, new_d
                c.zoom_kf, c.origin = [], ORIGIN_AI
                c.layout = self._auto_layout(p, m, c.track_id)
                c.note = note or c.note
                return c.id
            if mode == "after":
                tc = p.clips.get(target or "")
                if tc is None:
                    raise EditError("Selecciona el clip detrás del que quieres añadirlo.")
                t0, pref = tc.end, (tc.track_id if p.track(tc.track_id).kind == TRACK_VIDEO else None)
            else:
                t0, pref = max(0.0, t), None
            vtracks = [x for x in p.tracks if x.kind == TRACK_VIDEO]
            if not vtracks:
                raise EditError("No hay pistas de video.")
            tid = self._free_track(p, TRACK_VIDEO, pref or vtracks[-1].id, t0, t0 + d)
            c = Clip(new_id(), m.id, tid, t0, s0, d, volume=volume, origin=ORIGIN_AI, note=note,
                     layout=self._auto_layout(p, m, tid))
            p.clips[c.id] = c
            if volume > 0:
                self._link_audio(p, c, m, volume)
            return c.id

        label = {"insert": "IA · Insertar momento", "after": "IA · Añadir momento después",
                 "replace": "IA · Reemplazar por momento"}[mode]
        return self._edit(label, fn)

    def toggle_favorite(self, media_id: str, start: float, end: float, label: str = "") -> bool:
        """Guarda o quita un momento de favoritos (se guarda con el proyecto). Devuelve si quedó guardado."""
        favs = self.project.favorites
        for f in favs:
            if f["media_id"] == media_id and abs(f["start"] - start) < 0.05 and abs(f["end"] - end) < 0.05:
                favs.remove(f)
                self._set_media_dirty()
                return False
        favs.append({"media_id": media_id, "start": round(start, 2), "end": round(end, 2), "label": label})
        self._set_media_dirty()
        return True

    def gap_at(self, track_id: str, t: float) -> tuple[float, float] | None:
        """El hueco vacío de una pista que contiene el instante t: (inicio, fin). Solo si hay algo
        detrás (un hueco al final de la pista no es un hueco)."""
        clips = self.project.clips_on(track_id)
        if any(c.start - EPS <= t < c.end + EPS for c in clips):
            return None
        a = max((c.end for c in clips if c.end <= t + EPS), default=0.0)
        b = min((c.start for c in clips if c.start >= t - EPS), default=None)
        if b is None or b - a < MIN_CLIP:
            return None
        return a, b

    def _close_gap(self, p: Project, track_id: str, a: float, b: float) -> float:
        """Mueve a la izquierda lo que hay detrás del hueco, hasta donde algo lo bloquee.
        Lo vinculado en otras pistas (su sonido o su imagen) se mueve igual, sin pisar nada."""
        self._check_track(p, track_id)
        clips = p.clips_on(track_id)
        if any(c.start < b - EPS and c.end > a + EPS for c in clips):
            raise EditError("Ese tramo no está vacío.")
        after = [c for c in clips if c.start >= b - EPS]
        if not after:
            raise EditError("No hay nada detrás del hueco que mover.")
        d = b - a
        moved = {c.id for c in after}
        starts: dict[str, float] = {}
        for c in after:
            for o in self.partners(p, c):
                if o.track_id != track_id:
                    starts[o.track_id] = min(starts.get(o.track_id, math.inf), o.start)
        for tid, t0 in starts.items():
            self._check_track(p, tid)
            others = p.clips_on(tid)
            prev_end = max((c.end for c in others if c.start < t0 - EPS), default=0.0)
            d = min(d, t0 - prev_end)     # nunca encima del clip anterior de esa pista
            moved |= {c.id for c in others if c.start >= t0 - EPS}
        if d <= EPS:
            raise EditError("No se puede cerrar ese hueco: en otra pista, su sonido o imagen vinculado "
                            "chocaría con otro clip.")
        for cid in moved:
            if p.clips[cid].locked:
                raise EditError("🔒 No se puede cerrar el hueco: hay un clip bloqueado detrás.")
        for cid in moved:
            p.clips[cid].start -= d
        return d

    def close_gap(self, track_id: str, a: float, b: float):
        """Eliminar un hueco vacío de la línea de tiempo (lo de detrás se desplaza a la izquierda)."""
        return self._edit("Eliminar hueco", lambda p: self._close_gap(p, track_id, a, b))

    def join_gaps(self, points: list[tuple[str, float]]):
        """⇤ «Juntar» (Ctrl++, como el atajo del usuario en Resolve): en cada (pista, instante) que cae en un hueco, lo de
        la derecha se pega a lo de la izquierda (con su imagen o sonido vinculado). Un solo Ctrl+Z.
        Si al cerrar uno ya se cerró el de otra pista (estaban vinculados), ese se salta."""
        def fn(p: Project):
            n = 0
            for tid, t in points:
                tr = p.track(tid)
                if tr is None or tr.locked:
                    continue
                g = self.gap_at(tid, t)
                if g is None:
                    continue
                self._close_gap(p, tid, g[0], g[1])
                n += 1
            if not n:
                raise EditError("No hay ningún hueco ahí: pon el cabezal en un espacio vacío, selecciona el hueco o el "
                                "clip que quieres pegar a lo de su izquierda.")
            return n
        return self._edit("Juntar (cerrar hueco)", fn)

    def close_gaps_on(self, kind: str | None = None, track_ids: list[str] | None = None) -> int:
        """Cierra los huecos de varias pistas a la vez (un solo paso de deshacer):
        kind = "audio" | "video" | None (todas), o las pistas indicadas. Las bloqueadas se saltan."""
        def fn(p: Project):
            tids = track_ids or [t.id for t in p.tracks if (kind is None and t.kind in (TRACK_AUDIO, TRACK_VIDEO))
                                 or t.kind == kind]
            total = 0
            for tid in tids:
                tr = p.track(tid)
                if tr is None or tr.locked:
                    continue
                total += self._close_track_gaps(p, tid)
            if not total:
                raise EditError("No hay huecos que se puedan cerrar ahí.")
            return total

        names = {"audio": "en las pistas de audio", "video": "en las pistas de video", None: "en todas las pistas"}
        return self._edit("Eliminar huecos " + (names.get(kind, "") if not track_ids else "de la pista"), fn)

    def _close_track_gaps(self, p: Project, track_id: str) -> int:
        """Cierra todos los huecos de una pista de izquierda a derecha, igual que _close_gap uno a uno (lo de detrás y
        lo vinculado en otras pistas se mueve igual, sin pisar nada; lo bloqueado no se mueve: ese hueco se salta),
        pero en UNA pasada: cada hueco desplaza «todo lo de detrás», así que basta con ir sumando cuánto se ha movido y
        aplicarlo al final. (Uno a uno, con 1000 huecos y su sonido vinculado tardaba minutos.)"""
        import bisect
        T = p.clips_on(track_id)
        if not T:
            return 0
        if p.track(track_id) is not None and p.track(track_id).locked:
            return 0
        by_link: dict[str, list] = {}
        for c in p.clips.values():
            if c.link:
                by_link.setdefault(c.link, []).append(c)
        others: dict[str, list] = {}               # pistas con algo vinculado a esta (ordenadas, como clips_on)
        for c in T:
            for o in by_link.get(c.link, ()) if c.link else ():
                if o.track_id != track_id and o.track_id not in others:
                    others[o.track_id] = p.clips_on(o.track_id)
        idx = {tid: {c.id: k for k, c in enumerate(lst)} for tid, lst in others.items()}
        n_t = len(T)
        INF = 1 << 60
        # para cada i: el primer clip (en orden) de cada otra pista vinculado a algo de T[i:]
        suf = {tid: [INF] * (n_t + 1) for tid in others}
        for i in range(n_t - 1, -1, -1):
            c = T[i]
            for tid in others:
                suf[tid][i] = suf[tid][i + 1]
            if c.link:
                for o in by_link[c.link]:
                    if o.track_id in others:
                        k = idx[o.track_id][o.id]
                        if k < suf[o.track_id][i]:
                            suf[o.track_id][i] = k
        for tid, lst in others.items():            # lo que empieza a la vez que ese primero también se mueve
            st = [c.start for c in lst]
            for i in range(n_t + 1):
                k = suf[tid][i]
                if k < INF:
                    suf[tid][i] = bisect.bisect_left(st, st[k] - EPS)
        def locked_suffix(lst):
            out = [False] * (len(lst) + 1)
            for k in range(len(lst) - 1, -1, -1):
                out[k] = out[k + 1] or bool(lst[k].locked)
            return out
        lockT = locked_suffix(T)
        lockO = {tid: locked_suffix(lst) for tid, lst in others.items()}
        tr_locked = {tid: bool(p.track(tid) and p.track(tid).locked) for tid in others}
        ptr = {tid: 0 for tid in others}
        runmax = {tid: 0.0 for tid in others}      # fin del último clip de esa pista antes del que se moverá
        D = 0.0                                    # cuánto se ha movido ya «todo lo de detrás»
        events: list[tuple[int, dict, float]] = []
        prev_end = 0.0
        for i, c in enumerate(T):
            cs = c.start - D
            gap = cs - prev_end
            if gap >= MIN_CLIP and not lockT[i]:
                d = gap
                js = {}
                for tid, lst in others.items():
                    j = suf[tid][i]
                    if j >= INF:
                        continue
                    if tr_locked[tid] or lockO[tid][j]:
                        d = 0.0
                        break
                    while ptr[tid] < j:            # esos ya no se moverán más: su sitio es el de ahora
                        runmax[tid] = max(runmax[tid], lst[ptr[tid]].end - D)
                        ptr[tid] += 1
                    d = min(d, (lst[j].start - D) - runmax[tid])
                    js[tid] = j
                if d > EPS:
                    D += d
                    events.append((i, js, d))
                    cs -= d
            prev_end = max(prev_end, cs + c.duration)
        if not events:
            return 0
        acc, e = 0.0, 0                             # aplicar: cada clip, lo de todos los huecos de antes
        for i, c in enumerate(T):
            while e < len(events) and events[e][0] <= i:
                acc += events[e][2]
                e += 1
            if acc:
                c.start -= acc
        for tid, lst in others.items():
            evs = sorted((js[tid], d) for _i, js, d in events if tid in js)
            acc, e = 0.0, 0
            for k, c in enumerate(lst):
                while e < len(evs) and evs[e][0] <= k:
                    acc += evs[e][1]
                    e += 1
                if acc:
                    c.start -= acc
        return len(events)

    def close_all_gaps(self, track_id: str):
        """Cierra todos los huecos de una pista, de izquierda a derecha (una pista bloqueada no se toca)."""
        def fn(p: Project):
            tr = p.track(track_id)
            if tr is not None and tr.locked:
                raise EditError(f"La pista «{tr.name}» está bloqueada: desbloquéala para cerrar sus huecos.")
            n = self._close_track_gaps(p, track_id)
            if not n:
                raise EditError("No hay huecos que se puedan cerrar en esa pista.")
            return n

        return self._edit("Eliminar todos los huecos de la pista", fn)

    def set_clip_props(self, clip_ids: list[str], text: str, **props):
        def fn(p: Project):
            for cid in clip_ids:
                c = p.clips.get(cid)
                if c is None:
                    continue
                if set(props) - {"locked"}:  # bloquear/desbloquear siempre se permite
                    self._check_clip(p, c)
                for k, v in props.items():
                    setattr(c, k, v)

        return self._edit(text, fn)

    def apply_mix(self, curves: dict, track_ids: list[str], text: str = "🎚 Mezcla de la IA"):
        """🎛 Aplica la mezcla propuesta (las curvas de volumen de la música) en UN paso de Ctrl+Z. La curva de antes
        queda guardada en fx["mix_orig"] (para volver a proponer o quitarla). En esas pistas se quita el «bajar al
        hablar» fijo (ya va dentro de la curva)."""
        def fn(p: Project):
            for cid, kf in curves.items():
                c = p.clips.get(cid)
                if c is None or (p.track(c.track_id) and p.track(c.track_id).locked):
                    continue
                fx = dict(c.fx or {})
                if "mix_orig" not in fx:
                    fx["mix_orig"] = [dict(k) for k in c.vol_kf]
                c.fx = fx
                c.vol_kf = [dict(k) for k in kf]
            for tid in track_ids:
                tr = p.track(tid)
                if tr is not None and not tr.locked:
                    tr.duck_db = None
        return self._edit(text, fn)

    def remove_mix(self, track_ids: list[str] | None = None):
        """Quita la mezcla de la IA: cada clip vuelve a la curva de volumen que tenía antes."""
        def fn(p: Project):
            for c in p.clips.values():
                if track_ids and c.track_id not in track_ids:
                    continue
                fx = dict(c.fx or {})
                if "mix_orig" in fx:
                    c.vol_kf = [dict(k) for k in fx.pop("mix_orig") or []]
                    c.fx = fx or None
        return self._edit("Quitar la mezcla de la IA", fn)

    def set_track_props(self, track_id: str, text: str, **props):
        def fn(p: Project):
            tr = p.track(track_id)
            if tr is None:
                return
            for k, v in props.items():
                setattr(tr, k, v)

        return self._edit(text, fn)

    def lock_all_tracks(self, locked: bool):
        def fn(p: Project):
            for tr in p.tracks:
                tr.locked = locked

        return self._edit("Bloquear timeline" if locked else "Desbloquear timeline", fn)

    # ------------------------------------------------- papel de las pistas (voz / música / efectos)
    ROLE_WORDS = {"musica": ("músic", "music", "canci", "song"), "efectos": ("fecto", "sfx", "sonidos"),
                  "voz": ("narra", "voz", "voice", "locuc")}

    def _role_track(self, p: Project, role: str, create: bool = True) -> str | None:
        """La pista de audio con ese papel (por su papel, por «baja al hablar» si es música o por su nombre).
        Si no hay y create=True: una pista vacía sin papel, o una pista nueva (dentro de la misma edición)."""
        atracks = [t for t in p.tracks if t.kind == TRACK_AUDIO and not t.locked]
        for t in atracks:
            if t.role == role:
                return t.id
        if role == "musica":
            for t in atracks:
                if t.duck_db is not None:
                    return t.id
        for t in atracks:
            if any(w in t.name.lower() for w in self.ROLE_WORDS.get(role, ())):
                return t.id
        if not create:
            return None
        first = next((t for t in p.tracks if t.kind == TRACK_AUDIO), None)     # tu pista principal: nunca
        empty = next((t for t in atracks if t is not first and not t.role and t.duck_db is None
                      and re.fullmatch(r"A\d+", t.name) and not p.clips_on(t.id)), None)
        tr = empty
        if tr is None:
            n = sum(1 for t in p.tracks if t.kind == TRACK_AUDIO) + 1
            tr = Track(new_id(), TRACK_AUDIO, f"A{n}")
            p.tracks.append(tr)
        tr.role = role
        if role == "musica" and tr.duck_db is None:
            tr.duck_db = -12.0
        return tr.id

    def ensure_role_track(self, role: str) -> str | None:
        """La pista para música o efectos: la que ya tenga ese papel o una nueva (un paso de deshacer)."""
        tid = self._role_track(self.project, role, create=False)
        if tid:
            return tid
        res = self._edit("Añadir pista", lambda p: self._role_track(p, role, create=True))
        return res if isinstance(res, str) else None

    def add_track(self, kind: str):
        def fn(p: Project):
            n = sum(1 for t in p.tracks if t.kind == kind) + 1
            if kind == TRACK_VIDEO:
                p.tracks.insert(0, Track(new_id(), TRACK_VIDEO, f"V{n}"))
            else:
                p.tracks.append(Track(new_id(), TRACK_AUDIO, f"A{n}"))

        return self._edit("Añadir pista", fn)

    def remove_track(self, track_id: str):
        def fn(p: Project):
            tr = self._check_track(p, track_id)
            if p.clips_on(track_id):
                raise EditError("Solo se pueden eliminar pistas vacías.")
            if sum(1 for t in p.tracks if t.kind == tr.kind) <= 1:
                raise EditError("Tiene que quedar al menos una pista de cada tipo.")
            p.tracks.remove(tr)

        return self._edit("Eliminar pista", fn)

    def add_marker(self, t: float, label: str = ""):
        def fn(p: Project):
            n = len(p.markers) + 1
            p.markers.append(Marker(new_id(), max(0.0, t), label or f"Marcador {n}"))
            p.markers.sort(key=lambda m: m.time)

        return self._edit("Añadir marcador", fn)

    def update_marker(self, marker_id: str, **props):
        def fn(p: Project):
            for m in p.markers:
                if m.id == marker_id:
                    for k, v in props.items():
                        setattr(m, k, v)
            p.markers.sort(key=lambda m: m.time)

        return self._edit("Editar marcador", fn)

    def remove_marker(self, marker_id: str):
        def fn(p: Project):
            p.markers = [m for m in p.markers if m.id != marker_id]

        return self._edit("Eliminar marcador", fn)

    def set_settings(self, **props):
        def fn(p: Project):
            for k, v in props.items():
                setattr(p, k, v)

        return self._edit("Cambiar ajustes del proyecto", fn)

    # ------------------------------------------- cortes con "cerrar hueco"
    def _check_ripple(self, p: Project, t: float):
        """Cerrar o abrir un hueco mueve todo lo que hay detrás: no puede haber nada bloqueado."""
        for c in p.clips.values():
            if c.end > t + EPS and (c.locked or p.track(c.track_id).locked):
                tr = p.track(c.track_id)
                raise EditError(f"🔒 No se puede: hay contenido bloqueado después de este punto "
                                f"(pista «{tr.name}»). Desbloquéalo o aplica el corte a mano.")

    def remove_silence(self, clip_ids: list[str], regions: list[tuple[float, float]], scope: str = "all",
                       crossfade: bool = False) -> int:
        """«✂ Eliminar silencio»: quita los tramos (de la línea de tiempo) y cierra el hueco.
        scope="all": en TODAS las pistas (no se desincroniza nada, como la limpieza de voz);
        scope="track": solo en las pistas de esos clips (y de su imagen/sonido vinculado).
        crossfade: un fundido mínimo en cada corte del audio (sin «clics»)."""
        regs = sorted((a, b) for a, b in regions if b - a > 1e-3)
        if not regs:
            raise EditError("No hay silencios que quitar con estos ajustes.")

        def fn(p: Project):
            tracks = None
            if scope != "all":
                tracks = set()
                for cid in clip_ids:
                    c = p.clips.get(cid)
                    if c is not None:
                        tracks.add(c.track_id)
                        tracks.update(o.track_id for o in self.partners(p, c))
            for a, b in reversed(regs):            # del final al principio: lo anterior no se mueve
                if tracks is None:
                    self._ripple_delete(p, a, b)
                else:
                    d = b - a
                    for tid in tracks:
                        self._check_track(p, tid)
                        self._clear_range(p, tid, a, b)
                        for c in p.clips_on(tid):
                            if c.start >= b - EPS:
                                if c.locked:
                                    raise EditError("🔒 Hay un clip bloqueado detrás: no se puede mover.")
                                c.start -= d
            if crossfade:
                fade = min(0.08, 2.0 / max(p.fps, 1.0))
                removed = 0.0
                cuts = []
                for a, b in regs:                   # dónde quedó cada corte al final
                    cuts.append(a - removed)
                    removed += b - a
                for tr in p.tracks:
                    if tr.kind != TRACK_AUDIO or (tracks is not None and tr.id not in tracks):
                        continue
                    for c in p.clips_on(tr.id):
                        for t in cuts:
                            if abs(c.start - t) < 1e-4:
                                c.fx = dict(c.fx or {}, fade_in=max(float((c.fx or {}).get("fade_in", 0)), fade))
                            if abs(c.end - t) < 1e-4:
                                c.fx = dict(c.fx or {}, fade_out=max(float((c.fx or {}).get("fade_out", 0)), fade))
            return len(regs)

        total = sum(b - a for a, b in regs)
        return self._edit(f"Eliminar silencio ({len(regs)} tramos, {total:.1f} s)", fn)

    def _ripple_delete(self, p: Project, ta: float, tb: float):
        """Quita el tramo [ta, tb] de TODAS las pistas y adelanta lo que viene detrás."""
        d = tb - ta
        self._check_ripple(p, ta)
        for tr in p.tracks:
            self._clear_range(p, tr.id, ta, tb)
            for c in p.clips_on(tr.id):
                if c.start >= tb - EPS:
                    c.start -= d
        for m in p.markers:
            if m.time >= tb:
                m.time -= d
            elif m.time > ta:
                m.time = ta
            if m.end is not None:
                if m.end >= tb:
                    m.end -= d
                elif m.end > ta:
                    m.end = ta
                m.end = max(m.end, m.time)

    def _ripple_insert(self, p: Project, t: float, d: float):
        """Abre un hueco de d segundos en el momento t en TODAS las pistas."""
        self._check_ripple(p, t)
        for tr in p.tracks:
            for c in p.clips_on(tr.id):
                if c.start < t - EPS < c.end - EPS:  # el clip cruza el punto: se parte
                    right = replace(c, id=new_id(), start=t, duration=c.end - t,
                                    source_in=0.0 if self._is_image(p, c) else c.piece_src(t - c.start, c.duration))
                    if not self._is_image(p, c):
                        c.source_in = c.piece_src(0.0, t - c.start)
                    c.duration = t - c.start
                    p.clips[right.id] = right
            for c in p.clips_on(tr.id):
                if c.start >= t - EPS:
                    c.start += d
        for m in p.markers:
            if m.time >= t:
                m.time += d
            if m.end is not None and m.end >= t:
                m.end += d

    def _heal(self, p: Project, track_id: str, t: float, d: float):
        """Tras abrir un hueco [t, t+d]: si a ambos lados está el mismo archivo y el trozo
        que falta es justo el del hueco, se rellena y se vuelve a unir en un solo clip."""
        tol = mapping.TOL
        clips = p.clips_on(track_id)
        left = next((c for c in clips if abs(c.end - t) <= tol), None)
        right = next((c for c in clips if abs(c.start - (t + d)) <= tol), None)
        if left is None or right is None or left.media_id != right.media_id:
            return
        if left.retimed or right.retimed:
            return
        continuous = self._is_image(p, left) or \
            abs(right.source_in - (left.source_in + left.duration + d)) <= tol
        same_props = (left.enabled, left.volume, left.origin) == (right.enabled, right.volume, right.origin)
        if continuous and same_props:
            left.duration += d + right.duration
            del p.clips[right.id]

    # ------------------------------------------------- ritmo de la música
    def is_music_clip(self, c: Clip) -> bool:
        """Una canción: un clip de sonido en la pista de música (la que baja al hablar) o un archivo
        de la categoría Música."""
        p = self.project
        tr = p.track(c.track_id)
        m = p.media.get(c.media_id)
        if tr is None or tr.kind != TRACK_AUDIO or m is None or c.text is not None:
            return False
        if m.kind != KIND_AUDIO and not (m.kind == KIND_VIDEO and m.has_audio):
            return False
        cat = (m.category or "").lower()
        return tr.duck_db is not None or any(w in cat for w in ("músic", "music", "canci", "song"))

    def analyze_rhythm(self, media_ids, force: bool = False) -> int:
        """Reconoce el ritmo de esas canciones en segundo plano. Devuelve cuántas empezó."""
        n = 0
        for mid in media_ids:
            m = self.project.media.get(mid)
            if m is None or mid in self.missing or mid in self.rhythm_busy or (mid in self.rhythm and not force):
                continue
            self.rhythm_busy.add(mid)
            self._pool.start(_RhythmTask(mid, m.path, self._signals))
            n += 1
        return n

    def _auto_rhythm(self):
        """Cada canción que pones en la pista de música se escucha sola (una vez; luego queda en caché)."""
        todo = {c.media_id for c in self.project.clips.values()
                if c.media_id not in self.rhythm and c.media_id not in self.rhythm_busy and self.is_music_clip(c)}
        if todo:
            self.analyze_rhythm(todo)

    def _on_rhythm(self, media_id: str, res: dict):
        self.rhythm_busy.discard(media_id)
        m = self.project.media.get(media_id)
        if m is None:
            return
        if res.get("error"):
            self.message.emit(f"No se pudo reconocer el ritmo de «{m.name}»: {res['error'][:150]}")
            return
        from ..ai import rhythm
        self.rhythm[media_id] = res
        self.beats[media_id] = res["beats"]
        self.message.emit(f"🥁 Ritmo de «{m.name}»: {rhythm.summary(res)}")
        self.rhythm_changed.emit()

    def rhythm_on_timeline(self, clip_ids=None, exclude: set | None = None) -> dict:
        """Golpes, inicios de compás, golpes fuertes, drops y partes de la música, en tiempo de timeline."""
        from ..ai import rhythm
        out = {"beats": [], "downbeats": [], "strong": [], "drops": [], "sections": []}
        clips = [self.project.clips[i] for i in clip_ids if i in self.project.clips] if clip_ids is not None \
            else list(self.project.clips.values())
        for c in clips:
            r = self.rhythm.get(c.media_id)
            if r is None or c.retimed or not c.enabled or (exclude and c.id in exclude):
                continue
            tl = rhythm.to_timeline(r, c.source_in, c.duration, c.start)
            for k in ("beats", "downbeats", "strong", "sections"):
                out[k] += tl[k]
            if tl["drop"] is not None:
                out["drops"].append(tl["drop"])
        for k in ("beats", "downbeats", "strong", "drops"):
            out[k].sort()
        return out

    # ------------------------------------------------- 🛡 transformar una imagen (y volver al original)
    TRANSFORMS = {
        "cine": ("Cinemático", {"contrast": 0.2, "saturation": -0.15, "temperature": 0.1, "shadows": -0.1},
                 {"vignette": 0.55, "grain": 0.25}, (1.0, 1.12)),
        "poster": ("Póster", {"contrast": 0.45, "saturation": 0.25, "highlights": -0.1},
                   {"grain": 0.35, "vignette": 0.3}, (1.08, 1.08)),
        "bn": ("Blanco y negro", {"saturation": -1.0, "contrast": 0.35},
               {"grain": 0.4, "vignette": 0.6}, (1.0, 1.1)),
    }

    def transform_clips(self, clip_ids, style: str = "cine"):
        """Le da otro aspecto a la imagen/clip (color, grano, viñeta y un encuadre con zoom) para que no sea
        una copia tal cual. Se guarda cómo estaba: «↺ Volver al original» lo deja exactamente igual."""
        name, color, fx_add, (z0, z1) = self.TRANSFORMS[style]

        def fn(p: Project):
            n = 0
            for cid in clip_ids:
                c = p.clips.get(cid)
                tr = p.track(c.track_id) if c else None
                if c is None or c.text is not None or tr is None or tr.kind != TRACK_VIDEO or c.locked or tr.locked:
                    continue
                fx = dict(c.fx or {})
                orig = fx.pop("orig", None) or {"fx": dict(fx) or None, "color": c.color,
                                                 "zoom_kf": [dict(k) for k in c.zoom_kf]}
                base_fx = dict(orig["fx"] or {})
                base_fx.update(fx_add)
                base_fx["orig"] = orig
                base_fx["transform"] = style
                c.fx = base_fx
                c.color = dict(color)
                t0 = 0.0 if self._is_image(p, c) else c.source_in
                t1 = t0 + (c.duration if self._is_image(p, c) else c.src_len)
                c.zoom_kf = [{"t": round(t0, 4), "z": z0, "x": 0.5, "y": 0.5, "i": "linear"},
                             {"t": round(t1, 4), "z": z1, "x": 0.5, "y": 0.5, "i": "linear"}]
                n += 1
            if not n:
                raise EditError("Selecciona clips de video o imágenes (no bloqueados) para transformarlos.")
            return n

        return self._edit(f"Transformar: {name}", fn)

    def restore_original(self, clip_ids) -> int | None:
        """↺ Deja los clips transformados exactamente como estaban."""
        def fn(p: Project):
            n = 0
            for cid in clip_ids:
                c = p.clips.get(cid)
                orig = (c.fx or {}).get("orig") if c else None
                if c is None or orig is None:
                    continue
                c.fx = dict(orig["fx"]) if orig.get("fx") else None
                c.color = orig.get("color")
                c.zoom_kf = [dict(k) for k in orig.get("zoom_kf") or []]
                n += 1
            if not n:
                raise EditError("Esos clips no están transformados.")
            return n

        return self._edit("Volver al original", fn)

    # ------------------------------------------------- ⭐ mis efectos para la IA
    START_FX = ("trans", "fade_in", "flash", "shake", "glitch", "invert")

    def _split_at(self, p: Project, c: Clip, t: float) -> Clip:
        """Divide c (y su sonido vinculado) en t. Devuelve la parte derecha de c. Los efectos «de entrada»
        (destello, transición…) se quedan en la izquierda y el fundido de salida pasa a la derecha."""
        group = [c] + [o for o in self.partners(p, c) if o.start + MIN_CLIP < t < o.end - MIN_CLIP]
        link = new_id() if (c.link and len(group) > 1) else ""
        right_c = c
        for o in group:
            fx = dict(o.fx or {})
            rfx = {k: v for k, v in fx.items() if k not in self.START_FX}
            lfx = {k: v for k, v in fx.items() if k != "fade_out"}
            right = replace(o, id=new_id(), start=t, duration=o.end - t, fx=rfx or None,
                            source_in=0.0 if self._is_image(p, o) else o.piece_src(t - o.start, o.duration),
                            link=link)
            if self._is_image(p, o) and o.layout_kf:   # imágenes: sus claves cuentan desde el inicio del clip
                right.layout_kf = [dict(k, t=round(k["t"] - (t - o.start), 4)) for k in o.layout_kf]
            if not self._is_image(p, o):
                o.source_in = o.piece_src(0.0, t - o.start)
            o.duration = t - o.start
            o.fx = lfx or None
            p.clips[right.id] = right
            if o is c:
                right_c = right
        return right_c

    def apply_effect_items(self, items: list[dict], sound_media: dict[str, str] | None = None):
        """Pone efectos de «⭐ Mis efectos para la IA»: [{effect, t, clip_id}] en un solo paso de deshacer.
        Imagen: en ese instante (cortando el clip si cae en medio), al empezar/acabar o en todo el clip.
        Sonido: en la pista de efectos (el whoosh un poco antes del corte, la subida acaba en el momento).
        Transición: en el corte del inicio del clip."""
        from ..ai.effect_memory import effect_info
        from . import transitions
        sound_media = sound_media or {}

        def fn(p: Project):
            n = 0
            for it in sorted(items, key=lambda x: x["t"]):
                info = effect_info(it["effect"])
                if info["type"] == "sound":
                    m = p.media.get(sound_media.get(it["effect"], ""))
                    if m is None or m.duration <= 0:
                        continue
                    t0 = it["t"]
                    if info.get("category") == "Tensión":
                        t0 -= m.duration
                    elif info.get("category") == "Transiciones":
                        t0 -= min(0.35, m.duration / 2)
                    t0 = max(0.0, t0)
                    pref = p.track(self._role_track(p, "efectos", create=True))
                    if pref is None:
                        continue
                    tid = self._free_track(p, TRACK_AUDIO, pref.id, t0, t0 + m.duration)
                    sc = Clip(new_id(), m.id, tid, t0, 0.0, m.duration, origin=ORIGIN_AI, note="⭐ " + info["name"])
                    p.clips[sc.id] = sc
                    n += 1
                    continue
                c = p.clips.get(it["clip_id"])
                tr = p.track(c.track_id) if c else None
                if c is None or c.locked or (tr and tr.locked):
                    continue
                if info["type"] == "transition":
                    prev = transitions.previous(p, c)
                    if prev is None:
                        continue
                    fx = dict(c.fx or {})
                    fx["trans"] = transitions.ai_trans(info["trans"], 0.5, prev, c)
                    c.fx = fx
                    n += 1
                    continue
                if info["apply"] == "moment":
                    t = it["t"]
                    if t - c.start > 0.3 and c.end - t > 0.2:
                        c = self._split_at(p, c, t)
                fx = dict(c.fx or {})
                fx[info["fx"]] = info["value"]
                c.fx = fx
                n += 1
            if not n:
                raise EditError("No se pudo poner ningún efecto (¿clips bloqueados o el sonido sin leer?).")
            return n

        return self._edit("IA · Mis efectos", fn)

    def add_rhythm_markers(self, clip_ids) -> int:
        """Marcadores en el drop y donde empieza cada parte de la canción (intro, subida, pausa…)."""
        from ..ai import rhythm
        rt = self.rhythm_on_timeline(clip_ids)
        colors = {"drop": "#e5413c", "build": "#f2b33d", "break": "#4fa3e0", "outro": "#9a8cff", "intro": "#7bc47f"}
        items = [(t, "💥 Drop", "#e5413c") for t in rt["drops"]]
        for s in rt["sections"]:
            if any(abs(s["a"] - c.start) < 0.05 for c in (self.project.clips[i] for i in clip_ids
                                                          if i in self.project.clips)):
                continue   # el inicio del clip no es una parte nueva
            if s["kind"] == "intro" or (s["kind"] == "drop" and any(abs(s["a"] - d) < 1.0 for d in rt["drops"])):
                continue
            items.append((s["a"], rhythm.KIND_ES.get(s["kind"], s["kind"]), colors.get(s["kind"], "#f2b33d")))
        if not items:
            return 0

        def fn(p: Project):
            n = 0
            for t, label, color in sorted(items):
                if any(abs(m.time - t) < 0.05 and m.label == label for m in p.markers):
                    continue
                p.markers.append(Marker(new_id(), round(t, 4), label, color, origin=ORIGIN_AI))
                n += 1
            return n

        return self._edit("Marcadores del ritmo", fn)

    # ------------------------------------------------- cortes a ritmo
    def beats_on_timeline(self, track_id: str) -> list[float]:
        """Golpes de la música de una pista, en tiempo de timeline (si ya se analizó)."""
        p = self.project
        out = []
        for c in p.clips_on(track_id):
            if c.retimed:
                continue
            for b in self.beats.get(c.media_id, []):
                if c.source_in <= b < c.source_in + c.duration:
                    out.append(c.start + (b - c.source_in))
        return sorted(out)

    def snap_cuts(self, track_id: str, targets: dict[float, float]):
        """Mueve los cortes entre clips seguidos de una pista al golpe de música indicado."""
        def fn(p: Project):
            clips = p.clips_on(track_id)
            n = 0
            for left, right in zip(clips, clips[1:]):
                cut = left.end
                if abs(right.start - cut) > 0.01:
                    continue
                key = next((k for k in targets if abs(k - cut) < 1e-3), None)
                if key is None or left.locked or right.locked or p.track(track_id).locked \
                        or left.retimed or right.retimed:
                    continue
                new = targets[key]
                delta = new - cut
                if left.duration + delta < MIN_CLIP * 4 or right.duration - delta < MIN_CLIP * 4:
                    continue
                ml = p.media_of(left)
                if ml and ml.kind != KIND_IMAGE and ml.duration and \
                        left.source_in + left.duration + delta > ml.duration:
                    continue  # el clip de la izquierda no tiene más material
                if right.source_in + delta < 0 and not self._is_image(p, right):
                    continue
                left.duration += delta
                right.start += delta
                right.duration -= delta
                if not self._is_image(p, right):
                    right.source_in += delta
                n += 1
            if not n:
                raise EditError("No había cortes cerca de los golpes de la música para ajustar.")
            return n

        return self._edit("IA · Cortes a ritmo de la música", fn)

    # ------------------------------------------------- proteger una parte
    def lock_range(self, a: float, b: float, label: str = "🔒 No modificar", marker_id: str | None = None):
        """Protege un tramo: bloquea todo lo que hay en él y lo indica con un marcador
        (si la orden vino de un marcador, se marca ese mismo con 🔒)."""
        def fn(p: Project):
            n = 0
            for c in p.clips.values():
                if c.start < b and c.end > a and not c.locked:
                    c.locked = True
                    n += 1
            existing = next((m for m in p.markers if m.id == marker_id), None)
            if existing is not None:
                if not existing.label.startswith("🔒"):
                    existing.label = "🔒 " + existing.label
                existing.color, existing.end = "#d9a400", b
            else:
                p.markers.append(Marker(new_id(), a, label, "#d9a400", end=b))
            p.markers.sort(key=lambda m: m.time)
            return n

        return self._edit("Proteger una parte", fn)

    # ------------------------------------------------- audio del clip (EQ, balance)
    MERGE_EQ = 104

    def set_clip_audio(self, clip_ids: list[str], text: str = "Ecualizador", **props):
        """Cambia eq/pan/volumen de clips. Cambios seguidos (arrastrar un punto) = un solo paso."""
        def fn(p: Project):
            for cid in clip_ids:
                c = p.clips.get(cid)
                if c is None:
                    continue
                self._check_clip(p, c)
                for k, v in props.items():
                    setattr(c, k, v)

        return self._edit(text, fn, merge_id=self.MERGE_EQ)

    def batch_clip_props(self, changes: dict[str, dict], text: str) -> int:
        """Cambia propiedades de muchos clips en un solo paso de deshacer: {id_clip: {prop: valor}}.
        Los clips bloqueados (o en pistas bloqueadas) se saltan."""
        def fn(p: Project):
            n = 0
            for cid, props in changes.items():
                c = p.clips.get(cid)
                tr = p.track(c.track_id) if c else None
                if c is None or c.locked or (tr and tr.locked):
                    continue
                for k, v in props.items():
                    setattr(c, k, v)
                n += 1
            return n

        return self._edit(text, fn) or 0

    # ------------------------------------------------- edit musical
    def _edit_layout(self, p: Project, m, v1_id: str, layout: str):
        from . import transform
        if layout == "mirror":
            lay = dict(transform.MIRROR)
        elif layout == "mirrorflip":
            lay = dict(transform.MIRROR_FLIP)
        elif layout == "blur":
            lay = dict(transform.BLURFILL)
        elif layout == "none":
            lay = None
        else:
            lay = self._edit_auto_layout(p, m, v1_id)
        if lay is not None and m.width and m.height and m.width / m.height <= (p.width / p.height) * 1.15:
            lay = None   # clip vertical: llena la pantalla
        return lay

    def _plan_clip(self, p: Project, it: dict, base: float, v1_id: str, layout: str, game_volume: float):
        """Un plano del plan → Clip (sin añadirlo todavía)."""
        m = p.media.get(it["media_id"])
        if m is None:
            return None, None
        start = base + it["start"]
        src = 0.0 if m.kind == KIND_IMAGE else it["source_in"]
        zt = src if m.kind != KIND_IMAGE else 0.0
        sp = 1.0 if m.kind == KIND_IMAGE else float(it.get("speed", 1.0))
        kf = [{"t": round(zt + zk[0] * (sp if sp > 0 else 1.0), 4), "z": zk[1],
               "x": float(zk[3]) if len(zk) > 3 else 0.5, "y": 0.5,      # (4.º valor: deslizar a un lado)
               **({"i": "linear"} if zk[2] else {})} for zk in it.get("zoom", [])]
        c = Clip(new_id(), m.id, v1_id, start, src, it["duration"], origin=ORIGIN_AI,
                 volume=game_volume, zoom_kf=kf, layout=self._edit_layout(p, m, v1_id, layout),
                 fx=it.get("fx") or None, speed=sp, smooth=bool(it.get("smooth")),
                 color=dict(it["color"]) if it.get("color") else None)
        if it.get("trans"):
            from . import transitions
            tt = dict(it["trans"])
            t_base = float(tt.get("dur", 0.5))     # (¡no «base»: esa es dónde empieza el edit!)
            tt.update(dur=round(min(transitions.MAX_DUR, max(transitions.MIN_DUR,
                                                             t_base * transitions.ai_scale())), 3),
                      ai=True, base=t_base)
            c.fx = dict(c.fx or {}, trans=tt)
        return c, m

    @staticmethod
    def _plan_fp(plan: dict) -> dict | None:
        try:
            from ..ai import edit_feedback
            return edit_feedback.fingerprint(edit_feedback.shots_from_plan(plan), plan.get("sections") or [],
                                             plan.get("period") or 0.5)
        except (KeyError, TypeError, ValueError):
            return None

    def use_dialogue(self, clip_ids, voice_media: dict[str, str]) -> int:
        """🗣 Los clips de sonido (de los elegidos y sus vinculados) pasan a sonar SOLO con los diálogos
        (mismo tiempo del archivo, otro archivo). voice_media = {archivo original: archivo de diálogos}."""
        def fn(p: Project):
            n = 0
            for cid in self.linked_ids(clip_ids):
                c = p.clips.get(cid)
                tr = p.track(c.track_id) if c else None
                if c is None or tr is None or tr.kind != TRACK_AUDIO or c.media_id not in voice_media:
                    continue
                self._check_clip(p, c)
                c.fx = dict(c.fx or {}, orig_media=c.media_id)
                c.media_id = voice_media[c.media_id]
                n += 1
            if not n:
                raise EditError("Esos clips no tienen sonido aparte (sepáralo antes a una pista de audio).")
            return n

        return self._edit("🗣 Solo los diálogos", fn)

    def restore_dialogue(self, clip_ids) -> int:
        """Vuelve al sonido original (con el ruido de fondo)."""
        def fn(p: Project):
            n = 0
            for cid in self.linked_ids(clip_ids):
                c = p.clips.get(cid)
                orig = (c.fx or {}).get("orig_media") if c else None
                if orig and orig in p.media:
                    c.media_id = orig
                    c.fx = {k: v for k, v in c.fx.items() if k != "orig_media"} or None
                    n += 1
            return n

        return self._edit("Sonido original", fn)

    def apply_edit_plan(self, plan: dict, layout: str = "auto", game_volume: float = 0.0,
                        ctx: dict | None = None, replace: str | None = None) -> list[str]:
        """Coloca un edit musical (ver ai/edit_maker.py) al final de la timeline, en un solo paso
        de deshacer: la canción en la pista de música, los planos en V1 con sus efectos y zooms,
        las frases de la intro y un marcador en el drop. Todo queda editable.
        El proyecto recuerda cómo se hizo (para 👍/👎, 🔀 Remix y 🎛 Mix). replace = id de un edit que se
        rehace entero en su sitio (🔀 Remix)."""
        fp = self._plan_fp(plan)

        def fn(p: Project):
            old = next((e for e in p.edits if e["id"] == replace), None) if replace else None
            if replace and old is None:
                raise EditError("Ese edit ya no está en la línea de tiempo.")
            if old is not None:      # 🔀 Remix: se quita la versión anterior (planos, textos, canción y marcador)
                for cid in old.get("clip_ids", []) + old.get("text_ids", []) + [old.get("music_id")]:
                    if cid in p.clips and not p.clips[cid].locked:
                        del p.clips[cid]
                p.markers = [mk for mk in p.markers if mk.id != old.get("marker_id")]
                base = float(old["base"])
            else:
                base = p.duration()
            vtracks = [t for t in p.tracks if t.kind == TRACK_VIDEO]
            atracks = [t for t in p.tracks if t.kind == TRACK_AUDIO]
            if not vtracks or not atracks:
                raise EditError("Hacen falta una pista de video y una de audio.")
            v1 = vtracks[-1]
            music_tr = p.track(self._role_track(p, "musica", create=True))
            for tr in (v1, music_tr):
                self._check_track(p, tr.id)
            created, vids, texts = [], [], []
            mu = plan["music"]
            mm = p.media.get(mu["media_id"])
            if mm is None:
                raise EditError("No se encuentra la canción en el panel de medios.")
            self._clear_range(p, music_tr.id, base, base + mu["duration"])
            c = Clip(new_id(), mm.id, music_tr.id, base, mu["source_in"], mu["duration"], origin=ORIGIN_AI,
                     note="🎵 Edit", fx={"fade_out": mu["fade_out"]} if mu.get("fade_out") else None)
            p.clips[c.id] = c
            created.append(c.id)
            music_id = c.id
            for it in plan["clips"]:
                c, m = self._plan_clip(p, it, base, v1.id, layout, game_volume)
                if c is None:
                    continue
                self._clear_range(p, v1.id, c.start, c.end)
                p.clips[c.id] = c
                created.append(c.id)
                vids.append(c.id)
                if game_volume > 0:
                    ac = self._link_audio(p, c, m, game_volume, (ctx or {}).get("dialogue") or
                                          (old or {}).get("dialogue"))
                    if ac:
                        created.append(ac)
                        vids.append(ac)
            for tx in plan.get("texts", []):
                tid = self._put_text(p, base + tx["start"], tx["duration"], tx["content"], ORIGIN_AI,
                                     **tx.get("style", {}))
                created.append(tid)
                texts.append(tid)
            marker_id = None
            if plan.get("drop") is not None:
                mk = Marker(new_id(), base + plan["drop"], "💥 Drop", "#e5413c", origin=ORIGIN_AI)
                p.markers.append(mk)
                marker_id = mk.id
            rec = {"id": old["id"] if old else new_id(), "style": plan.get("style") or "halo", "base": round(base, 4),
                   "duration": round(float(mu["duration"]), 4), "sections": plan.get("sections") or [],
                   "period": plan.get("period") or 0.5, "window": plan.get("window"),
                   "song_id": mm.id, "clip_ids": vids, "text_ids": texts, "music_id": music_id,
                   "marker_id": marker_id, "layout": layout, "game_volume": game_volume,
                   "dialogue": dict((ctx or {}).get("dialogue") or (old or {}).get("dialogue") or {}),
                   "options": dict((ctx or {}).get("options") or (old or {}).get("options") or {}),
                   "sources": list((ctx or {}).get("sources") or (old or {}).get("sources") or []),
                   "ai_fp": fp, "version": (old.get("version", 1) + 1) if old else 1,
                   "remix": plan.get("remix") or [], "rating": None,
                   "avoid": list((old or {}).get("avoid") or [])}      # 👎 planos vetados: siguen vetados
            if old is not None:
                p.edits[p.edits.index(old)] = rec
            else:
                p.edits.append(rec)
            return created

        res = self._edit("🔀 Remix del edit" if replace else "Edit musical", fn)
        if fp is not None and plan.get("style") and plan.get("style") != "halo" and isinstance(res, list):
            try:
                from ..ai import edit_feedback
                edit_feedback.note_created(plan["style"], fp)
            except OSError:
                pass
        return res

    # ------------------------------------------------- ⊞ composición (huecos en pantalla + fondo)
    def _comp_track(self, p: Project, background: bool, a: float, b: float) -> str:
        """Una pista «⊞ Composición» libre en [a, b) (encima de todo) o «⊞ Fondo» (debajo de la imagen
        principal). Pistas propias: no se mezclan con tu línea de tiempo principal."""
        role = "fondo" if background else "comp"
        for t in p.tracks:
            if t.kind == TRACK_VIDEO and t.role == role and not t.locked and \
                    not any(c.start < b - EPS and c.end > a + EPS for c in p.clips_on(t.id)):
                return t.id
        n = sum(1 for t in p.tracks if t.role == role) + 1
        tr = Track(new_id(), TRACK_VIDEO, ("⊞ Fondo" if background else "⊞ Composición") + (f" {n}" if n > 1 else ""))
        tr.role = role
        vidx = [i for i, t in enumerate(p.tracks) if t.kind == TRACK_VIDEO]
        if background:
            p.tracks.insert((vidx[-1] + 1) if vidx else 0, tr)
        else:
            p.tracks.insert(vidx[0] if vidx else 0, tr)
        return tr.id

    def place_composition(self, media_ids, box: dict | None, start: float) -> list[str]:
        """Pone archivos en un hueco de la composición (box en fracciones) o, sin box, de fondo, desde start.
        Dura lo que el plano principal que hay ahí (o 5 s / lo que dure el video). Un paso de deshacer."""
        def fn(p: Project):
            made = []
            t = max(0.0, start)
            main = next((c for tr in reversed([x for x in p.tracks if x.kind == TRACK_VIDEO and x.role not in
                                               ("comp", "fondo")])
                         for c in [p.clip_at(tr.id, t)] if c is not None), None)
            for mid in media_ids:
                m = p.media.get(mid)
                if m is None or m.kind == KIND_AUDIO:
                    continue
                if m.kind != KIND_IMAGE and m.duration <= 0:
                    raise EditError(f"Todavía se está analizando «{m.name}». Prueba en un momento.")
                dur = (main.end - t) if main is not None and main.end - t > 0.5 else DEFAULT_IMAGE_DURATION
                if m.kind != KIND_IMAGE:
                    dur = min(dur, m.duration) if main is not None else m.duration
                tid = self._comp_track(p, box is None, t, t + dur)
                lay = dict(box) if box is not None else {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "cover"}
                c = Clip(new_id(), mid, tid, t, 0.0, dur, layout=lay)
                p.clips[c.id] = c
                made.append(c.id)
                t += dur
            if not made:
                raise EditError("Arrastra una imagen, un video o un GIF (el sonido va en la línea de tiempo).")
            return made

        res = self._edit("⊞ Composición", fn)
        return res if isinstance(res, list) else []

    # ------------------------------------------------- ⧉ clips compuestos
    def make_compound(self, clip_ids, media_id: str, a: float, b: float) -> str | None:
        """Sustituye los clips (y sus vinculados) por el video ya cocinado, en el mismo sitio. Guarda los
        originales para poder deshacerlo («Deshacer clip compuesto»). Un paso de deshacer."""
        from dataclasses import asdict
        from . import compound as CP

        def fn(p: Project):
            ids = CP.with_partners(p, clip_ids)
            olds = [p.clips[i] for i in ids]
            for c in olds:
                self._check_clip(p, c)
            vt = [p.track(c.track_id) for c in olds if p.track(c.track_id) and p.track(c.track_id).kind == TRACK_VIDEO]
            if vt:      # en la pista de video más baja de las elegidas
                tr = max(vt, key=lambda t: p.track_index(t.id))
            else:
                tr = next(t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO)
            p.compounds[media_id] = {"a": round(a, 4), "clips": [asdict(c) for c in olds]}
            for c in olds:
                del p.clips[c.id]
            m = p.media[media_id]
            self._clear_range(p, tr.id, a, b)
            c = Clip(new_id(), media_id, tr.id, a, 0.0, b - a, note="⧉ Clip compuesto")
            p.clips[c.id] = c
            self._link_audio(p, c, m)
            return c.id

        res = self._edit("⧉ Clip compuesto", fn)
        return res if isinstance(res, str) else None

    def is_compound(self, clip_id: str) -> bool:
        c = self.project.clips.get(clip_id)
        return c is not None and c.media_id in self.project.compounds

    def break_compound(self, clip_id: str) -> list[str]:
        """Devuelve los clips originales en su sitio (movidos si moviste el compuesto)."""
        def fn(p: Project):
            c = p.clips.get(clip_id)
            rec = p.compounds.get(c.media_id) if c else None
            if rec is None:
                raise EditError("Ese clip no es un clip compuesto.")
            shift = c.start - float(rec["a"])
            for o in self.partners(p, c) + [c]:
                p.clips.pop(o.id, None)
            from .model import _build
            back = []
            for d in rec["clips"]:
                o = _build(Clip, d)
                if p.track(o.track_id) is None:
                    continue
                if o.id in p.clips:
                    o.id = new_id()
                o.start = round(o.start + shift, 4)
                p.clips[o.id] = o
                back.append(o.id)
            return back

        res = self._edit("⧉ Deshacer clip compuesto", fn)
        return res if isinstance(res, list) else []

    def edit_at(self, t: float) -> dict | None:
        """El edit que ocupa el instante t de la línea de tiempo (o el último, si no hay ninguno ahí)."""
        p = self.project
        for e in reversed(p.edits):
            if e["base"] - 1e-3 <= t < e["base"] + e["duration"]:
                return e
        return p.edits[-1] if p.edits else None

    def edit_clips(self, rec: dict) -> list:
        """Los planos (video) que hay AHORA en la línea de tiempo dentro de ese edit (incluidos tus cambios)."""
        p = self.project
        tr = next((t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO), None)
        if tr is None:
            return []
        a, b = rec["base"], rec["base"] + rec["duration"]
        known = set(rec.get("clip_ids", []))
        return [c for c in p.clips_on(tr.id) if c.text is None and (c.id in known or (c.start >= a - 1e-3 and
                                                                                          c.end <= b + 1e-3))]

    def ban_edit_clips(self, edit_id: str, clip_ids) -> int:
        """👎 de planos: esos momentos de los videos ya no vuelven a salir en los edits de este proyecto
        (🔀 Remix, 🎛 Mix ni edits nuevos). Es un paso de deshacer: Ctrl+Z los vuelve a permitir."""
        p = self.project
        ranges = []
        for i in clip_ids:
            c = p.clips.get(i)
            m = p.media_of(c) if c is not None and c.text is None else None
            if m is None or m.kind == "audio":
                continue
            a = float(c.source_in)
            ranges.append([c.media_id, round(a, 3), round(a + max(0.1, float(c.src_len)), 3)])
        if not ranges:
            return 0

        def fn(p: Project):
            rec = next((e for e in p.edits if e["id"] == edit_id), None)
            if rec is None:
                raise EditError("Ese edit ya no está en la línea de tiempo.")
            have = {tuple(r) for r in rec.get("avoid") or []}
            rec["avoid"] = list(rec.get("avoid") or []) + [r for r in ranges if tuple(r) not in have]
            return len(ranges)

        return self._edit("👎 Planos que no quiero", fn)

    def ban_edit_slot(self, edit_id: str, clip_ids) -> int:
        """⛔ «Aquí no»: esos planos ya no se sugieren EN ESE TRAMO del edit (en otras partes sí pueden salir; para no
        verlos nunca más está 👎). Se guarda el tramo de la línea de tiempo y el momento del video. Un paso de deshacer:
        Ctrl+Z los vuelve a permitir ahí."""
        p = self.project
        entries = []
        for i in clip_ids:
            c = p.clips.get(i)
            m = p.media_of(c) if c is not None and c.text is None else None
            if m is None or m.kind == "audio":
                continue
            a = float(c.source_in)
            entries.append([round(c.start, 3), round(c.end, 3), c.media_id, round(a, 3),
                            round(a + max(0.1, float(c.src_len)), 3)])
        if not entries:
            return 0

        def fn(p: Project):
            rec = next((e for e in p.edits if e["id"] == edit_id), None)
            if rec is None:
                raise EditError("Ese edit ya no está en la línea de tiempo.")
            have = {tuple(r) for r in rec.get("slot_avoid") or []}
            rec["slot_avoid"] = list(rec.get("slot_avoid") or []) + [r for r in entries if tuple(r) not in have]
            return len(entries)

        return self._edit("⛔ Este plano aquí no", fn)

    def edit_slot_avoid(self, edit_id: str, a: float, b: float) -> dict:
        """Los planos que no van en [a, b) de ese edit (⛔ «Aquí no»): {media_id: [(desde, hasta), …]}."""
        out: dict[str, list] = {}
        rec = next((e for e in self.project.edits if e["id"] == edit_id), None)
        for sa, sb, mid, x, y in (rec or {}).get("slot_avoid") or []:
            if float(sb) > a + 1e-3 and float(sa) < b - 1e-3:
                out.setdefault(mid, []).append((float(x), float(y)))
        return out

    def edit_avoid(self) -> dict:
        """Los momentos vetados con 👎 en este proyecto: {media_id: [(desde, hasta), …]} (tiempo del video)."""
        out: dict[str, list] = {}
        for e in self.project.edits:
            for mid, a, b in e.get("avoid") or []:
                out.setdefault(mid, []).append((float(a), float(b)))
        return out

    def edit_fingerprint(self, rec: dict) -> dict | None:
        from ..ai import edit_feedback
        clips = self.edit_clips(rec)
        if not clips:
            return None
        return edit_feedback.fingerprint(edit_feedback.shots_from_clips(clips, rec["base"]), rec.get("sections") or [],
                                         rec.get("period") or 0.5)

    def mix_edit_range(self, edit_id: str, a: float, b: float, plan: dict) -> list[str]:
        """🎛 Mix: rehace SOLO el tramo [a, b) de un edit con los planos de otra versión (misma canción y mismo
        sitio; a y b son cortes, así que todo sigue en el ritmo). Un paso de deshacer."""
        def fn(p: Project):
            rec = next((e for e in p.edits if e["id"] == edit_id), None)
            if rec is None:
                raise EditError("Ese edit ya no está en la línea de tiempo.")
            base = float(rec["base"])
            v1 = next(t for t in reversed(p.tracks) if t.kind == TRACK_VIDEO)
            self._check_track(p, v1.id)
            olds = [c for c in p.clips_on(v1.id) if c.end > a + EPS and c.start < b - EPS]
            partner_tracks = {o.track_id for c in olds for o in self.partners(p, c)}
            self._clear_range(p, v1.id, a, b)
            for tid in partner_tracks:        # el sonido del juego de esos planos, también
                self._clear_range(p, tid, a, b)
            made = []
            for it in plan["clips"]:
                s, e = base + it["start"], base + it["start"] + it["duration"]
                if e <= a + EPS or s >= b - EPS:
                    continue
                c, m = self._plan_clip(p, it, base, v1.id, rec.get("layout", "auto"), rec.get("game_volume", 0.0))
                if c is None:
                    continue
                if c.start < a:               # recortado al tramo (los bordes son cortes: siguen en el golpe)
                    cut = a - c.start
                    if not self._is_image(p, c):
                        c.source_in = c.piece_src(cut, c.duration)
                    c.start, c.duration = a, c.duration - cut
                    c.zoom_kf = []
                    c.fx = {k: v for k, v in (c.fx or {}).items() if k != "trans"} or None
                if c.end > b:
                    c.duration = b - c.start
                if c.duration < 0.04:
                    continue
                p.clips[c.id] = c
                made.append(c.id)
                if rec.get("game_volume", 0.0) > 0:
                    ac = self._link_audio(p, c, m, rec["game_volume"], rec.get("dialogue"))
                    if ac:
                        made.append(ac)
            if not made:
                raise EditError("No salió nada nuevo para ese tramo. Prueba con un tramo más largo.")
            keep_ids = [cid for cid in rec.get("clip_ids", []) if cid in p.clips]
            rec["clip_ids"] = keep_ids + made
            rec["mixes"] = rec.get("mixes", 0) + 1
            return made

        return self._edit("🎛 Mix de un tramo del edit", fn)

    # ------------------------------------------------- textos en pantalla
    def _text_track(self, p: Project, start: float, end: float) -> str:
        """Una pista de textos libre en [start, end). Si todas están ocupadas (o bloqueadas) se crea
        otra arriba del todo: así puede haber varios textos a la vez (p. ej. ORIGINAL y REMAKE)."""
        for t in p.tracks:
            if t.kind == TRACK_TEXT and not t.locked and \
                    not any(c.start < end - EPS and c.end > start + EPS for c in p.clips_on(t.id)):
                return t.id
        n = sum(1 for t in p.tracks if t.kind == TRACK_TEXT) + 1
        tr = Track(new_id(), TRACK_TEXT, "T · Textos" if n == 1 else f"T{n} · Textos")
        p.tracks.insert(0, tr)
        return tr.id

    def _put_text(self, p: Project, start: float, duration: float, content: str, origin: str, **style) -> str:
        tid = self._text_track(p, start, start + duration)
        base = dict(TEXT_DEFAULTS)
        if p.height > p.width:   # vertical (Short o edit)
            base.update(y=0.29, size=3.8, box=False)
        if origin == ORIGIN_USER:   # tus valores recordados (Inspector → texto → «Recordar mis valores»)
            from .title_render import my_style, remembering
            if remembering():
                base.update(my_style())
        text = dict(base, content=content, **style)
        if origin == ORIGIN_USER and "blur_under" not in style and "blur_under" not in base:
            from .title_render import BLUR_UNDER_DEFAULT
            text["blur_under"] = BLUR_UNDER_DEFAULT     # lo de debajo se desenfoca (se quita en el Inspector)
        c = Clip(new_id(), "", tid, max(0.0, start), 0.0, max(0.3, duration), origin=origin, text=text)
        p.clips[c.id] = c
        return c.id

    def add_text(self, start: float, duration: float = 4.0, content: str = "Texto", origin: str = ORIGIN_USER,
                 **style):
        return self._edit("Añadir texto", lambda p: self._put_text(p, start, duration, content, origin, **style))

    # ------------------------------------------------- 🟦 generadores y 🎨 capas de ajuste
    def generator_media(self, gen: dict) -> str:
        """El medio (en la biblioteca, categoría «Generadores») de ese generador; se crea si hace falta."""
        from . import generators
        gen = generators.clean(gen)
        p = self.project
        for m in p.media.values():
            if m.gen == gen and m.width and os.path.exists(m.path):
                return m.id
        path = generators.make(gen, p.width, p.height)
        w, h = generators._size(gen, p.width, p.height)
        m = MediaItem(id=new_id(), path=path, kind=KIND_IMAGE, name=generators.name_of(gen), category="Generadores",
                      width=w, height=h, probed=True, gen=gen)
        p.media[m.id] = m
        self._analyze(m)
        self._set_media_dirty()
        self.media_changed.emit()
        return m.id

    def add_generator(self, gen: dict, start: float, duration: float = 5.0, track_id: str | None = None):
        """🟦 Color sólido / degradado o 🎨 capa de ajuste en el cabezal, en la pista de video de ARRIBA que esté
        libre (si no hay, una nueva encima de todo): así afecta (o tapa) a lo que hay debajo."""
        from . import generators, transform
        mid = self.generator_media(gen)
        adjust = generators.is_adjust(self.project.media[mid])

        def fn(p: Project):
            a, b = max(0.0, start), max(0.0, start) + max(0.1, duration)
            vt = [t for t in p.tracks if t.kind == TRACK_VIDEO]
            if not vt:
                raise EditError("No hay pistas de video.")
            pref = track_id if track_id and p.track(track_id) else vt[0].id
            tid = self._free_track(p, TRACK_VIDEO, pref, a, b)
            lay = dict(transform.FULL, fit="stretch", bg="none") if adjust else None
            c = Clip(new_id(), mid, tid, a, 0.0, b - a, volume=0.0, layout=lay)
            p.clips[c.id] = c
            return c.id

        return self._edit("🎨 Añadir capa de ajuste" if adjust else "🟦 Añadir generador", fn)

    def set_generator(self, clip_ids: list[str], gen: dict):
        """Cambia el color / degradado de esos clips (un solo paso de Ctrl+Z)."""
        mid = self.generator_media(gen)

        def fn(p: Project):
            for cid in clip_ids:
                c = p.clips.get(cid)
                m = p.media_of(c) if c else None
                if c is None or not (m and m.gen) or m.gen.get("kind") == "adjust":
                    continue
                self._check_clip(p, c)
                c.media_id = mid

        return self._edit("🟦 Cambiar generador", fn)

    def set_text_props(self, clip_id: str, **props):
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None or c.text is None:
                return
            self._check_clip(p, c)
            c.text = dict(c.text, **props)

        return self._edit("Editar texto", fn, merge_id=self.MERGE_TEXT)

    MERGE_TEXT = 103

    def add_comparison(self, media_a: str, src_a: float, media_b: str, src_b: float, start: float,
                       duration: float, labels: tuple[str, str] = ("", ""),
                       origin: str = ORIGIN_USER):
        """Comparación: A a la izquierda, B a la derecha, con su etiqueta encima de cada uno."""
        from . import transform

        def fn(p: Project):
            vtracks = [t for t in p.tracks if t.kind == TRACK_VIDEO]
            while len(vtracks) < 2:  # hacen falta dos pistas de video
                n = len(vtracks) + 1
                tr = Track(new_id(), TRACK_VIDEO, f"V{n}")
                p.tracks.insert(next(i for i, t in enumerate(p.tracks) if t.kind == TRACK_VIDEO), tr)
                vtracks = [t for t in p.tracks if t.kind == TRACK_VIDEO]
            low, high = vtracks[-1], vtracks[-2]
            ids = []
            short = p.height > p.width   # vertical: arriba y abajo
            for tr, mid, src, layout in ((low, media_a, src_a, "Mitad superior" if short else "Mitad izquierda"),
                                         (high, media_b, src_b, "Mitad inferior" if short else "Mitad derecha")):
                self._check_track(p, tr.id)
                m = p.media.get(mid)
                if m is None:
                    raise EditError("Falta uno de los dos clips de la comparación.")
                dur = duration if m.kind == KIND_IMAGE else min(duration, max(0.5, m.duration - src))
                self._clear_range(p, tr.id, start, start + dur)
                c = Clip(new_id(), mid, tr.id, start, 0.0 if m.kind == KIND_IMAGE else src, dur, volume=0.0,
                         origin=origin, layout=dict(transform.LAYOUTS[layout]))
                p.clips[c.id] = c
                ids.append(c.id)
            spots = ((0.5, 0.05), (0.5, 0.55)) if short else ((0.25, 0.08), (0.75, 0.08))
            for label, (x, y) in zip(labels, spots):
                if label:
                    ids.append(self._put_text(p, start, duration, label, origin, x=x, y=y,
                                              size=3.6 if short else 5.0, box=True))
            return ids

        return self._edit("Comparación", fn)

    # ------------------------------------------------- encuadre (zoom y disposición)
    MERGE_FRAMING = 102
    MERGE_COLOR = 103
    MERGE_CURVE = 104

    def set_curve(self, clip_id: str, kind: str, kf: list[dict] | None = None, level: float | None = None,
                  text: str | None = None):
        """Curva de volumen («vol») u opacidad («op»): kf = puntos nuevos; level = nivel de toda la línea
        (Clip.volume / Clip.opacity). Arrastrar = un solo paso de deshacer."""
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            group = [c] + ([o for o in self.partners(p, c) if p.track(o.track_id).kind == p.track(c.track_id).kind]
                           if kind == "op" else [])
            for x in group:
                self._check_clip(p, x)
                if kf is not None:
                    setattr(x, "vol_kf" if kind == "vol" else "op_kf", [dict(k) for k in kf])
                if level is not None:
                    if kind == "vol":
                        x.volume = max(0.0, min(2.0, level))
                    else:
                        x.opacity = max(0.0, min(1.0, level))

        label = text or ("Curva de volumen" if kind == "vol" else "Curva de opacidad")
        return self._edit(label, fn, merge_id=self.MERGE_CURVE)

    def set_color(self, clip_ids: list[str], color: dict | None, text: str = "Color"):
        """Corrección de color de los clips de imagen/video (los cambios seguidos de un control se juntan en
        un solo paso de deshacer)."""
        from . import color as C

        def fn(p: Project):
            n = 0
            for cid in clip_ids:
                c = p.clips.get(cid)
                tr = p.track(c.track_id) if c else None
                if c is None or c.text is not None or tr is None or tr.kind != TRACK_VIDEO:
                    continue
                self._check_clip(p, c)
                c.color = None if (color is None or C.is_neutral(color)) else dict(color)
                n += 1
            if not n:
                raise EditError("Selecciona un clip de video o imagen.")

        return self._edit(text, fn, merge_id=self.MERGE_COLOR)

    def frame_at(self, clip_id: str, t: float, width: int = 480):
        """El fotograma que muestra el clip en el instante t de la timeline (RGB, sin corregir)."""
        c = self.project.clips[clip_id]
        m = self.project.media_of(c)
        if m is None:
            return None
        if m.kind == KIND_IMAGE:
            import cv2
            img = cv2.imdecode(np.fromfile(m.path, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return None
            k = width / img.shape[1]
            img = cv2.resize(img, (width, max(2, int(img.shape[0] * k))))
            return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return media_tools.frame_rgb(m.path, self.clip_source_time(clip_id, t), width)

    def auto_color(self, clip_ids: list[str], t: float):
        """✨ Color automático: corrige exposición, contraste y balance de blancos mirando el fotograma del
        cabezal (del primer clip) y lo aplica a los elegidos."""
        from . import color as C
        if not clip_ids:
            raise EditError("Selecciona un clip de video o imagen.")
        c0 = self.project.clips.get(clip_ids[0])
        if c0 is None:
            raise EditError("Selecciona un clip de video o imagen.")
        t = min(max(t, c0.start), c0.end - 0.01)
        frame = self.frame_at(c0.id, t)
        if frame is None:
            raise EditError("No se pudo leer la imagen del clip.")
        auto = C.auto(frame)
        keep = {k: v for k, v in (c0.color or {}).items() if k in ("lut", "lut_mix")}
        return self.set_color(clip_ids, {**auto, **keep}, "Color automático")

    def clip_source_time(self, clip_id: str, t: float) -> float:
        """Segundo del archivo original que se ve en el momento t de la timeline."""
        c = self.project.clips[clip_id]
        m = self.project.media_of(c)
        local = min(max(t, c.start), c.end) - c.start
        return local if (m and m.kind == KIND_IMAGE) else c.src_at(local)

    # ------------------------------------------------- 🎞 posición y tamaño animados (fotogramas clave)
    def layout_key_times(self, clip_id: str) -> list[float]:
        """Momentos de la línea de tiempo donde el clip tiene una clave de posición/tamaño."""
        c = self.project.clips.get(clip_id)
        if c is None or not c.layout_kf:
            return []
        img = self._is_image(self.project, c)
        out = []
        for k in c.layout_kf:
            if img:
                local = k["t"]
            elif c.speed <= 0:
                continue
            elif c.reverse:
                local = (c.source_in + c.src_len - k["t"]) / c.speed
            else:
                local = (k["t"] - c.source_in) / c.speed
            if -1e-3 <= local <= c.duration + 1e-3:
                out.append(round(c.start + local, 4))
        return sorted(out)

    def set_layout_key(self, clip_id: str, t: float, box: dict, text: str = "Clave de posición y tamaño"):
        """Crea o cambia la clave de posición/tamaño del momento t (la animación se activa con la primera)."""
        from . import transform

        def fn(p: Project):
            c = p.clips[clip_id]
            self._check_clip(p, c)
            if c.text is not None:
                raise EditError("Los textos se colocan con su propio estilo.")
            s = self.clip_source_time(clip_id, t)
            if not c.layout:                    # era pantalla completa: al encogerla se verá lo de debajo
                c.layout = dict(transform.FULL, bg="none")
            if box.get("fit") == "stretch" and c.layout.get("fit") != "stretch":     # ↔ deformado en el visor
                c.layout = {k: v for k, v in c.layout.items() if k != "flip"}
                c.layout["fit"] = "stretch"
            c.layout_kf = transform.layout_upsert(c.layout_kf, s, box)
        return self._edit(text, fn)

    def animate_layout(self, clip_id: str, t: float):
        """◆ Primera clave (o una más) con la posición y el tamaño que tiene ahora en ese momento."""
        from . import transform
        c = self.project.clips[clip_id]
        box = transform.layout_at(c, min(max(t, c.start), c.end) - c.start, self._is_image(self.project, c))
        return self.set_layout_key(clip_id, t, box or transform.FULL, "◆ Clave de posición y tamaño")

    def remove_layout_key(self, clip_id: str, t: float):
        from . import transform

        def fn(p: Project):
            c = p.clips[clip_id]
            self._check_clip(p, c)
            s = self.clip_source_time(clip_id, t)
            left = [dict(k) for k in c.layout_kf if abs(k["t"] - s) > 0.05]
            if len(left) == len(c.layout_kf):
                raise EditError("No hay una clave de posición/tamaño justo en el cabezal.")
            if not left:                        # era la última: se queda quieto donde estaba
                c.layout = transform.layout_at(c, min(max(t, c.start), c.end) - c.start,
                                               self._is_image(p, c))
            c.layout_kf = left
        return self._edit("✕ Quitar clave de posición y tamaño", fn)

    def clear_layout_animation(self, clip_id: str, t: float):
        """Quita la animación: el clip se queda con la posición y el tamaño de ese momento."""
        from . import transform

        def fn(p: Project):
            c = p.clips[clip_id]
            self._check_clip(p, c)
            if not c.layout_kf:
                raise EditError("Ese clip no tiene posición/tamaño animados.")
            c.layout = transform.layout_at(c, min(max(t, c.start), c.end) - c.start, self._is_image(p, c))
            c.layout_kf = []
        return self._edit("Quitar animación de posición y tamaño", fn)

    def set_zoom_at(self, clip_id: str, t: float, z: float, x: float, y: float, text: str = "Encuadre"):
        """Cambia el zoom en el momento t. Si el clip ya está animado, crea/cambia la clave de ese
        momento; si no, cambia el encuadre fijo de todo el clip."""
        from . import transform

        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            self._check_clip(p, c)
            src = self.clip_source_time(clip_id, t)
            if len(c.zoom_kf) >= 2:
                c.zoom_kf = transform.upsert(c.zoom_kf, src, z, x, y)
            else:
                c.zoom_kf = transform.upsert([], src, z, x, y)

        return self._edit(text, fn, merge_id=self.MERGE_FRAMING)

    def add_zoom_keyframe(self, clip_id: str, t: float):
        """Añade un fotograma clave con el encuadre actual (así se puede animar desde aquí)."""
        from . import transform

        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            self._check_clip(p, c)
            src = self.clip_source_time(clip_id, t)
            z, x, y = transform.value_at(c.zoom_kf, src)
            kf = c.zoom_kf
            if len(kf) == 1:  # el encuadre fijo pasa a ser la primera clave, al inicio del clip
                m = p.media_of(c)
                first = 0.0 if (m and m.kind == KIND_IMAGE) else c.src_at(0.0)
                kf = [dict(kf[0], t=first)] if abs(first - src) > 0.05 else kf
            c.zoom_kf = transform.upsert(kf, src, z, x, y)

        return self._edit("Añadir fotograma clave", fn)

    def apply_zoom_suggestions(self, items: list[tuple[str, str, list[dict]]]):
        """Aplica sugerencias de zoom: items = [(id_sugerencia, id_clip, claves_nuevas)]. Un solo paso."""
        from ..ai.transform_helpers import merge_window

        def fn(p: Project):
            done = 0
            for sid, cid, kf in items:
                s = next((x for x in p.suggestions if x.id == sid), None)
                c = p.clips.get(cid)
                if s is None or c is None or s.status != SUG_PENDING:
                    continue
                self._check_clip(p, c)
                c.zoom_kf = merge_window(c.zoom_kf, kf)
                s.status = SUG_APPLIED
                s.data = dict(s.data, clip_id=cid)
                done += 1
            if not done:
                raise EditError("No se pudo aplicar ningún zoom (¿no hay video en esos momentos o está bloqueado?).")
            return done

        return self._edit("IA · Zoom en momentos clave" if len(items) > 1 else "IA · Zoom", fn)

    def set_zoom_keyframes(self, clip_id: str, kf: list[dict], text: str, origin_ai: bool = False):
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            self._check_clip(p, c)
            c.zoom_kf = [dict(k) for k in kf]
            if origin_ai:
                c.note = (c.note + "\n" if c.note else "") + "Encuadre automático (IA)"

        return self._edit(text, fn)

    def remove_zoom_keyframe(self, clip_id: str, src_t: float):
        def fn(p: Project):
            c = p.clips.get(clip_id)
            if c is None:
                return
            self._check_clip(p, c)
            c.zoom_kf = [k for k in c.zoom_kf if abs(k["t"] - src_t) > 0.05]

        return self._edit("Quitar fotograma clave", fn)

    # ✨ Efectos SOLO al personaje: una copia del clip encima, recortada al sujeto (la IA lo sigue en todo el clip).
    # Lo que le pongas a la copia solo afecta al personaje; lo que le pongas al de abajo, solo al fondo.
    SUBJECT_FX = {
        "bn_fondo": "🎨 El personaje a color y el fondo en blanco y negro",
        "glow": "✨ Resplandor en el personaje",
        "vivo": "🌈 El personaje con colores más vivos",
        "oscuro_fondo": "🌑 El fondo más oscuro (el personaje destaca)",
        "blur_fondo": "🌫 El fondo desenfocado",
        "nada": "Solo la copia (yo elijo los efectos)",
    }

    def subject_layer(self, clip_id: str, sm: dict, preset: str = "nada") -> str | None:
        """Copia del clip en la pista de video de ENCIMA (libre; si no hay, una nueva justo encima), con el recorte
        del sujeto, sin sonido ni transición; y el efecto elegido (en la copia o en el original). Un paso de Ctrl+Z."""
        from dataclasses import replace as _rep

        def fn(p: Project):
            c = p.clips[clip_id]
            self._check_clip(p, c)
            i = p.track_index(c.track_id)
            above = [t for t in p.tracks[:i] if t.kind == TRACK_VIDEO]
            tid = None
            for t in reversed(above):              # la más cercana por encima que esté libre
                if not t.locked and not any(o.start < c.end - EPS and o.end > c.start + EPS for o in p.clips_on(t.id)):
                    tid = t.id
                    break
            if tid is None:
                n = sum(1 for t in p.tracks if t.kind == TRACK_VIDEO) + 1
                nt = Track(new_id(), TRACK_VIDEO, f"V{n}")
                p.tracks.insert(i, nt)
                tid = nt.id
            fx = {k: v for k, v in (c.fx or {}).items() if k not in ("trans", "subject_mask")}
            fx["subject_mask"] = dict(sm, invert=False)
            cp = _rep(c, id=new_id(), track_id=tid, link="", volume=0.0, fx=fx, note="✨ Solo el personaje",
                      zoom_kf=[dict(k) for k in c.zoom_kf], layout=dict(c.layout) if c.layout else None,
                      layout_kf=[dict(k) for k in c.layout_kf], vol_kf=[], op_kf=[dict(k) for k in c.op_kf])
            base = dict(c.fx or {})
            if preset == "bn_fondo":
                base["bw"] = True
            elif preset == "blur_fondo":
                base["blur"] = max(0.5, float(base.get("blur", 0) or 0))
            elif preset == "oscuro_fondo":
                c.color = dict(c.color or {}, exposure=round(float((c.color or {}).get("exposure", 0)) - 0.35, 3))
            elif preset == "glow":
                cp.fx["glow"] = 0.55
            elif preset == "vivo":
                cp.fx["punchy"] = 0.6
                cp.color = dict(cp.color or {}, saturation=round(float((cp.color or {}).get("saturation", 0)) + 0.3, 3))
            if preset in ("bn_fondo", "blur_fondo"):
                c.fx = base
            p.clips[cp.id] = cp
            return cp.id
        return self._edit("✨ Efecto solo al personaje", fn)

    MERGE_TRANSFORM = 107

    def set_clip_layout(self, clip_id: str, box: dict | None, t: float | None = None, text: str = "⤧ Transformar"):
        """⤧ La caja del clip desde el Inspector (tamaño, posición, giro, voltear). Con claves de posición/tamaño,
        cambia la clave de ese momento (lo demás —giro, voltear, deformado— va en la disposición del clip).
        Varios cambios seguidos = un paso de Ctrl+Z."""
        from . import transform

        def fn(p: Project):
            c = p.clips[clip_id]
            self._check_clip(p, c)
            if c.layout_kf and t is not None and box:
                s = self.clip_source_time(clip_id, t)
                base = dict(c.layout or transform.FULL)
                base.update({k: v for k, v in box.items() if k not in transform.LAYOUT_KEYS})
                c.layout = base
                c.layout_kf = transform.layout_upsert(c.layout_kf, s, box)
            else:
                c.layout = dict(box) if box else None
        return self._edit(text, fn, merge_id=self.MERGE_TRANSFORM)

    def set_fill(self, clip_ids: list[str], params: dict | None, text: str = "▦ Relleno"):
        """▦ Relleno (fondo con la propia imagen, desenfocada) en esos clips; None = quitarlo. Lo de alrededor del clip
        pasa a ser transparente para que se vea el relleno."""
        from . import transform

        def fn(p: Project):
            for cid in clip_ids:
                c = p.clips.get(cid)
                if c is None or c.text is not None or p.track(c.track_id).kind != TRACK_VIDEO:
                    continue
                self._check_clip(p, c)
                fx = dict(c.fx or {})
                if params:
                    fx["relleno"] = {k: round(float(v), 3) for k, v in params.items()}
                    lay = dict(c.layout or transform.FULL)
                    if lay.get("fit") in ("blurfill", "mirrorfill"):
                        lay["fit"] = "contain"
                    lay["bg"] = "none"
                    c.layout = lay
                else:
                    fx.pop("relleno", None)
                c.fx = fx or None
        return self._edit(text, fn)

    def set_follow(self, clip_id: str, kf: list[dict] | None, text: str = "🎯 Encuadre que sigue la acción"):
        """🎯 El recorte vertical sigue la acción (kf = [{"t", "x"}] en segundos del archivo); None = quitarlo
        (vuelve al recorte centrado). El clip pasa a llenar la pantalla recortando los lados («cover»)."""
        from . import transform

        def fn(p: Project):
            c = p.clips[clip_id]
            self._check_clip(p, c)
            if kf:
                lay = {k: v for k, v in (c.layout or transform.FULL).items() if k not in ("flip",)}
                lay.update(fit="cover", follow=[dict(k) for k in kf])
                lay.pop("bg", None)
                c.layout = lay
            elif c.layout and "follow" in c.layout:
                c.layout = {k: v for k, v in c.layout.items() if k != "follow"}
        return self._edit(text, fn)

    def set_layout(self, clip_ids: list[str], layout: dict | None, text: str = "Disposición en pantalla"):
        def fn(p: Project):
            for cid in clip_ids:
                c = p.clips.get(cid)
                if c is None:
                    continue
                self._check_clip(p, c)
                c.layout = dict(layout) if layout else None
                c.layout_kf = []          # una disposición fija quita la animación de posición/tamaño

        return self._edit(text, fn)

    # ------------------------------------------------- temas de la narración
    @staticmethod
    def _tidy_topics(p: Project):
        """Temas limpios: los trozos diminutos («…» en la barra) se unen al de al lado y dos seguidos con el
        mismo nombre se juntan en uno. «Diminuto» = menos de 15 s y del 4 % de la narración."""
        topics = sorted((m for m in p.markers if m.kind == "topic"), key=lambda m: m.time)
        if not topics:
            return
        span = (topics[-1].end or topics[-1].time) - topics[0].time
        min_len = min(15.0, 0.04 * span)
        keep = []
        for m in topics:
            if keep and (m.label == keep[-1].label or (m.end or m.time) - m.time < min_len):
                keep[-1].end = max(keep[-1].end or m.time, m.end or m.time)     # se une al anterior
                continue
            keep.append(m)
        if len(keep) > 1 and (keep[0].end or 0) - keep[0].time < min_len:   # el primero, diminuto: al siguiente
            keep[1].time = keep[0].time
            keep = keep[1:]
        ids = {m.id for m in keep}
        p.markers = [m for m in p.markers if m.kind != "topic" or m.id in ids]

    def topic_segments(self, labels=None) -> list[tuple[str, float, float]]:
        """[(tema, desde, hasta)] de la línea de tiempo (solo esos temas si se dan)."""
        out = []
        for m in sorted((m for m in self.project.markers if m.kind == "topic"), key=lambda m: m.time):
            if (labels is None or m.label in labels) and (m.end or m.time) - m.time > 0.05:
                out.append((m.label, m.time, m.end))
        return out

    def keep_topics(self, labels) -> int:
        """«Quedarme con estos temas»: quita de la línea de tiempo todo lo que no sea de esos temas y junta lo que
        queda (un solo Ctrl+Z). Devuelve cuántos tramos quedan."""
        keep = [(a, b) for _l, a, b in self.topic_segments(set(labels))]
        if not keep:
            raise EditError("Marca al menos un tema.")
        merged: list[list[float]] = []
        for a, b in sorted(keep):
            if merged and a <= merged[-1][1] + EPS:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        end = max(self.project.duration(), merged[-1][1])
        drop, cur = [], 0.0
        for a, b in merged:
            if a > cur + EPS:
                drop.append((cur, a))
            cur = max(cur, b)
        if end > cur + EPS:
            drop.append((cur, end))

        def fn(p: Project):
            for a, b in reversed(drop):
                self._ripple_delete(p, a, b)
            p.markers = [m for m in p.markers if m.kind != "topic" or (m.end or m.time) - m.time > 0.05]
            return len(merged)

        return self._edit("Quedarme con estos temas", fn)

    def remove_all_topics(self):
        return self._edit("Quitar todos los temas",
                          lambda p: setattr(p, "markers", [m for m in p.markers if m.kind != "topic"]))

    def set_topics(self, media_id: str, segments: list[dict]):
        """Sustituye los temas detectados por la IA (marcadores de tramo) por un análisis nuevo."""
        def fn(p: Project):
            p.markers = [m for m in p.markers if m.kind != "topic"]
            index = mapping.SourceIndex(p, media_id)
            for s in segments:
                a, b = index.time(s["start"]), index.time(max(s["start"], s["end"] - 0.05))
                if a is None or b is None or b <= a:
                    continue
                p.markers.append(Marker(new_id(), a, s["topic"], s.get("color", "#9aa1ad"),
                                        origin=ORIGIN_AI, end=b, kind="topic"))
            p.markers.sort(key=lambda m: m.time)
            topics = [m for m in p.markers if m.kind == "topic"]
            for x, y in zip(topics, topics[1:]):  # tramos seguidos, sin huecos ni solapes
                x.end = y.time
            if not topics:
                raise EditError("No se pudieron colocar los temas: ¿la narración está en la timeline?")
            self._tidy_topics(p)
            return sum(1 for m in p.markers if m.kind == "topic")

        return self._edit("IA · Detectar temas", fn)

    def move_topic_start(self, marker_id: str, t: float):
        """Mueve el inicio de un tema (y el final del anterior, si están pegados)."""
        def fn(p: Project):
            topics = sorted((m for m in p.markers if m.kind == "topic"), key=lambda m: m.time)
            for i, m in enumerate(topics):
                if m.id == marker_id:
                    lo = topics[i - 1].time + 1.0 if i > 0 else 0.0
                    hi = (m.end if m.end is not None else t) - 1.0
                    new = min(max(t, lo), max(lo, hi))
                    if i > 0 and topics[i - 1].end is not None and abs(topics[i - 1].end - m.time) < 0.05:
                        topics[i - 1].end = new
                    m.time = new
                    m.origin = ORIGIN_USER  # retocado a mano
            p.markers.sort(key=lambda m: m.time)

        return self._edit("Ajustar tema", fn)

    def remove_topic(self, marker_id: str):
        """Quita un tema: su tramo pasa a formar parte del tema anterior."""
        def fn(p: Project):
            topics = sorted((m for m in p.markers if m.kind == "topic"), key=lambda m: m.time)
            for i, m in enumerate(topics):
                if m.id == marker_id:
                    if i > 0:
                        topics[i - 1].end = m.end
                    elif i + 1 < len(topics):
                        topics[i + 1].time = m.time
                    p.markers.remove(m)
                    break

        return self._edit("Quitar tema", fn)

    # ------------------------------------------------- análisis de clips
    def set_media_ai(self, media_id: str, result: dict):
        """Guarda lo que la IA vio en un clip. Las categorías que puso el usuario se respetan."""
        m = self.project.media.get(media_id)
        if m is None:
            return
        m.ai_type = result.get("type", "")
        m.ai_tags = list(result.get("tags", []))
        m.ai_analyzed = True
        if m.kind == KIND_VIDEO and m.category in ("Videos", "Sin clasificar") and m.ai_type:
            m.category = m.ai_type
        if result.get("vecs") is not None:
            self.clip_vecs[media_id] = (result["times"], result["vecs"])
        self._set_media_dirty()
        self.media_changed.emit()

    # ------------------------------------------------- subtítulos
    MERGE_SUBTITLE_STYLE = 101

    def set_subtitle_style(self, text: str = "Estilo de subtítulos", **props):
        def fn(p: Project):
            for k, v in props.items():
                setattr(p.subtitles, k, v)

        return self._edit(text, fn, merge_id=self.MERGE_SUBTITLE_STYLE)

    def set_emphasis(self, indices: list[int], on: bool):
        """Resalta (o quita el resalte de) palabras en los subtítulos, p. ej. «NO»."""
        def fn(p: Project):
            current = set(p.subtitles.emphasis)
            current = current | set(indices) if on else current - set(indices)
            p.subtitles.emphasis = sorted(current)

        return self._edit("Resaltar palabra" if on else "Quitar resaltado", fn)

    # ------------------------------------------------- transcripción
    def set_transcript(self, media_id: str, data: dict):
        if self.project.transcripts.get(media_id, {}).get("words") != data.get("words") and \
                self.project.subtitles.media_id == media_id and self.project.subtitles.emphasis:
            # Transcripción nueva: los índices de palabras resaltadas ya no valen
            self.project.subtitles.emphasis = []
        self.project.transcripts[media_id] = data
        self._set_media_dirty()
        self.transcript_changed.emit(media_id)

    def edit_words(self, media_id: str, indices: list[int], text: str):
        """Corrige varias palabras seguidas (un bloque de lo que sale en pantalla). Con el mismo número de palabras,
        cada una conserva sus tiempos; si cambia, las nuevas se reparten en el mismo tramo (según su largo)."""
        words = self.project.transcripts.get(media_id, {}).get("words", [])
        idx = sorted(i for i in indices if 0 <= i < len(words))
        new = text.split()
        if not idx or not new or idx != list(range(idx[0], idx[-1] + 1)):
            return
        if len(new) == len(idx):
            for i, w in zip(idx, new):
                words[i][2] = w
        else:
            a, b = float(words[idx[0]][0]), float(words[idx[-1]][1])
            conf = words[idx[0]][3] if len(words[idx[0]]) > 3 else 1.0
            total = sum(len(w) for w in new) or 1
            t, rebuilt = a, []
            for w in new:
                d = (b - a) * len(w) / total
                rebuilt.append([round(t, 3), round(t + d, 3), w, conf])
                t += d
            words[idx[0]:idx[-1] + 1] = rebuilt
            delta = len(new) - len(idx)
            st = self.project.subtitles
            if st.media_id == media_id and st.emphasis:   # resaltados: los de detrás se corren; los del bloque, fuera
                st.emphasis = [e + delta if e > idx[-1] else e for e in st.emphasis if not idx[0] <= e <= idx[-1]]
        self._set_media_dirty()
        self.transcript_changed.emit(media_id)

    def edit_word(self, media_id: str, index: int, text: str):
        """Corrige el texto de una palabra (los tiempos no cambian, así sigue sincronizada)."""
        self.edit_word_texts(media_id, {index: text})

    def edit_word_texts(self, media_id: str, texts: dict[int, str]) -> int:
        """✎ Corrige varias palabras de una vez (p. ej. la misma en todo el texto); los tiempos no cambian."""
        words = self.project.transcripts.get(media_id, {}).get("words", [])
        n = 0
        for i, t in texts.items():
            if 0 <= i < len(words) and t.strip():
                words[i][2] = t.strip()
                n += 1
        if n:
            self._set_media_dirty()
            self.transcript_changed.emit(media_id)
        return n

    # ------------------------------------------------- sugerencias de IA
    def set_suggestions(self, media_id: str, items: list[dict], kinds: set[str], cuttable: dict):
        """Sustituye las sugerencias pendientes/ignoradas de esos tipos por un análisis nuevo.
        Las ya aplicadas se conservan (para poder restaurarlas)."""
        def fn(p: Project):
            p.suggestions = [s for s in p.suggestions
                             if not (s.media_id == media_id and s.kind in kinds and s.status != SUG_APPLIED)]
            applied = [(s.applied_start, s.applied_end) for s in p.suggestions
                       if s.media_id == media_id and s.status == SUG_APPLIED]
            for d in items:
                # No volver a proponer lo que ya se cortó
                if any(a is not None and d["start"] >= a - 0.05 and d["end"] <= b + 0.05 for a, b in applied):
                    continue
                p.suggestions.append(Suggestion(
                    id=new_id(), kind=d["kind"], media_id=media_id, start=d["start"], end=d["end"],
                    label=d.get("label", ""), detail=d.get("detail", ""),
                    cuttable=cuttable.get(d["kind"], True),
                    alt_start=d.get("alt_start"), alt_end=d.get("alt_end"), data=dict(d.get("data", {}))))
            p.suggestions.sort(key=lambda s: (s.media_id, s.start))
            return len(items)

        return self._edit("IA · Analizar narración", fn)

    def apply_suggestions(self, ids: list[str], keep_first: bool | None = None):
        """Aplica sugerencias de corte (cerrando el hueco en todas las pistas).
        Tomas repetidas: se queda la que eligió la IA (la mejor); keep_first=True/False fuerza la toma 1 / la 2."""
        def fn(p: Project):
            sugs = [s for s in p.suggestions if s.id in set(ids) and s.status == SUG_PENDING and s.cuttable]
            if not sugs:
                raise EditError("No hay sugerencias pendientes que se puedan aplicar.")
            # Tramos de la timeline a quitar (calculados antes de cortar nada)
            spans, done = [], []
            for s in sugs:
                kf = keep_first if keep_first is not None else (s.kind == "retake" and (s.data or {}).get("best") == 1)
                a, b = (s.alt_start, s.alt_end) if kf and s.alt_start is not None else (s.start, s.end)
                parts = mapping.map_range(p, s.media_id, a, b)
                if not parts:
                    continue
                spans += [(ta, tb) for _c, ta, tb in parts]
                done.append((s, a, b))
            if not spans:
                raise EditError("Esos fragmentos ya no están en la timeline "
                                "(¿la narración no está añadida o ya se cortaron?).")
            spans.sort()
            merged = [list(spans[0])]
            for ta, tb in spans[1:]:
                if ta <= merged[-1][1] + EPS:
                    merged[-1][1] = max(merged[-1][1], tb)
                else:
                    merged.append([ta, tb])
            for ta, tb in reversed(merged):  # de atrás hacia delante: no se desplazan los anteriores
                self._ripple_delete(p, ta, tb)
            for s, a, b in done:
                s.status, s.applied_start, s.applied_end = SUG_APPLIED, a, b
            return len(done)

        n = len(ids)
        return self._edit("IA · Aplicar corte" if n == 1 else f"IA · Aplicar {n} cortes", fn)

    def reject_suggestions(self, ids: list[str], rejected: bool = True):
        def fn(p: Project):
            for s in p.suggestions:
                if s.id in set(ids) and s.status != SUG_APPLIED:
                    s.status = SUG_REJECTED if rejected else SUG_PENDING

        return self._edit("IA · Ignorar sugerencia" if rejected else "IA · Recuperar sugerencia", fn)

    def set_cross(self, ids: list[str], on: bool | None):
        """✂ Tachar (on=True: se quitará al cortar lo tachado) o destachar (False: se queda) en el texto. None = lo que
        diga la limpieza automática. Lo tachado a mano, al destacharlo, desaparece."""
        def fn(p: Project):
            ids_ = set(ids)
            for s in list(p.suggestions):
                if s.id not in ids_ or s.status == SUG_APPLIED:
                    continue
                if s.kind == "manual" and on is False:
                    p.suggestions.remove(s)
                    continue
                s.status = SUG_PENDING
                s.data = dict(s.data or {})
                if on is None:
                    s.data.pop("tachar", None)
                else:
                    s.data["tachar"] = bool(on)

        return self._edit("✂ Tachar" if on else "Quitar tachado", fn)

    def add_manual_cut(self, media_id: str, start: float, end: float, text: str):
        """✂ Lo que tachas tú en el texto: se quita junto con lo demás al cortar lo tachado."""
        if end - start < 0.02:
            return None

        def fn(p: Project):
            short = text if len(text) <= 60 else text[:57] + "…"
            p.suggestions.append(Suggestion(id=new_id(), kind="manual", media_id=media_id, start=start, end=end,
                                            label=f"Tachado a mano: «{short}»", detail="Lo tachaste tú en el texto.",
                                            data={"tachar": True, "text": text}))
            p.suggestions.sort(key=lambda s: (s.media_id, s.start))

        return self._edit("✂ Tachar en el texto", fn)

    def choose_take(self, sug_id: str, best: int):
        """Tomas repetidas: con qué toma te quedas (1 = la primera, 2 = la segunda); la otra queda tachada."""
        def fn(p: Project):
            for s in p.suggestions:
                if s.id == sug_id and s.status != SUG_APPLIED and s.kind == "retake":
                    s.status = SUG_PENDING
                    s.data = dict(s.data or {}, best=1 if best == 1 else 2, tachar=True)

        return self._edit("Elegir toma", fn)

    def mark_suggestions_applied(self, ids: list[str]):
        def fn(p: Project):
            for s in p.suggestions:
                if s.id in set(ids):
                    s.status = SUG_APPLIED

        return self._edit("IA · Sugerencia aplicada", fn)

    def restore_suggestions(self, ids: list[str]):
        """Deshace UN corte concreto de la IA (aunque después hayas hecho otros cambios)."""
        def fn(p: Project):
            sugs = sorted((s for s in p.suggestions if s.id in set(ids) and s.status == SUG_APPLIED),
                          key=lambda s: s.applied_start, reverse=True)
            for s in sugs:
                a, b = s.applied_start, s.applied_end
                found = mapping.find_cut(p, s.media_id, a, b)
                if found is None:
                    raise EditError("No se encontró ese corte en la timeline (puede que lo hayas "
                                    "editado a mano). Usa Deshacer (Ctrl+Z) si es reciente.")
                L, R, t = found
                d = b - a
                self._ripple_insert(p, t, d)
                # En todas las pistas: si el contenido era continuo, se vuelve a unir
                for tr in p.tracks:
                    self._heal(p, tr.id, t, d)
                if L is None:      # corte al principio del archivo
                    R.start -= d
                    R.source_in -= d
                    R.duration += d
                elif R is None:    # corte al final del archivo
                    L.duration += d
                s.status, s.applied_start, s.applied_end = SUG_PENDING, None, None

        return self._edit("IA · Restaurar corte", fn)

    # ---------------------------------------------------------- biblioteca
    def recheck_missing(self) -> int:
        """Los archivos que faltaban y ya vuelven a estar (recuperados de la Papelera, disco conectado…):
        sus clips dejan de salir en rojo. Devuelve cuántos volvieron."""
        back = [mid for mid in list(self.missing)
                if mid in self.project.media and os.path.isfile(self.project.media[mid].path)]
        for mid in back:
            self.missing.discard(mid)
            self._analyze(self.project.media[mid])
        if back:
            self.message.emit(f"✓ {len(back)} archivo(s) que faltaban vuelven a estar: sus clips ya se ven.")
            self.media_changed.emit()
            self.project_changed.emit()
        return len(back)

    def _same_missing(self, ap: str, kind: str):
        """¿Ese archivo nuevo es uno de los que faltan, en otra carpeta? (mismo nombre y, si se sabe, misma
        duración). Así sus clips se reconectan solos en vez de quedarse en rojo."""
        name = os.path.basename(ap).lower()
        cands = [self.project.media[i] for i in self.missing if i in self.project.media
                 and self.project.media[i].kind == kind and self.project.media[i].name.lower() == name]
        if not cands:
            return None
        if len(cands) == 1 and not (cands[0].probed and cands[0].duration > 0):
            return cands[0]
        try:
            dur = float(media_tools.probe(ap)["duration"]) if kind != KIND_IMAGE else 0.0
        except Exception:  # noqa: BLE001 - archivo ilegible: no se reconecta
            return None
        same = [m for m in cands if kind == KIND_IMAGE or abs(m.duration - dur) < 0.25]
        return same[0] if len(same) == 1 else None

    def adopt_media(self, items: list) -> int:
        """🗂 La biblioteca es común a las pestañas (YouTube · Edits · Shorts): los medios de la otra pestaña que aquí
        no estén se añaden tal cual (con su categoría, tramos elegidos…), sin tocar la línea de tiempo. Lo ya
        analizado (miniaturas, formas de onda) se reutiliza: va por archivo. Devuelve cuántos se añadieron."""
        import copy as _copy
        have = {os.path.normcase(os.path.abspath(m.path)) for m in self.project.media.values()}
        n = 0
        for src in items:
            key = os.path.normcase(os.path.abspath(src.path))
            if key in have or not os.path.isfile(src.path):
                continue
            m = _copy.deepcopy(src)
            if m.id in self.project.media:
                m.id = new_id()
            self.project.media[m.id] = m
            have.add(key)
            self._analyze(m)
            n += 1
        if n:
            self._set_media_dirty()
            self.media_changed.emit()
        return n

    def import_paths(self, paths: list[str], root: str | None = None) -> list[str]:
        existing = {os.path.normcase(os.path.abspath(m.path)) for m in self.project.media.values()}
        new_ids = []
        relinked = []
        if self.missing:
            self.recheck_missing()          # el mismo archivo, otra vez en su sitio
        for path in paths:
            ap = os.path.abspath(path)
            kind = kind_for_path(ap)
            key = os.path.normcase(ap)
            if not kind or key in existing or not os.path.isfile(ap):
                continue
            old = self._same_missing(ap, kind) if self.missing else None
            if old is not None:             # el que faltaba, en otra carpeta: se reconectan sus clips
                old.path = ap
                self.missing.discard(old.id)
                existing.add(key)
                relinked.append(old.id)
                self._analyze(old)
                continue
            category, tags = classify(ap, kind, root)
            m = MediaItem(id=new_id(), path=ap, kind=kind, name=os.path.basename(ap),
                          category=category, tags=tags)
            self.project.media[m.id] = m
            existing.add(key)
            new_ids.append(m.id)
            self._analyze(m)
        if relinked:
            self._set_media_dirty()
            self.media_changed.emit()
            self.project_changed.emit()
            self.message.emit(f"🔗 {len(relinked)} archivo(s) que faltaban reconectados: sus clips ya se ven.")
        if new_ids:
            self._set_media_dirty()
            self.media_changed.emit()
            self.message.emit(f"Importados {len(new_ids)} archivos. Analizando en segundo plano…")
        elif not relinked:
            self.message.emit("No se importó nada nuevo (archivos repetidos o formatos no compatibles).")
        return new_ids

    def import_now(self, paths: list[str]) -> list[str]:
        """Importa y lee al momento la duración y el tamaño (para soltar archivos de Windows directamente
        en la timeline). Devuelve los ids, también de los que ya estaban en la biblioteca."""
        new = set(self.import_paths(paths))
        by_path = {os.path.normcase(os.path.abspath(m.path)): m.id for m in self.project.media.values()}
        out = []
        for path in paths:
            mid = by_path.get(os.path.normcase(os.path.abspath(path)))
            if mid is None:
                mid = next((i for i in new if os.path.normcase(self.project.media[i].path)
                            == os.path.normcase(os.path.abspath(path))), None)
            if mid is None:
                continue
            m = self.project.media[mid]
            if not m.probed and m.kind != KIND_IMAGE or (m.kind == KIND_IMAGE and not m.width):
                try:
                    info = media_tools.probe(m.path)
                    m.duration = 0.0 if m.kind == KIND_IMAGE else float(info["duration"])
                    m.width, m.height = info["width"], info["height"]
                    m.fps, m.has_audio = info["fps"], info["has_audio"]
                    m.channels = int(info.get("channels", 0))
                    m.probed = True
                except Exception:  # noqa: BLE001 - archivo dañado: se avisa al añadirlo
                    pass
            out.append(mid)
        return out

    def import_folder(self, folder: str) -> list[str]:
        paths = []
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            paths += [os.path.join(dirpath, f) for f in sorted(filenames) if kind_for_path(f)]
        return self.import_paths(paths, root=folder)

    def set_media_props(self, media_ids: list[str], **props):
        for mid in media_ids:
            m = self.project.media.get(mid)
            if m:
                for k, v in props.items():
                    setattr(m, k, v)
        self._set_media_dirty()
        self.media_changed.emit()

    def remove_media(self, media_ids: list[str]) -> bool:
        used = [self.project.media[m].name for m in media_ids
                if m in self.project.media and self.project.is_media_used(m)]
        if used:
            self.message.emit(f"«{used[0]}» se está usando en la timeline. Quita primero sus clips.")
            return False
        for mid in media_ids:
            self.project.media.pop(mid, None)
            self.project.transcripts.pop(mid, None)
            self.clip_vecs.pop(mid, None)
        self._set_media_dirty()
        self.media_changed.emit()
        return True

    def set_deep_analysis(self, media_id: str, res: dict):
        """Guarda el análisis a fondo de un clip (un fotograma por segundo y sus planos)."""
        from ..ai.clip_analysis import classify
        m = self.project.media.get(media_id)
        if m is None:
            return
        self.clip_vecs[media_id] = (res["times"], res["vecs"])
        self.clip_shots[media_id] = res.get("shots")
        r = classify(res["vecs"], res.get("letterbox", 0.0))
        self.set_media_ai(media_id, {"type": r["type"], "tags": r["tags"]})

    def _load_clip_vecs(self, m: MediaItem):
        """Recupera de la caché las huellas IA de un clip ya analizado (a fondo, si lo hay)."""
        from ..ai.clip_analysis import load_cached
        from ..ai.library_understanding import load_deep
        deep = load_deep(m.path)
        if deep is not None:
            self.clip_vecs[m.id] = (deep["times"], deep["vecs"])
            self.clip_shots[m.id] = deep["shots"]
            return
        cached = load_cached(m.path)
        if cached is not None:
            self.clip_vecs[m.id] = (cached[0], cached[1])
        else:
            m.ai_analyzed = False  # la caché se borró o el archivo cambió: hay que volver a analizar

    def _analyze(self, m: MediaItem):
        self.analyzing.add(m.id)
        self._pool.start(_AnalyzeTask(m.id, m.path, m.kind, self._signals))

    def _on_analyzed(self, media_id: str, result: dict):
        self.analyzing.discard(media_id)
        m = self.project.media.get(media_id)
        if m is None:
            return
        info = result.get("info")
        if info:
            m.duration = 0.0 if m.kind == KIND_IMAGE else float(info["duration"])
            m.width, m.height = info["width"], info["height"]
            m.fps, m.has_audio = info["fps"], info["has_audio"]
            m.channels = int(info.get("channels", 0))
            m.probed = True
        if result.get("thumb"):
            self.thumbs[media_id] = result["thumb"]
        if result.get("peaks") is not None:
            self.peaks[media_id] = result["peaks"]
        if result.get("obs") is not None:
            self._obs_tracks(m, result["obs"])
        if result.get("error"):
            self.message.emit(f"No se pudo analizar «{m.name}»: {result['error'][:150]}")
        self.media_changed.emit()

    def separate_audio_tracks_now(self, media_id: str) -> dict:
        """🎵 «Separar audio» de una grabación con varias pistas (OBS: micrófono y juego), ya (bloquea: para pruebas y
        el puente de Claude; la interfaz lo hace en segundo plano con obs_tracks.split + apply_audio_tracks)."""
        from . import obs_tracks
        m = self.project.media.get(media_id)
        if m is None:
            return {}
        res = obs_tracks.split(m.path)
        self.apply_audio_tracks(media_id, res)
        return res

    def apply_audio_tracks(self, media_id: str, res: dict):
        m = self.project.media.get(media_id)
        if m is not None:
            self._obs_tracks(m, res)
            self.media_changed.emit()

    # 🎙/🎮 Cada pista separada en su categoría de Medios (el usuario: «que me dé una categoría en específico, como
    # audio de micrófono»)
    OBS_CATEGORY = {"voz": "🎙 Audio de micrófono", "juego": "🎮 Audio del juego"}

    def _obs_tracks(self, m: MediaItem, res: dict):
        """🎙/🎮 Registra las pistas separadas (micrófono, juego) de una grabación de OBS como audios del proyecto."""
        tracks = res.get("tracks") or []
        if not tracks:
            if res.get("note") and not getattr(m, "_obs_warned", False):
                m._obs_warned = True
                self.message.emit(f"🎙 «{m.name}» tiene varias pistas de audio, pero no se pueden separar: "
                                  f"{res['note']}. Revisa en OBS qué va a cada pista.")
            return
        by_path = {os.path.normcase(x.path): x for x in self.project.media.values()}
        out, new = [], False
        for t in tracks:
            a = by_path.get(os.path.normcase(t["path"]))
            cat = self.OBS_CATEGORY.get(t["role"], "Pistas de OBS")
            if a is None:
                a = MediaItem(id=new_id(), path=t["path"], kind=KIND_AUDIO, name=os.path.basename(t["path"]),
                              category=cat, tags=[t["label"]])
                self.project.media[a.id] = a
                self._analyze(a)
                new = True
            elif a.category == "Pistas de OBS":           # (los separados antes: a su categoría)
                a.category = cat
                self._set_media_dirty()
            out.append({"media_id": a.id, "role": t["role"], "label": t["label"]})
        if out != m.audio_tracks:
            m.audio_tracks = out
            self._set_media_dirty()
        if new and len(out) == 1:
            self.message.emit(f"🎙 «{m.name}»: tu voz sola (micrófono) está en «🎙 Audio de micrófono» (el juego no "
                              "sonó). "
                              "Clic derecho → «Mostrar en el Explorador» para llevarla a transcribir.")
        elif new:
            self.message.emit(f"🎙 «{m.name}»: separado. Tu micrófono está en «🎙 Audio de micrófono» y el juego en "
                              "«🎮 Audio del juego»; al poner el video en la línea de tiempo irán cada uno en su pista "
                              "(vinculados).")

    def _obs_track_for(self, p: Project, role: str, a: float, b: float) -> str:
        """Pista de audio para tu voz (🎙 Micrófono, con la mejora de voz) o para el juego, libre en [a, b)."""
        if role != "voz":
            return self._av_track(p, a, b)
        for t in p.tracks:
            if t.kind == TRACK_AUDIO and t.role == "voz" and not t.locked and \
                    not any(c.start < b - EPS and c.end > a + EPS for c in p.clips_on(t.id)):
                return t.id
        tr = Track(new_id(), TRACK_AUDIO, "🎙 Micrófono", fx={"eq": True, "compress": True}, role="voz")
        last = max((i for i, t in enumerate(p.tracks) if t.kind == TRACK_AUDIO), default=len(p.tracks) - 1)
        p.tracks.insert(last + 1, tr)
        return tr.id

    # ------------------------------------------------------ guardar / abrir
    def new_project(self):
        self._replace(Project.new(), None)

    def load(self, path: str, recovered: bool = False, keep_undo: bool = False):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        project = Project.from_dict(data)
        self._replace(project, data.get("_autosave_of") if recovered else path, keep_undo)
        if recovered:
            self._set_media_dirty()

    def _replace(self, project: Project, path: str | None, keep_undo: bool = False):
        self.project = project
        self.path = path
        if not keep_undo:            # 🗂 al volver a una pestaña se conserva su historial (Ctrl+Z sigue valiendo)
            self.undo_stack.clear()
        self.thumbs.clear()
        self.peaks.clear()
        self.missing.clear()
        self.clip_vecs.clear()
        self.clip_shots.clear()
        self.understanding = None
        self.beats.clear()
        self.rhythm.clear()
        self.rhythm_busy.clear()
        self._media_dirty = False
        for m in project.media.values():
            if not os.path.exists(m.path) and path:        # 📦 proyecto recopilado: ¿está en su carpeta «Medios»?
                from . import collect
                alt = collect.find_in_media_folder(path, m.path)
                if alt:
                    m.path = alt
                    self._media_dirty = True
            if m.gen and not os.path.exists(m.path):       # 🟦 generadores: se vuelven a crear (otro PC)
                try:
                    from . import generators
                    m.path = generators.make(m.gen, m.width or project.width, m.height or project.height)
                except Exception:  # noqa: BLE001 - sin él, queda como archivo que falta
                    pass
            if os.path.exists(m.path):
                self._analyze(m)
                if m.ai_analyzed:
                    self._load_clip_vecs(m)
            else:
                self.missing.add(m.id)
        if self.missing:
            self.message.emit(f"⚠️ No se encuentran {len(self.missing)} archivos del proyecto (¿se movieron?).")
        self.project_replaced.emit()
        self.project_changed.emit()
        self.media_changed.emit()
        self.dirty_changed.emit()

    def rename_project(self, name: str) -> None:
        """✎ Nombre del video/proyecto (cabecera del visor). Se usa al guardar y al exportar."""
        name = (name or "").strip()
        if name and name != self.project.name:
            self.undo_stack.push(_RenameCommand(self, self.project.name, name))

    def save(self, path: str | None = None, backup: bool = True) -> bool:
        path = path or self.path
        if not path:
            return False
        if not self.path or os.path.normcase(path) != os.path.normcase(self.path):
            self.project.name = os.path.splitext(os.path.basename(path))[0]
        _atomic_write_json(path, self.project.to_dict())
        self.path = path
        self.undo_stack.setClean()
        self._media_dirty = False
        self.dirty_changed.emit()
        if backup:
            self._backup(path)
        self.saved.emit(path)
        return True

    def save_version(self) -> str | None:
        """Guarda una copia numerada: Proyecto_v01.eia, Proyecto_v02.eia…"""
        if not self.path:
            return None
        folder = os.path.dirname(self.path)
        stem = re.sub(r"_v\d+$", "", os.path.splitext(os.path.basename(self.path))[0])
        n = 1
        for f in os.listdir(folder):
            m = re.fullmatch(re.escape(stem) + r"_v(\d+)\.eia", f, flags=re.IGNORECASE)
            if m:
                n = max(n, int(m.group(1)) + 1)
        version_path = os.path.join(folder, f"{stem}_v{n:02d}.eia")
        _atomic_write_json(version_path, self.project.to_dict())
        return version_path

    def write_autosave(self):
        data = self.project.to_dict()
        data["_autosave_of"] = self.path
        ws = getattr(self, "workspace_file", None)
        if ws:
            data["_espacio"] = os.path.splitext(os.path.basename(ws))[0]
        _atomic_write_json(str(autosave_path()), data)
        if ws and not self.path:            # 🗂 proyecto sin nombre de una pestaña: también en su archivo
            _atomic_write_json(ws, data)

    def load_workspace(self, path: str, keep_undo: bool = False):
        """🗂 El proyecto sin nombre de una pestaña de trabajo (no cuenta como «cambios sin guardar»)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self._replace(Project.from_dict(data), None, keep_undo)

    def backup_now(self, path: str, keep: int = 40, name: str | None = None):
        """Copia de seguridad con fecha y hora (se conservan las «keep» más recientes de ese proyecto)."""
        stem = os.path.splitext(os.path.basename(name or path))[0]
        dest = backups_dir() / f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.eia"
        shutil.copy2(path, dest)
        old = sorted(backups_dir().glob(f"{stem}_*.eia"), key=os.path.getmtime)
        for f in old[:-max(1, keep)]:
            f.unlink(missing_ok=True)
        return str(dest)

    def _backup(self, path: str):
        try:
            stem = os.path.splitext(os.path.basename(path))[0]
            dest = backups_dir() / f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.eia"
            shutil.copy2(path, dest)
            old = sorted(backups_dir().glob(f"{stem}_*.eia"))
            for f in old[:-30]:  # se conservan las 30 copias más recientes
                f.unlink(missing_ok=True)
        except OSError:
            pass
