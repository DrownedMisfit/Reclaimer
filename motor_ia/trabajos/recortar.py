"""
✂ Recortar al sujeto con SAM 2.1 (Meta, licencia Apache-2.0) en la tarjeta gráfica (ROCm) o, si no hay, en el
procesador. No mira solo el contorno: el modelo convierte cada fotograma en un «mapa» denso de lo que hay dentro
(texturas, piezas, detalles) y una MEMORIA de los fotogramas anteriores, así sigue al personaje, la roca o el
vehículo aunque gire, se tape un momento o cambie la luz. Después, los bordes finos (pelo, telas) se afinan con
un filtro guiado por la propia imagen.

Uso:  python recortar.py trabajo.json
  {"modo": "imagen" | "video", "ffmpeg": ruta, "video": ruta, "a": s, "b": s, "t0": s, "fps": n,
   "puntos": [[x, y, 1|0], …] (0–1), "caja": [x0, y0, x1, y1] (0–1) | null, "salida": ruta, "modelo": ruta,
   "config": "configs/sam2.1/sam2.1_hiera_l.yaml", "ancho": 1280, "bordes": true}
Escribe «PROGRESO f texto» por la salida; al final «LISTO ruta».
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np
import torch

BLOCK = 200          # fotogramas por bloque (la memoria de SAM 2 crece con el bloque)


def say(f, text):
    print(f"PROGRESO {max(0.0, min(1.0, f)):.4f} {text}", flush=True)


def device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def fast():
    """Media precisión en la tarjeta: ~4 veces más rápido con el mismo resultado. bf16 donde la tarjeta lo tiene;
    en las que no (p. ej. NVIDIA GTX 10/16), float16."""
    if device() == "cuda":
        dt = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        return torch.autocast("cuda", dtype=dt)
    import contextlib
    return contextlib.nullcontext()


def refine(prob: np.ndarray, frame_bgr: np.ndarray, on: bool) -> np.ndarray:
    """Probabilidad 0–1 → transparencia 0–255. Con «bordes finos», guiada por la imagen (pelo, telas)."""
    prob = prob.astype(np.float32)
    if on and hasattr(cv2, "ximgproc"):
        guide = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        r = max(2, int(min(prob.shape) / 90))
        prob = cv2.ximgproc.guidedFilter(guide, prob, r, 1e-4)
    # agujeros pequeños dentro del sujeto: fuera
    hard = (prob > 0.5).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(1 - hard, 8)
    area = prob.size * 0.0015
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < area and x > 0 and y > 0 and x + w < prob.shape[1] and y + h < prob.shape[0]:
            prob[lab == i] = 1.0
    return (np.clip(prob, 0, 1) * 255).astype(np.uint8)


def extract(job, folder) -> tuple[int, int, int]:
    a, b = float(job["a"]), float(job["b"])
    vf = f"fps={job['fps']},scale='min({job.get('ancho', 1280)},iw)':-2"
    subprocess.run([job["ffmpeg"], "-nostdin", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                    "-i", job["video"], "-vf", vf, "-q:v", "2", "-start_number", "0",
                    os.path.join(folder, "%05d.jpg")], check=True)
    names = sorted(f for f in os.listdir(folder) if f.endswith(".jpg"))
    h, w = cv2.imread(os.path.join(folder, names[0])).shape[:2]
    return len(names), w, h


def prompts_px(job, w, h):
    pts = np.array([[p[0] * w, p[1] * h] for p in job.get("puntos") or []], np.float32)
    labels = np.array([int(p[2]) for p in job.get("puntos") or []], np.int32)
    box = job.get("caja")
    box = np.array([box[0] * w, box[1] * h, box[2] * w, box[3] * h], np.float32) if box else None
    return (pts if len(pts) else None), (labels if len(labels) else None), box


def run_image(job):
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    tmp = tempfile.mkdtemp(prefix="recorte_", dir=os.path.dirname(job["salida"]))
    try:
        t = float(job["t0"])
        img_path = os.path.join(tmp, "f.jpg")
        subprocess.run([job["ffmpeg"], "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", job["video"],
                        "-frames:v", "1", "-vf", f"scale='min({job.get('ancho', 1280)},iw)':-2", "-q:v", "2",
                        img_path], check=True)
        frame = cv2.imread(img_path)
        h, w = frame.shape[:2]
        say(0.3, "Cargando SAM 2.1…")
        model = build_sam2(job["config"], job["modelo"], device=device())
        pred = SAM2ImagePredictor(model)
        pts, labels, box = prompts_px(job, w, h)
        with torch.inference_mode(), fast():
            pred.set_image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            masks, scores, logits = pred.predict(point_coords=pts, point_labels=labels, box=box,
                                                 multimask_output=pts is not None and box is None and len(pts) == 1,
                                                 return_logits=True)
        k = int(np.argmax(scores))
        prob = 1 / (1 + np.exp(-np.asarray(masks[k], np.float32)))
        cv2.imwrite(job["salida"], refine(prob, frame, job.get("bordes", True)))
        print(f"LISTO {job['salida']}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_video(job):
    from sam2.build_sam import build_sam2_video_predictor
    tmp = tempfile.mkdtemp(prefix="recorte_", dir=os.path.dirname(job["salida"]))
    try:
        say(0.01, "Leyendo los fotogramas…")
        allf = os.path.join(tmp, "todos")
        os.makedirs(allf)
        n, w, h = extract(job, allf)
        k0 = min(n - 1, max(0, int(round((float(job["t0"]) - float(job["a"])) * float(job["fps"])))))
        masks_dir = os.path.join(tmp, "mascaras")
        os.makedirs(masks_dir)
        say(0.04, "Cargando SAM 2.1 en la tarjeta gráfica…" if device() == "cuda" else "Cargando SAM 2.1…")
        pred = build_sam2_video_predictor(job["config"], job["modelo"], device=device())
        pts, labels, box = prompts_px(job, w, h)
        done: set[int] = set()

        def block(lo, hi, seed, reverse):
            """Fotogramas [lo, hi] (incluidos); seed = (índice local, puntos/caja) o máscara del borde."""
            d = os.path.join(tmp, f"b_{lo}_{hi}")
            os.makedirs(d)
            for i in range(lo, hi + 1):
                src = os.path.join(allf, f"{i:05d}.jpg")
                dst = os.path.join(d, f"{i - lo:05d}.jpg")
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy(src, dst)
            # gráfica de poca memoria («ahorro»): lo que se recuerda de cada fotograma va a la RAM
            state = pred.init_state(video_path=d, offload_video_to_cpu=True,
                                    offload_state_to_cpu=bool(job.get("ahorro")))
            local0 = seed[0] - lo
            if isinstance(seed[1], np.ndarray):
                pred.add_new_mask(state, frame_idx=local0, obj_id=1, mask=seed[1] > 127)
            else:
                p_, l_, b_ = seed[1]
                pred.add_new_points_or_box(state, frame_idx=local0, obj_id=1, points=p_, labels=l_, box=b_)
            last = None
            for idx, _ids, logits in pred.propagate_in_video(state, start_frame_idx=local0, reverse=reverse):
                gi = lo + idx
                frame = cv2.imread(os.path.join(allf, f"{gi:05d}.jpg"))
                prob = torch.sigmoid(logits[0, 0]).float().cpu().numpy()
                if prob.shape != frame.shape[:2]:
                    prob = cv2.resize(prob, (frame.shape[1], frame.shape[0]))
                alpha = refine(prob, frame, job.get("bordes", True))
                cv2.imwrite(os.path.join(masks_dir, f"{gi:05d}.png"), alpha)
                last = alpha
                done.add(gi)
                say(0.06 + 0.88 * len(done) / max(1, n), f"✂ Siguiendo al sujeto · fotograma {len(done)} de {n}")
            pred.reset_state(state)
            del state
            shutil.rmtree(d, ignore_errors=True)
            if device() == "cuda":
                torch.cuda.empty_cache()
            return last

        with torch.inference_mode(), fast():
            # hacia delante desde el fotograma marcado, por bloques encadenados
            lo, seed = k0, (k0, (pts, labels, box))
            while lo < n:
                hi = min(n - 1, lo + BLOCK)
                last = block(lo, hi, seed, False)
                if hi >= n - 1 or last is None:
                    break
                lo, seed = hi, (hi, last)
            # y hacia atrás
            if k0 > 0:
                hi, seed = k0, (k0, (pts, labels, box))
                while hi > 0:
                    lo = max(0, hi - BLOCK)
                    last = block(lo, hi, seed, True)
                    if lo <= 0 or last is None:
                        break
                    hi, seed = lo, (lo, last)
        say(0.95, "Guardando la máscara…")
        subprocess.run([job["ffmpeg"], "-nostdin", "-v", "error", "-y", "-framerate", str(job["fps"]),
                        "-start_number", "0", "-i", os.path.join(masks_dir, "%05d.png"), "-pix_fmt", "gray",
                        "-c:v", "ffv1", job["salida"]], check=True)
        print(f"LISTO {job['salida']}", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)
    if job["modo"] == "imagen":
        run_image(job)
    else:
        run_video(job)


if __name__ == "__main__":
    main()
