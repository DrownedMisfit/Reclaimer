"""
«✂ Eliminar silencio» (como el de DaVinci Resolve): encuentra los tramos donde el sonido está por debajo de
un umbral y los quita, dejando un poco de margen antes y después de cada sonido.

Ajustes (en fotogramas del proyecto, como en Resolve):
  threshold_db  umbral: por debajo de este volumen es «silencio» (p. ej. -32 dB)
  before        «Antes del inicio»: silencio que se conserva antes de que vuelva a sonar
  after         «Después del final»: silencio que se conserva después de que deja de sonar
  min_frames    «Mínimo a eliminar»: silencios más cortos se respetan
  crossfade     fundido mínimo en cada corte (sin «clics»)
  mode          "voz" (por defecto, preciso) o "volumen" (solo el umbral, exactamente como Resolve)

🎙 Modo «voz» (preciso: no se come ni el principio ni el final de las palabras, y no lo engaña el ruido de fondo):
  1. Una IA de detección de voz (Silero VAD, incluida con la transcripción; licencia MIT) dice dónde se HABLA
     (distingue la voz del ruido: ventilador, teclado, el juego de fondo…).
  2. Cada borde se ajusta cada 5 ms siguiendo el sonido hasta que de verdad se apaga en el ruido de fondo, que se
     mide en cada zona de la grabación (no es un volumen fijo). Las consonantes suaves («s», «f», «j»), que tienen
     poco volumen pero mucho agudo, se siguen con un detector de agudos aparte.
  3. Lo que pase del umbral (tu ajuste de Resolve) y destaque del ruido también se conserva siempre.
  4. Solo se ALARGA la voz detectada, nunca se recorta. Encima van tus márgenes «antes/después» y, al pasar a la
     línea de tiempo, los cortes se redondean hacia dentro del silencio (nunca hacia la voz).
  5. Si la voz está transcrita, ningún corte atraviesa una palabra reconocida.
"""
from __future__ import annotations

import threading

import numpy as np

from . import media as media_tools

SR = 16000
# Ajustes del usuario (copiados de los que usa en DaVinci Resolve)
PRESETS = {
    # Medido en los Shorts terminados del usuario: casi siempre hablando, pausas muy cortas (la mayoría < 0,1 s y solo
    # 1 de cada 10 > 0,3 s). Con «🎙 Voz precisa» este ajuste deja pausas de ese estilo sin comerse nada.
    "Pausas cortas, ritmo de Shorts (-32 dB · 1 / 2 · mín. 12)": {"threshold_db": -32.0, "before": 1, "after": 2,
                                                                  "min_frames": 12},
    "Equilibrado (-26.8 dB · 2 / 4 · mín. 14)": {"threshold_db": -26.8, "before": 2, "after": 4, "min_frames": 14},
    "Natural, con aire (-32 dB · 5 / 8 · mín. 20)": {"threshold_db": -32.0, "before": 5, "after": 8, "min_frames": 20},
    "Rápido y dinámico (-32 dB · 1 / 10 · mín. 2)": {"threshold_db": -32.0, "before": 1, "after": 10, "min_frames": 2},
}
_lock = threading.Lock()
_levels: dict[tuple[str, float], np.ndarray] = {}


def frame_levels(path: str, fps: float) -> np.ndarray:
    """Volumen (dBFS) de cada fotograma del archivo: el pico de su energía en ventanas de 10 ms."""
    key = (path, round(fps, 3))
    with _lock:
        if key in _levels:
            return _levels[key]
    x = media_tools.decode_mono(path, SR).astype(np.float32)
    win = SR // 100                                  # 10 ms
    n = len(x) // win
    if n == 0:
        return np.full(1, -120.0, np.float32)
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    per_frame = 100.0 / fps                          # ventanas de 10 ms por fotograma
    nf = int(np.ceil(n / per_frame))
    idx = (np.arange(n) / per_frame).astype(np.int64)
    levels = np.full(nf, 1e-12, np.float32)
    np.maximum.at(levels, idx, rms.astype(np.float32))
    db = (20 * np.log10(np.maximum(levels, 1e-6))).astype(np.float32)
    with _lock:
        if len(_levels) > 32:
            _levels.clear()
        _levels[key] = db
    return db


def silent_ranges(db: np.ndarray, fps: float, threshold_db: float, before: int, after: int, min_frames: int,
                  a: float = 0.0, b: float | None = None) -> list[tuple[float, float]]:
    """Tramos a quitar (segundos DEL ARCHIVO) dentro de [a, b]."""
    f0 = max(0, int(round(a * fps)))
    f1 = len(db) if b is None else min(len(db), int(round(b * fps)))
    if f1 <= f0:
        return []
    quiet = db[f0:f1] < threshold_db
    out = []
    i, n = 0, len(quiet)
    while i < n:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < n and quiet[j]:
            j += 1
        if j - i >= max(1, min_frames):
            s = i + (after if i > 0 else 0)          # deja «después del final» del sonido anterior
            e = j - (before if j < n else 0)         # y «antes del inicio» del siguiente
            if e > s:
                out.append(((f0 + s) / fps, (f0 + e) / fps))
        i = j
    return out


