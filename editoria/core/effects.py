"""
Efectos de un clip para los «edits» (videos musicales): destellos, fundidos y temblor.

Se guardan en Clip.fx, por ejemplo {"flash": 0.12, "shake": 0.4, "fade_out": 0.3}:
  flash     segundos de destello blanco al empezar el clip (el golpe del drop)
  fade_in   segundos de fundido desde negro al empezar
  fade_out  segundos de fundido a negro al acabar
  shake     segundos de temblor al empezar (se va apagando)
  shake_amp fuerza del temblor (fracción de la pantalla, por defecto 0,025)

Efectos de imagen (todo el clip; valores 0–1 salvo que se diga otra cosa):
  bw        blanco y negro (1 = activado)
  vignette  viñeta: oscurece los bordes
  grain     grano de película
  blur      desenfoque
  glitch    segundos de glitch RGB al empezar (separa los colores y tiembla)
  oldfilm   película antigua: tono cálido, grano y viñeta (1 = activado)
  warm / cold  tono cálido o frío (0–1)
  invert    segundos de imagen en negativo al empezar (el «impact frame» de los edits)
  letterbox barras de cine: fracción del alto que tapa cada barra (p. ej. 0,11)

Efectos de edits musicales (los que más se usan en velocity / phonk / AMV, octubre de 2026):
  rgbsplit   separación RGB (aberración cromática) todo el clip (0–1)
  glow       brillo soñador (glow): lo claro brilla y se difumina (0–1)
  motionblur desenfoque de movimiento (estela entre fotogramas; ideal en el acelerón del velocity) (0–1)
  punchy     contraste intenso: más contraste, color y nitidez (0–1)
  vhs        cinta VHS: líneas, colores corridos y ruido (0–1)
  flicker    parpadeo de luz (0–1, todo el clip)
  roll       giro de cámara al entrar: segundos (se va apagando)
  lightleak  destello de luz cálida que cruza la imagen (0–1)

El visor y la exportación usan las mismas fórmulas, para que se vea igual.
"""
from __future__ import annotations

import math

SHAKE_AMP = 0.025
SHAKE_FX, SHAKE_FY = 53.0, 41.0   # frecuencias (rad/s) del temblor horizontal y vertical


LOOKS = ("bw", "vignette", "grain", "blur", "glitch", "oldfilm", "warm", "cold", "invert", "letterbox",
         "rgbsplit", "glow", "motionblur", "punchy", "vhs", "flicker", "roll", "lightleak", "duotone")
# ✦ Los efectos de imagen que se marcan en la línea de tiempo con la pastilla «fx» (y se quitan de un golpe). Los
# fundidos y la transición no cuentan: tienen su propia marca. PARAMS: lo que va con un efecto y se quita con él.
VISIBLE = set(LOOKS) | {"flash", "shake"}
PARAMS = {"shake": ("shake_amp",)}


def visible_of(fx: dict | None) -> list[str]:
    """Los efectos de imagen que lleva un clip (los de la pastilla «fx»)."""
    return [k for k, v in (fx or {}).items() if k in VISIBLE and v not in (0, 0.0, False, None, "")]


def without(fx: dict | None, keys) -> dict | None:
    """Los efectos del clip sin esos (y sin sus parámetros)."""
    drop = set(keys)
    for k in list(drop):
        drop.update(PARAMS.get(k, ()))
    out = {k: v for k, v in (fx or {}).items() if k not in drop}
    return out or None
# 🟣 Duotono: las sombras moradas y las luces verdes (como en los edits estilizados de Halo)
DUO_A, DUO_B = (52, 8, 96), (150, 255, 170)
ROLL_AMP = 0.10       # radianes (~6°)
ROLL_F = 19.0
FLICKER_HZ = 8.0


def is_active(fx: dict | None) -> bool:
    return bool(fx) and (any(float(fx.get(k, 0)) > 0 for k in ("flash", "fade_in", "fade_out", "shake") + LOOKS)
                         or bool(blur_regions(fx)))


