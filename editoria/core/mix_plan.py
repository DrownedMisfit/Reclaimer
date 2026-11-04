"""
🎛 ANALIZAR Y PROPONER MEZCLA (edits y videos con música + diálogo/narración): la IA NO toca nada hasta que tú lo
aceptas. Propone, tramo a tramo y con su motivo, cómo debe ir la música:

  · mientras se habla, la música baja (ducking) — cuánto, según LO QUE SE DICE (si hay transcripción):
      emotivo («lo siento», «adiós», «hermano», «sorry», «goodbye»…) → la música casi desaparece;
      acción / tensión («¡corre!», «¡cuidado!», «fire», «move»…)      → baja poco (la música acompaña);
      lo demás                                                       → lo normal;
    sin transcripción, se detecta dónde hay voz por el volumen de esas pistas;
  · después de una frase emotiva, el silencio sigue siendo «importante»: la música no vuelve de golpe;
  · la forma de la canción (si se puede escuchar): intro suave, pausas suaves, la subida y el drop arriba, el final
    baja poco a poco;
  · tus marcadores mandan: uno llamado «voz» / «diálogo» = prioridad a la voz; «música» = la música arriba;
  · las pistas BLOQUEADAS nunca se tocan; límites máximo y mínimo; velocidad de bajada y subida a tu gusto.

  propose(p, opts, rhythm={media_id: análisis}) -> {"tracks", "items": [{"a","b","db","why","kind"}], "speech"}
  curves(p, items, opts, track_ids) -> {clip_id: vol_kf}   (solo con los tramos que aceptes)
La curva va en Clip.vol_kf (se oye en el visor y se exporta igual). La de antes se guarda en fx["mix_orig"]: volver
a proponer parte de ella y «Quitar la mezcla de la IA» la devuelve.
"""
from __future__ import annotations

import re
import subprocess

import numpy as np

from . import media as media_tools
from .model import KIND_AUDIO, KIND_VIDEO, TRACK_AUDIO, Project

DEFAULTS = {"duck_db": -12.0, "deep_db": -22.0, "action_db": -6.0, "min_db": -30.0, "max_db": 0.0,
            "attack": 0.35, "release": 1.0, "song_shape": True}
STEP = 0.1          # resolución de la curva (s)

EMOTIVE = re.compile(r"\b(lo siento|perd[oó]n(ame)?|adi[oó]s|gracias|te quiero|te amo|hermano|hermana|mam[aá]|"
                     r"pap[aá]|hijo|hija|amor|muer[te]?|morir|muri[oó]|por favor|no me dejes|nunca|siempre|"
                     r"recuerda|perdimos|se fue|lo prometo|promesa|duele|dolor|sorry|goodbye|bye|please|"
                     r"brother|sister|mom|dad|love|dead|die|died|dying|forgive|remember|promise|never|"
                     r"always|miss you|i'm sorry|maria)\b", re.I)
ACTION = re.compile(r"\b(corre|corred|cuidado|vamos|dispara|disparen|fuego|ataca|atacan|granada|abajo|"
                     r"mu[eé]vete|retirada|enemigos?|cubr[ea]te|maldita|maldito|m[aá]talo|r[aá]pido|go|run|"
                     r"move|fire|now|cover|grenade|incoming|get down|shoot|kill|watch out|hurry|attack)\b", re.I)


def _db(g: float) -> float:
    return 20 * np.log10(max(g, 1e-4))


def _gain(db: float) -> float:
    return float(10 ** (db / 20))


def music_tracks(p: Project) -> list[str]:
    """Pistas de música: las marcadas como música (o que bajan al hablar) o con «música» en el nombre."""
    out = [t.id for t in p.tracks if t.kind == TRACK_AUDIO and (t.role == "musica" or t.duck_db is not None
                                                               or "música" in t.name.lower()
                                                               or "musica" in t.name.lower())]
    if not out:      # la pista de audio cuyos clips son canciones (categoría Música)
        for t in p.tracks:
            if t.kind == TRACK_AUDIO and any((p.media_of(c) and p.media_of(c).category.lower().startswith("m")
                                              and "sic" in p.media_of(c).category.lower()) for c in p.clips_on(t.id)):
                out.append(t.id)
    return out


def _voice_words(p: Project, music: set) -> list[tuple[float, float, str]]:
    from .subtitles import timeline_words
    words = []
    mids = {c.media_id for t in p.tracks if t.kind == TRACK_AUDIO and t.id not in music and not t.muted
            for c in p.clips_on(t.id) if c.enabled}
    mids |= {c.media_id for c in p.clips.values() if c.enabled and c.volume > 0 and not c.link
             and p.media_of(c) is not None and p.media_of(c).kind == KIND_VIDEO and p.media_of(c).has_audio}
    for mid in mids:
        if mid in p.transcripts:
            words += [(a, b, w) for a, b, w, _i in timeline_words(p, mid)]
    return sorted(words)