# ------------------------------------------------------------------ 🎙 modo «voz» (preciso)
HOP = 0.005                  # resolución de los bordes: 5 ms
_HOP_N = int(SR * HOP)       # 80 muestras
VAD_ON, VAD_OFF = 0.5, 0.35  # la IA: empieza a hablar con 0.5, sigue hablando mientras no baje de 0.35
MIN_SPEECH = 0.06            # trozos de voz más cortos que esto (y sueltos) no cuentan
JOIN_GAP = 0.10              # huecos más cortos dentro de la voz se rellenan (entre sílabas)
TAIL_MAX, HEAD_MAX = 0.45, 0.25   # cuánto se puede alargar como mucho el final y el principio de cada frase
TAIL_GAP = 0.02              # al seguir el final, se toleran microcaídas de hasta 20 ms
# Seguro fijo alrededor de cada voz: la IA se da cuenta de que empiezas a hablar ~30–40 ms tarde, y con ruido de fondo
# el arranque suave de la palabra queda tapado por el ruido (no se puede seguir por volumen)
HEAD_SAFE, TAIL_SAFE = 0.08, 0.05   # (menos ya se come voz en la prueba con ruido; medido)
# Sonidos suaves cerca de una frase (el arranque flojo de una palabra, una sílaba que la IA casi no oye): si destacan
# claramente del fondo, están cerca de lo fuerte que hablas (ISLAND_LVL), la IA oye voz en ellos y están a menos de
# medio segundo de una frase, se quedan unidos a ella. (Con micro con puerta de ruido el fondo es -90 dB y una
# respiración de -70 «destacaba» 20 dB: se pegaba a la frase y dejaba pausas de hasta un segundo; medido)
ISLAND_DB, ISLAND_ABS, ISLAND_VAD, ISLAND_MIN, ISLAND_REACH = 25.0, -70.0, 0.4, 0.03, 0.5
ISLAND_LVL = 35.0
# Lo que está más de AUDIBLE_DB por debajo de cómo hablas en esa zona no se oye (con micros con puerta de ruido, entre
# palabras queda un «silencio digital» de -100 dB y cualquier resto de -90 contaba como sonido: cada frase se alargaba
# casi medio segundo y el resultado sonaba más separado que como editas tú)
AUDIBLE_DB = 40.0
DEAD_DB = 50.0       # más de 50 dB por debajo de tu voz: silencio muerto (ahí sobra el seguro; ver speech_mask, paso 6)
FLOOR_DB, HI_DB, LOUD_DB = 6.0, 8.0, 12.0   # sobre el ruido de fondo: sonido / agudos (s, f) / sonido fuerte
ANALYSIS_VERSION = 2         # (súbelo si cambia analyze(): los análisis guardados se rehacen)
_an_mem: dict[str, dict] = {}


def _blocks_db(x: np.ndarray) -> np.ndarray:
    """Volumen (dBFS) en ventanas de 10 ms cada 5 ms."""
    n = len(x) // _HOP_N
    e = (x[: n * _HOP_N].astype(np.float64).reshape(n, _HOP_N) ** 2).mean(axis=1)
    e10 = np.empty_like(e)
    e10[:-1] = (e[:-1] + e[1:]) / 2
    e10[-1:] = e[-1:]
    return (10 * np.log10(e10 + 1e-12)).astype(np.float32)


# 🖱 Clics y tics (ratón, teclado, la boca…): impulsos de pocos milisegundos que destacan mucho de lo que hay
# alrededor. Solo se quitan los que están FUERA de la voz (nada de voz a menos de CLICK_CLEAR), así nunca se toca
# una «p», «t» o «k» (que también son golpecitos cortos, pero dentro de la palabra)
CLICK_RISE, CLICK_MAX_MS, CLICK_CLEAR, CLICK_VAD = 25.0, 6, 0.06, 0.3


def _detect_clicks(x: np.ndarray) -> np.ndarray:
    """[[inicio, duración, cuánto destaca (dB)]] de los impulsos cortos (en el archivo)."""
    from numpy.lib.stride_tricks import sliding_window_view
    w = SR // 1000                                   # 1 ms
    d = np.diff(x, prepend=x[:1]).astype(np.float64)
    n = len(d) // w
    if n < 100:
        return np.zeros((0, 3), np.float32)
    db = 10 * np.log10((d[: n * w].reshape(n, w) ** 2).mean(axis=1) + 1e-14)
    med = np.median(sliding_window_view(np.pad(db, 40, mode="edge"), 81), axis=1)
    rise = db - med
    out, i = [], 0
    cand = np.nonzero((rise > CLICK_RISE) & (db > -70))[0]
    for i in cand:
        if out and i <= out[-1][0] * 1000 + out[-1][1] * 1000 + 1:
            continue
        j = i
        while j < n and rise[j] > 12:
            j += 1
        if 0 < j - i <= CLICK_MAX_MS:
            out.append((i / 1000.0, (j - i) / 1000.0, float(rise[i:j].max())))
    return np.asarray(out, np.float32).reshape(-1, 3)


def _vad_probs(x: np.ndarray) -> np.ndarray:
    """Probabilidad de voz (0–1) cada 32 ms con Silero VAD (la IA de la transcripción)."""
    from faster_whisper.vad import get_vad_model
    model = get_vad_model()
    n = 512
    pad = (-len(x)) % n
    xx = np.concatenate([x.astype(np.float32), np.zeros(pad + n, np.float32)])
    out = np.asarray(model(xx, num_samples=n)).reshape(-1)
    return out.astype(np.float32)


