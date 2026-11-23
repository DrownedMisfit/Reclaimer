"""
🎚 VOZ PAREJA (fase 9): el mismo volumen en todas las frases de la narración, sin tocar el sonido de la voz.

El usuario ya graba la voz igualada en OBS (ReaEQ + compresor 4:1) y no quiere otra ecualización ni otro compresor al
editar. Por eso esto SOLO pone una ganancia suave por frase:
  · cada frase (palabras de la transcripción separadas por pausas de PAUSA s o más) se mide (RMS de sus palabras) y se
    lleva al nivel típico de la narración (la mediana de las frases: el volumen total casi no cambia);
  · como mucho ±LIMITE_DB; las frases muy cortas no cuentan para el nivel típico y toman la ganancia de su vecina; lo
    que está más de MUY_BAJO dB por debajo del típico no sube (palabras sin voz real); entre frases vecinas, como
    mucho SALTO dB de diferencia;
  · el cambio de ganancia se hace en las PAUSAS, en rampas de RAMPA s (sin bombeo dentro de una frase), y en una
    pausa la ganancia nunca sube: va al MENOR de sus dos frases y nunca por encima de 0 dB (el ruido de fondo no sube);
  · se guarda como puntos de la curva de volumen del clip (Clip.vol_kf, marcados «voz»): el visor la oye al momento y
    la exportación igual; un Ctrl+Z la quita; «Quitar» borra solo esos puntos (los tuyos se quedan);
  · nada se hace solo: es una orden (menú Voz). Un clip con puntos de volumen tuyos no se toca (se avisa).

  frases(words) -> [(a, b)]                      tramos del archivo con voz
  niveles(muestras, sr, frases, words) -> [dB]   el nivel de cada frase (RMS de sus palabras)
  ganancias(niveles, duraciones, tramos) -> [dB] lo que hay que subir o bajar cada una
  puntos(frases, ganancias) -> vol_kf            la curva (rampas en las pausas)
  igualar(ctrl, clip_ids=None, muestras=None) -> str    lo aplica (un Ctrl+Z)
  quitar(ctrl, clip_ids=None) -> str
"""
from __future__ import annotations

import math

import numpy as np

PAUSA = 0.35          # s: una pausa así separa dos frases
LIMITE_DB = 6.0       # como mucho ±6 dB por frase
RAMPA = 0.12          # s: lo que dura el cambio de ganancia (en la pausa)
MARGEN = 0.03         # s: la rampa acaba un poco antes de la primera palabra (el ataque de la voz entero)
MIN_FRASE = 0.4       # s: una frase más corta no cuenta para el nivel típico y toma la ganancia de su vecina
MUY_BAJO = 12.0       # dB: más de esto por debajo del nivel típico = palabras transcritas sin voz real: no se suben
SALTO = 4.0           # dB: diferencia máxima de ganancia entre dos frases vecinas
SR = 16000


def _db(x: float) -> float:
    return 20.0 * math.log10(max(x, 1e-9))


def frases(words: list) -> list[tuple[float, float, int, int]]:
    """[(inicio, fin, primera palabra, última+1)] en segundos del archivo."""
    out = []
    i0 = None
    for i, w in enumerate(words):
        if i0 is None:
            i0 = i
        siguiente = words[i + 1] if i + 1 < len(words) else None
        if siguiente is None or float(siguiente[0]) - float(w[1]) >= PAUSA:
            out.append((float(words[i0][0]), float(w[1]), i0, i + 1))
            i0 = None
    return out


def niveles(muestras: np.ndarray, sr: int, fr: list, words: list) -> list[float]:
    """El nivel (dBFS RMS) de cada frase, solo con lo que suena dentro de sus palabras."""
    out = []
    for _a, _b, i0, i1 in fr:
        trozos = []
        for w in words[i0:i1]:
            x0, x1 = int(float(w[0]) * sr), int(float(w[1]) * sr)
            if x1 > x0:
                trozos.append(muestras[max(0, x0):max(0, x1)])
        s = np.concatenate(trozos) if trozos else np.zeros(1, np.float32)
        out.append(_db(float(np.sqrt(np.mean(np.square(s, dtype=np.float64)))) if len(s) else 0.0))
    return out


