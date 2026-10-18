# simpleplay - a small, clean mp3 player
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
import contextlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # sin el cartel de bienvenida
import pygame
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from PySide6.QtCore import (Qt, QTimer, QRectF, QPointF, QSize, Signal, QLocale,
                            QStandardPaths, QVariantAnimation, QEasingCurve)
from PySide6.QtGui import (QIcon, QFont, QFontMetrics, QPainter, QColor, QPixmap, QImage, QLinearGradient,
                           QPainterPath, QPolygonF, QPen)
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QSlider, QAbstractButton, QListWidget,
                               QFileDialog, QFrame, QLayout, QMenu, QSizePolicy,
                               QStackedLayout, QGraphicsOpacityEffect)

VERSION = "1.0"
NARANJA = "#ff4e01"
@contextlib.contextmanager
def sin_stderr():
    """Silencia stderr a nivel de descriptor mientras dura el bloque.

    libmpg123 (dentro de SDL_mixer) imprime "No comment text / valid description?" por cada
    etiqueta ID3 de comentario mal formada, algo común en mp3 bajados con yt-dlp. Es solo una
    advertencia, pero sale por C, así que hay que redirigir el descriptor 2.
    """
    sys.stderr.flush()
    guardado = os.dup(2)
    nulo = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(nulo, 2)
        yield
    finally:
        os.dup2(guardado, 2)
        os.close(guardado)
        os.close(nulo)


