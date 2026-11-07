"""
📖 Guía de Reclaimer: un instructivo paso a paso DENTRO del programa.

Cada lección tiene pasos. En cada paso la guía:
  · te lleva a la opción (abre su panel o su pestaña si hace falta),
  · la rodea con un recuadro naranja tenue que NO estorba (los clics pasan a través),
  · y muestra una imagen real de esa opción (capturada del propio programa: siempre al día).

Las explicaciones largas de cada botón siguen en «❓ ¿Qué hace esto?» (clic derecho): aquí solo
se cuenta CÓMO hacer cada cosa, en orden.

Un paso apunta a su opción con un texto:
  "w:library.btn_files"   atributo de la ventana principal (también docks.media, page_buttons.thumb…)
  "ed:canvas"             atributo del taller de miniaturas (la guía lo abre si hace falta)
  "menu:IA"               un menú de la barra de arriba
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDockWidget, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenuBar, QPushButton, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

ORANGE = QColor(232, 116, 47)

# (id, título, palabras para el buscador, [(texto, objetivo, acción previa o None)])
LESSONS: list[tuple[str, str, str, list[tuple[str, str, str | None]]]] = [
    ("inicio", "👋 Primeros pasos", "empezar importar montar exportar ayuda básico", [
        ("<b>Importa tu material.</b> Pulsa «＋ Archivos» o «＋ Carpeta» y elige tu narración y tus clips. "
         "También puedes arrastrarlos desde el Explorador de Windows a este panel.", "w:library.btn_files", None),
        ("<b>Monta.</b> Arrastra un clip de Medios a la línea de tiempo, o haz <b>doble clic</b> en él y se "
         "coloca en el cabezal.", "w:timeline", None),
        ("<b>Mira cómo va.</b> <b>Espacio</b> reproduce o pausa; <b>← →</b> avanzan fotograma a fotograma.",
         "w:preview.btn_play", None),
        ("<b>Exporta.</b> «🚀 Entrega» (o <b>Ctrl+E</b>) abre la exportación con los ajustes para YouTube.",
         "w:page_buttons.deliver", None),
        ("<b>¿Dudas con un botón?</b> Haz <b>clic derecho</b> sobre cualquier botón o sección → «❓ ¿Qué hace "
         "esto?» y te lo explica.", "w:preview", None),
    ]),
    ("cortar", "✂ Cortar y recortar clips", "cortar dividir recortar borrar hueco cuchilla imán", [
        ("<b>Dividir:</b> pon el cabezal donde quieras cortar y pulsa <b>S</b>. O usa la cuchilla (<b>B</b>) y "
         "haz clic sobre el clip.", "w:tool_blade", None),
        ("<b>Recortar:</b> arrastra el <b>borde</b> de un clip. <b>Mover:</b> arrástralo desde el centro. "
         "<b>Supr</b> lo elimina y <b>Mayús+Supr</b> lo elimina cerrando el hueco. Un hueco también se "
         "selecciona con un clic y se borra con Supr.", "w:timeline", None),
        ("<b>Imán (N):</b> los clips se pegan a otros clips, al cabezal y a los marcadores.", "w:tool_snap", None),
        ("<b>Imagen y sonido juntos:</b> con 🔗 activo se mueven y cortan juntos. <b>Alt+clic</b> elige solo "
         "uno de los dos.", "w:tool_link", None),
    ]),
    ("jkl", "⏯ Reproducir con J/K/L y marcar un tramo (I/O)", "jkl reproducir rápido atrás entrada salida tramo bucle in out",
     [
         ("<b>J / K / L</b> (como en Resolve): <b>L</b> reproduce hacia delante, <b>J</b> hacia atrás y <b>K</b> "
          "para. Pulsa L o J otra vez para ir a 2×, 4× u 8×.", "menu:Reproducción", None),
         ("<b>I</b> marca la <b>entrada</b> y <b>O</b> la <b>salida</b> de un tramo: se ve como una banda en la "
          "regla. Mayús+I / Mayús+O saltan a ellas y <b>Alt+X</b> las quita.", "w:timeline", None),
         ("Con el tramo marcado: <b>Alt+/</b> lo reproduce, <b>🔁</b> (Ctrl+/) lo repite en bucle, Editar → «Quitar "
          "el tramo marcado» lo borra cerrando el hueco, y al exportar puedes sacar <b>solo ese tramo</b>.",
          "w:preview.btn_loop", None),
     ]),
    ("velocidad", "🐢 Velocidad, reversa y congelar imagen", "velocidad lento rápido cámara lenta reversa atrás congelar freeze",
     [
         ("Selecciona un clip y pulsa <b>R</b>: en el Inspector, «Velocidad» (50 % = cámara lenta, 200 % = el "
          "doble de rápido). Su sonido cambia igual, sin voz de ardilla.", "w:inspector.speed_box", None),
         ("<b>◀ Hacia atrás</b> pone el clip en reversa. «Mover lo que viene detrás» evita tapar o dejar "
          "huecos.", "w:inspector.reverse", None),
         ("<b>Mayús+R</b> congela la imagen desde el cabezal hasta el final del clip (el sonido sigue). En la "
          "línea de tiempo verás «❄», «50%» o «◀» en el clip.", "w:inspector.btn_freeze", None),
     ]),
    ("trans", "⧉ Transiciones entre clips", "transición transiciones disolver fundido barrido latigazo zoom corte",
     [
         ("En <b>Efectos → ⧉ Transiciones</b> elige una (disolver, fundido a negro, latigazo, zoom…) y su "
          "duración. <b>Doble clic</b> la pone en el corte del clip seleccionado o en el más cercano al cabezal.",
          "w:effects.trans_list", None),
         ("También con <b>clic derecho</b> sobre un clip → «⧉ Transición», o <b>Alt+T</b> (disolver). En la línea "
          "de tiempo aparece una pajarita sobre el corte.", "w:timeline", None),
         ("El visor la muestra como un fundido. <b>«▶ Ver la transición»</b> prepara en unos segundos cómo queda "
          "exactamente.", "w:effects.b_view", None),
     ]),
    ("recortes", "⇿ Recortes avanzados (ripple, roll, slip, slide)", "recortar ripple roll slip slide mover corte trim",
     [
         ("<b>⇿ Recorte</b> (Mayús+T), como el modo Trim de Resolve. Arrastrar un <b>borde</b> = <b>ripple</b>: "
          "el clip cambia de largo y lo de detrás se mueve (sin huecos). Con la herramienta normal: "
          "<b>Ctrl+borde</b>.", "w:tool_trim", None),
         ("<b>Mayús+borde</b> en un corte = <b>roll</b>: mueve el corte entre dos clips. Arrastrar el <b>centro</b> = "
          "<b>slip</b>: el clip enseña otra parte del video sin moverse. <b>Mayús+centro</b> = <b>slide</b>: se "
          "desliza entre sus vecinos.", "w:timeline", None),
     ]),
    ("copiar", "📋 Copiar, pegar y repetir ajustes", "copiar pegar cortar atributos repetir ajustes efectos",
     [
         ("<b>Ctrl+C</b> copia los clips seleccionados (con su sonido), <b>Ctrl+X</b> los corta y <b>Ctrl+V</b> los "
          "pega en el cabezal, sin tapar nada (si su pista está ocupada, van a otra).", "menu:Editar", None),
         ("<b>Alt+V · Pegar atributos</b>: copia un clip que te guste y pega solo sus <b>ajustes</b> (efectos, zoom, "
          "volumen y ecualizador, velocidad, transición) en otros clips.", "w:timeline", None),
     ]),
    ("vumetros", "🔊 Solo de pista y vúmetros", "solo pista vumetro nivel volumen saturar escuchar sonido",
     [
         ("En una pista de audio, <b>S</b> = <b>solo</b> (solo suenan las pistas con S) y <b>M</b> = silenciar. "
          "La barrita de color a la derecha de cada pista es su nivel.", "w:timeline", None),
         ("El <b>medidor</b> del visor muestra el nivel total en dB: verde bien, amarillo alto, rojo = cerca de "
          "saturar.", "w:preview.meter", None),
     ]),
    ("color", "🎨 Color del clip y gráficas", "color exposición contraste saturación lut temperatura scopes gráficas histograma",
     [
         ("Selecciona un clip → Inspector → pestaña <b>Color</b>: exposición, contraste, saturación, temperatura, "
          "tinte, sombras y luces; <b>✨ Color automático</b>; <b>🎨 LUT (.cube)</b>; y «👁 Ver sin corrección» para "
          "comparar.", "w:inspector.color_box", None),
         ("El panel <b>📊 Gráficas</b> mide la imagen: forma de onda, desfile RGB, histograma y vectorscopio, con "
          "avisos si algo está quemado o muy oscuro.", "w:docks.scopes", None),
         ("Para repetir el color en otros clips: <b>Ctrl+C</b> en este y <b>Alt+V</b> en los otros → «Color».",
          "w:timeline", None),
     ]),
    ("letra", "🔠 Letra más grande", "letra grande pequeña tamaño fuente texto leer zoom accesibilidad",
     [
         ("Botón <b>«🔠 Letra»</b> arriba a la derecha (o Ventana → «🔠 Tamaño de letra…»). <b>Paneles, menús y ventanas</b> agranda todo "
          "lo que no es la línea de tiempo; <b>Global</b> lo agranda todo, también la línea de tiempo. Se ve al "
          "momento y se recuerda.", "w:btn_font", None),
     ]),
    ("silencio", "✂ Eliminar silencio (como en Resolve)", "silencio silencios callado pausa umbral resolve cortar audio",
     [
         ("En la barra de encima del visor: <b>«✂ Eliminar silencio»</b> (o Ctrl+Mayús+Supr). Selecciona antes los "
          "clips (si no, usa la narración).", "w:preview.quick.silence", None),
         ("Ajusta <b>umbral</b>, <b>antes del inicio</b>, <b>después del final</b> y <b>mínimo a eliminar</b> (o elige "
          "uno de tus ajustes guardados): lo que se quitará se marca en <b>naranja</b> en la línea de tiempo. "
          "«Eliminar» lo corta todo de una vez (Ctrl+Z lo deshace).", "w:timeline", None),
     ]),
    ("huecos", "⇤ Quitar espacios vacíos (huecos) entre clips", "hueco huecos espacio vacio vacios audio cerrar juntar",
     [
         ("Un <b>hueco</b> es el espacio vacío entre dos clips de una pista (de video <b>o de audio</b>), p. ej. "
          "después de cortar y borrar unos segundos. <b>Clic</b> en el hueco lo marca y <b>Supr</b> lo elimina: lo "
          "de detrás se acerca (y su imagen o sonido vinculado también).", "w:timeline", None),
         ("Para quitarlos todos de una vez: menú <b>Timeline → «⇤ Eliminar huecos»</b> → <b>en todas las pistas de "
          "audio</b>, de video, en todas, o solo en la pista del clip elegido. También con clic derecho en el nombre "
          "de la pista.", "menu:Timeline", None),
     ]),
    ("paneles", "🗂 Acomodar los paneles", "paneles ventana mover acoplar distribución", [
        ("Arrastra un panel por su <b>pestaña o su título</b> a otro sitio: a un lado, junto a la línea de "
         "tiempo o encima de otro (se juntan en pestañas). Doble clic en el título lo saca o lo devuelve.",
         "w:docks.media", None),
        ("Menú <b>Ventana</b>: abre o cierra paneles y «Restablecer la distribución de paneles» lo deja como "
         "al principio.", "menu:Ventana", None),
    ]),
    ("fluidez", "⚡ Editar con fluidez (baja resolución)", "lento pesado fluido proxy resolución calidad cuarto",
     [
         ("Si la reproducción va a tirones, elige <b>«Media»</b> o <b>«Un cuarto»</b> aquí. Se crean copias "
          "ligeras de tus videos en segundo plano. Al exportar se usan siempre los originales.",
          "w:preview.quality", None),
         ("Lo mismo está en el menú <b>Reproducción → Resolución de la línea de tiempo</b>. Se recuerda para "
          "la próxima vez.", "menu:Reproducción", None),
     ]),
    ("voz", "🎙 Limpiar la narración", "voz silencios muletillas transcribir limpieza tachar resumen tomas", [
        ("Pulsa <b>«🎙 Transcribir y analizar»</b>. La IA escribe lo que dices y busca silencios, "
         "respiraciones, muletillas y tomas repetidas. Con <b>«🔁 Escucha literal»</b> (marcada) no se escapa ninguna "
         "toma repetida aunque Whisper la haya escrito una sola vez (tarda más).", "w:voice.btn_transcribe", None),
        ("<b>Automático</b>: en «⚡ Limpieza automática» marca qué quitar (muletillas, repeticiones, tomas repetidas "
         "—la IA se queda con la mejor—, silencios) y pulsa <b>«⚡ Limpiar automáticamente»</b>. Puedes hacer que lo "
         "haga solo al terminar de transcribir.", "w:voice.btn_auto_clean", None),
        ("<b>Manual</b>: revisa las sugerencias una por una: <b>▶ Escuchar</b>, <b>✓ Aplicar</b> o <b>✗ Ignorar</b>. "
         "En una toma repetida, ⭐ marca la que recomienda la IA. «↺ Restaurar» devuelve un corte.",
         "w:voice.btn_apply", None),
        ("En <b>Texto</b> ves lo que dices: clic en una palabra = ir a ese momento; doble clic = corregirla.",
         "w:transcript", None),
        ("<b>Editar con el texto</b>: lo que se va a quitar sale <b>tachado en rojo</b>. Clic en lo tachado = se "
         "queda; selecciona texto y pulsa <b>Supr</b> para tacharlo tú. Luego <b>«✂ Cortar lo tachado»</b>.",
         "w:transcript.btn_cut", None),
        ("<b>📋 Resumen</b>: solo lo que se puede quitar — frases que se repiten, se medio repiten o suenan parecido "
         "(con lo que dijiste después), muletillas como «¿no?» agrupadas… Casilla marcada = se quita.",
         "w:transcript.summary", None),
    ]),
    ("subs", "💬 Subtítulos", "subtítulos srt karaoke estilo", [
        ("Activa los <b>subtítulos dentro del video</b> y elige un estilo (YouTube clásico, Shorts dinámico, "
         "Karaoke…). Siguen a la voz aunque cortes.", "w:subtitles.enabled", None),
        ("Para subirlos aparte a YouTube: <b>«Exportar .srt»</b>.", "w:transcript.btn_srt", None),
    ]),
    ("auto", "✨ Primera versión automática", "automático autoedición primera versión ia", [
        ("En el panel <b>IA ✨</b>, la tarjeta <b>«✨ Autoedición»</b> (o "
         "<b>Ctrl+Mayús+A</b>): eliges tu narración y la IA monta el video casi terminado.",
         "w:docks.ai", None),
        ("Todo queda como clips normales: cámbialos a tu gusto o deshazlo entero con <b>Ctrl+Z</b>.",
         "w:timeline", None),
    ]),
    ("entender", "🔬 Que la IA conozca tus clips", "entender biblioteca personajes nombres reconocer", [
        ("<b>«🔬 Entender mi biblioteca a fondo»</b>: la IA revisa cada segundo de tus videos y aprende quién y "
         "qué aparece. Ponle a tus imágenes nombres claros («jefe maestro.png»).",
         "w:ai_panel.btn_understand", None),
    ]),
    ("momentos", "🔎 Encontrar un momento concreto", "buscar momento escena aparece imagen referencia", [
        ("<b>«🔎 Buscar momentos»</b> (Ctrl+Mayús+F): describe lo que buscas o dale una imagen de referencia.",
         "w:ai_panel.btn_moments", None),
        ("Cada resultado es una aparición con su inicio y su fin: <b>Insertar</b>, <b>Reemplazar</b> el clip "
         "elegido o <b>Añadir después</b>.", "w:moments", None),
        ("<b>Enséñale qué buscas</b>: en la esquina de cada resultado (tus videos o internet), <b>✓</b> = «aquí está» y "
         "<b>✗</b> = «no es». Con ✓ busca más momentos parecidos; con ✗ aparta los parecidos. La tarjeta <b>«🤔 ¿Es "
         "esto?»</b> te pregunta por lo que más le ayuda a aprender. Se recuerda, y si es un nombre que la IA conoce "
         "(«Jefe Maestro»), también lo usa el B-roll automático.", "w:moments.grid", None),
        ("<b>Imágenes de internet</b>: en «Buscar en» elige 🌐 Internet. La IA esconde las que no se parecen a lo que "
         "pides. En la esquina de cada imagen: <b>✓</b> = «esta es» (suben las parecidas) y <b>✗</b> = «no es» (se "
         "quita, y también las casi iguales). <b>«✨ Buscar más como las ✓»</b> trae más. Se recuerda para la próxima.",
         "w:moments.grid", None),
    ]),
    ("edit", "🎵 Edit musical", "edit música ritmo beats drop vertical phonk velocity blanco negro estilo", [
        ("Pestaña <b>IA ✨ → «🎵 Edit musical»</b> (<b>Ctrl+M</b>): eliges la canción, el <b>estilo</b> "
         "(Agresivo / Intenso, Épico en blanco y negro, Hype gaming, Cinemático…), la duración (30/45/60 s) y tus clips.",
         "w:docks.ai", None),
        ("La IA escucha el bombo, la caja, la subida y el drop: los cortes se aceleran antes del drop, llega "
         "el golpe y luego van al ritmo. Cada efecto (velocity, temblor, glitch, barras de cine…) se puede "
         "quitar o poner en la ventana.", "w:docks.ai", None),
    ]),
    ("efectos", "🎆 Efectos", "efectos sonido whoosh blanco negro viñeta destello fundido", [
        ("En <b>Efectos</b>: clic = escuchar un sonido, doble clic = ponerlo en el cabezal. Los efectos de "
         "imagen se aplican a los clips seleccionados.", "w:docks.effects", None),
        ("Los efectos del clip (destello, fundidos, temblor) se ajustan en el <b>Inspector</b>.",
         "w:inspector.effects_box", None),
    ]),
    ("zoom", "🎯 Zoom y seguir a un personaje", "zoom encuadre clave seguir tracking", [
        ("Selecciona un clip y arrastra en el visor para encuadrar; la <b>rueda</b> hace zoom. "
         "<b>«◆ Clave aquí»</b> anima el zoom entre claves.", "w:inspector.frame_box", None),
        ("<b>«🎯 Seguir personaje u objeto…»</b>: marcas algo y el zoom lo acompaña.", "w:inspector.btn_track",
         None),
    ]),
    ("audio", "🎚 Sonido", "audio volumen ecualizador música ducking lufs", [
        ("Con un clip de audio seleccionado, el <b>Inspector</b> muestra su volumen, balance y "
         "<b>ecualizador</b>. «🎧 Escuchar con EQ» repite unos segundos mientras ajustas.",
         "w:inspector.btn_monitor", None),
        ("<b>«🎚 Audio»</b> abre el audio inteligente: mejorar la voz, bajar la música cuando hablas y "
         "volumen final para YouTube.", "w:page_buttons.fairlight", None),
    ]),
    ("aprendizaje", "◈ Aprendizaje de mi estilo", "aprender estilo perfil preferencias privacidad confianza", [
        ("Arriba a la derecha, <b>«◈ Aprendizaje IA»</b>: actívalo si quieres que la IA aprenda cómo editas "
         "(apagado de fábrica). Solo mira lo que haces dentro del editor y se detiene al cerrar.",
         "w:btn_learning", None),
    ]),
    ("mis_efectos", "⭐ Mis efectos para la IA", "efectos favoritos ia propone aprende palomita destello whoosh "
     "sonido transicion automatico", [
        ("En <b>Efectos → ⭐ Mis efectos para la IA</b> elige tus efectos favoritos (o clic derecho en cualquier "
         "efecto → ⭐) y pulsa «◈ Proponer dónde ponerlos».", "w:effects.b_propose", None),
        ("Cada propuesta sale en la lista y como rombo dorado en la línea de tiempo: <b>✓</b> la pone, <b>✗</b> la "
         "descarta, <b>🎯</b> la pone en los clips que elijas. Aprende de cada respuesta.", "w:effects.prop_tree", None),
    ]),
    ("ejemplo", "🎯 Buscar con un ejemplo", "ejemplo buscar personaje objeto recuadro aprender palomita referencia", [
        ("En <b>🔎 Momentos</b>, «🎯 Ejemplo» usa el clip seleccionado en la línea de tiempo (o clic derecho en un "
         "clip o en Medios → «🎯 Usar como ejemplo»): eliges el momento, dibujas un recuadro si quieres y "
         "escribes qué es.", "w:moments.b_example", None),
    ]),
    ("ritmo", "🥁 Ritmo de la música", "ritmo golpes beats compás bombo drop imán música canción tempo bpm", [
        ("Pon tu canción en una pista de audio (si quieres, renómbrala «Música»: baja sola cuando hablas): se escucha sola y aparecen sus golpes (rayitas), los "
         "inicios de compás (más largas), los golpes fuertes (puntos naranjas) y el <b>drop</b> (línea roja).",
         "w:timeline", None),
        ("Con el <b>imán</b> (N) los clips y la cuchilla se pegan a esos golpes: así cortas a ritmo a mano. "
         "Clic derecho en la canción → «📍 Poner marcadores en el drop y en cada parte».", "w:tool_snap", None),
    ]),
    ("miniatura", "🖼 Hacer la miniatura", "miniatura thumbnail portada", [
        ("<b>«🖼 Miniatura»</b> abre el taller de miniaturas (YouTube o Shorts).", "w:page_buttons.thumb", None),
        ("<b>✨ Propuestas:</b> elige una frase corta y pulsa «Crear 3 propuestas». «🎨 Mi estilo…» hace que se "
         "parezcan a tus miniaturas.", "ed:left_tabs", "open_thumbnail"),
        ("<b>Lienzo:</b> clic = elegir; arrastra para mover; esquinas = tamaño; círculo = girar. A la derecha, "
         "las opciones de lo elegido (en una imagen: <b>✂ Quitar fondo</b>).", "ed:canvas", "open_thumbnail"),
        ("<b>⚕ Analizar</b> te dice si se lee en pequeño; <b>⬇ Exportar</b> la guarda por debajo de 2 MB.",
         "ed:fmt", "open_thumbnail"),
    ]),
    ("final", "🚀 Revisar y exportar", "exportar revisar render entrega errores", [
        ("Pestaña <b>IA ✨ → «⚕ Revisión»</b> (<b>Ctrl+R</b>): pantallas negras, silencios, audio "
         "saturado, clips repetidos…", "w:docks.ai", None),
        ("<b>«🚀 Entrega»</b> (<b>Ctrl+E</b>): elige el preset y exporta.", "w:page_buttons.deliver", None),
    ]),
    ("mejoras2", "🛠 Ruido, estabilizar, cortes de escena y cámara lenta suave",
     "ruido estabilizar temblor escena cortes trailer camara lenta suave rampa speed ramp warp",
     [
         ("Inspector → <b>🛠 Mejorar imagen</b>: <b>reducir ruido</b>, <b>estabilizar</b> (analiza el temblor unos "
          "segundos) y <b>✂ Detectar cortes de escena</b> para cortar un tráiler o una cinemática en sus planos.",
          "w:inspector.enhance_box", None),
         ("En <b>Velocidad</b>: <b>✨ Cámara lenta suave</b> (inventa fotogramas al exportar) y <b>📈 Rampa de "
          "velocidad</b> (rápido → lento → rápido…). <b>▶ Ver cómo queda</b> prepara unos segundos exactos.",
          "w:inspector.speed_box", None),
     ]),
    ("curvas", "〰 Curvas de volumen y opacidad, y modos de fusión", "curvas volumen opacidad fusion pantalla multiplicar keyframes puntos",
     [
         ("Activa <b>〰 Curvas</b> (Mayús+C). En los clips de audio verás la línea del <b>volumen</b> y en los de video "
          "la de <b>opacidad</b>: clic en la línea = punto nuevo, arrastrar = moverlo, clic derecho = borrarlo, "
          "Mayús+arrastrar = subir o bajar toda.", "w:tool_curves", None),
         ("Inspector → <b>Video</b>: <b>opacidad</b> y <b>modo de fusión</b> (pantalla para destellos y luces, "
          "multiplicar para sombras y texturas…).", "w:inspector.blend_box", None),
     ]),
    ("cola", "🚀 Cola de exportación", "exportar cola varias render queue audio 4k tramo",
     [
         ("En <b>Exportar</b>, <b>«➕ Añadir a la cola»</b> guarda esa exportación (con el proyecto tal como está). "
          "<b>Archivo → 🚀 Cola de exportación</b> (Ctrl+Mayús+E) las hace todas seguidas; también puedes añadir "
          "rápido «solo audio», «tramo marcado» o «4K».", "menu:Archivo", None),
     ]),
    ("cache", "✧ Espacio en disco y diagnóstico", "cache espacio disco limpiar borrar diagnostico error falla informe lento",
     [
         ("Menú <b>Ayuda → «✧ Caché y diagnóstico…»</b>: cuánto ocupa lo que guarda Reclaimer y un botón para borrar lo "
          "que se rehace solo (copias ligeras, formas de onda…). Lo que usan tus miniaturas o proyectos no se borra. "
          "En «⚕ Diagnóstico» ves si FFmpeg y la tarjeta gráfica funcionan, el espacio libre, archivos que faltan, "
          "y puedes copiar un informe si algo falla.", "menu:Ayuda", None),
     ]),
    ("atajos", "⌨ Atajos de teclado", "atajos teclado teclas shortcuts", [
        ("Aquí tienes <b>todos los atajos de teclado</b>.", "menu:Ayuda", "_show_shortcuts"),
    ]),
]


def _plain(text: str) -> str:
    """Minúsculas y sin tildes (para buscar «subtitulos» y encontrar «subtítulos»)."""
    import unicodedata
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _resolve_attr(root, path: str):
    obj = root
    for part in path.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
    return obj


def reveal(widget: QWidget):
    """Hace visible un control: abre su panel y las pestañas que lo contienen."""
    chain = []
    w = widget
    while w is not None:
        chain.append(w)
        w = w.parentWidget()
    for i, w in enumerate(chain):
        if isinstance(w, QDockWidget):
            w.show()
            w.raise_()
        elif isinstance(w, (QTabWidget, QStackedWidget)) and i >= 1:
            # el hijo directo de la pestaña que contiene al control
            for c in reversed(chain[:i]):
                idx = w.indexOf(c)
                if idx >= 0:
                    w.setCurrentIndex(idx)
                    break
    for w in chain:
        if isinstance(w, QScrollArea) and w.widget() is not None and w.widget().isAncestorOf(widget):
            w.ensureWidgetVisible(widget, 20, 20)


class Highlighter(QWidget):
    """Recuadro naranja tenue alrededor de una opción. Los clics pasan a través (no estorba)."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setObjectName("guide_highlighter")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.target = None          # QWidget o (QMenuBar, QAction)
        self.alpha = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(2400)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._pulse)
        self._follow = QTimer(self)
        self._follow.setInterval(150)
        self._follow.timeout.connect(self._update)
        self._fade = QTimer(self)
        self._fade.setSingleShot(True)
        self._fade.timeout.connect(self.clear)
        window.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget() and ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def _pulse(self, v):
        import math
        # dos latidos suaves y luego queda tenue
        self.alpha = 0.55 + 0.45 * abs(math.sin(v * math.pi * 2)) if v < 1 else 0.55
        self._repaint_ring()

    def _repaint_ring(self):
        """⚡ Solo se repinta el contorno (donde está ahora y donde estaba). Esta capa ocupa TODA la ventana: un
        update() suyo hacía redibujar el programa entero 7 veces por segundo mientras se veía un consejo."""
        from PySide6.QtGui import QRegion

        def _banda(rc):      # solo la franja donde va el contorno (el interior es transparente)
            if rc.isEmpty():
                return QRegion()
            return QRegion(rc).subtracted(QRegion(rc.adjusted(16, 16, -16, -16)))
        r = self.target_rect()
        now = r.adjusted(-12, -12, 12, 12) if r is not None else QRect()
        old = self.__dict__.get("_ring", QRect())
        self._ring = now
        reg = _banda(now).united(_banda(old))
        if not reg.isEmpty():
            self.update(reg)

    def show_on(self, target, seconds: float = 14.0):
        self.target = target
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.start()
        self._follow.start()
        self._fade.start(int(seconds * 1000))

    def clear(self):
        self.target = None
        self._follow.stop()
        self.hide()

    def target_rect(self) -> QRect | None:
        t = self.target
        win = self.parentWidget()
        if t is None:
            return None
        if isinstance(t, tuple):
            bar, act = t
            r = bar.actionGeometry(act)
            if r.isEmpty():
                return None
            return QRect(bar.mapTo(win, r.topLeft()), r.size())
        try:
            if not t.isVisible():
                return None
            vis = t.visibleRegion().boundingRect()       # solo la parte que se ve (no lo oculto por scroll)
            if vis.isEmpty():
                vis = t.rect()
            return QRect(t.mapTo(win, vis.topLeft()), vis.size())
        except RuntimeError:            # el control se destruyó
            return None

    def _update(self):
        sib = self.parentWidget().children() if self.parentWidget() else []
        if sib and sib[-1] is not self:          # solo si algo se le puso encima
            self.raise_()
        self._repaint_ring()

    def paintEvent(self, _e):
        r = self.target_rect()
        if r is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Solo un CONTORNO alrededor (nada de rellenar: lo de dentro se ve igual que siempre)
        rr = QRectF(r).adjusted(-4, -4, 4, 4).intersected(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        line = QColor(ORANGE)
        line.setAlphaF(0.9 * self.alpha)
        glow = QColor(ORANGE)
        glow.setAlphaF(0.22 * self.alpha)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(glow, 6))
        p.drawRoundedRect(rr.adjusted(-2, -2, 2, 2), 8, 8)
        p.setPen(QPen(line, 2))
        p.drawRoundedRect(rr, 7, 7)