def _vecina(k: int, duraciones: list[float], fr: list | None) -> int | None:
    """La frase larga (≥ MIN_FRASE) más cercana a la k: la de la pausa más corta (sin tramos, la más próxima)."""
    n = len(duraciones)
    izq = next((j for j in range(k - 1, -1, -1) if duraciones[j] >= MIN_FRASE), None)
    der = next((j for j in range(k + 1, n) if duraciones[j] >= MIN_FRASE), None)
    if izq is None or der is None:
        return izq if der is None else der
    if fr is not None:
        return izq if fr[k][0] - fr[izq][1] <= fr[der][0] - fr[k][1] else der
    return izq if k - izq <= der - k else der


def ganancias(lv: list[float], duraciones: list[float], fr: list | None = None) -> list[float]:
    """Cada frase al nivel típico (mediana de las frases que cuentan), dentro de ±LIMITE_DB, con estas reservas:
      · lo que está más de MUY_BAJO dB por debajo del típico NO sube (palabras transcritas sin voz real: ruido);
      · las frases de menos de MIN_FRASE s toman la ganancia de su vecina (medir 0,2 s no es fiable);
      · entre frases vecinas, como mucho SALTO dB de diferencia (sin saltos bruscos de una frase a otra).
    fr: los tramos de las frases (para elegir la vecina más cercana en el tiempo)."""
    n = len(lv)
    cuentan = [l for l, d in zip(lv, duraciones) if d >= MIN_FRASE and l > -80] or [l for l in lv if l > -80]
    if not cuentan:
        return [0.0] * n
    tipico = float(np.median(cuentan))
    g = np.array([max(-LIMITE_DB, min(LIMITE_DB, tipico - l)) if l > -80 else 0.0 for l in lv], dtype=np.float64)
    tope = np.array([0.0 if (l <= -80 or l < tipico - MUY_BAJO) else LIMITE_DB for l in lv], dtype=np.float64)
    if any(d >= MIN_FRASE for d in duraciones):
        g0 = g.copy()
        for k in range(n):
            if duraciones[k] < MIN_FRASE:
                j = _vecina(k, duraciones, fr)
                if j is not None:
                    g[k] = g0[j]
    g = np.clip(g, -LIMITE_DB, tope)
    # vecinas a SALTO dB como mucho: por parejas alternas (pares e impares), cada una se acerca a la otra a medias, y
    # luego los topes (proyecciones alternas: siempre hay solución, p. ej. todo a 0 dB)
    for _ in range(3000):
        if n < 2 or float(np.abs(np.diff(g)).max()) <= SALTO + 1e-4:
            break
        for par in (0, 1):
            i = np.arange(par, n - 1, 2)
            d = g[i + 1] - g[i]
            sobra = np.sign(d) * np.maximum(np.abs(d) - SALTO, 0.0) / 2.0
            g[i] += sobra
            g[i + 1] -= sobra
            g = np.clip(g, -LIMITE_DB, tope)
    return [round(float(x), 4) for x in g]


def _v(db: float) -> float:
    return round(10 ** (db / 20.0), 5)