def recurso(ruta):
    """Ruta a un archivo incluido con la app (también dentro del paquete PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(base / ruta)


ESTADO = Path.home() / ".config" / "simpleplay" / "estado.json"
ESTADO_ANTIGUO = Path.home() / ".config" / "mp3player" / "estado.json"  # nombre previo a simpleplay

# interfaz en español si el sistema está en español, en inglés en cualquier otro caso
ES = QLocale.system().language() == QLocale.Language.Spanish


def tr(es, en):
    return es if ES else en

ESTILO = """
QSlider::groove:horizontal { height: 3px; background: rgba(255,255,255,70); border-radius: 1px; }
QSlider::sub-page:horizontal { background: white; border-radius: 1px; }
QSlider::handle:horizontal { background: white; width: 9px; height: 9px; margin: -3px 0; border-radius: 4px; }
QLabel { color: white; background: transparent; }
QFrame#pill { background: rgba(0,0,0,95); border-radius: 18px; }
QFrame#panel { background: rgba(22,22,24,235); border-radius: 18px; }
QListWidget { background: transparent; color: white; border: none; padding: 0; outline: 0; }
QListWidget::item { padding: 6px 8px; border-radius: 8px; }
QListWidget::item:selected { background: rgba(255,78,1,190); color: white; }
"""


def fmt(s):
    s = max(int(s), 0)
    return f"{s // 60}:{s % 60:02d}"


def leer_meta(path):
    titulo, artista, portada = Path(path).stem, "", None
    try:
        t = ID3(path)
        if t.get("TIT2"):
            titulo = str(t["TIT2"])
        if t.get("TPE1"):
            artista = str(t["TPE1"])
        for k in t:
            if k.startswith("APIC"):
                portada = t[k].data
                break
    except Exception:
        pass
    return titulo, artista, portada


def circular(pix, d):
    out = QPixmap(d, d)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, d, d)
    p.setClipPath(path)
    esc = pix.scaled(d, d, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    p.drawPixmap((d - esc.width()) // 2, (d - esc.height()) // 2, esc)
    p.end()
    return out


class IconButton(QAbstractButton):
    def __init__(self, kind, size=44):
        super().__init__()
        self.kind = kind
        self.t = 1.0 if kind == "pause" else 0.0  # 0 = play, 1 = pausa
        # estados del fondo, todos 0..1 y animados: mouse encima, presionado, activado
        self.hov = self.pre = self.chk = 0.0
        self._anims = {}
        for n in ("hov", "pre", "chk"):
            a = QVariantAnimation(self)
            a.setEasingCurve(QEasingCurve.OutCubic)
            a.valueChanged.connect(lambda v, n=n: self._set(n, v))
            self._anims[n] = a
        self.toggled.connect(lambda on: self._animar("chk", 1.0 if on else 0.0, 260))
        self.pressed.connect(lambda: self._animar("pre", 1.0, 90))
        self.released.connect(lambda: self._animar("pre", 0.0, 220))
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._mezclar)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)

    def _mezclar(self, v):
        self.t = v
        self.update()

    def set_kind(self, kind):
        """Cambia el ícono; play <-> pausa se funden girando un poco."""
        if kind == self.kind:
            return
        viejo, self.kind = self.kind, kind
        if {viejo, kind} == {"play", "pause"}:
            self.anim.stop()
            self.anim.setStartValue(self.t)
            self.anim.setEndValue(1.0 if kind == "pause" else 0.0)
            self.anim.start()
        else:
            self.update()

    def _set(self, nombre, v):
        setattr(self, nombre, v)
        self.update()

    def _animar(self, nombre, destino, ms):
        a = self._anims[nombre]
        a.stop()
        a.setDuration(ms)
        a.setStartValue(getattr(self, nombre))
        a.setEndValue(destino)
        a.start()

    def enterEvent(self, e):
        self._animar("hov", 1.0, 150)

    def leaveEvent(self, e):
        self._animar("hov", 0.0, 200)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # gris translúcido (más claro con mouse encima / presionado) → naranja al activarse
        gris = (255, 255, 255, 55 + 35 * self.hov + 45 * self.pre)
        nar = QColor(NARANJA)
        naranja = (nar.red(), nar.green(), nar.blue(), 235)
        bg = QColor(*(round(g + (n - g) * self.chk) for g, n in zip(gris, naranja)))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(self.rect())

        w = QColor("white")
        x, y = self.width() / 2, self.height() / 2
        s = self.width() * 0.18
        if self.kind in ("play", "pause"):
            for k, o in (("play", 1 - self.t), ("pause", self.t)):
                if o < 0.01:
                    continue
                p.save()
                p.setOpacity(o)
                esc = 0.7 + 0.3 * o
                p.translate(x, y)
                p.rotate((1 - o) * (-45 if k == "pause" else 45))
                p.scale(esc, esc)
                p.translate(-x, -y)
                self._icono(p, k, x, y, s, w)
                p.restore()
        else:
            self._icono(p, self.kind, x, y, s, w)

    def _icono(self, p, k, x, y, s, w):
        p.setBrush(w)
        def tri(*pts):
            p.drawPolygon(QPolygonF([QPointF(a, b) for a, b in pts]))

        if k == "play":
            tri((x - s * 0.6, y - s * 1.1), (x - s * 0.6, y + s * 1.1), (x + s * 1.2, y))
        elif k == "pause":
            p.drawRoundedRect(QRectF(x - s * 0.9, y - s, s * 0.65, 2 * s), 1.5, 1.5)
            p.drawRoundedRect(QRectF(x + s * 0.25, y - s, s * 0.65, 2 * s), 1.5, 1.5)
        elif k == "prev":
            p.drawRect(QRectF(x - s * 1.1, y - s, s * 0.3, 2 * s))
            tri((x + s, y - s), (x + s, y + s), (x - s * 0.6, y))
        elif k == "next":
            p.drawRect(QRectF(x + s * 0.8, y - s, s * 0.3, 2 * s))
            tri((x - s, y - s), (x - s, y + s), (x + s * 0.6, y))
        elif k == "list":
            for dy in (-0.85, 0, 0.85):
                p.drawRoundedRect(QRectF(x - s * 1.1, y + dy * s - s * 0.14, s * 2.2, s * 0.28), 1, 1)
        elif k == "plus":
            p.drawRoundedRect(QRectF(x - s, y - s * 0.14, 2 * s, s * 0.28), 1, 1)
            p.drawRoundedRect(QRectF(x - s * 0.14, y - s, s * 0.28, 2 * s), 1, 1)
        elif k == "shuffle":
            pen = QPen(w, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for sg in (1, -1):
                p.drawPolyline(QPolygonF([
                    QPointF(x - s, y + sg * s * 0.6), QPointF(x - s * 0.2, y + sg * s * 0.6),
                    QPointF(x + s * 0.4, y - sg * s * 0.6), QPointF(x + s * 0.7, y - sg * s * 0.6)]))
            p.setPen(Qt.NoPen)
            p.setBrush(w)
            for sg in (1, -1):
                tri((x + s * 0.65, y - sg * s * 0.6 - s * 0.35),
                    (x + s * 0.65, y - sg * s * 0.6 + s * 0.35),
                    (x + s * 1.1, y - sg * s * 0.6))


class ClickSlider(QSlider):
    """Slider que salta donde se hace clic; avisa al soltar."""
    soltado = Signal(float)

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(0, 1000)
        self.arrastrando = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(16)

    def _val(self, e):
        return max(0, min(1000, round(e.position().x() / max(self.width(), 1) * 1000)))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.arrastrando = True
            self.setValue(self._val(e))

    def mouseMoveEvent(self, e):
        if self.arrastrando:
            self.setValue(self._val(e))

    def mouseReleaseEvent(self, e):
        if self.arrastrando:
            self.arrastrando = False
            self.soltado.emit(self.value() / 1000)


class Marquee(QWidget):
    """Texto de una línea; si no entra, se desplaza en bucle."""
    HUECO = 40   # px entre una vuelta y la siguiente
    ESPERA = 45  # ticks quietos al inicio de cada vuelta

    def __init__(self, px, color, peso=QFont.Normal):
        super().__init__()
        self.texto = ""
        self.color = QColor(color)
        self.fuente = QFont(self.font())
        self.fuente.setPixelSize(px)
        self.fuente.setWeight(peso)
        self.setFixedHeight(QFontMetrics(self.fuente).height())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pos = 0
        self.espera = self.ESPERA
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._avanzar)
        self.timer.start(33)

    def sizeHint(self):
        return QSize(10, self.height())

    def set_text(self, texto):
        self.texto = texto
        self.pos = 0
        self.espera = self.ESPERA
        self.update()

    def _ancho(self):
        return QFontMetrics(self.fuente).horizontalAdvance(self.texto)

    def _avanzar(self):
        if self._ancho() <= self.width():
            return
        if self.espera > 0:
            self.espera -= 1
            return
        self.pos += 1
        if self.pos >= self._ancho() + self.HUECO:
            self.pos = 0
            self.espera = self.ESPERA
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self.fuente)
        p.setPen(self.color)
        fm = QFontMetrics(self.fuente)
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        tw = self._ancho()
        if tw <= self.width():
            self.pos = 0
            p.drawText(QPointF(0, y), self.texto)
            return
        p.drawText(QPointF(-self.pos, y), self.texto)
        p.drawText(QPointF(-self.pos + tw + self.HUECO, y), self.texto)


class ClickFrame(QFrame):
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()  # que no arrastre la ventana


class Barras(QWidget):
    """Ecualizador estilo Winamp: segmentos verde→amarillo→rojo y picos que caen."""
    N = 24
    SEG, HUECO_SEG, HUECO = 2, 1, 2

    def __init__(self, fuente):
        super().__init__()
        self.fuente = fuente  # callable(n) -> n valores 0..1
        self.vals = [0.0] * self.N
        self.picos = [0.0] * self.N
        self.espera = [0] * self.N
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def sizeHint(self):
        return QSize(10, self.height())

    def activar(self, si):
        if si:
            self.timer.start(33)
        else:
            self.timer.stop()

    def _tick(self):
        nuevo = self.fuente(self.N)
        for i, v in enumerate(nuevo):
            self.vals[i] = v if v > self.vals[i] else max(self.vals[i] - 0.06, v)
            if self.vals[i] >= self.picos[i]:
                self.picos[i] = self.vals[i]
                self.espera[i] = 12
            elif self.espera[i] > 0:
                self.espera[i] -= 1
            else:
                self.picos[i] = max(self.picos[i] - 0.025, 0.0)
        self.update()

    @staticmethod
    def _color(frac):
        if frac < 0.55:
            return QColor(60, 220, 70)
        if frac < 0.8:
            return QColor(235, 215, 40)
        return QColor(240, 60, 40)

    def paintEvent(self, e):
        p = QPainter(self)
        h = self.height()
        paso = self.SEG + self.HUECO_SEG
        filas = h // paso
        bw = (self.width() - self.HUECO * (self.N - 1)) / self.N
        for i in range(self.N):
            x = i * (bw + self.HUECO)
            for r in range(round(self.vals[i] * filas)):
                y = h - (r + 1) * paso + self.HUECO_SEG
                p.fillRect(QRectF(x, y, bw, self.SEG), self._color(r / filas))
            if self.picos[i] > 0.02:
                r = min(round(self.picos[i] * filas), filas) - 1
                y = h - (r + 1) * paso + self.HUECO_SEG
                p.fillRect(QRectF(x, y, bw, self.SEG), QColor(255, 255, 255, 220))


class Card(QWidget):
    LADO = 320

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.LADO, self.LADO)
        self.escalada = None  # carátula actual (None = degradado naranja)
        self.previa = None    # la anterior, debajo mientras dura el fundido
        self.mezcla = 1.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(380)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(self._mezclar)

    def _mezclar(self, v):
        self.mezcla = v
        self.update()

    def set_pixmap(self, pix):
        self.previa = self.escalada
        self.escalada = (pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                    Qt.SmoothTransformation) if pix else None)
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def _capa(self, p, esc, w, h):
        if esc:
            p.drawPixmap((w - esc.width()) // 2, (h - esc.height()) // 2, esc)
        else:
            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0, QColor("#ff7a2e"))
            g.setColorAt(1, QColor("#3a1200"))
            p.fillRect(self.rect(), g)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 30, 30)
        p.setClipPath(clip)
        if self.mezcla < 1.0:
            self._capa(p, self.previa, w, h)
            p.setOpacity(self.mezcla)
        self._capa(p, self.escalada, w, h)
        p.setOpacity(1.0)
        abajo = QLinearGradient(0, h * 0.35, 0, h)
        abajo.setColorAt(0, QColor(0, 0, 0, 0))
        abajo.setColorAt(1, QColor(0, 0, 0, 195))
        p.fillRect(self.rect(), abajo)
        arriba = QLinearGradient(0, 0, 0, 90)
        arriba.setColorAt(0, QColor(0, 0, 0, 110))
        arriba.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), arriba)


class Player(QWidget):
    def __init__(self):
        super().__init__()
        pygame.mixer.init()
        self.setWindowTitle("simpleplay")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(ESTILO)

        self.pistas = []
        self.actual = -1
        self.pausado = False
        self.duracion = 0.0
        self.offset = 0.0  # segundo desde el que arrancó (por seek)
        # espectro: se decodifica con ffmpeg solo un tramo alrededor de la posición
        self.token = 0
        self.chunk = None  # (token, inicio_seg, muestras mono int16)
        self.pidiendo = False
        self.pendiente = None  # (índice, segundo) de la sesión restaurada, aún sin sonar

        # --- tarjeta ---
        self.card = Card()
        self.thumb = QLabel()
        self.thumb.setFixedSize(28, 28)
        self.titulo = Marquee(12, "white", QFont.DemiBold)
        self.titulo.set_text(tr("Sin pista", "No track"))
        self.artista = Marquee(10, QColor(255, 255, 255, 170))
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addStretch()
        textos.addWidget(self.titulo)
        textos.addWidget(self.artista)
        textos.addStretch()
        self.thumb.hide()
        self.artista.hide()
        pill = ClickFrame()
        pill.setCursor(Qt.PointingHandCursor)
        pill.setObjectName("pill")
        pill.setFixedHeight(36)
        pl = self.pill_lay = QHBoxLayout(pill)
        pl.setContentsMargins(16, 3, 14, 3)  # sin miniatura: más aire a la izquierda
        pl.setSpacing(8)
        pl.addWidget(self.thumb)
        self.textos_w = QWidget()
        self.textos_w.setLayout(textos)
        textos.setContentsMargins(0, 0, 0, 0)
        self.barras = Barras(self.espectro)
        # texto y barras se apilan en el mismo lugar y se funden entre sí
        apilado = QWidget()
        stack = QStackedLayout(apilado)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.addWidget(self.textos_w)
        stack.addWidget(self.barras)
        stack.setAlignment(self.barras, Qt.AlignVCenter)
        pl.addWidget(apilado, 1)
        self.ef_texto = QGraphicsOpacityEffect(self.textos_w)
        self.ef_barras = QGraphicsOpacityEffect(self.barras)
        self.textos_w.setGraphicsEffect(self.ef_texto)
        self.barras.setGraphicsEffect(self.ef_barras)
        self.ef_barras.setOpacity(0.0)
        self.modo_barras = False
        self.mezcla = 0.0
        self.fundido = QVariantAnimation(self)
        self.fundido.setDuration(240)
        self.fundido.setEasingCurve(QEasingCurve.InOutCubic)
        self.fundido.valueChanged.connect(self._fundir)
        self.fundido.finished.connect(self._fin_fundido)
        pill.clicked.connect(self.alternar_barras)

        self.btn_shuffle = IconButton("shuffle", 30)
        self.btn_shuffle.setCheckable(True)
        self.btn_lista = IconButton("list", 36)
        self.btn_lista.setCheckable(True)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(pill, 1)
        top.addWidget(self.btn_lista)

        self.t_actual = QLabel("0:00")
        self.t_resta = QLabel("-0:00")
        for l in (self.t_actual, self.t_resta):
            l.setStyleSheet("font-size: 11px; font-weight: 500;")
        tiempos = QHBoxLayout()
        tiempos.addWidget(self.t_actual)
        tiempos.addStretch()
        tiempos.addWidget(self.t_resta)

        self.linea = ClickSlider()
        self.linea.soltado.connect(self.saltar)

        self.btn_prev = IconButton("prev", 44)
        self.btn_play = IconButton("play", 50)
        self.btn_next = IconButton("next", 44)
        botones = QHBoxLayout()
        botones.setSpacing(14)
        botones.addSpacing(30)  # contrapeso del shuffle: los 3 botones quedan centrados
        botones.addStretch()
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            botones.addWidget(b)
        botones.addStretch()
        botones.addWidget(self.btn_shuffle)

        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(14, 14, 14, 16)
        cl.setSpacing(4)
        cl.addLayout(top)
        cl.addStretch()
        cl.addLayout(tiempos)
        cl.addWidget(self.linea)
        cl.addSpacing(6)
        cl.addLayout(botones)

        pygame.mixer.music.set_volume(1.0)  # el volumen se maneja desde el sistema

        self.lista = QListWidget()
        self.lista.setFixedHeight(140)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lista.setTextElideMode(Qt.ElideRight)
        self.btn_abrir = IconButton("plus", 36)
        self.btn_abrir.clicked.connect(self.abrir)
        abajo = QHBoxLayout()
        abajo.addStretch()
        abajo.addWidget(self.btn_abrir)
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(10, 10, 10, 10)
        pv.setSpacing(6)
        pv.addWidget(self.lista)
        pv.addLayout(abajo)
        # contenedor que se anima: alto de 0 al total + opacidad; el aire con la tarjeta va dentro
        self.caja = QWidget()
        cv = QVBoxLayout(self.caja)
        cv.setContentsMargins(0, 10, 0, 0)
        cv.addWidget(self.panel)
        # tamaño fijo: al animar solo se revela (recorta) en vez de aplastar el contenido
        self.panel.setFixedHeight(self.panel.sizeHint().height())
        self.caja_h = self.caja.sizeHint().height()
        self.ef_caja = QGraphicsOpacityEffect(self.caja)
        self.caja.setGraphicsEffect(self.ef_caja)
        self.caja.setMaximumHeight(0)
        self.caja.hide()
        self.lista_abierta = False
        self.despliegue = QVariantAnimation(self)
        self.despliegue.setDuration(280)
        self.despliegue.setEasingCurve(QEasingCurve.OutCubic)
        self.despliegue.valueChanged.connect(self._desplegar)
        self.despliegue.finished.connect(self._fin_despliegue)

        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetFixedSize)  # la ventana crece al mostrar la lista
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.card, 0, Qt.AlignHCenter)
        root.addWidget(self.caja)

        self.btn_play.clicked.connect(self.play_pausa)
        self.btn_prev.clicked.connect(self.anterior)
        self.btn_next.clicked.connect(self.siguiente)
        self.btn_lista.toggled.connect(self.alternar_lista)
        self.lista.itemDoubleClicked.connect(lambda it: self.reproducir(self.lista.row(it)))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self.autoguardado = QTimer(self)
        self.autoguardado.timeout.connect(self.guardar_estado)
        self.autoguardado.start(15000)

    # --- archivos ---
    def abrir(self):
        archivos, _ = QFileDialog.getOpenFileNames(
            self, tr("Abrir", "Open"),
            QStandardPaths.writableLocation(QStandardPaths.MusicLocation), "MP3 (*.mp3)")
        self.agregar(archivos)

    def agregar(self, archivos, mostrar=True):
        primera = not self.pistas
        for a in archivos:
            self.pistas.append(a)
            self.lista.addItem(Path(a).stem)
        if primera and self.pistas:
            self.lista.setCurrentRow(0)
            if mostrar:
                self.mostrar_meta(0)

    def guardar_estado(self):
        if not self.pistas:
            return
        if self.actual >= 0:
            i, pos = self.actual, self.posicion()
        elif self.pendiente:
            i, pos = self.pendiente
        else:
            i, pos = max(self.lista.currentRow(), 0), 0.0
        datos = {"pistas": self.pistas, "indice": i, "pos": round(pos, 1),
                 "shuffle": self.btn_shuffle.isChecked()}
        try:
            ESTADO.parent.mkdir(parents=True, exist_ok=True)
            tmp = ESTADO.with_suffix(".tmp")
            tmp.write_text(json.dumps(datos, ensure_ascii=False))
            os.replace(tmp, ESTADO)
        except OSError:
            pass

    def restaurar(self, con_pistas=True):
        """Carga la última sesión: muestra el tema (en pausa) y deja el play listo."""
        try:
            d = json.loads((ESTADO if ESTADO.exists() else ESTADO_ANTIGUO).read_text())
        except (OSError, ValueError):
            return
        self.btn_shuffle.setChecked(bool(d.get("shuffle")))
        if not con_pistas:
            return
        pistas = [a for a in d.get("pistas", []) if Path(a).exists()]
        if not pistas:
            return
        # si faltan archivos, el índice guardado se corre con la lista filtrada
        previas = d.get("pistas", [])
        guardada = previas[d.get("indice", 0)] if 0 <= d.get("indice", 0) < len(previas) else None
        i = pistas.index(guardada) if guardada in pistas else 0
        self.agregar(pistas, mostrar=False)
        self.lista.setCurrentRow(i)
        self.mostrar_meta(i)
        pos = float(d.get("pos", 0)) if guardada in pistas else 0.0
        try:
            self.duracion = MP3(pistas[i]).info.length
        except Exception:
            self.duracion = 0.0
        if self.duracion > 0:
            pos = min(pos, self.duracion)
            self.linea.setValue(round(pos / self.duracion * 1000))
        self.t_actual.setText(fmt(pos))
        self.t_resta.setText("-" + fmt(self.duracion - pos))
        self.pendiente = (i, pos)

    def closeEvent(self, e):
        self.guardar_estado()
        super().closeEvent(e)

    def mostrar_meta(self, i):
        titulo, artista, portada = leer_meta(self.pistas[i])
        self.titulo.set_text(titulo)
        self.artista.set_text(artista)
        pix = None
        if portada:
            pix = QPixmap()
            if not pix.loadFromData(portada):
                pix = None
        self.card.set_pixmap(pix)
        self.thumb.setPixmap(circular(pix, 28) if pix else QPixmap())
        self.thumb.setVisible(pix is not None)
        self.pill_lay.setContentsMargins(5 if pix else 16, 3, 14, 3)
        self.artista.setVisible(bool(artista))

    # --- reproducción ---
    def reproducir(self, i=None):
        if i is None:
            i = self.lista.currentRow()
            if i < 0:
                if not self.pistas:
                    return
                i = 0
        self.actual = i
        self.pausado = False
        self.pendiente = None
        self.offset = 0.0
        try:
            self.duracion = MP3(self.pistas[i]).info.length
        except Exception:
            self.duracion = 0.0
        with sin_stderr():
            pygame.mixer.music.load(self.pistas[i])
            pygame.mixer.music.play()
        self.token += 1
        self.chunk = None
        self.pedir_tramo(0.0)
        self.lista.setCurrentRow(i)
        self.mostrar_meta(i)
        self.icono_play()
        self.guardar_estado()

    SR = 22050       # muestreo del análisis (basta para ver hasta ~10 kHz)
    VENTANA = 1024   # ≈ 46 ms
    TRAMO = 40       # segundos que se decodifican por pedido

    def pedir_tramo(self, inicio):
        if self.pidiendo:
            return
        self.pidiendo = True
        threading.Thread(target=self._decodificar,
                         args=(self.pistas[self.actual], self.token, max(inicio, 0.0)),
                         daemon=True).start()

    def _tramo_ffmpeg(self, ruta, inicio):
        out = subprocess.run(
            ["ffmpeg", "-v", "quiet", "-ss", f"{inicio:.2f}", "-i", ruta,
             "-t", str(self.TRAMO), "-vn", "-f", "s16le", "-ac", "1",
             "-ar", str(self.SR), "-"],
            capture_output=True, timeout=20).stdout
        return np.frombuffer(out, np.int16)

    def _tramo_miniaudio(self, ruta, inicio):
        # decodificador incluido en el paquete: no depende de nada instalado en el sistema
        # (seek_frame cuenta en cuadros de la frecuencia de salida)
        import miniaudio
        gen = miniaudio.stream_file(
            ruta, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
            sample_rate=self.SR, frames_to_read=self.SR, seek_frame=int(inicio * self.SR))
        bloques, n = [], 0
        for b in gen:
            bloques.append(np.frombuffer(b, np.int16))
            n += len(bloques[-1])
            if n >= self.TRAMO * self.SR:
                break
        return np.concatenate(bloques) if bloques else np.zeros(0, np.int16)

    def _decodificar(self, ruta, token, inicio):
        try:
            # ffmpeg si está (salta más rápido dentro de archivos enormes); si no, miniaudio
            if shutil.which("ffmpeg"):
                m = self._tramo_ffmpeg(ruta, inicio)
            else:
                m = self._tramo_miniaudio(ruta, inicio)
            if token == self.token:
                self.chunk = (token, inicio, m)
        except Exception:
            pass
        finally:
            self.pidiendo = False

    def alternar_lista(self, abrir):
        self.lista_abierta = abrir
        self.despliegue.stop()
        if abrir:
            self.caja.show()
        self.despliegue.setStartValue(self.mezcla_lista if hasattr(self, "mezcla_lista") else 0.0)
        self.despliegue.setEndValue(1.0 if abrir else 0.0)
        self.despliegue.start()

    def _desplegar(self, v):
        self.mezcla_lista = v
        self.caja.setMaximumHeight(round(self.caja_h * v))
        self.ef_caja.setOpacity(v)

    def _fin_despliegue(self):
        if not self.lista_abierta:
            self.caja.hide()
        else:
            self.caja.setMaximumHeight(16777215)  # sin tope una vez abierta

    def alternar_barras(self):
        self.modo_barras = not self.modo_barras
        if self.modo_barras:
            self.barras.activar(True)
        self.fundido.stop()
        self.fundido.setStartValue(self.mezcla)
        self.fundido.setEndValue(1.0 if self.modo_barras else 0.0)
        self.fundido.start()

    def _fundir(self, v):
        self.mezcla = v
        self.ef_barras.setOpacity(v)
        self.ef_texto.setOpacity(1 - v)

    def _fin_fundido(self):
        if not self.modo_barras:
            self.barras.activar(False)

    def espectro(self, n):
        """n valores 0..1 con la energía por banda (escala log) en este instante."""
        if self.actual < 0 or self.pausado:
            return [0.0] * n
        pos = self.posicion()
        v = None
        if self.chunk and self.chunk[0] == self.token:
            _, ini, m = self.chunk
            i = int((pos - ini) * self.SR)
            if 0 <= i and i + self.VENTANA <= len(m):
                v = m[i:i + self.VENTANA]
            # se acerca al final del tramo: pedir el siguiente antes de que falte
            if ini + len(m) / self.SR - pos < 8:
                self.pedir_tramo(pos)
        if v is None:
            if pos < self.duracion - 1:
                self.pedir_tramo(pos)  # seek o pista nueva: el tramo actual no cubre pos
            # mientras llega el tramo, un leve movimiento en vez de barras planas
            t = time.monotonic() * 3
            return [0.12 + 0.08 * math.sin(t + k * 0.7) for k in range(n)]
        mag = np.abs(np.fft.rfft(v / 32768.0 * np.hanning(self.VENTANA)))
        mag /= self.VENTANA / 4  # una senoidal a fondo de escala ≈ 1.0
        res = self.SR / self.VENTANA
        bordes = np.geomspace(50, 10000, n + 1)
        out = []
        for a, b in zip(bordes[:-1], bordes[1:]):
            lo = int(a / res)
            hi = max(int(b / res), lo + 1)
            db = 20 * math.log10(mag[lo:hi].max() + 1e-9)
            db += 3 * math.log2(math.sqrt(a * b) / 100)  # compensa la caída de agudos
            out.append(min(max((db + 42) / 32, 0.0), 1.0))
        return out

    def icono_play(self):
        self.btn_play.set_kind("pause" if (self.actual >= 0 and not self.pausado) else "play")

    def play_pausa(self):
        if self.actual < 0:
            if not self.pistas:
                self.abrir()
            pend = self.pendiente
            self.reproducir()
            if pend and self.actual == pend[0] and self.duracion > 0 and pend[1] > 1:
                self.saltar(min(pend[1] / self.duracion, 0.999))
            return
        if self.pausado:
            pygame.mixer.music.unpause()
        else:
            pygame.mixer.music.pause()
        self.pausado = not self.pausado
        self.icono_play()

    def parar(self):
        pygame.mixer.music.stop()
        self.actual = -1
        self.pausado = False
        self.icono_play()
        self.linea.setValue(0)
        self.t_actual.setText("0:00")
        self.t_resta.setText("-0:00")

    def siguiente(self):
        if not self.pistas:
            return
        if self.btn_shuffle.isChecked() and len(self.pistas) > 1:
            self.reproducir(random.choice([n for n in range(len(self.pistas)) if n != self.actual]))
        elif self.actual + 1 < len(self.pistas):
            self.reproducir(self.actual + 1)
        else:
            self.parar()

    def anterior(self):
        if self.actual < 0:
            return
        # pasados 3 s vuelve al inicio de la pista, si no, a la anterior
        if self.posicion() > 3 or self.actual == 0:
            self.reproducir(self.actual)
        else:
            self.reproducir(self.actual - 1)

    def posicion(self):
        return self.offset + max(pygame.mixer.music.get_pos(), 0) / 1000

    def saltar(self, frac):
        if self.actual < 0 or self.duracion <= 0:
            return
        self.offset = frac * self.duracion
        with sin_stderr():
            pygame.mixer.music.play(start=self.offset)
        if self.pausado:
            pygame.mixer.music.pause()

    def tick(self):
        if self.actual < 0:
            return
        if self.linea.arrastrando:
            pos = self.linea.value() / 1000 * self.duracion
        else:
            pos = min(self.posicion(), self.duracion)
            if self.duracion > 0:
                self.linea.setValue(round(pos / self.duracion * 1000))
        self.t_actual.setText(fmt(pos))
        self.t_resta.setText("-" + fmt(self.duracion - pos))
        if not self.pausado and not pygame.mixer.music.get_busy():
            self.siguiente()

    def mousePressEvent(self, e):
        # sin barra de título: se mueve arrastrando cualquier zona vacía
        if e.button() == Qt.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.agregar([u.toLocalFile() for u in e.mimeData().urls()
                      if u.toLocalFile().lower().endswith(".mp3")])

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction(f"simpleplay v{VERSION}").setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Abrir archivos…", "Open files…"), self.abrir)
        menu.addAction(tr("Cerrar", "Close"), self.close)
        menu.exec(e.globalPos())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_Space:
            self.play_pausa()
        else:
            super().keyPressEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("simpleplay")
    app.setDesktopFileName("simpleplay")  # Wayland: une la ventana con su .desktop e ícono
    app.setWindowIcon(QIcon(recurso("icon/simpleplay-256.png")))
    w = Player()
    args = [a for a in sys.argv[1:] if a.lower().endswith(".mp3")]
    w.restaurar(con_pistas=not args)  # con archivos por parámetro, solo se recuerda el shuffle
    w.agregar(args)
    w.show()
    sys.exit(app.exec())
