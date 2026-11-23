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
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".bmp", ".webp", ".gif", ".tif", ".tiff"}   # (.jfif: las
#   imágenes que Windows baja de internet con ese nombre son JPEG)

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


_NAME_SETS: dict = {}


def _build(cls, data: dict, copiar: bool = False):
    """Crea un dataclass ignorando claves desconocidas (compatibilidad con versiones futuras). copiar: sus listas y
    diccionarios son copias (el objeto no comparte nada con data: data puede ser un estado del historial)."""
    names = _NAME_SETS.get(cls)
    if names is None:
        names = _NAME_SETS[cls] = frozenset(f.name for f in fields(cls))
    if copiar:
        return cls(**{k: (v if type(v) in _ATOMS else _plain(v)) for k, v in data.items() if k in names})
    if names.issuperset(data):
        return cls(**data)
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


# ⚡ Foto de deshacer COMPARTIDA (21/11, ronda 2): cada edición copiaba los ~2500 clips del proyecto aunque solo cambiara
# uno (~12 ms y ~400 000 objetos nuevos por edición, con pausas del recolector de hasta 170 ms). snap_asdict devuelve el
# MISMO diccionario de la vez anterior si el objeto no cambió (se compara por valor, en C: attrgetter + ==, también los
# tipos), y uno nuevo si cambió. ⚠ Esos diccionarios son de SOLO LECTURA (los comparten varios pasos del historial):
# nunca se modifican ni se usan para crear objetos vivos sin copiar (apply_timeline_state copia por defecto).
_SNAP: dict = {}          # (tipo, id) → (valores, tipos, dict)
_GETTERS: dict = {}       # tipo → (attrgetter de todos sus campos, nombres)


def _getter(t):
    g = _GETTERS.get(t)
    if g is None:
        import operator
        names = _FIELD_NAMES.get(t)
        if names is None:
            names = _FIELD_NAMES[t] = tuple(f.name for f in fields(t))
        g = _GETTERS[t] = (operator.attrgetter(*names), names)
    return g


def snap_asdict(o) -> dict:
    """fast_asdict compartido (ver arriba): el mismo dict si el objeto no cambió desde la última foto. SOLO LECTURA."""
    t = type(o)
    getter, names = _getter(t)
    vals = getter(o)
    tipos = tuple(map(type, vals))
    key = (t, getattr(o, "id", None))
    hit = _SNAP.get(key)
    if hit is not None and hit[1] == tipos and hit[0] == vals:
        return hit[2]
    d = fast_asdict(o)
    _SNAP[key] = (tuple(d[n] for n in names), tipos, d)
    return d


def snap_lista(objs) -> list:
    """⚡ snap_asdict de muchos objetos del MISMO tipo en un solo bucle (sin una llamada de Python por objeto): con
    2500 clips, la foto de deshacer de cada edición. Mismo resultado que [snap_asdict(o) for o in objs]."""
    out = []
    objs = list(objs)
    if not objs:
        return out
    t = type(objs[0])
    getter, names = _getter(t)
    get, snap, asd = _SNAP.get, _SNAP, fast_asdict
    append = out.append
    for o in objs:
        if type(o) is not t:                     # (tipos mezclados: el camino de siempre)
            append(snap_asdict(o))
            continue
        vals = getter(o)
        key = (t, o.id)
        hit = get(key)
        if hit is not None and hit[0] == vals:
            tipos = tuple(map(type, vals))
            if hit[1] == tipos:
                append(hit[2])
                continue
        else:
            tipos = tuple(map(type, vals))
        dd = asd(o)
        snap[key] = (tuple(dd[n] for n in names), tipos, dd)
        append(dd)
    return out


def _podar_snap(vivos: int):
    """La memoria de fotos no crece sin fin (clips que ya no existen): se vacía al pasar de 4 veces lo vivo."""
    if len(_SNAP) > 4 * vivos + 2000:
        _SNAP.clear()




