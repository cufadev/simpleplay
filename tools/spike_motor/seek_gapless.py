import sys, time
import numpy as np
import miniaudio
C = sys.argv[1]
SR = 44100
F32 = miniaudio.SampleFormat.FLOAT32

def stream(path, seek=0, block=4096, rate=SR):
    return miniaudio.stream_file(path, output_format=F32, nchannels=2, sample_rate=rate, frames_to_read=block, seek_frame=seek)

print("== (b) SEEK en el mp3 de 60 min (chirp: frecuencia = 200 + segundo)")
for seg in (0, 600, 1800, 2700, 3500):
    t0 = time.perf_counter()
    g = stream(f"{C}/largo_60min.mp3", seek=seg * SR)
    bloque = np.frombuffer(next(g), dtype=np.float32).reshape(-1, 2)[:, 0]
    dt = time.perf_counter() - t0
    # frecuencia dominante del primer bloque -> segundo real
    n = len(bloque); esp = np.abs(np.fft.rfft(bloque * np.hanning(n)))
    f = np.argmax(esp) * SR / n
    print(f"  pedido {seg:5d} s -> primer bloque en {dt*1000:7.0f} ms | frecuencia {f:7.0f} Hz => segundo ~{f-200:6.0f}")

print("== (c) GAPLESS: dos mitades de una senoide continua, cada una con etiqueta LAME")
def todo(path):
    out = []
    for b in stream(path):
        out.append(np.frombuffer(b, dtype=np.float32).reshape(-1, 2)[:, 0].copy())
    return np.concatenate(out)
a, b = todo(f"{C}/gapless_a.mp3"), todo(f"{C}/gapless_b.mp3")
print(f"  muestras de A: {len(a)} (ideal 441000, diferencia {len(a)-441000:+d}); de B: {len(b)} (diferencia {len(b)-441000:+d})")
x = np.concatenate([a, b])
t = np.arange(len(x)) / SR
ref = 0.5 * np.sin(2 * np.pi * 440 * t)
j = len(a)  # punto de empalme
def error(desde, hasta):
    seg = slice(desde, hasta)
    return float(np.sqrt(np.mean((x[seg] - ref[seg]) ** 2)))
print(f"  error RMS lejos del empalme: {error(200000, 300000):.4f} | alrededor del empalme (±1000): {error(j-1000, j+1000):.4f}")
salto = np.abs(np.diff(x[j-50:j+50])).max()
print(f"  mayor salto entre muestras vecinas junto al empalme: {salto:.4f} (una senoide limpia no pasa de {2*np.pi*440/SR*0.5:.4f})")
silencio = int(np.sum(np.abs(x[j-3000:j+3000]) < 1e-4))
print(f"  muestras en silencio (|x|<1e-4) alrededor del empalme: {silencio} (una senoide pasa por cero unas {int(6000*440*2/SR)} veces, sin quedarse ahí)")
