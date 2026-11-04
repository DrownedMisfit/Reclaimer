"""
Motor de EDITS 2.0: estilos de edit como los de internet (phonk / velocity, blanco y negro épico, hype…).

Se basa en cómo trabajan los generadores open source (mugen: cortes por golpes/medios golpes, sin repetir,
sin planos oscuros ni con cortes dentro; AV-Sync: batería separada, la canción en secciones lentas/rápidas
y el movimiento de los clips acorde a cada sección) y en las técnicas típicas de los edits (velocity,
impact frames, temblor en el bajo, zoom de golpe, estrobo al final de la subida, congelar en las paradas).

  plan_v2(song, sources, style="phonk", **opciones) → el mismo tipo de plan que edit_maker.plan_edit
  (clips con velocidad, color, efectos y transiciones), que el controlador coloca en la timeline.
"""
from __future__ import annotations

import numpy as np

from . import song_structure as SS
from .edit_maker import _Picker, _quotes_texts, choose_window

# Cada estilo es un conjunto de ajustes; en la ventana se puede cambiar cualquiera.
STYLES: dict[str, dict] = {
    "phonk": {
        "name": "🔥 Agresivo / Intenso",
        "desc": "Velocity (cámara lenta en el golpe y acelerón), destellos, temblores con el bajo y color duro.",
        "rgbsplit": 0.25, "punchy": 0.5, "flicker_drop": True, "roll_hits": True, "density": "intenso", "velocity": True, "impact": "flash", "shake": True, "punch": True, "glitch": False,
        "strobe": True, "freeze": True, "transitions": "hblur", "slowmo_calm": False,
        "grade": {"contrast": 0.35, "saturation": 0.1, "exposure": -0.1, "shadows": -0.15},
        "grain": 0.2, "vignette": 0.45, "letterbox": 0.0, "font": "Impact", "color": "#FFFFFF", "accent": "#E5413C"},
    "epico_bn": {
        "name": "🗿 Épico clásico (blanco y negro)",
        "desc": "Blanco y negro muy contrastado, grano, viñeta y barras de cine; cámara lenta dramática, "
                "imagen invertida en el drop y textos grandes con letra clásica.",
        "density": "normal", "velocity": True, "impact": "invert", "shake": True, "punch": True, "glitch": False,
        "strobe": True, "freeze": True, "transitions": "fadeblack", "slowmo_calm": True,
        "grade": {"saturation": -1.0, "contrast": 0.55, "exposure": -0.05, "shadows": -0.25, "highlights": 0.15},
        "grain": 0.5, "vignette": 0.75, "letterbox": 0.11, "font": "Times New Roman", "color": "#FFFFFF",
        "accent": "#FFFFFF"},
    "hype": {
        "name": "⚡ Hype gaming",
        "desc": "Cortes muy rápidos, colores saturados, glitch RGB, zooms y destellos en los golpes fuertes; la intro "
                "respira (con tus frases) y un instante a negro justo antes del drop.",
        "taste": {"predrop_black": True},
        "rgbsplit": 0.4, "punchy": 0.6, "flicker_drop": True, "roll_hits": True, "density": "frenetico", "velocity": True, "impact": "flash", "shake": True, "punch": True, "glitch": True,
        "strobe": True, "freeze": False, "transitions": "zoomin", "slowmo_calm": False,
        "grade": {"saturation": 0.35, "contrast": 0.25}, "grain": 0.0, "vignette": 0.2, "letterbox": 0.0,
        "font": "Impact", "color": "#FFFFFF", "accent": "#FFD400"},
    "cine": {
        "name": "🎬 Cinemático",
        "desc": "Barras de cine, color de película, planos más largos y fundidos; zooms suaves.",
        "punchy": 0.25, "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": True, "transitions": "fade", "slowmo_calm": True,
        "grade": {"contrast": 0.2, "temperature": 0.15, "saturation": -0.1, "shadows": -0.1},
        "grain": 0.15, "vignette": 0.4, "letterbox": 0.11, "font": "Times New Roman", "color": "#FFFFFF",
        "accent": "#FFFFFF"},
    "emocional": {
        "name": "💧 Emocional / lento",
        "desc": "Cámara lenta suave, colores apagados y fundidos: para canciones tranquilas.",
        "glow": 0.35, "leak_calm": True, "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": False, "transitions": "fade", "slowmo_calm": True,
        "grade": {"exposure": 0.1, "saturation": -0.3, "contrast": -0.1, "temperature": -0.1},
        "grain": 0.1, "vignette": 0.35, "letterbox": 0.0, "font": "Times New Roman", "color": "#FFFFFF",
        "accent": "#FFFFFF"},
    "vhs": {
        "name": "📼 Analógico / VHS",
        "desc": "Grano fuerte, glitch y colores retro; destellos en los golpes.",
        "vhs": 0.7, "density": "normal", "velocity": False, "impact": "flash", "shake": True, "punch": False, "glitch": True,
        "strobe": False, "freeze": True, "transitions": "pixelize", "slowmo_calm": False,
        "grade": {"saturation": -0.2, "temperature": 0.2, "contrast": 0.15}, "grain": 0.6, "vignette": 0.55,
        "letterbox": 0.0, "font": "Courier New", "color": "#F5F5DC", "accent": "#E5413C"},
    # Más estilos (cada uno cambia CÓMO se edita: ritmo de cortes, cámara lenta, golpes, transiciones y color)
    "dramatico": {
        "name": "🎭 Dramático",
        "desc": "Planos que respiran, golpes en negativo en los momentos clave, fundidos a negro y contraste alto.",
        "density": "normal", "velocity": False, "impact": "invert", "shake": False, "punch": True, "glitch": False,
        "strobe": False, "freeze": True, "transitions": "fadeblack", "slowmo_calm": True,
        "grade": {"contrast": 0.4, "saturation": -0.25, "shadows": -0.2, "highlights": 0.1},
        "grain": 0.2, "vignette": 0.6, "letterbox": 0.11, "font": "Times New Roman", "color": "#FFFFFF",
        "accent": "#E5413C"},
    "triste": {
        "name": "🌧 Triste / melancólico",
        "desc": "Muy pausado: cámara lenta, colores fríos y apagados, fundidos largos; sin golpes ni temblores.",
        "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": False, "transitions": "fade", "slowmo_calm": True,
        "grade": {"saturation": -0.45, "exposure": -0.05, "temperature": -0.25, "contrast": -0.05},
        "grain": 0.15, "vignette": 0.5, "letterbox": 0.0, "font": "Times New Roman", "color": "#E8EEF5",
        "accent": "#9FB4C8"},
    "misterioso": {
        "name": "🌑 Misterioso / oscuro",
        "desc": "Oscuro y frío, planos largos que se funden con grano; congela en los silencios.",
        "glow": 0.2, "flicker_drop": True, "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": True, "transitions": "dissolve", "slowmo_calm": True,
        "grade": {"exposure": -0.2, "contrast": 0.3, "saturation": -0.3, "shadows": -0.3, "temperature": -0.2},
        "grain": 0.3, "vignette": 0.8, "letterbox": 0.11, "font": "Times New Roman", "color": "#D8D8D8",
        "accent": "#7FA7D9"},
    "tenso": {
        "name": "⚠ Tenso",
        "desc": "Cortes nerviosos en la subida, temblores con el bajo, destellos y latigazos; color duro.",
        "punchy": 0.4, "flicker_drop": True, "density": "normal", "velocity": False, "impact": "flash", "shake": True, "punch": True, "glitch": False,
        "strobe": True, "freeze": True, "transitions": "hblur", "slowmo_calm": False,
        "grade": {"contrast": 0.35, "saturation": -0.2, "temperature": 0.1},
        "grain": 0.25, "vignette": 0.55, "letterbox": 0.0, "font": "Impact", "color": "#FFFFFF",
        "accent": "#F2A03D"},
    "nostalgico": {
        "name": "🕰 Nostálgico",
        "desc": "Cálido y suave, con grano de película y fundidos: como un recuerdo.",
        "glow": 0.3, "leak_calm": True, "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": False, "transitions": "fade", "slowmo_calm": True,
        "grade": {"temperature": 0.3, "saturation": -0.15, "contrast": -0.1, "highlights": -0.1},
        "grain": 0.45, "vignette": 0.5, "letterbox": 0.0, "font": "Georgia", "color": "#F5E6C8",
        "accent": "#F2A03D"},
    "inspirador": {
        "name": "🌅 Inspirador / épico",
        "desc": "Crece con la canción: cámara lenta en lo tranquilo, velocity y destellos en el drop, color luminoso.",
        "glow": 0.3, "leak_calm": True, "roll_hits": True, "density": "normal", "velocity": True, "impact": "flash", "shake": False, "punch": True, "glitch": False,
        "strobe": False, "freeze": False, "transitions": "zoomin", "slowmo_calm": True,
        "grade": {"contrast": 0.2, "saturation": 0.15, "exposure": 0.05, "temperature": 0.1},
        "grain": 0.0, "vignette": 0.3, "letterbox": 0.0, "font": "Arial", "color": "#FFFFFF",
        "accent": "#FFD400"},
    # Aprendidos de los edits de ejemplo del usuario (2026-10-10): la IA los conoce como estilos, no son una opción
    "estilizado": {
        "name": "🎴 Estilizado (looks en los golpes)",
        "desc": "Imágenes casi quietas que cambian de look en los golpes fuertes (duotono morado/verde, negativo, "
                "glitch, RGB); cortes a los golpes reales; casi sin destellos; final que se queda.",
        "density": "normal", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": True,
        "strobe": False, "freeze": True, "transitions": "", "slowmo_calm": False,
        "grade": {"contrast": 0.3, "saturation": 0.25}, "grain": 0.15, "vignette": 0.3, "letterbox": 0.0,
        "font": "Impact", "color": "#FFFFFF", "accent": "#B36BFF",
        "taste": {"accent_sync": 0.73, "look_share": 0.45, "still_share": 0.82, "invert_share": 0.04,
                  "final_hold_s": 6.0, "image_every_beats": 1.2,
                  "looks": ["duotono", "negativo", "glitch", "rgb", "intenso", "frio"]}},
    "historia": {
        "name": "📜 Historia / lore",
        "desc": "Para contar una historia (lore, documentos, escenas): planos que respiran, la misma imagen cambia de "
                "tono en los golpes, fundidos, un parpadeo rápido antes del final y un final largo.",
        "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": True, "transitions": "fade", "slowmo_calm": True,
        "grade": {"contrast": 0.2, "saturation": -0.05, "temperature": -0.1}, "grain": 0.2, "vignette": 0.5,
        "letterbox": 0.0, "font": "Georgia", "color": "#FFFFFF", "accent": "#7FA7D9",
        "taste": {"accent_sync": 0.57, "look_share": 0.5, "still_share": 0.8, "invert_share": 0.02,
                  "final_hold_s": 6.0, "looks": ["frio", "calido", "bw", "intenso", "duotono"], "flicker_end": True}},
    "minimalista": {
        "name": "◻ Minimalista",
        "desc": "Limpio: cortes a ritmo y fundidos, sin efectos ni color fuerte.",
        "density": "tranquilo", "velocity": False, "impact": "", "shake": False, "punch": False, "glitch": False,
        "strobe": False, "freeze": False, "transitions": "fade", "slowmo_calm": False,
        "grade": {"contrast": 0.05}, "grain": 0.0, "vignette": 0.0, "letterbox": 0.0, "font": "Arial",
        "color": "#FFFFFF", "accent": "#FFFFFF"},
}
# Lo que la IA aprendió de los edits de ejemplo del usuario y vale para TODOS los estilos: los cortes caen en los
# golpes FUERTES reales de la canción (bombo, caja), no en una rejilla fija (en sus edits: 73–89 % de los cortes).
GENERAL_TASTE = {"accent_sync": 0.6}
DENSITY = {   # golpes por plano en cada sección: (subida al empezar, drop, pausa)
    # Más pausado que antes (el usuario: «tantos cortes ya no dejan apreciar el detalle»): un plano dura un compás
    # o más; los cortes caen en los compases y en los golpes fuertes de la canción.
    "tranquilo": (8, 8, 16),
    "normal": (4, 4, 8),      # en el drop, un plano por compás
    "intenso": (4, 2, 8),     # en el drop, cada 2 golpes (o 1 en una caja muy fuerte)
    "frenetico": (2, 1, 4),
}
# Lo más rápido que se corta en cada densidad (en golpes). A medio golpe o menos SOLO en la ráfaga (ver BURST).
FASTEST = {"tranquilo": 4, "normal": 2, "intenso": 1, "frenetico": 1}
# ⚡ Ráfaga automática: cortes muy seguidos (al ritmo) justo antes del drop, UNA vez por edit como mucho y solo si la
# canción es enérgica (rock, metal, phonk: batería muy marcada). Si no, nunca: para eso está «⚡ Ráfaga» a mano.
BURST_BEATS = 4
# Y un mínimo EN SEGUNDOS por plano (con canciones rápidas, «un compás» puede ser muy poco): se alarga el plano al
# doble de golpes hasta llegar, así sigue cayendo en el ritmo.
MIN_SHOT = {"tranquilo": 3.0, "normal": 1.7, "intenso": 1.2, "frenetico": 0.8}
KIND_ES = {"intro": "intro", "build": "subida", "drop": "drop", "break": "pausa", "outro": "final"}
STEPS = (0.25, 0.5, 1, 2, 4, 8)          # duraciones de plano «musicales» (en golpes)
DENSITY_ORDER = ("tranquilo", "normal", "intenso", "frenetico")
# Transiciones que se usan en los edits de internet, por «familia» (para el 🔀 Remix)
TRANS_POOL = {"calm": ("fade", "fadeblack", "dissolve", "smoothleft", "circleopen"),
              "hard": ("hblur", "zoomin", "fadewhite", "pixelize", "slideleft", "squeezeh")}


