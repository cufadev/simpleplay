"""Genera los mp3 sintéticos para probar el motor de audio (van a tests/corpus/, que no se sube).

    python tests/generar_corpus.py

- tono_44k.mp3, tono_48k.mp3, mono_44k.mp3: senoides de 10 s en cada formato; vbr_4min.mp3: un barrido VBR de 4 min; tono_bajo.mp3: la misma senoide a -34 dBFS.
- largo_60min.mp3: un barrido (chirp) de 60 min cuya frecuencia vale 200 + t Hz en el segundo t, así
  la frecuencia dominante de cualquier tramo dice en qué segundo está (sirve para probar saltos).
- gapless_a.mp3 / gapless_b.mp3: una senoide continua de 20 s cortada en dos mitades exactas de 10 s
  y codificada por separado con LAME (que escribe el retardo y el relleno en la etiqueta).
"""
import subprocess
import sys
from pathlib import Path

DESTINO = Path(__file__).parent / "corpus"
DESTINO.mkdir(exist_ok=True)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def lavfi(expr, dur, rate, canales, salida, extra=("-b:a", "128k")):
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc={expr}:s={rate}:d={dur}:c={'mono' if canales == 1 else 'stereo'}",
           "-codec:a", "libmp3lame", *extra, str(DESTINO / salida))


lavfi("0.5*sin(2*PI*440*t)", 10, 44100, 2, "tono_44k.mp3")
lavfi("0.5*sin(2*PI*440*t)", 10, 48000, 2, "tono_48k.mp3")
lavfi("0.02*sin(2*PI*440*t)", 10, 44100, 2, "tono_bajo.mp3")   # muy suave (-34 dBFS)
lavfi("0.5*sin(2*PI*440*t)", 10, 44100, 1, "mono_44k.mp3")
lavfi("0.5*sin(2*PI*(200*t+0.5*t*t))", 3600, 44100, 2, "largo_60min.mp3")
lavfi("0.4*sin(2*PI*(300*t+8*t*t))", 240, 44100, 2, "vbr_4min.mp3", extra=("-q:a", "2"))  # VBR

# gapless: se corta el WAV continuo en un número exacto de muestras y se codifica cada mitad
wav = DESTINO / "_continuo.wav"
ffmpeg("-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*440*t):s=44100:d=20:c=stereo", str(wav))
ffmpeg("-i", str(wav), "-af", "atrim=end_sample=441000", "-codec:a", "libmp3lame", "-b:a", "128k",
       str(DESTINO / "gapless_a.mp3"))
ffmpeg("-i", str(wav), "-af", "atrim=start_sample=441000,asetpts=PTS-STARTPTS", "-codec:a", "libmp3lame",
       "-b:a", "128k", str(DESTINO / "gapless_b.mp3"))
print("corpus listo en", DESTINO)
