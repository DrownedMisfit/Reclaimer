"""
Prueba de «Entender mi biblioteca a fondo» con material real (si existe):
el Jefe Maestro debe encontrarse en el Halo edit y no en un Short de Gears.
Ejecutar:  .venv/Scripts/python.exe tests/test_understand.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)

from editoria.ai import broll_selection as B  # noqa: E402
from editoria.ai import library_understanding as LU  # noqa: E402
from editoria.core import media as media_tools  # noqa: E402

HALO = os.environ.get("RECLAIMER_VIDEO_1", "")    # un video de prueba tuyo (no viene con Reclaimer)
GEARS = os.environ.get("RECLAIMER_VIDEO_2", "")   # otro video de prueba


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    if not (os.path.exists(HALO) and os.path.exists(GEARS)):
        print("(sin material real: prueba omitida)")
        return
    ff = media_tools.ffmpeg()
    # Una imagen de referencia con nombre: «jefe maestro.png» (el casco, del final del Halo edit)
    ref = os.path.join(out, "jefe maestro.png")
    media_tools.run_quiet([ff, "-nostdin", "-v", "error", "-y", "-ss", "37.0", "-i", HALO, "-frames:v", "1",
                           "-vf", "crop=1080:1080:0:420", ref])
    assert os.path.exists(ref)

    # 1) Nombres propios de la narración
    text = ("Hoy hablamos de Halo. El Jefe Maestro vuelve en este remake, y Cortana también. "
            "Pero el gameplay se siente igual que antes, con los mismos enemigos.")
    words, t = [], 0.0
    for w in text.split():
        words.append([t, t + 0.3, w, 0.99])
        t += 0.35
    names = LU.narration_names(words)
    assert "Jefe Maestro" in names and "Cortana" in names, names
    print("✓ nombres propios de la narración:", names)

    # 2) Análisis a fondo (cada segundo, planos)
    media = []
    data = {}
    t0 = time.time()
    for mid, path, kind in (("halo", HALO, "video"), ("gears", GEARS, "video"), ("ref", ref, "image")):
        info = media_tools.probe(path)
        dur = info["duration"] if kind == "video" else 0.0
        res = LU.analyze_deep(path, kind, dur)
        data[mid] = dict(res, kind=kind, duration=dur)
        media.append({"media_id": mid, "path": path, "kind": kind, "duration": dur,
                      "name": os.path.basename(path), "tags": [], "meta": os.path.basename(path)})
        print(f"  {os.path.basename(path)[:34]:34s} {len(res['times']) // 2:4d} s analizados · "
              f"{len(res['shots'])} planos")
    print(f"✓ análisis a fondo en {time.time() - t0:.0f} s")

    # 3) Entidades e índice
    ents = LU.build_entities(media, words, LU.STARTER_GLOSSARY)
    jm = next(e for e in ents if e.name == "Jefe Maestro")
    assert "ref" in jm.refs, "la imagen «jefe maestro.png» enseña cómo es"
    index = LU.build_index(ents, data, {m["media_id"]: m["meta"] for m in media})
    hits = [h for h in index.get("Jefe Maestro", []) if h.media_id != "ref"]
    print("  Jefe Maestro:", [(h.media_id, round(h.time), round(h.score, 1)) for h in hits[:8]])
    assert hits and hits[0].media_id == "halo", "el mejor momento del Jefe Maestro está en el Halo edit"
    assert hits[0].time > 25, hits[0].time   # aparece al final del edit
    in_gears = [h for h in hits[:5] if h.media_id == "gears"]
    assert len(in_gears) <= 1, in_gears
    print("✓ el Jefe Maestro se encuentra en el Halo edit (por parecido con tu imagen), no en Gears")

    # 4) B-roll: al nombrarlo, su plano; si no, gameplay continuo
    clips = [B.ClipInfo("halo", "Halo edit", "video", data["halo"]["duration"], "Cinemáticas", [],
                        data["halo"]["times"], data["halo"]["vecs"], "halo edit"),
             B.ClipInfo("gears", "Gears", "video", data["gears"]["duration"], "Gameplay", [],
                        data["gears"]["times"], data["gears"]["vecs"], "gears gameplay")]
    slots = [{"start": 0.0, "end": 4.0, "text": "Hoy hablamos de este juego.", "topic": "JUGABILIDAD"},
             {"start": 4.0, "end": 8.0, "text": "El Jefe Maestro vuelve en este remake.", "topic": "JUGABILIDAD"},
             {"start": 8.0, "end": 12.0, "text": "Pero se siente igual que antes.", "topic": "JUGABILIDAD"},
             {"start": 12.0, "end": 16.0, "text": "Con los mismos enemigos de siempre.", "topic": "JUGABILIDAD"}]
    st = B.BrollSettings(continuous=True)
    slots = B.propose_understood(slots, clips, st, {}, {"entities": ents, "index": index})
    picks = [(s["candidates"][0]["media_id"], round(s["candidates"][0]["source_in"], 1)) for s in slots]
    print("  B-roll:", picks, "·", [s["candidates"][0]["reason"][:40] for s in slots])
    assert picks[1][0] == "halo" and slots[1].get("entity") == "Jefe Maestro"
    assert picks[0][0] == "gears" and picks[2][0] == "gears" and picks[3][0] == "gears"
    assert picks[2][1] > picks[0][1] and abs(picks[3][1] - picks[2][1] - 4.0) < 0.6, picks
    print("✓ B-roll: al nombrar al Jefe Maestro, su plano; el resto, gameplay continuo (sigue donde iba)")
    print("TODO OK")


if __name__ == "__main__":
    main()
