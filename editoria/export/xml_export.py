"""
⇄ Llevar el proyecto a DaVinci Resolve, Premiere Pro o Final Cut 7 (XML «xmeml» versión 5, el formato que los
tres abren: Archivo → Importar → Línea de tiempo / XML).

Lo que viaja: todas las pistas de video y audio con sus clips (archivo, dónde empieza, cuánto dura), clips
desactivados, velocidad y reversa (Time Remap), volumen (en dB), opacidad, transiciones (disolver, fundido a negro…),
los marcadores y los vínculos imagen/sonido. Lo que NO viaja (cada editor lo hace a su manera): textos de Reclaimer,
efectos, color, zoom/encuadre y curvas; la lista sale en `notes` para avisarte.

  export_xml(project, ruta) -> {"clips": n, "notes": [...]}
"""
from __future__ import annotations

import math
import os
import urllib.parse
from xml.sax.saxutils import escape

from ..core.model import KIND_AUDIO, KIND_IMAGE, KIND_VIDEO, TRACK_AUDIO, TRACK_VIDEO, Project


def _rate(fps: float) -> tuple[int, bool]:
    """(timebase, ntsc): 29,97 → (30, TRUE); 23,976 → (24, TRUE); 25 → (25, FALSE)."""
    fps = float(fps or 30.0)
    base = int(round(fps))
    ntsc = abs(fps - base) > 0.005 and abs(fps * 1001 / 1000 - base) < 0.02
    return max(1, base), ntsc


def _rate_xml(fps: float) -> str:
    tb, ntsc = _rate(fps)
    return f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc></rate>"


def _url(path: str) -> str:
    """file://localhost/D:/carpeta/archivo.mp4 (como lo escriben Premiere y Resolve en Windows)."""
    p = os.path.abspath(path).replace("\\", "/")
    return "file://localhost/" + urllib.parse.quote(p.lstrip("/"), safe="/:")


def _db(vol: float) -> float:
    return -96.0 if vol <= 0.0001 else round(20 * math.log10(vol), 2)


TRANS_NAMES = {          # Reclaimer → nombre del efecto en Premiere / Resolve
    "fadeblack": ("Dip to Color Dissolve", "Dissolve"),
    "fadewhite": ("Dip to Color Dissolve", "Dissolve"),
    "wipeleft": ("Edge Wipe", "Wipe"),
    "smoothleft": ("Edge Wipe", "Wipe"),
}