def _rehacer(cls, datos, viejos, copiar: bool) -> list:
    """Objetos de cls desde sus diccionarios. copiar: sin compartir nada con los diccionarios, y reutilizando los
    objetos vivos (viejos) que valen exactamente lo mismo (mismos valores y tipos): ⚡ deshacer sin rehacer 2500 clips."""
    if not copiar:
        return [_build(cls, d) for d in datos]
    getter, names = _getter(cls)
    import operator
    leer_d = operator.itemgetter(*names)          # (en C: sin bucle de Python por campo)
    por_id = {getattr(o, "id", None): o for o in viejos} if viejos else {}
    usados: set = set()
    out = []
    for d in datos:
        o = por_id.get(d.get("id")) if por_id else None
        if o is not None and type(o) is cls and id(o) not in usados:
            vals = getter(o)
            try:
                ref = leer_d(d)
            except KeyError:                      # (un estado sin algún campo: se crea de nuevo)
                ref = None
            if ref is not None and vals == ref and tuple(map(type, vals)) == tuple(map(type, ref)):
                usados.add(id(o))
                out.append(o)
                continue
        out.append(_build(cls, d, copiar=True))
    return out


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
    # 🎯 Recorridos de SEGUIMIENTO (por dónde va un objeto dentro del video, en segundos del archivo): se guardan para
    # usarlos cuando quieras (zoom que sigue, pegar un texto al objeto, desenfocarlo…). Ver core/motion_track.py
    motion_tracks: list[dict] = field(default_factory=list)

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
    note: str = ""               # 📍 nota (M dos veces en el mismo sitio la abre; ver core/marcadores_auto.py)
    resuelto: bool = False       # 📍 dado por revisado: deja de salir en la capa de marcas y en el índice


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
    animation: str = "none"     # none | fade | pop | karaoke | words (palabra a palabra, se van sumando)
    emphasis: list[int] = field(default_factory=list)  # índices de palabras resaltadas
    glow: float = 0.0           # resplandor difuminado alrededor de las letras (% de la altura; 0 = sin resplandor)
    glow_color: str = "#FFFFFF"
    fx_color: bool = False      # frases con ¿?¡! o palabras resaltadas: el resplandor pasa a lila y al resaltado
    fx_stretch: bool = False    # estirón a lo ancho en los primeros fotogramas de cada frase
    fx_punch: bool = False      # golpe final: la frase crece justo antes de un corte de plano


