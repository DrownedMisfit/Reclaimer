"""
Efectos de sonido PROPIOS de Reclaimer, generados con matemáticas (sin descargar nada).
Son 100 % tuyos: sin licencias, sin atribución y sin riesgo de reclamaciones de Content ID.

Cada efecto se crea la primera vez que se usa y se guarda como .wav en
datos/cache/efectos (junto al programa) (estéreo, 48 kHz).
"""
from __future__ import annotations

import os
import wave

import numpy as np

from .paths import cache_dir

SR = 48000

# clave: (nombre visible, categoría, descripción)
CATALOG = {
    "whoosh": ("Whoosh corto", "Transiciones", "Barrido de aire rápido, de izquierda a derecha. Para cortes y zooms."),
    "whoosh_largo": ("Whoosh largo", "Transiciones", "Barrido lento y amplio. Para cambios de tema."),
    "swoosh_grave": ("Swoosh grave", "Transiciones", "Barrido oscuro y pesado, más cinematográfico."),
    "impacto": ("Impacto cinematográfico", "Golpes", "Golpe grave con cola larga. Para el drop o una revelación."),
    "golpe": ("Golpe seco", "Golpes", "Golpe corto y contundente. Para zooms de golpe."),
    "sub_drop": ("Caída de bajo (sub drop)", "Golpes", "Bajo que cae de agudo a muy grave."),
    "riser": ("Subida (riser) 3 s", "Tensión", "Sube la tensión antes del drop o de una revelación."),
    "riser_largo": ("Subida (riser) 6 s", "Tensión", "Subida larga para intros."),
    "caida": ("Bajada (downlifter)", "Tensión", "Lo contrario de la subida: suelta la tensión."),
    "glitch": ("Glitch digital", "Digital", "Interferencia digital entrecortada."),
    "clic": ("Clic de interfaz", "Digital", "Clic limpio para textos o menús."),
    "brillo": ("Destello sonoro", "Digital", "Brillo agudo para un destello o un texto que aparece."),
    "obturador": ("Obturador de cámara", "Digital", "Foto: para congelar imagen o capturas."),
    # 🎬 para las escenas (⚡ prehechas): acción y reacciones
    "disparo": ("Disparo", "Acción", "Disparo seco con su eco corto. Uno por cada retroceso del arma."),
    "punetazo": ("Puñetazo", "Acción", "Golpe de puño o patada: seco y con cuerpo."),
    "explosion": ("Explosión", "Acción", "Estallido grave con cola larga."),
    "pasos": ("Pasos corriendo", "Acción", "Pasos rápidos durante 1,6 s (persecuciones, huidas)."),
    "susto": ("Susto (golpe de tensión)", "Reacción", "Acorde disonante de golpe: sorpresa, aparece algo, emboscada."),
    "victoria": ("Fanfarria de victoria", "Reacción", "Arpegio alegre que sube: victoria, celebración."),
    "derrota": ("Trombón triste", "Reacción", "«Buah, buah, buaaah»: derrota, fracaso, cae derrotado."),
}


def folder() -> str:
    return str(cache_dir("efectos"))


def path_for(key: str) -> str:
    """Ruta del .wav del efecto (lo genera si no existe)."""
    name = CATALOG[key][0]
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -()").strip()
    p = os.path.join(folder(), f"{safe}.wav")
    if not os.path.exists(p):
        write_wav(p, GENERATORS[key]())
    return p