def _accents(song: dict) -> np.ndarray:
    return np.array(sorted(set(round(float(t), 3) for t in (song.get("kick_t") or []) + (song.get("snare_t") or []))))


def _ref_slots(slots, song, ref, drop, start, end, per, min_len, st, seed):
    """📚 Como en tus ejemplos: (1) la imagen cambia más o menos cada lo mismo que en ellos (sin bajar del mínimo de
    tu estilo: nada de cortes de ni un segundo); (2) los cortes van al golpe FUERTE más cercano (bombo/caja), no a una
    rejilla fija; (3) el plano final se queda más tiempo."""
    from . import edit_variety as EV
    rng = np.random.default_rng(seed * 101 + 7)
    out = [dict(s) for s in slots]
    # (1) cada cuánto cambia la imagen: se juntan planos si tus ejemplos los dejan durar más
    want = float(ref.get("image_every_beats", 0) or 0) * per
    if want > 0:
        k = 1
        while k < len(out):
            a, b = out[k - 1], out[k]
            if (a["kind"] == b["kind"] == "drop" and not a.get("sub") and not b.get("sub")
                    and not (drop is not None and abs(b["a"] - drop) < 0.03)
                    and (a["b"] - a["a"]) < want * 0.75 and (b["b"] - a["a"]) <= want * 1.6):
                a["b"] = b["b"]
                del out[k]
                continue
            k += 1
    # (2) a los golpes fuertes
    acc = _accents(song)
    p_snap = float(np.clip(ref.get("accent_sync", 0), 0, 1))
    if len(acc) and p_snap > 0.2:
        for k in range(1, len(out)):
            s, pv = out[k], out[k - 1]
            if s.get("sub") or pv.get("sub") or (drop is not None and abs(s["a"] - drop) < 0.03):
                continue
            if rng.random() > p_snap:
                continue
            near = acc[np.abs(acc - s["a"]) <= 0.3 * per]
            if not len(near):
                continue
            t = float(near[np.argmin(np.abs(near - s["a"]))])
            if t - pv["a"] >= min_len * 0.85 and s["b"] - t >= min_len * 0.85:
                pv["b"] = s["a"] = round(t, 4)
    # (3) un final que respira
    fin = min(float(ref.get("final_hold_s", 0) or 0), 6.0, 0.18 * (end - start))
    while fin > 0 and len(out) > 2 and out[-1]["b"] - out[-1]["a"] < fin * 0.9 and not out[-1].get("sub") \
            and not (drop is not None and abs(out[-1]["a"] - drop) < 0.03):
        out[-2]["b"] = out[-1]["b"]
        out[-2]["kind"] = out[-1]["kind"]
        del out[-1]
    # que no queden tres iguales seguidos tras los cambios
    return EV.vary_lengths(out, [b for b in song["beats"] if start <= b <= end], EV.strength_map(song),
                           min_len=min_len, rng=np.random.default_rng(seed * 17 + 5), kinds=("drop",),
                           protect=lambda s_: drop is not None and abs(s_["a"] - drop) < 0.03,
                           max_len=max(4.5, 8 * per))