def analyze(path: str, progress=None) -> dict:
    """Análisis de la voz de un archivo (se guarda: la siguiente vez es instantáneo).
    {"full": dB cada 5 ms, "hi": dB de los agudos cada 5 ms, "vad": probabilidad de voz cada 5 ms}"""
    import os
    from .paths import cache_dir
    key = f"{media_tools.cache_key(path)}_v{ANALYSIS_VERSION}"
    with _lock:
        if key in _an_mem:
            return _an_mem[key]
    cf = os.path.join(str(cache_dir("silencio")), key + ".npz")
    res = None
    if os.path.exists(cf):
        try:
            d = np.load(cf)
            res = {k: d[k] for k in ("full", "hi", "vad", "clicks")}
        except (OSError, ValueError, KeyError):
            res = None
    if res is None:
        if progress:
            progress(0.05, "Escuchando el audio…")
        x = media_tools.decode_mono(path, SR).astype(np.float32)
        if len(x) < _HOP_N * 4:
            x = np.concatenate([x, np.zeros(_HOP_N * 4, np.float32)])
        full = _blocks_db(x)
        # Agudos: la diferencia entre muestras seguidas resalta lo agudo (s, f, j) y apaga lo grave (zumbidos)
        hi = _blocks_db(np.diff(x, prepend=x[:1]))
        if progress:
            progress(0.3, "La IA está reconociendo dónde hablas…")
        p32 = _vad_probs(x)
        k = (np.arange(len(full)) * _HOP_N) // 512             # cada 5 ms → su trozo de 32 ms
        vad = p32[np.minimum(k, len(p32) - 1)]
        res = {"full": full, "hi": hi.astype(np.float32), "vad": vad.astype(np.float32),
               "clicks": _detect_clicks(x)}
        try:
            np.savez_compressed(cf, **res)
        except OSError:
            pass
    with _lock:
        if len(_an_mem) > 16:
            _an_mem.clear()
        _an_mem[key] = res
    return res


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Tramos [i, j) donde mask es verdadero."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(np.int8))
    return list(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))


def _local_floor(db: np.ndarray, quiet: np.ndarray, block: int = 400, pct: float = 20.0) -> np.ndarray:
    """Ruido de fondo en cada zona (bloques de 2 s): el percentil bajo de lo que NO es voz. (Con pct alto y la máscara
    de la voz: lo fuerte que hablas en cada zona.)"""
    n = len(db)
    nb = max(1, int(np.ceil(n / block)))
    vals = np.full(nb, np.nan, np.float32)
    for b in range(nb):
        seg = db[b * block:(b + 1) * block][quiet[b * block:(b + 1) * block]]
        if len(seg) >= block // 10:
            vals[b] = np.percentile(seg, pct)
    glob = np.percentile(db[quiet], pct) if quiet.any() else np.percentile(db, 5)
    if np.isnan(vals).all():
        vals[:] = glob
    else:                                    # bloques sin silencio: el del bloque con dato más cercano
        idx = np.nonzero(~np.isnan(vals))[0]
        vals = np.interp(np.arange(nb), idx, vals[idx]).astype(np.float32)
    if pct < 50:
        vals = np.minimum(vals, glob + 10)   # una zona entera de voz no sube el «ruido» de golpe
    centers = (np.arange(nb) + 0.5) * block
    return np.interp(np.arange(n), centers, vals).astype(np.float32)


