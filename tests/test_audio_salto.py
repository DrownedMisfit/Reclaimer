"""
🔊 Saltar mientras suena (clic en la línea de tiempo con la reproducción en marcha) no deja el audio mudo: la salida de
audio se para antes de arrancar otra vez (QAudioSink.start() sin stop() la dejaba en reposo hasta darle a Espacio).
Usa la tarjeta de sonido real a VOLUMEN 0 (no suena nada); si no hay tarjeta, se salta.
Ejecutar:  .venv/Scripts/python.exe tests/test_audio_salto.py <carpeta_salida>
"""
from __future__ import annotations

import os
import sys
import time

# 🔒 datos y caché de la prueba en una carpeta temporal (nunca en F:\Reclaimer\datos real; se borra al acabar). Los
#    modelos ya descargados se leen de datos\modelos (no se bajan otra vez).
def _aislar_datos():
    import atexit
    import shutil
    import tempfile
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmproot = os.path.join(raiz, "_pruebas_tmp")
    os.makedirs(tmproot, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reclaimer_aislada_", dir=tmproot)
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["EDITORIA_DATOS"] = os.path.join(tmp, "EditorIA")
    os.environ.setdefault("EDITORIA_MODELOS", os.path.join(raiz, "datos", "modelos"))


_aislar_datos()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402


def main():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    from editoria.core import live_mix as LM
    from editoria.ui import live_audio as LA
    w = LA._Worker(LM.Mixer(LM.Decoder()), False)
    w.init()
    if w.sink is None:
        print("(sin tarjeta de sonido: no se puede comprobar aquí)")
        print("TODO OK")
        return
    w.sink.setVolume(0.0)                         # (nunca suena)

    def esperar(s):
        t0 = time.time()
        while time.time() - t0 < s:
            app.processEvents()
            time.sleep(0.01)
    try:
        w.start(0.0)
        esperar(0.4)
        for i in range(3):                        # tres clics seguidos en la línea de tiempo mientras suena
            w.start(5.0 + i)
            esperar(0.3)
        u0 = w.sink.processedUSecs()
        esperar(0.6)
        u1 = w.sink.processedUSecs()
        estado = w.sink.state().name
        assert estado == "ActiveState" and u1 > u0 + 300000, (estado, u0, u1)
        print(f"✓ tras saltar 3 veces mientras suena, el audio sigue (estado {estado}, avanza {(u1 - u0) / 1e6:.2f} s)")
        # lo que suena va al compás del cabezal tras un salto (se compensa lo que tarda en arrancar)
        w.t_pedido = time.perf_counter()
        t_pedido = w.t_pedido
        w.pedidos = w.atendidos + 1
        w.start(20.0)
        esperar(0.5)
        esperado = 20.0 + (time.perf_counter() - t_pedido)
        desfase = abs(w.heard() - esperado)
        assert desfase < 0.2, (w.heard(), esperado)
        print(f"✓ tras el salto, lo que suena va con el cabezal (desfase {desfase * 1000:.0f} ms)")
        # varios arranques seguidos (scrub): solo cuenta el último
        w.pedidos = w.atendidos + 3
        for t in (30.0, 31.0, 32.0):
            w.start(t)
        assert w.t_start >= 32.0, w.t_start
        print("✓ varios arranques seguidos: se atiende solo el último (no se amontonan)")
    finally:
        w.stop()
    print("TODO OK")


if __name__ == "__main__":
    main()