def write_wav(path: str, stereo: np.ndarray):
    x = np.clip(stereo, -1, 1)
    k = min(len(x), int(0.02 * SR))
    x[-k:] *= np.linspace(1, 0, k)[:, None]       # 20 ms de fundido al final: sin chasquidos
    peak = float(np.abs(x).max()) or 1.0
    x = x / peak * 0.89                       # -1 dB de pico
    data = (x * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ---------------------------------------------------------------- utilidades
def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def _noise(n: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def _sweep_band(x: np.ndarray, centers: np.ndarray, width: float = 0.6, hop: int = 256) -> np.ndarray:
    """Filtro de banda que se mueve en el tiempo (por bloques en frecuencia). centers: Hz por muestra."""
    n = 1024
    win = np.hanning(n)
    out = np.zeros(len(x) + n)
    norm = np.zeros(len(x) + n)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    for i in range(0, len(x), hop):
        seg = np.zeros(n)
        chunk = x[i:i + n]
        seg[:len(chunk)] = chunk
        f0 = centers[min(i, len(centers) - 1)]
        spec = np.fft.rfft(seg * win)
        g = np.exp(-0.5 * (np.log2(np.maximum(freqs, 1) / f0) / width) ** 2)
        out[i:i + n] += np.fft.irfft(spec * g, n) * win
        norm[i:i + n] += win ** 2
    return out[:len(x)] / np.maximum(norm[:len(x)], 1e-6)


def _lowpass(x: np.ndarray, fc: float) -> np.ndarray:
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def _reverb(x: np.ndarray, decay: float = 1.2, mix: float = 0.25) -> np.ndarray:
    """Cola de reverberación sencilla (convolución con ruido que decae)."""
    n = int(decay * SR)
    ir = _noise(n, 7) * np.exp(-np.arange(n) / (SR * decay / 5))
    ir /= np.sqrt((ir ** 2).sum()) + 1e-9
    wet = np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.fft.rfft(ir, len(x) + n), len(x) + n)
    dry = np.concatenate([x, np.zeros(n)])
    return (1 - mix) * dry + mix * wet * 3


def _stereo(mono: np.ndarray, pan_from: float = 0.0, pan_to: float = 0.0, width: float = 0.0) -> np.ndarray:
    """Mono → estéreo con paneo (de -1 izquierda a +1 derecha) y algo de anchura."""
    p = np.linspace(pan_from, pan_to, len(mono))
    left = mono * np.cos((p + 1) * np.pi / 4)
    right = mono * np.sin((p + 1) * np.pi / 4)
    if width:
        d = int(0.012 * SR)
        right = (1 - width) * right + width * np.concatenate([np.zeros(d), right[:-d]])
    return np.stack([left, right], axis=1)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.minimum(1, t / max(attack, 1e-4))
    r = np.exp(-np.maximum(0, t - attack) / max(release, 1e-4))
    return a * r


# ---------------------------------------------------------------- generadores
def whoosh(dur: float = 0.7, lo: float = 350, hi: float = 3500, seed: int = 1) -> np.ndarray:
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    bell = np.sin(np.pi * t) ** 1.6
    centers = lo * (hi / lo) ** np.sin(np.pi * t)
    x = _sweep_band(_noise(n, seed), centers, 0.55) * bell
    return _stereo(x, -0.8, 0.8, 0.3)


def swoosh_grave() -> np.ndarray:
    n = int(1.1 * SR)
    t = np.linspace(0, 1, n)
    x = _sweep_band(_noise(n, 3), 120 * (900 / 120) ** np.sin(np.pi * t), 0.7) * np.sin(np.pi * t) ** 1.3
    sub = np.sin(2 * np.pi * np.cumsum(60 + 40 * np.sin(np.pi * t)) / SR) * np.sin(np.pi * t) ** 2 * 0.5
    return _stereo(x + sub, -0.6, 0.6, 0.4)


def impacto() -> np.ndarray:
    n = int(0.9 * SR)
    t = _t(0.9)
    freq = 38 + 90 * np.exp(-t * 18)
    boom = np.sin(2 * np.pi * np.cumsum(freq) / SR) * _env(n, 0.003, 0.35)
    crack = _lowpass(_noise(n, 5), 2500) * _env(n, 0.001, 0.06) * 0.8
    x = _reverb(boom + crack, 2.2, 0.35)
    return _stereo(x, 0, 0, 0.5)


def golpe() -> np.ndarray:
    n = int(0.35 * SR)
    t = _t(0.35)
    freq = 55 + 160 * np.exp(-t * 35)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR) * _env(n, 0.001, 0.09)
    click = _noise(n, 9) * _env(n, 0.0005, 0.008) * 0.6
    return _stereo(_reverb(body + click, 0.4, 0.12), 0, 0, 0.2)


