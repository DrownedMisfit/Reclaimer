"""
🎲 VARIEDAD en los edits musicales (el usuario: «la IA abusa de los efectos… no quiero que se vea igual, el mismo
corte, el mismo filtro, la misma transición una tras otra»).

Lo usan los dos motores (ai/edit_engine.py y el de Halo en ai/edit_maker.py):
  · vary_lengths: nunca más de 2 planos seguidos con la MISMA duración. Se juntan dos en el golpe más flojo o se parte
    uno en el golpe más fuerte que tenga dentro (siempre en golpes, nunca más corto que el mínimo del estilo, sin
    tocar el corte del drop ni pasar de una parte de la canción a otra).
  · Director: reparte efectos, movimientos, velocidades y transiciones:
      - cada efecto tiene su «descanso» (no vuelve hasta pasados N planos) y nunca dos planos seguidos con lo mismo;
      - como mucho 2 efectos de golpe por plano (el drop, los que quiera el estilo);
      - cuántos efectos hay depende de la CANCIÓN (pegada, tempo) y de la PARTE (drop > subida > lo tranquilo), y van a
        los golpes más fuertes, no «uno de cada tres»;
      - el movimiento del plano cambia (acercar, alejar, deslizar a un lado u otro, quieto…) sin repetir seguido;
      - las transiciones se turnan dentro de la familia del estilo.
  · grade_for: el color del estilo con un matiz por parte (lo tranquilo más suave, el drop más intenso), sin
    cambiar su carácter (el blanco y negro sigue siendo blanco y negro).
"""
from __future__ import annotations

import numpy as np

# Cuántos planos tiene que «descansar» cada efecto antes de volver (más = más especial). El doble que antes: el
# usuario (28/10): «reutiliza muchísimo los efectos y eso no me gusta» (con planos de medio segundo, un destello cada
# 3 planos era uno por segundo y medio). Además, cuanto más se ha usado ya, más descansa y menos sale (ok()).
COOLDOWN = {"flash": 4, "invert": 9, "shake": 4, "roll": 11, "glitch": 6, "punch": 3, "pulse": 5, "velocity": 1,
            "lightleak": 6, "rgbsplit": 6, "glow": 4, "strobe": 1, "trans": 3}
# Planos seguidos como mucho con el mismo efecto de cámara (velocity)
MAX_RUN = {"velocity": 2}
SAME_TOL = 0.10            # dos planos «miden lo mismo» si difieren menos de un 10 %


def song_drive(song: dict) -> float:
    """0–1: cuánta «caña» tiene la canción (pegada de la batería y tempo). Con más, más efectos."""
    pu = song.get("punch") or {}
    peak, ratio = float(pu.get("peak", 0.3)), float(pu.get("ratio", 1.9))
    tempo = float(song.get("tempo") or 110)
    d = 0.35 * np.clip((peak - 0.15) / 0.35, 0, 1) + 0.35 * np.clip((ratio - 1.4) / 1.2, 0, 1) + \
        0.3 * np.clip((tempo - 80) / 80, 0, 1)
    return float(np.clip(d, 0.15, 1.0))