# ------------------------------------------------------------- desenfoque por zonas (cuadro / círculo)
# fx["blur_regions"] = [{"shape": "rect"|"ellipse", "x", "y" (centro), "w", "h" (tamaño), "amount" 0–1}]
# todo en fracciones de la caja del clip (lo que ves de ese clip en pantalla).
def blur_regions(fx: dict | None) -> list[dict]:
    out = []
    for r in (fx or {}).get("blur_regions") or []:
        try:
            w, h = min(1.0, max(0.02, float(r["w"]))), min(1.0, max(0.02, float(r["h"])))
            x = min(1 - w / 2, max(w / 2, float(r["x"])))
            y = min(1 - h / 2, max(h / 2, float(r["y"])))
            out.append({"shape": "ellipse" if r.get("shape") == "ellipse" else "rect", "x": x, "y": y, "w": w,
                        "h": h, "amount": min(1.0, max(0.05, float(r.get("amount", 0.6))))})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def new_region(shape: str, box_w: float, box_h: float) -> dict:
    """Una zona nueva en el centro (el círculo, redondo de verdad en pantalla)."""
    w = 0.3
    h = 0.3 if shape == "rect" else min(0.9, w * box_w / max(1.0, box_h))
    return {"shape": shape, "x": 0.5, "y": 0.5, "w": w, "h": h, "amount": 0.6}


def region_blur_graph(regions: list[dict], k: int) -> str:
    """Trozo de filtergraph de FFmpeg: [rz{k}] → zonas desenfocadas → [ro{k}]. Con expresiones relativas al
    tamaño (iw/ih), así vale para cualquier caja. El círculo lleva el borde suavizado."""
    parts = []
    n = len(regions)
    for i, r in enumerate(regions):
        src = f"[rz{k}]" if i == 0 else f"[rq{k}_{i}]"
        dst = f"[ro{k}]" if i == n - 1 else f"[rq{k}_{i + 1}]"
        x0, y0 = r["x"] - r["w"] / 2, r["y"] - r["h"] / 2
        crop = (f"crop=w='trunc(iw*{r['w']:.4f}/2)*2':h='trunc(ih*{r['h']:.4f}/2)*2'"
                f":x='trunc(iw*{x0:.4f})':y='trunc(ih*{y0:.4f})'")
        k_rad = 0.04 + 0.16 * r["amount"]
        blur = (f"boxblur=lr='max(1,min(w,h)*{k_rad:.3f})':lp=3"
                f":cr='max(1,min(cw,ch)*{k_rad:.3f})':cp=3")
        mask = ""
        if r["shape"] == "ellipse":
            mask = (",format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)'"
                    ":a='255*clip((1-sqrt(pow((X-W/2)/(W/2),2)+pow((Y-H/2)/(H/2),2)))/0.12,0,1)'")
        parts.append(f"{src}split[ra{k}_{i}][rc{k}_{i}];[rc{k}_{i}]{crop},{blur}{mask}[rd{k}_{i}];"
                     f"[ra{k}_{i}][rd{k}_{i}]overlay=x='trunc(main_w*{x0:.4f})':y='trunc(main_h*{y0:.4f})'"
                     f":format=auto{dst}")
    return ";".join(parts)


def rgb_px(v: float, w: int) -> int:
    return max(1, int(round(w * 0.004 * (0.5 + 1.5 * v))))


