"""Prueba de cortes: dispositivo miniaudio real (ganancia 0) mientras la interfaz de la kiosk trabaja a pleno."""
import os, sys, time, glob, tempfile
os.environ.update(QT_QPA_PLATFORM="offscreen", SDL_AUDIODRIVER="dummy", SIMPLEPLAY_NO_MPRIS="1", SIMPLEPLAY_UI="1",
                  XDG_CONFIG_HOME=tempfile.mkdtemp(), XDG_DATA_HOME=tempfile.mkdtemp())
KIOSK, CORPUS, SEG = sys.argv[1], sys.argv[2], int(sys.argv[3])
BUF = int(sys.argv[4]) if len(sys.argv) > 4 else 200
CARGA = (sys.argv[5] if len(sys.argv) > 5 else "ui") == "ui"
sys.path.insert(0, KIOSK)
import numpy as np, miniaudio
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

SR, F32 = 44100, miniaudio.SampleFormat.FLOAT32
anillo = np.zeros(32768, dtype=np.float32); pos = [0]
t_prev = [None]; gaps = []; proc = []

def callback():
    stream = miniaudio.stream_file(f"{CORPUS}/vbr_4min.mp3", output_format=F32, nchannels=2, sample_rate=SR, frames_to_read=1024)
    req = yield b""
    while True:
        t0 = time.perf_counter()
        if t_prev[0] is not None: gaps.append(t0 - t_prev[0])
        x = np.frombuffer(stream.send(req), dtype=np.float32).reshape(-1, 2)
        mono = x.mean(axis=1)                                  # lo que haría el motor: copiar al anillo del espectro
        if len(mono) > len(anillo): mono = mono[-len(anillo):]
        n = len(mono); i = pos[0] % len(anillo)
        if i + n <= len(anillo): anillo[i:i+n] = mono
        else: k = len(anillo) - i; anillo[i:] = mono[:k]; anillo[:n-k] = mono[k:]
        pos[0] += n
        out = (x * 0.0)                                        # silencio: la prueba no suena
        t1 = time.perf_counter(); proc.append(t1 - t0); t_prev[0] = t1
        req = yield out

app = QApplication([])
if CARGA:
    import simpleplay as S
    w = S.Player(); w.resize(1024, 768)
    w.agregar(sorted(glob.glob(f"{CORPUS}/*.mp3"))[:6]); w.show()
    QTimer.singleShot(300, lambda: w.reproducir(0))
    def mover():  # simula el uso: salta, abre y cierra
        w.saltar(0.5)
    QTimer.singleShot(20000, mover)
    if len(sys.argv) > 6 and sys.argv[6] == "estres":   # trabajo pesado de la interfaz mientras suena
        carpeta = tempfile.mkdtemp(); muchos = []
        for i in range(800):
            d = f"{carpeta}/t{i:04d}.mp3"; os.symlink(f"{CORPUS}/tono_44k.mp3", d); muchos.append(d)
        def estres():
            t = time.perf_counter(); w.agregar(muchos); print(f"  [estrés] agregar 800 temas: {time.perf_counter()-t:.2f} s en el hilo de la interfaz")
            t = time.perf_counter(); w.ordenar("titulo"); w.ordenar("artista"); w._filtrar("t07"); w._filtrar("")
            print(f"  [estrés] ordenar x2 y filtrar x2: {time.perf_counter()-t:.2f} s")
        QTimer.singleShot(10000, estres)
dev = miniaudio.PlaybackDevice(output_format=F32, nchannels=2, sample_rate=SR, buffersize_msec=BUF)
g = callback(); next(g); dev.start(g)
c0, w0 = time.process_time(), time.perf_counter()
QTimer.singleShot(SEG * 1000, app.quit)
app.exec()
cpu = (time.process_time() - c0) / (time.perf_counter() - w0)
dev.stop()
gp = np.array(gaps[5:]) * 1000; pr = np.array(proc[5:]) * 1000
print(f"buffer {BUF} ms | carga {'interfaz kiosk completa' if CARGA else 'ninguna'} | {SEG} s | {len(gp)} llamadas")
print(f"  intervalo entre callbacks: mediana {np.median(gp):.1f} ms, p99 {np.percentile(gp,99):.1f} ms, MÁXIMO {gp.max():.1f} ms")
print(f"  tiempo dentro del callback: mediana {np.median(pr):.2f} ms, MÁXIMO {pr.max():.2f} ms")
print(f"  intervalos > 1,5 x mediana: {int((gp > 1.5*np.median(gp)).sum())} | > 2 x mediana (probable corte): {int((gp > 2*np.median(gp)).sum())}")
print(f"  CPU de todo el proceso (interfaz + audio): {cpu*100:.0f}% de un núcleo")
