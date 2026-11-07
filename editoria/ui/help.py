"""
Ayuda con clic derecho: «❓ ¿Qué hace esto?».

En lugar de llenar los paneles de textos explicativos, cada parte del programa tiene su
explicación aquí. Clic derecho sobre cualquier botón, casilla, sección o panel → aparece
un menú con «❓ ¿Qué hace esto?». En los campos de texto el menú normal (copiar, pegar…)
sigue estando, con la ayuda añadida al final.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                               QTextEdit, QWidget)

HELP: dict[str, tuple[str, str]] = {
    # ---------------------------------------------------------- general
    "biblioteca": ("Biblioteca", """
Aquí están todos tus archivos (narración, gameplay, cinemáticas, música, imágenes…).
<ul>
<li><b>＋ Archivos / ＋ Carpeta</b>: importa archivos o una carpeta entera (con subcarpetas). También puedes arrastrarlos desde el Explorador.</li>
<li>Se ordenan solos por el nombre de sus carpetas (Gameplay, Cinematics, Music…). Las subcarpetas (Combat, Marcus…) se vuelven etiquetas.</li>
<li><b>Doble clic</b> en un archivo = se añade a la timeline en el cabezal. También puedes arrastrarlo.</li>
<li><b>Clic derecho</b> en un archivo: cambiar categoría, etiquetas, corregir lo que vio la IA…</li>
<li>Los archivos originales nunca se modifican.</li>
</ul><br><br><b>Organizar</b>: clic derecho → «📂 Mover a…» (otra categoría o carpeta, o una nueva), o arrastra los archivos sobre una carpeta. <b>Supr</b> quita de Medios (el archivo sigue en el disco); «🗑 Eliminar el archivo» lo manda a la Papelera de Windows (recuperable).<br><br><b>🎵 Convertir en solo audio</b>: clic derecho en uno o varios videos. Si el sonido ya es AAC o MP3 se copia tal cual (sin perder nada, en segundos); si no, se convierte a AAC de alta calidad. Se guarda en la carpeta «Audio extraído» de Reclaimer (tus originales no se tocan) y aparece en Medios ▸ «Audio extraído»."""),
    "palabras_clave": ("🔑 Palabras clave", """
Una carpeta por palabra (Fortnite, Minecraft…) con tu material para ella. Lo que dices en la narración
aparece aquí y en 🎬 Clips.
<ul>
<li><b>＋ Palabra clave</b>: crea una. <b>✨ Crear de lo que dices</b>: crea una carpeta por cada palabra de tu narración.</li>
<li><b>📂 Añadir carpeta de mi PC</b>: la enlaza (no se copia). Arrastrar una carpeta del Explorador sobre la palabra hace lo mismo.</li>
<li><b>📍 Poner donde lo dices</b>: pone los archivos seleccionados (o todos) en los momentos donde la dices. Un solo Ctrl+Z.</li>
<li>🔗 = viene de una carpeta de tu PC. <b>Quitar palabra clave</b> manda a la Papelera solo su carpeta de Reclaimer; tus carpetas del PC nunca se borran.</li>
</ul>"""),
    "montaje_guion": ("📜 Montaje desde el guion", """
Pegas tu guion con <b>una oración por línea</b> y eliges la narración. «🔍 Analizar» busca cada línea en lo que dijiste
y elige la mejor toma (normalmente la última completa). Cada línea tiene su desplegable de tomas y ▶ para escucharla.
<ul>
<li><b>⚠ falta</b>: esa línea no la encontré en la grabación (se marca donde iría).</li>
<li><b>✎ improvisado</b>: lo dijiste y no estaba en el guion. Se deja, pero se marca.</li>
<li>Etiquetas entre corchetes: <b>[CLIP: fortnite]</b> pone un clip de esa carpeta en esa frase; <b>[IMG: titular.png]</b>
pone una imagen; <b>[MÚSICA: tensa]</b> y <b>[NOTA: …]</b> solo dejan un marcador con el texto.</li>
</ul>«✓ Montar» hace todo en UN solo paso: quita las tomas descartadas en todas las pistas. Ctrl+Z lo deshace todo."""),
    "montaje_guiado": ("🧭 Montaje guiado", """
Los pasos de un montaje en orden: importar, quitar silencios, revisar los cortes dudosos, poner los clips
de lo que dices, la revisión rápida, la miniatura y la entrega.<br><br>
Cada paso muestra su estado y tiene su botón. Lo que hagas aquí es el mismo proyecto que en las demás páginas."""),
    "analizar_clips": ("◈ Analizar clips con IA", """
La IA mira varios fotogramas de cada clip y anota su <b>tipo</b> (Gameplay, Cinemáticas, Menús…) y
<b>lo que se ve</b> (combate, exploración, diálogo, personaje…).<br><br>
Sirve para buscar clips por contenido, proponer B-roll y avisar de inconsistencias.
La primera vez descarga los modelos (~500 MB); después los clips nuevos se analizan solos en segundo
plano. Todo funciona en tu PC. Pulsarlo mientras analiza lo detiene."""),
    "buscar": ("Buscar en la biblioteca", """
<b>Búsqueda normal</b>: escribe y se filtra por nombre, categoría, carpeta y lo que vio la IA.<br><br>
<b>◈ Buscar (por contenido)</b>: actívalo, describe lo que quieres ver («Marcus peleando contra varios
enemigos», «una cinemática triste») y pulsa Enter. La IA ordena los clips por parecido y encuentra
el mejor momento de cada uno (★★★ = más parecido). Doble clic en un resultado = se añade desde ese momento."""),
    "visor": ("Visor", """
Muestra el video tal como saldrá al exportar (encuadres, pantalla dividida, textos y subtítulos).
<ul><li><b>Espacio</b> = reproducir/pausar, <b>← →</b> = fotograma a fotograma.</li>
<li>Con un clip de video o imagen seleccionado (como el «Transform» de DaVinci Resolve): cada capa es
independiente. Sale su caja con 4 esquinas: <b>arrastra</b> dentro para moverla, una <b>esquina</b> o la
<b>rueda</b> para cambiar su tamaño (sin deformar); se ve lo de las pistas de debajo. <b>Doble clic</b> = vuelve
a pantalla completa. <b>Alt + arrastrar / Alt + rueda</b> = mover o acercar la imagen DENTRO de su caja
(encuadre). Todo con Ctrl+Z.</li></ul>"""),
    "timeline": ("Timeline", """
<ul>
<li><b>Arrastrar</b> un clip = moverlo · <b>arrastrar su borde</b> = recortarlo · <b>S</b> = dividir en el cabezal.</li>
<li><b>Supr</b> = eliminar · <b>Mayús+Supr</b> = eliminar y cerrar el hueco · <b>Ctrl+L</b> = bloquear el clip.</li>
<li><b>J / K / L</b> = atrás / parar / adelante · <b>I / O</b> = entrada / salida del tramo · <b>R</b> = velocidad · <b>Mayús+R</b> = congelar la imagen.</li>
<li><b>M</b> = marcador · <b>T</b> = texto en pantalla · <b>Ctrl+rueda</b> = zoom de la timeline.</li>
<li><b>✨ Ideas para esto</b> (clic derecho en uno o varios clips): entrada animada, sombra, contorno y dónde
ponerlo, con un clic. Las capturas de texto se proponen como tarjeta; varios clips, escalonados. Ctrl+Z.</li>
<li><b>⊞ Composición</b> (botón del visor): elige cuántos huecos (2, 3, 4, 6, 9) y arrastra desde Medios a cada
«+»; fuera de los huecos = fondo. Van en sus pistas «⊞ Composición» / «⊞ Fondo»; muévelos arrastrando en el visor.</li>
<li><b>⧉ Clip compuesto</b>: selecciona varios clips → clic derecho → «Hacer clip compuesto (cocinar)»: se
renderizan con todo (efectos, color, textos, transiciones, sonido) a un solo video que los sustituye, y el visor
va más fluido. Clic derecho → «Deshacer clip compuesto» devuelve los originales.</li>
<li>🔒 en una pista = nadie (ni la IA) puede tocarla. 👁/🔊 = ocultar o silenciar la pista.</li>
<li><b>Pistas</b>: un proyecto nuevo trae <b>una sola pista de audio</b>. Encima de los nombres:
<b>➕ Pista</b> = agregar una de video o de audio · <b>🎞 ↕</b> = alto de las pistas de video · <b>🔊 ↕</b> = alto
de las de audio (clic = barrita para el tamaño exacto; rueda del ratón encima = más / menos). Si arrastras algo a
la <b>franja de abajo</b> («➕ Suelta aquí…»), se crea una pista nueva para eso. <b>Doble clic en el nombre</b> (o clic derecho → Renombrar) = ponle el nombre que quieras; salen
sugerencias (Narración, Música, Efectos…). Si la llamas <b>Música</b>, baja sola cuando hablas; <b>Efectos</b>
recibe los sonidos; <b>Narración/Voz</b> recibe la mejora de voz. Cuando la IA pone música o sonidos y no hay
pista para ellos, crea una nueva (nunca encima de tu voz).</li>
<li>Borde naranja con «IA» = lo hizo la IA. ✂ naranja = corte de la IA. Rombos amarillos = claves de zoom.</li>
<li>La franja de colores de arriba son los <b>temas</b> de tu narración: doble clic = cambiar, arrastra el borde para ajustarlo.</li>
<li>En un marcador puedes escribir una instrucción para el Modo Director («usa cinemáticas», «no modificar»).</li>
<li><b>Imagen y sonido vinculados</b> (como en Resolve): al poner un video, su sonido va a la pista
«Audio de video», justo debajo, con 🔗. Se seleccionan, mueven, recortan, cortan y borran juntos.
<b>Alt+clic</b> = solo uno de los dos. El botón 🔗 (Ctrl+Mayús+L) activa o desactiva la selección
vinculada. Clic derecho → «Desvincular», «Vincular» o «Separar el audio» (para clips antiguos).</li>
<li><b>Forma de onda</b> (menú Timeline → 〰 Forma de onda): espejo, rectificada (desde abajo) o solo
contorno; escala en dB para ver los sonidos bajos; silencios sombreados con una marca amarilla
<b>«fin del sonido»</b>; picos saturados en rojo; pistas de audio normales, altas o muy altas.</li>
</ul>"""),
    "historial": ("Historial", """