def look_filters(fx: dict | None, w: int = 1920, h: int = 1080) -> list[str]:
    """Filtros de FFmpeg de los efectos de imagen."""
    fx = fx or {}
    out = []
    v = lambda k: float(fx.get(k, 0) or 0)   # noqa: E731
    if v("motionblur") > 0:      # estela: mezcla con los fotogramas anteriores
        nf = 2 + int(round(3 * min(1.0, v("motionblur"))))
        out.append(f"tmix=frames={nf}")
    if v("punchy") > 0:
        p = min(1.0, v("punchy"))
        out += [f"eq=contrast={1 + 0.28 * p:.3f}:saturation={1 + 0.45 * p:.3f}",
                f"unsharp=5:5:{0.9 * p:.2f}"]
    if v("oldfilm") > 0:
        out += ["curves=preset=vintage", "noise=alls=18:allf=t+u", "vignette=angle=PI/4:dither=0"]
    if v("bw") > 0:
        out.append("hue=s=0")
    if v("duotone") > 0:          # 🟣 dos tonos: gris → de morado (sombras) a verde (luces)
        (ar, ag, ab), (br, bg, bb) = DUO_A, DUO_B
        out += ["hue=s=0", "format=rgb24",
                f"lutrgb=r='{ar}+{br - ar}*val/255':g='{ag}+{bg - ag}*val/255':b='{ab}+{bb - ab}*val/255'"]
    if v("warm") > 0:
        out.append(f"colorbalance=rs={0.12 * v('warm'):.3f}:bs={-0.12 * v('warm'):.3f}:rm={0.08 * v('warm'):.3f}")
    if v("cold") > 0:
        out.append(f"colorbalance=rs={-0.10 * v('cold'):.3f}:bs={0.14 * v('cold'):.3f}:bm={0.08 * v('cold'):.3f}")
    if v("blur") > 0:
        out.append(f"gblur=sigma={2 + 18 * v('blur'):.1f}")
    if v("grain") > 0:
        out.append(f"noise=alls={int(6 + 34 * v('grain'))}:allf=t+u")
    if v("vignette") > 0:
        # (sin «dither»: 2,7 veces más rápida al exportar y no se nota; los edits ya llevan grano)
        out.append(f"vignette=angle={0.25 + 0.6 * v('vignette'):.2f}:dither=0")
    if v("glitch") > 0:
        d = v("glitch")
        out.append(f"rgbashift=rh=-10:bh=10:rv=3:bv=-3:enable='lt(t,{d:.3f})'")
    if v("invert") > 0:
        out.append(f"negate=enable='lt(t,{v('invert'):.3f})'")
    if v("rgbsplit") > 0:
        px = rgb_px(min(1.0, v("rgbsplit")), w)
        out.append(f"rgbashift=rh=-{px}:bh={px}")
    if v("vhs") > 0:
        q = min(1.0, v("vhs"))
        px = rgb_px(0.3 * q, w)
        out += [f"rgbashift=rh=-{px}:bh={px}", f"eq=saturation={1 + 0.3 * q:.2f}:contrast={1 + 0.1 * q:.2f}",
                f"noise=alls={int(8 + 18 * q)}:allf=t", "gblur=sigma=0.7",
                f"drawgrid=w=iw:h={max(3, h // 270)}:t=1:c=black@{0.12 + 0.2 * q:.2f}"]
    if v("flicker") > 0:          # la luz parpadea (sube y baja a saltos)
        a = 0.16 * min(1.0, v("flicker"))
        out.append(f"eq=brightness='{a:.3f}*(2*lt(mod(t*{FLICKER_HZ * 2:.1f}\\,2)\\,1)-1)':eval=frame")
    if v("lightleak") > 0:        # una mancha de luz cálida que cruza despacio
        a = min(1.0, v("lightleak"))
        blob = f"{255 * a:.1f}*exp(-(pow(X-W*(0.15+0.7*(0.5+0.5*sin(T*0.6))),2)+pow(Y-H*0.35,2))/(W*W*0.09))"
        out += ["format=rgb24", f"geq=r='min(255,r(X,Y)+{blob})':g='min(255,g(X,Y)+0.55*{blob})'"
                                f":b='min(255,b(X,Y)+0.15*{blob})'"]
    if v("letterbox") > 0:
        f = min(0.3, v("letterbox"))
        out.append(f"drawbox=x=0:y=0:w=iw:h=ih*{f:.3f}:color=black:t=fill,"
                   f"drawbox=x=0:y=ih*{1 - f:.3f}:w=iw:h=ih*{f:.3f}+1:color=black:t=fill")
    return out


def glow_graph(fx: dict | None, k: int) -> str:
    """Brillo soñador (necesita dos ramas): [gz{k}] → imagen + su copia muy difuminada en «pantalla» → [go{k}]."""
    g = min(1.0, float((fx or {}).get("glow", 0) or 0))
    return (f"[gz{k}]format=gbrp,split[ga{k}][gb{k}];[gb{k}]gblur=sigma={8 + 22 * g:.1f},"
            f"eq=brightness={0.04 * g:.3f}[gc{k}];[ga{k}][gc{k}]blend=all_mode=screen:all_opacity={0.25 + 0.45 * g:.2f}"
            f"[go{k}]")


def roll_at(fx: dict | None, t: float) -> float:
    """Ángulo (grados) del giro de cámara en el instante t."""
    r = float((fx or {}).get("roll", 0) or 0)
    if r <= 0 or t >= r:
        return 0.0
    return math.degrees(ROLL_AMP * math.sin(t * ROLL_F) * (1 - t / r))


