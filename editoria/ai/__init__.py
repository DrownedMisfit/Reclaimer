"""
Módulos de IA. Cada uno es independiente: si uno falla o no está instalado,
el resto del programa sigue funcionando.

Plan de módulos (todos locales y gratuitos):
  transcription        Fase 1  voz -> texto con tiempos por palabra (Whisper)
  silence_detection    Fase 1  silencios y pausas largas (análisis de volumen)
  semantic_analysis    Fase 2  temas de la narración (modelo de lenguaje local)
  repetition_detection Fase 2  tomas repetidas y muletillas
  clip_classification  Fase 2  qué se ve en cada clip (modelo de visión local)
  broll_selection      Fase 2  sugerir clips para cada frase
  tracking             Fase 3  seguimiento de personajes/objetos
  editing_assistant    Fase 3  Modo Director (instrucciones en lenguaje natural)

Regla común: los módulos NUNCA modifican la timeline directamente.
Devuelven sugerencias; el usuario (o el modo automático, según sus reglas)
las aplica a través de ProjectController, con origin="ai", de forma que
todo es reversible y respeta los bloqueos.
"""
