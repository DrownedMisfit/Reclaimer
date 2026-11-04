"""
Módulo de IA: EDIT MUSICAL automático.

Un «edit» es un video sin comentario donde manda la música: intro tranquila, un «drop»
donde la canción explota y, a partir de ahí, cortes rápidos al ritmo con destellos,
zooms de golpe y temblores. (Estudiado a partir de un edit de ejemplo: intro de 9 s con
frases entre corchetes, drop con destello y planos de ~0,4 s, uno por golpe o medio golpe.)

Cómo lo hace (todo local, sin modelos que descargar):
  1. Canción: golpes (beats), fuerza de cada golpe y energía → dónde está el drop.
  2. Clips: cuánto movimiento hay en cada momento, dónde hay cortes y dónde está oscuro
     (se guarda en caché: la segunda vez es instantáneo).
  3. Plan: planos largos y con zoom lento en la intro; tras el drop, planos de 2, 1 o ½ golpe
     según la energía; los momentos de más acción van a los golpes más fuertes.
El resultado es un plan que el controlador coloca en la timeline (y se puede deshacer).
"""
from __future__ import annotations

import os
import subprocess

import numpy as np

from ..core import media as media_tools
from ..core.paths import cache_dir
from . import music_analysis
from .base import CancelFn, ProgressFn, check_cancel, report

STEP = 0.25            # resolución del análisis de movimiento (s)
SCENE_CHUNK = 8.0      # una escena sin cortes muy larga (partida, cinemática continua) cuenta por trozos de 8 s
PW, PH = 64, 36        # tamaño diminuto para analizar (rápido)
VERSION = 1

INTENSITY = {          # golpes por plano según la energía: (muy alta, alta, media, baja)
    # Más pausado (sin medios golpes): con tantos cortes no se apreciaba el detalle. Ráfagas: «⚡ Ráfaga» a mano.
    "tranquilo": (4, 4, 8, 8),
    "normal": (2, 2, 4, 4),
    "intenso": (1, 2, 2, 4),     # como el edit de ejemplo, pero sin cortar a medio golpe
}

QUOTE_STYLE = {"font": "Times New Roman", "bold": False, "box": False, "size": 3.3, "y": 0.56,
               "color": "#FFFFFF"}
QUOTE_RED = "#E5413C"


# ------------------------------------------------------------------ análisis de los clips
def _profile_path(path: str) -> str:
    return str(cache_dir("movimiento") / f"{media_tools.cache_key(path)}_v{VERSION}.npz")


LONG_VIDEO = 10 * 60     # a partir de aquí (s), solo se miran los fotogramas clave (~4 veces más rápido)


def motion_profile(path: str, duration: float, cancelled: CancelFn = None, progress=None) -> dict:
    """{"motion", "bright", "cut"} cada STEP segundos. Se guarda en caché.
    progress(fracción 0–1) mientras lo ve. En videos largos (películas, «all cutscenes»…) solo mira los
    fotogramas clave. (Con la tarjeta gráfica era más lento: copiar cada imagen de vuelta cuesta más.)"""
    cache = _profile_path(path)
    if os.path.exists(cache):
        try:
            d = np.load(cache)
            return {k: d[k] for k in ("motion", "bright", "cut")}
        except (OSError, ValueError, KeyError):
            pass
    long_video = (duration or 0) > LONG_VIDEO
    res = _read_profile(path, duration, cancelled, progress, hw=False, keyframes=long_video)
    if long_video and len(res["motion"]) < 4:      # (por si el archivo no tiene fotogramas clave legibles)
        res = _read_profile(path, duration, cancelled, progress, hw=False, keyframes=False)
    if long_video and len(res["motion"]) > 2:
        res["motion"] = _fill_repeats(res["motion"])
    if len(res["motion"]) >= 4:
        np.savez_compressed(cache, **res)
    return res


def _fill_repeats(motion: np.ndarray) -> np.ndarray:
    """Solo con fotogramas clave, entre dos claves se repite la imagen (movimiento 0): se rellena
    interpolando entre los valores reales."""
    m = np.asarray(motion, np.float32).copy()
    real = np.flatnonzero(m > 1e-6)
    if len(real) >= 2:
        m = np.interp(np.arange(len(m)), real, m[real]).astype(np.float32)
    return m