def sub_drop() -> np.ndarray:
    t = _t(1.6)
    freq = 30 + 150 * np.exp(-t * 3.5)
    x = np.sin(2 * np.pi * np.cumsum(freq) / SR) * _env(len(t), 0.005, 0.7)
    return _stereo(x, 0, 0, 0.0)


def riser(dur: float = 3.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    centers = 300 * (6000 / 300) ** (t ** 1.5)
    noise = _sweep_band(_noise(n, 11), centers, 0.9)
    tone = np.sin(2 * np.pi * np.cumsum(180 * (4 ** t)) / SR) * 0.35
    trem = 1 + 0.25 * np.sin(2 * np.pi * np.cumsum(4 + 16 * t) / SR)
    x = (noise + tone) * (t ** 2.2) * trem
    x[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    return _stereo(x, 0, 0, 0.5)


def caida() -> np.ndarray:
    x = riser(2.0)[::-1].copy()
    return x


def glitch() -> np.ndarray:
    rng = np.random.default_rng(13)
    out = []
    for _ in range(9):
        d = int(rng.uniform(0.02, 0.07) * SR)
        kind = rng.integers(0, 3)
        tt = np.arange(d) / SR
        if kind == 0:
            seg = np.sign(np.sin(2 * np.pi * rng.uniform(200, 2000) * tt)) * 0.5
        elif kind == 1:
            seg = np.round(_noise(d, int(rng.integers(0, 999))) * 3) / 3 * 0.6
        else:
            seg = np.zeros(d)
        out.append(seg * np.hanning(d) ** 0.2)
    x = np.concatenate(out)
    return _stereo(x, -0.4, 0.4, 0.3)


def clic() -> np.ndarray:
    n = int(0.08 * SR)
    t = _t(0.08)
    x = np.sin(2 * np.pi * 2200 * t) * _env(n, 0.0005, 0.012) + _noise(n, 4) * _env(n, 0.0003, 0.003) * 0.4
    return _stereo(x, 0, 0, 0)


def brillo() -> np.ndarray:
    t = _t(1.2)
    n = len(t)
    x = np.zeros(n)
    for k, f in enumerate((2093, 2637, 3136, 4186)):
        start = int(k * 0.05 * SR)
        tt = t[:n - start]
        x[start:] += np.sin(2 * np.pi * f * tt) * np.exp(-tt * 4) * 0.25
    x = _reverb(x, 1.5, 0.4)
    return _stereo(x, -0.3, 0.3, 0.6)


def obturador() -> np.ndarray:
    n = int(0.25 * SR)
    a = _noise(n, 21) * _env(n, 0.0005, 0.012)
    b = np.concatenate([np.zeros(int(0.09 * SR)), _noise(n - int(0.09 * SR), 22) * _env(n - int(0.09 * SR), 0.0005, 0.02)])
    x = _sweep_band(a + 0.8 * b, np.full(n, 3000.0), 1.0)
    return _stereo(x, 0, 0, 0.2)


def _lp(x: np.ndarray, fc: float) -> np.ndarray:
    """Paso bajo suave hecho en frecuencia (rápido también con sonidos largos)."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    return np.fft.irfft(np.fft.rfft(x) / (1 + (f / fc) ** 4), n)


def disparo() -> np.ndarray:
    n = int(0.7 * SR)
    t = _t(0.7)
    crack = _noise(n, 31) * _env(n, 0.0004, 0.025)
    cuerpo = _lp(_noise(n, 32), 900) * _env(n, 0.001, 0.09) * 1.6
    boom = np.sin(2 * np.pi * np.cumsum(70 + 140 * np.exp(-t * 40)) / SR) * _env(n, 0.001, 0.12) * 0.9
    return _stereo(_reverb(crack + cuerpo + boom, 0.6, 0.18), 0, 0, 0.3)


def punetazo() -> np.ndarray:
    n = int(0.3 * SR)
    t = _t(0.3)
    golpe_ = np.sin(2 * np.pi * np.cumsum(60 + 120 * np.exp(-t * 45)) / SR) * _env(n, 0.0008, 0.06)
    chasquido = _sweep_band(_noise(n, 41), np.full(n, 1800.0), 0.8) * _env(n, 0.0004, 0.012) * 1.4
    return _stereo(_reverb(golpe_ + chasquido, 0.3, 0.1), 0, 0, 0.15)


def explosion() -> np.ndarray:
    n = int(2.2 * SR)
    t = _t(2.2)
    ruido = _lp(_noise(n, 51), 700) * _env(n, 0.004, 0.45) * 2.0
    boom = np.sin(2 * np.pi * np.cumsum(28 + 70 * np.exp(-t * 6)) / SR) * _env(n, 0.003, 0.6)
    crujido = _noise(n, 52) * _env(n, 0.0005, 0.04) * 0.5
    return _stereo(_reverb(ruido + boom + crujido, 1.8, 0.3), 0, 0, 0.6)


def pasos() -> np.ndarray:
    n = int(1.6 * SR)
    out = np.zeros((n, 2))
    k = int(0.035 * SR)
    for j, t0 in enumerate(np.arange(0.02, 1.55, 0.19)):
        i = int(t0 * SR)
        tt = np.arange(k) / SR
        paso = (np.sin(2 * np.pi * (90 + 40 * np.exp(-tt * 60)) * tt) * 0.8 +
                _lp(_noise(k, 60 + j), 2500) * 0.7) * _env(k, 0.001, 0.02)
        pan = -0.35 if j % 2 else 0.35
        m = min(k, n - i)
        out[i:i + m] += _stereo(paso[:m], pan, pan, 0.0)
    return out


def susto() -> np.ndarray:
    n = int(1.4 * SR)
    t = _t(1.4)
    x = np.zeros(n)
    for f in (196.0, 207.7, 277.2, 415.3, 587.3):          # (un racimo disonante)
        fase = 2 * np.pi * f * t
        x += (np.sin(fase) + 0.5 * np.sin(2 * fase) + 0.33 * np.sin(3 * fase)) * 0.2
    x *= _env(n, 0.004, 0.45)
    golpe_ = _lp(_noise(n, 71), 1500) * _env(n, 0.001, 0.05)
    return _stereo(_reverb(x + golpe_, 1.4, 0.35), -0.2, 0.2, 0.5)


def _nota(f: float, dur: float, brillo_: float = 0.5) -> np.ndarray:
    t = _t(dur)
    fase = 2 * np.pi * f * t
    x = np.sin(fase) + brillo_ * np.sin(3 * fase) / 3 + brillo_ * np.sin(5 * fase) / 5
    return x * _env(len(t), 0.008, dur * 0.6)


def victoria() -> np.ndarray:
    partes = [_nota(f, 0.13) for f in (523.3, 659.3, 784.0)] + [_nota(1046.5, 0.9)]
    x = np.concatenate(partes)
    return _stereo(_reverb(x * 0.6, 1.2, 0.25), -0.1, 0.1, 0.4)


def derrota() -> np.ndarray:
    partes = []
    for f, d in ((233.1, 0.38), (220.0, 0.38), (207.7, 0.38)):
        partes.append(_lp(_nota(f, d, 0.9), 1400))
    t = _t(1.1)
    vib = 196.0 * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * t))
    fase = 2 * np.pi * np.cumsum(vib) / SR
    ultima = (np.sin(fase) + 0.9 * np.sin(3 * fase) / 3 + 0.9 * np.sin(5 * fase) / 5) * _env(len(t), 0.01, 0.6)
    partes.append(_lp(ultima, 1400))
    return _stereo(np.concatenate(partes) * 0.7, 0, 0, 0.3)


GENERATORS = {
    "whoosh": whoosh, "whoosh_largo": lambda: whoosh(1.4, 250, 2500, 2), "swoosh_grave": swoosh_grave,
    "impacto": impacto, "golpe": golpe, "sub_drop": sub_drop, "riser": riser,
    "riser_largo": lambda: riser(6.0), "caida": caida, "glitch": glitch, "clic": clic, "brillo": brillo,
    "obturador": obturador, "disparo": disparo, "punetazo": punetazo, "explosion": explosion, "pasos": pasos,
    "susto": susto, "victoria": victoria, "derrota": derrota,
}
