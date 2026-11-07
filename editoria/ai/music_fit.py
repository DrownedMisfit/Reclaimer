"""
Módulo de IA (sin ventanas): AJUSTAR LA MÚSICA A UNA DURACIÓN, por compases.

Como el Remix de Premiere o el AI Music Editor de Resolve: la canción se alarga o se acorta quitando o repitiendo
secciones ENTERAS (bloques de compases), nunca cortando a ciegas. Así:
  · la intro se conserva al principio y el final de la canción al acabar (termina en un final natural);
  · todos los cortes caen al inicio de un compás (el «1»), los de la rejilla de rhythm.analyze;
  · el último trozo puede acabar a mitad de compás con fundido de salida (así cuadra el total exacto).

plan_fit() devuelve [(source_in, duration), …] en segundos DEL ARCHIVO. Si no hay ritmo detectable, cae al modo de
siempre (canción entera si sobra; si no, repetirla con fundidos).
"""
from __future__ import annotations


TOL = 0.5          # el total queda a ±0,5 s de lo pedido
MIN_PART = 0.5     # un trozo final más corto que esto no se pone
FADE_S = 0.4       # fundido en cada unión (lo usa quien aplica el plan)
END_FADE_S = 2.5   # fundido de salida al final de la pista
BLOCK_MAX = 8      # compases máximos por bloque (si no hay secciones: bloques de 4)
BLOCK_NO_SEC = 4
EPS = 1e-6


def _fallback(song_dur: float, target: float) -> list[tuple[float, float]]:
    """Sin ritmo: canción entera si sobra (fundido al final lo pone quien aplica); si no, repetir."""
    if song_dur >= target:
        return [(0.0, round(target, 4))]
    out, t = [], 0.0
    while t < target - EPS:
        d = min(song_dur, target - t)
        out.append((0.0, round(d, 4)))
        t += d
    return out


