"""
🗣 VOZ IA (texto → voz): si no quieres hablar, pegas tu guion entero y Reclaimer lo lee con una voz sintética
(en tu PC, sin internet; más rápido que tiempo real en el procesador). Dos motores:
  · Kokoro-82M (Apache 2.0; modelos/kokoro): Alex, Santa, Dora y sus mezclas de estilo;
  · Piper (piper-tts, GPL v3; modelos/piper): voces de rhasspy/piper-voices con licencia que permite vender y
    redistribuir (davefx CC0, sharvard CC BY 3.0, ald Unlicense).
CATALOGO: cada voz = motor + voz (o mezcla de estilos) + ritmo + tono (semitonos, sin cambiar la duración) +
ecualización («voz de documental»: paso alto, cuerpo, compresión suave) + pausas. Las de «🎙 Narración» están
pensadas para contar historia (graves, calmadas).

  available(voz) -> (bool, motivo)       ¿están el modelo de esa voz y las librerías?
  descargar(progress, cancelled, voz=…)  ⬇ baja el modelo que le falta a esa voz (.part, tamaño y SHA-256)
  cargar(progress) / cargar_piper(modelo)   carga cada modelo UNA vez (seguro entre hilos)
  frases(texto) -> [{"texto", "fin_parrafo"}]       troceo por frases y párrafos (sin partir «Sr.», «etc.»…)
  contar(texto, …, voz) -> (palabras, segundos estimados)  para el contador del panel
  leer_diccionario() / guardar_diccionario(texto) / aplicar_diccionario(texto)   «palabra = como suena»
  sintetizar(texto, voz, velocidad, pausa, pausa_parrafo, acento, robot, destino, progress, cancelled,
             solo_primera=False) -> {"ruta", "duracion", "frases": [...], "transcripcion": {...}}
  crear_muestras(carpeta) -> [rutas]     la misma narración con cada voz + LEEME.txt (para comparar)

La transcripción sale YA hecha (sin Whisper), en el formato de p.transcripts: el texto exacto que pegaste y, para cada
frase, su tiempo real en el WAV; dentro de cada frase las palabras se reparten por sílabas, respetando las pausas de
las comas (silencios que se miden en el audio) y ajustando cada borde al punto más silencioso cercano.
El tono y la ecualización se aplican al final a todo el audio (FFmpeg: rubberband si lo trae, si no asetrate+atempo);
si eso cambia un pelín la duración, todos los tiempos se reescalan.
El WAV (mono, 16 bits, 24 kHz) se escribe al final de golpe (archivo temporal + renombrar): cancelar a mitad no deja
nada en disco.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .base import CancelFn, Cancelled, ProgressFn, check_cancel, report

SR = 24000
VOCES = {"em_alex": "Alex (hombre)", "em_santa": "Santa (hombre, grave)", "ef_dora": "Dora (mujer)"}  # (Kokoro)
VOZ_DEFECTO = "narrador_documental"
ACENTOS = {"es": "España", "es-419": "Latinoamérica"}
MAX_FRASE = 380                 # una frase más larga se parte en su última coma (el modelo pierde la entonación)
PICO = 0.89                     # techo de pico: −1 dBFS
LUFS_VOZ = -18.0                # sonoridad de la narración (todas las voces igual de fuertes; al exportar, −14 LUFS)
ETIQUETA = "🗣 Voz IA"          # etiqueta (tags) de los audios creados aquí: así se reconoce la narración anterior

_kokoro = None
_lock = threading.Lock()


# ------------------------------------------------------------------ modelo
# La release oficial de kokoro-onnx (thewh1teagle): tamaño exacto y SHA-256 de cada archivo (comprobados el 16/11/2026)
URL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
ARCHIVOS = {"kokoro-v1.0.onnx": (325_532_387, "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
            "voices-v1.0.bin": (28_214_398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d")}
TAM_DESCARGA = "≈350 MB"


def _carpetas() -> list[Path]:
    """Dónde puede estar el modelo: junto al programa (modelos/kokoro; en la versión «todo en uno», dentro de app)
    o, si ahí no se pudo escribir al descargarlo, en datos/modelos/kokoro. RECLAIMER_KOKORO lo cambia."""
    if os.environ.get("RECLAIMER_KOKORO"):
        return [Path(os.environ["RECLAIMER_KOKORO"])]
    from ..core.paths import PROGRAM_DIR, app_data_dir
    return [PROGRAM_DIR / "modelos" / "kokoro", app_data_dir() / "modelos" / "kokoro"]


def model_dir() -> Path:
    cands = _carpetas()
    for d in cands:
        if all((d / n).is_file() for n in ARCHIVOS):
            return d
    return cands[0]


def _archivos() -> tuple[Path, Path]:
    d = model_dir()
    return d / "kokoro-v1.0.onnx", d / "voices-v1.0.bin"


def falta_kokoro() -> bool:
    return not all(p.is_file() for p in _archivos())


# ------------------------------------------------------------------ Piper (piper-tts, GPL v3)
# rhasspy/piper-voices en Hugging Face, fijado a una revisión: tamaño exacto y SHA-256 de cada archivo (comprobados el
# 16/11/2026; el MD5 coincide con el de su voices.json). Solo voces cuya licencia (su MODEL_CARD y la de la voz de la
# que se afinaron) permite uso comercial y redistribución. Descartadas: es_AR-daniela-high (afinada de «lessac»,
# licencia de investigación), es_ES-mls_* (afinadas de «ryan», no comercial), es_MX-claude-high (origen de los datos
# sin verificar) y es_ES-carlfm-x_low (dominio público, pero de calidad muy baja).
PIPER_REV = "e9ab671f2a0e50a701b34361136ba3e6a3a9eb0c"
PIPER_URL = f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REV}/"
PIPER_MODELOS = {
    "es_ES-davefx-medium": {
        "remoto": "es/es_ES/davefx/medium/",
        "archivos": {"es_ES-davefx-medium.onnx": ("es_ES-davefx-medium.onnx", 63_221_984,
                                                  "d2c9224e122321aac3c33343957fff4d0f465226cb74c66b0f520ca3f8c0dd07"),
                     "es_ES-davefx-medium.onnx.json": ("es_ES-davefx-medium.onnx.json", 5_458,
                                                       "531c4051502e1acbc10b42437f11679bfce9e3919e1796e51fabd73e01e7fd2e"),
                     "es_ES-davefx-medium.MODEL_CARD.txt": ("MODEL_CARD", 418,
                                                            "2d55d0d84100cde9d9ed88866c2625c89d333a45507d88aa8bae40f6de94c134")},
        "licencia": "CC0 (dominio público)",
        "creditos": "Voz «davefx» (español de España, hombre) de rhasspy/piper-voices. Datos: OHF-Voice/voice-datasets, "
                    "CC0. Afinada desde la voz «rdh» (CC0). Sin obligación de atribución.",
    },
    "es_ES-sharvard-medium": {
        "remoto": "es/es_ES/sharvard/medium/",
        "archivos": {"es_ES-sharvard-medium.onnx": ("es_ES-sharvard-medium.onnx", 76_753_841,
                                                    "234dc4cf0fdb53ccb76b9b2c4d7ef1330364762674c1b78c1b62d8608c528a54"),
                     "es_ES-sharvard-medium.onnx.json": ("es_ES-sharvard-medium.onnx.json", 5_486,
                                                         "1910940c6b480e0f7cbce5e0da45c8cbe2557ccbfd86a5d22cda141a3b65f521"),
                     "es_ES-sharvard-medium.MODEL_CARD.txt": ("MODEL_CARD", 882,
                                                              "05d80690fb21967f301e69a86c61b3c2320002f941a0d7f9423c805ae653b59f")},
        "licencia": "CC BY 3.0 (pide atribución)",
        "creditos": "Voz «sharvard» (español de España; hablante 0 = hombre, 1 = mujer) de rhasspy/piper-voices. "
                    "Datos: Sharvard Corpus (Aubanel, García Lecumberri, Cooke y otros; Universidad de Edimburgo, "
                    "https://datashare.ed.ac.uk/handle/10283/574), licencia CC BY 3.0 "
                    "(http://creativecommons.org/licenses/by/3.0/). Afinada desde la voz «hifi_tts_92» (Hi-Fi TTS, "
                    "CC BY 4.0).",
        # lo que se pone en los créditos del video (credits.py, apartado «🗣 Voz:»)
        "atribucion": "Voz sintética: Piper, voz sharvard (Sharvard Corpus, CC BY 3.0)",
        "url_atribucion": "https://datashare.ed.ac.uk/handle/10283/574",
    },
    "es_MX-ald-medium": {
        "remoto": "es/es_MX/ald/medium/",
        "archivos": {"es_MX-ald-medium.onnx": ("es_MX-ald-medium.onnx", 63_201_294,
                                               "019b3803293c93e34a206dd2e53a3889209a514e786fd7144f7b70196c579b63"),
                     "es_MX-ald-medium.onnx.json": ("es_MX-ald-medium.onnx.json", 4_878,
                                                    "5a71498158e04afc8099bfd019c7e87c68eb9d042505a2b1a87e5c1ac2b1a61d"),
                     "es_MX-ald-medium.MODEL_CARD.txt": ("MODEL_CARD", 320,
                                                         "1f0694ceb3f1e78c1e2ee0e2d5da40f19f965bc638e1b4fb4fca9bdca420d713")},
        "licencia": "Unlicense (dominio público)",
        "creditos": "Voz «ald» (español de México, hombre) de rhasspy/piper-voices. Datos: "
                    "rmcpantoja/Ald_Mexican_Spanish_speech_dataset, Unlicense. Afinada desde «davefx» (CC0).",
    },
}


def _carpetas_piper() -> list[Path]:
    if os.environ.get("RECLAIMER_PIPER"):
        return [Path(os.environ["RECLAIMER_PIPER"])]
    from ..core.paths import PROGRAM_DIR, app_data_dir
    return [PROGRAM_DIR / "modelos" / "piper", app_data_dir() / "modelos" / "piper"]


def piper_dir(modelo: str) -> Path:
    cands = _carpetas_piper()
    nombres = [n for n in PIPER_MODELOS[modelo]["archivos"] if not n.endswith(".txt")]
    for d in cands:
        if all((d / n).is_file() for n in nombres):
            return d
    return cands[0]


def falta_piper(modelo: str) -> bool:
    d = piper_dir(modelo)
    return not all((d / n).is_file() for n in PIPER_MODELOS[modelo]["archivos"] if not n.endswith(".txt"))


def tam_piper(modelo: str) -> int:
    return sum(v[1] for v in PIPER_MODELOS[modelo]["archivos"].values())


# ------------------------------------------------------------------ catálogo de voces
GRUPOS = ("🎙 Narración", "Kokoro", "Piper")


@dataclass(frozen=True)
class Voz:
    clave: str
    nombre: str                       # lo que se ve en el desplegable
    grupo: str                        # uno de GRUPOS
    motor: str                        # "kokoro" | "piper"
    voz: str | tuple = ""             # kokoro: "em_alex" o ((estilo, peso), …) = mezcla; piper: el modelo
    hablante: int | None = None       # piper con varios hablantes
    velocidad: float = 1.0            # se multiplica por la del panel
    tono: float = 0.0                 # semitonos (negativo = más grave), sin cambiar la duración
    eq: str = ""                      # "" | "documental" | "firme" | "suave"
    pausas: float = 1.0               # se multiplica por las pausas del panel
    descripcion: str = ""
    licencia: str = ""
    archivo: str = ""                 # nombre de su muestra en «Muestras de voces»

    @property
    def modelo_kokoro(self) -> bool:
        return self.motor == "kokoro"


_LIC_KOKORO = "Kokoro-82M, Apache 2.0 (uso comercial libre)"


def _lic_piper(modelo: str) -> str:
    return f"Piper «{modelo}», {PIPER_MODELOS[modelo]['licencia']}"


def _pide_atribucion(modelo: str) -> bool:
    return "atribución" in PIPER_MODELOS[modelo]["licencia"]


def _creditos_tooltip(modelo: str) -> str:
    return ("\n⚠ Esta voz pide atribución en la descripción del video (Reclaimer la añade a los créditos al "
            "exportar).\n" + PIPER_MODELOS[modelo]["creditos"]) if _pide_atribucion(modelo) else ""


CATALOGO: dict[str, Voz] = {v.clave: v for v in (
    # 🎙 Narración: para contar historia (graves, calmadas, pausadas, con la ecualización de documental)
    Voz("narrador_documental", "🎙 Narrador de documental", "🎙 Narración", "kokoro",
        (("em_santa", 0.6), ("em_alex", 0.4)), velocidad=0.82, tono=-2.0, eq="documental", pausas=1.4,
        descripcion="Grave y pausado, con cuerpo y compresión suave de documental. Para contar historia y la vida de "
                    "un personaje histórico.\nMezcla de los estilos de Santa y Alex (Kokoro), dos semitonos más "
                    "grave y más despacio.",
        licencia=_LIC_KOKORO, archivo="Narrador de documental (grave)"),
    Voz("narrador_calmado", "🎙 Narrador calmado", "🎙 Narración", "piper", "es_ES-davefx-medium",
        velocidad=0.88, tono=-1.0, eq="suave", pausas=1.35,
        descripcion="Tranquilo y cercano, sin prisa. Para relatos largos.\nVoz «davefx» de Piper (España), un "
                    "semitono más grave.",
        licencia=_lic_piper("es_ES-davefx-medium"), archivo="Narrador calmado"),
    Voz("narrador_solemne", "🎙 Narrador solemne", "🎙 Narración", "piper", "es_ES-sharvard-medium", hablante=0,
        velocidad=0.86, tono=-1.5, eq="documental", pausas=1.45,
        descripcion="Serio y ceremonioso, con pausas largas. Para los momentos duros de la historia.\nVoz "
                    "«sharvard» (hombre) de Piper (España)." + _creditos_tooltip("es_ES-sharvard-medium"),
        licencia=_lic_piper("es_ES-sharvard-medium"), archivo="Narrador solemne"),
    Voz("voz_firme", "🎙 Voz firme", "🎙 Narración", "kokoro", "em_alex",
        velocidad=0.92, tono=-1.5, eq="firme", pausas=1.2,
        descripcion="Contundente y segura, con más presencia. Para afirmaciones fuertes y datos.\nAlex (Kokoro) más "
                    "grave, más despacio y más comprimida.",
        licencia=_LIC_KOKORO, archivo="Voz firme"),
    Voz("cronista_grave", "🎙 Cronista grave", "🎙 Narración", "kokoro", "em_santa",
        velocidad=0.86, tono=-2.5, eq="documental", pausas=1.4,
        descripcion="La más grave: voz profunda de cronista. Para introducciones y cierres.\nSanta (Kokoro) dos "
                    "semitonos y medio más grave.",
        licencia=_LIC_KOKORO, archivo="Cronista grave"),
    Voz("narrador_latino", "🎙 Narrador latino", "🎙 Narración", "piper", "es_MX-ald-medium",
        velocidad=0.88, tono=-1.5, eq="documental", pausas=1.35,
        descripcion="Calmado, con acento de México (seseo). Para un público latinoamericano.\nVoz «ald» de Piper, "
                    "semitono y medio más grave.",
        licencia=_lic_piper("es_MX-ald-medium"), archivo="Narrador latino (México)"),
    Voz("narradora_serena", "🎙 Narradora serena", "🎙 Narración", "kokoro", "ef_dora",
        velocidad=0.88, tono=-1.0, eq="suave", pausas=1.35,
        descripcion="Voz de mujer, serena y pausada. Para relatos y biografías.\nDora (Kokoro), un semitono más "
                    "grave y más despacio.",
        licencia=_LIC_KOKORO, archivo="Narradora serena (mujer)"),
    Voz("narradora_clara", "🎙 Narradora clara", "🎙 Narración", "piper", "es_ES-sharvard-medium", hablante=1,
        velocidad=0.9, tono=-0.5, eq="suave", pausas=1.3,
        descripcion="Voz de mujer, clara y tranquila. Para explicar contexto y fechas.\nVoz «sharvard» (mujer) de "
                    "Piper (España)." + _creditos_tooltip("es_ES-sharvard-medium"),
        licencia=_lic_piper("es_ES-sharvard-medium"), archivo="Narradora clara (mujer)"),
    # Kokoro tal cual (las de antes)
    Voz("em_alex", "Alex (hombre)", "Kokoro", "kokoro", "em_alex",
        descripcion="La voz de siempre: hombre, natural y ágil. Va bien para Shorts.", licencia=_LIC_KOKORO,
        archivo="Alex (Kokoro)"),
    Voz("em_santa", "Santa (hombre, grave)", "Kokoro", "kokoro", "em_santa",
        descripcion="Hombre, algo más grave que Alex.", licencia=_LIC_KOKORO, archivo="Santa (Kokoro)"),
    Voz("ef_dora", "Dora (mujer)", "Kokoro", "kokoro", "ef_dora",
        descripcion="Mujer, natural.", licencia=_LIC_KOKORO, archivo="Dora (Kokoro)"),
    # Piper tal cual
    Voz("piper_davefx", "David (hombre, España)", "Piper", "piper", "es_ES-davefx-medium",
        descripcion="Hombre, acento de España, natural.", licencia=_lic_piper("es_ES-davefx-medium"),
        archivo="David (Piper)"),
    Voz("piper_sharvard_m", "Sharvard (hombre, España)", "Piper", "piper", "es_ES-sharvard-medium", hablante=0,
        descripcion="Hombre, acento de España, dicción cuidada." + _creditos_tooltip("es_ES-sharvard-medium"),
        licencia=_lic_piper("es_ES-sharvard-medium"), archivo="Sharvard hombre (Piper)"),
    Voz("piper_sharvard_f", "Sharvard (mujer, España)", "Piper", "piper", "es_ES-sharvard-medium", hablante=1,
        descripcion="Mujer, acento de España, dicción cuidada." + _creditos_tooltip("es_ES-sharvard-medium"),
        licencia=_lic_piper("es_ES-sharvard-medium"), archivo="Sharvard mujer (Piper)"),
    Voz("piper_ald", "Ald (hombre, México)", "Piper", "piper", "es_MX-ald-medium",
        descripcion="Hombre, acento de México.", licencia=_lic_piper("es_MX-ald-medium"), archivo="Ald (Piper)"),
)}


def voz_info(clave: str | None) -> Voz:
    """La voz del catálogo (una clave desconocida → la de por defecto)."""
    return CATALOGO.get(clave or "", CATALOGO[VOZ_DEFECTO])


def tooltip_voz(clave: str) -> str:
    v = voz_info(clave)
    extra = []
    if v.velocidad != 1.0:
        extra.append(f"ritmo ×{v.velocidad:.2f}".replace(".", ","))
    if v.tono:
        extra.append(f"tono {v.tono:+.1f} semitonos".replace(".", ","))
    if v.eq:
        extra.append({"documental": "ecualización de documental", "firme": "ecualización firme",
                      "suave": "ecualización suave"}[v.eq])
    if v.pausas != 1.0:
        extra.append(f"pausas ×{v.pausas:.2f}".replace(".", ","))
    return (v.descripcion + ("\n(" + ", ".join(extra) + ")" if extra else "") + f"\nLicencia: {v.licencia}."
            + ("\nAcento propio de la voz (el ajuste «Acento» no le afecta)." if v.motor == "piper" else ""))


def falta_modelo(voz: str | None = None) -> bool:
    v = voz_info(voz)
    return falta_kokoro() if v.motor == "kokoro" else falta_piper(str(v.voz))


def tam_descarga(voz: str | None = None) -> str:
    v = voz_info(voz)
    return TAM_DESCARGA if v.motor == "kokoro" else f"{tam_piper(str(v.voz)) / 1e6:.0f} MB"


def falta_componente(voz: str | None = None) -> str:
    import importlib.util
    mods = ("kokoro_onnx", "onnxruntime", "espeakng_loader", "phonemizer") if voz_info(voz).motor == "kokoro" \
        else ("piper", "onnxruntime")
    for mod in mods:
        if importlib.util.find_spec(mod) is None:
            return f"Falta el componente «{mod}» de la voz IA. Vuelve a abrir INSTALAR.bat (lo instala solo)."
    return ""


def available(voz: str | None = None) -> tuple[bool, str]:
    v = voz_info(voz)
    if falta_modelo(v.clave):
        if v.motor == "kokoro":
            return False, (f"Falta esta voz (modelo Kokoro, {TAM_DESCARGA}). Pulsa «⬇ Descargar esta voz» (una sola "
                           f"vez) o pon «kokoro-v1.0.onnx» y «voices-v1.0.bin» en la carpeta {_carpetas()[0]}")
        return False, (f"Falta esta voz (modelo Piper «{v.voz}», {tam_descarga(v.clave)}). Pulsa «⬇ Descargar esta "
                       f"voz» (una sola vez) o pon sus archivos .onnx y .onnx.json en {_carpetas_piper()[0]}")
    comp = falta_componente(v.clave)
    return (False, comp) if comp else (True, "")


def _destino_escribible(cands: list[Path]) -> Path:
    for d in cands:
        try:
            d.mkdir(parents=True, exist_ok=True)
            prueba = d / f".escritura_{os.getpid()}"
            prueba.write_text("ok", encoding="utf-8")
            prueba.unlink()
            return d
        except OSError:
            continue
    raise RuntimeError(f"No se puede escribir en {cands[0]} (ni en la carpeta de datos).")


def destino_descarga() -> Path:
    """La primera carpeta de _carpetas() en la que se puede escribir."""
    return _destino_escribible(_carpetas())


def _bajar(archivos: dict[str, tuple[str, int, str]], d: Path, progress: ProgressFn, cancelled: CancelFn):
    """Cada archivo (nombre local → (url, tamaño, sha256)) a «.part», comprobando tamaño y SHA-256, y al final se
    renombra. Cancelar o un fallo no dejan nada a medias."""
    import hashlib
    import urllib.error
    import urllib.request
    faltan = {n: v for n, v in archivos.items() if not ((d / n).is_file() and (d / n).stat().st_size == v[1])}
    total = sum(v[1] for v in faltan.values()) or 1
    hecho = 0
    for nombre, (url, tam, sha) in faltan.items():
        final = d / nombre
        part = d / (nombre + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Reclaimer"})
            with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                h = hashlib.sha256()
                n = 0
                while True:
                    check_cancel(cancelled)
                    trozo = r.read(1 << 20)
                    if not trozo:
                        break
                    f.write(trozo)
                    h.update(trozo)
                    n += len(trozo)
                    report(progress, min(0.999, (hecho + n) / total),
                           f"⬇ Descargando la voz… {(hecho + n) / 1e6:.0f} de {total / 1e6:.0f} MB")
            if n != tam:
                raise RuntimeError(f"La descarga de «{nombre}» quedó incompleta ({n} de {tam} bytes). Prueba otra vez.")
            if sha and h.hexdigest() != sha:
                raise RuntimeError(f"«{nombre}» no es el archivo esperado (su huella SHA-256 no coincide).")
            os.replace(part, final)
            hecho += tam
        except BaseException as exc:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
                raise RuntimeError(f"No se pudo descargar la voz (¿sin internet?): {getattr(exc, 'reason', exc)}") \
                    from exc
            raise
    report(progress, 1.0, "✓ Voz descargada.")


def descargar(progress: ProgressFn = None, cancelled: CancelFn = None, url_base: str | None = None,
              voz: str | None = None) -> Path:
    """⬇ Baja el modelo que le falta a esa voz: Kokoro de la release oficial de kokoro-onnx (o RECLAIMER_KOKORO_URL);
    Piper de rhasspy/piper-voices en Hugging Face, revisión fijada (o RECLAIMER_PIPER_URL)."""
    v = voz_info(voz)
    if v.motor == "piper":
        modelo = PIPER_MODELOS[str(v.voz)]
        base = url_base or os.environ.get("RECLAIMER_PIPER_URL") or PIPER_URL
        if not base.endswith("/"):
            base += "/"
        d = _destino_escribible(_carpetas_piper())
        _bajar({n: (base + modelo["remoto"] + remoto, tam, sha) for n, (remoto, tam, sha) in modelo["archivos"].items()},
               d, progress, cancelled)
        return d
    base = url_base or os.environ.get("RECLAIMER_KOKORO_URL") or URL_BASE
    if not base.endswith("/"):
        base += "/"
    d = destino_descarga()
    _bajar({n: (base + n, tam, sha) for n, (tam, sha) in ARCHIVOS.items()}, d, progress, cancelled)
    return d


def cargado() -> bool:
    return _kokoro is not None


def cargar(progress: ProgressFn = None):
    """El modelo Kokoro, cargado una sola vez (~1 s). Seguro entre hilos: dos trabajos a la vez no lo cargan dos
    veces."""
    global _kokoro
    with _lock:
        if _kokoro is None:
            if falta_kokoro():
                raise RuntimeError(available("em_alex")[1])
            comp = falta_componente("em_alex")
            if comp:
                raise RuntimeError(comp)
            report(progress, 0.0, "Cargando la voz (solo la primera vez)…")
            from kokoro_onnx import Kokoro
            onnx, voces = _archivos()
            _kokoro = Kokoro(str(onnx), str(voces))
        return _kokoro


_piper: dict[str, object] = {}


def cargar_piper(modelo: str, progress: ProgressFn = None):
    """Una voz de Piper, cargada una sola vez (en el procesador). Solo se queda en memoria la última usada (cada
    una ocupa ~100–200 MB): al cargar otra, la anterior se suelta."""
    with _lock:
        pv = _piper.get(modelo)
        if pv is None:
            _piper.clear()
            if falta_piper(modelo):
                raise RuntimeError(f"Falta la voz Piper «{modelo}». Pulsa «⬇ Descargar esta voz».")
            comp = falta_componente("piper_davefx")
            if comp:
                raise RuntimeError(comp)
            report(progress, 0.0, "Cargando la voz (solo la primera vez)…")
            from piper import PiperVoice
            d = piper_dir(modelo)
            pv = PiperVoice.load(str(d / f"{modelo}.onnx"), config_path=str(d / f"{modelo}.onnx.json"))
            _piper[modelo] = pv
        return pv


def _estilo_kokoro(k, voz) -> object:
    """El estilo de Kokoro: un nombre («em_alex») o la mezcla ponderada de varios (promedio de sus vectores)."""
    if isinstance(voz, str):
        return voz
    total = sum(p for _n, p in voz) or 1.0
    return sum(np.asarray(k.get_voice_style(n), np.float32) * (p / total) for n, p in voz).astype(np.float32)


# ------------------------------------------------------------------ diccionario de pronunciación
DICCIONARIO_INICIAL = (
    "# Cómo se debe pronunciar una palabra:  palabra = como suena\n"
    "# Una por línea; no distingue mayúsculas; vale también para varias palabras seguidas.\n"
    "# Solo cambia cómo se LEE: los subtítulos y el texto siguen con lo que escribiste.\n"
    "YouTube = yutub\n"
    "TikTok = tiktok\n"
    "online = onlain\n"
    "streamer = estrímer\n"
    "gamer = guéimer\n"
)


def ruta_diccionario() -> Path:
    from ..core.paths import app_data_dir
    d = app_data_dir() / "voz_ia"
    d.mkdir(parents=True, exist_ok=True)
    return d / "pronunciacion.txt"


def texto_diccionario() -> str:
    p = ruta_diccionario()
    if not p.is_file():
        p.write_text(DICCIONARIO_INICIAL, encoding="utf-8")
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return DICCIONARIO_INICIAL


def guardar_diccionario(texto: str):
    p = ruta_diccionario()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(texto if texto.endswith("\n") else texto + "\n", encoding="utf-8")
    os.replace(tmp, p)


def leer_diccionario(texto: str | None = None) -> list[tuple[str, str]]:
    reglas = []
    for linea in (texto_diccionario() if texto is None else texto).splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            a, b = (x.strip() for x in linea.split("=", 1))
            if a:
                reglas.append((a, b))
    return sorted(reglas, key=lambda r: -len(r[0]))       # (las largas primero: «Nintendo Switch» antes que «Switch»)


def aplicar_diccionario(texto: str, reglas: list[tuple[str, str]] | None = None) -> str:
    for a, b in (leer_diccionario() if reglas is None else reglas):
        texto = re.sub(r"(?<!\w)" + re.escape(a) + r"(?!\w)", lambda _m, b=b: b, texto, flags=re.IGNORECASE)
    return texto


def ruta_borrador() -> Path:
    return ruta_diccionario().parent / "borrador.txt"


def leer_borrador() -> str:
    try:
        return ruta_borrador().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def guardar_borrador(texto: str):
    """📝 Lo que tienes escrito en el panel (se recupera al volver a abrir Reclaimer)."""
    p = ruta_borrador()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, p)


def añadir_al_diccionario(palabra: str, suena: str):
    """Añade (o cambia) una entrada sin tocar el resto del archivo."""
    palabra, suena = palabra.strip(), suena.strip()
    if not palabra:
        return
    lineas = texto_diccionario().splitlines()
    nuevo = f"{palabra} = {suena}"
    for i, linea in enumerate(lineas):
        s = linea.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip().lower() == palabra.lower():
            lineas[i] = nuevo
            break
    else:
        lineas.append(nuevo)
    guardar_diccionario("\n".join(lineas))


# ------------------------------------------------------------------ texto
_ABREV = {"sr", "sra", "srta", "dr", "dra", "ing", "lic", "etc", "ej", "vs", "aprox", "núm", "num", "pág", "pag",
          "ud", "uds", "vol", "cap", "min", "máx", "max", "art", "av", "dto", "tel", "nº", "no", "p", "ee", "uu"}


def _es_emoji(ch: str) -> bool:
    o = ord(ch)
    cat = unicodedata.category(ch)
    return (0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o in (0xFE0F, 0x200D)
            or cat in ("Cs", "Co") or (cat == "So" and o > 0x2000))


def limpiar(t: str) -> str:
    """Lo que se ESCRIBE (subtítulos, Texto) y se lee: sin marcas de Markdown, enlaces, almohadillas de hashtag ni
    emojis (lo que no se lee tampoco sale escrito). El resto, tal cual (signos, números, mayúsculas)."""
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)
    # títulos, viñetas y listas numeradas de Markdown: sin la marca, y cada uno es su propia frase
    t = re.sub(r"(?m)^[ \t]*(?:#{1,6}|[-*•]|\d+[.)])[ \t]+(.*?)[ \t]*$",
               lambda m: m.group(1) + ("" if re.search(r"[.!?…:;]['\"»”)]*$", m.group(1)) or not m.group(1) else "."),
               t)
    t = t.replace("**", "").replace("*", "").replace("`", "")
    t = re.sub(r"(?<!\w)_+|_+(?!\w)", "", t)                   # _cursiva_ y __negrita__
    t = re.sub(r"(?<![\w#])#(?=[^\W\d])", "", t)               # #hashtag → hashtag («#1» se queda)
    t = "".join(ch for ch in t if not _es_emoji(ch))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" +(?=[.,;:!?…])", "", t)                      # («tema 😀.» → «tema.»)
    return "\n".join(x.strip() for x in t.split("\n"))


def _normalizar(t: str) -> str:
    """Lo que se lee: lo limpio y los signos sueltos dichos con palabras («&» → «y», «25 €» → «25 euros»…)."""
    t = limpiar(t)
    t = re.sub(r"(\d)\s*€", r"\1 euros", t)
    t = re.sub(r"\$\s*(\d[\d.,]*)", r"\1 dólares", t)
    t = re.sub(r"(\d[\d.,]*)\s*\$", r"\1 dólares", t)
    t = re.sub(r"(?<=\d)\s*[xX×]\s*(?=\d)", " por ", t)
    t = re.sub(r"\s&\s", " y ", t)
    t = re.sub(r"(?<=[\w\s])\+(?=[\s\d])", " más ", t)
    t = re.sub(r"\s=\s", " igual a ", t)
    t = re.sub(r"@(?=\w)", " arroba ", t)
    t = re.sub(r"#(?=\d)", "número ", t)
    t = t.replace("—", ", ").replace("–", ", ")
    return re.sub(r"[ \t]+", " ", t)


def _partir_largo(p: str) -> list[str]:
    out = []
    while len(p) > MAX_FRASE:
        corte = max(p.rfind(c, 0, MAX_FRASE) for c in (",", ";", ":"))
        if corte < 80:
            corte = p.rfind(" ", 0, MAX_FRASE)
            corte = corte if corte > 80 else MAX_FRASE
        out.append(p[:corte + 1].strip())
        p = p[corte + 1:].strip()
    if p:
        out.append(p)
    return out


def frases(texto: str) -> list[dict]:
    """Las frases del guion en orden: [{"texto": la frase como la escribiste (sin Markdown, enlaces ni emojis: es lo
    que sale en los subtítulos), "fin_parrafo": bool}].
    Un párrafo = separado por una línea en blanco (o por un salto de línea simple si la línea acaba en punto)."""
    out: list[dict] = []
    texto = limpiar((texto or "").replace("\r\n", "\n").replace("\r", "\n"))
    parrafos = [p for p in re.split(r"\n\s*\n", texto) if p.strip()]
    for par in parrafos:
        lineas = [x.strip() for x in par.split("\n") if x.strip()]
        trozos: list[str] = []
        for linea in lineas:                            # (una línea sin punto final se une a la siguiente: guion
            if trozos and not re.search(r"[.!?…:;]['\"»”)]*$", trozos[-1]):  # pegado con saltos a mitad de frase)
                trozos[-1] += " " + linea
            else:
                trozos.append(linea)
        piezas: list[str] = []
        for tz in trozos:
            for s in re.split(r"(?<=[.!?…])['\"»”)]*\s+", tz):
                s = s.strip()
                if not s:
                    continue
                if piezas:
                    prev = piezas[-1]
                    ult = re.findall(r"([\wñáéíóúü]+)\.$", prev.lower())
                    if (ult and ult[0] in _ABREV) or re.match(r"^[a-zñáéíóú]", s) or \
                            re.search(r"\b[A-ZÑ]\.$", prev):            # «Sr. López», «etc. y», «J. R.»
                        piezas[-1] = prev + " " + s
                        continue
                piezas.append(s)
        piezas = [x for s in piezas for x in _partir_largo(s)]
        for i, s in enumerate(piezas):
            if re.search(r"[\wñáéíóúü0-9]", s):          # (una «frase» sin letras ni números no se lee)
                out.append({"texto": s, "fin_parrafo": i == len(piezas) - 1})
    return out


_VOC = "aeiouáéíóúü"
_UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
             "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte",
             "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete",
             "veintiocho", "veintinueve"]
_DECENAS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
             "ochocientos", "novecientos"]
# lo que se dice por un símbolo o una abreviatura (para repartir bien el tiempo de esa palabra)
_DICHO = {"€": "euros", "$": "dólares", "%": "por ciento", "&": "y", "+": "más", "=": "igual", "@": "arroba",
          "sr": "señor", "sra": "señora", "srta": "señorita", "dr": "doctor", "dra": "doctora", "etc": "etcétera",
          "ej": "ejemplo", "vs": "versus", "aprox": "aproximadamente", "ud": "usted", "uds": "ustedes",
          "km": "kilómetros", "kg": "kilos", "min": "minutos", "h": "horas"}


def numero_en_letras(n: int) -> str:
    """Un número entero en palabras (para medir cuánto se tarda en decirlo)."""
    if n < 0:
        return "menos " + numero_en_letras(-n)
    if n < 30:
        return _UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _DECENAS[d] + (f" y {_UNIDADES[u]}" if u else "")
    if n == 100:
        return "cien"
    if n < 1000:
        c, r = divmod(n, 100)
        return _CENTENAS[c] + (" " + numero_en_letras(r) if r else "")
    if n < 1_000_000:
        m, r = divmod(n, 1000)
        return ("mil" if m == 1 else numero_en_letras(m) + " mil") + (" " + numero_en_letras(r) if r else "")
    if n < 10 ** 12:
        m, r = divmod(n, 1_000_000)
        return ("un millón" if m == 1 else numero_en_letras(m) + " millones") + \
            (" " + numero_en_letras(r) if r else "")
    return " ".join(_UNIDADES[int(c)] for c in str(n))


def dicho(palabra: str) -> str:
    """Cómo suena una palabra suelta del guion: números en letras, símbolos y abreviaturas («Sr.» → «señor»)."""
    w = palabra.strip()
    m = re.fullmatch(r"[^\w€$%&+=@]*([\d.,]*\d)([€$%]?)[^\w]*", w)
    if m:
        num, sim = m.group(1), m.group(2)
        ent, _, dec = num.replace(".", "").partition(",") if re.search(r"\.\d{3}(?!\d)", num) or "," in num \
            else (num.replace(".", ""), "", "")
        try:
            out = numero_en_letras(int(ent or "0"))
            if dec:
                out += " coma " + numero_en_letras(int(dec[:6]))
        except ValueError:
            out = num
        return out + (" " + _DICHO[sim] if sim else "")
    limpio = re.sub(r"^[^\w€$%&+=@]+|[^\w€$%&+=@]+$", "", w)
    return _DICHO.get(limpio.lower(), limpio or w)


def silabas(palabra: str) -> int:
    """Sílabas aproximadas de una palabra en español (grupos de vocales)."""
    w = palabra.lower()
    if any(ch.isdigit() for ch in w):
        return sum(silabas(x) for x in dicho(w).split()) or 1
    w = re.sub(r"[^a-zñáéíóúü]", "", w)
    if not w:
        return 1
    n = 0
    prev = False
    for i, ch in enumerate(w):
        v = ch in _VOC or (ch == "y" and (i == len(w) - 1 or w[i + 1] not in _VOC) and i > 0)
        if v and not prev:
            n += 1
        elif v and prev and ch in "aeoáéó" and w[i - 1] in "aeoáéó":
            n += 1                                     # hiato (dos vocales fuertes: «le-er», «po-e-ta»)
        prev = v
    return max(1, n)


# Sílabas por segundo a 1,0x de cada motor/modelo (medido con el mismo texto el 16/11/2026)
SILABAS_SEG = {"kokoro": 5.8, "es_ES-davefx-medium": 6.0, "es_ES-sharvard-medium": 5.9, "es_MX-ald-medium": 5.0}


def contar(texto: str, velocidad: float = 1.1, pausa: float = 0.25, pausa_parrafo: float = 0.6,
           voz: str | None = None) -> tuple[int, float]:
    """(palabras, segundos estimados) para el contador del panel (Alex lee ~5,8 sílabas por segundo a 1,0x; con voz,
    su ritmo, el de su motor y sus pausas propios)."""
    ritmo = 5.8
    if voz is not None:
        v = voz_info(voz)
        velocidad, pausa, pausa_parrafo = velocidad * v.velocidad, pausa * v.pausas, pausa_parrafo * v.pausas
        ritmo = SILABAS_SEG.get(str(v.voz) if v.motor == "piper" else "kokoro", 5.8)
    fr = frases(texto)
    palabras = sum(len(f["texto"].split()) for f in fr)
    reglas = leer_diccionario()
    sil = sum(silabas(x) for f in fr for w in f["texto"].split() for x in aplicar_diccionario(dicho(w), reglas).split())
    seg = sil / (ritmo * max(0.5, velocidad))
    seg += sum((pausa_parrafo if f["fin_parrafo"] else pausa) for f in fr[:-1])
    seg += 0.12 * sum(f["texto"].count(",") for f in fr)
    return palabras, seg


# ------------------------------------------------------------------ audio
def _rms_frames(a: np.ndarray, hop: int) -> np.ndarray:
    n = len(a) // hop
    if n <= 0:
        return np.zeros(0, np.float32)
    x = a[:n * hop].reshape(n, hop)
    return np.sqrt((x.astype(np.float64) ** 2).mean(axis=1)).astype(np.float32)


def _silencios(a: np.ndarray, sr: int, min_dur: float = 0.06, db: float = 32.0) -> list[tuple[float, float]]:
    """Silencios DENTRO de una frase (pausas de las comas y cierres de «p», «t», «k»), en segundos desde su principio."""
    hop = int(sr * 0.01)
    e = _rms_frames(a, hop)
    if not len(e) or e.max() <= 0:
        return []
    bajo = e < e.max() * 10 ** (-db / 20)
    out, i = [], 0
    while i < len(bajo):
        if bajo[i]:
            j = i
            while j < len(bajo) and bajo[j]:
                j += 1
            if i > 0 and j < len(bajo) and (j - i) * 0.01 >= min_dur:
                out.append((i * 0.01, j * 0.01))
            i = j
        else:
            i += 1
    return out


def _voz(a: np.ndarray, sr: int) -> tuple[float, float]:
    """Dónde empieza y acaba la voz dentro del trozo (sin el aire del principio y del final)."""
    hop = int(sr * 0.005)
    e = _rms_frames(a, hop)
    if not len(e) or e.max() <= 0:
        return 0.0, len(a) / sr
    on = np.nonzero(e >= e.max() * 10 ** (-42 / 20))[0]
    if not len(on):
        return 0.0, len(a) / sr
    return max(0.0, on[0] * 0.005 - 0.01), min(len(a) / sr, (on[-1] + 1) * 0.005 + 0.01)


def _emparejar(esperados: list[float], fuertes: list[bool], sil: list[tuple[float, float]], tol: float) -> list:
    """Empareja (en orden) cada corte de cláusula con un silencio medido o con ninguno: programación dinámica.
    Coste: distancia al sitio esperado; un silencio largo sin corte cuesta (no suele ser una «p» o una «t»), y un
    corte fuerte (punto, «?», «:») sin silencio cuesta más que una coma sin pausa."""
    nb, ns = len(esperados), len(sil)
    INF = float("inf")
    sin_corte = [max(0.0, (s1 - s0) - 0.08) * 6.0 for s0, s1 in sil]      # (≤80 ms: casi gratis, puede ser una «t»)
    sin_sil = [1.2 if f else 0.6 for f in fuertes]
    # coste[b][s] = lo mejor con los b primeros cortes y los s primeros silencios
    coste = [[INF] * (ns + 1) for _ in range(nb + 1)]
    paso = [[None] * (ns + 1) for _ in range(nb + 1)]
    coste[0][0] = 0.0
    for b in range(nb + 1):
        for s in range(ns + 1):
            c = coste[b][s]
            if c == INF:
                continue
            if s < ns and c + sin_corte[s] < coste[b][s + 1]:
                coste[b][s + 1], paso[b][s + 1] = c + sin_corte[s], (b, s, None)
            if b < nb and c + sin_sil[b] < coste[b + 1][s]:
                coste[b + 1][s], paso[b + 1][s] = c + sin_sil[b], (b, s, None)
            if b < nb and s < ns:
                s0, s1 = sil[s]
                d = abs((s0 + s1) / 2 - esperados[b]) / tol
                if d <= 1.0:
                    v = c + d - min(0.3, (s1 - s0)) * (2.0 if fuertes[b] else 1.0)
                    if v < coste[b + 1][s + 1]:
                        coste[b + 1][s + 1], paso[b + 1][s + 1] = v, (b, s, s)
    out = [None] * nb
    b, s = nb, ns
    while (b, s) != (0, 0):
        pb, ps, emp = paso[b][s]
        if emp is not None:
            out[pb] = sil[emp]
        b, s = pb, ps
    return out


_VOCALES_IPA = set("aeiouɛɔəɐæɪʊ")


def _pesos(toks: list[str], reglas: list[tuple[str, str]], fonemas=None) -> list[float]:
    """Cuánto se tarda (en proporción) en decir cada palabra. Con fonemas(texto) (los del propio modelo): consonantes
    1 y vocales 1,5 (medido contra el alineador: mediana 31 ms); sin él, sus sílabas tal como suenan (47 ms)."""
    out = []
    for w in toks:
        suena = aplicar_diccionario(dicho(w), reglas)
        peso = 0.0
        if fonemas is not None and re.search(r"\w", suena):
            try:
                ph = [c for c in fonemas(suena) if c.isalpha() and c not in "ˈˌːˑ"]
                peso = sum(1.5 if c in _VOCALES_IPA else 1.0 for c in ph) / 2.2   # (~2,2 fonemas «pesados» por sílaba)
            except Exception:  # noqa: BLE001 - si el fonetizador falla con algo raro, por sílabas
                peso = 0.0
        if peso <= 0:
            peso = float(sum(silabas(x) for x in suena.split()))
        out.append(max(1.0, peso))
    return out


SNAP = 0.06          # cada borde entre palabras, al punto más silencioso a ±60 ms


def _palabras_de_frase(texto: str, leido: str, a: np.ndarray, sr: int, t0: float,
                       reglas: list[tuple[str, str]], fonemas=None) -> list[list]:
    """Las palabras ORIGINALES de la frase repartidas en su audio (a, desde t0): por sílabas de lo que se lee, con las
    pausas de las comas puestas en los silencios medidos y cada borde ajustado al punto más silencioso cercano."""
    toks = texto.split()
    if not toks:
        return []
    dur = len(a) / sr
    v0, v1 = _voz(a, sr)
    pesos = _pesos(toks, reglas, fonemas)
    total = sum(pesos)
    acum = np.cumsum(pesos) / total
    # cortes de cláusula (coma, punto y coma, dos puntos, paréntesis, «etc.»…)
    cortes = [i for i, w in enumerate(toks[:-1]) if re.search(r"[,;:.!?)\]»”—…]$", w)]
    sil = [(s0, s1) for s0, s1 in _silencios(a, sr) if v0 < s0 and s1 < v1]
    # el sitio esperado de cada corte: por peso, sobre el tiempo CON voz (las pausas no se llevan palabras)
    largos = [(s0, s1) for s0, s1 in sil if s1 - s0 >= 0.09]
    hablado = (v1 - v0) - sum(s1 - s0 for s0, s1 in largos)

    def a_tiempo(frac: float) -> float:
        t, falta = v0, frac * hablado
        for s0, s1 in largos:
            if t + falta <= s0:
                break
            falta -= s0 - t
            t = s1
        return t + falta
    esperados = [a_tiempo(float(acum[i])) for i in cortes]
    fuertes = [bool(re.search(r"[.!?:;…]$", toks[i])) for i in cortes]
    emparejados = _emparejar(esperados, fuertes, sil, tol=max(0.3, 0.12 * (v1 - v0)))
    usados = [(i, m[0], m[1]) for i, m in zip(cortes, emparejados) if m is not None]
    # tramos de voz entre pausas → palabras de cada tramo por peso
    tramos = []
    ini_t, ini_w = v0, 0
    for i, s0, s1 in usados:
        tramos.append((ini_t, s0, ini_w, i + 1))
        ini_t, ini_w = s1, i + 1
    tramos.append((ini_t, v1, ini_w, len(toks)))
    hop = int(sr * 0.005)
    e = _rms_frames(a, hop)
    out = []
    for ta, tb, wa, wb in tramos:
        if wb <= wa:
            continue
        ps = pesos[wa:wb]
        tot = sum(ps)
        bordes = [ta]
        c = ta
        for p in ps[:-1]:
            c += (tb - ta) * p / tot
            bordes.append(c)
        bordes.append(tb)
        for b in range(1, len(bordes) - 1):
            vent = min(SNAP, 0.25 * (bordes[b] - bordes[b - 1]), 0.25 * (bordes[b + 1] - bordes[b]))
            if vent >= 0.01 and len(e):
                lo = max(0, int((bordes[b] - vent) / 0.005))
                hi = min(len(e), int((bordes[b] + vent) / 0.005) + 1)
                if hi - lo >= 2:
                    bordes[b] = (lo + int(np.argmin(e[lo:hi]))) * 0.005 + 0.0025
        for k in range(1, len(bordes)):                  # siempre crecientes (mínimo 40 ms por palabra)
            bordes[k] = max(bordes[k], bordes[k - 1] + 0.04)
        for k, w in enumerate(toks[wa:wb]):
            out.append([round(t0 + bordes[k], 3), round(t0 + min(bordes[k + 1], dur), 3), w, 1.0])
    for k in range(1, len(out)):                         # (por si el mínimo de 40 ms empujó algo fuera)
        if out[k][0] < out[k - 1][1]:
            out[k][0] = out[k - 1][1]
        if out[k][1] < out[k][0]:
            out[k][1] = out[k][0]
    return out


# ------------------------------------------------------------------ tono y ecualización (FFmpeg, todo el audio de golpe)
# «Voz de documental»: paso alto (fuera retumbe y ruido grave), cuerpo en graves, menos «caja» en medios, algo de
# presencia y compresión suave (la voz siempre delante, sin bombear). Nada de reverb ni efectos: que no suene a robot.
_EQ = {
    "documental": ("highpass=f=80:p=2,equalizer=f=140:t=q:w=0.9:g=2.5,equalizer=f=380:t=q:w=1.2:g=-1.5,"
                   "equalizer=f=3200:t=q:w=1.4:g=1.5,deesser=i=0.3,"
                   "acompressor=threshold=-20dB:ratio=2.5:attack=12:release=180:knee=6:makeup=2"),
    "firme": ("highpass=f=85:p=2,equalizer=f=120:t=q:w=1:g=2,equalizer=f=400:t=q:w=1.2:g=-1.5,"
              "equalizer=f=2600:t=q:w=1.2:g=2.5,deesser=i=0.3,"
              "acompressor=threshold=-22dB:ratio=3.5:attack=8:release=150:knee=4:makeup=3"),
    "suave": ("highpass=f=70:p=2,equalizer=f=180:t=q:w=1:g=1.5,equalizer=f=6500:t=q:w=1:g=-1,"
              "acompressor=threshold=-18dB:ratio=2:attack=20:release=250:knee=6:makeup=1.5"),
}
# 🤖 Toque robótico (tipo Loquendo): algo más agudo, timbre de radio y un pelín metálico. Misma duración.
_ROBOT = (f"asetrate={SR}*1.060,aresample={SR},atempo={1 / 1.06:.4f},"
          "highpass=f=140,lowpass=f=9000,equalizer=f=2800:t=q:w=1.2:g=4,equalizer=f=400:t=q:w=1:g=-2,"
          "aecho=0.8:0.6:6:0.25")
_rubberband: bool | None = None


def tiene_rubberband() -> bool:
    """¿El FFmpeg trae «rubberband»? (cambia el tono conservando el timbre y la duración exacta)."""
    global _rubberband
    if _rubberband is None:
        try:
            from ..core import media
            r = subprocess.run([media.ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True,
                               timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _rubberband = bool(re.search(r"^\s*\S+\s+rubberband\s", r.stdout or "", re.M))
        except (OSError, RuntimeError, subprocess.SubprocessError):     # (sin FFmpeg: media.ffmpeg() lanza)
            _rubberband = False
    return _rubberband


def creditos_voz(voz: str | None) -> dict | None:
    """Lo que hay que poner en los créditos del video si la voz pide atribución (CC BY); None si no hace falta."""
    v = voz_info(voz)
    if v.motor != "piper" or not _pide_atribucion(str(v.voz)):
        return None
    m = PIPER_MODELOS[str(v.voz)]
    return {"tipo": "voz", "title": m["atribucion"], "url": m["url_atribucion"], "voz": v.clave,
            "licencia": m["licencia"]}


def ruta_creditos(ruta_wav: str) -> str:
    """«<narración>.creditos.json» (como los clips: credits.collect lo encuentra junto al medio)."""
    return os.path.splitext(ruta_wav)[0] + ".creditos.json"


def escribir_creditos(ruta_wav: str, voz: str | None) -> str | None:
    """Si la voz pide atribución, deja sus créditos junto al WAV (salen al pedir la descripción del video)."""
    datos = creditos_voz(voz)
    if not datos:
        return None
    import json
    ruta = ruta_creditos(ruta_wav)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    return ruta


def _desactivar_rubberband():
    global _rubberband
    _rubberband = False


def cadena_efectos(tono: float = 0.0, eq: str = "", robot: bool = False) -> str:
    """Los filtros de FFmpeg de esa voz ("" = nada que hacer)."""
    f = []
    if abs(tono) >= 0.05:
        r = 2 ** (tono / 12)
        f.append(f"rubberband=pitch={r:.5f}:formant=preserved:pitchq=quality" if tiene_rubberband() else
                 f"asetrate={SR}*{r:.5f},aresample={SR},atempo={1 / r:.5f}")
    if eq:
        f.append(_EQ[eq])
    if robot:
        f.append(_ROBOT)
    return ",".join(f)


def _procesar(audio: np.ndarray, cadena: str) -> np.ndarray:
    """El audio (float, 24 kHz) por los filtros de FFmpeg, por tuberías (sin archivos)."""
    from ..core import media
    r = subprocess.run([media.ffmpeg(), "-nostdin", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1",
                        "-i", "-", "-af", cadena, "-f", "f32le", "-ar", str(SR), "-ac", "1", "-"],
                       input=np.ascontiguousarray(audio, "<f4").tobytes(), capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("No se pudo aplicar el tono o la ecualización de la voz: "
                           + (r.stderr or b"").decode("utf-8", "replace").strip()[-200:])
    out = np.frombuffer(r.stdout, "<f4").astype(np.float32)
    if not len(out) or not np.isfinite(out).all():
        raise RuntimeError("El tono o la ecualización de la voz dieron un audio vacío o roto.")
    return out


def _rms_voz_db(a: np.ndarray) -> float:
    """RMS (dBFS) solo de los tramos con voz (ventanas de 50 ms a menos de 40 dB del máximo): sin los silencios."""
    e = _rms_frames(a, int(SR * 0.05))
    if not len(e) or e.max() <= 0:
        return -120.0
    v = e[e >= e.max() * 10 ** (-40 / 20)]
    return float(20 * np.log10(np.sqrt((v.astype(np.float64) ** 2).mean()) + 1e-12))


def sonoridad(a: np.ndarray) -> float | None:
    """Sonoridad integrada (LUFS, EBU R128 con su puerta) medida con el ebur128 de FFmpeg. None si no se pudo."""
    try:
        from ..core import media
        r = subprocess.run([media.ffmpeg(), "-nostdin", "-hide_banner", "-nostats", "-f", "f32le", "-ar", str(SR),
                            "-ac", "1", "-i", "-", "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                           input=np.ascontiguousarray(a, "<f4").tobytes(), capture_output=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, RuntimeError, subprocess.SubprocessError):         # (sin FFmpeg: plan B por RMS)
        return None
    found = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", (r.stderr or b"").decode("utf-8", "replace"))
    v = float(found[-1]) if found else None
    return v if v is not None and -70.0 < v < 0.0 else None


def _min_deslizante(x: np.ndarray, k: int) -> np.ndarray:
    """Mínimo en una ventana centrada de k muestras (k impar), en O(n) (van Herk / Gil-Werman)."""
    w = k // 2
    n = len(x)
    pad = np.concatenate([np.full(w, x[0]), x, np.full(w + (-(n + 2 * w) % k), x[-1])])
    b = pad.reshape(-1, k)
    pre = np.minimum.accumulate(b, axis=1).ravel()
    suf = np.minimum.accumulate(b[:, ::-1], axis=1)[:, ::-1].ravel()
    i = np.arange(n)
    return np.minimum(suf[i], pre[i + k - 1])


def _limitar(a: np.ndarray, techo: float = PICO, ms: float = 8.0) -> np.ndarray:
    """Limitador de picos sin retraso: la ganancia necesaria en cada muestra, mínimo en ±ms y suavizada con una media
    del mismo ancho (así nunca pasa del techo y no cruje). Fuera de los picos no toca nada."""
    if not len(a) or float(np.abs(a).max()) <= techo:
        return a
    k = 2 * int(SR * ms / 1000) + 1
    g = np.minimum(1.0, techo / np.maximum(np.abs(a), 1e-9))
    g = _min_deslizante(g, k)
    c = np.concatenate([[0.0], np.cumsum(np.concatenate([np.full(k // 2, 1.0), g, np.full(k // 2, 1.0)]))])
    g = (c[k:] - c[:-k]) / k
    return np.clip(a * g[:len(a)], -techo, techo).astype(np.float32)


def normalizar_sonoridad(a: np.ndarray, objetivo: float = LUFS_VOZ, techo: float = PICO) -> np.ndarray:
    """Todas las voces igual de fuertes: ganancia hasta «objetivo» LUFS (plan B sin FFmpeg: por el RMS de los tramos
    con voz, que en estas voces queda ~0,3 dB por encima de su LUFS, medido) y limitador de picos a «techo»
    (−1 dBFS). Una segunda pasada corrige lo que quite el limitador."""
    a = np.asarray(a, np.float32)
    if not len(a) or float(np.abs(a).max()) <= 0:
        return a
    for _ in range(2):
        lufs = sonoridad(a)
        actual = lufs if lufs is not None else _rms_voz_db(a) - 0.3
        if abs(actual - objetivo) < 0.2:
            break
        a = _limitar(a * np.float32(10 ** ((objetivo - actual) / 20)), techo)
    return _limitar(a, techo)


def _remuestrear(a: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    """Cambio de frecuencia de muestreo limpio (por FFT: sin el «aliasing» de interpolar a lo bruto)."""
    if sr_in == sr_out or not len(a):
        return a
    n_out = int(round(len(a) * sr_out / sr_in))
    spec = np.fft.rfft(a.astype(np.float64))
    m = n_out // 2 + 1
    nuevo = np.zeros(m, np.complex128)
    k = min(m, len(spec))
    nuevo[:k] = spec[:k]
    return (np.fft.irfft(nuevo, n_out) * (n_out / len(a))).astype(np.float32)


def _escribir_wav(ruta: str, a: np.ndarray):
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        paso = SR * 30
        for i in range(0, len(a), paso):
            w.writeframes((np.clip(a[i:i + paso], -1.0, 1.0) * 32767.0).astype("<i2").tobytes())


def nombre_corto(voz: str) -> str:
    """«🎙 Narrador de documental» → «Narrador de documental»; «Alex (hombre)» → «Alex»."""
    return re.sub(r"^[^\w]+", "", voz_info(voz).nombre).split(" (")[0].strip()


def ruta_nueva(carpeta: str, voz: str = VOZ_DEFECTO) -> str:
    base = os.path.join(carpeta, f"Narración IA {time.strftime('%Y-%m-%d %H-%M-%S')} ({nombre_corto(voz)})")
    ruta, n = base + ".wav", 2
    while os.path.exists(ruta):
        ruta, n = f"{base} ({n}).wav", n + 1
    return ruta


def _motor(v: Voz, velocidad: float, acento: str, progress: ProgressFn):
    """(leer(texto) -> (audio float, sr), fonemas(texto) -> str) de esa voz."""
    if v.motor == "piper":
        pv = cargar_piper(str(v.voz), progress)
        from piper import SynthesisConfig
        # (normalize_audio=False: Piper subiría cada frase a pico 1,0; aquí solo cuenta la normalización global. Y
        # sin pasar por synthesize(), que recorta a ±1: davefx llega a 0,99 en bruto. Mismo proceso, sin recortar)
        cfg = SynthesisConfig(speaker_id=v.hablante, length_scale=1.0 / velocidad, normalize_audio=False)

        def leer(txt: str):
            trozos = []
            for fonos in pv.phonemize(txt):
                if fonos:
                    a = pv.phoneme_ids_to_audio(pv.phonemes_to_ids(fonos), cfg)
                    trozos.append(np.asarray(a[0] if isinstance(a, tuple) else a, np.float32).ravel())
            if not trozos:
                return np.zeros(0, np.float32), SR
            return np.concatenate(trozos), int(pv.config.sample_rate)

        def fonemas(txt: str) -> str:
            return "".join(p for frase in pv.phonemize(txt) for p in frase)
        return leer, fonemas
    k = cargar(progress)
    estilo = _estilo_kokoro(k, v.voz)

    def leer(txt: str):
        return k.create(txt, voice=estilo, speed=velocidad, lang=acento)

    def fonemas(txt: str) -> str:
        return k.tokenizer.phonemize(txt, acento)
    return leer, fonemas


def sintetizar(texto: str, voz: str = VOZ_DEFECTO, velocidad: float = 1.1, pausa: float = 0.25,
               pausa_parrafo: float = 0.6, acento: str = "es", robot: bool = False, destino: str | None = None,
               progress: ProgressFn = None, cancelled: CancelFn = None, solo_primera: bool = False) -> dict:
    """Lee el guion frase a frase con esa voz del CATALOGO y escribe el WAV en «destino». La velocidad y las pausas
    se multiplican por las propias de la voz; el tono y la ecualización van al final (los tiempos se reescalan si la
    duración cambia).
    Devuelve {"ruta", "duracion", "frases": [{"texto", "leido", "inicio", "fin"}], "transcripcion": {...}}.
    Cancelar (cancelled() → True) lanza Cancelled y no deja ningún archivo."""
    fr = frases(texto)
    if solo_primera:
        fr = fr[:1]
    if not fr:
        raise ValueError("No hay nada que leer: pega el texto primero.")
    if not destino:
        raise ValueError("Falta dónde guardar la narración.")
    v = voz_info(voz)
    ok, why = available(v.clave)
    if not ok:
        raise RuntimeError(why)
    velocidad = float(min(2.0, max(0.5, velocidad * v.velocidad)))
    pausa, pausa_parrafo = pausa * v.pausas, pausa_parrafo * v.pausas
    cadena = cadena_efectos(v.tono, v.eq, robot)
    if cadena:                                         # (tono/ecualización necesitan FFmpeg: avisar ANTES de leer)
        from ..core import media
        media.ffmpeg()
    leer, fonemas = _motor(v, velocidad, acento, progress)
    check_cancel(cancelled)
    reglas = leer_diccionario()
    trozos: list[np.ndarray] = []
    info: list[dict] = []
    palabras: list[list] = []
    segmentos: list[list] = []
    t = 0.0
    n = len(fr)
    t_ini = time.monotonic()
    for i, f in enumerate(fr):
        check_cancel(cancelled)
        resto = ""
        if i:
            hecho = time.monotonic() - t_ini
            falta = hecho / i * (n - i)
            resto = f" · faltan ~{int(falta) // 60}:{int(falta) % 60:02d}" if falta >= 3 else ""
        report(progress, 0.05 + 0.88 * i / n, f"Leyendo frase {i + 1} de {n}…{resto}")
        leido = aplicar_diccionario(_normalizar(f["texto"]), reglas).strip()
        if not re.search(r"\w", leido):
            continue
        a, sr = leer(leido)
        a = np.nan_to_num(np.asarray(a, np.float32).ravel())
        a = _remuestrear(a, int(sr))                   # (Kokoro da 24 kHz; Piper 22,05 kHz)
        if not len(a):
            continue
        first = len(palabras)
        palabras += _palabras_de_frase(f["texto"], leido, a, SR, t, reglas, fonemas)
        if len(palabras) > first:
            segmentos.append([palabras[first][0], palabras[-1][1], first, len(palabras)])
        info.append({"texto": f["texto"], "leido": leido, "inicio": round(t, 3), "fin": round(t + len(a) / SR, 3)})
        trozos.append(a)
        t += len(a) / SR
        if i < n - 1:
            hueco = pausa_parrafo if f["fin_parrafo"] else pausa
            if hueco > 0:
                trozos.append(np.zeros(int(round(hueco * SR)), np.float32))
                t += round(hueco * SR) / SR
    check_cancel(cancelled)
    if not trozos:
        raise ValueError("No se pudo leer nada del texto.")
    audio = np.concatenate(trozos)
    pico = float(np.abs(audio).max()) or 1.0
    audio *= PICO / pico
    if cadena:
        report(progress, 0.94, "Dando el tono a la voz…")
        n0 = len(audio)
        try:
            audio2 = _procesar(audio, cadena)
        except RuntimeError:
            if "rubberband" not in cadena:
                raise
            _desactivar_rubberband()                   # (rubberband falló: otra vez con asetrate+atempo)
            audio2 = _procesar(audio, cadena_efectos(v.tono, v.eq, robot))
        audio = audio2
        check_cancel(cancelled)
        if len(audio) != n0:                           # (asetrate+atempo no clava la duración: todo a escala)
            k_ = len(audio) / n0
            dur_ = len(audio) / SR
            for w in palabras:
                w[0], w[1] = round(min(w[0] * k_, dur_), 3), round(min(w[1] * k_, dur_), 3)
            for s in segmentos:
                s[0], s[1] = round(min(s[0] * k_, dur_), 3), round(min(s[1] * k_, dur_), 3)
            for x in info:
                x["inicio"], x["fin"] = round(x["inicio"] * k_, 3), round(min(x["fin"] * k_, dur_), 3)
    report(progress, 0.96, "Igualando el volumen…")
    audio = normalizar_sonoridad(audio)                # (todas las voces igual de fuertes: −18 LUFS, picos ≤ −1 dBFS)
    report(progress, 0.97, "Guardando la narración…")
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    tmp = os.path.join(os.path.dirname(os.path.abspath(destino)), f".~voz_ia_{os.getpid()}_{threading.get_ident()}.wav")
    try:
        _escribir_wav(tmp, audio)
        check_cancel(cancelled)
        os.replace(tmp, destino)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    dur = len(audio) / SR
    tr = {"language": acento.split("-")[0], "model": f"{v.motor}:{v.clave}", "words": palabras,
          "segments": segmentos, "estimada": True, "voz_ia": True}  # ("aligned" solo con el alineador: afinar())
    report(progress, 1.0, f"✓ Narración lista: {int(dur) // 60}:{int(dur) % 60:02d}.")
    return {"ruta": destino, "duracion": dur, "frases": info, "transcripcion": tr}


# ------------------------------------------------------------------ 🎧 muestras para comparar las voces
TEXTO_MUESTRA = ("En el invierno de aquel año, el país despertó en silencio. Nadie imaginaba que una sola decisión "
                 "cambiaría su historia para siempre. Esta es la historia de cómo llegó al poder.")


def carpeta_muestras() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Videos" / "Reclaimer" / "Muestras de voces"


def creditos_piper() -> str:
    """Las licencias y atribuciones de las voces de Piper (para licencias/ y el LEEME de las muestras)."""
    out = []
    for modelo, m in PIPER_MODELOS.items():
        out.append(f"· {modelo} — {m['licencia']}\n  {m['creditos']}\n  "
                   f"https://huggingface.co/rhasspy/piper-voices/tree/{PIPER_REV}/{m['remoto'].rstrip('/')}")
    return "\n".join(out)


def crear_muestras(carpeta: str | Path | None = None, texto: str = TEXTO_MUESTRA, progress: ProgressFn = None,
                   cancelled: CancelFn = None, voces: list[str] | None = None) -> list[str]:
    """🎧 La misma narración con cada voz del catálogo («01 Narrador de documental (grave).wav», …) + LEEME.txt con
    qué es cada una y su licencia. Las voces sin su modelo se saltan (y se dice en el LEEME). No suena nada."""
    d = Path(carpeta) if carpeta else carpeta_muestras()
    d.mkdir(parents=True, exist_ok=True)
    claves = voces or list(CATALOGO)
    hechas, lineas, saltadas = [], [], []
    for i, clave in enumerate(claves, 1):
        check_cancel(cancelled)
        v = CATALOGO[clave]
        report(progress, (i - 1) / len(claves), f"Muestra {i} de {len(claves)}: {nombre_corto(clave)}…")
        ok, why = available(clave)
        if not ok:
            saltadas.append(f"  {v.nombre}: {why}")
            continue
        ruta = d / f"{i:02d} {v.archivo}.wav"
        res = sintetizar(texto, clave, destino=str(ruta), cancelled=cancelled)
        hechas.append(str(ruta))
        motor = "Kokoro" if v.motor == "kokoro" else "Piper"
        grupo = motor if v.grupo == motor else f"{v.grupo}, {motor}"
        seg = f"{res['duracion']:.1f}".replace(".", ",")
        lineas.append(f"{ruta.name}  ({seg} s)\n   {v.nombre} [{grupo}] — "
                      f"{v.descripcion.splitlines()[0]}\n   Licencia: {v.licencia}.")
    leeme = ("MUESTRAS DE VOCES — Reclaimer, «🗣 Voz IA»\n\n"
             "El mismo texto leído con cada voz, con los ajustes de entrada del panel (velocidad 1,10 x; las voces de\n"
             "«🎙 Narración» ya van más despacio, más graves y con su ecualización). Todas igual de fuertes\n"
             f"({LUFS_VOZ:.0f} LUFS, picos por debajo de −1 dBFS). Escúchalas y elige la tuya en el panel 🗣 Voz IA → "
             "«Voz».\n\n"
             f"Texto: «{texto}»\n\n" + "\n\n".join(lineas)
             + ("\n\nNo se pudieron hacer (falta su modelo):\n" + "\n".join(saltadas) if saltadas else "")
             + "\n\nLICENCIAS\n"
               "· Kokoro-82M (hexgrad): Apache 2.0 — uso comercial libre. https://huggingface.co/hexgrad/Kokoro-82M\n"
             + creditos_piper()
             + "\n\nLas voces con licencia CC BY piden atribución: si usas «Narrador solemne», «Narradora clara» o "
               "«Sharvard»,\nmenciona en la descripción del video: «Voz sintética: Piper, voz sharvard (Sharvard "
               "Corpus, CC BY 3.0)».\n")
    (d / "LEEME.txt").write_text(leeme, encoding="utf-8")
    report(progress, 1.0, f"✓ {len(hechas)} muestras en {d}")
    return hechas


def afinar(ruta: str, tr: dict, progress: ProgressFn = None, cancelled: CancelFn = None) -> dict:
    """🎯 Opcional: las palabras afinadas con el alineador (motor_ia/alineador_es, ~20 ms) si está instalado. Si no está
    o falla, la transcripción se queda como estaba (ya es buena: sale de los tiempos reales de cada frase)."""
    try:
        from . import align
        if not align.available()[0]:
            return tr
        try:
            nuevas = align.align_words(ruta, [list(w) for w in tr["words"]], progress, cancelled)
        finally:
            align.unload()
        if cancelled and cancelled():
            raise Cancelled()
        if len(nuevas) == len(tr["words"]):
            segs = [[nuevas[a][0], nuevas[b - 1][1], a, b] for _s, _e, a, b in tr.get("segments", []) if b > a]
            out = dict(tr, words=nuevas, segments=segs, aligned=True, afinada=True)
            out.pop("estimada", None)
            return out
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - el alineador es un extra: si falla, se queda la estimación
        pass
    return tr
