"""
📦 Recopilar proyecto: una COPIA del proyecto con todos sus archivos en una carpeta (para respaldarlo, llevarlo a otro
disco u otro PC). Tu proyecto y tus archivos originales no se tocan.

  · «Completos»: cada archivo se copia tal cual (rápido y exacto).
  · «Solo lo que se usa»: de los videos largos (p. ej. grabaciones de OBS de 10 GB) solo se guardan los trozos que
    usan tus clips, con unos segundos de margen, unidos en un archivo más pequeño (se vuelven a codificar en alta
    calidad, con TODAS sus pistas de audio). Los tiempos de los clips, claves, transcripción y momentos favoritos se
    ajustan solos al archivo nuevo.

Resultado: <destino>/<nombre> (recopilado)/<nombre>.eia y la subcarpeta «Medios». Al abrir ese proyecto, si los
archivos no están donde decía, se buscan en su carpeta «Medios» (así la carpeta se puede mover entera).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from . import media as media_tools
from ..ai.base import Cancelled
from .model import KIND_VIDEO, Project

MARGIN = 2.0           # segundos de margen alrededor de cada trozo usado
WORTH = 0.75           # si los trozos son más del 75 % del video, se copia entero (no compensa)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _clips_with_inner(p: Project) -> list[dict]:
    """Todos los clips (también los de dentro de los clips compuestos), como diccionarios."""
    from dataclasses import asdict
    out = [asdict(c) for c in p.clips.values()]
    for comp in (p.compounds or {}).values():
        out += [dict(c) for c in comp.get("clips", [])]
    return out


def used_media(p: Project, include_unused: bool = False) -> list[str]:
    ids = set(p.media) if include_unused else set()
    for c in _clips_with_inner(p):
        if c.get("media_id") in p.media:
            ids.add(c["media_id"])
    for mid in list(ids):                    # 🎙/🎮 pistas separadas de OBS y compuestos: van con su video
        m = p.media.get(mid)
        for t in (m.audio_tracks if m else []) or []:
            if t.get("media_id") in p.media:
                ids.add(t["media_id"])
    for mid in (p.compounds or {}):
        if mid in p.media and any(c.get("media_id") == mid for c in _clips_with_inner(p)):
            ids.add(mid)
    return sorted(ids, key=lambda i: p.media[i].name.lower())


def used_ranges(p: Project, media_id: str, margin: float = MARGIN) -> list[tuple[float, float]]:
    """Trozos del archivo que usan los clips (con margen), unidos si se tocan."""
    m = p.media[media_id]
    spans = []
    for c in _clips_with_inner(p):
        if c.get("media_id") != media_id:
            continue
        a = float(c.get("source_in", 0.0))
        speed = float(c.get("speed", 1.0))
        b = a + (float(c.get("duration", 0.0)) * speed if speed > 0 else 0.1)
        spans.append((max(0.0, a - margin), min(m.duration or b + margin, b + margin)))
    spans.sort()
    out: list[list[float]] = []
    for a, b in spans:
        if out and a <= out[-1][1] + 0.5:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def plan(p: Project, trim: bool, include_unused: bool = False) -> list[dict]:
    """[{"media_id", "mode": "copy"|"trim", "ranges", "bytes" (estimado)}]"""
    out = []
    for mid in used_media(p, include_unused):
        m = p.media[mid]
        size = os.path.getsize(m.path) if os.path.exists(m.path) else 0
        item = {"media_id": mid, "mode": "copy", "ranges": [], "bytes": size, "exists": os.path.exists(m.path)}
        if trim and m.kind == KIND_VIDEO and m.duration > 0 and not (p.compounds or {}).get(mid):
            rs = used_ranges(p, mid)
            used = sum(b - a for a, b in rs)
            if rs and used < WORTH * m.duration:
                item.update(mode="trim", ranges=rs, bytes=int(size * used / m.duration * 1.2))
        out.append(item)
    return out


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', " ", name).strip() or "archivo"


def _unique(folder: str, name: str, taken: set) -> str:
    stem, ext = os.path.splitext(name)
    k, cand = 1, name
    while cand.lower() in taken or os.path.exists(os.path.join(folder, cand)):
        k += 1
        cand = f"{stem} ({k}){ext}"
    taken.add(cand.lower())
    return os.path.join(folder, cand)


def _mapper(ranges: list[tuple[float, float]], durs: list[float]):
    """Segundo del archivo original → segundo del archivo recortado (lo que cae entre trozos, al borde más cercano)."""
    offs, o = [], 0.0
    for d in durs:
        offs.append(o)
        o += d

    def f(t: float) -> float:
        best = None
        for (a, b), off, d in zip(ranges, offs, durs):
            if a - 1e-6 <= t <= b + 1e-6:
                return round(off + min(max(t - a, 0.0), d), 4)
            dist = a - t if t < a else t - b
            edge = off if t < a else off + d
            if best is None or dist < best[0]:
                best = (dist, edge)
        return round(best[1], 4) if best else t

    def inside(t: float) -> bool:
        return any(a - 1e-6 <= t <= b + 1e-6 for a, b in ranges)
    return f, inside, o


def _remap_clip(c, f):
    """Tiempos del archivo de un clip (objeto o diccionario) → los del archivo recortado."""
    get = (lambda k: c.get(k)) if isinstance(c, dict) else (lambda k: getattr(c, k))
    put = c.__setitem__ if isinstance(c, dict) else (lambda k, v: setattr(c, k, v))
    put("source_in", f(float(get("source_in"))))
    for key in ("zoom_kf", "layout_kf", "vol_kf", "op_kf"):
        kf = get(key) or []
        put(key, [dict(k, t=f(float(k["t"]))) for k in kf])


def _encode_piece(src: str, a: float, b: float, out: str, cancelled) -> float:
    """Un trozo [a, b] del video, con la imagen y TODAS sus pistas de audio, en alta calidad. Devuelve su duración."""
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-ss", f"{a:.3f}", "-i", src, "-t", f"{b - a:.3f}",
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-avoid_negative_ts", "make_zero", out]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    while proc.poll() is None:
        if cancelled():
            proc.kill()
            proc.wait()
            raise Cancelled()
        try:
            proc.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            pass
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr.read() or b"").decode(errors="replace")[-400:] or "FFmpeg falló.")
    return float(media_tools.probe(out)["duration"])


def _trim_file(src: str, ranges, out: str, tmp: str, cancelled, report) -> list[float]:
    pieces, durs = [], []
    for i, (a, b) in enumerate(ranges):
        report(i / max(1, len(ranges)), f"trozo {i + 1} de {len(ranges)}")
        piece = os.path.join(tmp, f"trozo_{i:04d}.mp4")
        durs.append(_encode_piece(src, a, b, piece, cancelled))
        pieces.append(piece)
    if len(pieces) == 1:
        os.replace(pieces[0], out)
        return durs
    lst = os.path.join(tmp, "lista.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for x in pieces:
            fh.write("file '" + x.replace("\\", "/").replace("'", "'\\''") + "'\n")
    r = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-map", "0", "-c", "copy", out], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[-400:])
    return durs


def run(project: Project, dest: str, trim: bool, include_unused: bool, progress, cancelled) -> str:
    """Hace la copia. progress(fracción, texto); cancelled() -> bool. Devuelve la ruta del proyecto nuevo."""
    p = Project.from_dict(json.loads(json.dumps(project.to_dict(), default=_json_default)))
    name = _safe(p.name or "Proyecto")
    dest = os.path.abspath(dest)     # rutas completas: la lista de trozos de FFmpeg y el proyecto nuevo las necesitan
    root = os.path.join(dest, f"{name} (recopilado)")
    k = 2
    while os.path.exists(root):
        root = os.path.join(dest, f"{name} (recopilado {k})")
        k += 1
    medios = os.path.join(root, "Medios")
    tmp = os.path.join(root, ".trabajo")
    os.makedirs(medios)
    os.makedirs(tmp)
    items = plan(p, trim, include_unused)
    total = sum(max(1, it["bytes"]) for it in items) or 1
    done_b = 0
    taken: set = set()
    missing = []
    try:
        for it in items:
            if cancelled():
                raise Cancelled()
            m = p.media[it["media_id"]]
            frac0 = done_b / total
            span = max(1, it["bytes"]) / total

            def report(f, txt, m=m, frac0=frac0, span=span):
                progress(min(0.99, frac0 + span * f), f"📦 {m.name}: {txt}")
            if not it["exists"]:
                missing.append(m.name)
                done_b += max(1, it["bytes"])
                continue
            if it["mode"] == "trim":
                stem = os.path.splitext(os.path.basename(m.path))[0]
                out = _unique(medios, _safe(stem) + " (trozos usados).mp4", taken)
                durs = _trim_file(m.path, it["ranges"], out, tmp, cancelled, report)
                f, inside, new_len = _mapper(it["ranges"], durs)
                for c in p.clips.values():
                    if c.media_id == m.id:
                        _remap_clip(c, f)
                for comp in (p.compounds or {}).values():
                    for c in comp.get("clips", []):
                        if c.get("media_id") == m.id:
                            _remap_clip(c, f)
                _remap_media(p, m, f, inside)
                m.duration = round(new_len, 3)
                m.ai_analyzed = False            # sus análisis eran del archivo entero: se rehacen
                m.path = out
            else:
                out = _unique(medios, os.path.basename(m.path), taken)
                _copy(m.path, out, cancelled, report)
                m.path = out
            done_b += max(1, it["bytes"])
        if not include_unused:                  # la biblioteca de la copia: solo lo que se usa
            keep = {it["media_id"] for it in items}
            p.media = {k_: v for k_, v in p.media.items() if k_ in keep}
            p.transcripts = {k_: v for k_, v in p.transcripts.items() if k_ in keep}
            p.favorites = [x for x in p.favorites if x.get("media_id") in keep]
        path = os.path.join(root, f"{name}.eia")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(p.to_dict(), fh, ensure_ascii=False, indent=1, default=_json_default)
        if missing:
            with open(os.path.join(root, "FALTAN.txt"), "w", encoding="utf-8") as fh:
                fh.write("Estos archivos no se encontraron al recopilar (no están en la copia):\n" +
                         "\n".join(missing) + "\n")
        progress(1.0, "📦 Listo")
        return path
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)     # cancelado o falló: no deja media copia a medias
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _remap_media(p: Project, m, f, inside):
    """Transcripción, momentos favoritos y tramos elegidos del archivo, en los tiempos del recortado."""
    tr = p.transcripts.get(m.id)
    if tr and tr.get("words"):
        old = tr["words"]
        new_idx, words = {}, []
        for i, w in enumerate(old):
            if inside(float(w[0])) and inside(float(w[1])):
                new_idx[i] = len(words)
                words.append([f(float(w[0])), f(float(w[1]))] + list(w[2:]))
        segs = []
        for s in tr.get("segments") or []:
            kept = [new_idx[i] for i in range(int(s[2]), int(s[3])) if i in new_idx]
            if kept:
                segs.append([words[kept[0]][0], words[kept[-1]][1], kept[0], kept[-1] + 1])
        p.transcripts[m.id] = dict(tr, words=words, segments=segs)
    favs = []
    for x in p.favorites:
        if x.get("media_id") != m.id:
            favs.append(x)
        elif inside(float(x["start"])) or inside(float(x["end"])):
            favs.append(dict(x, start=f(float(x["start"])), end=f(float(x["end"]))))
    p.favorites = favs
    m.edit_ranges = [[f(float(a)), f(float(b))] for a, b in (m.edit_ranges or []) if inside(float(a)) or inside(float(b))]


def _copy(src: str, dst: str, cancelled, report=None, chunk: int = 16 * 1024 * 1024):
    size = max(1, os.path.getsize(src))
    done = 0
    with open(src, "rb") as a, open(dst + ".parcial", "wb") as b:
        while True:
            if cancelled():
                b.close()
                os.remove(dst + ".parcial")
                raise Cancelled()
            buf = a.read(chunk)
            if not buf:
                break
            b.write(buf)
            done += len(buf)
            if report:
                report(done / size, f"copiando… {done / size:.0%}")
    os.replace(dst + ".parcial", dst)
    shutil.copystat(src, dst)


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
    except ImportError:
        pass
    raise TypeError(f"{type(o).__name__} no se puede guardar")


def find_in_media_folder(project_path: str, path: str) -> str | None:
    """Si el archivo no está donde decía el proyecto: ¿está en la carpeta «Medios» junto al proyecto?"""
    if not project_path:
        return None
    cand = os.path.join(os.path.dirname(project_path), "Medios", os.path.basename(path))
    return cand if os.path.exists(cand) else None