def _read_profile(path: str, duration: float, cancelled, progress, hw: bool, keyframes: bool) -> dict:
    args = [media_tools.ffmpeg(), "-nostdin", "-v", "error"]
    if hw:
        args += ["-hwaccel", "auto"]
    if keyframes:
        args += ["-skip_frame", "nokey"]
    # ⚡ Sin el filtro de desbloqueo del decodificador: ~25 % más rápido y en una imagen de 64×36 no cambia nada
    # (diferencia media < 2 niveles de 255; el movimiento compara un fotograma con el anterior)
    args += ["-skip_loop_filter", "all"]
    args += ["-threads", "0", "-i", path, "-an", "-sn", "-dn",
             "-vf", f"fps={1 / STEP:g},scale={PW}:{PH}:flags=fast_bilinear", "-pix_fmt", "rgb24",
             "-f", "rawvideo", "-"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, creationflags=flags)
    size = PW * PH * 3
    motion, bright, cut = [], [], []
    prev = prev_hist = None
    total = max(1.0, (duration or 0) / STEP)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            if len(motion) % 200 == 0:
                if cancelled is not None:
                    check_cancel(cancelled)
                if progress is not None:
                    progress(min(0.999, len(motion) / total))
            f = np.frombuffer(buf, np.uint8).reshape(PH, PW, 3).astype(np.float32)
            g = f.mean(axis=2)
            hist = np.concatenate([np.histogram(f[..., c], bins=12, range=(0, 256))[0] for c in range(3)])
            hist = hist / (PW * PH)
            if prev is None:
                motion.append(0.0)
                cut.append(False)
            else:
                d = float(np.abs(g - prev).mean())
                hd = float(np.abs(hist - prev_hist).sum())
                motion.append(d)
                cut.append(hd > 0.9 and d > 22)
            bright.append(float(g.mean() / 255))
            prev, prev_hist = g, hist
    finally:
        proc.stdout.close()
        proc.kill() if proc.poll() is None else None
        proc.wait()
    return {"motion": np.array(motion, np.float32), "bright": np.array(bright, np.float32),
            "cut": np.array(cut, bool)}


# ------------------------------------------------------------------ análisis de la canción
def analyze_song(path: str, samples: np.ndarray | None = None) -> dict:
    """{"tempo", "beats", "strength" (0–1 por golpe), "energy" (cada 0,1 s), "duration"}"""
    sr = music_analysis.SR
    samples = media_tools.decode_mono(path, sr) if samples is None else samples
    info = music_analysis.detect_beats(samples, sr)
    env = music_analysis.onset_envelope(samples, sr)
    fps = sr / music_analysis.HOP
    ref = float(np.percentile(env, 97)) or 1.0
    strength = []
    for b in info["beats"]:
        i = int((b - 1024 / sr) * fps)
        a, z = max(0, i - 2), min(len(env), i + 3)
        strength.append(round(float(min(1.0, env[a:z].max() / ref)) if z > a else 0.0, 3))
    info["strength"] = strength
    info["duration"] = len(samples) / sr
    # Intensidad cada 0,1 s: volumen general + graves (el drop es, sobre todo, cuando entra el bajo)
    win, hop = 2048, sr // 10
    n = max(0, 1 + (len(samples) - win) // hop)
    if n:
        idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
        spec = np.abs(np.fft.rfft(samples[idx] * np.hanning(win)[None, :], axis=1)) ** 2
        f = np.fft.rfftfreq(win, 1 / sr)
        bass = 10 * np.log10(spec[:, (f >= 20) & (f < 150)].mean(axis=1) + 1e-12)
        loud = 10 * np.log10(spec.mean(axis=1) + 1e-12)
        info["intensity"] = np.round((bass + loud) / 2, 2).tolist()
    else:
        info["intensity"] = [0.0]
    return info


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) < n or n < 2:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def _intensity(song: dict) -> np.ndarray:
    if song.get("intensity") is not None and len(song["intensity"]) > 1:
        return _smooth(np.asarray(song["intensity"], np.float32), 5)
    return 20 * np.log10(_smooth(np.asarray(song["energy"], np.float32), 5) + 1e-3)