# ------------------------------------------------------------------ duraciones
def vary_lengths(slots: list[dict], beats: list[float], strength: dict, *, min_len: float, rng,
                 kinds: tuple = ("drop", "main"), kind_key: str = "kind", protect=None, annotate=None,
                 max_len: float = 4.5) -> list[dict]:
    """Rompe las rachas de planos iguales (3 o más seguidos de la misma duración).
    strength: {golpe: 0–1}. protect(slot) → True si su corte de inicio no se puede tocar (el drop).
    annotate(slot_nuevo, a) rellena lo que el motor necesite (golpe, compás…) de un plano que empieza en a."""
    slots = [dict(s) for s in slots]
    protect = protect or (lambda s: False)
    bt = np.array(sorted(beats)) if beats else np.array([])
    flip = bool(rng.random() < 0.5)            # empieza juntando o partiendo (cambia con la semilla)

    def L(s):
        return s["b"] - s["a"]

    def eligible(s):
        return s.get(kind_key) in kinds and not s.get("sub")

    def same(x, y):
        return abs(L(x) - L(y)) <= SAME_TOL * max(L(x), L(y))

    def inner_beats(s):
        if not len(bt):
            return []
        return [float(b) for b in bt if s["a"] + min_len - 1e-3 <= b <= s["b"] - min_len + 1e-3]

    for _it in range(400):
        run = None
        i = 0
        while i < len(slots):
            if not eligible(slots[i]):
                i += 1
                continue
            j = i
            while j + 1 < len(slots) and eligible(slots[j + 1]) and slots[j + 1][kind_key] == slots[i][kind_key] \
                    and same(slots[j + 1], slots[i]):
                j += 1
            if j - i + 1 >= 3:
                run = (i, j)
                break
            i = j + 1
        if run is None:
            break
        i, j = run
        # Primero, MOVER un corte de la racha a otro golpe fuerte cercano (8+8 → 6+10 golpes): rompe la racha sin
        # cambiar cuánto duran los planos de media (así no deshace lo aprendido: «planos más largos en el drop»)
        shifts = []
        for k in range(i + 1, j + 1):
            if protect(slots[k]):
                continue
            a0, t0, b0 = slots[k - 1]["a"], slots[k]["a"], slots[k]["b"]
            span = min(t0 - a0, b0 - t0)
            for b in (bt[(bt >= a0 + min_len - 1e-3) & (bt <= b0 - min_len + 1e-3)] if len(bt) else []):
                d = abs(float(b) - t0)
                if 0.2 * span <= d <= 0.5 * span:
                    sc = strength.get(round(float(b), 3), strength.get(float(b), 0.5)) + rng.uniform(0, 0.2)
                    shifts.append((sc, k, float(b)))
        if shifts:
            _sc, k, b = max(shifts)
            slots[k - 1]["b"] = b
            slots[k]["a"] = b
            slots[k]["phrase"] = False
            if annotate:
                annotate(slots[k], b)
            continue
        merges = [k for k in range(i + 1, j + 1) if not protect(slots[k]) and L(slots[k - 1]) + L(slots[k]) <= max_len]
        splits = [k for k in range(i, j + 1) if inner_beats(slots[k])]
        do_merge = bool(merges) and (flip or not splits)
        flip = not flip
        if do_merge:
            # el corte más flojo de la racha desaparece (con algo de azar entre los parecidos)
            w = np.array([strength.get(round(slots[k]["a"], 3), strength.get(slots[k]["a"], 0.5)) for k in merges])
            w = w + rng.uniform(0, 0.15, len(w))
            k = merges[int(np.argmin(w))]
            slots[k - 1]["b"] = slots[k]["b"]
            del slots[k]
        elif splits:
            best = None
            for k in splits:
                for b in inner_beats(slots[k]):
                    sc = strength.get(round(b, 3), strength.get(b, 0.5)) + rng.uniform(0, 0.15)
                    if best is None or sc > best[0]:
                        best = (sc, k, b)
            _sc, k, b = best
            s = slots[k]
            new = dict(s, a=b)
            for key in ("phrase",):
                new[key] = False
            if annotate:
                annotate(new, b)
            s["b"] = b
            slots.insert(k + 1, new)
        else:
            break                      # nada que hacer (planos al mínimo y sin golpes dentro)
    return slots


def strength_map(song: dict) -> dict:
    return {round(float(b), 3): float(s) for b, s in zip(song.get("beats") or [], song.get("strength") or [])}