def highlighter_of(window: QWidget) -> "Highlighter | None":
    return window.findChild(Highlighter, "guide_highlighter", Qt.FindDirectChildrenOnly)


class GuidePanel(QWidget):
    """Panel «📖 Guía»: lecciones con buscador, pasos con imagen real y «📍 Muéstrame»."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.lesson = None
        self.step = 0
        self._hl: list[Highlighter] = []
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        intro = QLabel("Elige qué quieres aprender. Te llevo a cada opción y la marco en <span style='color:"
                       "#e8742f'>naranja</span>.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 ¿Qué quieres hacer? (p. ej. «cortar», «subtítulos», «lento»)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setMaximumHeight(180)
        for lid, title, words, steps in LESSONS:
            it = QListWidgetItem(f"{title}   ({len(steps)} paso{'s' if len(steps) > 1 else ''})")
            it.setData(Qt.UserRole, lid)
            it.setData(Qt.UserRole + 1, _plain(title + " " + words))
            self.list.addItem(it)
        self.list.currentItemChanged.connect(lambda it, _p: it and self.open_lesson(it.data(Qt.UserRole)))
        lay.addWidget(self.list)

        self.card = QWidget()
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(0, 6, 0, 0)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        cl.addWidget(self.title)
        self.counter = QLabel()
        self.counter.setObjectName("dim")
        cl.addWidget(self.counter)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        cl.addWidget(self.text)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(60)
        self.image.setStyleSheet("border: 1px solid rgba(232,116,47,0.45); border-radius: 6px; padding: 4px;")
        self.image.setToolTip("Así se ve esta opción en tu pantalla")
        cl.addWidget(self.image)
        row = QHBoxLayout()
        self.b_prev = QPushButton("◀ Anterior")
        self.b_prev.clicked.connect(lambda: self.go(self.step - 1))
        self.b_show = QPushButton("📍 Muéstrame")
        self.b_show.setToolTip("Llevarme a esta opción y marcarla")
        self.b_show.clicked.connect(self.show_target)
        self.b_next = QPushButton("Siguiente ▶")
        self.b_next.setObjectName("primary")
        self.b_next.clicked.connect(lambda: self.go(self.step + 1))
        row.addWidget(self.b_prev)
        row.addWidget(self.b_show)
        row.addWidget(self.b_next)
        cl.addLayout(row)
        self.auto = QCheckBox("Marcar la opción al cambiar de paso")
        self.auto.setChecked(True)
        cl.addWidget(self.auto)
        lay.addWidget(self.card)
        lay.addStretch(1)
        self.card.hide()

    # ------------------------------------------------------------- lecciones
    def _filter(self, text: str):
        words = [w for w in _plain(text).split() if w]
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            hay = it.data(Qt.UserRole + 1)
            ok = all(w[:5] in hay for w in words)
            it.setHidden(not ok)
            if ok and first is None:
                first = it
        if words and first is not None and self.list.currentItem() is not first:
            self.list.setCurrentItem(first)

    def open_lesson(self, lid: str):
        self.lesson = next((L for L in LESSONS if L[0] == lid), None)
        if self.lesson is None:
            return
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == lid and self.list.currentRow() != i:
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)
        self.card.show()
        self.go(0)

    def go(self, i: int):
        if self.lesson is None:
            return
        steps = self.lesson[3]
        self.step = max(0, min(i, len(steps) - 1))
        text, _target, _do = steps[self.step]
        self.title.setText(self.lesson[1])
        self.counter.setText(f"Paso {self.step + 1} de {len(steps)}")
        self.text.setText(text)
        self.b_prev.setEnabled(self.step > 0)
        last = self.step == len(steps) - 1
        self.b_next.setText("✓ Terminar" if last else "Siguiente ▶")
        try:
            self.b_next.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.b_next.clicked.connect(self.finish if last else (lambda: self.go(self.step + 1)))
        if self.auto.isChecked():
            QTimer.singleShot(0, self.show_target)
        else:
            QTimer.singleShot(0, self._snapshot)

    def finish(self):
        self.clear()
        self.counter.setText("✓ ¡Lección terminada! Elige otra cuando quieras.")

    # ------------------------------------------------------------- objetivo
    def resolve(self, target: str, do: str | None = None):
        """De «w:…», «ed:…» o «menu:…» al control real (abriendo lo necesario)."""
        if do and do != "_show_shortcuts":
            fn = getattr(self.win, do, None)
            if callable(fn) and not (do == "open_thumbnail" and self._thumb_open()):
                fn()
        kind, _, path = target.partition(":")
        if kind in ("w", "menu") and getattr(self.win, "_thumb_page", None) is not None \
                and do != "open_thumbnail" and not path.startswith("page_buttons"):
            self.win.go_page("edit")              # 🖼 algo del editor: primero se sale de la página Miniatura
        if kind == "menu":
            bar: QMenuBar = self.win.menuBar()
            for act in bar.actions():
                if act.text().replace("&", "") == path:
                    return bar, act
            return None
        root = self.win if kind == "w" else getattr(self.win, "_thumb_editor", None)
        obj = _resolve_attr(root, path) if root is not None else None
        return obj if isinstance(obj, QWidget) else None

    def _thumb_open(self) -> bool:
        ed = getattr(self.win, "_thumb_editor", None)
        return ed is not None and ed.isVisible()

    def current(self):
        if self.lesson is None:
            return None, None
        _text, target, do = self.lesson[3][self.step]
        return target, do

    def show_target(self):
        target, do = self.current()
        if target is None:
            return
        obj = self.resolve(target, do)
        if obj is None:
            self.image.setText("<i>(Esta opción aparece cuando está disponible)</i>")
            return
        hint = None
        if isinstance(obj, QWidget):
            reveal(obj)
            if not obj.isVisibleTo(obj.window()):
                # Esta opción solo aparece con un clip seleccionado: se marca la línea de tiempo
                hint = "Selecciona un clip en la línea de tiempo y vuelve a pulsar «📍 Muéstrame»."
                obj = self.resolve("w:timeline")
            window = obj.window()
        else:
            window = obj[0].window()
        hl = highlighter_of(window)
        if hl is None:
            hl = Highlighter(window)
            self._hl.append(hl)
        for other in list(self._hl):
            if other is not hl:
                try:
                    other.clear()
                except RuntimeError:
                    self._hl.remove(other)
        # dejar que se abran los paneles/pestañas antes de marcar y capturar
        QTimer.singleShot(80, lambda: (hl.show_on(obj), self._snapshot(obj, hint)))
        if do == "_show_shortcuts":
            QTimer.singleShot(400, self.win._show_shortcuts)

    def _snapshot(self, obj=None, hint: str | None = None):
        """Imagen real de la opción (para reconocerla de un vistazo)."""
        if hint:
            self.image.setPixmap(QPixmap())
            self.image.setText(f"👉 {hint}")
            return
        if obj is None:
            target, _do = self.current()
            obj = self.resolve(target) if target else None
        pm = QPixmap()
        try:
            if isinstance(obj, QWidget) and obj.isVisible():
                pm = obj.grab()
            elif isinstance(obj, tuple):
                bar, act = obj
                r = bar.actionGeometry(act).adjusted(-30, -2, 120, 2).intersected(bar.rect())
                pm = bar.grab(r)
        except RuntimeError:
            pm = QPixmap()
        if pm.isNull():
            self.image.setPixmap(QPixmap())
            self.image.setText("<i>(abre esta opción para verla aquí)</i>")
            return
        w = max(120, self.width() - 40)
        pm = pm.scaled(min(w, pm.width()), min(170, pm.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image.setPixmap(pm)

    def clear(self):
        for hl in list(self._hl):
            try:
                hl.clear()
            except RuntimeError:        # su ventana ya se cerró
                self._hl.remove(hl)