def find_drop(song: dict, lo: float = 4.0, hi_frac: float = 0.75, min_rise_db: float = 5.0) -> float | None:
    """Golpe donde la intensidad (graves + volumen) sube más de golpe: el «drop».
    None si la canción no tiene uno claro."""
    e = _intensity(song)
    beats = song["beats"]
    best, best_t = 0.0, None
    win = 30   # 3 s (energía cada 0,1 s)
    for b in beats:
        if b < lo or b > song["duration"] * hi_frac:
            continue
        i = int(b * 10)
        if i - win < 0 or i + win > len(e):
            continue
        rise = float(e[i:i + win].mean() - e[i - win:i].mean())
        if rise > best:
            best, best_t = rise, b
    return best_t if best >= min_rise_db else None


def choose_window(song: dict, length: float | None, intro: float = 9.0) -> tuple[float, float, float | None]:
    """(inicio, fin, drop) del trozo de la canción a usar."""
    dur = song["duration"]
    beats = song["beats"]
    drop = find_drop(song)
    if length is None or length >= dur - 0.5:
        return 0.0, dur, drop
    if drop is not None:
        start = max(0.0, drop - intro)
        start = max([b for b in beats if b <= start + 0.05] or [0.0]) if start > 0 else 0.0
    else:
        # Sin drop claro: el trozo con más energía
        e = _intensity(song)
        n = max(1, int(length * 10))
        cs = np.concatenate([[0.0], np.cumsum(e)])
        means = (cs[n:] - cs[:-n]) / n if len(e) > n else np.array([0.0])
        start = float(np.argmax(means)) / 10
        start = max([b for b in beats if b <= start + 0.05] or [0.0])
    end = min(dur, start + length)
    # Terminar en un golpe
    after = [b for b in beats if start + length * 0.9 <= b <= end]
    if after:
        end = after[-1]
    if drop is not None and not (start < drop < end):
        drop = None
    return start, end, drop


# ------------------------------------------------------------------ plan
def _norm_energy(song: dict, a: float, b: float) -> callable:
    """Energía 0–1 respecto al nivel fuerte de la canción: 1 = a tope (como el drop),
    0,7 ≈ 3 dB por debajo, 0 = 10 dB o más por debajo (parte tranquila)."""
    e = _intensity(song)
    seg = e[int(a * 10):max(int(a * 10) + 1, int(b * 10))]
    ref = float(np.percentile(seg, 90)) if len(seg) else 0.0

    def at(t: float) -> float:
        i = min(len(e) - 1, max(0, int(t * 10)))
        return float(np.clip(1 + (e[i] - ref) / 10, 0, 1))
    return at