Cada cambio queda registrado aquí; los de la IA empiezan por «IA ·».
Haz clic en una línea para volver a ese punto (como pulsar Ctrl+Z varias veces)."""),
    # ---------------------------------------------------------- detalles
    "proyecto": ("Ajustes del proyecto", """
<b>Tipo</b>: Video de YouTube (16:9) o YouTube Short (9:16). En un Short, los clips horizontales se colocan
solos con fondo desenfocado (como en tus Shorts), los subtítulos usan el estilo «Mis Shorts», las etiquetas
van encima del video, la comparación se pone arriba y abajo, y el B-roll cambia cada 2–3 s.<br>
<b>Edit musical</b> (9:16): videos sin comentario donde manda la música.
Para montarlo solo: pestaña IA ✨ → «🎵 Edit musical» (Ctrl+M).<br><br>
Resolución y fotogramas por segundo del video. Para ver y cambiar las propiedades de un clip,
selecciónalo en la timeline."""),
    "edit_musical": ("Crear edit musical", """
Monta solo un <b>edit</b>: un video sin comentario donde manda la música, con los cortes al ritmo.<br><br>
<b>1.</b> Escucha la canción: el tempo, el <b>bombo</b>, la <b>caja</b> y los platillos por separado, dónde
empieza cada compás, las partes (intro, <b>subida</b>, <b>drop</b>, pausa, final) y las <b>paradas</b>
(cuando la música se calla de golpe). Coloca los golpes justo sobre el bombo real.<br>
<b>2.</b> Mira tus clips: dónde hay acción, cortes u oscuridad (la 2ª vez es instantáneo).<br>
<b>3.</b> Monta según la parte de la canción: en la intro y las pausas, planos largos (y cámara lenta si el
estilo la usa); en la <b>subida</b> los cortes se aceleran (golpe → medio → cuarto, con estrobo) hasta el
<b>drop</b>, donde llega el golpe (destello o negativo) y los cortes van al ritmo; en las paradas la imagen se
congela.<br><br>
<b>Estilos</b> (cada uno pone sus efectos; luego puedes cambiar cualquiera):<br>
· 🎭 Dramático · 🌧 Triste / melancólico · 🌑 Misterioso / oscuro · ⚠ Tenso · 🕰 Nostálgico · 🌅 Inspirador / épico · ◻ Minimalista (cada uno cambia el ritmo de cortes, la cámara lenta, los golpes, las transiciones y el color).<br>
· 🔥 <b>Agresivo / Intenso</b>: velocity, destellos, temblor con el bajo, color duro.<br>
· 🗿 <b>Épico clásico (blanco y negro)</b>: B/N muy contrastado, grano, viñeta, barras de cine, cámara lenta
dramática, negativo en el drop y textos con letra clásica.<br>
· ⚡ <b>Hype gaming</b>: cortes muy rápidos, color saturado, glitch, zooms.<br>
· 🎬 <b>Cinemático</b> · 💧 <b>Emocional / lento</b> · 📼 <b>Analógico / VHS</b> · 🎴 <b>Estilizado</b> ·
📜 <b>Historia / lore</b>.<br><br>
<b>Velocity</b>: cámara lenta justo en el golpe y acelerón hasta el siguiente (lo típico de los edits).<br>
<b>Duración</b>: 30, 45 o 60 s, automático (~40 s alrededor del drop) o la canción entera.<br>
<b>Cortes</b>: tranquilo, normal, intenso o frenético.<br>
<b>Crear otra versión</b>: elige otros planos (puedes deshacer la anterior con Ctrl+Z).<br><br>
Todo queda como clips normales en la timeline (con su velocidad, color, transiciones y efectos): puedes
moverlos, cambiarlos, quitar efectos en el Inspector o deshacerlo todo con Ctrl+Z. Un marcador rojo señala
el drop.<br><br>
<b>Ritmo</b>: la canción se divide en frases (4 compases); cada estilo tiene su ritmo de cortes (Emocional y
Cine nunca bajan de 2 golpes por plano; los cortes rápidos solo en las partes fuertes de Agresivo/Hype). Las
transiciones caen en los cambios de parte o al empezar una frase y duran 1 golpe (½ en lo fuerte).
Se exporta a 60 FPS con cámara lenta fluida.<br><br>
<b>Barra «🎵 Edit» de la línea de tiempo</b> (con el cabezal sobre el edit):<br>
<b>👍 / 👎</b> = este edit (entero) funciona o no. Si lo retocaste a mano, aprende de <b>tu versión</b>
(comparándola con la de la IA). Los siguientes edits de ese estilo salen con lo aprendido.<br>
<b>👎 además VETA esos planos</b>: ya no vuelven a salir (ni en 🔀 Remix, ni en 🎛 Mix, ni en edits nuevos de este
proyecto). Con <b>solo unos planos seleccionados</b>, 👎 veta esos y los cambia al momento por otros.
Ctrl+Z los vuelve a permitir.<br>
<b>🔀 Remix</b> = lo rehace entero de otra manera (otros planos, cortes, transición y efectos como el zoom 3D),
siempre al ritmo. Ctrl+Z vuelve a la versión anterior.<br>
<b>🎛 Mix</b> = selecciona unos planos del edit (o marca un tramo con I y O) y solo eso se rehace; lo demás
queda igual.<br><br>
<b>✂ Elegir tramos</b> (en la ventana del edit: doble clic en un video o «✂ Elegir tramos…»): lo reproduces y
marcas de dónde a dónde (I / O / «➕ Añadir tramo»). La IA solo saca planos de ahí, también en Remix y Mix.
Se guardan con el video."""),
    "miniatura": ("Taller de miniaturas", """
Crea la miniatura sin salir del editor (botón <b>🖼 Miniatura</b> de abajo o Archivo → Crear miniatura).<br><br>
<b>Arriba</b>: formato (YouTube 1280×720 o Shorts 1080×1920), deshacer, duplicar, ordenar, alinear y
<b>Exportar</b> (JPG por debajo de 2 MB, el límite de YouTube).<br>
<b>Izquierda</b>: 🖼 Material (fotogramas e imágenes: clic = encima, doble clic = de fondo; «📷 Fotograma del
visor» toma lo que ves en el video), T Texto, ◆ Elementos (formas, flecha, degradado oscuro para dar contraste
al texto), ▦ Fondo y ☰ Capas (ocultar, bloquear, ordenar).<br>
<b>Lienzo</b>: clic = elegir; arrastra para mover (se pega al centro y a los tercios); esquinas = tamaño; círculo
de arriba = girar (Mayús: de 15 en 15). Supr = borrar, Ctrl+D = duplicar, flechas = mover poquito.<br>
<b>Derecha</b>: las opciones de lo elegido: texto (fuente, tamaño, grosor, espaciado…), ajustes de imagen
(exposición, contraste, saturación, temperatura, sombras, luces, nitidez, desenfoque, viñeta), recorte, y
efectos (contorno, sombra, brillo). Se guarda con el proyecto."""),
    "mapa_ia": ("Qué puede hacer la IA", """
