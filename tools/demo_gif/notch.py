"""Genera el GIF y el MP4 del notch con la aplicación real (sin pantalla ni sonido), como capturas.py.

    .venv/bin/python tools/demo_gif/notch.py

Escribe docs/notch.gif y docs/notch.mp4. Muestra: la tarjeta pasa a píldora y se pega arriba como notch, se
esconde sola dejando un borde fino, baja al tocar el borde, cambia de tema y se suelta. El "escritorio" de
fondo es ficticio (una ventana de mentira para que se vea que el notch queda por encima); los temas también.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capturas as C   # noqa: E402  (reusa los temas ficticios; capturas.py solo corre en __main__)

RAIZ, TMP = C.RAIZ, C.TMP
ANCHO, ALTO = 640, 400          # recorte de la pantalla de 800 x 800 donde ocurre todo (el notch queda centrado)
X0 = 80


def correr():
    os.environ.update(QT_QPA_PLATFORM="offscreen", SIMPLEPLAY_AUDIO="null", SIMPLEPLAY_NO_MPRIS="1", LANGUAGE=os.environ.get("IDIOMA", "en"),
                      XDG_CONFIG_HOME=str(TMP / "cfg"), XDG_DATA_HOME=str(TMP / "data"))
    sys.path.insert(0, str(RAIZ))
    from PySide6.QtCore import QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
    from PySide6.QtWidgets import QApplication
    import simpleplay as S

    app = QApplication([])
    temas = C.preparar_temas()
    w = S.Player()
    w.agregar([str(t) for t in temas])
    w.show()
    w.move(214, 40)
    w.underMouse = lambda: False            # en offscreen siempre dice True: acá el mouse está afuera (se esconde solo)
    cuadros = TMP / "cuadros"
    cuadros.mkdir(exist_ok=True)
    n = [0]

    def escenario():
        im = QImage(ANCHO, ALTO, QImage.Format_RGB32)
        p = QPainter(im)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, ANCHO, ALTO)             # fondo de escritorio oscuro
        g.setColorAt(0, QColor("#2a2d3a"))
        g.setColorAt(1, QColor("#14151b"))
        p.fillRect(QRectF(0, 0, ANCHO, ALTO), g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1d1f27"))                       # una ventana cualquiera, para ver que el notch queda encima
        p.drawRoundedRect(QRectF(60, 30, ANCHO - 120, ALTO - 30), 10, 10)
        p.setBrush(QColor("#272a35"))
        p.drawRoundedRect(QRectF(60, 30, ANCHO - 120, 34), 10, 10)
        p.setBrush(QColor("#ff5f57"))
        p.drawEllipse(QRectF(76, 42, 10, 10))
        p.setBrush(QColor("#febc2e"))
        p.drawEllipse(QRectF(94, 42, 10, 10))
        p.setBrush(QColor("#28c840"))
        p.drawEllipse(QRectF(112, 42, 10, 10))
        p.setBrush(QColor("#323645"))
        for i, ancho in enumerate((380, 300, 440, 220, 360, 260, 400, 320)):
            p.drawRoundedRect(QRectF(86, 96 + i * 34, ancho, 10), 5, 5)
        p.end()
        return im
    fondo = escenario()

    def foto():
        im = fondo.copy()
        p = QPainter(im)
        g = w.geometry()
        pm = w.grab()
        p.drawPixmap(g.x() - X0, g.y(), pm)
        p.end()
        im.save(str(cuadros / f"f{n[0]:04d}.png"))
        n[0] += 1

    reloj = QTimer()
    reloj.timeout.connect(foto)
    reloj.start(50)
    agenda = [
        (0.6, lambda: w.reproducir(0)),
        (1.4, lambda: w.saltar(0.30)),
        (2.4, lambda: w.poner_notch(True)),     # tarjeta -> píldora -> notch
        (8.0, lambda: w._mostrar()),            # el mouse toca el borde: baja (se esconde sola unos 1,8 s antes)
        (9.6, w.siguiente),
        (11.6, lambda: w.poner_notch(False)),   # soltarlo
    ]
    for seg, f in agenda:
        QTimer.singleShot(int(seg * 1000), f)
    QTimer.singleShot(13500, app.quit)
    app.exec()
    w.close()
    w.motor.cerrar()
    return cuadros


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pasada":
        carpeta = correr()
        print(f"CARPETA={carpeta}")
        sys.stdout.flush()
        os._exit(0)
    r = subprocess.run([sys.executable, __file__, "pasada"], capture_output=True, text=True, env=os.environ)
    sys.stderr.write("\n".join(l for l in r.stderr.splitlines() if "propagateSizeHints" not in l) + "\n")
    carpeta = [l.split("=", 1)[1] for l in r.stdout.splitlines() if l.startswith("CARPETA=")][-1]
    docs = RAIZ / "docs"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "20", "-start_number", "6", "-i", f"{carpeta}/f%04d.png",
                    "-vf", "fps=15,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    str(docs / "notch.gif")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "20", "-start_number", "6", "-i", f"{carpeta}/f%04d.png",
                    "-vf", "scale=1280:-2:flags=lanczos", "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", str(docs / "notch.mp4")], check=True)
    print("listo:", docs / "notch.gif", f"({(docs / 'notch.gif').stat().st_size // 1024} KB)", docs / "notch.mp4")
    shutil.rmtree(Path(carpeta).parent, ignore_errors=True)
    shutil.rmtree(TMP, ignore_errors=True)