def _ref_looks(clips, song, ref, start, D, grade):
    """📚 «La misma imagen, otro look» en un golpe fuerte dentro del plano (en tus ejemplos, casi la mitad de los
    «cortes»): el plano se parte en dos SIN saltar en el video y el segundo trozo cambia de look (color, B/N, RGB,
    glitch; el negativo, poco). Así hay ritmo sin cambiar de imagen a cada golpe (y se aprecia el detalle)."""
    from . import edit_variety as EV
    acc = _accents(song) - start
    share = float(np.clip(ref.get("look_share", 0) * 1.3, 0, 0.85))
    gray = bool(grade and float(grade.get("saturation", 0)) <= -0.99)
    out = []
    shots: dict[int, int] = {}
    for c in clips:
        shots[c["shot"]] = shots.get(c["shot"], 0) + 1
    seen: set = set()
    for c in clips:
        a, L = c["start"], c["duration"]
        if shots[c["shot"]] == 2 and c["shot"] in seen and c.get("kind") in ("drop", "build")                 and D.rng.random() < share:
            # velocity (lento → acelerón): el cambio de look cae justo en el paso a rápido (que ya es un golpe)
            key = EV.look_variant(D, float(ref.get("invert_share", 0)), gray, ref.get("looks"))
            fx_add, col_add = EV.LOOK_VARIANTS[key]
            c2 = dict(c, fx=dict(c.get("fx") or {}, **fx_add), look=key)
            if col_add:
                c2["color"] = dict(c.get("color") or {}, **col_add)
            out.append(c2)
            continue
        seen.add(c["shot"])
        ok = (shots[c["shot"]] == 1 and c.get("speed", 1.0) == 1.0 and c.get("kind") in ("drop", "build")
              and L >= 0.8 and not c.get("trans"))
        inside = acc[(acc > a + 0.3) & (acc < a + L - 0.3)] if ok and len(acc) else []
        if not len(inside) or D.rng.random() > share:
            out.append(c)
            continue
        t = float(inside[np.argmin(np.abs(inside - (a + L / 2)))])
        d1 = round(t - a, 4)
        first = dict(c, duration=d1)
        z = c.get("zoom") or []
        if len(z) == 2 and all(len(k) > 2 and k[2] for k in z):      # movimiento suave: sigue en el segundo trozo
            u = d1 / max(L, 1e-6)
            zm = z[0][1] + (z[1][1] - z[0][1]) * u
            xm = (z[0][3] + (z[1][3] - z[0][3]) * u) if len(z[0]) > 3 else 0.5
            first["zoom"] = [z[0], (d1, round(zm, 4), True, round(xm, 4))]
            z2 = [(0.0, round(zm, 4), True, round(xm, 4)), (round(L - d1, 4), z[1][1], True,
                                                            z[1][3] if len(z[1]) > 3 else 0.5)]
        else:
            z2 = []
        key = EV.look_variant(D, float(ref.get("invert_share", 0)), gray, ref.get("looks"))
        fx_add, col_add = EV.LOOK_VARIANTS[key]
        fx2 = {k: v for k, v in (c.get("fx") or {}).items()
               if k in ("grain", "vignette", "letterbox", "vhs", "punchy", "glow")}
        fx2.update(fx_add)
        second = dict(c, start=round(t, 4), duration=round(L - d1, 4), source_in=round(c["source_in"] + d1, 3),
                      fx=fx2, zoom=z2, look=key)
        if col_add:
            second["color"] = dict(c.get("color") or {}, **col_add)
        out += [first, second]
    return out