def puntos(fr: list, gs: list[float]) -> list[dict]:
    """La curva de volumen: ganancia fija dentro de cada frase; los cambios, en las pausas y con rampas cortas; en una
    pausa, la menor de sus dos frases y nunca más de 0 dB (el ruido de fondo no sube)."""
    if not fr:
        return []
    kf: list[dict] = []

    def poner(t, db):
        t = round(float(max(0.0, t, kf[-1]["t"] if kf else 0.0)), 4)   # (nunca dos puntos en t=0 ni hacia atrás)
        if kf and abs(kf[-1]["t"] - t) < 1e-4:
            kf[-1]["v"] = _v(db)
        else:
            kf.append({"t": t, "v": _v(db), "voz": True})
    g0 = min(gs[0], 0.0)
    poner(max(0.0, fr[0][0] - MARGEN - RAMPA), g0)
    for k, ((a, b, _i0, _i1), g) in enumerate(zip(fr, gs)):
        poner(a - MARGEN, g)
        poner(b, g)
        if k + 1 < len(fr):
            a2, g2 = fr[k + 1][0], gs[k + 1]
            pausa = a2 - MARGEN - b
            gp = min(g, g2, 0.0)
            if pausa >= 2 * RAMPA + 0.02:
                poner(b + RAMPA, gp)
                poner(a2 - MARGEN - RAMPA, gp)
            # (pausa corta: va en línea recta de una a otra, sin subir: la menor de las dos hasta el final)
    poner(fr[-1][1] + RAMPA, min(gs[-1], 0.0))
    return kf


def _recortar(kf: list[dict], a: float, b: float) -> list[dict]:
    """Solo los puntos del tramo del clip (y el vecino de cada lado): la curva de cada trozo, pequeña."""
    from .curves import recortar
    return recortar(kf, a, b)


def leer(ruta: str, sr: int = SR) -> np.ndarray:
    """🎙 El sonido que de verdad SUENA del clip, en mono: la 1.ª pista de audio de SU archivo (-map 0:a:0), lo mismo que
    el visor (live_mix) y la exportación ([k:a]). Nunca «la mejor» que elegiría FFmpeg por su cuenta. En una grabación
    de OBS con varias pistas separada (obs_tracks), el clip de voz usa su propio archivo: la pista del micrófono."""
    from . import media as M
    r = M.run_quiet([M.ffmpeg(), "-v", "error", "-nostdin", "-i", ruta, "-map", "0:a:0", "-vn", "-ac", "1",
                     "-ar", str(sr), "-f", "s16le", "-"], timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-300:] or "no se pudo leer el audio")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def palabras_de(p, c) -> tuple[list, str | None]:
    """(palabras, id del medio transcrito) del sonido del clip, con los tiempos de su archivo:
      · su propia transcripción;
      · si su archivo es la pista 🎙 de voz separada de una grabación de OBS (Medio.audio_tracks, rol «voz»), la de esa
        grabación (misma base de tiempos: la pista se copió tal cual). La del juego no cuenta: no es narración;
      · si es el archivo de «solo diálogos» de un video (fx["orig_media"]), la del video."""
    own = (p.transcripts.get(c.media_id) or {}).get("words")
    if own:
        return own, c.media_id
    cand = [m.id for m in p.media.values()
            if any(t.get("media_id") == c.media_id and t.get("role") == "voz" for t in (m.audio_tracks or []))]
    orig = (c.fx or {}).get("orig_media")
    if orig:
        cand.append(orig)
    for mid in cand:
        words = (p.transcripts.get(mid) or {}).get("words")
        if words:
            return words, mid
    return [], None


def _clips_voz(p, clip_ids=None) -> list:
    from .model import TRACK_AUDIO
    out = []
    for c in p.clips.values():
        if clip_ids is not None and c.id not in clip_ids:
            continue
        tr = p.track(c.track_id)
        if tr is None or tr.kind != TRACK_AUDIO or c.media_id not in p.media:
            continue
        if not palabras_de(p, c)[0]:
            continue
        out.append(c)
    return out