Cada tarjeta es una herramienta de la IA: <b>qué hace</b> (el nombre), <b>qué encontró o hizo ya</b> (la línea
gris: «✓ 7 temas», «Reconoce 3 nombres»…) y <b>un clic para usarla</b>. La IA propone; tú decides:
todo se puede revisar, cambiar o deshacer con Ctrl+Z.<br><br>
<b>Flujo típico</b>: 🔬 Entender mis clips → ✨ Autoedición (de tu voz a una primera versión) → revisa →
🔎 Buscar momentos para cambiar un plano concreto → ⚕ Revisión → exportar.<br>
También tienes la IA en el <b>clic derecho</b> de la línea de tiempo (submenú ✨ IA) y de la transcripción."""),
    "momentos": ("Buscar momentos", """
Busca <b>dónde aparece algo</b> en tus videos e imágenes y ponlo en la línea de tiempo.<br><br>
<b>Qué buscas</b>: escribe una descripción («la Lancer», «un coche rojo», «una explosión»), pulsa
<b>🖼 Por imagen…</b> para darle una foto o captura de referencia, o elige un nombre que la IA ya
aprendió («Lo que conoce la IA»).<br>
<b>Qué encontró</b>: cada miniatura es una <b>aparición</b>, con su inicio y su fin (si algo vuelve a
salir mucho después, es otra aparición). Desplázate para ver más.<br>
<b>Qué puedes hacer</b>: ▶ verla, recortar «Desde/hasta», <b>Insertar en el cabezal</b> (en una pista libre:
no tapa nada), <b>Reemplazar</b> el clip seleccionado, <b>Añadir después</b> de él, ⭐ guardarla en favoritos o
ver de qué archivo viene. Doble clic = insertar.<br><br>
También desde el <b>clic derecho</b>: en la transcripción («Buscar material para esta frase»: lo pone donde
dices la frase) o en un clip («Buscar momentos parecidos a este clip»).<br>
Funciona mejor tras «🔬 Entender mi biblioteca a fondo» (revisa cada segundo de tus videos).<br><br><b>🎯 Ejemplo</b> (a la derecha de Buscar, o clic derecho en un clip de la línea de tiempo o en un
archivo de Medios): enséñale a la IA lo que buscas con tu propio material. Eliges el momento (con la <b>tira de
fotogramas</b> o la barra), si quieres <b>dibujas un recuadro</b> sobre lo que buscas y escribes qué es.
<b>✓ Esto es</b> / <b>✗ Esto NO es</b> guardan ese ejemplo y la ventana sigue abierta para marcar más momentos;
<b>🔎 Buscar</b> busca con todo lo marcado; <b>✓ Es esto y buscar</b> hace las dos cosas de una vez.<br>
<b>Varios fotogramas</b>: Ctrl+clic en la tira añade o quita uno, Mayús+clic elige un tramo, o marca «Varios fotogramas» para que cada clic seleccione (también «Todos» / «Ninguno»): ✓ o ✗ guardan un ejemplo por cada fotograma.<br><b>◈ Dónde sale</b>: encima de la barra de tiempo, la IA pinta en naranja los momentos del clip que más se parecen a lo que escribiste en «¿Qué es?» (y a tus ✓/✗, que mandan); ▲ = los más probables, clic = ir ahí, <b>◀ ▶</b> = el anterior / siguiente. Al cambiar de momento, el recuadro se quita solo (era de otro fotograma).<br><br><b>Internet</b>: busca en <b>Openverse</b> y <b>Wikimedia Commons</b> (solo licencias de uso comercial).
«caballero medieval» se busca también como «medieval knight» (las imágenes están etiquetadas en inglés) y suben las
que llevan tus palabras en el título. <b>Solo buena calidad</b> esconde las pequeñas (menos de 800 px).
Para personajes de videojuegos casi no hay imágenes libres: si salen pocas, <b>📁 Buscar en mis archivos</b>
busca lo mismo en tus videos.<br><br><b>Cada imagen</b> lleva su barra «es lo que buscas: 0–100 %» (lo que cree la IA; «identificando…» mientras la analiza). Arriba a la derecha ✓ (es) y ✗ (no es); arriba a la izquierda <b>»</b> «Saltar» la esconde sin enseñarle nada. La lista no salta sola al principio: «⤒ Inicio» sube. La imagen de «Aparición seleccionada» se puede <b>arrastrar a la línea de tiempo</b>. Las de internet marcadas ✓ se guardan como «lo que buscaste 1, 2, 3…» y en Medios aparecen en «Internet ▸ lo que buscaste»."""),
    "entender": ("Entender mi biblioteca a fondo", """
La IA revisa <b>cada imagen y cada segundo</b> de tus videos (no solo unos pocos fotogramas), los divide
en planos y aprende <b>quién y qué aparece</b>. Así, cuando en tu narración dices «el Jefe Maestro», el
B-roll muestra una imagen, cinemática o momento donde sale.<br><br>
<b>Cómo aprende los nombres:</b><br>
• De tus <b>imágenes</b>: «jefe maestro.png» le enseña cómo es, y lo busca en tus videos por parecido.
  Es lo más fiable: añade unas cuantas imágenes con buen nombre.<br>
• De los nombres de tus archivos y carpetas («Cinemáticas/Cortana.mp4»).<br>
• De los <b>nombres propios que dices</b> en la narración.<br>
• Del <b>glosario</b> (a la derecha): «Jefe Maestro = Master Chief, John-117» une apodos y nombres en inglés.<br><br>
Despliega un nombre para ver dónde lo encontró (con miniaturas). Tarda ≈1 minuto por cada hora de
video y se guarda: la segunda vez es instantáneo. «Actualizar nombres» recalcula rápido tras editar el glosario."""),
    "primera_version": ("Primera versión automática", """
De tu narración a un video casi terminado, sin estar delante de la pantalla. Elige la narración
(y, si quieres, una música de fondo), pulsa «Empezar» y vete: la IA hace, uno detrás de otro:<br><br>
<b>1.</b> Pone la narración en la timeline · <b>2.</b> La transcribe · <b>3.</b> Limpia la voz
(silencios largos, respiraciones, muletillas, repeticiones; en las tomas repetidas se queda la última) ·
<b>4.</b> Mira tus clips · <b>5.</b> Detecta los temas · <b>6.</b> Coloca B-roll que encaja con lo que
dices, a tu ritmo (como en tus videos: cada 3–6 s; en Shorts cada 2–3 s) · <b>7.</b> Zooms rápidos cuando
dices «miren», «fíjense»… · <b>8.</b> Toques de cine: zoom lento en los planos largos y un fundido breve
en cada cambio de tema · <b>9.</b> Audio: tu ecualizador «Mi voz», mejora de voz, música que baja sola
cuando hablas y volumen final −14 LUFS · <b>10.</b> Subtítulos (en Shorts) · <b>11.</b> Revisión final.<br><br>
<b>Nada es definitivo</b>: todo queda como clips normales, los cortes de voz se pueden restaurar en
«Limpieza», los clips de B-roll se cambian en IA ✨, y <b>Ctrl+Z deshace la primera versión entera</b>.
Las comparaciones solo se sugieren (tú eliges los dos clips)."""),
    "efectos_sonido": ("Sonidos", """
<b>Sonidos de Reclaimer</b>: whooshes, impactos, subidas (risers), glitch, clics… generados por el propio
programa: son <b>100 % tuyos</b> (sin licencias ni reclamaciones de Content ID).<br>
<b>Clic</b> = escuchar · <b>doble clic</b> = ponerlo en el cabezal (en tu pista de efectos; si no hay, se crea) · o <b>arrástralo</b> a la timeline.<br>
<b>📁 Mi carpeta de efectos</b>: elige la carpeta donde guardas los que descargas (Kenney, Sonniss…) y
aparecerán aquí, con buscador."""),
    "efectos_imagen": ("Efectos de imagen", """