# ------------------------------------------------------------------ el director
class Director:
    """Reparte efectos, movimientos, velocidades y transiciones para que el edit no se repita."""

    LEVEL = {"drop": 1.0, "main": 0.9, "build": 0.7, "break": 0.3, "intro": 0.25, "outro": 0.3}

    def __init__(self, song: dict, seed: int):
        self.rng = np.random.default_rng(seed * 31 + 5)
        self.drive = song_drive(song)
        self.count: dict[str, int] = {}          # cuántas veces va ya cada efecto en este edit
        self.last: dict[str, int] = {}
        self.run: dict[str, int] = {}
        self.motions: list[str] = []
        self.trans: list[str] = []
        self.shot_fx: dict[int, int] = {}
        self.still_p = 0.0          # 📚 de tus ejemplos: qué parte de los planos se queda QUIETA
        self.looks: list[str] = []

    # --- efectos de golpe
    def chance(self, kind: str, strength: float) -> float:
        """Probabilidad base de poner un efecto en este plano: la canción, la parte y la fuerza del golpe."""
        lvl = self.LEVEL.get(kind, 0.6)
        return float(np.clip((0.25 + 0.75 * self.drive) * lvl * (0.35 + 0.9 * strength), 0.0, 0.95))

    def ok(self, key: str, k: int, kind: str = "drop", strength: float = 0.7, boost: float = 1.0) -> bool:
        """¿Puede ir este efecto en el plano k? (descanso, no repetir seguido, como mucho 2 por plano, y azar
        según la canción). Si dice que sí, ya cuenta como usado."""
        if self.shot_fx.get(k, 0) >= 2:
            return False
        n = self.count.get(key, 0)                 # lo ya usado: cada 2 veces, un plano más de descanso
        cd = COOLDOWN.get(key, 2) + n // 2
        if k - self.last.get(key, -99) <= cd:
            return False
        if self.rng.random() >= min(0.97, self.chance(kind, strength) * boost / (1.0 + 0.35 * n)):
            return False
        self.use(key, k)
        return True

    def use(self, key: str, k: int):
        self.run[key] = self.run.get(key, 0) + 1 if self.last.get(key) == k - 1 else 1
        self.last[key] = k
        self.count[key] = self.count.get(key, 0) + 1
        if key not in ("velocity", "trans"):
            self.shot_fx[k] = self.shot_fx.get(k, 0) + 1

    def velocity(self, k: int, kind: str, strength: float, on: bool) -> bool:
        """Velocity (lento → acelerón) en algunos planos, no en todos: los golpes fuertes; nunca 3 seguidos."""
        if not on:
            return False
        if self.last.get("velocity") == k - 1 and self.run.get("velocity", 0) >= MAX_RUN["velocity"]:
            return False
        p = (0.3 + 0.45 * strength) * (0.7 + 0.3 * self.drive) * (1.0 if kind == "drop" else 0.75)
        if self.last.get("velocity") == k - 1:
            p *= 0.6
        if self.rng.random() < p:
            self.use("velocity", k)
            return True
        return False

    def ramp(self) -> list[tuple[float, float]]:
        """Distintas rampas de velocity (no siempre la misma): (fracción del plano, velocidad)."""
        options = [[(0.45, 0.35), (0.55, 2.4)],          # el clásico: lento en el golpe → acelerón
                   [(0.55, 0.35), (0.45, 2.4)],          # se recrea más en lo lento
                   [(0.35, 0.35), (0.65, 1.8)],          # lento corto y acelerón suave
                   [(0.6, 2.4), (0.4, 0.35)]]            # al revés: acelerón y frena en el siguiente golpe
        w = np.array([0.4, 0.25, 0.2, 0.15])
        return options[int(self.rng.choice(len(options), p=w / w.sum()))]

    # --- movimiento de cámara del plano
    def motion(self, kind: str, L: float, allowed: tuple = ("in", "out", "left", "right", "still")) -> list:
        """Zoom/desplazamiento suave del plano, sin repetir el mismo movimiento dos veces seguidas.
        Devuelve claves (segundo, zoom, lineal, x)."""
        if self.still_p > 0 and "still" in allowed and self.rng.random() < self.still_p:
            self.motions.append("still")             # 📚 como en tus ejemplos: imagen quieta
            return []
        opts = [m for m in allowed if not (self.motions and self.motions[-1] == m)]
        if kind in ("intro", "break", "outro"):
            opts = [m for m in opts if m != "still"] or ["in"]
        w = np.array([{"in": 1.0, "out": 0.9, "left": 0.7, "right": 0.7, "still": 0.45}.get(m, 0.5) for m in opts])
        m = opts[int(self.rng.choice(len(opts), p=w / w.sum()))]
        self.motions.append(m)
        amt = 0.12 if kind in ("intro", "break", "outro") else min(0.08, 0.03 * L + 0.02)
        if m == "in":
            return [(0.0, 1.0, True, 0.5), (L, 1.0 + amt, True, 0.5)]
        if m == "out":
            return [(0.0, 1.0 + amt, True, 0.5), (L, 1.0, True, 0.5)]
        if m in ("left", "right"):
            z = 1.0 + max(0.06, amt)
            x0, x1 = (0.56, 0.44) if m == "left" else (0.44, 0.56)
            return [(0.0, z, True, x0), (L, z, True, x1)]
        return []

    # --- transiciones
    def transition(self, main: str, family: tuple) -> str:
        """La del estilo casi siempre al principio; luego se turnan las de su familia (nunca dos iguales seguidas)."""
        pool = [main] + [t for t in family if t != main]
        if not self.trans:
            pick = main
        else:
            opts = [t for t in pool if t != self.trans[-1]] or pool
            w = np.array([2.0 if t == main else 1.0 for t in opts])
            pick = opts[int(self.rng.choice(len(opts), p=w / w.sum()))]
        self.trans.append(pick)
        return pick