def EV_FAMILY(main: str | None) -> tuple:
    """Las transiciones con las que se turna la del estilo (de su misma familia: suaves o fuertes)."""
    if not main:
        return ()
    return TRANS_POOL["calm"] if main in TRANS_POOL["calm"] else TRANS_POOL["hard"]


def _quant(step: float) -> float:
    """El paso (en golpes) más cercano que suena musical: ¼, ½, 1, 2, 4 u 8 golpes."""
    return min(STEPS, key=lambda v: abs(np.log2(max(step, 1e-3)) - np.log2(v)))


def remix_settings(st: dict, rng) -> tuple[dict, list[str]]:
    """🔀 Remix: otra manera de hacer el MISMO estilo (otra densidad cercana, otra transición de su familia,
    otros efectos de los que se usan en internet). Devuelve (ajustes, qué cambió)."""
    st = dict(st)
    notes: list[str] = []
    calm = st["density"] in ("tranquilo",) or (st.get("slowmo_calm") and not st.get("velocity"))
    i = DENSITY_ORDER.index(st["density"]) if st["density"] in DENSITY_ORDER else 1
    if rng.random() < 0.6:
        j = min(len(DENSITY_ORDER) - 1, i + 1) if calm else int(np.clip(i + rng.choice([-1, 1]), 0, 3))
        if j != i:
            st["density"] = DENSITY_ORDER[j]
            notes.append(f"cortes {'más rápidos' if j > i else 'más pausados'}")
    if st.get("transitions"):
        pool = TRANS_POOL["calm" if calm else "hard"]
        st["transitions"] = str(rng.choice([t for t in pool if t != st["transitions"]] or pool))
        from ..core.transitions import NAMES
        notes.append(f"transición «{NAMES.get(st['transitions'], st['transitions'])}»")
    if not calm:
        if rng.random() < 0.5:
            st["pulse"] = True
            notes.append("zoom 3D (entra y sale)")
        for key, name in (("shake", "temblor con el bajo"), ("glitch", "glitch RGB"), ("strobe", "estrobo"),
                          ("freeze", "congelar en las paradas")):
            if rng.random() < 0.3:
                st[key] = not st.get(key)
                notes.append(("+ " if st[key] else "sin ") + name)
        if st.get("impact") and rng.random() < 0.35:
            st["impact"] = "invert" if st["impact"] == "flash" else "flash"
            notes.append("golpe: " + ("negativo" if st["impact"] == "invert" else "destello"))
    elif rng.random() < 0.4:
        st["punch"] = not st.get("punch")
        notes.append(("+ " if st["punch"] else "sin ") + "zoom de golpe")
    return st, notes

OPTION_KEYS = ("density", "velocity", "impact", "shake", "punch", "glitch", "strobe", "freeze", "transitions",
               "slowmo_calm", "grain", "vignette", "letterbox", "grade", "smooth_slow")


EXTRA_KEYS = ("rgbsplit", "glow", "punchy", "vhs", "flicker_drop", "roll_hits", "leak_calm")


def settings_for(style: str, overrides: dict | None = None) -> dict:
    st = dict(STYLES.get(style, STYLES["phonk"]))
    for k, v in (overrides or {}).items():
        if v is not None and k in OPTION_KEYS:
            st[k] = v
    if (overrides or {}).get("extras") is False:      # «Efectos de edit» desmarcado: sin los efectos nuevos
        for k in EXTRA_KEYS:
            st[k] = 0.0 if k in ("rgbsplit", "glow", "punchy", "vhs") else False
        st["motionblur"] = False
    return st


def punch(samples: np.ndarray, sr: int, max_s: float = 240.0) -> dict:
    """«Pegada» ABSOLUTA de la canción (la fuerza de los golpes de cada canción se mide relativa a ella misma, así
    que hasta un sonido suave parecía «fuerte»): cuánto destacan los ataques (cambio brusco del espectro).
    {"peak": percentil 95 del ataque, "ratio": pico / lo normal}. Batería marcada: peak ≳ 0.3 y ratio ≳ 1.9."""
    win, hop = 2048, 1024
    x = samples[: int(max_s * sr)].astype(np.float32)
    n = 1 + (len(x) - win) // hop if len(x) >= win else 0
    if n < 8:
        return {"peak": 0.0, "ratio": 0.0}
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    w = np.hanning(win).astype(np.float32)
    parts = []
    for c in range(0, n, 256):
        mag = np.log1p(10 * np.abs(np.fft.rfft(x[idx[c:c + 257]] * w, axis=1)))
        parts.append(np.maximum(0.0, np.diff(mag, axis=0)).mean(axis=1))
    o = np.concatenate(parts)
    peak = float(np.percentile(o, 95))
    return {"peak": round(peak, 4), "ratio": round(peak / (float(np.median(o)) + 1e-6), 3)}


