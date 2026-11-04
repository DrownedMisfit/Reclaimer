"""
Modelo de datos del proyecto.

Idea clave (edición NO destructiva): los archivos originales nunca se tocan.
Un clip de la timeline solo guarda QUÉ trozo de un archivo se usa
(source_in + duration) y DÓNDE se coloca (start). Cortar, mover o borrar
clips solo cambia estos números; el archivo original queda intacto.
"""
from __future__ import annotations

import copy
import json

import os
import uuid
from dataclasses import dataclass, field, fields

FORMAT_NAME = "editoria-project"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".ts", ".mts", ".m2ts"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}

KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_IMAGE = "image"

TRACK_VIDEO = "video"
TRACK_AUDIO = "audio"
TRACK_TEXT = "text"       # pista de textos en pantalla (títulos, etiquetas)

# Estilo por defecto de un texto en pantalla (tamaños en % de la altura del video)
TEXT_DEFAULTS = {"content": "Texto", "x": 0.5, "y": 0.12, "size": 6.0, "color": "#FFFFFF",
                 "box": True, "box_color": "#000000", "box_opacity": 0.6, "bold": True, "font": "Arial"}

ORIGIN_USER = "user"
ORIGIN_AI = "ai"

DEFAULT_IMAGE_DURATION = 5.0


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def kind_for_path(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return KIND_VIDEO
    if ext in AUDIO_EXT:
        return KIND_AUDIO
    if ext in IMAGE_EXT:
        return KIND_IMAGE
    return None


def _build(cls, data: dict):
    """Crea un dataclass ignorando claves desconocidas (compatibilidad con versiones futuras)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


# ⚡ Copia rápida de un dataclass a dict (el mismo resultado que dataclasses.asdict, ~2 veces más rápida): cada edición
# guarda el estado de TODA la línea de tiempo para Ctrl+Z, y con 1000+ clips asdict tardaba ~40 ms (dos veces por edición)
_ATOMS = (str, int, float, bool, type(None))
_FIELD_NAMES: dict = {}


def _plain(v):
    t = type(v)
    if t in _ATOMS:
        return v
    if t is dict:
        return {k: _plain(x) for k, x in v.items()}
    if t is list:
        return [_plain(x) for x in v]
    if t is tuple:
        return tuple(_plain(x) for x in v)
    if hasattr(t, "__dataclass_fields__"):
        return fast_asdict(v)
    return copy.deepcopy(v)


def fast_asdict(o) -> dict:
    names = _FIELD_NAMES.get(type(o))
    if names is None:
        names = _FIELD_NAMES[type(o)] = tuple(f.name for f in fields(o))
    return {n: _plain(getattr(o, n)) for n in names}


@dataclass
class MediaItem:
    """Un archivo importado en la biblioteca."""
    id: str
    path: str
    kind: str
    name: str
    category: str = "Sin clasificar"
    tags: list[str] = field(default_factory=list)
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    channels: int = 0          # canales de audio (1 = mono, 2 = estéreo)
    probed: bool = False
    # Análisis de contenido por IA (se puede corregir a mano)
    ai_type: str = ""            # Gameplay, Cinemáticas, Menús…
    ai_tags: list[str] = field(default_factory=list)
    ai_analyzed: bool = False
    # ✂ Tramos elegidos a mano para los edits musicales: [[desde, hasta], …] (vacío = todo el video)
    edit_ranges: list = field(default_factory=list)
    # 🎙/🎮 Pistas de audio separadas de una grabación de OBS: [{"media_id", "role": "voz"|"juego", "label"}]
    audio_tracks: list = field(default_factory=list)
    # 🟦 Generado por Reclaimer (color sólido, degradado o 🎨 capa de ajuste): ver core/generators.py
    gen: dict = field(default_factory=dict)
    scene_cut: bool = False      # ✂ al ponerlo en la línea de tiempo se corta solo en cada cambio de escena


@dataclass
class Track:
    id: str
    kind: str          # TRACK_VIDEO | TRACK_AUDIO
    name: str
    locked: bool = False
    muted: bool = False
    hidden: bool = False
    solo: bool = False       # «S» de Resolve: si alguna pista de audio está en solo, solo suenan esas
    fx: dict = field(default_factory=dict)   # efectos de audio de la pista (ver core/audio_fx.py)
    duck_db: float | None = None             # si es música: cuánto baja mientras hablas (dB)
    role: str = ""     # papel (no se ve en el nombre): "voz" | "musica" | "efectos" | "" (lo eliges al renombrar)


@dataclass
class Clip:
    id: str
    media_id: str
    track_id: str
    start: float       # posición en la timeline (segundos)
    source_in: float   # dónde empieza dentro del archivo original (segundos)
    duration: float
    volume: float = 1.0
    enabled: bool = True
    locked: bool = False
    origin: str = ORIGIN_USER   # quién lo creó: usuario o IA
    note: str = ""
    zoom_kf: list[dict] = field(default_factory=list)  # encuadre/zoom (ver core/transform.py)
    layout: dict | None = None                         # posición en pantalla (None = completa)
    text: dict | None = None                           # si es un texto en pantalla (ver TEXT_DEFAULTS)
    eq: dict | None = None                             # ecualizador del clip (ver core/equalizer.py)
    pan: float = 0.0                                   # balance: -1 izquierda … +1 derecha
    fx: dict | None = None                             # efectos: destello, fundidos, temblor (core/effects.py)
    link: str = ""     # vínculo: la imagen y el sonido de un mismo video comparten este id (como en Resolve)
    # Velocidad (como «Cambiar velocidad del clip» de Resolve): 1 = normal, 0.5 = cámara lenta, 2 = el doble
    # de rápido, 0 = fotograma congelado (siempre se ve el fotograma source_in). reverse = hacia atrás.
    speed: float = 1.0
    reverse: bool = False
    color: dict | None = None   # corrección de color (ver core/color.py)
    # Curvas de volumen y opacidad (puntos en segundos DEL ARCHIVO) y modo de fusión (ver core/curves.py)
    vol_kf: list[dict] = field(default_factory=list)
    opacity: float = 1.0
    op_kf: list[dict] = field(default_factory=list)
    blend: str = "normal"
    smooth: bool = False   # cámara lenta suave: al exportar se inventan fotogramas (como Speed Warp de Resolve)
    label: str = ""        # «Color de clip» (como en Resolve): solo para organizarte en la línea de tiempo
    # 🎞 Fotogramas clave de POSICIÓN y TAMAÑO de la capa: [{"t": segundo del archivo (imágenes: desde el inicio del
    # clip), "x", "y", "w", "h", "i"?: "linear"}]; vacío = la disposición fija de «layout» (ver core/transform.py)
    layout_kf: list[dict] = field(default_factory=list)

    @property
    def is_text(self) -> bool:
        return self.text is not None

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def retimed(self) -> bool:
        return self.speed != 1.0 or self.reverse

    @property
    def src_len(self) -> float:
        """Cuántos segundos del archivo usa el clip (a velocidad normal = su duración)."""
        return self.duration * self.speed

    def src_at(self, local: float) -> float:
        """Segundo del archivo que se ve en el instante local (0 = inicio del clip)."""
        local = min(max(local, 0.0), self.duration)
        if self.reverse:
            return self.source_in + (self.duration - local) * self.speed
        return self.source_in + local * self.speed

    def piece_src(self, la: float, lb: float) -> float:
        """source_in de un trozo [la, lb] (tiempo local) del clip: para dividir y recortar con velocidad."""
        if self.reverse:
            return self.source_in + (self.duration - lb) * self.speed
        return self.source_in + la * self.speed


FORMATS = {"youtube": ("🎬 Video de YouTube", 1920, 1080),
           "short": ("📱 YouTube Short", 1080, 1920),
           "edit": ("🎵 Edit musical (vertical)", 1080, 1920)}   # sin comentario: manda la música


@dataclass
class Marker:
    id: str
    time: float
    label: str = ""
    color: str = "#f2b33d"
    origin: str = ORIGIN_USER
    end: float | None = None     # si tiene fin, es un tramo (p. ej. un tema de la narración)
    kind: str = "marker"         # marker | topic


SUG_PENDING = "pending"
SUG_APPLIED = "applied"
SUG_REJECTED = "rejected"


@dataclass
class Suggestion:
    """Una propuesta de la IA. Nunca se aplica sola: el usuario la acepta o la ignora."""
    id: str
    kind: str              # silence | noise | filler | repeat | retake | doubt | clipping
    media_id: str          # archivo de narración al que se refiere
    start: float           # tramo a quitar, en tiempo del archivo original
    end: float
    label: str = ""
    detail: str = ""
    cuttable: bool = True
    status: str = SUG_PENDING
    alt_start: float | None = None   # tomas repetidas: tramo de la otra toma
    alt_end: float | None = None
    applied_start: float | None = None  # tramo que realmente se cortó
    applied_end: float | None = None
    data: dict = field(default_factory=dict)  # datos extra (p. ej. si menciona una cara)


@dataclass
class SubtitleStyle:
    """Cómo se ven los subtítulos dentro del video. Los tamaños son % de la altura del video."""
    enabled: bool = False
    media_id: str = ""          # narración de la que salen los subtítulos
    preset: str = "YouTube clásico"
    font: str = "Arial"
    size: float = 5.0
    bold: bool = True
    uppercase: bool = False
    strip_punct: bool = False   # quitar comas y puntos (estilo Shorts)
    color: str = "#FFFFFF"
    highlight: str = "#FFD400"  # palabras resaltadas y palabra actual (karaoke)
    outline_color: str = "#000000"
    outline: float = 0.30
    box: bool = False
    box_color: str = "#000000"
    box_opacity: float = 0.6
    position: str = "bottom"    # bottom | middle | top
    margin: float = 7.0
    max_chars: int = 42         # caracteres por línea
    max_lines: int = 2
    max_words: int = 0          # palabras como mucho en pantalla a la vez (0 = sin límite; Shorts: 3)
    shadow: float = 0.0         # sombra suave debajo de las letras (% de la altura del video; 0 = sin sombra)
    animation: str = "none"     # none | fade | pop | karaoke
    emphasis: list[int] = field(default_factory=list)  # índices de palabras resaltadas


@dataclass
class Project:
    name: str = "Proyecto sin título"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    media: dict[str, MediaItem] = field(default_factory=dict)
    tracks: list[Track] = field(default_factory=list)
    clips: dict[str, Clip] = field(default_factory=dict)
    markers: list[Marker] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    subtitles: SubtitleStyle = field(default_factory=SubtitleStyle)
    loudnorm: bool = True    # normalizar el volumen final para YouTube (-14 LUFS)
    format: str = "youtube"  # "youtube" (video 16:9) | "short" (YouTube Short 9:16) | "edit" (edit musical)
    # Transcripciones por archivo: {"language", "model", "words": [[ini, fin, texto, conf]], "segments"}
    transcripts: dict[str, dict] = field(default_factory=dict)
    # Momentos favoritos (del buscador de la IA): [{"media_id", "start", "end", "label"}]
    favorites: list[dict] = field(default_factory=list)
    # Miniaturas del video (taller de miniaturas): {"youtube": doc, "short": doc} (ver core/thumbnail.py)
    thumbnails: dict = field(default_factory=dict)
    # Marcas de entrada y salida (I / O, como en Resolve): un tramo para repetir, borrar o exportar solo
    mark_in: float | None = None
    mark_out: float | None = None
    # Edits musicales hechos por la IA (para 👍/👎, 🔀 Remix y 🎛 Mix): cómo se hizo cada uno
    edits: list[dict] = field(default_factory=list)
    # ⧉ Clips compuestos: {media_id del video cocinado: {"a": inicio original, "clips": [clips originales]}}
    compounds: dict = field(default_factory=dict)
    # ✏ Anotaciones del visor (no se exportan): [{"t": segundo, "dur": s, "color": "#e5413c", "strokes": [[x, y, …]]}]
    annotations: list[dict] = field(default_factory=list)

    def marked_range(self) -> tuple[float, float] | None:
        """(entrada, salida) si hay un tramo marcado válido. Falta una marca = desde el inicio / hasta el final."""
        if self.mark_in is None and self.mark_out is None:
            return None
        a = self.mark_in if self.mark_in is not None else 0.0
        b = self.mark_out if self.mark_out is not None else self.duration()
        return (a, b) if b - a > 0.04 else None

    @classmethod
    def new(cls) -> "Project":
        p = cls()
        p.fps = 60.0      # proyectos nuevos: 60 FPS (fluidez); los antiguos conservan los suyos
        p.tracks = [
            Track(new_id(), TRACK_VIDEO, "V2"),
            Track(new_id(), TRACK_VIDEO, "V1"),
            Track(new_id(), TRACK_AUDIO, "A1", fx={"eq": True, "compress": True}),   # una sola (con mejora de voz)
        ]
        return p

    # ---- estado para deshacer/rehacer (todo menos la biblioteca) ----
    def timeline_state(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "tracks": [fast_asdict(t) for t in self.tracks],
            "clips": [fast_asdict(c) for c in self.clips.values()],
            "markers": [fast_asdict(m) for m in self.markers],
            "suggestions": [fast_asdict(s) for s in self.suggestions],
            "subtitles": fast_asdict(self.subtitles),
            "loudnorm": self.loudnorm,
            "project_type": self.format,   # «format» ya identifica el archivo de proyecto
            "edits": json.loads(json.dumps(self.edits)),
            "compounds": json.loads(json.dumps(self.compounds)),
            "annotations": json.loads(json.dumps(self.annotations)),
        }

    def apply_timeline_state(self, s: dict) -> None:
        self.name = s.get("name", self.name)
        self.width = int(s.get("width", self.width))
        self.height = int(s.get("height", self.height))
        self.fps = float(s.get("fps", self.fps))
        self.tracks = [_build(Track, d) for d in s.get("tracks", [])]
        clips = (_build(Clip, d) for d in s.get("clips", []))
        self.clips = {c.id: c for c in clips}
        self.markers = [_build(Marker, d) for d in s.get("markers", [])]
        self.suggestions = [_build(Suggestion, d) for d in s.get("suggestions", [])]
        self.subtitles = _build(SubtitleStyle, s.get("subtitles", {}))
        self.loudnorm = bool(s.get("loudnorm", True))
        self.format = s.get("project_type", "short" if self.height > self.width else "youtube")
        self.edits = json.loads(json.dumps(s.get("edits") or []))
        self.compounds = json.loads(json.dumps(s.get("compounds") or {}))
        self.annotations = json.loads(json.dumps(s.get("annotations") or []))

    # ---- guardar / abrir ----
    def to_dict(self) -> dict:
        d = {"format": FORMAT_NAME, "format_version": 1}
        d.update(self.timeline_state())
        d["media"] = [fast_asdict(m) for m in self.media.values()]
        d["transcripts"] = self.transcripts
        d["favorites"] = self.favorites
        d["thumbnails"] = self.thumbnails
        d["marks"] = [self.mark_in, self.mark_out]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        if d.get("format") != FORMAT_NAME and "format_version" not in d:
            raise ValueError("Este archivo no es un proyecto de Reclaimer.")
        p = cls()
        p.apply_timeline_state(d)
        media = (_build(MediaItem, m) for m in d.get("media", []))
        p.media = {m.id: m for m in media}
        p.transcripts = {k: v for k, v in d.get("transcripts", {}).items() if k in p.media}
        p.favorites = [f for f in d.get("favorites", []) if f.get("media_id") in p.media]
        p.thumbnails = dict(d.get("thumbnails", {}))
        p.mark_in, p.mark_out = (list(d.get("marks") or [None, None]) + [None, None])[:2]
        return p

    # ---- consultas ----
    def duration(self) -> float:
        return max((c.end for c in self.clips.values()), default=0.0)

    def track(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def track_index(self, track_id: str) -> int:
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                return i
        return -1

    def clips_on(self, track_id: str) -> list[Clip]:
        return sorted((c for c in self.clips.values() if c.track_id == track_id), key=lambda c: c.start)

    def clip_at(self, track_id: str, t: float) -> Clip | None:
        for c in self.clips_on(track_id):
            if c.start <= t < c.end:
                return c
        return None

    def audible(self, tr: "Track") -> bool:
        """¿Se oye esta pista? Silenciada (M) no; y si hay pistas de audio en solo (S), solo esas."""
        if tr.muted:
            return False
        if any(t.solo for t in self.tracks if t.kind == TRACK_AUDIO):
            return tr.kind == TRACK_AUDIO and tr.solo
        return True

    def media_of(self, clip: Clip) -> MediaItem | None:
        return self.media.get(clip.media_id)

    def is_media_used(self, media_id: str) -> bool:
        return any(c.media_id == media_id for c in self.clips.values())