def _regular(info: dict) -> bool:
    """¿Hay un pulso de verdad? Casi todos los golpes separados lo mismo (±10 %). El ruido no lo tiene."""
    beats = sorted(float(x) for x in (info.get("beats") or []))
    if len(beats) < 16:
        return False
    d = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
    med = sorted(d)[len(d) // 2]
    if med <= 0.2:
        return False
    return sum(1 for x in d if abs(x - med) <= 0.1 * med) / len(d) >= 0.8


def _nearest(t: float, bars: list[float]) -> float:
    return min(bars, key=lambda b: abs(b - t))


def _bars(info: dict, song_dur: float) -> list[float]:
    """Inicios de compás (downbeats) dentro de la canción, ordenados."""
    bars = [float(x) for x in (info.get("downbeats") or []) if 0.0 <= float(x) < song_dur - 0.5]
    if len(bars) < 2 and len(info.get("beats") or []) >= 8:           # sin downbeats: cada 4 golpes
        bars = [float(x) for x in info["beats"][::4] if 0.0 <= float(x) < song_dur - 0.5]
    return sorted(set(round(b, 4) for b in bars))


def _blocks(info: dict, bars: list[float], mid_a: float, tail_start: float) -> list[dict]:
    """Bloques de la parte central [mid_a, tail_start): cada sección se trocea en bloques de hasta 8 compases
    (sin secciones: de 4). Cada bloque: {a, b, len, drop}. Los de menos de 4 compases se juntan con el anterior."""
    mids = [b for b in bars if mid_a - EPS <= b < tail_start - EPS]
    if not mids or mids[0] > mid_a + EPS:
        mids = [mid_a] + mids
    edges = mids + [tail_start]                       # compás i = [edges[i], edges[i+1])
    secs = sorted(info.get("sections") or [], key=lambda s: s["a"])
    if not secs:
        n = len(edges) - 1
        groups = [list(range(i, min(i + BLOCK_NO_SEC, n))) for i in range(0, n, BLOCK_NO_SEC)]
    else:
        def sec_of(t):
            for k, s in enumerate(secs):
                if s["a"] - 0.05 <= t < s["b"] - 0.05:
                    return k
            return -1
        runs: list[list[int]] = []
        for i in range(len(edges) - 1):
            k = sec_of(edges[i])
            if runs and runs[-1][0] == k:
                runs[-1][1].append(i)
            else:
                runs.append([k, [i]])
        groups = []
        for _, idx in runs:
            for j in range(0, len(idx), BLOCK_MAX):
                chunk = idx[j:j + BLOCK_MAX]
                if groups and len(chunk) < 4 and len(groups[-1]) + len(chunk) <= BLOCK_MAX:
                    groups[-1].extend(chunk)          # un trozo corto se pega al anterior
                else:
                    groups.append(chunk)
    drop = info.get("drop")
    out = []
    for g in groups:
        a, b = edges[g[0]], edges[g[-1] + 1]
        if b - a <= EPS:
            continue
        has_drop = drop is not None and a - EPS <= float(drop) < b
        out.append({"a": a, "b": b, "len": b - a, "drop": bool(has_drop)})
    return out


def plan_fit(rhythm_info: dict | None, song_dur: float, target_dur: float) -> list[tuple[float, float]]:
    """Trozos de la canción a encadenar para durar target_dur (±0,5 s).

    · Cabeza: la intro (o los 4 primeros compases si no hay sección de intro). Se conserva.
    · Cola: el final (la sección «outro», o los 4 últimos compases). Se conserva y termina la canción.
    · Medio: secciones troceadas en bloques de compases. Si sobra canción, se QUITAN bloques (los del centro
      primero, nunca los que tienen el drop si se puede evitar); si falta, se REPITE la secuencia de bloques.
    · El trozo que no cuadra es un fragmento de un bloque, cortado a mitad de compás (con fundido).
    """
    target = float(target_dur)
    S = float(song_dur)
    if target <= 0 or S <= 0:
        return []
    bars = _bars(rhythm_info or {}, S)
    if len(bars) < 12 or not _regular(rhythm_info or {}):   # poca rejilla o sin pulso (ruido): sin ritmo útil
        return _fallback(S, target)
    bl = float(sum(bars[i + 1] - bars[i] for i in range(len(bars) - 1)) / (len(bars) - 1))
    secs = sorted((rhythm_info or {}).get("sections") or [], key=lambda s: s["a"])

    # Cabeza (intro)
    head_end = None
    if secs and secs[0].get("kind") == "intro":
        cand = _nearest(float(secs[0]["b"]), bars)
        cand = min(cand, _nearest(bars[0] + 16 * bl, bars))   # la intro conservada: como mucho 16 compases
        if cand >= bl * 1.5:
            head_end = cand
    if head_end is None:
        head_end = bars[4]                   # sin intro detectada: los primeros 4 compases
    # Cola (final)
    tail_start = None
    if len(secs) > 1 and secs[-1].get("kind") == "outro":
        ok = [b for b in bars if b <= float(secs[-1]["a"]) + 0.05]
        if ok:
            tail_start = ok[-1]
    if tail_start is None:
        tail_start = bars[-4]
    if tail_start < head_end + 4 * bl:   # canción demasiado corta para cabeza + medio + cola
        return _fallback(S, target)
    tail_len = S - tail_start
    head_len = head_end
    need = target - head_len - tail_len

    if target <= tail_len + TOL:         # solo cabe el final: termina la canción igual
        return [(round(S - target, 4), round(target, 4))]
    if need < 0:                         # cabe la cabeza parcial + el final
        return [(0.0, round(target - tail_len, 4)), (round(tail_start, 4), round(tail_len, 4))]

    blocks = _blocks(rhythm_info or {}, bars, head_end, tail_start)
    if not blocks:
        return _fallback(S, target)
    n = len(blocks)
    total_mid = sum(b["len"] for b in blocks)
    pieces: list[tuple[float, float]] = []
    if total_mid >= need:                # hay que QUITAR: bloques del centro hacia fuera
        keep = [True] * n
        kept = total_mid
        center = (n - 1) / 2.0
        order = sorted(range(n), key=lambda i: (blocks[i]["drop"], abs(i - center)))
        last = None
        for i in order:
            if kept <= need + EPS:
                break
            keep[i] = False
            kept -= blocks[i]["len"]
            last = i
        gap = need - kept                # < longitud del último bloque quitado
        for i, b in enumerate(blocks):
            if keep[i]:
                pieces.append((b["a"], b["len"]))
            elif i == last and gap >= MIN_PART:
                pieces.append((b["a"], gap))
    else:                                # hay que REPETIR la secuencia de bloques
        acc, i = 0.0, 0
        while True:
            b = blocks[i % n]
            if acc + b["len"] <= need + EPS:
                pieces.append((b["a"], b["len"]))
                acc += b["len"]
                i += 1
            else:
                break
        gap = need - acc
        if gap >= MIN_PART:
            pieces.append((blocks[i % n]["a"], gap))

    plan = []
    if head_len > 0:
        plan.append((0.0, head_len))
    plan += pieces
    plan.append((tail_start, tail_len))
    out = [(round(a, 4), round(d, 4)) for a, d in plan if d > EPS]
    # seguridad: el total no puede separarse de lo pedido
    if not out or abs(sum(d for _, d in out) - target) > TOL:
        return _fallback(S, target)
    return out


def apply_to_clip(ctrl, clip_id: str, plan: list[tuple[float, float]], text: str = "Ajustar la música",
                 start: float | None = None) -> bool:
    """Sustituye el clip de música `clip_id` por los trozos de `plan`, en su misma pista y desde `start` (o su inicio).
    Los trozos van seguidos con fundido de salida/entrada de FADE_S en cada unión. Un solo paso de deshacer."""
    from ..core.controller import EditError
    from ..core.model import Clip, ORIGIN_AI, new_id

    def fn(p):
        c = p.clips.get(clip_id)
        if c is None:
            raise EditError("Ese clip ya no está en la línea de tiempo.")
        tr = p.track(c.track_id)
        if c.locked or (tr is not None and tr.locked):
            raise EditError("El clip o su pista están bloqueados.")
        if c.retimed:
            raise EditError("Quítale antes la velocidad o el sentido inverso al clip de música.")
        m = p.media.get(c.media_id)
        if m is None:
            raise EditError("No encuentro el archivo de esa música.")
        track_id, a, vol = c.track_id, (c.start if start is None else float(start)), c.volume
        base_fx = dict(c.fx or {})
        base_note = c.note
        origin = c.origin
        total = sum(d for _, d in plan)
        del p.clips[clip_id]
        ctrl._clear_range(p, track_id, a, a + total)
        t = a
        for i, (src, dur) in enumerate(plan):
            fx = {k: v for k, v in base_fx.items() if k not in ("fade_in", "fade_out")}
            if i == 0 and base_fx.get("fade_in"):
                fx["fade_in"] = base_fx["fade_in"]
            elif i == 0:
                fx["fade_in"] = 1.5
            if i > 0:
                fx["fade_in"] = FADE_S
            if i < len(plan) - 1:
                fx["fade_out"] = FADE_S
            else:
                fx["fade_out"] = base_fx.get("fade_out") or END_FADE_S
            nc = Clip(new_id(), m.id, track_id, t, src, dur, volume=vol,
                      origin=origin or ORIGIN_AI, note=base_note or "Música ajustada a la duración (IA)", fx=fx)
            p.clips[nc.id] = nc
            t += dur
        return len(plan)

    return bool(ctrl._edit(text, fn))


def describe(plan: list[tuple[float, float]]) -> str:
    """Resumen corto para la barra de estado: cuántos trozos y el total."""
    total = sum(d for _, d in plan)
    return f"{len(plan)} trozos · {total:.1f} s"
