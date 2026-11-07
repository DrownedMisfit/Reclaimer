"""
◈ Tu voz, aprendida: un modelo pequeño que sabe, cada 10 ms, si estás diciendo una palabra o no. Se entrena con TUS
grabaciones: Whisper dice qué palabras dijiste, el alineador (ai/align.py) dónde empieza y acaba cada una, y con eso
se le enseña a reconocer tus palabras (tu voz, tu micro, tu sala) solo por el sonido. Después funciona al instante y sin
transcripción (los pesos se guardan en un .npz y se calcula con numpy: no necesita PyTorch).

  features(x) -> [T, N_MELS] (10 ms)              la «huella» del sonido que mira el modelo
  labels(words, T) -> [T] (1 = palabra, 0 = no, -1 = no contar: el borde justo)
  train(pares (audio, palabras), …) -> informe     (necesita PyTorch; solo al entrenar)
  available() / predict(x) -> probabilidad de palabra cada 10 ms
"""
from __future__ import annotations

import json
import os

import numpy as np

SR = 16000
HOP = 0.010
N_FFT, WIN, N_MELS = 512, 400, 40
EDGE = 0.010            # 10 ms a cada lado del borde de una palabra no cuentan (ahí ni el alineador es exacto)
_mel = None


def model_path() -> str:
    from ..core.paths import app_data_dir
    d = os.path.join(str(app_data_dir()), "modelos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "voz_personal.npz")


def info() -> dict | None:
    try:
        with open(model_path()[:-4] + ".json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def available() -> bool:
    return os.path.exists(model_path())


def _mel_fb() -> np.ndarray:
    global _mel
    if _mel is None:
        def hz2mel(h):
            return 2595 * np.log10(1 + h / 700)

        def mel2hz(m):
            return 700 * (10 ** (m / 2595) - 1)
        pts = mel2hz(np.linspace(hz2mel(40), hz2mel(SR / 2), N_MELS + 2))
        bins = np.floor((N_FFT + 1) * pts / SR).astype(int)
        fb = np.zeros((N_MELS, N_FFT // 2 + 1), np.float32)
        for i in range(N_MELS):
            a, b, c = bins[i], bins[i + 1], bins[i + 2]
            for k in range(a, b):
                fb[i, k] = (k - a) / max(1, b - a)
            for k in range(b, c):
                fb[i, k] = (c - k) / max(1, c - b)
        _mel = fb
    return _mel


def features(x: np.ndarray) -> np.ndarray:
    """log-mel cada 10 ms, relativo a lo fuerte que hablas en esa grabación (el percentil 95 de la energía), con un
    suelo: el modelo no depende del volumen de tu micro. (Restar la mediana fallaba: con micro con puerta de ruido, la
    mediana es el silencio total o la voz según cuánto hables; medido: 51 % de acierto en otra grabación.)"""
    hop = int(HOP * SR)
    x = np.asarray(x, np.float32)
    n = 1 + max(0, len(x) - WIN) // hop
    if n <= 0:
        return np.zeros((0, N_MELS), np.float32)
    win = np.hanning(WIN).astype(np.float32)
    out = np.empty((n, N_MELS), np.float32)
    fb = _mel_fb()
    step = 4096
    for i in range(0, n, step):
        m = min(step, n - i)
        idx = (np.arange(m)[:, None] + i) * hop + np.arange(WIN)[None, :]
        frames = x[np.minimum(idx, len(x) - 1)] * win
        spec = np.abs(np.fft.rfft(frames, N_FFT)) ** 2
        out[i:i + m] = np.log10(spec @ fb.T + 1e-10)
    tot = np.log10(np.sum(10 ** out, axis=1) + 1e-10)
    ref = float(np.percentile(tot, 95)) if len(tot) else 0.0
    return np.maximum(out - ref, -8.0).astype(np.float32)


def labels(words: list, n: int) -> np.ndarray:
    y = np.zeros(n, np.int8)
    for w in words:
        a, b = int(round(float(w[0]) / HOP)), int(round(float(w[1]) / HOP))
        y[max(0, a):min(n, b)] = 1
    e = max(1, int(round(EDGE / HOP)))
    edges = np.nonzero(np.diff(y.astype(np.int16)))[0] + 1
    for k in edges:
        y[max(0, k - e):min(n, k + e)] = -1
    return y


def _net():
    import torch
    from torch import nn

    class Net(nn.Module):
        """Convoluciones con dilatación: mira ±0,3 s alrededor de cada fotograma."""
        def __init__(self):
            super().__init__()
            ch = 48
            self.inp = nn.Conv1d(N_MELS, ch, 3, padding=1)
            self.blocks = nn.ModuleList([nn.Conv1d(ch, ch, 3, padding=d, dilation=d) for d in (1, 2, 4, 8, 16)])
            self.out = nn.Conv1d(ch, 1, 1)

        def forward(self, f):                      # f: [B, N_MELS, T]
            h = torch.relu(self.inp(f))
            for b in self.blocks:
                h = h + torch.relu(b(h))
            return self.out(h)[:, 0]              # [B, T] (logits)
    return Net()


def _fit(X: list, Y: list, epochs: int, progress=None) -> tuple[dict, float]:
    """Entrena la red con log-mel [T, N_MELS] y etiquetas [T]; devuelve (pesos para numpy, pérdida media)."""
    import torch
    torch.manual_seed(0)
    torch.set_num_threads(max(2, (os.cpu_count() or 4) // 2))
    mu = np.concatenate(X).mean(axis=0)
    sd = np.concatenate(X).std(axis=0) + 1e-5
    net = _net()
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    seg = 800                                       # trozos de 8 s
    chunks = [(i, s) for i, f in enumerate(X) for s in range(0, max(1, len(f) - seg), seg // 2)]
    rng = np.random.default_rng(0)
    tot, nb = 0.0, 1
    for ep in range(epochs):
        rng.shuffle(chunks)
        net.train()
        tot, nb = 0.0, 0
        for b in range(0, len(chunks), 16):
            fb, yb = [], []
            for i, s in chunks[b:b + 16]:
                f = (X[i][s:s + seg] - mu) / sd
                y = Y[i][s:s + seg]
                if len(f) < seg:
                    f = np.pad(f, ((0, seg - len(f)), (0, 0)))
                    y = np.pad(y, (0, seg - len(y)), constant_values=-1)
                fb.append(f.T)
                yb.append(y)
            f_t = torch.from_numpy(np.stack(fb).astype(np.float32))
            y_t = torch.from_numpy(np.stack(yb).astype(np.float32))
            logit = net(f_t)
            mask = y_t >= 0
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logit[mask], y_t[mask])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach())
            nb += 1
        if progress:
            progress((ep + 1) / epochs, f"◈ Aprendiendo tu voz… vuelta {ep + 1}/{epochs}")
    net.eval()
    w = {k: v.detach().numpy().astype(np.float32) for k, v in net.state_dict().items()}
    w["mu"], w["sd"] = mu.astype(np.float32), sd.astype(np.float32)
    return w, tot / max(1, nb)


def _save(w: dict, report: dict) -> None:
    global _w
    path = model_path()
    tmp = path[:-4] + ".tmp.npz"
    np.savez(tmp, **{k.replace(".", "__"): v for k, v in w.items()})
    os.replace(tmp, path)
    _w = None
    with open(path[:-4] + ".json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)


def train(pairs: list[tuple[np.ndarray, list]], epochs: int = 12, progress=None) -> dict:
    """Entrena con [(audio 16 kHz, palabras afinadas), …] y guarda el modelo. Devuelve un informe."""
    X = [features(x) for x, _w_ in pairs]
    Y = [labels(words, len(f)) for f, (_x, words) in zip(X, pairs)]
    w, loss = _fit(X, Y, epochs, progress)
    rep = {"minutes": round(sum(len(f) for f in X) * HOP / 60, 1), "epochs": epochs, "loss": round(loss, 4)}
    _save(w, rep)
    return rep


# ------------------------------------------------------------------ ejemplos (aprende sola)
# Cada vez que se afinan las palabras de una grabación, se guarda como ejemplo de tu voz (solo la «huella» del sonido
# y dónde hay palabra, no el audio). Con ellos se vuelve a entrenar: cuanto más grabas, mejor te conoce.
EX_MAX_MIN = 180.0      # como mucho 3 horas de ejemplos (se olvidan los más viejos)
MIN_TRAIN_MIN = 5.0     # con menos de 5 minutos todavía no se entrena


def examples_dir() -> str:
    d = os.path.join(os.path.dirname(model_path()), "voz_ejemplos")
    os.makedirs(d, exist_ok=True)
    return d


def add_example(key: str, x: np.ndarray, words: list) -> float:
    """Guarda (o sustituye) el ejemplo de esta grabación. Devuelve los minutos de ejemplos que hay en total."""
    import re
    f = features(x)
    y = labels(words, len(f))
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:80]
    np.savez_compressed(os.path.join(examples_dir(), name + ".npz"), f=f.astype(np.float16), y=y)
    files = sorted((os.path.join(examples_dir(), n) for n in os.listdir(examples_dir()) if n.endswith(".npz")),
                   key=os.path.getmtime, reverse=True)
    total = 0.0
    for p in files:
        try:
            with np.load(p) as z:
                mins = len(z["y"]) * HOP / 60
        except (OSError, ValueError):
            continue
        if total + mins > EX_MAX_MIN and total > 0:
            os.remove(p)
            continue
        total += mins
    return total


# ---- pendientes: al transcribir solo se APUNTA la grabación (instantáneo); decodificar y aprender se hace cuando
# se usa (al abrir «✂ Eliminar silencio» o con Voz → Entrenar). El usuario: «solo entro a subtitular y pierdo
# rendimiento».
def _pending_file() -> str:
    return os.path.join(examples_dir(), "pendientes.json")


def queue_example(path: str, words: list) -> int:
    """Apunta una grabación con sus palabras afinadas para aprender más tarde. Devuelve cuántas hay pendientes."""
    import json
    items = [it for it in pending() if os.path.normcase(it.get("path", "")) != os.path.normcase(path)]
    items.append({"path": path, "words": [list(w) for w in words]})
    tmp = _pending_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[-20:], f, ensure_ascii=False)
    os.replace(tmp, _pending_file())
    return len(items[-20:])


def pending() -> list[dict]:
    import json
    try:
        with open(_pending_file(), encoding="utf-8") as f:
            items = json.load(f)
        return [it for it in items if isinstance(it, dict) and it.get("path") and it.get("words")]
    except (OSError, ValueError):
        return []


def process_pending(progress=None, cancelled=None) -> int:
    """Convierte las grabaciones apuntadas en ejemplos (decodifica su audio). Devuelve cuántas se añadieron."""
    from ..core import media as media_tools
    items = pending()
    hechas = 0
    for i, it in enumerate(items):
        if cancelled and cancelled():
            break
        if progress:
            progress(0.02 + 0.08 * i / max(1, len(items)), f"◈ Preparando ejemplos de tu voz… {i + 1}/{len(items)}")
        if os.path.exists(it["path"]):
            try:
                add_example(media_tools.cache_key(it["path"]), media_tools.decode_mono(it["path"], SR), it["words"])
                hechas += 1
            except Exception:  # noqa: BLE001 - una grabación rota no detiene las demás
                pass
    try:
        os.remove(_pending_file())
    except OSError:
        pass
    return hechas


def learn_pending(progress=None, cancelled=None) -> dict | None:
    """Pendientes → ejemplos → entrenar. None si no había nada nuevo o aún hay pocos minutos."""
    if not process_pending(progress, cancelled):
        return None
    return train_from_examples(progress=progress)


def examples() -> list[tuple[np.ndarray, np.ndarray, str]]:
    """[(log-mel, etiquetas, nombre)] del más viejo al más nuevo."""
    out = []
    for n in sorted(os.listdir(examples_dir()), key=lambda n: os.path.getmtime(os.path.join(examples_dir(), n))):
        if not n.endswith(".npz"):            # (pendientes.json y demás no son ejemplos)
            continue
        try:
            with np.load(os.path.join(examples_dir(), n)) as z:
                out.append((z["f"].astype(np.float32), z["y"].astype(np.int8), n[:-4]))
        except (OSError, ValueError):
            continue
    return out


def examples_minutes() -> float:
    return sum(len(y) for _f, y, _n in examples()) * HOP / 60


def train_from_examples(epochs: int = 12, progress=None) -> dict | None:
    """Entrena con todos los ejemplos guardados. Si hay 2 o más, primero se prueba sin el más nuevo y se mide con él
    (una grabación que el modelo no vio): ese es el acierto que se enseña. None si aún hay pocos ejemplos."""
    ex = examples()
    mins = sum(len(y) for _f, y, _n in ex) * HOP / 60
    if mins < MIN_TRAIN_MIN:
        return None
    rep = {"minutes": round(mins, 1), "examples": len(ex), "epochs": epochs}
    if len(ex) >= 2:
        prog = (lambda f, t: progress(f * 0.45, t)) if progress else None
        w, _l = _fit([f for f, _y, _n in ex[:-1]], [y for _f, y, _n in ex[:-1]], epochs, prog)
        global _w
        old = _w
        _w = w
        rep["val"] = _score(ex[-1][0], ex[-1][1])
        _w = old
    prog = (lambda f, t: progress(0.5 + f * 0.5, t)) if progress else None
    w, loss = _fit([f for f, _y, _n in ex], [y for _f, y, _n in ex], epochs, prog)
    rep["loss"] = round(loss, 4)
    _save(w, rep)
    return rep


DILATIONS = (1, 2, 4, 8, 16)
_w = None


def _conv(h: np.ndarray, w: np.ndarray, b: np.ndarray, d: int) -> np.ndarray:
    """Conv1d (núcleo 3, dilatación d, relleno d) con numpy: h [C, T] -> [C_out, T]."""
    c, t = h.shape
    hp = np.pad(h, ((0, 0), (d, d)))
    x3 = np.concatenate([hp[:, 0:t], hp[:, d:d + t], hp[:, 2 * d:2 * d + t]], axis=0)
    w2 = np.concatenate([w[:, :, 0], w[:, :, 1], w[:, :, 2]], axis=1)
    return w2 @ x3 + b[:, None]


def _forward(f: np.ndarray) -> np.ndarray:
    """f: log-mel [T, N_MELS] -> probabilidad [T]. La misma red que _net(), con numpy."""
    global _w
    if _w is None:
        with np.load(model_path()) as z:
            _w = {k.replace("__", "."): z[k] for k in z.files}
    w = _w
    h = ((f - w["mu"]) / w["sd"]).T.astype(np.float32)
    h = np.maximum(_conv(h, w["inp.weight"], w["inp.bias"], 1), 0)
    for i, d in enumerate(DILATIONS):
        h = h + np.maximum(_conv(h, w[f"blocks.{i}.weight"], w[f"blocks.{i}.bias"], d), 0)
    logit = (w["out.weight"][:, :, 0] @ h + w["out.bias"][:, None])[0]
    return 1 / (1 + np.exp(-logit))


def predict(x: np.ndarray) -> np.ndarray:
    """Probabilidad de palabra cada 10 ms (0–1)."""
    f = features(x)
    if not len(f):
        return np.zeros(0, np.float32)
    out = np.empty(len(f), np.float32)
    step, ctx = 30000, 64                           # trozos de 5 min con contexto a los lados
    for i in range(0, len(f), step):
        a, b = max(0, i - ctx), min(len(f), i + step + ctx)
        p = _forward(f[a:b])
        out[i:min(len(f), i + step)] = p[i - a:i - a + min(step, len(f) - i)]
    return out


def _score(f: np.ndarray, y: np.ndarray) -> dict:
    """Acierto cada 10 ms y error en el principio/final de cada tramo de habla (contra las etiquetas)."""
    p = _forward(f) if len(f) else np.zeros(0)
    ok = y >= 0
    acc = float(((p[ok] >= 0.5) == (y[ok] == 1)).mean()) if ok.any() else 0.0
    truth = (y == 1) | (y == -1)
    pred = p >= 0.5
    errs = []
    for m_t, m_p in ((truth, pred),):
        dt = np.diff(np.concatenate([[0], m_t.astype(np.int8), [0]]))
        dp = np.diff(np.concatenate([[0], m_p.astype(np.int8), [0]]))
        for kind in (1, -1):
            t_, p_ = np.nonzero(dt == kind)[0], np.nonzero(dp == kind)[0]
            if len(p_):
                errs += [abs(int(p_[np.argmin(np.abs(p_ - e))]) - e) * HOP * 1000 for e in t_]
    e = np.array(errs) if errs else np.zeros(1)
    return {"acierto": round(acc, 4), "borde_mediana_ms": round(float(np.median(e)), 1),
            "bordes_30ms": round(float(np.mean(e <= 30)), 3)}


def evaluate(x: np.ndarray, words: list) -> dict:
    """Acierto y bordes en una grabación (contra sus palabras afinadas)."""
    f = features(x)
    return _score(f, labels(words, len(f)))
