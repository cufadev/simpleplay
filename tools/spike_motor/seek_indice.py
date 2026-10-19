"""Seek rápido en mp3: se indexan los frames (offsets) y se decodifica desde el frame justo."""
import sys, time
import numpy as np
import miniaudio

SR = 44100
F32 = miniaudio.SampleFormat.FLOAT32
BR1 = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0]
BR2 = [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160,0]
SRT = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}

def cabecera(b, i):
    """(longitud, muestras por frame, frecuencia) del frame que empieza en b[i], o None."""
    if i + 4 > len(b) or b[i] != 0xFF or (b[i+1] & 0xE0) != 0xE0:
        return None
    ver, capa = (b[i+1] >> 3) & 3, (b[i+1] >> 1) & 3
    if ver == 1 or capa != 1:          # solo MPEG 1/2/2.5, capa III
        return None
    br_i, sr_i, pad = b[i+2] >> 4, (b[i+2] >> 2) & 3, (b[i+2] >> 1) & 1
    if br_i in (0, 15) or sr_i == 3:
        return None
    sr = SRT[ver][sr_i]
    if ver == 3:
        return 144 * BR1[br_i] * 1000 // sr + pad, 1152, sr
    return 72 * BR2[br_i] * 1000 // sr + pad, 576, sr

def indexar(b):
    """Offsets de los frames de audio (sin el frame Xing/Info), muestras por frame y frecuencia."""
    i = 0
    if b[:3] == b"ID3":
        i = 10 + ((b[6] << 21) | (b[7] << 14) | (b[8] << 7) | b[9])
    offs, spf, sr = [], 1152, 44100
    n = len(b)
    while i < n - 4:
        h = cabecera(b, i)
        if h is None:                  # perdió el hilo: busca el próximo sincronismo
            j = b.find(b"\xff", i + 1)
            if j < 0: break
            i = j
            continue
        ln, spf, sr = h
        if not offs and (b"Xing" in b[i:i+60] or b"Info" in b[i:i+60]):
            i += ln; continue          # frame de información, no tiene audio
        offs.append(i)
        i += ln
    return offs, spf, sr

class Fuente(miniaudio.StreamableSource):
    def __init__(self, datos, desde):
        self.d, self.base, self.p = datos, desde, desde   # "el inicio" del stream es el frame pedido
    def read(self, n):
        r = self.d[self.p:self.p + n]; self.p += len(r); return r
    def seek(self, offset, origin):
        if origin == miniaudio.SeekOrigin.START: self.p = self.base + offset
        elif origin == miniaudio.SeekOrigin.CURRENT: self.p += offset
        return True

DELAY = 1105   # retardo del encoder (576) + del decodificador (529): lo que recorta el gapless

def primer_bloque(datos, offs, spf, sr, pos, block=4096):
    """Devuelve (mono float32 del bloque que empieza en `pos` muestras, segundos que tardó)."""
    t0 = time.perf_counter()
    kf = (pos + DELAY) // spf
    k0 = max(kf - 2, 0)                              # dos frames antes: llena la reserva de bits
    ps = k0 * spf - DELAY + spf if k0 else 0         # el decodificador no entrega el 1.er frame si arranca a mitad de archivo
    g = miniaudio.stream_any(Fuente(datos, offs[k0]), source_format=miniaudio.FileFormat.MP3,
                             output_format=F32, nchannels=2, sample_rate=sr, frames_to_read=block)
    descartar = max(pos - ps, 0)
    bufs, tengo = [], 0
    for blk in g:
        a = np.frombuffer(blk, dtype=np.float32).reshape(-1, 2)[:, 0]
        bufs.append(a); tengo += len(a)
        if tengo >= descartar + block: break
    x = np.concatenate(bufs)[descartar:descartar + block]
    return x, time.perf_counter() - t0

def desfase(x, ref):
    n = min(len(x), len(ref)); a = x[:n] - x[:n].mean(); b = ref[:n] - ref[:n].mean()
    c = np.fft.irfft(np.fft.rfft(a, 2*n) * np.conj(np.fft.rfft(b, 2*n)))
    k = int(np.argmax(c)); return k if k < n else k - 2*n

def comparar(ruta, puntos=(0.0, 0.05, 0.3, 0.6, 0.95)):
    datos = open(ruta, "rb").read()
    t0 = time.perf_counter(); offs, spf, sr = indexar(datos); ti = time.perf_counter() - t0
    dur = len(offs) * spf / sr
    print(f"{ruta.split('/')[-1][:50]}: {len(offs)} frames, {dur/60:.1f} min, {spf} muestras/frame, {sr} Hz, índice {ti*1000:.0f} ms")
    for fr in puntos:
        pos = int(fr * (dur - 3) * sr)
        x, dt = primer_bloque(datos, offs, spf, sr, pos)
        ref = np.frombuffer(next(miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=sr,
                            frames_to_read=4096, seek_frame=pos)), dtype=np.float32).reshape(-1, 2)[:, 0]
        print(f"   {fr*100:4.0f}% ({pos/sr:7.1f} s): {1000*dt:5.1f} ms, desfase {desfase(x, ref):+d} muestras")

if __name__ == "__main__":
    for r in sys.argv[1:]:
        comparar(r)
