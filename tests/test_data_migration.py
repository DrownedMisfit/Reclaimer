"""
Prueba de la mudanza de datos de C: (%LOCALAPPDATA%\\EditorIA) a la carpeta del programa (datos/): lo que solo está
en C: se mueve, lo ya copiado igual solo se quita de C:, y si los dos son distintos gana el más reciente.
Todo en carpetas temporales (en D:, junto al programa); no toca tus datos.
Ejecutar:  .venv/Scripts/python.exe tests/test_data_migration.py <carpeta_salida>
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ajustes  # noqa: E402,F401  (tus ajustes quedan como estaban; si se cuelga, dice dónde)


def main():
    tmp_root = os.path.join(ROOT, "_pruebas_tmp")
    os.makedirs(tmp_root, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="mudanza_", dir=tmp_root)
    try:
        os.environ.pop("EDITORIA_DATOS", None)
        os.environ["LOCALAPPDATA"] = os.path.join(tmp, "C_local")
        from pathlib import Path

        from editoria.core import paths
        paths.PROGRAM_DIR = Path(tmp) / "programa"
        old = Path(os.environ["LOCALAPPDATA"]) / "EditorIA"
        new = paths.app_data_dir()
        assert new == Path(tmp) / "programa" / "datos"

        def put(p: Path, text: str, mtime: float):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            os.utime(p, (mtime, mtime))
        now = time.time()
        put(old / "modelos" / "solo_en_c.bin", "modelo", now - 500)
        put(old / "igual.json", "mismo", now - 400)
        put(new / "igual.json", "mismo", now - 400)
        put(old / "c_mas_nuevo.json", "nuevo en C", now - 10)
        put(new / "c_mas_nuevo.json", "viejo en D", now - 300)
        put(old / "d_mas_nuevo.json", "viejo en C", now - 300)
        put(new / "d_mas_nuevo.json", "nuevo en D", now - 10)
        assert paths.old_data_dir() == old
        seen = []
        moved, failed = paths.migrate_old_data(lambda d, t, n: seen.append((d, t)))
        assert failed == 0 and moved == 4, (moved, failed)
        assert (new / "modelos" / "solo_en_c.bin").read_text(encoding="utf-8") == "modelo"
        assert (new / "igual.json").read_text(encoding="utf-8") == "mismo"
        assert (new / "c_mas_nuevo.json").read_text(encoding="utf-8") == "nuevo en C"
        assert (new / "d_mas_nuevo.json").read_text(encoding="utf-8") == "nuevo en D"
        assert not old.exists(), "la carpeta de C: queda vacía y se quita"
        assert paths.old_data_dir() is None, "solo una vez"
        assert seen and seen[-1][0] == seen[-1][1]
        print("✓ mudanza C: → datos/: mueve lo que falta, quita lo ya copiado, gana el más reciente, C: queda vacío")
        os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "pruebas")
        assert paths.app_data_dir() == Path(tmp) / "pruebas" and paths.old_data_dir() is None
        assert paths.temp_dir() == Path(tmp) / "pruebas" / "temporal" and paths.temp_dir().is_dir()
        print("✓ las pruebas usan su propia carpeta (EDITORIA_DATOS) y los temporales van en datos/temporal")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("TODO OK")


if __name__ == "__main__":
    main()