def build_slots(song: dict, start: float, end: float, drop: float | None, intensity: str = "normal",
                n_quotes: int = 0) -> list[dict]:
    """Huecos de la timeline (en tiempo de la canción): [{a, b, part, energy, hit, bar}]"""
    beats = [b for b in song["beats"] if start - 1e-3 <= b <= end + 1e-3]
    strength = dict(zip(song["beats"], song["strength"]))
    energy = _norm_energy(song, drop if drop is not None else start, end)
    steps = INTENSITY.get(intensity, INTENSITY["normal"])
    slots: list[dict] = []
    period = float(np.median(np.diff(song["beats"]))) if len(song["beats"]) > 2 else 0.5

    # Intro: planos largos (uno por frase si hay frases)
    main_from = drop if drop is not None else start
    if drop is not None and drop - start > 1.0:
        ib = [b for b in beats if start < b < drop - 1e-3]
        want = max(2.5, 8 * period)
        n = max(1, int(round((drop - start) / want)))
        if n_quotes:
            n = max(n, min(n_quotes, max(1, int((drop - start) / 1.8))))
        edges = [start]
        for k in range(1, n):
            target = start + (drop - start) * k / n
            edges.append(min(ib, key=lambda b: abs(b - target)) if ib else target)
        edges.append(drop)
        edges = sorted(set(round(x, 3) for x in edges))
        for a, b in zip(edges, edges[1:]):
            if b - a > 0.3:
                slots.append({"a": a, "b": b, "part": "intro", "energy": 0.2, "hit": 0.0, "bar": False})

    # Después del drop: según la energía
    mb = [b for b in beats if b >= main_from - 1e-3]
    if not mb or mb[0] - main_from > 0.05:
        mb = [main_from] + mb
    i = 0
    while i < len(mb) - 1:
        t = mb[i]
        e = energy(t + 0.05)
        hit = strength.get(t, 0.5)
        if e > 0.82:
            step = steps[0]
        elif e > 0.6:
            step = steps[1]
        elif e > 0.35:
            step = steps[2]
        else:
            step = steps[3]
        if step < 1 and hit < 0.75:   # medio golpe solo en los golpes muy marcados
            step = 1
        while step * period < 0.8:    # ningún plano de menos de 0,8 s: el doble de golpes (sigue en el ritmo)
            step *= 2
        bar = i % 4 == 0
        if step >= 4 and not bar:          # los planos largos empiezan en compás
            step = 4 - i % 4
        if step < 1:   # dos medios golpes seguidos
            nxt = mb[i + 1]
            mid = (t + nxt) / 2
            slots.append({"a": t, "b": mid, "part": "main", "energy": e, "hit": hit, "bar": bar})
            slots.append({"a": mid, "b": nxt, "part": "main", "energy": e, "hit": 0.4, "bar": False})
            i += 1
            continue
        j = min(len(mb) - 1, i + int(step))
        slots.append({"a": t, "b": mb[j], "part": "main", "energy": e, "hit": hit, "bar": bar})
        i = j
    if slots and slots[-1]["b"] < end - 0.05:
        slots[-1]["b"] = end if end - slots[-1]["b"] < 1.5 * period else slots[-1]["b"]
        if slots[-1]["b"] < end - 0.05:
            slots.append({"a": slots[-1]["b"], "b": end, "part": "main", "energy": 0.3, "hit": 0.3, "bar": True})
    # Final: el último plano algo más largo (se funde a negro)
    if len(slots) >= 3 and slots[-1]["b"] - slots[-1]["a"] < 2 * period and slots[-2]["part"] == "main":
        last = slots.pop()
        slots[-1]["b"] = last["b"]
    # Sin trocitos de menos de 0,8 s (el usuario: «cortes de ni un segundo» rompen la continuidad con el ritmo):
    # se juntan con el anterior (el primero, con el siguiente). El corte del drop no se toca.
    k = 0
    while k < len(slots) and len(slots) > 1:
        s = slots[k]
        at_drop = drop is not None and (abs(s["a"] - drop) < 0.03)
        if s["b"] - s["a"] < 0.8 and not at_drop:
            if k == 0:
                if drop is not None and abs(slots[1]["a"] - drop) < 0.03:
                    k += 1
                    continue
                slots[1]["a"] = s["a"]
            else:
                slots[k - 1]["b"] = s["b"]
            del slots[k]
            continue
        k += 1
    if slots:
        slots[-1]["part"] = "outro" if slots[-1]["part"] == "main" else slots[-1]["part"]
    return slots


