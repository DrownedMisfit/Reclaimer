"""
Material común de las pruebas de «Buscar material conforme a frases y palabras clave» (sin internet): imágenes
fabricadas, fuentes locales, codificadores CLIP falsos y un proyecto con narración transcrita.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(cond, msg):
    if not cond:
        print("FALLO:", msg)
        sys.exit(1)
    print("✓", msg)


# ---------------------------------------------------------------- material fabricado
def fabricar(d: str) -> dict:
    """Imágenes locales: fuego (explosión), cielo, pasto, nieve, y una COPIA del fuego con otro nombre (para
    comprobar que no se repite la misma escena)."""
    import cv2
    os.makedirs(d, exist_ok=True)
    rng = np.random.default_rng(1)

    def fuego():
        img = np.zeros((300, 400, 3), np.uint8)
        for _ in range(60):
            c = (int(rng.integers(0, 400)), int(rng.integers(80, 300)))
            cv2.circle(img, c, int(rng.integers(20, 70)), (0, int(rng.integers(60, 200)), 255), -1)
        return cv2.GaussianBlur(img, (31, 31), 0)

    def cielo():
        img = np.zeros((300, 400, 3), np.uint8)
        for y in range(300):
            img[y, :] = (255, 200 - y // 3, 120 - y // 4)
        cv2.circle(img, (300, 70), 40, (255, 255, 255), -1)
        return img

    def pasto():
        img = np.zeros((300, 400, 3), np.uint8)
        img[:] = (40, 160, 50)
        img[:100] = (235, 206, 135)
        return img

    def nieve():
        return np.full((300, 400, 3), 245, np.uint8)

    rutas = {}
    for n, f in (("fuego", fuego), ("cielo", cielo), ("pasto", pasto), ("nieve", nieve)):
        rutas[n] = os.path.join(d, n + ".jpg")
        cv2.imencode(".jpg", f())[1].tofile(rutas[n])
    rutas["fuego_copia"] = os.path.join(d, "fuego_copia.jpg")
    shutil.copyfile(rutas["fuego"], rutas["fuego_copia"])
    return rutas


CARA = (0.55, 0.18, 0.22, 0.40)        # (x, y, ancho, alto) de la «cara» fabricada, en fracciones de la imagen


def fabricar_cara(d: str) -> str:
    """Una imagen 16:9 con una «cara» (óvalo de piel con ojos y boca) donde dice CARA: como la cámara de un youtuber."""
    import cv2
    os.makedirs(d, exist_ok=True)
    W, H = 640, 360
    img = np.full((H, W, 3), (60, 90, 40), np.uint8)
    x, y, w, h = CARA
    cx, cy = int((x + w / 2) * W), int((y + h / 2) * H)
    cv2.ellipse(img, (cx, cy), (int(w * W / 2), int(h * H / 2)), 0, 0, 360, (150, 180, 225), -1)
    for dx in (-0.25, 0.25):
        cv2.circle(img, (int(cx + dx * w * W), int(cy - 0.12 * h * H)), 6, (40, 30, 30), -1)
    cv2.ellipse(img, (cx, int(cy + 0.2 * h * H)), (18, 6), 0, 0, 180, (60, 40, 120), -1)
    ruta = os.path.join(d, "cara.jpg")
    cv2.imencode(".jpg", img)[1].tofile(ruta)
    return ruta


def detector_falso(_frame):
    """Como ai/tracking.detect_faces, pero sabe dónde está la cara fabricada (YuNet no ve un dibujo)."""
    x, y, w, h = CARA
    return [(x, y, w, h, 0.95)]


def detector_vacio(_frame):
    return []


class FuentesLocales:
    """Como Fuentes, pero con las imágenes fabricadas (ni una conexión)."""

    def __init__(self, rutas: dict, destino: str):
        self.rutas, self.destino = rutas, destino
        self.consultas: list[list[str]] = []
        self.bajadas: list[str] = []
        os.makedirs(destino, exist_ok=True)

    def buscar_imagenes(self, qs, cancelled=None):
        self.consultas.append(list(qs))
        out = []
        for n, r in self.rutas.items():
            out.append({"id": f"loc_{n}", "title": f"Imagen {n}", "url": f"https://ejemplo.invalid/{n}.jpg",
                        "thumbnail": r, "license": "cc0", "license_text": "CC0 (dominio público)",
                        "creator": "Autor de prueba", "page": f"https://ejemplo.invalid/{n}", "attribution": "",
                        "source": "Openverse", "query": qs[0] if qs else ""})
        return out

    def bajar_miniatura(self, item, destino):
        shutil.copyfile(item["thumbnail"], destino)
        return destino

    def bajar_imagen(self, item, nombre):
        dest = os.path.join(self.destino, f"{(nombre or 'imagen')} {len(self.bajadas) + 1}.jpg")
        shutil.copyfile(item["thumbnail"], dest)
        self.bajadas.append(dest)
        return dest


class TextoFalso:
    """Codificador de texto falso y determinista: «fuego/explot» → eje 0, «cielo/vuel» → eje 1, resto → eje 2."""

    def encode(self, textos):
        out = []
        for t in textos:
            t = t.lower()
            v = np.array([1.0 if ("explot" in t or "fire" in t or "explos" in t) else 0.0,
                          1.0 if ("cielo" in t or "sky" in t or "vuel" in t or "fly" in t) else 0.0, 0.2, 0.0],
                         np.float32)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


class ImagenFalsa:
    """Imagen → (rojo, azul, verde, brillo) normalizado."""

    def encode(self, imgs):
        out = []
        for im in imgs:
            m = im.reshape(-1, 3).mean(axis=0) / 255.0
            v = np.array([m[0] - 0.5 * m[2], m[2] - 0.3 * m[0], m[1] - 0.5 * (m[0] + m[2]), 0.1], np.float32)
            v = np.maximum(v, 0.0) + 1e-3
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def esperar(app, ctrl):
    t0 = time.time()
    while getattr(ctrl, "analyzing", False) and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.02)


def proyecto(app, out: str, rutas: dict):
    """V1 = video de fondo de 20 s; A1 = narración con su transcripción: dos frases con palabra clave y una sin
    video debajo (a los 24 s, después del fondo)."""
    from editoria.core import media as MT
    from editoria.core.controller import ProjectController
    from editoria.core.model import TRACK_AUDIO, TRACK_VIDEO
    ff = MT.ffmpeg()
    os.makedirs(out, exist_ok=True)
    vid = os.path.join(out, "fondo.mp4")
    subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20",
                    "-pix_fmt", "yuv420p", vid], check=True)
    wav = os.path.join(ROOT, "tests", "assets", "narracion_prueba.wav")

    def frase(t0: float, texto: str) -> list:
        ws = texto.split()
        return [[round(t0 + i * 0.35, 2), round(t0 + i * 0.35 + 0.3, 2), w, 1.0] for i, w in enumerate(ws)]
    words = (frase(1.0, "En GTA 5 hay carros que explotan con unos cuantos disparos.")
             + frase(11.0, "En Elden Ring los dragones vuelan sobre el castillo.")
             + frase(24.0, "Y en GTA 5 los carros explotan otra vez.")
             + frase(29.0, "Gracias por ver."))
    ctrl = ProjectController()
    ctrl.project.width, ctrl.project.height = 640, 360
    bid, nid = ctrl.import_now([vid, wav])
    esperar(app, ctrl)
    p = ctrl.project
    p.transcripts[nid] = {"words": words}
    v1 = next(t for t in p.tracks if t.kind == TRACK_VIDEO and not t.locked)
    vids = [t for t in p.tracks if t.kind == TRACK_VIDEO]
    v1 = vids[-1]
    a1 = next(t for t in p.tracks if t.kind == TRACK_AUDIO)
    ctrl.add_media([bid], v1.id, 0.0)
    ctrl.add_media([nid], a1.id, 0.0)
    return ctrl, v1, words