def speech_mask(an: dict, threshold_db: float) -> np.ndarray:
    """Dónde hay voz (o sonido que conservar), cada 5 ms. Nunca se queda corto: solo alarga."""
    full, hi, vad = an["full"], an["hi"], an["vad"]
    n = len(full)
    # 1) la IA, con histéresis: empieza en VAD_ON y sigue mientras no baje de VAD_OFF
    on = vad >= VAD_ON
    keep = vad >= VAD_OFF
    sp = np.zeros(n, bool)
    for i, j in _runs(keep):
        if on[i:j].any():
            sp[i:j] = True
    # trocitos sueltos demasiado cortos fuera; huecos cortos dentro de la voz, rellenos
    min_n, join_n = int(MIN_SPEECH / HOP), int(JOIN_GAP / HOP)
    for i, j in _runs(sp):
        if j - i < min_n:
            sp[i:j] = False
    for i, j in _runs(~sp):
        if 0 < i and j < n and j - i <= join_n:
            sp[i:j] = True
    # 2) ruido de fondo de cada zona (de lo que no es voz) y lo fuerte que hablas en cada zona
    quiet = ~sp
    f_full = _local_floor(full, quiet)
    f_hi = _local_floor(hi, quiet)
    lvl = _local_floor(full, sp, block=2000, pct=90.0) if sp.any() else np.full(n, -30.0, np.float32)
    lvl_hi = _local_floor(hi, sp, block=2000, pct=90.0) if sp.any() else np.full(n, -40.0, np.float32)
    sound = ((full > np.maximum(f_full + FLOOR_DB, lvl - AUDIBLE_DB))
             | (hi > np.maximum(f_hi + HI_DB, lvl_hi - AUDIBLE_DB)) | (full > threshold_db))
    # la IA alarga cada frase un poco después de que callas: se recorta SOLO lo que de verdad no se oye junto a tu voz
    # (el «silencio digital» de un micro con puerta de ruido). Con ruido de fondo de verdad no se recorta nada: la voz
    # suave queda tapada por el ruido y solo la IA sabe dónde está
    inaudible = (full < lvl - AUDIBLE_DB) & (hi < lvl_hi - AUDIBLE_DB)
    for i, j in _runs(sp):
        k = j
        while k > i and inaudible[k - 1]:
            k -= 1
        sp[k:j] = False
        k2 = i
        while k2 < k and inaudible[k2]:
            k2 += 1
        sp[i:k2] = False
    # 3) lo fuerte (por encima de tu umbral y muy por encima del ruido) se conserva siempre, como en Resolve
    loud = (full > threshold_db) & (full > f_full + LOUD_DB)
    for i, j in _runs(loud):
        if j - i >= int(0.08 / HOP):
            sp[i:j] = True
    # 4) cada frase se alarga mientras siga sonando (final que se apaga, «s» final, inicio suave)
    tail_n, head_n, gap_n = int(TAIL_MAX / HOP), int(HEAD_MAX / HOP), max(1, int(TAIL_GAP / HOP))
    out = sp.copy()
    for i, j in _runs(sp):
        k, last, miss = j, j, 0                # hacia delante (el final)
        while k < min(n, j + tail_n):
            if sound[k]:
                last, miss = k + 1, 0
            else:
                miss += 1
                if miss > gap_n:
                    break
            k += 1
        out[j:last] = True
        k, first, miss = i - 1, i, 0           # hacia atrás (el principio)
        while k >= max(0, i - head_n):
            if sound[k]:
                first, miss = k, 0
            else:
                miss += 1
                if miss > gap_n:
                    break
            k -= 1
        out[first:i] = True
    # 5) sonidos suaves con algo de voz, cerca de una frase: se unen a ella (no se come un arranque flojo)
    cand = (full > np.maximum(np.maximum(f_full + ISLAND_DB, ISLAND_ABS), lvl - ISLAND_LVL)) & ~out
    gap_n2 = max(1, int(0.02 / HOP))
    for i, j in _runs(~cand):                 # microcaídas dentro de un mismo sonido
        if 0 < i and j < n and j - i <= gap_n2:
            cand[i:j] = True
    reach = int(ISLAND_REACH / HOP)
    for i, j in _runs(cand):
        if (j - i) * HOP < ISLAND_MIN or float(vad[i:j].max()) < ISLAND_VAD:
            continue
        right = out[j:min(n, j + reach)]
        left = out[max(0, i - reach):i]
        if right.any():
            out[i:j + int(np.argmax(right))] = True
        if left.any():
            out[max(0, i - reach) + len(left) - 1 - int(np.argmax(left[::-1])):j] = True
    # 6) el seguro alrededor de cada voz (ver HEAD_SAFE), SOLO donde hay algo que podría ser voz floja tapada por el
    # ruido: sobre silencio de verdad (micro con puerta de ruido: -100 dB) no hace falta y dejaba huecos vacíos en
    # cada unión por mucho que bajaras los márgenes
    hs, ts = int(round(HEAD_SAFE / HOP)), int(round(TAIL_SAFE / HOP))
    dead = (full < lvl - DEAD_DB) & (hi < lvl_hi - DEAD_DB)   # silencio MUERTO (no un ruido flojo que tape algo)
    for i, j in _runs(out.copy()):
        k = i
        while k > max(0, i - hs) and not dead[k - 1]:
            k -= 1
        out[k:i] = True
        k = j
        while k < min(n, j + ts) and not dead[k]:
            k += 1
        out[j:k] = True
    return out


# 🎚 Híbrido (volumen + IA): además de lo de «Voz precisa», los microsilencios DENTRO de una frase dicha de corrido
# (50–150 ms entre dos palabras) que Resolve quita por volumen y la IA tapa (cree que sigues hablando). Solo si:
#   · son silencio de verdad en graves Y agudos (DIP_DB por debajo de tu voz, y por debajo del umbral);
#   · con transcripción: el cambio de una palabra a la siguiente cae DENTRO del silencio (±DIP_WORD). Si una palabra lo
#     cruza entero, es la pausa de una «p», «t» o «k» dentro de la palabra: no se toca;
#   · sin transcripción: solo los de DIP_NOWORDS o más (una «p» o una «t» casi nunca para tanto).
#   · y en los bordes de cada frase, el seguro (HEAD_SAFE/TAIL_SAFE) sobre lo que ya es silencio de verdad, SOLO si la
#     grabación es limpia (el fondo CLEAN_DB o más por debajo de tu voz: micro con puerta de ruido). Con ruido de fondo
#     el seguro se queda: ahí el arranque suave de una palabra puede estar tapado por el ruido.
DIP_DB, DIP_MIN, DIP_WORD, DIP_NOWORDS, CLEAN_DB = 40.0, 0.04, 0.04, 0.12, 55.0
EDGE_DB = 42.0      # (en el borde de una frase, más exigente: el final de una frase se apaga despacio; medido)


