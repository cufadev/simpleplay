"""La app con MPRIS activo, para que `probar.sh` la maneje por D-Bus (no se corre sola)."""
import os, sys
os.environ.update(QT_QPA_PLATFORM="offscreen", SIMPLEPLAY_AUDIO="null", QT_NO_XDG_DESKTOP_PORTAL="1",
                  XDG_CONFIG_HOME=os.environ["TMPCFG"], LANGUAGE="es")
os.environ.pop("SIMPLEPLAY_NO_MPRIS", None)
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import simpleplay as S
C = os.path.join(RAIZ, "tests", "corpus")
app = QApplication([]); w = S.Player(); w.agregar([f"{C}/tono_44k.mp3", f"{C}/mono_44k.mp3"]); w.show()
w.reproducir(0)
QTimer.singleShot(14000, lambda: (print("ESTADO FINAL: actual", w.actual, "| pausado", w.pausado, "| motor", os.path.basename(w.motor.ruta or ""), "| pos %.1f" % w.posicion(), flush=True), app.quit()))
app.exec()