def flicker_at(fx: dict | None, t: float) -> float:
    """Brillo extra (−1…1 × fuerza) del parpadeo en el instante t."""
    f = float((fx or {}).get("flicker", 0) or 0)
    if f <= 0:
        return 0.0
    return 0.16 * min(1.0, f) * (1 if (t * FLICKER_HZ * 2) % 2 < 1 else -1)


def overlay_at(fx: dict | None, t: float, dur: float) -> tuple[str, float]:
    """(color, opacidad 0–1) de la capa encima del clip en el instante t (desde el inicio del clip)."""
    if not fx:
        return "#000000", 0.0
    flash = float(fx.get("flash", 0))
    if flash > 0 and t < flash:
        return "#FFFFFF", 1.0 - t / flash
    fin = float(fx.get("fade_in", 0))
    if fin > 0 and t < fin:
        return "#000000", 1.0 - t / fin
    fout = float(fx.get("fade_out", 0))
    if fout > 0 and t > dur - fout:
        return "#000000", min(1.0, (t - (dur - fout)) / fout)
    return "#000000", 0.0


def shake_at(fx: dict | None, t: float) -> tuple[float, float]:
    """Desplazamiento (dx, dy) en fracción del tamaño, por el temblor."""
    s = float((fx or {}).get("shake", 0))
    if s <= 0 or t >= s:
        return 0.0, 0.0
    a = float(fx.get("shake_amp", SHAKE_AMP)) * (1 - t / s)
    return a * math.sin(t * SHAKE_FX), a * math.cos(t * SHAKE_FY)


def ffmpeg_filters(fx: dict | None, dur: float, w: int, h: int) -> list[str]:
    """Filtros de FFmpeg (para un clip de w×h cuyo tiempo empieza en 0)."""
    if not is_active(fx):
        return []
    out = look_filters(fx, w, h)
    r = float(fx.get("roll", 0) or 0)
    if r > 0:                    # giro de cámara: ampliar, girar y recortar (sin esquinas negras)
        k = 1.22
        sw, sh = 2 * round(w * k / 2), 2 * round(h * k / 2)
        out += [f"scale={sw}:{sh}", f"rotate=a='{ROLL_AMP}*sin(t*{ROLL_F})*max(0\\,1-t/{r:.3f})':c=black",
                f"crop={w}:{h}"]
    s = float(fx.get("shake", 0))
    if s > 0:
        a = float(fx.get("shake_amp", SHAKE_AMP))
        # Ampliar un poco y mover la ventana de recorte: la imagen tiembla sin mostrar bordes
        k = 1 + 2.2 * a
        sw, sh = 2 * round(w * k / 2), 2 * round(h * k / 2)
        decay = f"max(0\\,1-t/{s:.3f})"
        out += [f"scale={sw}:{sh}",
                f"crop={w}:{h}:x='({sw}-{w})/2+{a * w:.2f}*sin(t*{SHAKE_FX})*{decay}'"
                f":y='({sh}-{h})/2+{a * h:.2f}*cos(t*{SHAKE_FY})*{decay}'"]
    flash = float(fx.get("flash", 0))
    fin = float(fx.get("fade_in", 0))
    if flash > 0:
        out.append(f"fade=t=in:st=0:d={flash:.3f}:color=white")
    elif fin > 0:
        out.append(f"fade=t=in:st=0:d={fin:.3f}")
    fout = float(fx.get("fade_out", 0))
    if fout > 0:
        out.append(f"fade=t=out:st={max(0.0, dur - fout):.3f}:d={fout:.3f}")
    return out


def fade_gain(fx, local: float, dur: float) -> float:
    """Volumen (0…1) por los fundidos de entrada/salida del clip en el segundo «local» (para escucharlo en el visor;
    al exportar lo hace «afade»)."""
    fx = fx or {}
    g = 1.0
    fin, fout = float(fx.get("fade_in", 0) or 0), float(fx.get("fade_out", 0) or 0)
    if fin > 0:
        g = min(g, max(0.0, local / fin))
    if fout > 0:
        g = min(g, max(0.0, (dur - local) / fout))
    return g