def _dips(an: dict, sp: np.ndarray, threshold_db: float, words: list | None) -> np.ndarray:
    """Dónde quitar microsilencios dentro de la voz (cada 5 ms; ver DIP_DB)."""
    full, hi = an["full"], an["hi"]
    n = len(sp)
    out = np.zeros(n, bool)
    if not sp.any():
        return out
    lvl = _local_floor(full, sp, block=2000, pct=90.0)
    lvl_hi = _local_floor(hi, sp, block=2000, pct=90.0)
    clean = _local_floor(full, ~sp) < lvl - CLEAN_DB
    dead_all = (full < np.minimum(threshold_db, lvl - DIP_DB)) & (hi < lvl_hi - DIP_DB) & clean
    dead_edge = (full < np.minimum(threshold_db, lvl - EDGE_DB)) & (hi < lvl_hi - EDGE_DB) & clean
    for i, j in _runs(dead_edge & sp):                  # junto al borde de una frase: fuera el seguro
        if (i > 0 and not sp[i - 1]) or (j < n and not sp[j]):
            out[i:j] = True
    dead = dead_all & sp & ~out
    bounds = []
    if words:
        ws = []
        for w in words:
            try:
                ws.append((float(w[0]), float(w[1])))
            except (TypeError, ValueError, IndexError):
                continue
        ws.sort()
        bounds = sorted({round(x, 4) for p, q in zip(ws, ws[1:]) for x in (p[1], q[0])})
    import bisect
    for i, j in _runs(dead):
        if 0 == i or j >= n or (j - i) * HOP < DIP_MIN:
            continue
        if not (sp[i - 1] and sp[j]):                   # (los bordes de las frases ya los hace «Voz precisa»)
            continue
        a, b = i * HOP, j * HOP
        if words:
            k = bisect.bisect_left(bounds, a - DIP_WORD)
            if k >= len(bounds) or bounds[k] > b + DIP_WORD:
                continue                                # ninguna palabra acaba o empieza aquí: dentro de una palabra
        elif b - a < DIP_NOWORDS:
            continue
        out[i:j] = True
    return out


# 🛡 Protección de la voz (modo híbrido). En un micro con puerta de ruido las pausas ya son silencio total con
# cualquier umbral: lo ÚNICO que el umbral puede quitar de más es voz (finales y sílabas suaves). El usuario elige:
#   · "max": no se come voz (el umbral casi no cambia nada en un micro así);
#   · "media": el umbral manda en todo lo que la IA no reconoce con seguridad como voz (hasta PROTECT_SOFT dB por debajo
#     del umbral se respeta); la voz segura que se oye no se corta nunca;
#   · "resolve": el umbral manda en todo, como DaVinci Resolve (solo se salvan las «s» y «f» por sus agudos).
# Medido con su micro (-18…-50 dB · 0/1/2): máxima 113 s siempre; media 112–122 s sin cortar voz clara; como Resolve
# 125–284 s cortando 0–144 s de voz clara. Voz sintética (15 frases): media como mucho 63 ms; como Resolve, ~3,3 s.
PROTECT = ("max", "media", "resolve")
PROTECT_SOFT, PROTECT_DIP = 18.0, 30.0


def _close_gaps(m: np.ndarray, seconds: float) -> np.ndarray:
    g = max(1, int(seconds / HOP))
    m = m.copy()
    for i, j in _runs(~m):
        if 0 < i and j < len(m) and j - i <= g:
            m[i:j] = True
    return m


# ◈ Tu voz, aprendida (ai/voice_model.py): un modelo entrenado con tus grabaciones sabe cada 10 ms si estás diciendo
# una palabra (medido en una grabación que no vio: 96 % de acierto y el borde de las palabras a 10 ms de mediana; la IA
# de voz general, 20 ms; «Voz precisa», con sus seguros, 50 ms). En el modo híbrido:
#   · lo que el modelo está seguro de que es palabra (PV_ON) y se oye, nunca se corta;
#   · los restos de los seguros en los bordes de cada frase, donde el modelo dice que no hay palabra (PV_OFF), la IA
#     general tampoco y no suena (PV_QUIET bajo tu voz), se quitan.
PV_ON, PV_OFF, PV_QUIET = 0.5, 0.15, 30.0
_pv_mem: dict = {}


def voice_prob(path: str, n: int) -> np.ndarray | None:
    """Probabilidad de palabra (tu modelo) cada HOP, o None si no hay modelo entrenado."""
    import os
    try:
        from ..ai import voice_model as VM
    except ImportError:
        return None
    if not VM.available():
        return None
    key = (media_tools.cache_key(path), os.path.getmtime(VM.model_path()))
    with _lock:
        if key in _pv_mem:
            p = _pv_mem[key]
            return p[:n] if len(p) >= n else np.pad(p, (0, n - len(p)))
    p10 = VM.predict(media_tools.decode_mono(path, SR).astype(np.float32))
    p = np.repeat(p10, int(round(VM.HOP / HOP))).astype(np.float32)
    with _lock:
        if len(_pv_mem) > 8:
            _pv_mem.clear()
        _pv_mem[key] = p
    return p[:n] if len(p) >= n else np.pad(p, (0, n - len(p)))


