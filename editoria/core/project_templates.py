"""
📋 Plantillas de proyecto: la configuración de un proyecto guardada para usarla en otros videos del mismo tipo.

Guarda: formato (YouTube / Short / Edit) con su resolución y fotogramas, las pistas con sus ajustes de audio (efectos,
papel, bajar la música al hablar), el estilo de subtítulos y el normalizado de volumen final.
NO guarda nunca clips, medios, marcadores, transcripciones ni sugerencias: eso es de cada proyecto.

Se guardan en datos/plantillas_proyecto/<nombre>.json. Sin Qt: se puede probar sin ventanas.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import time
from pathlib import Path

from .model import FORMATS, TRACK_AUDIO, TRACK_VIDEO, Project, SubtitleStyle, Track, new_id
from .paths import app_data_dir

VERSION = 1
# Del estilo de subtítulos no se guarda la narración de la que salen ni si están encendidos (son de cada proyecto).
SUB_SKIP = ("media_id", "enabled")


def templates_dir() -> Path:
    d = app_data_dir() / "plantillas_proyecto"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_name(name: str) -> str:
    """Nombre seguro para un archivo de Windows."""
    n = re.sub(r'[\\/:*?"<>|]+', "-", str(name)).strip(" .")
    return n[:80] or "Plantilla"


def template_path(name: str) -> str:
    return str(templates_dir() / f"{clean_name(name)}.json")


def capture(p: Project, name: str) -> dict:
    """La configuración del proyecto como diccionario (sin clips ni medios)."""
    sub = {k: copy.deepcopy(v) for k, v in dataclasses.asdict(p.subtitles).items() if k not in SUB_SKIP}
    return {
        "plantilla": VERSION,
        "nombre": str(name),
        "creada": time.strftime("%Y-%m-%d %H:%M"),
        "formato": p.format,
        "ancho": p.width,
        "alto": p.height,
        "fps": p.fps,
        "normalizar_volumen": bool(p.loudnorm),
        "pistas": [{"nombre": t.name, "tipo": t.kind, "papel": t.role,
                    "efectos": copy.deepcopy(t.fx or {}), "bajar_musica_db": t.duck_db}
                   for t in p.tracks if t.kind in (TRACK_VIDEO, TRACK_AUDIO)],
        "subtitulos": sub,
    }


def save(p: Project, name: str) -> str:
    """Guarda la plantilla y devuelve su ruta. Si ya existía, la sustituye."""
    path = Path(template_path(name))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(capture(p, name), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def load(path: str) -> dict:
    """Lee una plantilla. Lanza ValueError si el archivo no es una plantilla de Reclaimer."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "pistas" not in data:
        raise ValueError("Ese archivo no es una plantilla de proyecto.")
    return data


def list_templates() -> list[dict]:
    """Plantillas guardadas: [{nombre, ruta, formato}], por nombre."""
    out = []
    for f in sorted(templates_dir().glob("*.json"), key=lambda x: x.stem.lower()):
        try:
            d = load(str(f))
        except (OSError, ValueError):
            continue
        out.append({"nombre": str(d.get("nombre") or f.stem), "ruta": str(f),
                    "formato": str(d.get("formato") or "youtube")})
    return out


def apply(p: Project, tpl: dict) -> None:
    """Pone la configuración de la plantilla en un proyecto NUEVO (sin clips). Pensado para ir dentro de un paso
    de deshacer. No toca clips, medios ni el nombre del proyecto."""
    if p.clips:
        raise ValueError("Una plantilla solo se aplica a un proyecto vacío.")
    fmt = str(tpl.get("formato") or "youtube")
    if fmt not in FORMATS:
        fmt = "youtube"
    _label, w, h = FORMATS[fmt]
    p.format = fmt
    p.width = int(tpl.get("ancho") or w)
    p.height = int(tpl.get("alto") or h)
    p.fps = float(tpl.get("fps") or 60.0)
    p.loudnorm = bool(tpl.get("normalizar_volumen", True))

    tracks = []
    for d in tpl.get("pistas") or []:
        kind = d.get("tipo")
        if kind not in (TRACK_VIDEO, TRACK_AUDIO):
            continue
        tracks.append(Track(new_id(), kind, str(d.get("nombre") or kind), role=str(d.get("papel") or ""),
                            fx=copy.deepcopy(d.get("efectos") or {}), duck_db=d.get("bajar_musica_db")))
    p.tracks = tracks or Project.new().tracks

    base = dataclasses.asdict(SubtitleStyle())
    st = {k: copy.deepcopy(v) for k, v in (tpl.get("subtitulos") or {}).items() if k in base and k not in SUB_SKIP}
    # Los subtítulos quedan con el estilo de la plantilla, apagados hasta elegir su narración (como en cada proyecto).
    p.subtitles = SubtitleStyle(**{**base, **st, "enabled": False, "media_id": ""})