Selecciona uno o varios clips en la timeline y pulsa un efecto para ponerlo (o quitarlo):
blanco y negro, viñeta, grano de película, desenfoque, glitch RGB, película antigua, tono cálido/frío,
destello, temblor y fundidos. En el visor se ven el blanco y negro, el desenfoque, la viñeta, los destellos,
fundidos y temblor; el grano, el glitch y los tonos se ven al exportar. Todo se deshace con Ctrl+Z.<br><br>
<b>🟩 Pantalla verde</b>: selecciona el clip con fondo de color y pulsa «Quitar fondo de color»: el color se
detecta solo (verde, azul…) y se quita también el reflejo verde sobre la persona; lo de la pista de debajo se ve
a través. <b>Tolerancia</b>: si queda verde, súbela; si se come al sujeto, bájala. <b>Suavidad</b>: borde suave.
✕ = quitarla. Lo que ves en el visor es lo que se exporta.<br><br>
<b>👤 Quitar el fondo quieto</b> (sin pantalla verde): con la cámara FIJA (facecam, plano quieto) Reclaimer
aprende cómo es el fondo vacío y quita todo lo que no se mueve. Si la cámara se mueve, te avisa y no lo aplica.
Tolerancia: si queda fondo, súbela; si se come a la persona, bájala."""),
    "color": ("Color del clip", """
Ajusta el color de un clip de video o imagen, como en la página Color de DaVinci Resolve (en sencillo):
<b>exposición</b> (más luz o menos, en pasos), <b>contraste</b>, <b>saturación</b>, <b>temperatura</b> (más azul ↔
más naranja), <b>tinte</b> (verde ↔ magenta), <b>sombras</b> y <b>luces</b>.<br><br>
<b>✨ Color automático</b>: mira el fotograma del cabezal y corrige exposición, contraste y balance de blancos.<br>
<b>🎨 LUT (.cube)</b>: un «look» de color ya hecho (de Resolve, de tu cámara, descargado…), con su intensidad.<br>
<b>👁 Ver sin corrección</b>: compara el antes y el después en el visor.<br><br>
Lo que ves en el visor es exactamente lo que sale al exportar (se usa la misma tabla de color).
Para repetirlo en otros clips: <b>Ctrl+C</b> en este y <b>Alt+V</b> en los otros → «Color»."""),
    "graficas": ("Gráficas de video", """
Como los «scopes» de DaVinci Resolve: miden el fotograma del cabezal (con su color) para que no dependas
de cómo se ve tu pantalla.<br><br>
<b>Forma de onda</b>: cada columna de la imagen, de abajo (negro) a arriba (blanco). Si algo toca el techo está
quemado; si se queda pegado al suelo, aplastado.<br>
<b>Desfile RGB</b>: lo mismo por separado para rojo, verde y azul: si una sube más que las otras, hay un tono
dominante (p. ej. todo anaranjado).<br>
<b>Histograma</b>: cuántos píxeles hay de cada brillo.<br>
<b>Vectorscopio</b>: el centro es gris; cuanto más lejos, más saturado. La línea naranja marca el tono de
la piel: las caras deberían caer cerca de ella.<br><br>
Debajo verás avisos en palabras (quemado, muy oscuro, muy saturado). Se actualiza al pausar o mover el cabezal."""),
    "fusion": ("Opacidad y modo de fusión", """
<b>Opacidad</b>: cuánto se ve el clip sobre lo que hay debajo (100 % = tapa por completo).<br>
<b>Fusión</b>: cómo se mezcla con lo de abajo, como en Resolve: <b>Pantalla</b> y <b>Añadir</b> aclaran (perfecto
para destellos, luces, humo o polvo sobre fondo negro); <b>Multiplicar</b> y <b>Oscurecer</b> oscurecen (texturas,
sombras sobre fondo blanco); <b>Superponer</b> y <b>Luz suave</b> dan contraste; <b>Diferencia</b>, efecto raro.<br><br>
Para que la opacidad cambie con el tiempo (aparecer poco a poco…), activa <b>〰 Curvas</b> en la línea de tiempo."""),
    "mejorar": ("Mejorar imagen", """
<b>Reducir ruido</b>: quita el «grano» de los videos oscuros o grabados con poca luz (más alto = más suave).<br>
<b>Estabilizar</b>: quita el temblor de la cámara (videos grabados con el móvil o a mano). Al activarlo se
analiza el movimiento unos segundos; el deslizador dice cuánto se suaviza. Se amplía un poco la imagen para
que no se vean bordes negros.<br>
<b>✂ Detectar cortes de escena</b>: en un clip largo con muchos planos (un tráiler, una cinemática) encuentra
cada cambio de plano para <b>cortar ahí</b> de una vez o <b>poner marcadores</b>.<br><br>
El ruido y la estabilización se ven al exportar o con <b>«▶ Ver cómo queda»</b>."""),
    "silencio": ("Eliminar silencio", """
Como el «Eliminar silencio» de DaVinci Resolve: quita los tramos callados de los clips seleccionados (o de la
narración si no hay nada seleccionado), midiendo el sonido (no hace falta transcribir). También con <b>clic derecho
en un audio → «✂ Eliminar silencios»</b>.<br><br>
<b>Detección «🎙 Voz precisa»</b> (por defecto): una IA reconoce dónde HABLAS (no la engaña el ruido de fondo: ventilador,
teclado, el juego) y cada borde se ajusta cada 5 ms hasta que el sonido de verdad se apaga, también las «s» y «f»
suaves del final y los arranques flojos. Nunca recorta la voz: solo la alarga, y los cortes se redondean hacia el
silencio. «🔊 Solo volumen» corta exactamente como Resolve (con voz baja o ruido se puede comer palabras).<br>
Ajuste <b>«Pausas cortas, ritmo de Shorts»</b>: medido en tus Shorts terminados (hablas casi todo el tiempo, pausas muy
cortas); es lo más ajustado que sigue sin comerse nada.<br><br>
<b>Umbral</b>: por debajo de este volumen es silencio (-32 dB = solo lo muy callado; -26 dB = también lo bajito).<br>
<b>Antes del inicio</b> / <b>Después del final</b>: fotogramas de silencio que se conservan junto a cada sonido
(para no comerse el principio ni el final de las palabras).<br>
<b>Mínimo a eliminar</b>: los silencios más cortos se respetan (pausas naturales).<br>
<b>Fundido cruzado</b>: un fundido mínimo en cada corte para que no se oiga un «clic».<br><br>
Mientras ajustas, la línea de tiempo marca en <b>naranja</b> lo que se quitará. «Mover todo lo de detrás» corta en
todas las pistas (no se desincroniza el video de tu voz). Tus ajustes de Resolve ya están guardados y puedes guardar
más. Todo se deshace con un Ctrl+Z."""),
    "limpieza_auto": ("Limpieza automática", """
Quita de una vez lo que marques, después de transcribir:<br>
<b>Muletillas seguras</b> (eh, mmm…) · <b>posibles muletillas</b> (este, bueno, o sea… solo con pausa detrás) ·
<b>palabras repetidas y cortadas</b> («el el», «pro… problema»; las que suelen ser a propósito, como «muy muy» o
«no no», no se tocan) · <b>tomas repetidas</b> · <b>silencios largos</b> · <b>respiraciones</b>.<br><br>
<b>Tomas repetidas</b>: si dices una frase dos o más veces, la IA se queda con la <b>mejor</b> (no siempre la última):
la que no dejaste a medias, la más completa, sin muletillas ni trabas, sin pausas raras y que se entiende mejor.
En la lista verás ⭐ la elegida y el porqué; con «✓ Elegir toma…» puedes quedarte con otra.<br><br>
<b>Hacerlo solo al terminar</b>: limpia en cuanto acaba la transcripción. Todo se deshace con un Ctrl+Z, o corte a
corte desde «Aplicadas» con «↺ Restaurar». Para revisar una por una, usa la lista de abajo (modo manual).<br><br>
Estas casillas también deciden qué sale <b>tachado en rojo</b> en la pestaña «Texto»; lo que taches o destaches
allí manda sobre ellas."""),
    "transiciones": ("Transiciones", """
