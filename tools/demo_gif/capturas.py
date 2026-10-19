"""Genera las capturas y el GIF del README y de la página, con la aplicación real (sin pantalla ni sonido).

    python tools/demo_gif/capturas.py                       (usa ~/Música/Tu Cuerpo.mp3)
    TEMA=/ruta/otro.mp3 python tools/demo_gif/capturas.py

Escribe docs/screenshots/{player,spectrum,playlist,compact}.png (al doble de resolución, con la sombra y el fondo
transparente) y docs/demo.gif + docs/demo.mp4. Los otros temas de la lista son ficticios (se generan acá).
El tema que se pasa se copia a una carpeta temporal: el original no se toca.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
TEMA = Path(os.environ.get("TEMA", Path.home() / "Música" / "Tu Cuerpo.mp3"))
TMP = Path(tempfile.mkdtemp(prefix="simpleplay-capturas-"))
MODO = sys.argv[1] if len(sys.argv) > 1 else "todo"


def preparar_temas():
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, APIC
    from mutagen.mp3 import MP3
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
    TMP.mkdir(exist_ok=True)
    real = TMP / "01 Tu Cuerpo.mp3"
    shutil.copy(TEMA, real)
    t = ID3(real)
    t.add(TPE1(encoding=3, text=str(t.get("TPE1", "")).replace(" - Topic", "")))   # el "- Topic" es un resto de YouTube
    t.save()
    falsos = [("Night Drive", "Lumen Park", "Neon Roads", ("#1b1464", "#ff4e01"), [220, 277, 330]),
              ("Paper Moons", "The Quiet Hours", "Slow Light", ("#134e5e", "#f7b733"), [196, 247, 294]),
              ("Static Garden", "Mira Voss", "Greenhouse", ("#0f2027", "#2ecc71"), [262, 330, 392]),
              ("Low Tide", "Harbor & Pine", "Salt", ("#42275a", "#ff9a8b"), [175, 220, 262])]
    for n, (tit, art, alb, (c1, c2), notas) in enumerate(falsos, 2):
        ruta = TMP / f"{n:02d} {tit}.mp3"
        expr = "+".join(f"0.18*sin(2*PI*{f}*t)*(0.6+0.4*sin(2*PI*{0.4 + 0.15 * i}*t))" for i, f in enumerate(notas))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc={expr}:s=44100:d=60",
                        "-b:a", "128k", str(ruta)], check=True)
        im = QImage(500, 500, QImage.Format_RGB32)
        p = QPainter(im)
        g = QLinearGradient(0, 0, 500, 500)
        g.setColorAt(0, QColor(c1))
        g.setColorAt(1, QColor(c2))
        p.fillRect(im.rect(), g)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawEllipse(100, 100, 300, 300)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawEllipse(190, 190, 120, 120)
        p.end()
        ba = QByteArray()
        b = QBuffer(ba)
        b.open(QIODevice.WriteOnly)
        im.save(b, "JPG", 90)
        m = MP3(ruta)
        if m.tags is None:
            m.add_tags()
        for fr in (TIT2(encoding=3, text=tit), TPE1(encoding=3, text=art), TALB(encoding=3, text=alb),
                   APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=bytes(ba))):
            m.tags.add(fr)
        m.save()
    return sorted(TMP.glob("*.mp3"))


def correr(modo):
    """Una pasada con la aplicación: modo 'png' (x2, capturas sueltas) o 'gif' (x1, cuadros)."""
    os.environ.update(QT_QPA_PLATFORM="offscreen", SIMPLEPLAY_AUDIO="null", SIMPLEPLAY_NO_MPRIS="1", LANGUAGE=os.environ.get("IDIOMA", "en"),
                      XDG_CONFIG_HOME=str(TMP / "cfg"), XDG_DATA_HOME=str(TMP / "data"),
                      QT_SCALE_FACTOR="2")
    sys.path.insert(0, str(RAIZ))
    from PySide6.QtCore import QRectF, QTimer
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
    from PySide6.QtWidgets import QApplication
    import simpleplay as S

    app = QApplication([])
    temas = preparar_temas()
    w = S.Player()
    w.agregar([str(t) for t in temas])
    w.show()
    destino = RAIZ / "docs" / "screenshots"
    destino.mkdir(parents=True, exist_ok=True)
    agenda = []

    def en(seg, f):
        agenda.append((seg, f))

    if modo == "png":
        en(0.8, lambda: w.reproducir(0))
        en(1.6, lambda: w.saltar(0.30))
        en(3.4, lambda: w.grab().save(str(destino / "player.png")))
        en(3.5, w.alternar_barras)
        en(5.6, lambda: w.grab().save(str(destino / "spectrum.png")))
        en(5.7, w.alternar_barras)
        en(6.4, lambda: w.alternar_lista(True))
        en(7.6, lambda: w.grab().save(str(destino / "playlist.png")))
        en(7.7, lambda: w.alternar_lista(False))
        en(8.4, lambda: w.poner_compacto(True, animar=False))
        en(9.2, lambda: w.grab().save(str(destino / "compact.png")))
        fin = 9.8
    else:
        cuadros = TMP / "cuadros"
        cuadros.mkdir(exist_ok=True)
        CW, CH = 460, 700
        n = [0]

        def foto():
            pm = w.grab()
            lienzo = QImage(CW * 2, CH * 2, QImage.Format_RGB32)   # al doble de resolución, como la captura
            lienzo.setDevicePixelRatio(2)
            p = QPainter(lienzo)
            g = QLinearGradient(0, 0, CW, CH)                       # un escenario oscuro: se ve bien en la página clara y en la oscura
            g.setColorAt(0, QColor("#2c2f37"))
            g.setColorAt(1, QColor("#15161a"))
            p.fillRect(QRectF(0, 0, CW, CH), g)
            ancho = pm.width() / pm.devicePixelRatio()               # tamaño lógico (la captura es de doble resolución)
            p.drawPixmap(round((CW - ancho) / 2), 20, pm)
            p.end()
            lienzo.save(str(cuadros / f"f{n[0]:04d}.png"))
            n[0] += 1

        reloj = QTimer()
        reloj.timeout.connect(foto)
        reloj.start(50)
        en(0.8, lambda: w.reproducir(0))
        en(1.6, lambda: w.saltar(0.30))
        en(3.5, w.alternar_barras)
        en(7.5, w.alternar_barras)
        en(8.6, lambda: w.poner_compacto(True))
        en(11.6, lambda: w.poner_compacto(False))
        en(12.8, lambda: w.alternar_lista(True))
        for i in range(1, 5):
            en(13.8 + i * 0.28, lambda i=i: w.buscador.setText("cuer"[:i]))
        en(16.4, lambda: w.buscador.setText(""))
        en(17.2, lambda: w.alternar_lista(False))
        fin = 19.6
    for seg, f in agenda:
        QTimer.singleShot(int(seg * 1000), f)
    QTimer.singleShot(int(fin * 1000), app.quit)
    app.exec()
    w.close()
    w.motor.cerrar()
    return TMP / "cuadros" if modo == "gif" else None


if __name__ == "__main__":
    if MODO in ("png", "gif"):                      # una pasada (se llama a sí mismo para cada modo)
        carpeta = correr(MODO)
        if carpeta:
            cuadros = len(list(carpeta.glob("*.png")))
            print(f"{cuadros} cuadros en {carpeta}")
            print(f"CARPETA={carpeta}")
        sys.exit(0)
    for modo in ("png", "gif"):
        r = subprocess.run([sys.executable, __file__, modo], capture_output=True, text=True,
                           env={**os.environ, "TEMA": str(TEMA)})
        sys.stderr.write("\n".join(l for l in r.stderr.splitlines() if "propagateSizeHints" not in l) + "\n")
        if modo == "gif":
            carpeta = [l.split("=", 1)[1] for l in r.stdout.splitlines() if l.startswith("CARPETA=")][-1]
            docs = RAIZ / "docs"
            filtro = "scale=720:-2:flags=lanczos"   # los cuadros son de 920x1400
            filtro_gif = "scale=360:-1:flags=lanczos"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "20", "-start_number", "6", "-i",
                            f"{carpeta}/f%04d.png", "-vf", f"{filtro_gif},fps=15,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
                            "[b][p]paletteuse=dither=bayer:bayer_scale=4", str(docs / "demo.gif")], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "20", "-start_number", "6", "-i",
                            f"{carpeta}/f%04d.png", "-vf", filtro, "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-an", str(docs / "demo.mp4")], check=True)
            print("listo:", docs / "demo.gif", f"({(docs / 'demo.gif').stat().st_size // 1024} KB)")
            shutil.rmtree(Path(carpeta).parent, ignore_errors=True)
    shutil.rmtree(TMP, ignore_errors=True)