def calcular(p, media_id: str, muestras: np.ndarray | None = None, sr: int = SR,
             words: list | None = None) -> tuple[list[dict], dict]:
    """La curva de voz pareja de un archivo de narración y un resumen {frases, antes: (min, max), ganancias}.
    media_id: el archivo que SUENA (el del clip; se mide ese). words: las palabras (por defecto, su transcripción)."""
    if words is None:
        words = (p.transcripts.get(media_id) or {}).get("words") or []
    fr = frases(words)
    if muestras is None:
        muestras = leer(p.media[media_id].path, sr)
    lv = niveles(muestras, sr, fr, words)
    gs = ganancias(lv, [b - a for a, b, _i, _j in fr], fr)
    validos = [l for l in lv if l > -80]
    resumen = {"frases": len(fr), "antes": (min(validos), max(validos)) if validos else (0.0, 0.0),
               "ganancias": (min(gs), max(gs)) if gs else (0.0, 0.0), "niveles": lv, "lista": gs, "tramos": fr}
    return puntos(fr, gs), resumen


def igualar(ctrl, clip_ids=None, muestras: dict | None = None) -> str:
    """🎚 Pone la voz pareja en los clips de narración (los elegidos, o todos). Un Ctrl+Z. muestras = {media_id: array}
    (si ya se leyó el audio; si no, se lee aquí)."""
    from .controller import EditError
    p = ctrl.project
    clips = _clips_voz(p, set(clip_ids) if clip_ids else None)
    if not clips:
        return "No hay ninguna narración transcrita en la línea de tiempo (o en lo elegido)."
    tuyos = [c for c in clips if c.vol_kf and not all(k.get("voz") for k in c.vol_kf)]
    clips = [c for c in clips if c not in tuyos]
    if not clips:
        return "Esos clips ya llevan puntos de volumen tuyos: no se tocan (quítalos o usa otros clips)."
    curvas, resumenes, clave = {}, {}, {}
    for c in clips:                          # (se mide el archivo del clip, con las palabras que le tocan)
        words, wmid = palabras_de(p, c)
        clave[c.id] = (c.media_id, wmid)
        if clave[c.id] not in curvas:
            curvas[clave[c.id]], resumenes[clave[c.id]] = calcular(p, c.media_id, (muestras or {}).get(c.media_id),
                                                                   words=words)
    ids = [c.id for c in clips]

    def fn(proj):
        for cid in ids:
            c = proj.clips.get(cid)
            if c is None:
                continue
            ctrl._check_clip(proj, c)
            a, b = float(c.source_in), float(c.source_in) + float(c.src_len)
            c.vol_kf = _recortar(curvas[clave[cid]], a, b)
    if not ctrl._edit("🎚 Voz pareja (volumen igual en cada frase)", fn):
        return ""
    r = next(iter(resumenes.values()))
    aviso = f" ({len(tuyos)} clip(s) con puntos tuyos, sin tocar)" if tuyos else ""
    return (f"✓ Voz pareja: {r['frases']} frases, que iban de {r['antes'][0]:.0f} a {r['antes'][1]:.0f} dB, ahora al mismo "
            f"nivel (ganancias de {r['ganancias'][0]:+.1f} a {r['ganancias'][1]:+.1f} dB, solo volumen: ni ecualizador ni "
            f"compresor){aviso}. Ctrl+Z lo deshace.")


def quitar(ctrl, clip_ids=None) -> str:
    """Quita la voz pareja (solo sus puntos; los tuyos se quedan). Un Ctrl+Z."""
    p = ctrl.project
    clips = [c for c in _clips_voz(p, set(clip_ids) if clip_ids else None) if any(k.get("voz") for k in c.vol_kf or [])]
    if not clips:
        return "No hay voz pareja que quitar."
    ids = [c.id for c in clips]

    def fn(proj):
        for cid in ids:
            c = proj.clips.get(cid)
            if c is not None:
                ctrl._check_clip(proj, c)
                c.vol_kf = [dict(k) for k in c.vol_kf if not k.get("voz")]
    if not ctrl._edit("🎚 Quitar la voz pareja", fn):
        return ""
    return f"✓ Voz pareja quitada de {len(ids)} clip(s). Ctrl+Z la devuelve."