def _voice_activity(p: Project, music: set, cancelled=None, max_total: float = 1800.0) -> list[tuple[float, float]]:
    """Sin transcripción: dónde suena voz/diálogo (volumen de las pistas que no son música)."""
    spans = []
    used = 0.0
    clips = [c for t in p.tracks if t.kind == TRACK_AUDIO and t.id not in music and not t.muted
             for c in p.clips_on(t.id) if c.enabled and c.volume > 0 and c.speed > 0]
    for c in clips:
        m = p.media_of(c)
        if m is None or m.id in p.transcripts or not (m.kind == KIND_AUDIO or m.has_audio):
            continue
        if used > max_total or (cancelled and cancelled()):
            break
        sr = 8000
        r = subprocess.run([media_tools.ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{c.source_in:.3f}", "-i", m.path,
                            "-t", f"{c.src_len:.3f}", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        x = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0
        used += c.src_len
        hop = int(sr * 0.1)
        if len(x) < hop * 3:
            continue
        rms = np.sqrt(np.convolve(x[: len(x) // hop * hop].reshape(-1, hop).var(axis=1), np.ones(3) / 3, "same"))
        thr = max(0.012, np.percentile(rms, 30) * 2.5)
        on = rms > thr
        k = 0
        while k < len(on):
            if on[k]:
                j = k
                while j < len(on) and on[j]:
                    j += 1
                a, b = c.start + k * 0.1 / c.speed, c.start + j * 0.1 / c.speed
                if b - a >= 0.25:
                    spans.append((a, min(b, c.end)))
                k = j
            k += 1
    return sorted(spans)


def _blocks(words, gap: float = 0.8) -> list[dict]:
    out: list[dict] = []
    for a, b, w in words:
        if out and a - out[-1]["b"] <= gap:
            out[-1]["b"] = max(out[-1]["b"], b)
            out[-1]["text"] += " " + w
        else:
            out.append({"a": a, "b": b, "text": w})
    return out


def _mood(text: str) -> str:
    t = text.lower()
    e, a = len(EMOTIVE.findall(t)), len(ACTION.findall(t))
    if e and e >= a:
        return "emotivo"
    if a:
        return "accion"
    return "normal"


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def propose(p: Project, opts: dict | None = None, rhythm: dict | None = None, cancelled=None) -> dict:
    o = dict(DEFAULTS, **(opts or {}))
    tracks = [t for t in (o.get("tracks") or music_tracks(p)) if p.track(t)]
    locked = [t for t in tracks if p.track(t).locked]
    tracks = [t for t in tracks if not p.track(t).locked]
    music = set(o.get("tracks") or music_tracks(p))
    items: list[dict] = []
    words = _voice_words(p, music)
    if words:
        blocks = _blocks(words)
        src = "transcripción"
    else:
        blocks = [{"a": a, "b": b, "text": ""} for a, b in _voice_activity(p, music, cancelled)]
        blocks = _blocks([(x["a"], x["b"], "") for x in blocks], gap=0.6)
        src = "volumen de la voz"
    # Marcadores: prioridad a la voz o a la música
    marks = sorted((m for m in p.markers if m.kind == "marker"), key=lambda m: m.time)
    prio = []
    for i, m in enumerate(marks):
        lab = (m.label or "").lower()
        nxt = m.end if m.end else (marks[i + 1].time if i + 1 < len(marks) else m.time + 5.0)
        if any(w in lab for w in ("voz", "diálogo", "dialogo", "🎙")):
            prio.append((m.time, nxt, "voz"))
        elif any(w in lab for w in ("música", "musica", "🎵")):
            prio.append((m.time, nxt, "musica"))
    for bl in blocks:
        mood = _mood(bl["text"]) if bl["text"] else "normal"
        pr = next((k for a, b, k in prio if a - 0.05 <= bl["a"] < b), None)
        if pr == "musica":
            continue
        db = {"emotivo": o["deep_db"], "accion": o["action_db"], "normal": o["duck_db"]}[mood]
        if pr == "voz":
            db = min(db, o["deep_db"])
        quote = f" «{bl['text'][:40].strip()}{'…' if len(bl['text']) > 40 else ''}»" if bl["text"] else ""
        why = {"emotivo": "frase emotiva: la música casi desaparece",
               "accion": "acción: la música baja poco y acompaña",
               "normal": "se habla: la música baja"}[mood] + quote + (" · tu marcador da prioridad a la voz"
                                                                         if pr == "voz" else "")
        items.append({"a": round(bl["a"], 3), "b": round(bl["b"], 3), "db": float(db), "why": why, "kind": mood})
    # Silencio importante tras una frase emotiva: la música no vuelve de golpe
    emo = [x for x in items if x["kind"] == "emotivo"]
    for x in emo:
        nxt = min([y["a"] for y in items if y["a"] > x["b"]] + [x["b"] + 3.0])
        if nxt - x["b"] >= 0.8:
            items.append({"a": x["b"], "b": round(min(nxt, x["b"] + 3.0), 3), "db": float(o["duck_db"]),
                          "why": "silencio importante después de la frase: la música sigue baja", "kind": "silencio"})
    # La forma de la canción
    if o.get("song_shape"):
        for tid in tracks:
            for c in p.clips_on(tid):
                info = (rhythm or {}).get(c.media_id)
                if not info:
                    continue
                for s in info.get("sections") or []:
                    a = c.start + (float(s["a"]) - c.source_in) / max(c.speed, 1e-3)
                    b = c.start + (float(s["b"]) - c.source_in) / max(c.speed, 1e-3)
                    a, b = max(a, c.start), min(b, c.end)
                    if b - a < 1.0:
                        continue
                    kind = s.get("kind")
                    if kind in ("intro", "break"):
                        items.append({"a": round(a, 3), "b": round(b, 3), "db": -5.0, "kind": "cancion",
                                      "why": ("intro de la canción" if kind == "intro" else "pausa de la canción")
                                      + ": música suave"})
                    elif kind in ("build", "drop"):
                        items.append({"a": round(a, 3), "b": round(b, 3), "db": float(o["max_db"]), "kind": "cancion",
                                      "why": ("la subida" if kind == "build" else "el drop / clímax")
                                      + ": la música protagonista"})
                if c.duration > 8 and not (c.fx or {}).get("fade_out"):
                    a = max(c.start, c.end - 4.0)
                    items.append({"a": round(a, 3), "b": round(c.end, 3), "db": -9.0, "kind": "final",
                                  "why": "final: la música baja poco a poco", "ramp": True})
    items.sort(key=lambda x: x["a"])
    for i, x in enumerate(items):
        x["id"] = i
        x["label"] = f"{_fmt(x['a'])}–{_fmt(x['b'])}  {x['db']:+.0f} dB · {x['why']}"
    return {"tracks": tracks, "locked": locked, "items": items, "source": src, "n_speech": len(blocks)}


def level_db(items: list[dict], t: float, o: dict) -> float:
    """Nivel propuesto (dB) en el instante t: lo de la voz manda sobre la forma de la canción (el mínimo)."""
    att, rel = float(o["attack"]), float(o["release"])
    voice = 0.0
    song = None
    for x in items:
        a, b, db = x["a"], x["b"], x["db"]
        if x.get("kind") in ("cancion", "final"):
            if a <= t <= b:
                if x.get("ramp"):
                    db = db * (t - a) / max(b - a, 1e-6)
                song = db if song is None else min(song, db)
            continue
        if a - att <= t < a:
            w = (t - (a - att)) / att
        elif a <= t <= b:
            w = 1.0
        elif b < t <= b + rel:
            w = 1 - (t - b) / rel
        else:
            continue
        voice = min(voice, db * w)
    base = song if song is not None else 0.0
    return float(np.clip(min(base, voice) if voice < 0 else base, o["min_db"], o["max_db"]))


def curves(p: Project, items: list[dict], opts: dict | None = None, track_ids: list[str] | None = None) -> dict:
    """{clip_id: vol_kf} con los tramos aceptados (sobre la curva que tenía el clip antes de la IA)."""
    from . import curves as CV
    o = dict(DEFAULTS, **(opts or {}))
    out = {}
    for tid in track_ids or []:
        for c in p.clips_on(tid):
            base = (c.fx or {}).get("mix_orig")
            base = base if base is not None else c.vol_kf
            ts = np.arange(c.start, c.end + 1e-6, STEP)
            vals = []
            for t in ts:
                g = _gain(level_db(items, float(t), o))
                s = c.src_at(float(t) - c.start)
                vals.append((round(s, 4), round(g * CV.value_at(base, s), 4)))
            kf = _simplify(vals)
            out[c.id] = kf if any(abs(k["v"] - 1.0) > 1e-3 for k in kf) else []
    return out


def _simplify(vals: list[tuple[float, float]], tol: float = 0.015) -> list[dict]:
    if not vals:
        return []
    vals = sorted(vals)
    keep = [vals[0]]
    for i in range(1, len(vals) - 1):
        a, b, c = keep[-1], vals[i], vals[i + 1]
        u = (b[0] - a[0]) / max(c[0] - a[0], 1e-9)
        if abs(a[1] + (c[1] - a[1]) * u - b[1]) > tol:
            keep.append(b)
    keep.append(vals[-1])
    return [{"t": t, "v": v} for t, v in keep]