Une dos clips <b>pegados</b> de una pista de video con un efecto, como en DaVinci Resolve: disolver,
fundido a negro, destello blanco, latigazo, zoom, deslizar, barrido, círculo, pixelado…<br><br>
<b>Dónde se pone</b>: en el corte del clip seleccionado, o en el corte más cercano al cabezal.
También con <b>clic derecho</b> sobre un clip → «⧉ Transición» (al inicio o al final) o <b>Alt+T</b> (disolver).<br>
<b>Duración</b>: se centra en el corte (empieza la mitad antes y acaba la mitad después), así el video no
cambia de duración. Si no hay más material en el archivo, se alarga el borde con una imagen quieta.<br>
En la línea de tiempo se ve como una pajarita sobre el corte. En el visor se ve como un fundido;
<b>«▶ Ver la transición»</b> prepara el resultado exacto en unos segundos.<br><br>
<b>Editarla en la línea de tiempo</b>: <b>clic</b> en la pajarita = seleccionarla (naranja) · <b>Supr</b> o
<b>Ctrl+X</b> = quitarla (los clips quedan igual) · <b>arrastra un borde</b> = más larga o más corta ·
<b>clic derecho</b> = 🔁 Reemplazar por otra, ⏱ Duración (+/− 0,25 s o un valor), ✕ Quitar.<br>
<b>🤖 Las de la IA</b> (en ese mismo clic derecho): más cortas, normales, más largas o muy largas; se aplica a
las que ponga a partir de ahora y a las que ya puso (Ctrl+Z lo deshace)."""),
    "efectos_internet": ("Efectos gratis en internet", """
Fuentes revisadas para que puedas usarlas en videos <b>monetizados</b>:<br>
• <b>Kenney.nl</b>: CC0 (dominio público), sin atribución. Lo más seguro.<br>
• <b>Sonniss GDC Bundle</b>: decenas de GB de efectos de cine; libres de derechos, sin atribución
(no se pueden revender sueltos ni usar para entrenar IA).<br>
• <b>Freesound</b>: usa solo los marcados CC0 (los CC-BY piden crédito en la descripción).<br>
• <b>Mixkit</b>: gratis; revisa su licencia antes.<br>
Descárgalos en una carpeta y elígela con «📁 Mi carpeta de efectos»."""),
    "efectos": ("Efectos del clip", """
<b>Destello</b>: el clip empieza en blanco y se aclara (ideal en el golpe del drop).<br>
<b>Fundido de entrada / salida</b>: desde negro al empezar o a negro al acabar.<br>
<b>Temblor</b>: la imagen tiembla al empezar el clip y se va calmando.<br>
Todo en segundos; 0 = sin efecto. Se ven en el visor y salen igual al exportar."""),
    "clip": ("Clip", """
Información del clip seleccionado (qué archivo y qué trozo usa, dónde está), si está activo o
bloqueado 🔒 (nadie, ni la IA, podrá modificarlo) y una <b>nota</b>: puedes escribir instrucciones
para ese clip."""),
    "encuadre": ("Encuadre y zoom", """
<ul>
<li><b>Zoom</b> y <b>Centro (X, Y)</b>: cuánto se acerca y a qué punto mira.</li>
<li>Más fácil: con el clip seleccionado, <b>arrastra en el visor</b> y usa la <b>rueda</b>.</li>
<li><b>◆ Clave aquí</b>: guarda el encuadre en este momento. Con dos o más claves el zoom se mueve
suavemente entre ellas (rombos amarillos en el clip). ◀ ▶ saltan entre claves, ✕ quita la clave del cabezal.</li>
<li><b>En pantalla</b>: pon el clip en una mitad, arriba/abajo o en una esquina (pantalla dividida). Para llenar lo
que queda vacío alrededor con la propia imagen desenfocada: <b>▦ Relleno</b> (⤧ Transformar).</li>
<li><b>🎯 Seguir personaje u objeto</b>: marcas algo y la IA crea un zoom que lo acompaña.</li>
</ul>"""),
    "audio_clip": ("Audio del clip", """
<b>Volumen</b> del clip y <b>Balance</b> (más a la izquierda o a la derecha).<br><br>
El <b>ecualizador</b> cambia el sonido por frecuencias, como el del Inspector de DaVinci Resolve."""),
    "ecualizador": ("Ecualizador", """
<ul>
<li>La gráfica: a la izquierda los graves, a la derecha los agudos; arriba más volumen, abajo menos.
En gris, el sonido del clip en el cabezal.</li>
<li><b>Arrastra un punto</b> = cambia su frecuencia y ganancia · <b>rueda sobre un punto</b> = más estrecho o más ancho (Q)
· <b>doble clic</b> = activar/desactivar esa banda.</li>
<li>Tipos: <b>corte de graves/agudos</b> (elimina por debajo/encima), <b>estante</b> (sube o baja todo lo grave/agudo),
<b>campana</b> (una zona concreta).</li>
<li><b>Presets</b>: Voz clara, Quitar retumbe, Más brillo, Teléfono/radio, Plano.</li>
<li><b>🎧 Escuchar con EQ</b>: repite en bucle unos segundos del cabezal y se actualiza al momento cuando cambias algo.</li>
<li><b>Aplicar a todo este archivo</b>: útil con la narración, que queda dividida en muchos clips tras quitar silencios.</li>
</ul>
Al exportar se aplica exactamente la curva que ves."""),
    "texto_pantalla": ("Texto en pantalla", """
Títulos y etiquetas encima del video, como el «Texto» de DaVinci Resolve (el texto se aplica solo al escribir).<br>
<b>✍ Ortografía</b> (debajo del cuadro): subraya en rojo lo mal escrito; clic derecho en la palabra → sugerencias,
«Añadir al diccionario» o «Ignorar». Idioma: <b>Mixto</b> (español de México + inglés, para cuando mezclas: «el boss
final del gameplay»), Español (México), English o Sin corregir. También en las frases del edit y en las miniaturas.
No revisa la gramática («esta» / «está» se aceptan las dos).<br>
<b>Desenfocar lo de debajo</b>: mientras se ve el texto, el video o la imagen de debajo se desenfoca (en el visor y
al exportar). Tus textos nuevos lo traen activado (50 %); se quita o se ajusta en su grupo del Inspector.<br>
<b>Texto</b>: fuente y tipo (Bold, Condensed…), color, tamaño, interletrado, interlineado, negrita/cursiva/
subrayado/tachado, mayúsculas, justificado, posición (en píxeles), zoom y rotación.<br>
<b>Trazo</b>: color, tamaño y «solo afuera». <b>Sombra</b> (casilla para activarla): color, desplazamiento,
desenfoque y opacidad. <b>Fondo</b> (casilla): color, contorno, ancho, altura, esquinas, centro y opacidad.<br>
<b>↺</b> junto a cada opción = valor de fábrica. Con «Recordar mis valores» marcado, lo que cambias se usa en los
textos nuevos («⭐ Aplicar mi estilo» lo pone en uno que ya existe).<br>
Se ve exactamente igual en el visor y al exportar."""),
    # ---------------------------------------------------------- voz
    "transcripcion": ("Transcripción", """
Convierte tu narración en texto con el momento exacto de cada palabra (Whisper, en tu PC).
<ul><li><b>Modelo</b>: Equilibrado (recomendado), Rápido (menos preciso) o Máxima precisión (más lento).</li>
<li>La primera vez se descarga el modelo. Una narración de 15 min tarda unos 3–4 min.</li>
<li><b>🔁 Escucha literal</b>: Whisper a veces escribe UNA vez lo que dijiste dos veces, y esa toma repetida no se
podría quitar. Un segundo oído (en tu PC) escucha todo letra a letra y recupera lo que faltaba. Tarda más (una
narración de 12 min: unos 9 min en total; 3 horas: unas 2 horas), pero se escapan muchas menos tomas.</li>
<li>Al terminar se analiza sola la limpieza de voz.</li></ul>"""),
    "limpieza": ("Limpieza de voz", """
Elige qué debe buscar la IA: silencios largos (dejando siempre una pausa natural), respiraciones y ruidos,
muletillas, palabras repetidas, tomas repetidas, frases que suenan parecido, palabras dudosas y saturación.<br><br>
<b>Tomas repetidas</b>, en tres niveles: <b>se repite</b> (casi palabra por palabra, o la empezaste y la volviste a
empezar), <b>se medio repite</b> (cambia algo: «ayer estaba jugando» → «ayer estaba trabajando») y <b>suena
parecido</b> (lo mismo con otras palabras; solo se avisa, no se tacha solo).<br>
<b>Mis muletillas</b>: las que sabes que dices, separadas por comas («¿por qué?, la verdad»). Con «?» solo cuenta si
es una pregunta suelta. Las coletillas «¿no?», «¿verdad?», «¿me explico?» se buscan siempre.<br><br>
<b>No corta nada por su cuenta</b>: todo aparece como sugerencia. «Volver a analizar» repite la búsqueda con
estas opciones sin transcribir de nuevo."""),
    "sugerencias": ("Sugerencias de la IA", """