def energetic(song: dict) -> bool:
    """¿Canción enérgica (rock, metal, phonk…)? Batería muy marcada en la mayoría de golpes y tempo vivo."""
    hits = song.get("hits") or []
    if len(hits) < 16:
        return False
    pu = song.get("punch")
    if pu is not None and (pu["peak"] < 0.3 or pu["ratio"] < 1.9):
        return False                        # sin pegada de verdad (pads, piano suave, ambiente…)
    strong = sum(1 for h in hits if max(float(h.get("kick", 0)), float(h.get("snare", 0))) > 0.6) / len(hits)
    tempo = float(song.get("tempo") or 0)
    if tempo <= 0 and len(song.get("beats") or []) > 4:
        tempo = 60.0 / float(np.median(np.diff(song["beats"])))
    return strong >= 0.55 and tempo >= 95


def enrich(song: dict, samples: np.ndarray, sr: int) -> dict:
    """Añade al análisis de la canción la batería, el compás, las secciones y las paradas."""
    d = SS.drums(samples, sr)
    song["beats"], song["offbeat_fixed"] = SS.fix_offbeat(song["beats"], d, song["duration"])
    song["beats"] = SS.snap_beats(song["beats"], d)
    song["hits"] = SS.beat_hits(song["beats"], d)
    # la fuerza de cada golpe, ahora medida en la batería (la rejilla puede haber cambiado)
    song["strength"] = [round(min(1.0, max(h["kick"], h["snare"])), 3) for h in song["hits"]]
    song["downbeat_phase"] = SS.downbeat_phase(song["hits"])
    song["sections"] = SS.sections(song)
    song["stops"] = SS.stops(song)
    song["kick_t"], song["snare_t"] = d["kick_t"], d["snare_t"]
    song["punch"] = punch(samples, sr)
    return song


# ------------------------------------------------------------------ huecos según la música
def _grid(song: dict, start: float, end: float, drop: float | None, st: dict) -> list[dict]:
    """Huecos (tiempo de la canción) con sección y golpe: los cortes caen en golpes; en la subida se
    aceleran (compás → golpe → medio → cuarto); en el drop según la densidad; en pausas, planos largos."""
    beats = [b for b in song["beats"] if start - 1e-3 <= b <= end + 1e-3]
    if len(beats) < 4:
        return []
    idx = {b: i for i, b in enumerate(song["beats"])}
    hits = song.get("hits") or [{"kick": 0.5, "snare": 0.0, "hat": 0.0}] * len(song["beats"])
    phase = song.get("downbeat_phase", 0)
    secs = song.get("sections") or [{"a": 0, "b": song["duration"], "kind": "drop", "level": 1.0}]
    up, main, calm = DENSITY.get(st["density"], DENSITY["normal"])
    fastest = FASTEST.get(st["density"], 1)
    period = float(np.median(np.diff(beats)))
    burst = bool(st.get("energetic")) and drop is not None and st.get("burst", True) and st["density"] != "tranquilo"
    min_shot = MIN_SHOT.get(st["density"], 1.7)
    slots: list[dict] = []

    def kind_at(t):
        if drop is not None and drop - 1e-3 <= t and (t < drop + period * 0.5):
            return "drop"
        if drop is not None and t < drop - 1e-3:
            s = SS.section_at(secs, t)
            # los 2 compases antes del drop siempre son subida (los cortes se aceleran), suene como suene
            return "build" if s["kind"] in ("build", "drop") or t >= drop - 8 * period - 1e-3 else "intro"
        s = SS.section_at(secs, t)
        if drop is not None and s["kind"] == "build" and s["a"] < drop:   # la subida acaba en el drop
            return "drop"
        return s["kind"]

    i = 0
    if beats[0] - start > 0.25:                 # antes del primer golpe
        slots.append({"a": start, "b": beats[0], "kind": "intro", "hit": {}, "bar": True})
    while i < len(beats) - 1:
        t = beats[i]
        kind = kind_at(t + 1e-3)
        h = hits[idx.get(t, 0)] if idx.get(t, 0) < len(hits) else {}
        bar = (idx.get(t, i) - phase) % 4 == 0
        if kind in ("intro", "outro"):
            step = 8 if kind == "intro" else 4
        elif kind == "break":
            step = calm
        elif kind == "build":
            # cuánto falta para el siguiente drop (o el final de la subida): cortes cada vez más rápidos
            sec = SS.section_at(secs, t)
            nxt = drop if (drop is not None and t < drop) else sec["b"]
            left = (nxt - t) / period
            if burst and nxt == drop and left <= BURST_BEATS + 0.01:
                # ⚡ la única ráfaga del edit (canción enérgica): medio golpe; el último, un cuarto si hay estrobo
                step = 0.25 if (st["strobe"] and left <= 1.01) else 0.5
            else:
                step = max(up if left > 8 else up / 2, fastest)   # se acelera un poco, nunca a medio golpe
        else:                                   # drop / parte fuerte
            step = max(main, fastest)
            if step < 1 and not (h.get("snare", 0) > 0.5 or h.get("kick", 0) > 0.6):
                step = 1
            elif main == 2 and not st.get("energetic"):
                pass                            # canción suave: sin acortar en las cajas
            elif main == 2:
                nh = hits[idx[t] + 1] if t in idx and idx[t] + 1 < len(hits) else {}
                if nh.get("snare", 0) > 0.7:
                    step = 1
        if step >= 1:                           # nunca más corto que el mínimo en segundos (salvo la ráfaga)
            while step * period < min_shot * 0.97 and step < 16:
                step *= 2
        m = (st.get("len_mult") or {}).get(kind)
        if m and abs(m - 1) > 0.05 and step >= 1:   # lo que aprendió de tus 👍/👎: más largos o más cortos aquí
            step = _quant(step * m)             # (después del mínimo: si no, «más largos» no se notaba)
            while step * period < min_shot * 0.97 and step < 16:
                step *= 2
        if step >= 2 and kind != "build":       # los planos largos van alineados al compás (o medio compás)
            align = min(int(step), 4)
            off = (idx.get(t, i) - phase) % align
            if off:
                step = align - off
        if step < 1:
            nxt_b = beats[i + 1]
            n = int(round(1 / step))
            for k in range(n):
                a = t + (nxt_b - t) * k / n
                b = t + (nxt_b - t) * (k + 1) / n
                slots.append({"a": a, "b": b, "kind": kind, "hit": h if k == 0 else {}, "bar": bar and k == 0,
                              "sub": True, "phrase": False, "period": period})
            i += 1
            continue
        j = min(len(beats) - 1, i + int(step))
        if drop is not None and beats[i] < drop < beats[j] - 1e-3:   # nunca saltarse el drop
            j = next(k for k in range(i + 1, len(beats)) if beats[k] >= drop - 1e-3)
        for m in range(i + 1, j):               # un plano no pasa de una sección a otra
            if kind_at(beats[m] + 1e-3) != kind:
                j = m
                break
        slots.append({"a": t, "b": beats[j], "kind": kind, "hit": h, "bar": bar,
                      "phrase": (idx.get(t, i) - phase) % 16 == 0, "period": period})   # frase = 4 compases
        i = j
    # Ningún plano más corto de lo que permite el estilo (los bordes de las partes dejaban planos de un golpe
    # sueltos = cortes «de la nada»): se juntan con el anterior. El corte del drop no se toca nunca.
    min_len = max(fastest * period, min_shot) * 0.95
    k = 1
    while k < len(slots):
        s = slots[k]
        short = not s.get("sub") and s["b"] - s["a"] < min_len
        at_drop = drop is not None and abs(s["a"] - drop) < 0.03
        if short and not at_drop and not slots[k - 1].get("sub"):
            slots[k - 1]["b"] = s["b"]
            del slots[k]
            continue
        if short and at_drop and k >= 2 and not slots[k - 1].get("sub") and \
                slots[k - 1]["b"] - slots[k - 1]["a"] < min_len:
            slots[k - 2]["b"] = slots[k - 1]["b"]     # el plano corto justo antes del drop se une al anterior
            del slots[k - 1]
            continue
        k += 1
    # El PRIMER plano (lo que suena antes del primer golpe) también: si es un trocito, va con el siguiente
    # (antes el bucle empezaba en el segundo y quedaba un corte de menos de un segundo al principio del edit)
    while len(slots) > 1 and slots[0]["b"] - slots[0]["a"] < min_len and not slots[1].get("sub") and             not (drop is not None and abs(slots[1]["a"] - drop) < 0.03):
        slots[1]["a"] = slots[0]["a"]
        slots[1]["kind"] = slots[0]["kind"] if slots[0]["kind"] == "intro" else slots[1]["kind"]
        del slots[0]
    if slots and slots[-1]["b"] < end - 0.05:
        slots[-1]["b"] = end
    if slots:
        slots[-1]["kind"] = "outro" if slots[-1]["kind"] not in ("intro",) else slots[-1]["kind"]
    return [s for s in slots if s["b"] - s["a"] > 0.04]


