"""
Importar los atajos de DaVinci Resolve del usuario (Preferencias de Resolve → keyboard.preset.xml).

Resolve guarda la lista como QDataStream de Qt en hexadecimal: preset → [(acción, [secuencias de teclas])].
Cada tecla es un entero de Qt (código de tecla | modificadores). Aquí se lee (solo lectura) y se traduce a
«Ctrl+Mayús+X» para las acciones de Resolve que tienen equivalente en Reclaimer.
"""
from __future__ import annotations

import os
import re
import struct

PRESET = os.path.join(os.environ.get("APPDATA", ""), "Blackmagic Design", "DaVinci Resolve", "Preferences",
                      "keyboard.preset.xml")

# acción de Resolve → orden de Reclaimer (el texto exacto de su menú)
RESOLVE_TO_RECLAIMER = {
    "editCopy": "Copiar clips", "editCut": "Cortar clips", "editPaste": "Pegar en el cabezal",
    "editPasteAttributes": "Pegar atributos… (efectos, zoom, sonido, velocidad)",
    "editBladeRazor": "Dividir en el cabezal", "editBackspace": "Eliminar",
    "editDelete": "Eliminar y cerrar hueco", "editSelectAll": "Seleccionar todos los clips",
    "editPointer": "Herramienta de selección", "editBlade": "Herramienta cuchilla",
    "editTrim": "Herramienta de recorte avanzado (ripple, roll, slip, slide)",
    "editSnapping": "Imán (encajar) sí/no", "editLinkedSelection": "🔗 Selección vinculada (audio y video juntos)",
    "editAddTransition": "⧉ Poner transición (disolver) en el corte",
    "clipChangeClipSpeed": "Velocidad del clip…", "clipFreezeFrame": "Congelar la imagen desde el cabezal",
    "markMarkerAdd": "Añadir marcador", "markIn": "Marcar entrada", "markOut": "Marcar salida",
    "markResetInOut": "Quitar entrada y salida", "controlGotoIn": "Ir a la entrada",
    "controlGotoOut": "Ir a la salida", "controlPlayToggle": "Reproducir / pausar",
    "controlPlayReverse": "Hacia atrás (J: otra vez = más rápido)", "controlStop": "Parar (K)",
    "controlPlayForward": "Hacia delante (L: otra vez = más rápido)",
    "controlPlayAroundToPlayInToOut": "Reproducir de la entrada a la salida", "controlLoop": "Repetir en bucle",
    "controlStepReverse": "Fotograma anterior", "controlStepForward": "Fotograma siguiente",
    "controlTimelineStart": "Ir al inicio", "controlTimelineEnd": "Ir al final",
    "fileSaveProject": "Guardar", "fileSaveProjectAs": "Guardar como…", "fileImportMedia": "Importar archivos…",
    "fileCreateTimelineBackup": "Guardar nueva versión (v01, v02…)",
    "viewZoomSubZoomIn": "Acercar", "viewZoomSubZoomOut": "Alejar", "viewZoomSubZoomToFit": "Ajustar a la ventana",
}

_KEYS = {0x20: "Space", 0x01000000: "Esc", 0x01000001: "Tab", 0x01000003: "Backspace", 0x01000004: "Return",
         0x01000005: "Enter", 0x01000006: "Ins", 0x01000007: "Del", 0x01000010: "Home", 0x01000011: "End",
         0x01000012: "Left", 0x01000013: "Up", 0x01000014: "Right", 0x01000015: "Down", 0x01000016: "PgUp",
         0x01000017: "PgDown"}
_MODS = ((0x04000000, "Ctrl"), (0x08000000, "Alt"), (0x02000000, "Shift"), (0x10000000, "Meta"))


def key_text(code: int) -> str:
    """Entero de Qt (tecla | modificadores) → «Ctrl+Shift+X» (formato de QKeySequence)."""
    mods = [name for bit, name in _MODS if code & bit]
    k = code & 0x01FFFFFF
    if k in _KEYS:
        key = _KEYS[k]
    elif 0x01000030 <= k <= 0x01000052:
        key = f"F{k - 0x01000030 + 1}"
    elif 0x20 < k < 0x110000:
        key = chr(k).upper()
    else:
        return ""
    return "+".join(mods + [key])


def read_presets(path: str | None = None) -> dict[str, dict[str, list[str]]]:
    """{nombre del preset: {acción de Resolve: ["Ctrl+X", …]}}. Solo lectura."""
    with open(path or PRESET, encoding="utf-8") as f:
        xml = f.read()
    out: dict[str, dict[str, list[str]]] = {}
    for hexblob in re.findall(r"<PresetListBA>([0-9a-fA-F]+)</PresetListBA>", xml):
        b = bytes.fromhex(hexblob)
        pos = 0

        def u32():
            nonlocal pos
            v = struct.unpack(">I", b[pos:pos + 4])[0]
            pos += 4
            return v

        def qstr():
            nonlocal pos
            n = u32()
            if n == 0xFFFFFFFF:
                return ""
            s = b[pos:pos + n].decode("utf-16-be", errors="replace")
            pos += n
            return s
        n_presets = u32()
        u32()
        for _ in range(max(1, n_presets)):
            if pos >= len(b):
                break
            name = qstr()
            u32()                       # tamaño del bloque
            u32()
            n_actions = u32()
            acts: dict[str, list[str]] = {}
            for _a in range(n_actions):
                if pos >= len(b):
                    break
                action = qstr()
                seqs = []
                for _s in range(u32()):
                    keys = [key_text(u32()) for _k in range(u32())]
                    keys = [k for k in keys if k]
                    if keys:
                        seqs.append(", ".join(keys))
                acts[action] = seqs
            out[name] = acts
    return out


def plan(actions: dict, path: str | None = None) -> list[tuple[str, str, str, str]]:
    """Lo que cambiaría al traer tus atajos de Resolve: [(clave de la orden, nombre, atajo ahora, en Resolve)].
    actions = main_window.shortcut_actions ({"Menú/Orden": (QAction, atajo de fábrica)})."""
    from PySide6.QtGui import QKeySequence
    mine = mapped(path)
    out = []
    for key, (act, _default) in actions.items():
        name = key.split("/", 1)[1].replace("&", "")
        seq = mine.get(name)
        if not seq:
            continue
        now = act.shortcut().toString(QKeySequence.PortableText)
        out.append((key, name, now, QKeySequence(seq).toString(QKeySequence.PortableText)))
    return out


def mapped(path: str | None = None) -> dict[str, str]:
    """{acción de Reclaimer: atajo} con TUS atajos de Resolve (el primer preset con datos)."""
    presets = read_presets(path)
    if not presets:
        return {}
    acts = next(iter(presets.values()))
    out: dict[str, str] = {}
    for ra, mine in RESOLVE_TO_RECLAIMER.items():
        seqs = acts.get(ra) or []
        if seqs and mine not in out:
            out[mine] = seqs[0]
    return out