<ul><li><b>▶ Escuchar</b> (o doble clic): oyes ese momento.</li>
<li><b>✓ Aplicar</b>: se corta en todas las pistas y se cierra el hueco (voz y video siguen sincronizados).
En las tomas repetidas eliges con qué toma quedarte.</li>
<li><b>✗ Ignorar</b>: se descarta. <b>↺ Restaurar</b>: devuelve un corte aunque después hayas hecho otros cambios.</li>
<li>También se ven en color sobre la voz en la timeline.</li></ul>"""),
    "texto": ("Transcripción sincronizada", """
<ul><li>La palabra que suena se resalta en azul.</li>
<li><b>Clic</b> en una palabra = ir a ese momento · <b>doble clic</b> = corregirla (la sincronización se mantiene).</li>
<li><b>Clic derecho</b> en una o varias palabras = resaltarlas en los subtítulos (p. ej. «NO»).</li>
<li>Tachado gris = ya cortado de la timeline · fondo de color = hay una sugerencia · subrayado punteado = palabra
dudosa.</li>
<li><b>✂ Editar con el texto</b>: lo que se va a quitar sale <b>tachado en rojo</b>. Clic en lo tachado = se queda;
clic en algo con fondo de color = se tacha; en una toma repetida, clic en la que se queda = te quedas con la otra.
Selecciona texto y pulsa <b>Supr</b> (o clic derecho → «✂ Tachar») para quitarlo tú. <b>✂ Cortar lo tachado</b>
lo quita del video en todas las pistas (un Ctrl+Z lo deshace).</li>
<li><b>📋 Resumen</b>: solo los sitios donde hay algo que quitar — frases que se repiten, que se medio repiten o que
suenan parecido (con las tomas, cuál se queda y lo que dijiste después), muletillas agrupadas («¿no?» × 37),
palabras repetidas, lo que tachaste tú, silencios y lo que recuperó la escucha literal. Casilla marcada = se quita;
doble clic = escucharlo.</li>
<li><b>Exportar subtítulos .srt</b>: para subirlos a YouTube, ya ajustados a los cortes.</li>
<li><b>📺 En pantalla</b>: los bloques de texto que salen en el video (a lo mucho 3 palabras en los Shorts), en orden.
Lo que suena AHORA va grande y en naranja y se queda a la vista; clic = ir ahí; doble clic = corregirlo (con
ortografía). Sin subtítulos puestos, enseña cómo quedarían.</li></ul>"""),
    "subtitulos": ("Subtítulos dentro del video", """
Se generan desde la transcripción y siguen a la voz aunque cortes. Elige un estilo (YouTube clásico, Caja oscura,
Shorts dinámico, Minimalista) y ajusta letra, colores, posición y animación («Karaoke» resalta la palabra que dices).<br><br>
<b>Palabras resaltadas</b>: en la pestaña «Texto», clic derecho sobre una palabra → «Resaltar en subtítulos»."""),
    # ---------------------------------------------------------- IA
    "temas": ("Temas de la narración", """
La IA divide lo que dices por temas (Introducción, Historia, Combate, Cinematografía…) y los muestra como
bandas de color arriba de la timeline. Doble clic = cambiar el tema · arrastra el borde para ajustarlo ·
clic derecho = quitar. Se usan para elegir B-roll y avisar de inconsistencias."""),
    "broll": ("B-roll", """
Para cada frase de tu narración, la IA busca en tu biblioteca 3 clips que encajan con lo que dices
(y con el tema de esa parte), y dice por qué.
<ul><li><b>Doble clic en un clip</b> = insertarlo en ese momento · <b>doble clic en una frase</b> = escucharla.</li>
<li><b>⚡ Rellenar huecos con lo mejor</b> = modo automático: solo rellena huecos libres; nunca tapa lo que colocaste tú.</li>
<li>Ajustes: cada cuánto cambiar de clip, qué tipo preferir, en qué pista, no repetir clips y el volumen del sonido del clip.</li>
<li>Lo insertado tiene borde naranja «IA» y se deshace con Ctrl+Z.</li></ul>"""),
    "visuales": ("Sugerencias visuales", """
Cuando dices «miren…», «fíjense…», «en esta escena» o hablas de una cara, la IA propone un <b>zoom rápido</b>
(hacia la cara si la encuentra). Cuando comparas dos cosas («comparado con…», «a diferencia de…», el original
y el remake…), propone una <b>Comparación</b> en pantalla dividida.
Doble clic = verlo · ✓ Aplicar · ✗ Ignorar."""),
    "guardado": ("💾 Guardado y copias de seguridad", """
Para no perder nada, como en DaVinci Resolve (Archivo → «💾 Guardado y copias de seguridad…» o clic en el
«💾 Guardado…» de abajo a la derecha).<br>
<b>Guardado en vivo</b>: cada cambio se guarda solo en tu proyecto un par de segundos después (no hace falta Ctrl+S).
Un proyecto nuevo sin nombre se autoguarda; guárdalo una vez con Ctrl+S y desde entonces se guarda solo.<br>
<b>Copias de seguridad</b>: cada X minutos mientras trabajas se guarda una copia con fecha y hora; se conservan las
últimas N.<br>
<b>⟲ Recuperar</b>: elige una copia de la lista y se abre como copia (al guardar te pregunta dónde, para no pisar el
original). Si el programa se cierra de golpe, al abrirlo te ofrece recuperar lo último."""),
    "atajos": ("⌨ Personalizar atajos", """
Cambia el atajo de teclado de cualquier orden de los menús (Ventana → «⌨ Personalizar atajos de teclado…»).<br>
Clic en el atajo de la orden y pulsa la combinación nueva. Si otra orden ya la usa, te pregunta si quitársela.
<b>↺</b> vuelve al atajo de fábrica de esa orden; «Restablecer todos», a todos. Se guarda al momento y se
mantiene cada vez que abres Reclaimer.<br><br>
<b>Ctrl+X</b> = «Cortar clips»: los quita de la línea de tiempo (y los guarda por si quieres pegarlos con Ctrl+V).
<b>Supr</b> los borra sin guardarlos; <b>Mayús+Supr</b> los borra y cierra el hueco.<br><br>
<b>⬇ Traer mis atajos de DaVinci Resolve…</b>: lee tus atajos de Resolve (solo lectura, de sus Preferencias) y
te enseña, para cada orden que existe en los dos, el atajo de ahora y el de tu Resolve. Marca los que quieras y
«Aplicar los marcados» (si otra orden usaba ese atajo, se le quita). «Restablecer todos» lo deshace."""),
    "aprendizaje": ("◈ Aprendizaje de mi estilo", """
<b>Opcional y apagado de fábrica.</b> Con el interruptor en <b>ON</b>, la IA aprende poco a poco cómo editas;
en <b>OFF</b> no observa ni registra nada.<br><br>
<b>Qué mira</b>: solo lo que haces <b>dentro del editor</b> (cortar, mover, borrar, efectos… — lo que deshaces
enseguida no cuenta) y, al <b>guardar</b> o <b>cerrar</b>, cómo quedó el proyecto: duración de los planos,
transiciones, zooms, música, textos, silencios que quitas… Si la IA hizo una primera versión, compara lo que
propuso con tu resultado final. Nunca el ratón o el teclado de Windows, otras ventanas ni otras carpetas.
Con Reclaimer cerrado no funciona nada.<br><br>
<b>Mi estilo</b>: cada patrón con su <b>confianza</b> (sube con varios proyectos parecidos; uno suelto cuenta
poco). Puedes verlo general, por tipo (videos largos, Shorts, edits) o de este proyecto.<br>
<b>Preferencias</b>: «Creo que he detectado este patrón» → Aceptar, Rechazar, Editar o Eliminar. La IA solo
usa las <b>aceptadas</b>: por ejemplo, la «✨ Primera versión automática» preselecciona el ritmo o los silencios
y te dice por qué («Ver razonamiento»). Nunca cambia tu proyecto por su cuenta.<br>
<b>Este proyecto</b>: aprender de él o excluirlo, y qué tipo de contenido es.<br>
<b>Pausar</b>, <b>Analizar esta sesión</b> y <b>Eliminar perfil aprendido</b> (empezar de cero)."""),
    "desenfoque_zona": ("◌ Desenfoque en zona", """
En <b>Efectos → Efectos de imagen</b>: «▭ Cuadro» o «◯ Círculo» desenfoca solo una parte del clip seleccionado
(una cara, un logo, un dato). Con el clip seleccionado, en el visor ves su contorno naranja: <b>arrastra dentro</b>
para moverla y <b>la esquina naranja</b> para cambiar su tamaño. «Fuerza» cambia cuánto desenfoca (se recuerda) y
«✕» quita las zonas. Puedes poner varias. Se exporta igual que se ve; Ctrl+Z deshace."""),
    "mis_efectos": ("⭐ Mis efectos para la IA", """