# ------------------------------------------------------------------ plan
def plan_v2(song: dict, sources: list[dict], *, style: str = "phonk", length: float | None = 40.0,
            quotes: list[str] | None = None, seed: int = 7, overrides: dict | None = None,
            learned: dict | None = None, variation: bool = False, window: list | None = None) -> dict:
    """learned: lo aprendido de tus 👍/👎 (ver ai/edit_feedback.learned) · variation: 🔀 Remix (otra manera)."""
    st = settings_for(style, overrides)
    st["energetic"] = energetic(song)          # ⚡ solo así puede haber (una) ráfaga de cortes
    remix_notes: list[str] = []
    if variation:
        st, remix_notes = remix_settings(st, np.random.default_rng(seed * 7919 + 13))
    learned = learned or {}
    st["len_mult"] = learned.get("len_mult") or {}
    fxm = learned.get("fx_mult") or {}
    if window:                       # 🎛 Mix: el mismo tramo de la canción que el edit original
        start, end, drop = float(window[0]), float(window[1]), (None if window[2] is None else float(window[2]))
    else:
        start, end, drop = choose_window(song, length, intro=7.0 if st["density"] in ("intenso", "frenetico") else 9.0)
    slots = _grid(song, start, end, drop, st)
    if not slots:
        raise ValueError("La canción es demasiado corta o no se detectó el ritmo.")
    # 🎲 Variedad: nunca 3 planos seguidos de la misma duración en la parte fuerte (al ritmo, sin bajar del mínimo)
    from . import edit_variety as EV
    hits_all = song.get("hits") or []
    phase = song.get("downbeat_phase", 0)
    bidx = {round(float(b), 3): i for i, b in enumerate(song["beats"])}

    def annotate(s_, a_):
        i_ = bidx.get(round(a_, 3))
        s_["hit"] = hits_all[i_] if i_ is not None and i_ < len(hits_all) else {}
        s_["bar"] = i_ is not None and (i_ - phase) % 4 == 0
    bts_ = [b for b in song["beats"] if start <= b <= end]
    per_ = float(np.median(np.diff(bts_))) if len(bts_) > 2 else 0.5
    min_len = max(FASTEST.get(st["density"], 1) * per_, MIN_SHOT.get(st["density"], 1.7)) * 0.95
    slots = EV.vary_lengths(slots, bts_, EV.strength_map(song), min_len=min_len,
                            rng=np.random.default_rng(seed * 17 + 3), kinds=("drop",),
                            protect=lambda s_: drop is not None and abs(s_["a"] - drop) < 0.03, annotate=annotate,
                            max_len=max(4.5, 8 * per_))
    ref = dict(GENERAL_TASTE, **(st.get("taste") or {}))     # lo aprendido de los edits de ejemplo
    if ref:
        slots = _ref_slots(slots, song, ref, drop, start, end, per_, min_len, st, seed)
    D = EV.Director(song, seed)
    if ref:
        D.still_p = float(np.clip(ref.get("still_share", 0.0), 0.0, 0.9))
    family = EV_FAMILY(st.get("transitions"))
    picker = _Picker(sources, seed)
    rng = np.random.default_rng(seed)
    lrng = np.random.default_rng(seed + 4242)       # para lo aprendido (no cambia la elección de planos)

    def keep(key: str) -> bool:
        m = fxm.get(key, 1.0)
        return m >= 1.0 or lrng.random() < m

    def extra(key: str) -> bool:
        m = fxm.get(key, 1.0)
        return m > 1.0 and lrng.random() < (m - 1.0) * 0.3
    stops = [(a, d) for a, d in song.get("stops", []) if start < a < end]
    clips: list[dict] = []
    look = {}
    for key in ("grain", "vignette", "letterbox", "vhs"):     # la «textura» del estilo: en todos los planos
        if float(st.get(key) or 0) > 0:
            look[key] = round(float(st[key]), 3)
    # Los efectos «de golpe» del estilo ya NO van en todos los planos (se veía todo igual): el director los reparte
    rgb_v, glow_v, punchy_v = (round(float(st.get(k_) or 0), 3) for k_ in ("rgbsplit", "glow", "punchy"))
    grade = dict(st["grade"]) if st.get("grade") else None
    n_impact = 0
    for k, s in enumerate(slots):
        L = s["b"] - s["a"]
        kind = s["kind"]
        h = s.get("hit") or {}
        is_drop = drop is not None and abs(s["a"] - drop) < 0.03
        energy = 0.25 if kind in ("intro", "break", "outro") else (0.55 if kind == "build" else 0.85)
        hs = max(float(h.get("snare", 0)), float(h.get("kick", 0)))
        # Velocity: cámara lenta en el golpe y acelerón (en ALGUNOS planos, con rampas distintas; siempre en el drop)
        vel_ok = (st["velocity"] or extra("velocity")) and kind in ("drop", "build") and L >= 0.3 and not s.get("sub")
        vel_ok = vel_ok and keep("velocity")
        if is_drop and vel_ok:
            vel = True
            D.use("velocity", k)
        else:
            vel = D.velocity(k, kind, hs, vel_ok)
        slow_calm = st["slowmo_calm"] and kind in ("intro", "break", "outro") and L >= 1.0
        if vel:
            pieces = [(0.45, 0.35), (0.55, 2.4)] if is_drop else D.ramp()
        elif slow_calm:
            pieces = [(1.0, 0.5)]
        else:
            pieces = [(1.0, 1.0)]
        need = sum(L * f * sp for f, sp in pieces)
        choice = picker.pick(max(0.2, need), energy if kind != "drop" else min(1.0, energy + 0.1), kind)
        if choice is None:
            continue
        fx: dict = dict(look)
        if punchy_v > 0 and kind in ("drop", "build"):        # contraste «con pegada»: en lo fuerte, no en lo tranquilo
            fx["punchy"] = punchy_v
        zoom: list = []
        # Efectos al ritmo (🎲 el director: descanso entre usos, nunca dos planos seguidos igual, a los golpes fuertes)
        calm_part = kind in ("intro", "break", "outro")
        if glow_v > 0 and (calm_part or D.ok("glow", k, kind, hs, boost=0.8)):
            fx["glow"] = glow_v
        if st.get("leak_calm") and calm_part and L >= 1.0 and D.ok("lightleak", k, "drop", 0.7):
            fx["lightleak"] = 0.5            # ☀ destello de luz en lo tranquilo
        if is_drop:
            n_impact += 1
            if st.get("flicker_drop"):
                fx["flicker"] = 0.6           # ⚡ parpadeo en el drop
            if st["impact"] == "invert":
                fx["invert"] = round(min(0.12, L / 3), 3)
                D.use("invert", k)
            elif st["impact"] == "flash":
                fx["flash"] = round(min(0.2, L / 2), 3)
                D.use("flash", k)
            if st["shake"]:
                fx["shake"] = round(min(0.5, L), 3)
                D.use("shake", k)
            if rgb_v > 0:
                fx["rgbsplit"] = rgb_v
                D.use("rgbsplit", k)
        elif kind in ("drop", "build"):
            snare, kick = float(h.get("snare", 0)), float(h.get("kick", 0))
            if st["impact"] and snare > 0.55 and L >= 0.12:
                key_i = "invert" if st["impact"] == "invert" and D.rng.random() < 0.4 else "flash"
                if D.ok(key_i, k, kind, snare):
                    n_impact += 1
                    fx[key_i] = round(min(0.07, L / 3), 3)
            if st["shake"] and kick > 0.55 and D.ok("shake", k, kind, kick, boost=1.1 if s.get("bar") else 0.7):
                fx.update(shake=round(min(0.3, L), 3), shake_amp=round(0.012 + 0.01 * kick, 4))
            if st.get("roll_hits") and snare > 0.65 and L >= 0.25 and D.ok("roll", k, kind, snare, boost=0.7):
                fx["roll"] = round(min(0.35, L), 3)    # ↻ giro de cámara en algunos golpes
            if st["glitch"] and (snare > 0.55 or (s.get("sub") and kind == "build")) and \
                    D.ok("glitch", k, kind, max(snare, 0.5)):
                fx["glitch"] = round(min(0.15, L / 2), 3)
            if rgb_v > 0 and D.ok("rgbsplit", k, kind, hs):
                fx["rgbsplit"] = rgb_v
            if st["strobe"] and s.get("sub") and kind == "build" and L < 0.2:
                fx["flash"] = round(min(0.05, L / 2), 3)
        if kind in ("drop", "build") and not is_drop:      # lo aprendido: menos o más de cada efecto
            for key in ("flash", "shake", "invert", "glitch"):
                if key in fx and not keep(key):
                    fx.pop(key, None)
                    fx.pop("shake_amp", None) if key == "shake" else None
            if s.get("bar") and L >= 0.15:
                if "flash" not in fx and extra("flash"):
                    fx["flash"] = round(min(0.06, L / 3), 3)
                if "shake" not in fx and extra("shake"):
                    fx.update(shake=round(min(0.25, L), 3), shake_amp=0.018)
                if "glitch" not in fx and extra("glitch"):
                    fx["glitch"] = round(min(0.1, L / 2), 3)
        punch_here = (is_drop or (s.get("bar") and float(h.get("kick", 0)) > 0.5))
        want_punch = (st["punch"] and keep("punch")) or (extra("punch") and s.get("bar"))
        want_pulse = (st.get("pulse") and keep("pulse")) or (extra("pulse") and s.get("bar"))
        kick_ = float(h.get("kick", 0))
        if want_pulse and kind in ("drop", "build") and punch_here and L >= 0.3 and \
                (is_drop or D.ok("pulse", k, kind, kick_)):
            d = min(0.5, L * 0.9)      # zoom 3D: se acerca y se aleja en el golpe (con el reflejo se ve en 3D)
            zoom = [(0.0, 1.0, False), (d * 0.45, 1.24, False), (d, 1.0, False)]
        elif want_punch and kind in ("drop", "build") and punch_here and L >= 0.2 and \
                (is_drop or D.ok("punch", k, kind, kick_)):
            d = min(0.3, L * 0.8)
            zoom = [(0.0, 1.22, False), (d, 1.0, False)]
        elif calm_part and L > 1.0:
            zoom = D.motion(kind, L)
        elif L >= 0.5 and not vel:   # movimiento de cámara variado (acercar, alejar, deslizar… o quieto)
            zoom = D.motion(kind, L)
        if k == 0:
            fx["fade_in"] = round(min(0.8, L / 3), 3)
        if kind == "outro" and k == len(slots) - 1:
            fx["fade_out"] = round(min(1.4, L * 0.6), 3)
        if ref.get("predrop_black") and drop is not None and k + 1 < len(slots) and \
                abs(slots[k + 1]["a"] - drop) < 0.03 and L >= 0.6:
            fx["fade_out"] = round(min(0.25, L / 4), 3)       # un instante a negro justo antes del drop
        # Transiciones MUSICALES: en los cambios de parte (menos en la entrada del drop: ahí va el golpe) y al
        # empezar cada frase de 4 compases en lo tranquilo. Duran en golpes: 1 en lo tranquilo, ½ en lo fuerte.
        trans = None
        if st["transitions"] and k > 0 and not is_drop and not s.get("sub"):
            prev = slots[k - 1]
            calm_part = kind in ("intro", "break", "outro")
            change = prev["kind"] != kind
            if (change or (calm_part and s.get("phrase"))) and L >= 0.3 and prev["b"] - prev["a"] >= 0.3:
                beat = float(s.get("period") or 0.5)
                d = beat * (1.0 if calm_part else 0.5)
                d = min(d, 1.0, 0.45 * L, 0.45 * (prev["b"] - prev["a"]))
                if d >= 0.12 and keep("trans"):
                    trans = {"type": D.transition(st["transitions"], family), "dur": round(d, 3)}
            elif s.get("phrase") and not calm_part and extra("trans") and L >= 0.3:
                d = min(float(s.get("period") or 0.5) * 0.5, 0.45 * L, 0.45 * (prev["b"] - prev["a"]))
                if d >= 0.12:
                    trans = {"type": D.transition(st["transitions"], family), "dur": round(d, 3)}
        src = choice["source_in"]
        t0 = s["a"] - start
        for p_i, (frac, sp) in enumerate(pieces):
            dur = L * frac
            item = {"media_id": choice["media_id"], "source_in": round(src, 3), "start": round(t0, 4),
                    "duration": round(dur, 4),
                    "fx": dict(fx) if p_i == 0 else (dict(look, motionblur=0.6)
                                                      if sp >= 2 and st.get("motionblur", True) else dict(look)),
                    "zoom": zoom if p_i == 0 else [],
                    "part": "intro" if kind == "intro" else ("outro" if kind == "outro" else "main"),
                    "kind": kind, "speed": sp, "shot": k,
                    # cámara lenta fluida (fotogramas intermedios) también en el velocity
                    "smooth": 0 < sp < 0.99 and (st["slowmo_calm"] or vel) and st.get("smooth_slow", True)}
            if grade:
                item["color"] = EV.grade_for(grade, kind)     # 🎲 el color del estilo, con matiz según la parte
            if trans and p_i == 0:
                item["trans"] = trans
            clips.append(item)
            src += dur * sp
            t0 += dur
    if ref and float(ref.get("look_share", 0)) > 0.05:
        clips = _ref_looks(clips, song, ref, start, D, grade)
    if ref.get("flicker_end") and len({c["shot"] for c in clips}) > 3:
        # 📜 un parpadeo rápido justo antes del plano final (como en el ejemplo de historia)
        last = clips[-1]["shot"]
        prev = [c for c in clips if c["shot"] != last]
        if prev:
            prev[-1]["fx"] = dict(prev[-1].get("fx") or {}, flicker=0.8)
    # Paradas de la música: el plano que suena se congela durante la parada
    if st["freeze"]:
        for a, d in stops:
            rel = a - start
            for it in clips:
                if it["start"] < rel < it["start"] + it["duration"] - 0.05 and it.get("speed", 1) > 0:
                    split = rel - it["start"]
                    # congelado hasta el siguiente corte (que cae en el golpe): el resto de ese plano se quita
                    rest = [o for o in clips[clips.index(it) + 1:] if o["shot"] == it["shot"]]
                    shot_end = (rest[-1]["start"] + rest[-1]["duration"]) if rest else it["start"] + it["duration"]
                    for o in rest:
                        clips.remove(o)
                    frozen = dict(it, start=round(rel, 4), duration=round(shot_end - rel, 4),
                                  source_in=round(it["source_in"] + split * it.get("speed", 1), 3), speed=0.0,
                                  smooth=False, fx=dict(look), zoom=[])
                    it["duration"] = round(split, 4)
                    clips.insert(clips.index(it) + 1, frozen)
                    break
    style_txt = {"font": st["font"], "bold": st["font"] == "Impact", "box": False, "size": 3.3, "y": 0.56,
                 "color": st["color"]}
    texts = _quotes_texts(quotes or [], slots, song, start, drop)
    for tx in texts:
        accent = tx["style"].get("color") not in (None, "#FFFFFF") or tx["style"].get("bold")
        tx["style"] = dict(style_txt, size=tx["style"].get("size", 3.3),
                           color=st["accent"] if accent else st["color"], bold=tx["style"].get("bold", False) or
                           style_txt["bold"])
    total = end - start
    n_cuts = len({c["shot"] for c in clips})
    secs_txt = ", ".join(f"{KIND_ES.get(s['kind'], s['kind'])} {max(0.0, s['a'] - start):.0f}s" for s in song.get("sections", [])
                         if start <= s["a"] < end)[:120]
    sections = [{"a": round(max(0.0, x["a"] - start), 3), "b": round(min(total, x["b"] - start), 3),
                 "kind": x["kind"]} for x in song.get("sections", []) if x["b"] > start and x["a"] < end]
    bts = [b for b in song["beats"] if start <= b <= end]
    period = float(np.median(np.diff(bts))) if len(bts) > 2 else 0.5
    return {
        "music": {"source_in": round(start, 3), "duration": round(total, 3), "fade_out": min(1.5, total * 0.05)},
        "clips": clips, "texts": texts, "drop": None if drop is None else round(drop - start, 3),
        "tempo": song.get("tempo"), "style": style, "sections": sections, "period": round(period, 4),
        "remix": remix_notes, "learned_n": int(learned.get("n", 0)),
        "window": [round(start, 4), round(end, 4), None if drop is None else round(drop, 4)],
        "summary": (f"{STYLES[style]['name']} · {n_cuts} planos en {total:.0f} s · {song.get('tempo', 0):.0f} BPM · "
                    + (f"drop a los {drop - start:.1f} s" if drop is not None else "sin drop claro")
                    + (f" · secciones: {secs_txt}" if secs_txt else "")),
    }