class _Lectura:
    def __init__(self, project, rev):
        self.p, self.rev = project, rev

    def __enter__(self):
        d = self.p.__dict__
        prev = d.get("_lect")
        self._prev = prev
        if prev is not None and (self.rev is None or prev[0] == self.rev):
            return self.p                        # (anidado o misma versión: lo ya ordenado vale)
        guardado = d.get("_lect_rev")
        if self.rev is not None and guardado is not None and guardado[0] == self.rev:
            d["_lect"] = guardado
        else:
            d["_lect"] = [self.rev, None, {}]        # [versión, clips por pista, otros (duración, transiciones…)]
        return self.p

    def __exit__(self, *exc):
        d = self.p.__dict__
        cur = d.get("_lect")
        if self._prev is None:
            if cur is not None and self.rev is not None:
                d["_lect_rev"] = cur                 # (para la próxima lectura con la misma versión)
            d.pop("_lect", None)
        return False


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
    # Cortes de audio que diste por buenos («✓ Está bien así»): claves de core/cut_check.py (van al deshacer también)
    cut_ok: list[str] = field(default_factory=list)
    # ⚡ Acomodar por palabras clave: lo que elegiste en cada mención {clave: "gameplay"|"cinematic"|"image"|"none"}
    kw_choices: dict = field(default_factory=dict)
    # ✓ Revisión guiada: avisos y clips de la IA que diste por buenos («O» = está bien así), por su clave
    review_ok: list[str] = field(default_factory=list)
    # 🎬 Escenas animadas (core/scenes.py): {id: escena}; sus clips llevan la nota «🎬 <id>» (van al deshacer también)
    scenes: dict = field(default_factory=dict)

    def marked_range(self) -> tuple[float, float] | None:
        """(entrada, salida) si hay un tramo marcado válido. Falta una marca = desde el inicio / hasta el final."""
        if self.mark_in is None and self.mark_out is None:
            return None
        a = self.mark_in if self.mark_in is not None else 0.0
        b = self.mark_out if self.mark_out is not None else self.duration()
        return (a, b) if b - a > 0.04 else None

    @classmethod
    def new(cls, minimal: bool = False) -> "Project":
        p = cls()
        p.fps = 60.0      # proyectos nuevos: 60 FPS (fluidez); los antiguos conservan los suyos
        if minimal:       # proyecto nuevo de la ventana: una pista de video («V1») y una de audio («A1»)
            p.tracks = [
                Track(new_id(), TRACK_VIDEO, "V1"),
                Track(new_id(), TRACK_AUDIO, "A1"),     # (22/11: sin EQ ni compresor: nada procesa sin pedirlo)
            ]
            return p
        p.tracks = [
            Track(new_id(), TRACK_VIDEO, "V2"),
            Track(new_id(), TRACK_VIDEO, "V1"),
            Track(new_id(), TRACK_AUDIO, "A1"),         # una sola (EQ y compresor, a mano: audio_fx.AYUDA_FX)
        ]
        return p

    # ---- estado para deshacer/rehacer (todo menos la biblioteca) ----
    def timeline_state(self, compartir: bool = False) -> dict:
        """El estado de la línea de tiempo (todo menos la biblioteca). compartir=True (el historial de deshacer): los
        diccionarios de pistas, clips, marcadores y sugerencias que no cambiaron son LOS MISMOS de la foto anterior
        (⚡ snap_asdict; SOLO LECTURA). Sin compartir (guardar, copiar el proyecto…), todo copias nuevas."""
        asd = snap_asdict if compartir else fast_asdict
        if compartir:
            _podar_snap(len(self.clips) + len(self.markers) + len(self.suggestions) + len(self.tracks))
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "tracks": [asd(t) for t in self.tracks],
            "clips": snap_lista(self.clips.values()) if compartir else [asd(c) for c in self.clips.values()],
            "markers": [asd(m) for m in self.markers],
            "suggestions": [asd(s) for s in self.suggestions],
            "subtitles": fast_asdict(self.subtitles),
            "loudnorm": self.loudnorm,
            "project_type": self.format,   # «format» ya identifica el archivo de proyecto
            "edits": json.loads(json.dumps(self.edits)),
            "compounds": json.loads(json.dumps(self.compounds)),
            "annotations": json.loads(json.dumps(self.annotations)),
            "cut_ok": list(self.cut_ok),
            "kw_choices": dict(self.kw_choices),
            "review_ok": list(self.review_ok),
            "scenes": json.loads(json.dumps(self.scenes)),
        }

    def apply_timeline_state(self, s: dict, copiar: bool = True) -> None:
        """Pone ese estado. copiar (por defecto): lo nuevo no comparte listas ni diccionarios con s (s puede ser un paso
        del historial, compartido y de solo lectura) y los objetos que no cambiaron se REUTILIZAN (⚡ deshacer: con 2500
        clips ya no se rehacen todos). copiar=False: datos recién leídos de un archivo (from_dict), tal cual."""
        self.__dict__.pop("_lect_rev", None)       # (clips nuevos: lo memorizado en lectura() ya no vale)
        self.name = s.get("name", self.name)
        self.width = int(s.get("width", self.width))
        self.height = int(s.get("height", self.height))
        self.fps = float(s.get("fps", self.fps))
        self.tracks = _rehacer(Track, s.get("tracks", []), self.tracks, copiar)
        self.clips = {c.id: c for c in _rehacer(Clip, s.get("clips", []), self.clips.values(), copiar)}
        self.markers = _rehacer(Marker, s.get("markers", []), self.markers, copiar)
        self.suggestions = _rehacer(Suggestion, s.get("suggestions", []), self.suggestions, copiar)
        self.subtitles = _build(SubtitleStyle, s.get("subtitles", {}), copiar)
        self.loudnorm = bool(s.get("loudnorm", True))
        self.format = s.get("project_type", "short" if self.height > self.width else "youtube")
        self.edits = json.loads(json.dumps(s.get("edits") or []))
        self.compounds = json.loads(json.dumps(s.get("compounds") or {}))
        self.annotations = json.loads(json.dumps(s.get("annotations") or []))
        self.cut_ok = [str(k) for k in (s.get("cut_ok") or [])]
        self.kw_choices = {str(k): str(v) for k, v in (s.get("kw_choices") or {}).items()}
        self.review_ok = [str(k) for k in (s.get("review_ok") or [])]
        self.scenes = json.loads(json.dumps(s.get("scenes") or {}))

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
        p.apply_timeline_state(d, copiar=False)    # (datos recién leídos: no hace falta copiarlos)
        media = (_build(MediaItem, m) for m in d.get("media", []))
        p.media = {m.id: m for m in media}
        p.transcripts = {k: v for k, v in d.get("transcripts", {}).items() if k in p.media}
        p.favorites = [f for f in d.get("favorites", []) if f.get("media_id") in p.media]
        p.thumbnails = dict(d.get("thumbnails", {}))
        p.mark_in, p.mark_out = (list(d.get("marks") or [None, None]) + [None, None])[:2]
        from . import curves                       # 〰 proyectos de antes: cada pieza, solo los puntos de su tramo
        curves.podar(p)
        return p

    def reparar_vinculos(self) -> int:
        """Proyectos guardados con el fallo de «✂ Eliminar silencio» (cientos de trozos con UN mismo vínculo, que
        al hacer clic selecciona toda la narración): dentro de cada vínculo con más de 2 clips, se agrupa por inicio
        y duración (cada imagen con su sonido) y cada grupo recibe un vínculo propio; un grupo suelto queda sin vínculo.
        Devuelve cuántos clips cambiaron."""
        por_vinculo: dict[str, list[Clip]] = {}
        for c in self.clips.values():
            if c.link:
                por_vinculo.setdefault(c.link, []).append(c)
        cambiados = 0
        for grupo in por_vinculo.values():
            if len(grupo) <= 2:
                continue
            por_tiempo: dict[tuple, list[Clip]] = {}
            for c in grupo:
                por_tiempo.setdefault((round(c.start, 3), round(c.duration, 3)), []).append(c)
            if len(por_tiempo) == 1:            # todos en el mismo sitio (p. ej. imagen + dos sonidos): está bien
                continue
            for miembros in por_tiempo.values():
                nuevo = new_id() if len(miembros) > 1 else ""
                for c in miembros:
                    if c.link != nuevo:
                        c.link = nuevo
                        cambiados += 1
        return cambiados

    # ---- consultas ----
    def memo(self) -> dict | None:
        """⚡ Dentro de lectura(): un diccionario para guardar lo calculado (se tira al cambiar el proyecto)."""
        m = self.__dict__.get("_lect")
        return m[2] if m is not None and len(m) > 2 else None

    def duration(self) -> float:
        ex = self.memo()
        if ex is not None:
            d = ex.get("dur")
            if d is None:
                d = ex["dur"] = max((c.end for c in self.clips.values()), default=0.0)
            return d
        return max((c.end for c in self.clips.values()), default=0.0)

    def track(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def track_index(self, track_id: str) -> int:
        for i, t in enumerate(self.tracks):
            if t.id == track_id:
                return i
        return -1

    def clips_on(self, track_id: str) -> list[Clip]:
        memo = self.__dict__.get("_lect")
        if memo is not None:                     # ⚡ dentro de lectura(): ordenado una vez (ver lectura)
            por = memo[1]
            if por is None:
                por = {}
                for c in self.clips.values():
                    por.setdefault(c.track_id, []).append(c)
                for v in por.values():
                    v.sort(key=lambda c: c.start)
                memo[1] = por
            return list(por.get(track_id, ()))
        return sorted((c for c in self.clips.values() if c.track_id == track_id), key=lambda c: c.start)

    def clip_at(self, track_id: str, t: float) -> Clip | None:
        for c in self.clips_on(track_id):
            if c.start > t:
                break                            # (ordenados por inicio: los demás empiezan después)
            if t < c.end:
                return c
        return None

    def lectura(self, rev=None):
        """⚡ Para pintar la línea de tiempo o hacer sonar el visor (SOLO leer): clips_on/clip_at ordenan los clips una
        vez y no en cada llamada (con 3000 clips eran ~13 ordenaciones por fotograma). rev = versión del proyecto
        (ProjectController.rev): con la misma versión se reutiliza entre llamadas; sin rev, solo dentro del bloque."""
        return _Lectura(self, rev)

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