Eliges tus efectos favoritos y la IA los propone donde encajan; tú decides.<br><br>
<b>1. Elige</b>: «➕ Añadir efecto…», o clic derecho en un efecto de imagen, un sonido (también los de tu
carpeta) o una transición → ⭐.<br>
<b>2. Propón</b>: «◈ Proponer dónde ponerlos» (todo el video, los clips seleccionados o entre las marcas
I–O; pocos, normal o muchos). La IA mira los <b>cambios de tema</b>, los <b>cortes</b>, los <b>golpes y el drop</b>
de la música, <b>lo que dices</b> («fíjense», «hace años», «un error», «increíble»…) y <b>lo que se ve</b>
(acción, plano tranquilo, escena oscura).<br>
<b>3. Decide</b>: cada propuesta sale en la lista y como un rombo dorado en la línea de tiempo (clic = ir ahí).
<b>✓</b> la pone (si cae en medio de un clip, lo corta ahí), <b>✗</b> la descarta. <b>🎯 En los clips
seleccionados</b> la pone donde tú elijas.<br>
<b>Arrastrar</b>: arrastra un ⭐ (o un efecto de imagen, o una transición) <b>encima de un clip</b> de la línea de
tiempo y se le pone; si sueltas encima de un clip seleccionado junto con otros, se pone en todos. Doble clic en
un ⭐ = en los clips seleccionados. Si el clip está bloqueado 🔒, te lo dice.<br><br>
<b>Aprende</b>: cada ✓/✗ le enseña qué efecto te gusta en qué tipo de momento y con qué tipo de imagen; la
próxima vez propone mejor. Todo se deshace con Ctrl+Z."""),
    "audio_ia": ("Audio inteligente", """
Se aplica al reproducir y al exportar; tus archivos no se modifican.
<ul><li><b>Voz</b>: reducir ruido, ecualizar (más clara), de-esser (suaviza las «s»), compresor (volumen más parejo).</li>
<li><b>Bajar la música cuando hablo</b> (ducking): la música baja sola mientras hablas y sube en las pausas.</li>
<li><b>Volumen final para YouTube</b>: normaliza el video a -14 LUFS.</li>
<li><b>🥁 Cortes al ritmo</b>: lleva los cortes del B-roll al golpe de música más cercano (prefiere el
inicio de compás, los golpes fuertes y el drop).</li>
<li><b>🥁 Ritmo de la música</b>: al poner una canción en la pista de música (o un archivo de la categoría
Música) se escucha sola: tempo, golpes pegados al bombo, compases, golpes fuertes, partes y drop. En la
canción verás una rayita en cada golpe (más larga al empezar el compás), puntos naranjas en los golpes
fuertes y una línea roja en el drop. Con el <b>imán</b> puesto, los clips y la cuchilla se pegan a esos
golpes (se quita en Timeline → «🥁 Imán también a los golpes»). Clic derecho en la canción → «📍 Poner
marcadores en el drop y en cada parte».</li>
<li><b>🎧 Escuchar 10 s</b>: oye esos efectos desde el cabezal.</li></ul>"""),
    "director": ("🎬 Modo Director", """
Escribe lo que quieres para una parte del video, por ejemplo:<br>
<i>«Usa gameplay de combate, cambia de clip cada 3-5 segundos y cuando diga 'el problema' haz un pequeño zoom
al personaje. No agregues texto.»</i><br><br>
Se aplica al tema bajo el cabezal, o a «de 1:20 a 1:40», o «durante 20 segundos». También entiende
«pon el texto 'X'» y «no modifiques esta parte». Verás el plan antes de aplicarlo y un Ctrl+Z lo deshace entero.<br><br>
<b>📍 Leer instrucciones de los marcadores</b>: aplica lo que hayas escrito en los marcadores de la timeline."""),
    "revision": ("Revisión del proyecto", """
Nada se cambia solo: tú decides qué corregir. Doble clic en un aviso = ir a ese momento (y seleccionar el clip).
⛔ = casi seguro un fallo · ⚠️ = posible problema · ℹ️ = sugerencia."""),
    "shorts_video": ("✂ Shorts desde este video", """
Reclaimer busca en tu narración los mejores momentos para Shorts de 45 a 75 segundos (voz con energía, temas y
nombres que salen, y que empiezan y acaban en pausa).<br>
<b>▶ Ver</b> reproduce el tramo. <b>✓ Crear Short</b> guarda un proyecto nuevo, en formato Short, solo con ese tramo.
El video largo no cambia."""),
    "recorte_ia":("✂ Recortar sujeto con IA", """
Separa un personaje, una roca o un vehículo del fondo en TODO el clip (como la «Magic Mask» de Resolve).
La IA (SAM 2.1, en tu tarjeta gráfica) no mira solo el contorno: entiende el interior (texturas, piezas,
detalles) y recuerda los fotogramas anteriores, así lo sigue aunque gire o se tape un momento.<br><br>
<b>Cómo</b>: clic derecho en el clip → ✨ IA → «✂ Recortar sujeto / quitar el fondo…» (o la tarjeta de la pestaña
IA ✨). En el fotograma: <b>clic</b> = esto sí · <b>clic derecho</b> = esto no · <b>arrastrar</b> = recuadro.
«👁 Vista previa» enseña en azul lo que se quitará. «✂ Recortar» lo hace en segundo plano.<br>
<b>Quitar el fondo</b> (queda el sujeto, como una pantalla verde: se ve la pista de debajo) o <b>quitar el
sujeto</b>. «Bordes finos» afina pelo y telas. Después: ✨ IA → «Invertir» o «Quitar el recorte». Ctrl+Z."""),
    "silueta": ("👤 Identificar por silueta", """
Enséñale a un personaje (o un vehículo, una criatura) y te dice en qué momentos de TODOS tus videos aparece.<br><br>
<b>Enseñar</b>: clic derecho en un clip donde salga → ✨ IA → «👤 Enseñar este personaje (silueta)…» (o 🔎 Momentos →
«Lo que conoce la IA» → «👤 Enseñar…»). Clic encima de él: en verde verás la silueta que aprenderá; si le falta
algo (pelo, casco, arma), clic también ahí. Escribe su nombre y «✓ Guardar este ejemplo». Con 2–5 ejemplos
(mueve «Momento» para elegir otros instantes) lo reconoce mejor.<br>
<b>Buscar</b>: «🔎 Buscarlo en mis videos», o en 🔎 Momentos elige «👤 Nombre». Aprende sus colores propios (los
que tiene él y no su fondo) en su proporción, su tamaño, su figura y sus líneas. Es ligero: la primera vez
recorre cada video en miniatura (se guarda) y después es casi instantáneo."""),
    "capitulos": ("📝 Descripción para YouTube", """
La descripción completa del video, lista para pegar en YouTube: un párrafo inicial (solo para este proyecto), los
<b>capítulos</b> («0:00 Intro · 3:12 Jugabilidad…», que YouTube convierte en capítulos), los <b>créditos</b> de los clips
bajados, tu <b>pie fijo</b> (Ko-fi, redes…, para todos los videos) y <b>hashtags</b> sugeridos. Cada parte se activa o no.
Al exportar el video se guarda también «<video>.descripcion.txt» junto a él.<br>
Sale de tus <b>marcadores con nombre</b> (M en la línea de tiempo) o de los <b>temas de la narración</b>. Cambia
los nombres en la lista (se guardan en los marcadores) y quita los que no quieras.<br>
Reglas de YouTube (se aplican solas y te avisa): el primero en 0:00, al menos 3, cada uno de 10 s o más.<br>
Archivo → «📝 Descripción para YouTube (capítulos, créditos…)» (Ctrl+Mayús+K)."""),
    "voz_off": ("🎙 Grabar voz en off", """
Pon el cabezal donde empieza tu narración y pulsa ⏺ Grabar: tras la cuenta atrás el video se reproduce y grabas
mientras lo ves; ⏹ Parar (o Espacio) y la toma cae en la pista de voz, en ese sitio. Nunca tapa nada (si ahí ya hay
audio, va a otra pista). Ctrl+Z la quita de la línea de tiempo.<br>
Las tomas se guardan como WAV en «Grabaciones de voz» (junto a tu proyecto). Mientras grabas, el sonido del
proyecto se silencia para que no se cuele en el micrófono (se puede cambiar). Voz → «🎙 Grabar voz en off…»
(Ctrl+Mayús+R)."""),
    "dialogos": ("🗣 Diálogos sin ruido de fondo", """