# 📚 «La misma imagen, otro look» en un golpe (como en tus edits de ejemplo): qué cambia en el segundo trozo
LOOK_VARIANTS = {
    "bw": ({"bw": True}, None),
    "frio": ({}, {"temperature": -0.6, "tint": 0.15}),
    "calido": ({}, {"temperature": 0.6}),
    "intenso": ({"punchy": 0.8}, {"saturation": 0.35}),
    "rgb": ({"rgbsplit": 0.6}, None),
    "glitch": ({"glitch": 0.12}, None),
    "negativo": ({"invert": 0.08}, None),
    "duotono": ({"duotone": 1.0}, None),
}


def look_variant(D: "Director", invert_share: float, grayscale: bool, allowed=None) -> str:
    """Un look distinto del anterior (el negativo, solo de vez en cuando; en blanco y negro, sin cambios de color).
    allowed: los looks de ese estilo (si los define)."""
    pool = [k for k in (allowed or LOOK_VARIANTS) if k in LOOK_VARIANTS] or list(LOOK_VARIANTS)
    opts = [k for k in pool if not (D.looks and D.looks[-1] == k)] or pool
    if grayscale:
        opts = [k for k in opts if k in ("rgb", "glitch", "negativo", "intenso")]
    w = np.array([max(0.02, invert_share * 3) if k == "negativo" else 1.0 for k in opts])
    k = opts[int(D.rng.choice(len(opts), p=w / w.sum()))]
    D.looks.append(k)
    return k


def grade_for(grade: dict | None, kind: str) -> dict | None:
    """El color del estilo con un matiz según la parte (sin cambiar su carácter)."""
    if not grade:
        return grade
    g = dict(grade)
    if kind in ("intro", "break", "outro"):
        g["contrast"] = round(float(g.get("contrast", 0)) - 0.08, 3)
        if float(g.get("saturation", 0)) > -0.99:
            g["saturation"] = round(float(g.get("saturation", 0)) - 0.08, 3)
        g["exposure"] = round(float(g.get("exposure", 0)) + 0.03, 3)
    elif kind == "drop":
        g["contrast"] = round(float(g.get("contrast", 0)) + 0.06, 3)
        if float(g.get("saturation", 0)) > -0.99:
            g["saturation"] = round(float(g.get("saturation", 0)) + 0.05, 3)
    return g
