"""
🤝 Las acciones que Claude puede pedirle a Reclaimer (por MCP). Solo usan funciones que Reclaimer ya tiene, todo lo que
cambia se deshace con Ctrl+Z y nada borra ni pisa tus archivos. Sin Qt: lo comparten el servidor MCP (mcp_reclaimer.py)
y el puente que vive dentro de Reclaimer (ui/claude_bridge.py).
"""
from __future__ import annotations

PROTOCOL = "2025-06-18"
SERVER_NAME = "reclaimer"
INSTRUCTIONS = (
    "Reclaimer es el editor de video del usuario (Windows). Con estas herramientas editas EN SU PROYECTO ABIERTO: todo "
    "lo que hagas aparece en su línea de tiempo y él lo puede deshacer con Ctrl+Z. Empieza siempre con «estado» para ver "
    "el proyecto. Tras cada cambio importante usa «captura» para ver cómo quedó y cuéntaselo. Habla con él en español. "
    "No exportes ni guardes encima de nada sin que te lo pida."
)


def _obj(props: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


S, N, I, B = {"type": "string"}, {"type": "number"}, {"type": "integer"}, {"type": "boolean"}

TOOLS: list[dict] = [
    {"name": "estado",
     "description": "Resumen del proyecto abierto en Reclaimer: nombre, formato (youtube/short/edit), duración, cabezal, "
                    "pistas con sus clips, archivos importados (id, nombre, tipo, duración, si está transcrito), "
                    "subtítulos y trabajos en marcha (transcripción, exportación). Úsalo antes de editar.",
     "inputSchema": _obj()},
    {"name": "importar",
     "description": "Importa archivos (video, audio, imagen) al proyecto por su ruta completa. No los copia ni modifica.",
     "inputSchema": _obj({"rutas": {"type": "array", "items": S, "description": "Rutas completas de los archivos"}},
                         ["rutas"])},
    {"name": "poner_en_linea_de_tiempo",
     "description": "Pone un archivo importado en la línea de tiempo (en el cabezal si no dices dónde). Los videos con "
                    "sonido llevan su audio vinculado.",
     "inputSchema": _obj({"media_id": {**S, "description": "id del archivo (de «estado»)"},
                          "inicio": {**N, "description": "segundo de la línea de tiempo (opcional)"},
                          "pista": {**S, "description": "id de la pista (opcional; si no, la adecuada)"}},
                         ["media_id"])},
    {"name": "formato",
     "description": "Cambia el formato del proyecto: «youtube» (16:9), «short» (9:16 vertical) o «edit» (edit musical "
                    "vertical).",
     "inputSchema": _obj({"tipo": {"type": "string", "enum": ["youtube", "short", "edit"]}}, ["tipo"])},
    {"name": "transcribir",
     "description": "Transcribe la voz de un archivo (en segundo plano; la primera vez tarda unos minutos). Hace falta "
                    "para los subtítulos. Mira «estado» para saber cuándo termina.",
     "inputSchema": _obj({"media_id": S}, ["media_id"])},
    {"name": "eliminar_silencios",
     "description": "Quita los silencios del audio y junta lo de detrás (ripple, en todas las pistas: no se "
                    "desincroniza nada). Detección híbrida (volumen + IA) que no se come palabras. Ajustes: «shorts» "
                    "(pausas cortas), «equilibrado», «natural» (con aire) o «rapido». «proteccion»: «max» (por "
                    "defecto: nunca corta voz), «davinci» (el umbral manda como en DaVinci Resolve y solo se protege "
                    "la voz clara: lo que usa el usuario en la ventana), «media» o «resolve» (el umbral decide todo: "
                    "puede comerse finales suaves; solo si el usuario lo pide). Sin media_id: la narración / los clips de "
                    "audio de la línea de tiempo.",
     "inputSchema": _obj({"ajuste": {"type": "string", "enum": ["shorts", "equilibrado", "natural", "rapido"]},
                          "proteccion": {"type": "string", "enum": ["max", "davinci", "media", "resolve"]},
                          "media_id": {**S, "description": "solo los clips de este archivo (opcional)"},
                          "solo_mirar": {**B, "description": "true = solo decir cuánto quitaría, sin cortar"},
                         "fundido": {**B, "description": "true = fundido cruzado de audio en cada corte. SOLO si el usuario lo pide: por defecto no se pone ninguno"}})},
    {"name": "subtitulos",
     "description": "Pone los subtítulos dentro del video a partir de la transcripción de un archivo. Estilos: "
                    "«shorts» (a lo mucho 3 palabras, letra grande con sombra), «mis_shorts» (el del usuario), "
                    "«youtube» (clásico), «caja» (caja oscura), «dinamico», «minimalista». También: «quitar».",
     "inputSchema": _obj({"media_id": S,
                          "estilo": {"type": "string", "enum": ["shorts", "mis_shorts", "youtube", "caja", "dinamico",
                                                                "minimalista", "quitar"]}}, ["estilo"])},
    {"name": "texto",
     "description": "Añade un texto en pantalla (título, etiqueta) en un momento y durante unos segundos.",
     "inputSchema": _obj({"contenido": S, "inicio": N, "duracion": {**N, "description": "segundos (por defecto 3)"}},
                         ["contenido"])},
    {"name": "cortar",
     "description": "Divide los clips que hay en ese segundo (como la tecla S) o quita el tramo entre dos segundos y "
                    "junta lo de detrás.",
     "inputSchema": _obj({"en": {**N, "description": "dividir en este segundo"},
                          "quitar_desde": N, "quitar_hasta": N,
                         "fundido": {**B, "description": "true = fundido cruzado de audio en cada corte. SOLO si el usuario lo pide: por defecto no se pone ninguno"}})},
    {"name": "clips",
     "description": "Lista los clips (id, pista, inicio–fin, archivo o texto, volumen, fundidos, si está activo). "
                    "Filtra por pista y/o tramo. Úsalo para saber a qué clips aplicar «ajustar_clips» o «borrar_clips».",
     "inputSchema": _obj({"pista": {**S, "description": "id de la pista (opcional)"},
                          "desde": N, "hasta": N})},
    {"name": "ajustar_clips",
     "description": "Cambia clips en un solo paso (Ctrl+Z lo deshace): volumen en % (100 = normal, 0 = mudo), "
                    "fundido de entrada / salida en segundos (0 = sin fundido), activo (false = ni se ve ni se oye). "
                    "Elige los clips por ids, por pista y/o por tramo.",
     "inputSchema": _obj({"ids": {"type": "array", "items": S, "description": "ids de los clips (de «clips»)"},
                          "pista": {**S, "description": "o todos los de esta pista (id)"},
                          "desde": {**N, "description": "y/o los que tocan este tramo (segundos)"}, "hasta": N,
                          "volumen": {**N, "description": "porcentaje (0–400)"},
                          "fundido_entrada": {**N, "description": "segundos"},
                          "fundido_salida": {**N, "description": "segundos"},
                          "activo": B})},
    {"name": "borrar_clips",
     "description": "Borra clips de la línea de tiempo (también textos); el archivo original no se toca. "
                    "«juntar» = true para que lo de detrás se pegue (sin hueco). Elige por ids, pista y/o tramo.",
     "inputSchema": _obj({"ids": {"type": "array", "items": S, "description": "ids de los clips (de «clips»)"},
                          "pista": {**S, "description": "o todos los de esta pista (id)"},
                          "desde": {**N, "description": "y/o los que tocan este tramo (segundos)"}, "hasta": N,
                          "juntar": {**B, "description": "cerrar el hueco (por defecto no)"}})},
    {"name": "efectos_pista",
     "description": "Activa o desactiva los efectos de voz de una pista de audio (no tocan el archivo): "
                    "«ecualizar» (voz más clara), «reducir_ruido», «de_esser» (suaviza las «s»), «compresor».",
     "inputSchema": _obj({"pista": {**S, "description": "id de la pista de audio"},
                          "ecualizar": B, "reducir_ruido": B, "de_esser": B, "compresor": B}, ["pista"])},
    {"name": "juntar_huecos",
     "description": "Cierra los huecos vacíos de la línea de tiempo (lo de la derecha se pega a lo de la izquierda).",
     "inputSchema": _obj({"en": {**N, "description": "solo el hueco de ese segundo (opcional; si no, todos)"}})},
    {"name": "ir_a",
     "description": "Mueve el cabezal a un segundo de la línea de tiempo.",
     "inputSchema": _obj({"segundo": N}, ["segundo"])},
    {"name": "captura",
     "description": "Imagen de cómo se ve el video en un segundo (con textos y subtítulos), para revisar el resultado.",
     "inputSchema": _obj({"segundo": {**N, "description": "por defecto, el cabezal"}})},
    {"name": "deshacer",
     "description": "Deshace los últimos cambios (como Ctrl+Z).",
     "inputSchema": _obj({"pasos": {**I, "description": "cuántos (por defecto 1)"}})},
    {"name": "rehacer",
     "description": "Rehace lo deshecho (como Ctrl+Y).",
     "inputSchema": _obj({"pasos": I})},
    {"name": "guardar",
     "description": "Guarda el proyecto (en su archivo; si no tiene, pide una ruta .eia nueva: nunca pisa otro archivo).",
     "inputSchema": _obj({"ruta": {**S, "description": "solo si el proyecto aún no tiene archivo"}})},
    {"name": "exportar",
     "description": "Exporta el video en segundo plano para «youtube», «tiktok» o «windows». Se guarda en la carpeta "
                    "de exportados con un nombre nuevo (no pisa nada). Mira «estado» para el progreso.",
     "inputSchema": _obj({"destino": {"type": "string", "enum": ["youtube", "tiktok", "windows"]},
                          "nombre": {**S, "description": "nombre del archivo (opcional)"}}, ["destino"])},
]

NAMES = {t["name"] for t in TOOLS}