def _with_voice_model(an: dict, keep: np.ndarray, pv: np.ndarray) -> np.ndarray:
    full, hi, vad = an["full"], an["hi"], an["vad"]
    n = len(keep)
    if not keep.any():
        return keep
    lvl = _local_floor(full, keep, block=2000, pct=90.0)
    lvl_hi = _local_floor(hi, keep, block=2000, pct=90.0)
    audible = (full > lvl - AUDIBLE_DB) | (hi > lvl_hi - AUDIBLE_DB)
    keep = keep | ((pv[:n] >= PV_ON) & audible)
    trim = (pv[:n] < PV_OFF) & (vad < VAD_OFF) & (full < lvl - PV_QUIET) & (hi < lvl_hi - PV_QUIET)
    for i, j in _runs(keep.copy()):
        k = j
        while k > i and trim[k - 1]:
            k -= 1
        k2 = i
        while k2 < k and trim[k2]:
            k2 += 1
        keep[k:j] = False
        keep[i:k2] = False
    return keep


def _protect(an: dict, sp: np.ndarray, threshold_db: float, words: list | None, level: str) -> np.ndarray:
    """Dónde hay sonido que conservar (cada 5 ms) en modo híbrido, según la protección de la voz elegida."""
    import bisect
    if level not in ("media", "resolve"):
        return sp & ~_dips(an, sp, threshold_db, words)
    full, hi, vad = an["full"], an["hi"], an["vad"]
    n = len(full)
    lvl = _local_floor(full, sp, block=2000, pct=90.0) if sp.any() else np.full(n, -20.0, np.float32)
    lvl_hi = _local_floor(hi, sp, block=2000, pct=90.0) if sp.any() else np.full(n, -30.0, np.float32)
    thr_hi = threshold_db + (lvl_hi - lvl)            # el mismo umbral, en los agudos (relativo a tu voz)
    if level == "resolve":
        return _close_gaps((full >= threshold_db) | (hi >= thr_hi), 0.02)
    core = np.zeros(n, bool)                           # la voz que la IA reconoce con seguridad
    for i, j in _runs(vad >= VAD_ON):
        if (j - i) * HOP >= MIN_SPEECH:
            core[i:j] = True
    core = _close_gaps(core, JOIN_GAP)
    audible = (full > lvl - AUDIBLE_DB) | (hi > lvl_hi - AUDIBLE_DB)
    soft = _close_gaps((full >= threshold_db - PROTECT_SOFT) | (hi >= thr_hi - PROTECT_SOFT), 0.02)
    keep = (core & audible) | (soft & sp)
    # microsilencios dentro de la voz: bajo el umbral y de verdad callados, y entre dos palabras (como en «max»)
    quiet = ((full < np.minimum(threshold_db - 6, lvl - PROTECT_DIP))
             & (hi < np.minimum(thr_hi - 6, lvl_hi - PROTECT_DIP)) & keep)
    bounds = []
    if words:
        ws = []
        for w in words:
            try:
                ws.append((float(w[0]), float(w[1])))
            except (TypeError, ValueError, IndexError):
                continue
        ws.sort()
        bounds = sorted({round(x, 4) for p, q in zip(ws, ws[1:]) for x in (p[1], q[0])})
    for i, j in _runs(quiet):
        if i == 0 or j >= n or (j - i) * HOP < DIP_MIN or not (keep[i - 1] and keep[j]):
            continue
        a, b = i * HOP, j * HOP
        if bounds:
            k = bisect.bisect_left(bounds, a - DIP_WORD)
            if k >= len(bounds) or bounds[k] > b + DIP_WORD:
                continue
        elif b - a < DIP_NOWORDS:
            continue
        keep[i:j] = False
    return keep


# 🎯 Palabras AFINADAS (ai/align.py, ±20 ms; con la voz del usuario): lo que está dentro de una palabra y suena no se
# corta NUNCA, en ningún nivel de protección (tampoco «Como Resolve»: ahí el umbral manda en pausas, respiraciones y
# ruido, pero las palabras quedan enteras). Lo que dentro de una palabra es silencio muerto (el alineador a veces
# estira una palabra sobre una pausa) sí se puede quitar. (El usuario: «está cortando mis palabras…»: con «Solo
# volumen» o «Como Resolve» y sus valores de Resolve se comían hasta 8 s de voz clara en 71 s; medido.)
def _word_frames(an: dict, sp: np.ndarray, words: list) -> np.ndarray:
    full, hi = an["full"], an["hi"]
    n = len(full)
    out = np.zeros(n, bool)
    for w in words:
        try:
            a, b = float(w[0]), float(w[1])
        except (TypeError, ValueError, IndexError):
            continue
        out[max(0, int(a / HOP)):min(n, int(np.ceil(b / HOP)))] = True
    if not out.any():
        return out
    ref = sp | out
    lvl = _local_floor(full, ref, block=2000, pct=90.0)
    lvl_hi = _local_floor(hi, ref, block=2000, pct=90.0)
    return out & ~((full < lvl - DEAD_DB) & (hi < lvl_hi - DEAD_DB))