def export_xml(p: Project, path: str) -> dict:
    from ..core import transitions as TR
    fps = float(p.fps or 30.0)
    fr = lambda s: int(round(float(s) * fps))             # noqa: E731 - segundos → fotogramas de la secuencia
    notes: set[str] = set()
    files_done: set[str] = set()
    file_ids: dict[str, str] = {}
    out: list[str] = []
    w = out.append

    def file_xml(m, mediatype: str) -> str:
        fid = file_ids.setdefault(m.id, f"file-{len(file_ids) + 1}")
        if fid in files_done:
            return f'<file id="{fid}"/>'
        files_done.add(fid)
        dur = fr(m.duration or 0) if m.kind != KIND_IMAGE else fr(3600)
        mfps = float(m.fps or fps)
        parts = [f'<file id="{fid}"><name>{escape(m.name or os.path.basename(m.path))}</name>',
                 f"<pathurl>{escape(_url(m.path))}</pathurl>", _rate_xml(mfps), f"<duration>{dur}</duration>",
                 "<media>"]
        if m.kind in (KIND_VIDEO, KIND_IMAGE):
            parts.append(f"<video><samplecharacteristics>{_rate_xml(mfps)}<width>{int(m.width or p.width)}</width>"
                         f"<height>{int(m.height or p.height)}</height></samplecharacteristics></video>")
        if m.kind == KIND_AUDIO or (m.kind == KIND_VIDEO and m.has_audio):
            ch = int(m.channels or 2)
            parts.append(f"<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate>"
                         f"</samplecharacteristics><channelcount>{ch}</channelcount></audio>")
        parts.append("</media></file>")
        return "".join(parts)

    clip_ids: dict[str, str] = {}
    for c in p.clips.values():
        clip_ids[c.id] = f"clipitem-{len(clip_ids) + 1}"
    links: dict[str, list] = {}
    for c in p.clips.values():
        if c.link:
            links.setdefault(c.link, []).append(c)

    def clip_xml(c, mediatype: str) -> str:
        m = p.media_of(c)
        start, end = fr(c.start), fr(c.end)
        if c.speed <= 0:                                  # fotograma congelado: un trozo de 1 fotograma estirado
            src_in, src_out = fr(c.source_in), fr(c.source_in) + 1
            notes.add("Los fotogramas congelados van como un clip de 1 fotograma (estíralo con «Freeze Frame»).")
        elif m is not None and m.kind == KIND_IMAGE:
            src_in, src_out = 0, end - start
        else:
            src_in = fr(c.source_in)
            src_out = src_in + max(1, int(round(c.duration * c.speed * fps)))
        parts = [f'<clipitem id="{clip_ids[c.id]}"><name>{escape(m.name if m else c.id)}</name>',
                 f"<enabled>{'TRUE' if c.enabled else 'FALSE'}</enabled>",
                 f"<duration>{fr(m.duration or c.duration) if m and m.kind != KIND_IMAGE else fr(3600)}</duration>",
                 _rate_xml(fps), f"<start>{start}</start><end>{end}</end><in>{src_in}</in><out>{src_out}</out>",
                 file_xml(m, mediatype)]
        if mediatype == "audio":
            parts.append("<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>")
        if (c.speed > 0 and abs(c.speed - 1) > 1e-6) or c.reverse:
            parts.append("<filter><effect><name>Time Remap</name><effectid>timeremap</effectid>"
                         "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
                         f"<mediatype>video</mediatype><parameter><parameterid>speed</parameterid><name>speed</name>"
                         f"<valuemin>-100000</valuemin><valuemax>100000</valuemax><value>{round(c.speed * 100, 3)}"
                         f"</value></parameter><parameter><parameterid>reverse</parameterid><name>reverse</name>"
                         f"<value>{'TRUE' if c.reverse else 'FALSE'}</value></parameter></effect></filter>")
        if mediatype == "audio" and abs(c.volume - 1) > 1e-4:
            parts.append("<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid>"
                         "<effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype>"
                         "<mediatype>audio</mediatype><parameter><parameterid>level</parameterid><name>Level</name>"
                         f"<valuemin>0</valuemin><valuemax>3.98109</valuemax><value>{round(c.volume, 5)}</value>"
                         "</parameter></effect></filter>")
        if mediatype == "video" and abs(c.opacity - 1) > 1e-4:
            parts.append("<filter><effect><name>Opacity</name><effectid>opacity</effectid>"
                         "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
                         "<mediatype>video</mediatype><parameter><parameterid>opacity</parameterid><name>opacity</name>"
                         f"<valuemin>0</valuemin><valuemax>100</valuemax><value>{round(c.opacity * 100, 2)}</value>"
                         "</parameter></effect></filter>")
        for x in links.get(c.link, []) if c.link else []:
            xtr = p.track(x.track_id)
            if xtr is None:
                continue
            parts.append(f"<link><linkclipref>{clip_ids[x.id]}</linkclipref><mediatype>"
                         f"{'video' if xtr.kind == TRACK_VIDEO else 'audio'}</mediatype></link>")
        if c.color or c.zoom_kf or c.layout or c.layout_kf or c.vol_kf or c.op_kf or c.eq or (c.fx and any(
                k != "trans" for k in c.fx)):
            notes.add("Color, encuadre/zoom, curvas, ecualizador y efectos de Reclaimer no viajan: rehazlos allí.")
        parts.append("</clipitem>")
        return "".join(parts)

    def trans_xml(left, right, t) -> str:
        cut = fr(right.start)
        half = max(1, fr(float(t["dur"]) / 2))
        name, cat = TRANS_NAMES.get(t["type"], ("Cross Dissolve", "Dissolve"))
        if t["type"] not in TRANS_NAMES and t["type"] not in ("fade", "dissolve"):
            notes.add("Las transiciones especiales (deslizar, zoom, círculo…) van como «Cross Dissolve»: cámbialas allí "
                      "si quieres la misma.")
        return (f"<transitionitem>{_rate_xml(fps)}<start>{cut - half}</start><end>{cut + half}</end>"
                f"<alignment>center</alignment><effect><name>{name}</name><effectid>{name}</effectid>"
                f"<effectcategory>{cat}</effectcategory><effecttype>transition</effecttype>"
                f"<mediatype>video</mediatype></effect></transitionitem>")

    n_clips = 0
    vtracks = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    atracks = [t for t in p.tracks if t.kind == TRACK_AUDIO]
    total = fr(p.duration())
    w('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5">')
    w(f"<sequence id=\"sequence-1\"><name>{escape(p.name or 'Reclaimer')}</name><duration>{total}</duration>")
    w(_rate_xml(fps))
    w(f"<timecode>{_rate_xml(fps)}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat>"
      f"</timecode>")
    w("<media><video><format><samplecharacteristics>" + _rate_xml(fps) +
      f"<width>{int(p.width)}</width><height>{int(p.height)}</height><pixelaspectratio>square</pixelaspectratio>"
      "</samplecharacteristics></format>")
    for tr in reversed(vtracks):        # (en Reclaimer la primera pista es la de ARRIBA; en XML, V1 abajo)
        w(f"<track><enabled>{'FALSE' if tr.hidden else 'TRUE'}</enabled><locked>{'TRUE' if tr.locked else 'FALSE'}"
          "</locked>")
        clips = p.clips_on(tr.id)
        trans = {right.id: (left, right, t) for left, right, t in TR.pairs(p, tr.id)}
        for c in clips:
            if c.text is not None:
                notes.add("Los textos de Reclaimer no viajan (haz los títulos en el otro editor).")
                continue
            if p.media_of(c) is None:
                continue
            if c.id in trans:
                w(trans_xml(*trans[c.id]))
            w(clip_xml(c, "video"))
            n_clips += 1
        w("</track>")
    w("</video><audio>")
    for tr in atracks:
        w(f"<track><enabled>{'FALSE' if tr.muted else 'TRUE'}</enabled><locked>{'TRUE' if tr.locked else 'FALSE'}"
          "</locked>")
        for c in p.clips_on(tr.id):
            m = p.media_of(c)
            if m is None or c.text is not None:
                continue
            w(clip_xml(c, "audio"))
            n_clips += 1
        if tr.fx:
            notes.add("Los efectos de pista de audio (mejora de voz, compresor…) no viajan.")
        w("</track>")
    w("</audio></media>")
    for mk in p.markers:
        if mk.kind == "topic" and mk.end is not None:
            w(f"<marker><name>{escape(mk.label or '')}</name><comment></comment><in>{fr(mk.time)}</in>"
              f"<out>{fr(mk.end)}</out></marker>")
        else:
            w(f"<marker><name>{escape(mk.label or '')}</name><comment></comment><in>{fr(mk.time)}</in>"
              f"<out>-1</out></marker>")
    w("</sequence></xmeml>\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out))
    os.replace(tmp, path)
    return {"clips": n_clips, "notes": sorted(notes)}
