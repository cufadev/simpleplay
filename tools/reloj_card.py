#!/usr/bin/env python3
"""Reloj en tarjeta (estilo widget de iOS): cuadrado blanco redondeado, hora en Bebas Neue y marquitas en el borde.

Arrastrar con el botón izquierdo para mover, clic derecho o Esc para cerrar.
Uso: .venv/bin/python tools/reloj_card.py [--24h] [--segundos]
"""
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QTime
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QApplication, QWidget

FUENTE = Path(__file__).resolve().parent.parent / "docs" / "fonts" / "bebas-neue.woff2"
LADO = 240
MARGEN = 20  # aire para la sombra


class RelojCard(QWidget):
    def __init__(self, h24=False, segundos=False):
        super().__init__()
        self.h24, self.segundos = h24, segundos
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(LADO + 2 * MARGEN, LADO + 2 * MARGEN)
        fid = QFontDatabase.addApplicationFont(str(FUENTE))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        self.familia = fams[0] if fams else "Impact"
        self.arrastre = None
        t = QTimer(self)
        t.timeout.connect(self.update)
        t.start(500)

    def _texto(self):
        h = QTime.currentTime()
        if self.segundos:
            return h.toString("HH:mm:ss") if self.h24 else f"{(h.hour() % 12) or 12}:{h.toString('mm:ss')}"
        return h.toString("HH:mm") if self.h24 else f"{(h.hour() % 12) or 12}:{h.toString('mm')}"

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        card = QRectF(MARGEN, MARGEN, LADO, LADO)

        # sombra: capas translúcidas cada vez más chicas
        for i in range(MARGEN, 0, -1):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, int(2 + 26 * (1 - i / MARGEN) ** 2)))
            p.drawRoundedRect(card.adjusted(-i, -i + 6, i, i + 6), 44 + i, 44 + i)

        # tarjeta blanca
        p.setBrush(QColor(247, 247, 247))
        p.drawRoundedRect(card, 44, 44)

        # marquitas: 60 alrededor del rectángulo redondeado, las de cada 5 un poco más largas
        borde = QPainterPath()
        borde.addRoundedRect(card.adjusted(13, 13, -13, -13), 32, 32)
        p.setPen(QPen(QColor(70, 70, 70), 1.4, Qt.SolidLine, Qt.RoundCap))
        n = 60
        for k in range(n):
            pt = borde.pointAtPercent(((k / n) + 0.25 + 0.0) % 1.0)  # arranca arriba al centro
            ang = borde.angleAtPercent(((k / n) + 0.25) % 1.0)
            largo = 7 if k % 5 == 0 else 3.5
            # normal hacia adentro (el path va en sentido antihorario en pantalla)
            import math
            nx, ny = -math.sin(math.radians(ang)), -math.cos(math.radians(ang))
            p.drawLine(pt, QPointF(pt.x() + nx * largo * -1, pt.y() + ny * largo * -1))

        # hora
        f = QFont(self.familia)
        f.setPixelSize(112 if not self.segundos else 74)
        p.setFont(f)
        p.setPen(QColor(30, 30, 30))
        p.drawText(card, Qt.AlignCenter, self._texto())

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.close()
        else:
            # el compositor mueve la ventana (en Wayland move() no funciona); si no hay soporte, arrastre manual
            if not (self.windowHandle() and self.windowHandle().startSystemMove()):
                self.arrastre = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.arrastre is not None:
            self.move(e.globalPosition().toPoint() - self.arrastre)

    def mouseReleaseEvent(self, e):
        self.arrastre = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = RelojCard(h24="--24h" in sys.argv, segundos="--segundos" in sys.argv)
    w.show()
    if "--captura" in sys.argv:
        QTimer.singleShot(400, lambda: (w.grab().save("/tmp/reloj.png"), app.quit()))
    sys.exit(app.exec())