La IA (Demucs, en tu tarjeta gráfica) separa las VOCES de la música del juego, las explosiones y el ambiente.<br>
· En un clip: clic derecho → ✨ IA → «🗣 Separar los diálogos del ruido de fondo» (y «Volver al sonido original»).<br>
· En el edit musical: «Opción de sonido» → «Solo los diálogos (sin el ruido de fondo)». La canción no se toca.<br>
Se hace una vez por archivo y se guarda (la siguiente vez es instantáneo)."""),
    "palabras_clave": ("🔑 Palabras clave", """
Escribe palabras o frases («Marcus, la traición, explosión») y te dice DÓNDE se dicen, gastando poco:
solo escucha donde hay voz (se salta la música, el ruido y el silencio), con un modelo pequeño, y deja la tarjeta
gráfica libre. Tolera acentos y pequeños errores («Marcos» encuentra «Marcus»). Lo escuchado se guarda: buscar
otra palabra en el mismo archivo es instantáneo (y si ya lo transcribiste en «Limpieza», usa eso).<br>
<b>Dónde</b>: pestaña IA ✨ → «🔑 Palabras clave», clic derecho en un clip (✨ IA) o en Medios.<br>
<b>Resultados</b>: doble clic = ir ahí · arrastrar a la línea de tiempo · «➕ Poner en el cabezal» ·
«📍 Marcadores» (si buscaste en la línea de tiempo).<br>
<b>Añadir en una palabra clave</b> (clic derecho en un clip o en Medios): «Por partes (recomendado)» pone un trozo
distinto en cada marca; «Entero» pone el video desde su principio hasta la siguiente marca.<br>
<b>🔗</b> = archivo enlazado desde una carpeta de tu PC (no se copia; quitarlo no borra nada de tu PC)."""),
    "clips_dijiste": ("🎬 Dijiste…", """
Lo que dices en la narración que parece un juego, una compañía o una palabra de tu vocabulario. Pulsa una palabra
para ver sus momentos. <b>Clic derecho</b>: «✓ Es palabra clave» (la guarda en el glosario) o «✕ No es palabra
clave» (no volverá a salir). Lo que internet confirma como juego lleva ✓; lo que dice que no lo es, va al final y
atenuado."""),
    "glosario": ("📖 Glosario de palabras clave", """
Dos listas: <b>Sí son palabras clave</b> (se buscan y se ofrecen en «Dijiste…» y en «✨ Crear de lo que dices») y
<b>No son palabras clave</b> (nunca salen). Añade una palabra o frase con su tipo si quieres (juego, saga, consola…).
«Quitar seleccionadas» la olvida de las dos listas. Se guarda al cerrar."""),
    "temas_tool":("◎ Temas: quedarme o mandar a Medios", """
Clic derecho en un tema → «◎ Temas: quedarme o mandar a Medios…». Marca los temas y elige:
<b>Quedarme solo con estos</b> (lo demás se quita y se junta) · <b>Mandar a Medios</b> (cada tramo, un video en
«Temas · <tema>», con el tema como palabra clave) · <b>Las dos cosas</b>. Ctrl+Z deshace lo de la línea de tiempo."""),
    "escenas": ("✂ Cortar en los cambios de escena", """
Clic derecho en un clip de video → «✂ Cortar en los cambios de escena». Sin IA: compara cada fotograma con el
anterior y corta donde la imagen cambia de golpe (un corte de cámara, otra escena, el menú de pausa).
«Cortes claros» o «También cambios más suaves». El sonido vinculado también se corta. Un solo Ctrl+Z."""),
    "convertir": ("🔁 Convertir", """
Menú <b>Convertir</b> (junto a Ayuda): arrastra videos o audios desde tus carpetas y elige <b>MP4</b> o
<b>MP3</b>. Si el video ya es H.264 con AAC, solo cambia el envoltorio (instantáneo, sin perder nada). Botones
rápidos para guardar en Escritorio, Descargas, Videos, Música o Exportados. El original nunca se toca.<br>
<b>⚡ Exportar rápido</b> (arriba a la derecha): YouTube / TikTok / Windows y la carpeta en dos clics; se exporta
en segundo plano."""),
    "visor_modos": ("Modos del visor", """
Abajo a la izquierda del visor (como en Resolve):<br>
<b>⤧ Transformar</b>: arrastrar = mover la capa · esquinas o Ctrl+rueda = tamaño · doble clic = pantalla completa.<br>
<b>✂ Recortar</b>: arrastra los bordes para esconder partes de la imagen (lo de fuera, transparente).<br>
<b>🔍 Zoom dinámico</b>: rectángulo VERDE = cómo empieza, ROJO = cómo acaba; el encuadre va suave de uno a otro.<br>
<b>✏ Anotaciones</b>: dibuja a mano (no sale al exportar); «Borrar las anotaciones de aquí».<br>
<b>Rueda</b> = acercar/alejar la vista · <b>rueda pulsada + arrastrar</b> = moverla · clic en el % = ajustar.<br>
<b>▦ Guías</b>: relaciones de aspecto de redes (1:1, 4:5, 9:16, 1.91, 16:9) y cine (1.33–2.40), áreas de
acción/título, centro, zona de Shorts, tercios y reglas."""),
}


def exec_menu(menu: QMenu, pos):
    """Abre un menú contextual (en una función aparte para poder probarlo automáticamente)."""
    return menu.exec(pos)


def set_help(widget: QWidget, key: str) -> QWidget:
    """Asocia una explicación a un control (y a todo lo que contiene)."""
    widget.setProperty("help_key", key)
    return widget


def help_key_for(widget: QWidget | None) -> str | None:
    w = widget
    while w is not None:
        key = w.property("help_key")
        if key:
            return str(key)
        w = w.parentWidget()
    return None


def show_help(key: str, parent: QWidget | None = None):
    build_help_box(key, parent).exec()


def build_help_box(key: str, parent: QWidget | None = None) -> QMessageBox:
    title, text = HELP.get(key, ("Ayuda", "Sin explicación todavía."))
    box = QMessageBox(parent)
    box.setWindowTitle(f"¿Qué hace esto? — {title}")
    box.setTextFormat(Qt.RichText)
    box.setText(f"<h3>{title}</h3>{text.strip()}")
    box.setIcon(QMessageBox.Information)
    return box


def add_help_action(menu: QMenu, key: str | None, parent: QWidget | None = None):
    """Añade «❓ ¿Qué hace esto?» a un menú contextual propio."""
    if key and key in HELP:
        menu.addSeparator()
        menu.addAction("❓ ¿Qué hace esto?", lambda: show_help(key, parent))


class HelpMenuFilter(QObject):
    """Filtro de toda la aplicación: el clic derecho muestra «❓ ¿Qué hace esto?»."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.ContextMenu or not isinstance(obj, QWidget):
            return False
        # Los paneles con menú propio (timeline, biblioteca…) añaden la ayuda ellos mismos
        w = obj
        while w is not None:
            if w.property("own_menu"):
                return False
            w = w.parentWidget()
        key = help_key_for(obj)
        if not key:
            return False
        # Campos de texto: su menú normal (copiar, pegar…) + la ayuda. En los de varias líneas el
        # clic llega a su "viewport", así que se mira también al padre. En los números, a su texto.
        editor = obj
        if not isinstance(editor, (QLineEdit, QTextEdit, QPlainTextEdit)) and \
                isinstance(obj.parentWidget(), (QTextEdit, QPlainTextEdit)):
            editor = obj.parentWidget()
        menu = None
        if isinstance(editor, (QLineEdit, QTextEdit, QPlainTextEdit)):
            menu = editor.createStandardContextMenu()
        elif isinstance(editor, QAbstractSpinBox) and editor.findChild(QLineEdit):
            menu = editor.findChild(QLineEdit).createStandardContextMenu()
        if menu is None:
            menu = QMenu(obj)
            menu.addAction("❓ ¿Qué hace esto?", lambda: show_help(key, obj.window()))
        else:
            add_help_action(menu, key, obj.window())
        exec_menu(menu, event.globalPos())
        menu.deleteLater()
        return True


def install(app: QApplication):
    if not getattr(app, "_help_filter", None):
        app._help_filter = HelpMenuFilter(app)
        app.installEventFilter(app._help_filter)
