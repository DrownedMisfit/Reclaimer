"""
Genera un archivo .ass (subtítulos con estilo) que FFmpeg «quema» en el video.

Las medidas usan la resolución del video (PlayResX/PlayResY), así que el tamaño
en % del estilo se traduce directamente a píxeles.
"""
from __future__ import annotations

from ..core.model import SubtitleStyle
from ..core.subtitles import Cue

ALIGN = {"bottom": 2, "middle": 5, "top": 8}


def ass_color(hex_color: str, opacity: float = 1.0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (en ASS, alfa 00 = opaco)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = int(round(255 * (1 - max(0.0, min(1.0, opacity)))))
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _inline_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def metrics(style: SubtitleStyle, height: int) -> tuple[float, float, float]:
    """(tamaño de letra, grosor del contorno, margen vertical) en píxeles."""
    return (style.size / 100 * height, style.outline / 100 * height, style.margin / 100 * height)


def _line_text(cue: Cue, style: SubtitleStyle, active: int | None) -> str:
    """Texto con colores: resaltados fijos y, en karaoke, la palabra que suena."""
    emph = set(style.emphasis)
    normal, hl = _inline_color(style.color), _inline_color(style.highlight)
    lines = []
    for line in cue.lines:
        parts = []
        for w in line:
            text = _escape(w.text)
            if w.index in emph or w.index == active:
                parts.append(f"{{\\1c{hl}}}{text}{{\\1c{normal}}}")
            else:
                parts.append(text)
        lines.append(" ".join(parts))
    return "\\N".join(lines)


def build_ass(cues: list[Cue], style: SubtitleStyle, width: int, height: int) -> str:
    size, outline, margin = metrics(style, height)
    shadow = float(getattr(style, "shadow", 0.0) or 0.0) / 100 * height    # sombra suave (desplazada y difuminada)
    soft = f"{{\\blur{max(1.0, shadow * 0.8):.1f}}}" if shadow > 0 else ""
    if style.box:
        border_style = 3
        outline_col = ass_color(style.box_color, style.box_opacity)
        outline = max(outline, size * 0.18)  # en modo caja, el "contorno" es el relleno de la caja
    else:
        border_style = 1
        outline_col = ass_color(style.outline_color)
    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,{style.font},{size:.1f},{ass_color(style.color)},{ass_color(style.highlight)},"
        f"{outline_col},{'&H60000000' if shadow > 0 else '&H80000000'},{-1 if style.bold else 0},0,0,0,100,100,0,0,"
        f"{border_style},{outline:.1f},{shadow:.1f},{ALIGN.get(style.position, 2)},{int(width * 0.05)},"
        f"{int(width * 0.05)},"
        f"{int(margin)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def event(a: float, b: float, text: str):
        if b > a:
            out.append(f"Dialogue: 0,{_time(a)},{_time(b)},Main,,0,0,0,,{soft}{text}")

    for cue in cues:
        if style.animation == "karaoke":
            words = cue.words
            for i, w in enumerate(words):
                a = cue.start if i == 0 else w.start
                b = words[i + 1].start if i + 1 < len(words) else cue.end
                event(a, b, _line_text(cue, style, w.index))
        else:
            prefix = ""
            if style.animation == "fade":
                prefix = "{\\fad(120,120)}"
            elif style.animation == "pop":
                prefix = "{\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)}"
            event(cue.start, cue.end, prefix + _line_text(cue, style, None))
    return "\n".join(out) + "\n"


# ------------------------------------------------------- textos en pantalla
def title_metrics(text: dict, height: int) -> tuple[float, float]:
    """(tamaño de letra, margen de la caja o grosor del contorno) en píxeles."""
    size = float(text.get("size", 6.0)) / 100 * height
    return size, (size * 0.22 if text.get("box", True) else size * 0.07)


def build_titles_ass(items: list[tuple[float, float, dict]], width: int, height: int) -> str:
    """Textos en pantalla (títulos, etiquetas ORIGINAL/REMAKE…): [(inicio, fin, texto)]."""
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: TOutline,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,5,0,0,0,1",
        "Style: TBox,Arial,60,&H00FFFFFF,&H000000FF,&H66000000,&H80000000,-1,0,0,0,100,100,0,0,3,10,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for a, b, t in items:
        size, border = title_metrics(t, height)
        box = t.get("box", True)
        x, y = float(t.get("x", 0.5)) * width, float(t.get("y", 0.5)) * height
        alpha = int(round(255 * (1 - float(t.get("box_opacity", 0.6)))))
        tags = (f"{{\\an5\\pos({x:.0f},{y:.0f})\\fn{t.get('font', 'Arial')}\\fs{size:.1f}"
                f"\\b{1 if t.get('bold', True) else 0}\\1c{_inline_color(t.get('color', '#FFFFFF'))}"
                f"\\3c{_inline_color(t.get('box_color', '#000000') if box else '#000000')}"
                f"\\3a&H{alpha if box else 0:02X}&\\bord{border:.1f}\\fad(150,150)}}")
        content = _escape(str(t.get("content", ""))).replace("\n", "\\N")
        out.append(f"Dialogue: 1,{_time(a)},{_time(b)},{'TBox' if box else 'TOutline'},,0,0,0,,{tags}{content}")
    return "\n".join(out) + "\n"
