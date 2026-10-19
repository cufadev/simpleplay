# Prototipos de la Fase 1 (motor de audio con miniaudio)

Descartables: sirvieron para decidir si valía la pena reemplazar pygame. Se corren con el corpus de
`tests/generar_corpus.py`. Resultados (2026-10-19, corona y notebook i5-7200U):

- `seek_gapless.py`: `stream_file(seek_frame=...)` es exacto pero lineal: 1,5 s para saltar al minuto 58.
  El gapless con etiqueta LAME funciona (cada mitad da exactamente 441000 muestras, sin hueco).
- `seek_pygame.py`: línea base de pygame, 4 a 25 ms para saltar en el mismo archivo.
- `seek_indice.py`: indexar los frames (77 ms para 138 mil frames) y decodificar desde el frame justo
  baja el salto a 0,2 ms. Error de 0 a 2 frames en archivos reales; falta leer el retardo de la etiqueta LAME.
- `cortes.py`: dispositivo miniaudio real con la interfaz kiosk a pleno y carga pesada: sin cortes con
  buffer de 200 y de 50 ms; el callback tarda menos de 1 ms (pico de 17 ms bajo estrés); 3 a 5 % de CPU.