def voice_hits(project, clips, regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """⚠ La predicción: los trozos (en la LÍNEA DE TIEMPO) de lo que se va a quitar donde hay voz clara (la IA está
    segura de que hablas y suena a menos de 25 dB de tu voz). Para avisar en rojo ANTES de cortar."""
    out = []
    for c in clips:
        m = project.media_of(c)
        if m is None or c.speed <= 0 or c.reverse or not (m.kind == "audio" or m.has_audio):
            continue
        try:
            an = analyze(m.path)
        except Exception:  # noqa: BLE001
            continue
        full, vad = an["full"], an["vad"]
        sp = speech_mask(an, -32.0)
        lvl = _local_floor(full, sp, block=2000, pct=90.0) if sp.any() else np.full(len(full), -20.0, np.float32)
        clear = (vad >= VAD_ON) & (full > lvl - 25)
        for ra, rb in regions:
            a, b = max(ra, c.start), min(rb, c.end)
            if b - a <= 1e-3:
                continue
            sa = c.source_in + (a - c.start) * c.speed
            i0, i1 = int(sa / HOP), int((c.source_in + (b - c.start) * c.speed) / HOP)
            for i, j in _runs(clear[max(0, i0):max(i0, i1)]):
                ta = a + (i * HOP) / c.speed
                tb = a + (j * HOP) / c.speed
                if tb - ta >= 0.02:
                    out.append((ta, tb))
    return sorted(out)


def silent_ranges_voice(an: dict, fps: float, threshold_db: float, before: int, after: int, min_frames: int,
                        a: float = 0.0, b: float | None = None,
                        words: list | None = None, edges: bool = False, hybrid: bool = False,
                        protect: str = "max", pv: np.ndarray | None = None, words_locked: bool = False) -> list:
    """Tramos a quitar (segundos DEL ARCHIVO) dentro de [a, b], en modo «voz».
    edges=True: también los silencios que tocan el principio o el final del tramo aunque sean cortos, marcados
    (s, e, toca_el_borde): al cortar otra vez, cada pausa está repartida entre el final de un trozo y el principio del
    siguiente, y es plan() quien las junta y mira el mínimo con la pausa ENTERA."""
    sp = speech_mask(an, threshold_db)
    if hybrid:
        sp = _protect(an, sp, threshold_db, words, protect)
        if pv is not None and protect != "resolve":
            sp = _with_voice_model(an, sp, pv)
        if words_locked and words:
            sp = sp | _word_frames(an, sp, words)
    n = len(sp)
    i0 = max(0, int(np.floor(a / HOP)))
    i1 = n if b is None else min(n, int(np.ceil(b / HOP)))
    if i1 <= i0:
        return []
    out = []
    min_s = max(1, min_frames) / fps
    runlen: dict[tuple, float] = {}
    for i, j in _runs(~sp[i0:i1]):
        edge = i == 0 or i0 + j >= i1
        if (j - i) * HOP < min_s and not (edges and edge):
            continue
        s = (i0 + i) * HOP + (after / fps if i > 0 else 0.0)
        e = (i0 + j) * HOP - (before / fps if i0 + j < i1 else 0.0)
        if e - s > 1e-3:
            out.append((s, e))
            runlen[(s, e)] = (j - i) * HOP          # lo que dura la pausa ENTERA (con los márgenes)
    if words:
        out = _guard_words(out, words, sp)
    out = [(s, e) for s, e in out if e - s > 1e-3]
    if edges:
        lo, hi = i0 * HOP, i1 * HOP
        return [(s, e, abs(s - lo) < 1e-6 or abs(e - hi) < 2 * HOP, runlen.get((s, e), e - s)) for s, e in out]
    return out


def click_ranges(an: dict, a: float = 0.0, b: float | None = None) -> list[tuple[float, float]]:
    """🖱 Tramos diminutos (segundos DEL ARCHIVO) para quitar los clics que están FUERA de la voz: la IA no oye voz a
    menos de 60 ms y lo de alrededor está mucho más bajo (un golpecito suelto, no parte de un sonido)."""
    clicks = an.get("clicks")
    if clicks is None or not len(clicks):
        return []
    vad, full = an["vad"], an["full"]
    n = len(vad)
    clear = int(round(CLICK_CLEAR / HOP))
    out = []
    for t, dur, _rise in clicks:
        t, dur = float(t), float(dur)
        if t < a or (b is not None and t + dur > b):
            continue
        k0, k1 = int(t / HOP), int((t + dur) / HOP) + 1
        if k1 >= n or float(vad[max(0, k0 - clear):min(n, k1 + clear)].max()) >= CLICK_VAD:
            continue                                  # hay voz cerca: no se toca
        around = np.concatenate([full[max(0, k0 - 8):max(0, k0 - 2)], full[min(n, k1 + 2):min(n, k1 + 8)]])
        if len(around) and float(np.percentile(around, 90)) > float(full[k0:k1].max()) - 12:
            continue                                  # no es un golpecito suelto (es parte de otro sonido)
        out.append((max(0.0, t - 0.004), t + dur + 0.006))
    return out


def _guard_words(cuts: list[tuple[float, float]], words: list, sp: np.ndarray | None = None) -> list[tuple[float, float]]:
    """Ningún corte atraviesa el centro de una palabra reconocida (la transcripción, si la hay).
    Con sp (dónde hay voz): cada palabra se reduce antes a su trozo de voz más largo. La transcripción suele hacer
    empezar cada palabra justo donde acabó la anterior, así que la pausa de en medio «era» parte de la palabra y se
    protegía (quedaban pausas de hasta 1,2 s por mucho que movieras los ajustes; medido con tu voz)."""
    import bisect
    cores = []
    for w in words:
        try:
            ws, we = float(w[0]), float(w[1])
        except (TypeError, ValueError, IndexError):
            continue
        if sp is not None:
            k0, k1 = max(0, int(ws / HOP)), min(len(sp), int(np.ceil(we / HOP)))
            runs = _runs(sp[k0:k1]) if k1 > k0 else []
            if not runs:
                continue                          # ahí no suena nada: esa «palabra» no protege ningún silencio
            i, j = max(runs, key=lambda r: r[1] - r[0])
            ws, we = max(ws, (k0 + i) * HOP), min(we, (k0 + j) * HOP)
        d = we - ws
        if d > 0.02:
            cores.append((ws + 0.3 * d, we - 0.3 * d, ws, we))
    if not cores:
        return cuts
    cores.sort()
    starts = [c[0] for c in cores]
    res = []
    for s, e in cuts:
        pieces = [(s, e)]
        k = max(0, bisect.bisect_left(starts, s) - 2)
        while k < len(cores) and cores[k][0] < e:
            cs, ce, ws, we = cores[k]
            new = []
            for ps, pe in pieces:
                if ce > ps and cs < pe:          # el corte toca el centro de la palabra: fuera la palabra entera
                    if ws - 0.02 > ps:
                        new.append((ps, ws - 0.02))
                    if we + 0.02 < pe:
                        new.append((we + 0.02, pe))
                else:
                    new.append((ps, pe))
            pieces = new
            k += 1
        res.extend(pieces)
    return res


def plan(project, clips, fps: float, settings: dict) -> list[tuple[float, float]]:
    """Tramos de la LÍNEA DE TIEMPO a quitar en los clips dados (unidos y ordenados)."""
    from .mapping import map_range
    spans = []
    for c in clips:
        m = project.media_of(c)
        if m is None or c.speed <= 0 or c.reverse or not (m.kind == "audio" or m.has_audio):
            continue
        mode = settings.get("mode", "voz")
        # ◈ lo aprendido de tus retoques (core/silence_learn.py): margen de más (o de menos) antes y después
        lr = settings.get("learned") or {}
        bef = max(0.0, float(settings["before"]) + float(lr.get("before", 0.0)) * fps)
        aft = max(0.0, float(settings["after"]) + float(lr.get("after", 0.0)) * fps)
        if mode in ("voz", "hibrido"):
            tr_ = project.transcripts.get(m.id) or {}
            words = tr_.get("words") or None
            an_ = analyze(m.path)
            pv = voice_prob(m.path, len(an_["full"])) if mode == "hibrido" and settings.get("voice_model", True) \
                else None
            found = silent_ranges_voice(an_, fps, settings["threshold_db"], bef, aft, int(settings["min_frames"]),
                                        c.source_in, c.source_in + c.src_len, words, edges=True,
                                        hybrid=mode == "hibrido", protect=str(settings.get("protect", "max")),
                                        pv=pv, words_locked=bool(tr_.get("aligned")) and settings.get("words", True))
        else:
            db = frame_levels(m.path, fps)
            found = silent_ranges(db, fps, settings["threshold_db"], int(settings["before"]),
                                  int(settings["after"]), int(settings["min_frames"]),
                                  c.source_in, c.source_in + c.src_len)
        if settings.get("clicks", True) and mode in ("voz", "hibrido"):
            for sa, sb in click_ranges(analyze(m.path), c.source_in, c.source_in + c.src_len):
                for _c, ta, tb in map_range(project, c.media_id, sa, sb, [c]):
                    ta2, tb2 = np.floor(ta * fps + 1e-6) / fps, np.ceil(tb * fps - 1e-6) / fps
                    if tb2 - ta2 > 1e-3:
                        spans.append((float(ta2), float(tb2), False, float(tb2 - ta2)))
        for f in found:
            sa, sb, edge, rl = f if len(f) == 4 else (f[0], f[1], False, f[1] - f[0])
            for _c, ta, tb in map_range(project, c.media_id, sa, sb, [c]):
                # en la línea de tiempo, al fotograma: el principio hacia DELANTE y el final hacia ATRÁS (el
                # redondeo siempre come silencio, nunca voz). En el borde del clip, exacto (es el corte que ya hay)
                ta2 = ta if edge and abs(ta - c.start) < 1e-4 else np.ceil(ta * fps - 1e-6) / fps
                tb2 = tb if edge and abs(tb - c.end) < 1e-4 else np.floor(tb * fps + 1e-6) / fps
                if tb2 - ta2 > 1e-3 or (edge and tb2 - ta2 > -1e-9):   # (un borde diminuto cuenta para la pausa)
                    spans.append((float(ta2), float(max(ta2, tb2)), bool(edge), float(rl)))
    spans.sort()
    merged: list[list] = []                      # [inicio, fin, ¿solo trozos de borde?, duración de la pausa entera]
    for a, b, edge, rl in spans:
        if merged and a <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2] = merged[-1][2] and edge
            merged[-1][3] += rl
        else:
            merged.append([a, b, edge, rl])
    # una pausa hecha SOLO de bordes (fin de un trozo + principio del siguiente) se quita si la pausa ENTERA (las dos
    # mitades, con sus márgenes) llega al mínimo
    min_s = max(1, int(settings.get("min_frames", 1))) / fps
    return [(a, b) for a, b, only_edges, rl in merged if b - a > 1e-3 and not (only_edges and rl < min_s - 1e-6)]