class _Picker:
    """Elige qué trozo de qué clip va en cada hueco, sin repetir y variando de fuente."""

    def __init__(self, sources: list[dict], seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.sources = []
        pooled = []
        for s in sources:
            prof = s.get("profile")
            if s["kind"] == "image" or prof is None or len(prof["motion"]) < 4:
                self.sources.append(dict(s, cs=None))
                continue
            mot = np.asarray(prof["motion"], np.float32)
            pooled.append(mot[mot > 0.01])
            cuts = np.asarray(prof["cut"])
            # 🎬 cada paso, a qué ESCENA pertenece (entre cortes de cámara; las muy largas, en trozos de 8 s): dos trozos
            # distintos de la misma escena se ven igual, así que cuentan como repetir
            sc_id = np.cumsum(cuts > 0) * 10000 + (np.arange(len(cuts)) // int(SCENE_CHUNK / STEP))
            self.sources.append(dict(s, cs=np.concatenate([[0.0], np.cumsum(mot)]),
                                     dark=np.asarray(prof["bright"]) < 0.05, cuts=cuts, scene=sc_id))
        # 👎 momentos vetados: no vuelven a salir (salvo que no quede nada más que usar)
        self.avoid = {s["media_id"]: [tuple(r) for r in s.get("avoid") or []] for s in sources}
        # ✂ tramos elegidos a mano: los planos salen SOLO de ahí
        self.only = {s["media_id"]: [tuple(r) for r in s.get("only") or [] if r[1] - r[0] > 0.2] for s in sources}
        # 🔑 momentos donde se dicen tus palabras clave: esos planos se prefieren (y uno, en el drop)
        self.prefer = {s["media_id"]: sorted(float(t) for t in s.get("prefer") or []) for s in sources}
        self.prefer_drop = any(s.get("prefer_drop") for s in sources)
        self.used_words: set[tuple[str, float]] = set()
        allm = np.concatenate(pooled) if pooled else np.array([1.0])
        self.qs = np.percentile(allm, np.linspace(0, 100, 21)) if len(allm) else np.zeros(21)
        self.used: dict[str, list[tuple[float, float]]] = {}
        self.used_scenes: dict[tuple[str, int], int] = {}     # (clip, escena) → veces que ya salió
        self.recent: list[str] = []

    def _pct(self, m: np.ndarray) -> np.ndarray:
        return np.interp(m, self.qs, np.linspace(0, 1, 21))

    def _banned(self, mid: str, a: float, b: float) -> bool:
        return any(a < vb - 0.15 and b > va + 0.15 for va, vb in self.avoid.get(mid, []))

    def _outside(self, mid: str, a: float, b: float) -> float:
        """Cuánto se sale el trozo [a, b] de los tramos elegidos a mano (0 = dentro o no hay tramos)."""
        rs = self.only.get(mid)
        if not rs:
            return 0.0
        return min(max(0.0, ra - a) + max(0.0, b - rb) for ra, rb in rs)

    def _inside_starts(self, mid: str, n: int, L: int) -> np.ndarray:
        """Comienzos (en pasos) cuyo trozo cabe entero en algún tramo elegido (o los que menos se salen)."""
        key = (mid, n, L)
        cache = self.__dict__.setdefault("_ins_cache", {})
        if key not in cache:
            st = np.arange(0, max(1, n - L + 1))
            a, b = st * STEP, (st + L) * STEP
            out = np.full(len(st), np.inf)
            for ra, rb in self.only[mid]:
                out = np.minimum(out, np.maximum(0.0, ra - a) + np.maximum(0.0, b - rb))
            ok = st[out <= 1e-6]
            cache[key] = ok if len(ok) else st[np.argsort(out)[:30]]
        return cache[key]

    def _random_inside(self, mid: str, length: float, duration: float) -> float:
        rs = self.only.get(mid)
        if not rs:
            return float(self.rng.uniform(0, max(0.0, duration - length)))
        ra, rb = rs[int(self.rng.integers(len(rs)))]
        return float(self.rng.uniform(ra, max(ra, rb - length)))

    def pick(self, length: float, target: float, part: str) -> dict | None:
        best, best_score = None, -1e9
        for s in self.sources:
            mid = s["media_id"]
            recent_pen = 0.6 * (self.recent[-1:] == [mid]) + 0.2 * self.recent[-4:].count(mid)
            if s["cs"] is None:
                jitter = self.rng.uniform(0, 0.35)
                if s["kind"] == "image":      # cada imagen, una sola vez
                    if self.used.get(mid):
                        continue
                    sc, st = -abs(0.3 - target) - 0.25 - recent_pen + jitter, 0.0
                    if self.avoid.get(mid):
                        sc -= 40.0
                elif s["duration"] > length:  # video sin análisis: un trozo al azar (en tus tramos, sin vetar)
                    st = self._random_inside(mid, length, s["duration"])
                    for _try in range(12):
                        if not self._banned(mid, st, st + length):
                            break
                        st = self._random_inside(mid, length, s["duration"])
                    sc = -0.6 - recent_pen + jitter - (40.0 if self._banned(mid, st, st + length) else 0.0)                         - 60.0 * min(1.0, self._outside(mid, st, st + length))
                else:
                    continue
                if sc > best_score:
                    best, best_score = {"media_id": mid, "source_in": st}, sc
                continue
            n = len(s["cs"]) - 1
            L = max(1, int(round(length / STEP)))
            margin = min(int(2.0 / STEP), max(0, n // 20))
            hi = n - L - margin
            if hi <= margin:
                if n >= L:
                    margin, hi = 0, n - L
                else:
                    continue
            pool = np.arange(margin, hi + 1)
            if self.only.get(mid):          # ✂ solo los comienzos que caben dentro de tus tramos
                pool = self._inside_starts(mid, n, L)
            k = min(60, len(pool))
            if k <= 0:
                continue
            starts = self.rng.choice(pool, size=k, replace=False)
            words = self.prefer.get(mid) or []
            if words:                        # 🔑 también los comienzos que dejan la palabra dentro del plano
                extra = [int(max(0.0, t - length * 0.35) / STEP) for t in words]
                extra = [st for st in extra if 0 <= st <= n - L]
                if extra:
                    starts = np.unique(np.concatenate([starts, np.array(extra, dtype=starts.dtype)]))
            avg = (s["cs"][starts + L] - s["cs"][starts + 1]) / max(1, L - 1)
            sc = -np.abs(self._pct(avg) - target) * 1.2
            for j, st in enumerate(starts):
                inner = s["cuts"][st + 1:st + L]
                if inner.any():
                    sc[j] -= 1.2
                if s["dark"][st:st + L].mean() > 0.5:
                    sc[j] -= 2.0
                a, b = st * STEP, (st + L) * STEP
                # 🔁 sin repetir (el usuario: «se repiten demasiado las mismas escenas»): los mismos segundos, casi
                # prohibido; la misma escena (otro trozo), mucho menos probable cuantas más veces haya salido; y
                # pegado a algo ya usado, algo menos. Solo se repite cuando ya no queda nada nuevo.
                if any(a < ub + 0.5 and b > ua - 0.5 for ua, ub in self.used.get(mid, [])):
                    sc[j] -= 14.0
                elif any(a < ub + 3.0 and b > ua - 3.0 for ua, ub in self.used.get(mid, [])):
                    sc[j] -= 1.5
                sc[j] -= 5.0 * min(3, self.used_scenes.get((mid, int(s["scene"][min(st + L // 2, len(s["scene"]) - 1)])), 0))
                if self._banned(mid, a, b):
                    sc[j] -= 40.0                # 👎 vetado: no vuelve (pesa más que repetir escena)
                sc[j] -= 60.0 * min(1.0, self._outside(mid, a, b))
                said = [t for t in words if a + 0.1 <= t <= b - 0.2 and (mid, t) not in self.used_words]
                if said:
                    sc[j] += 6.0 if (part == "drop" and self.prefer_drop) else 3.0
            sc = sc - recent_pen + self.rng.uniform(0, 0.35, size=len(sc))
            j = int(np.argmax(sc))
            if sc[j] > best_score:
                best, best_score = {"media_id": mid, "source_in": float(starts[j] * STEP)}, float(sc[j])
        if best is not None:
            mid = best["media_id"]
            a0 = best["source_in"]
            for t in self.prefer.get(mid) or []:
                if a0 <= t <= a0 + length:
                    self.used_words.add((mid, t))      # esa frase ya salió: la siguiente vez, otra
            self.used.setdefault(mid, []).append((best["source_in"], best["source_in"] + length))
            src = next((s for s in self.sources if s["media_id"] == mid), None)
            if src is not None and src.get("scene") is not None:
                mid_step = min(int((a0 + length / 2) / STEP), len(src["scene"]) - 1)
                key = (mid, int(src["scene"][mid_step]))
                self.used_scenes[key] = self.used_scenes.get(key, 0) + 1
            self.recent.append(mid)
        return best


def _quotes_texts(quotes: list[str], slots: list[dict], song: dict, start: float, drop: float | None) -> list[dict]:
    """Frases de la intro entre corchetes; la última aparece palabra por palabra, a golpe, y la
    última palabra en rojo (como «[YOU] [ARE] [FORERUNNER]» en el edit de ejemplo)."""
    quotes = [q.strip() for q in quotes if q.strip()]
    if not quotes or drop is None or drop - start < 2.0:
        return []
    out = []
    style = dict(QUOTE_STYLE)
    last_words = quotes[-1].upper().split()
    beats = [b for b in song["beats"] if start < b < drop - 0.05]
    reveal = beats[-len(last_words):] if len(last_words) <= len(beats) // 2 else []
    reveal_from = reveal[0] if reveal else drop
    lines = quotes[:-1] if reveal else quotes
    if lines:
        a0, b0 = start + 0.4, reveal_from - 0.25
        span = (b0 - a0) / len(lines)
        for k, q in enumerate(lines):
            if span > 0.6:
                out.append({"start": a0 + k * span - start, "duration": span - 0.2,
                            "content": f"[{q.upper()}]", "style": style})
    for k, (b, w) in enumerate(zip(reveal, last_words)):
        nb = reveal[k + 1] if k + 1 < len(reveal) else drop
        last = k == len(reveal) - 1
        st = dict(style, size=style["size"] * (1.35 if last else 1.15), bold=last)
        if last:
            st["color"] = QUOTE_RED
        out.append({"start": b - start, "duration": max(0.15, nb - b - 0.02), "content": f"[{w}]", "style": st})
    return out


def plan_edit(song: dict, sources: list[dict], *, length: float | None = 40.0, intensity: str = "intenso",
              flashes: bool = True, punches: bool = True, shake: bool = True,
              quotes: list[str] | None = None, seed: int = 7, learned: dict | None = None) -> dict:
    """Plan completo. Tiempos relativos al inicio del edit (0 = primer fotograma).
    learned: lo aprendido (📚 tus edits de ejemplo: planos quietos, menos destellos…)."""
    start, end, drop = choose_window(song, length)
    slots = build_slots(song, start, end, drop, intensity, len(quotes or []))
    if not slots:
        raise ValueError("La canción es demasiado corta o no se detectó el ritmo.")
    # 🎲 Variedad: nunca 3 planos seguidos de la misma duración; los efectos repartidos (ver ai/edit_variety.py)
    from . import edit_variety as EV
    smap = EV.strength_map(song)
    bl = sorted(song["beats"])
    period = float(np.median(np.diff(bl))) if len(bl) > 2 else 0.5

    def annotate(s_, a_):
        s_["hit"] = smap.get(round(a_, 3), 0.5)
        i_ = int(np.argmin(np.abs(np.array(bl) - a_))) if bl else 0
        s_["bar"] = i_ % 4 == 0
    slots = EV.vary_lengths(slots, [b for b in bl if start <= b <= end], smap, min_len=max(0.8, 2 * period) * 0.98,
                            rng=np.random.default_rng(seed * 17 + 3), kinds=("main",), kind_key="part",
                            protect=lambda s_: drop is not None and abs(s_["a"] - drop) < 0.03, annotate=annotate,
                            max_len=min(8 * period, max(4.5, 4 * period)))
    D = EV.Director(song, seed)
    ref = (learned or {}).get("ref")
    if ref:                                   # 📚 como en tus ejemplos: más planos quietos
        D.still_p = float(np.clip(ref.get("still_share", 0.0), 0.0, 0.9))
    fxm = (learned or {}).get("fx_mult") or {}
    picker = _Picker(sources, seed)
    clips = []
    strength = dict(zip(song["beats"], song["strength"]))
    for k, s in enumerate(slots):
        L = s["b"] - s["a"]
        target = 0.25 if s["part"] == "intro" else 0.35 + 0.6 * s["energy"]
        choice = picker.pick(L, target, s["part"])
        if choice is None:
            continue
        fx: dict = {}
        zoom: list[tuple[float, float, bool]] = []
        if s["part"] == "intro":
            zoom = D.motion("intro", L)       # acercar, alejar o deslizar (sin repetir el mismo seguido)
            if k == 0:
                fx["fade_in"] = min(0.8, L / 3)
            if k + 1 < len(slots) and slots[k + 1]["part"] != "intro":
                fx["fade_out"] = min(0.25, L / 4)   # un instante a negro justo antes del drop
        else:
            is_drop = drop is not None and abs(s["a"] - drop) < 0.02
            hit = max(s["hit"], strength.get(s["a"], 0.0))
            if is_drop:
                if flashes:
                    fx["flash"] = 0.18
                    D.use("flash", k)
                if shake:
                    fx["shake"] = min(0.45, L)
                    D.use("shake", k)
                if punches:
                    D.use("punch", k)
            elif hit > 0.55:              # 🎲 a los golpes fuertes, con descanso y sin repetir seguido
                if flashes and D.ok("flash", k, "drop", hit, boost=(1.1 if s["bar"] else 0.7) * fxm.get("flash", 1.0)):
                    fx["flash"] = 0.08
                elif shake and hit > 0.7 and D.ok("shake", k, "drop", hit):
                    fx.update(shake=min(0.25, L), shake_amp=round(0.01 + 0.008 * hit, 4))
            if punches and L >= 0.2 and (is_drop or ((s["bar"] or hit > 0.8) and hit > 0.5 and
                                                     D.ok("punch", k, "drop", hit, boost=fxm.get("punch", 1.0)))):
                d = min(0.3, L * 0.8)
                zoom = [(0.0, 1.22, False), (d, 1.0, False)]   # zoom de golpe
            elif L > 1.0:
                zoom = D.motion("main", L)   # acercar, alejar, deslizar… o quieto (variado)
            if s["part"] == "outro":
                fx["fade_out"] = min(1.2, L * 0.6)
        clips.append({"media_id": choice["media_id"], "source_in": round(choice["source_in"], 3),
                      "start": round(s["a"] - start, 4), "duration": round(L, 4), "fx": fx, "zoom": zoom,
                      "part": s["part"]})
    texts = _quotes_texts(quotes or [], slots, song, start, drop)
    total = end - start
    n_main = sum(1 for c in clips if c["part"] != "intro")
    main_len = (total - ((drop - start) if drop is not None else 0)) / max(1, n_main)
    return {
        "music": {"source_in": round(start, 3), "duration": round(total, 3), "fade_out": min(1.5, total * 0.05)},
        "clips": clips, "texts": texts, "drop": None if drop is None else round(drop - start, 3),
        "tempo": song.get("tempo"),
        "summary": (f"{len(clips)} planos en {total:.0f} s · {song.get('tempo', 0):.0f} BPM · "
                    + (f"drop a los {drop - start:.1f} s · " if drop is not None else "sin drop claro · ")
                    + f"~{main_len:.2f} s por plano tras el drop"),
    }


def make_edit(song_path: str, song_media_id: str, sources: list[dict], options: dict,
              progress: ProgressFn = None, cancelled: CancelFn = None) -> dict:
    """Todo el proceso (para ejecutar en segundo plano). sources: [{media_id, path, kind, duration}]"""
    if options.get("style") in (None, "halo"):    # (el estilo antiguo se fusionó con «Hype gaming»)
        options = dict(options, style="hype")
    report(progress, 0.02, "Escuchando la canción (golpes, bombo, caja y drop)…")
    song = analyze_song(song_path)
    style = options.get("style")
    if style and style != "halo":
        from . import edit_engine
        edit_engine.enrich(song, media_tools.decode_mono(song_path, music_analysis.SR), music_analysis.SR)
    check_cancel(cancelled)
    avoid = options.get("avoid") or {}
    ranges = options.get("ranges") or {}
    for s in sources:                       # 👎 momentos vetados en este proyecto
        if avoid.get(s["media_id"]):
            s["avoid"] = list(avoid[s["media_id"]])
        if ranges.get(s["media_id"]):         # ✂ solo de los tramos que elegiste a mano
            s["only"] = [list(r) for r in ranges[s["media_id"]]]
        hits = (options.get("keyword_hits") or {}).get(s["media_id"])
        if hits:                              # 🔑 donde se dicen tus palabras clave
            s["prefer"] = list(hits)
            s["prefer_drop"] = bool(options.get("keyword_drop"))
    vids = [s for s in sources if s["kind"] == "video"]
    for i, s in enumerate(vids):
        report(progress, 0.05 + 0.85 * i / max(1, len(vids)), f"Viendo el movimiento de «{s['name']}»…")
        long_txt = " (video largo: solo los fotogramas clave)" if (s.get("duration") or 0) > LONG_VIDEO else ""

        def sub_prog(f, i=i, s=s, long_txt=long_txt):   # la barra avanza DENTRO de cada video
            report(progress, 0.05 + 0.85 * (i + f) / max(1, len(vids)),
                   f"Viendo el movimiento de «{s['name']}» · {int(f * 100)} %{long_txt}")
        try:
            s["profile"] = motion_profile(s["path"], s["duration"], cancelled, sub_prog)
        except OSError:
            s["profile"] = None
        check_cancel(cancelled)
    report(progress, 0.95, "Montando el edit…")
    if style and style != "halo":
        from . import edit_engine
        plan = edit_engine.plan_v2(song, sources, style=style, length=options.get("length", 40.0),
                                   quotes=options.get("quotes"), seed=options.get("seed", 7),
                                   overrides=options.get("overrides"), learned=options.get("learned"),
                                   variation=bool(options.get("variation")), window=options.get("window"))
    else:
        legacy = {k: v for k, v in options.items() if k in ("length", "intensity", "flashes", "punches", "shake",
                                                            "quotes", "seed", "learned")}
        plan = plan_edit(song, sources, **legacy)
    plan["music"]["media_id"] = song_media_id
    report(progress, 1.0, "Listo")
    return plan
