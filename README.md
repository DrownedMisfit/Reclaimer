<p align="center"><img src="editoria/assets/reclaimer_oscuro_512.png" width="200" alt="Reclaimer"></p>

<h1 align="center">Reclaimer</h1>

<p align="center">
Editor de video gratuito para Windows con un asistente de IA que <b>propone</b> y tú decides.<br>
Videos de YouTube, Shorts y edits musicales. Todo funciona en tu PC: sin cuentas, sin nube, sin marcas de agua.
</p>

<p align="center"><a href="https://ko-fi.com/pigmeofurtivoyt"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Apóyame en Ko-fi"></a><br><sub>Es gratis. Si te sirve, puedes invitarme un café ☕</sub></p>

---

## Qué hace

- **Edición como en DaVinci Resolve**: páginas abajo, Inspector a la derecha, línea de tiempo con pistas,
  recortes, fundidos con tiradores, fotogramas clave, capas de ajuste, color y mezcla de audio.
- **Limpieza de la voz**: quita silencios, muletillas y tomas repetidas, con una vista previa antes de cortar.
  Ecualizador, reducción de ruido y voz separada del juego en grabaciones de OBS.
- **Subtítulos automáticos** (faster-whisper, local) y edición del video **desde el texto**: tachas una frase y se
  corta del video. Clic derecho en una palabra para corregirla.
- **Edits musicales automáticos**: cortes al ritmo de la canción, sin repetir escenas, con efectos variados y
  vistas previas de cada efecto.
- **Shorts**: encuadre vertical que sigue la acción, subtítulos grandes y elección de tramos.
- **Taller de miniaturas** integrado: propuestas a partir de tus imágenes, texto de impacto, recorte del
  personaje con IA, deformar en perspectiva y un buscador de PNG con fondo transparente.
- **Buscar momentos** en tu biblioteca por lo que se ve (texto, siluetas, imágenes de ejemplo).
- **Guía paso a paso (F1)** y clic derecho en cualquier botón → «❓ ¿Qué hace esto?».

Todo lo que hace la IA se puede deshacer con Ctrl+Z.

## Instalación (Windows 10 / 11)

1. Instala **Python 3.12** y **FFmpeg** (en una terminal):
   ```
   winget install Python.Python.3.12
   winget install Gyan.FFmpeg
   ```
2. Descarga este repositorio (botón verde **Code → Download ZIP**) y descomprímelo.
3. Doble clic en **`INSTALAR.bat`** (solo la primera vez; tarda unos minutos).
4. Doble clic en **`INICIAR.bat`** para abrir Reclaimer.

Opcional: **`motor_ia/INSTALAR_MOTOR_IA.bat`** instala el motor de IA avanzada (separar voz y música, recortar
personajes, etc.). Ocupa varios GB y funciona mejor con una tarjeta gráfica.

El manual completo está en **[MANUAL.md](MANUAL.md)**.

## Licencia

Reclaimer es software libre bajo la **[GNU GPL v3](LICENSE)**: puedes usarlo, estudiarlo, modificarlo y
compartirlo; si distribuyes una versión modificada, tiene que seguir siendo libre y con su código.

Incluye o descarga material de terceros con sus propias licencias:

| Qué | Licencia |
|---|---|
| Letra Anton (`editoria/assets/fuentes`) | SIL Open Font License 1.1 |
| Diccionarios de español e inglés (`editoria/assets/diccionarios`) | ver los archivos de licencia de esa carpeta |
| PySide6 (Qt) | LGPL v3 |
| faster-whisper | MIT |
| Modelo IS-Net para recortar (se descarga al usarlo) | Apache 2.0 |
| FFmpeg (se instala aparte) | LGPL / GPL |
