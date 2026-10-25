# simpleplay - a small, clean mp3 player
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
import collections
import difflib
import functools
import hashlib
import json
import math
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Si falta alguna dependencia, un mensaje claro en lugar de un error de Python en crudo (el ejecutable ya las trae).
if not getattr(sys, "frozen", False):
    import importlib.util
    faltan = [m for m in ("PySide6", "numpy", "mutagen", "miniaudio") if importlib.util.find_spec(m) is None]
    if faltan:
        es = (os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower().startswith("es")
        pip = f"  {sys.executable} -m pip install -r {Path(__file__).resolve().parent / 'requirements.txt'}"
        sys.exit(("simpleplay necesita módulos de Python que no están instalados: " + ", ".join(faltan) + ".\n"
                  "Instalalos con:\n" + pip + "\n(o usá el entorno del proyecto: .venv/bin/python simpleplay.py)") if es else
                 ("simpleplay needs Python modules that are not installed: " + ", ".join(faltan) + ".\n"
                  "Install them with:\n" + pip + "\n(or use the project's environment: .venv/bin/python simpleplay.py)"))

import numpy as np
import miniaudio

from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TDRC, APIC
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from PySide6.QtCore import (Qt, QEvent, QTimer, QCoreApplication, QRectF, QPointF, QSize, Signal, QLocale, QUrl, QObject,
                            ClassInfo, Property, Slot, QMetaType,
                            QStandardPaths, QVariantAnimation, QEasingCurve, QPoint, QItemSelectionModel, QEventLoop)
from PySide6.QtGui import (QDesktopServices, QShortcut, QKeySequence, QIcon, QFont, QFontMetrics, QPainter, QColor, QPixmap, QImage, QLinearGradient,
                           QPainterPath, QPolygonF, QPen, QPalette, QRegion, QCursor)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QGridLayout, QInputDialog, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QSlider, QAbstractButton, QListWidget,
                               QFileDialog, QFrame, QLayout, QMenu, QSizePolicy,
                               QStackedLayout, QGraphicsOpacityEffect, QMessageBox,
                               QAbstractItemView, QLineEdit, QListWidgetItem, QDialog, QPushButton, QComboBox, QCheckBox, QScrollArea)

try:
    from PySide6.QtDBus import (QDBusConnection, QDBusAbstractAdaptor, QDBusObjectPath,
                                QDBusMessage, QDBusArgument)
    HAY_DBUS = True
except ImportError:  # sin QtDBus no hay teclas multimedia; el resto anda igual
    HAY_DBUS = False

VERSION = "1.8"
# La escoba (completar los datos del tema desde MusicBrainz) está escrita pero desactivada en esta
# versión. Para seguir trabajando en ella: SIMPLEPLAY_ESCOBA=1 python simpleplay.py
ESCOBA = bool(os.environ.get("SIMPLEPLAY_ESCOBA"))
# El ecualizador gráfico y "Buscar mi sonido": activos desde la 1.6; la 1.5.3 pública los lleva apagados.
# SIMPLEPLAY_ECUALIZADOR=0 python simpleplay.py los apaga.
EQ_GRAFICO = os.environ.get("SIMPLEPLAY_ECUALIZADOR", "1") != "0"
# YouTube Music (versión de desarrollo): conectar la cuenta, ver Me gusta/playlists/búsqueda y agregar temas (se bajan y se
# convierten a mp3 en una caché). Hace falta pip install -r requirements-youtube.txt y el módulo simpleplay_youtube.py al lado.
# SIMPLEPLAY_YOUTUBE=1 python simpleplay.py
YOUTUBE = bool(os.environ.get("SIMPLEPLAY_YOUTUBE"))
# Mosquito (control remoto desde el celular): activo por defecto; SIMPLEPLAY_MOSQUITO=0 python simpleplay.py lo quita del menú
MOSQUITO = os.environ.get("SIMPLEPLAY_MOSQUITO", "1") != "0"
URL_APOYO = "https://buymeacoffee.com/cufadev"   # donación voluntaria: el mismo enlace de la web y del README
NARANJA = "#ff4e01"
# Colores de acento a elegir (botón activo, selección, volumen del panel). Todos se leen bien con texto blanco encima.
ACENTOS = {"naranja": ("Naranja", "Orange", NARANJA), "azul": ("Azul", "Blue", "#2f7bff"),
           "verde": ("Verde", "Green", "#1fa75a"), "violeta": ("Violeta", "Purple", "#8a5cf6"),
           "rosa": ("Rosa", "Pink", "#e83e8c"), "turquesa": ("Turquesa", "Teal", "#0fa3a3")}
ACENTO = NARANJA        # el activo; lo cambia Player.poner_acento


def tinte(css):
    """Las hojas de estilo se escriben con el naranja de la marca; esto lo cambia por el acento elegido."""
    if ACENTO == NARANJA:
        return css
    c = QColor(ACENTO)
    return css.replace(NARANJA, ACENTO).replace("rgba(255,78,1,", f"rgba({c.red()},{c.green()},{c.blue()},")


def _cubo(color, lado=14):
    """Un círculo de color para el menú."""
    pm = QPixmap(lado, lado)
    pm.fill(Qt.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.Antialiasing)
    q.setPen(Qt.NoPen)
    q.setBrush(QColor(color))
    q.drawEllipse(0, 0, lado, lado)
    q.end()
    return QIcon(pm)
# Sombra alrededor de la tarjeta y de la barra: la ventana no tiene marco y el escritorio no le pone ninguna.
# SIMPLEPLAY_SOMBRA=0 la apaga. Se dibuja en un margen transparente de la ventana (SOMBRA_MARGEN px por lado).
SOMBRA = os.environ.get("SIMPLEPLAY_SOMBRA", "1") != "0"
SOMBRA_BLUR = 8      # desvío del difuminado gaussiano, en px (más alto = más difusa)
SOMBRA_DY = 5        # cuánto baja (la luz viene de arriba)
SOMBRA_ALPHA = 0.40  # opacidad de la forma antes de difuminarla (0-1); en el borde queda la mitad
SOMBRA_MARGEN = (round(2.5 * SOMBRA_BLUR) + SOMBRA_DY + 1) if SOMBRA else 0

ESTILO_DIALOGO = """
QMessageBox, QDialog { background: #1e1e22; }
QLabel { color: #f2f2f2; background: transparent; font-size: 13px; }
QPushButton { background: rgba(255,255,255,40); color: white; border: none; border-radius: 12px;
              padding: 7px 16px; min-width: 104px; }
QPushButton:hover { background: rgba(255,255,255,75); }
QPushButton:default { background: #ff4e01; }
QTextEdit { background: #141416; color: #ddd; border: none; border-radius: 8px; }
"""
def recurso(ruta):
    """Ruta a un archivo incluido con la app (también dentro del paquete PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(base / ruta)


ESTADO = Path.home() / ".config" / "simpleplay" / "estado.json"
ARCHIVO_ACENTO = ESTADO.parent / "acento"       # aparte de estado.json: se guarda aunque la lista esté vacía
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
QFrame#mini { background: rgba(22,22,24,235); border-radius: 28px; }
QListWidget { background: transparent; color: white; border: none; padding: 0; outline: 0; }
QListWidget::item { padding: 6px 8px; border-radius: 8px; }
QListWidget::item:selected { background: rgba(255,78,1,190); color: white; }
QLineEdit { background: rgba(255,255,255,26); color: white; border: none; border-radius: 14px;
            padding: 7px 12px; selection-background-color: #ff4e01; }
QMenu { background: #1e1e22; color: #f2f2f2; border: 1px solid rgba(255,255,255,30); border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: #ff4e01; }
QMenu::item:disabled { color: rgba(255,255,255,110); }
QMenu::separator { height: 1px; background: rgba(255,255,255,30); margin: 5px 8px; }
"""


def fmt(s):
    s = max(int(s), 0)
    return f"{s // 60}:{s % 60:02d}"


EXTENSIONES = (".mp3", ".flac")     # lo que el reproductor abre


def etiquetas_de(ruta, con_portada=False):
    """Título, artista, álbum, n.º de pista (y la carátula si se pide) de un mp3 (etiquetas ID3) o de un flac
    (comentarios Vorbis). Lo que falte queda vacío (0 / None)."""
    d = {"titulo": "", "artista": "", "album": "", "pista": 0, "portada": None}
    try:
        if ruta.lower().endswith(".flac"):
            f = FLAC(ruta)
            for clave, campo in (("title", "titulo"), ("artist", "artista"), ("album", "album")):
                d[campo] = (f.get(clave) or [""])[0].strip()
            m = re.match(r"\d+", (f.get("tracknumber") or [""])[0])
            d["pista"] = int(m.group()) if m else 0
            if con_portada and f.pictures:
                d["portada"] = next((p for p in f.pictures if p.type == 3), f.pictures[0]).data   # tipo 3 = carátula frontal
        else:
            t = ID3(ruta)
            d["titulo"] = str(t["TIT2"]).strip() if "TIT2" in t else ""
            d["artista"] = str(t["TPE1"]).strip() if "TPE1" in t else ""
            d["album"] = str(t["TALB"]).strip() if "TALB" in t else ""
            m = re.match(r"\d+", str(t["TRCK"])) if "TRCK" in t else None
            d["pista"] = int(m.group()) if m else 0
            if con_portada:
                d["portada"] = next((t[k].data for k in t if k.startswith("APIC")), None)
    except Exception:
        pass
    return d


def duracion_de(ruta):
    """Duración en segundos de un mp3 o un flac (0.0 si no se puede leer)."""
    try:
        return float(MutagenFile(ruta).info.length)
    except Exception:
        return 0.0


def datos_lista(ruta):
    """Lo que la lista necesita de un tema: nombre para mostrar, artista, título, álbum y n.º de pista."""
    e = etiquetas_de(ruta)
    art, tit, alb, pista = e["artista"], e["titulo"], e["album"], e["pista"]
    # sin etiquetas útiles: el nombre del archivo, sin "[id de YouTube]" ni "(Official Video)" (solo para mostrar)
    limpio = limpiar_nombre(Path(ruta).stem) or Path(ruta).stem
    return {"nombre": f"{art} - {tit}" if tit and art else (tit or limpio),
            "artista": art, "titulo": tit or limpio, "album": alb, "pista": pista}


def nombre_para_lista(ruta):
    """Lo que se ve en la lista: "Artista - Título" de las etiquetas; si faltan, el título o el nombre limpio."""
    return datos_lista(ruta)["nombre"]


def elegir_al_azar(pistas, ya, actual=None, rng=random):
    """El próximo tema del shuffle: uno que no haya sonado en esta ronda (`ya`, un conjunto de rutas) ni sea el actual.
    Cuando ya sonaron todos, empieza una ronda nueva con cualquiera salvo el actual, así ninguno se repite antes de que
    suenen los demás y el último de una ronda no abre la siguiente. Trabaja con rutas y no con posiciones, así que
    sigue bien si se agregan, quitan, ordenan o arrastran temas a mitad de la ronda. -> (índice, ronda_nueva)"""
    quedan = [i for i, p in enumerate(pistas) if p not in ya and p != actual]
    nueva = not quedan
    if nueva:
        quedan = [i for i, p in enumerate(pistas) if p != actual]
    return rng.choice(quedan), nueva


LISTAS = (".m3u", ".m3u8")      # listas de reproducción que se abren y se guardan


def leer_lista(ruta):
    """Lee una lista M3U/M3U8. -> (rutas que existen, en orden, cantidad de entradas que no se encontraron).

    Las rutas relativas se toman desde la carpeta de la lista, así sigue andando si se mueve junto con la música."""
    crudo = Path(ruta).read_bytes()
    try:
        texto = crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = crudo.decode("latin-1")      # los .m3u viejos no son UTF-8
    base = Path(ruta).resolve().parent
    hallados, faltan = [], 0
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        if linea.lower().startswith("file://"):
            linea = urllib.parse.unquote(urllib.parse.urlparse(linea).path)
        p = base / linea
        if not p.is_file() and "\\" in linea:
            p = base / linea.replace("\\", "/")      # lista hecha en Windows
        if p.is_file() and p.suffix.lower() in EXTENSIONES:
            hallados.append(str(p.resolve()))
        else:
            faltan += 1
    return hallados, faltan


def escribir_lista(ruta, pistas, datos=None):
    """Guarda una lista M3U8 (UTF-8) con rutas relativas a su carpeta; con 'datos' agrega #EXTINF con el nombre."""
    base = Path(ruta).resolve().parent
    lineas = ["#EXTM3U"]
    for p in pistas:
        try:
            rel = Path(os.path.relpath(p, base)).as_posix()
        except ValueError:                   # otro disco (Windows): no hay ruta relativa posible
            rel = Path(p).as_posix()
        if datos and p in datos:
            lineas.append(f"#EXTINF:-1,{datos[p]['nombre']}")
        lineas.append(rel)
    tmp = Path(str(ruta) + ".parcial")
    tmp.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    os.replace(tmp, ruta)                    # nunca queda una lista a medio escribir


def agregar_a_lista(ruta, pistas, datos=None):
    """Agrega temas al final de una lista M3U8 sin tocar el resto (ni las entradas que hoy no se encuentran).
    Crea la lista si no existe y no repite lo que ya tiene. -> cantidad de temas agregados."""
    ruta = Path(ruta)
    if not ruta.exists():
        escribir_lista(ruta, pistas, datos)
        return len(pistas)
    ya = set(leer_lista(ruta)[0])
    nuevos = [p for p in pistas if str(Path(p).resolve()) not in ya]
    if nuevos:
        crudo = ruta.read_bytes()
        try:
            texto = crudo.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = crudo.decode("latin-1")
        base = ruta.resolve().parent
        lineas = []
        for p in nuevos:
            try:
                rel = Path(os.path.relpath(p, base)).as_posix()
            except ValueError:
                rel = Path(p).as_posix()
            if datos and p in datos:
                lineas.append(f"#EXTINF:-1,{datos[p]['nombre']}")
            lineas.append(rel)
        if not texto.strip():
            texto = "#EXTM3U"
        tmp = Path(str(ruta) + ".parcial")
        tmp.write_text(texto.rstrip("\n") + "\n" + "\n".join(lineas) + "\n", encoding="utf-8")
        os.replace(tmp, ruta)
    return len(nuevos)


def buscar_audio(rutas):
    """Expande carpetas (con sus subcarpetas) y listas M3U, y devuelve los mp3 y flac, sin repetir y en orden."""
    out, vistos = [], set()
    for r in rutas:
        p = Path(r)
        if p.suffix.lower() in LISTAS and p.is_file():
            try:
                hallados = [Path(x) for x in leer_lista(p)[0]]      # el orden de la lista se respeta
            except OSError:
                hallados = []
        elif p.is_dir():
            hallados = sorted((x for x in p.rglob("*") if x.suffix.lower() in EXTENSIONES and x.is_file()),
                              key=lambda x: str(x).lower())
        else:
            hallados = [p] if p.suffix.lower() in EXTENSIONES and p.is_file() else []
        for x in hallados:
            if str(x) not in vistos:
                vistos.add(str(x))
                out.append(str(x))
    return out


buscar_mp3 = buscar_audio     # el nombre de antes


ORDENES = ("original", "artista", "titulo", "album")


def clave_orden(modo, d):
    """Clave para ordenar un tema según el modo. Sin acentos ni mayúsculas; los datos vacíos van al final."""
    def n(t):
        return (t == "", _norm(t))
    if modo == "artista":
        return (n(d["artista"]), n(d["album"]), d["pista"] or 9999, n(d["titulo"]))
    if modo == "album":
        return (n(d["album"]), d["pista"] or 9999, n(d["titulo"]))
    return (n(d["titulo"]), n(d["artista"]))


def leer_meta(path):
    e = etiquetas_de(path, con_portada=True)
    return e["titulo"] or Path(path).stem, e["artista"], e["portada"]


DEBUG = bool(os.environ.get("SIMPLEPLAY_DEBUG"))


def log(*partes):
    """Mensajes de diagnóstico: solo se ven con SIMPLEPLAY_DEBUG=1."""
    if DEBUG:
        print("[simpleplay]", *partes, file=sys.stderr, flush=True)


# --- análisis de audio para el espectro ---
VENTANA = 2048   # muestras por análisis: 46 ms a 44,1 kHz, casillas de 21,5 Hz
BANDAS = 24
RANGO_DB = 36    # cuántos dB bajo el nivel de referencia reciente separan una barra vacía de una llena
HISTORIA = 300   # cuántos análisis recientes (~10 s a 30 por segundo) fijan ese nivel de referencia
_BORDES = np.geomspace(50, 10000, BANDAS + 1)
_HANN = np.hanning(VENTANA)


def bandas_db(v):
    """Nivel en dB de cada banda (escala log) para VENTANA muestras mono float32 (±1) a FS Hz."""
    mag = np.abs(np.fft.rfft(v * _HANN)) / (VENTANA / 4)  # senoidal a fondo ≈ 1.0
    mx = np.maximum.reduceat(mag, _IDX)[0::2]             # el máximo de cada banda, de una sola vez
    return 20 * np.log10(mx + 1e-9) + _COMP


def diagnosticar(ruta):
    """`simpleplay.py --diagnose archivo.mp3`: prueba la decodificación y el audio sin abrir la ventana.

    El espectro sale del mismo audio que suena, así que si el archivo se decodifica y el dispositivo abre,
    las barras funcionan.
    """
    print(f"simpleplay {VERSION} - Python {sys.version.split()[0]}")
    print("archivo:", ruta)
    try:
        info = miniaudio.get_file_info(ruta)
        print(f"formato: {info.file_format.name}, {info.sample_rate} Hz, {info.nchannels} canales, {info.duration:.1f} s")
    except Exception as e:
        print(f"formato: ERROR {e!r}")
    try:  # un tema corto no tiene un segundo 5: se arranca más cerca del principio
        inicio = min(5.0, max(0.0, duracion_de(ruta) - 3))
    except Exception:
        inicio = 0.0
    t0 = time.time()
    try:
        g = miniaudio.stream_file(ruta, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=2, sample_rate=FS,
                                  frames_to_read=1024, seek_frame=round(inicio * FS))
        x = _leer(g, FS * 3).mean(axis=1)
        rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
        print(f"decodificación: {len(x) / FS:.1f} s de audio desde el segundo {inicio:.0f} en {time.time() - t0:.2f} s, "
              f"nivel RMS {rms:.4f}")
    except Exception as e:
        x = np.zeros(0, np.float32)
        print(f"decodificación: ERROR {e!r}")
    if len(x) < VENTANA:
        print("resultado: NO se pudo decodificar; no habría audio ni espectro")
        return 1
    db = bandas_db(x[:VENTANA])
    vals = np.clip((db - (db.max() - RANGO_DB)) / RANGO_DB, 0, 1)
    print("espectro de ejemplo:", "".join(" ▁▂▃▄▅▆▇█"[int(round(v * 8))] for v in vals), f"(máximo {db.max():.1f} dB)")
    errores = []
    m = Motor(backend=miniaudio.Backend.NULL if os.environ.get("SIMPLEPLAY_AUDIO") == "null" else None)
    m.error_dispositivo.connect(errores.append)
    m.volumen = 0.0  # solo se prueba que abre y avanza: no suena
    m.cargar(ruta, inicio)
    time.sleep(0.8)
    avance = m.posicion() - inicio
    m.cerrar()
    if errores:
        print(f"dispositivo de audio: ERROR {errores[0]}")
        print("resultado: el archivo se decodifica pero NO se pudo abrir el audio")
        return 1
    print(f"dispositivo de audio: abre y avanza ({avance:.2f} s en 0,8 s)")
    print("resultado: el audio y el espectro deberían funcionar")
    try:  # la escoba necesita llegar a MusicBrainz por HTTPS
        if not ESCOBA:
            return 0
        _http("https://musicbrainz.org/ws/2/recording?query=recording:test&limit=1&fmt=json", reintentos=2)
        print("MusicBrainz: responde (la escoba puede buscar datos)")
    except urllib.error.HTTPError as e:  # el servidor contestó: la conexión y los certificados andan
        print(f"MusicBrainz: responde pero con HTTP {e.code} ({e.reason}); suele ser pasajero, la escoba reintenta sola")
    except Exception as e:
        paths = ssl.get_default_verify_paths()
        print(f"MusicBrainz: NO se pudo consultar ({e!r}); la escoba no va a funcionar, el reproductor sí")
        print(f"  certificados del sistema: {paths.cafile or paths.capath or 'ninguno'}")
    return 0


# --- escoba: buscar los datos del tema en MusicBrainz y escribirlos en el archivo ---
UA_MB = f"simpleplay/{VERSION} ( https://github.com/cufadev/simpleplay )"  # MusicBrainz exige identificarse
RUIDO = re.compile(r"official|oficial|video|audio|lyrics?|letra|\bhd\b|4k|1080p|720p|visuali[sz]er|\bmv\b|"
                   r"videoclip|clip|full album|\bhq\b|remaster", re.I)
UMBRAL_MB = 90        # puntaje mínimo de MusicBrainz (0-100)
UMBRAL_TEXTO = 0.85   # parecido mínimo (0-1) entre lo buscado y lo encontrado
_ultima_mb = [0.0]


def limpiar_nombre(texto):
    """Quita lo que sobra de un título bajado de YouTube: (Official Video), [id], '- Topic'..."""
    t = unicodedata.normalize("NFKC", texto or "").replace("⧸", "/")  # ＂？｜ de ancho completo -> normales
    t = re.sub(r"\[[^\]]*\]", " ", t)                                  # [id de YouTube], [HD], [Ultra Music]...
    t = re.sub(r"\([^)]*\)", lambda m: "" if RUIDO.search(m.group(0)) else m.group(0), t)
    t = re.sub(r"\s*[-–—|]\s*(topic|vevo)\s*$", "", t, flags=re.I)
    # "Official Video HD" suelto al final (sin paréntesis)
    t = re.sub(r"\s+(official|oficial)(\s+(music|video|audio|lyrics?|hd|4k|videoclip))*\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -–—|")


def sin_feat(titulo):
    """El título sin '(feat. ...)' / 'ft. ...' (MusicBrainz guarda a los invitados en el artista)."""
    t = re.sub(r"\s*[\(\[]\s*(feat|ft|con|with)\b[^)\]]*[\)\]]", "", titulo, flags=re.I)
    t = re.sub(r"\s+(feat|ft)\.?\s.*$", "", t, flags=re.I)
    return t.strip()


_INDICE = re.compile(r"^\s*\d{1,4}\s*[-–.)]\s+")   # "391 - ", "12. ", "07) ": el número de orden de una lista descargada


def candidatos(ruta, titulo_tag, artista_tag):
    """Posibles (artista, título) del tema, de lo más a lo menos probable, con etiquetas y nombre de archivo."""
    nombre, tit, art = limpiar_nombre(Path(ruta).stem), limpiar_nombre(titulo_tag), limpiar_nombre(artista_tag)
    # "391 - Boom Boom Kid - I Do": el 391 es la posición en una lista, no el artista. Se prueba sin él; solo si
    # lo que queda no trae artista ("311 - Amber") se vuelve al nombre completo, por si 311 es la banda.
    sin_n = _INDICE.sub("", nombre)
    bases = [tit, sin_n] + ([nombre] if sin_n != nombre and " - " not in sin_n else [])
    out, invertidos = [], []
    for base in bases:
        if " - " in base:
            a, t = (limpiar_nombre(x) for x in base.split(" - ", 1))  # cada parte por separado
            out.append((a, t))
            invertidos.append((t, a))  # por si el archivo dice "Título - Artista"
    if art and tit:
        out.append((art, tit))
    if art and nombre and " - " not in sin_n:
        out.append((art, sin_n))
    vistos, res = set(), []
    for a, t in out + invertidos:
        if "|" in a + t or len(a) > 60 or len(t) > 90:
            continue  # parece un mix o una lista de temas, no un tema: no se adivina
        if re.search(r'[()"]', a) or t.count("_") >= 2:
            continue  # "Título (Cover) - Artista" escrito al revés, o un listado: no se adivina
        if a and t and (a.lower(), t.lower()) not in vistos:
            vistos.add((a.lower(), t.lower()))
            res.append((a, t))
    return res


def _norm(t):
    t = unicodedata.normalize("NFKD", (t or "").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)   # para comparar, sin paréntesis
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def parecido(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def contexto_ssl():
    """Contexto HTTPS con los certificados del sistema; si no hay ninguno, los de certifi (incluido en el AppImage)."""
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats().get("x509_ca"):
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
    return ctx


def _http(url, binario=False, reintentos=4):
    for intento in range(reintentos + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA_MB, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20, context=contexto_ssl()) as f:
                datos = f.read()
                return datos if binario else json.loads(datos)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and intento < reintentos:
                time.sleep(3 * (intento + 1))  # MusicBrainz pide ir más despacio: espera creciente
                continue
            raise


def _esperar_mb():
    """MusicBrainz permite como máximo ~1 consulta por segundo."""
    falta = 1.1 - (time.monotonic() - _ultima_mb[0])
    if falta > 0:
        time.sleep(falta)
    _ultima_mb[0] = time.monotonic()


def _fecha_orden(fecha):
    return fecha or "9999"  # sin fecha va al final


def _nivel(ed):
    """Qué tan buena es una edición para ponerle al tema (0 = álbum de estudio oficial, lo mejor)."""
    if not ed:
        return 5
    rg = ed.get("release-group") or {}
    tipo = rg.get("primary-type")
    sec = set(rg.get("secondary-types") or [])
    oficial = ed.get("status") == "Official"
    if oficial and tipo == "Album" and not sec:
        return 0
    # un single/EP, o un álbum que es banda de sonido, son legítimos pero el álbum de estudio les gana
    if oficial and ((tipo in ("Single", "EP") and not sec) or (tipo == "Album" and sec == {"Soundtrack"})):
        return 1
    if oficial and not sec:
        return 2
    return 3 if oficial else 4  # 3: recopilatorio / en vivo / remix; 4: pirata, promo, retirado


def mejor_edicion(rec):
    """Entre las ediciones de una grabación, la mejor: álbum de estudio oficial y, a igualdad, el más antiguo."""
    ediciones = rec.get("releases") or []
    return min(ediciones, key=lambda r: (_nivel(r), _fecha_orden(r.get("date")))) if ediciones else None


def _q(t):
    return re.sub(r'["\\]', " ", t).strip()  # las comillas rompen la sintaxis de la consulta


def buscar_mb(artista, titulo, duracion=None):
    """Mejor coincidencia de MusicBrainz para (artista, título), o None si no hay una confiable.

    Solo se acepta una edición de estudio oficial (álbum, single o EP): con un recopilatorio, un
    vivo o un pirata es preferible no escribir nada antes que escribir un álbum equivocado.
    """
    variantes = []
    for v in (titulo, sin_feat(titulo), re.sub(r"\s*\([^)]*\)", "", sin_feat(titulo)).strip()):
        if v and v not in variantes:
            variantes.append(v)
    pide_otra_version = bool(re.search(r"live|en vivo|acoustic|acústic|remix|demo|session", titulo, re.I))
    vistas, candidatas = set(), []
    for variante in variantes:
        _esperar_mb()
        # de temas muy populares hay cientos de grabaciones (una por recopilatorio): se piden hasta 100
        datos = _http("https://musicbrainz.org/ws/2/recording?" + urllib.parse.urlencode(
            {"query": f'recording:"{_q(variante)}" AND artist:"{_q(artista)}"', "fmt": "json", "limit": 100}))
        for r in datos.get("recordings", []):
            if r.get("score", 0) < UMBRAL_MB or r["id"] in vistas:
                continue
            largo = (r.get("length") or 0) / 1000
            diferencia = abs(largo - duracion) if duracion and largo else 0
            if diferencia > max(45, 0.25 * duracion):
                continue  # un fragmento u otra pieza: los videos suelen traer intros, pero no tanto
            creditos = r.get("artist-credit") or []
            completo = "".join(c.get("name", "") + c.get("joinphrase", "") for c in creditos)
            nombres = [completo] + [c.get("name", "") for c in creditos]
            if max(parecido(r.get("title", ""), v) for v in variantes) < UMBRAL_TEXTO:
                continue
            if not any(parecido(artista, n) >= 0.85 for n in nombres if n):  # casi igual, no solo 'contiene' (Celtic Pink Floyd)
                continue
            vistas.add(r["id"])
            ed = mejor_edicion(r)
            en_vivo = bool(re.search(r"live|demo|remix|acoustic|karaoke|instrumental|session|bootleg",
                                     r.get("disambiguation", ""), re.I)) and not pide_otra_version
            candidatas.append((en_vivo, _nivel(ed), diferencia > 15, _fecha_orden((ed or {}).get("date")),
                               -r.get("score", 0), r, completo, ed))
        if candidatas and min(candidatas, key=lambda x: x[:5])[:3] == (False, 0, False):
            break  # ya apareció el álbum de estudio, con la duración justa: no hace falta seguir
    if not candidatas:
        return None
    en_vivo, nivel, _, _, _, r, completo, ed = min(candidatas, key=lambda x: x[:5])
    if en_vivo or nivel > 1:
        return None
    rg = ((ed or {}).get("release-group") or {}).get("id")
    return {"titulo": r["title"], "artista": completo, "album": (ed or {}).get("title"),
            "anio": ((ed or {}).get("date") or "")[:4] or None, "rg": rg, "release": (ed or {}).get("id")}


def _imagen(datos):
    """(bytes, mime) si los bytes son un JPEG o un PNG; si no, None."""
    if datos[:2] == b"\xff\xd8":
        return datos, "image/jpeg"
    if datos[:4] == b"\x89PNG":
        return datos, "image/png"
    return None


def portada_deezer(artista, album):
    """Portada de 1000 px de Deezer (sin clave) -> (bytes, mime) o None. Solo si el artista y el álbum coinciden y no es un recopilatorio."""
    if not (artista and album):
        return None
    try:
        q = urllib.parse.urlencode({"q": f'artist:"{_q(artista)}" album:"{_q(album)}"', "limit": 10})
        for d in _http("https://api.deezer.com/search/album?" + q).get("data", []):
            if d.get("record_type") == "compile" or not d.get("cover_xl"):
                continue
            if parecido(d.get("title", ""), album) < UMBRAL_TEXTO or parecido((d.get("artist") or {}).get("name", ""), artista) < 0.85:
                continue
            img = _imagen(_http(d["cover_xl"], binario=True))
            if img:
                return img
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    return None


def _lado_corto(img):
    """Lado menor en píxeles de una imagen (bytes, mime); 0 si no se puede leer."""
    q = QImage.fromData(img[0])
    return min(q.width(), q.height())


def descargar_portada(info):
    """La mejor portada del álbum -> (bytes, mime) o None.

    Primero Cover Art Archive (1200 px y, si no hay, 500 px), del álbum de estudio ya elegido (nunca de un
    recopilatorio). Si ese álbum no tiene portada, o la tiene chica (menos de 600 px), se prueba Deezer (1000 px)
    buscando por artista y álbum, y se queda la más grande.
    """
    mejor = None
    for tipo, mbid in (("release-group", info.get("rg")), ("release", info.get("release"))):
        if not mbid or mejor:
            continue
        for tam in ("front-1200", "front-500"):
            try:
                time.sleep(0.3)
                mejor = _imagen(_http(f"https://coverartarchive.org/{tipo}/{mbid}/{tam}", binario=True))
                if mejor:
                    break
            except urllib.error.HTTPError:
                continue  # ese álbum no tiene portada de ese tamaño
    if mejor and _lado_corto(mejor) >= 600:
        return mejor
    otra = portada_deezer(info.get("artista"), info.get("album"))
    if otra and (not mejor or _lado_corto(otra) > _lado_corto(mejor)):
        return otra
    return mejor


# --- reconocer el tema por su sonido (AcoustID + Chromaprint) ---
def clave_acoustid():
    """La clave de aplicación de AcoustID: variable SIMPLEPLAY_ACOUSTID o el archivo ~/.config/simpleplay/acoustid.key."""
    c = os.environ.get("SIMPLEPLAY_ACOUSTID", "").strip()
    if not c:
        try:
            c = (ESTADO.parent / "acoustid.key").read_text().strip()
        except OSError:
            c = ""
    return c


def _fpcalc():
    """Ruta de fpcalc (Chromaprint): junto al ejecutable empaquetado o en el PATH; None si no está."""
    propio = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / ("fpcalc.exe" if sys.platform == "win32" else "fpcalc")
    return str(propio) if propio.exists() else shutil.which("fpcalc")


def huella(ruta):
    """(duración en segundos, huella) del audio con fpcalc, o None si no se puede."""
    exe = _fpcalc()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-json", str(ruta)], capture_output=True, text=True, timeout=60).stdout
        d = json.loads(out)
        return int(d["duration"]), d["fingerprint"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None


def buscar_acoustid(ruta, duracion=None):
    """Reconoce el tema por su sonido -> mismo resultado que buscar_mb, o None si no hay una coincidencia confiable.

    AcoustID da la grabación de MusicBrainz (solo sale una huella corta, nunca el audio); de ahí se elige la edición
    con el mismo criterio que la búsqueda por texto, así que tampoco acepta recopilatorios ni en vivo.
    """
    clave = clave_acoustid()
    h = huella(ruta) if clave else None
    if not h:
        return None
    seg, fp = h
    datos = _http("https://api.acoustid.org/v2/lookup?" + urllib.parse.urlencode(
        {"client": clave, "format": "json", "duration": seg, "fingerprint": fp, "meta": "recordings"}))
    mejores = sorted((r for r in datos.get("results", []) if r.get("score", 0) >= 0.9 and r.get("recordings")),
                     key=lambda r: -r["score"])
    if not mejores:
        return None
    candidatas = []
    for rec in mejores[0]["recordings"][:5]:
        _esperar_mb()
        r = _http(f"https://musicbrainz.org/ws/2/recording/{rec['id']}?" + urllib.parse.urlencode(
            {"inc": "artist-credits+releases+release-groups", "fmt": "json"}))
        largo = (r.get("length") or 0) / 1000
        diferencia = abs(largo - duracion) if duracion and largo else 0
        ed = mejor_edicion(r)
        en_vivo = bool(re.search(r"live|demo|remix|acoustic|karaoke|instrumental|session|bootleg", r.get("disambiguation", ""), re.I))
        creditos = r.get("artist-credit") or []
        completo = "".join(c.get("name", "") + c.get("joinphrase", "") for c in creditos)
        candidatas.append((en_vivo, _nivel(ed), diferencia > 15, _fecha_orden((ed or {}).get("date")), r, completo, ed))
    en_vivo, nivel, _, _, r, completo, ed = min(candidatas, key=lambda x: x[:4])
    if en_vivo or nivel > 1:
        return None
    rg = ((ed or {}).get("release-group") or {}).get("id")
    return {"titulo": r["title"], "artista": completo, "album": (ed or {}).get("title"),
            "anio": ((ed or {}).get("date") or "")[:4] or None, "rg": rg, "release": (ed or {}).get("id")}


def guardar_original(carpeta, n, ruta):
    """Guarda las etiquetas actuales del archivo para poder deshacer."""
    carpeta.mkdir(parents=True, exist_ok=True)
    try:
        t = ID3(ruta)
    except ID3NoHeaderError:
        t = None
    datos = {"ruta": ruta}
    portada = None
    for k, f in (("titulo", "TIT2"), ("artista", "TPE1"), ("album", "TALB"), ("anio", "TDRC")):
        datos[k] = str(t[f]) if t is not None and f in t else None
    if t is not None:
        portada = next((t[k] for k in t if k.startswith("APIC")), None)
    datos["portada_mime"] = portada.mime if portada else None
    (carpeta / f"{n}.json").write_text(json.dumps(datos, ensure_ascii=False))
    if portada:
        (carpeta / f"{n}.cover").write_bytes(portada.data)


def guardar_atomico(t, ruta):
    """Escribe las etiquetas en una copia y la reemplaza: si algo falla o el tema está sonando, el original no se rompe."""
    tmp = Path(ruta).with_name(Path(ruta).name + ".simpleplay.tmp")
    try:
        shutil.copy2(ruta, tmp)
        t.save(str(tmp), v2_version=3)
        os.replace(tmp, ruta)
    finally:
        if tmp.exists():
            tmp.unlink()


def escribir_etiquetas(ruta, info, portada):
    try:
        t = ID3(ruta)
    except ID3NoHeaderError:
        t = ID3()
    t["TIT2"] = TIT2(encoding=3, text=info["titulo"])
    t["TPE1"] = TPE1(encoding=3, text=info["artista"])
    if info.get("album"):
        t["TALB"] = TALB(encoding=3, text=info["album"])
    if info.get("anio"):
        t["TDRC"] = TDRC(encoding=3, text=info["anio"])
    if portada:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime=portada[1], type=3, desc="Cover", data=portada[0]))
    guardar_atomico(t, ruta)


def restaurar_originales(carpeta):
    """Deshace un lote: devuelve a cada archivo las etiquetas que tenía. -> cantidad restaurada."""
    hechos = 0
    for j in sorted(carpeta.glob("*.json"), key=lambda x: int(x.stem)):
        d = json.loads(j.read_text())
        if not Path(d["ruta"]).exists():
            continue
        try:
            t = ID3(d["ruta"])
        except ID3NoHeaderError:
            t = ID3()
        for clave, marco, clase in (("titulo", "TIT2", TIT2), ("artista", "TPE1", TPE1),
                                    ("album", "TALB", TALB), ("anio", "TDRC", TDRC)):
            t.delall(marco)
            if d.get(clave) is not None:
                t.add(clase(encoding=3, text=d[clave]))
        t.delall("APIC")
        cover = j.with_suffix(".cover")
        if d.get("portada_mime") and cover.exists():
            t.add(APIC(encoding=3, mime=d["portada_mime"], type=3, desc="Cover", data=cover.read_bytes()))
        guardar_atomico(t, d["ruta"])
        hechos += 1
    return hechos


def etiquetar_archivo(ruta, carpeta_undo, n):
    """Busca y escribe los datos de un archivo. -> (estado, detalle): 'ok', 'sin_coincidencia' o 'error'."""
    try:
        t = ID3(ruta)
    except ID3NoHeaderError:
        t = None
    tit = str(t["TIT2"]) if t is not None and "TIT2" in t else ""
    art = str(t["TPE1"]) if t is not None and "TPE1" in t else ""
    try:
        duracion = duracion_de(ruta) or None
        info = None
        for artista, titulo in candidatos(ruta, tit, art):
            info = buscar_mb(artista, titulo, duracion)
            if info:
                break
        if not info:
            info = buscar_acoustid(ruta, duracion)   # sin nombre útil: se reconoce por el sonido (si hay clave y fpcalc)
        if info:
            portada = descargar_portada(info)
            guardar_original(carpeta_undo, n, ruta)
            escribir_etiquetas(ruta, info, portada)
            return "ok", f"{info['artista']} - {info['titulo']}" + (f" ({info['album']})" if info.get("album") else "") \
                + ("" if portada else " [sin portada]")
        return "sin_coincidencia", ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "error", str(getattr(e, "reason", e))[:120]


class Etiquetador(QObject):
    """Procesa varios archivos en segundo plano, de a uno (MusicBrainz limita el ritmo)."""
    progreso = Signal(int, int, str)
    terminado = Signal(object)

    def __init__(self, rutas, carpeta):
        super().__init__()
        self.rutas, self.carpeta = rutas, carpeta

    def iniciar(self):
        threading.Thread(target=self._trabajo, daemon=True).start()

    def _trabajo(self):
        res = []
        for n, ruta in enumerate(self.rutas, 1):
            self.progreso.emit(n, len(self.rutas), Path(ruta).stem)
            try:
                estado, detalle = etiquetar_archivo(ruta, self.carpeta, n)
            except Exception as e:  # un archivo que falla no frena al resto
                estado, detalle = "error", repr(e)[:120]
            res.append((ruta, estado, detalle))
        self.terminado.emit(res)


def carpeta_deshacer(nueva=False):
    base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "undo"
    if not nueva:
        return base
    carpeta = base / time.strftime("%Y%m%d-%H%M%S")
    for viejo in sorted(base.glob("*"))[:-4] if base.exists() else []:  # se conservan los últimos 5 lotes
        shutil.rmtree(viejo, ignore_errors=True)
    return carpeta


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


class Miniatura(QWidget):
    """La carátula redonda y chica de la píldora. Al cambiar de tema se funde con la anterior, igual que la grande
    (si venía oculta, aparece de a poco en vez de saltar)."""

    def __init__(self, lado):
        super().__init__()
        self.setFixedSize(lado, lado)
        self.actual = self.previa = None
        self.mezcla = 1.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(380)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(self._mezclar)
        self.anim.finished.connect(self._fin)

    def _mezclar(self, v):
        self.mezcla = v
        self.update()

    def _fin(self):
        self.previa = None
        self.update()

    def setPixmap(self, pix):
        nueva = pix if pix is not None and not pix.isNull() else None
        self.previa = self.actual if self.isVisible() else None   # oculta: no hay nada de dónde fundir
        self.actual = nueva
        self.anim.stop()
        if nueva is None:
            self.mezcla = 1.0
            self.update()
        else:
            self.mezcla = 0.0
            self.anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.previa is not None and self.mezcla < 1.0:
            p.drawPixmap(0, 0, self.previa)
        if self.actual is not None:
            p.setOpacity(self.mezcla)
            p.drawPixmap(0, 0, self.actual)


class Menu(QMenu):
    """QMenu con las esquinas redondeadas: sin marco del sistema y con fondo transparente, así se ve el radio del estilo."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def addMenu(self, *args):
        if args and isinstance(args[0], str):       # los submenús también redondeados
            sub = Menu(args[0], self)
            super().addMenu(sub)
            return sub
        return super().addMenu(*args)


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
        self.setFocusPolicy(Qt.NoFocus)
        self.badge = ""  # texto chico sobre el ícono (el "1" del modo repetir un tema)
        self.angulo = 0.0  # vaivén del ícono mientras el botón está "trabajando"
        self._fase = 0.0
        self._osc = QTimer(self)
        self._osc.timeout.connect(self._oscilar)

    def _oscilar(self):
        self._fase += 0.4
        self.angulo = 16 * math.sin(self._fase)
        self.update()

    def set_ocupado(self, si):
        if si:
            self._osc.start(30)
        else:
            self._osc.stop()
            self.angulo = 0.0
            self.update()

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
        nar = QColor(ACENTO)
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
            if self.angulo:
                p.translate(x, y)
                p.rotate(self.angulo)
                p.translate(-x, -y)
            self._icono(p, self.kind, x, y, s, w)
        if self.badge:
            p.setPen(w)
            f = p.font()
            f.setPixelSize(max(int(self.width() * 0.32), 8))
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(x - s * 0.9, y - s * 0.9, s * 1.8, s * 1.8), Qt.AlignCenter, self.badge)

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
        elif k == "repeat":
            pen = QPen(w, 1.7)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(x - s * 1.05, y + s * 0.15), QPointF(x - s * 1.05, y - s * 0.4),
                                      QPointF(x - s * 0.7, y - s * 0.75), QPointF(x + s * 0.55, y - s * 0.75)]))
            p.drawPolyline(QPolygonF([QPointF(x + s * 1.05, y - s * 0.15), QPointF(x + s * 1.05, y + s * 0.4),
                                      QPointF(x + s * 0.7, y + s * 0.75), QPointF(x - s * 0.55, y + s * 0.75)]))
            p.setPen(Qt.NoPen)
            p.setBrush(w)
            tri((x + s * 0.5, y - s * 1.1), (x + s * 0.5, y - s * 0.4), (x + s * 1.0, y - s * 0.75))
            tri((x - s * 0.5, y + s * 0.4), (x - s * 0.5, y + s * 1.1), (x - s * 1.0, y + s * 0.75))
        elif k == "sort":
            for dy, ancho in ((-0.8, 2.2), (0.0, 1.5), (0.8, 0.8)):
                p.drawRoundedRect(QRectF(x - s * 1.1, y + dy * s - s * 0.14, s * ancho, s * 0.28), 1, 1)
        elif k == "broom":
            # se dibuja derecha (cabeza abajo) y se inclina: el mango queda arriba a la derecha
            u = s * 1.2
            p.save()
            p.translate(x + u * 0.1, y)
            p.rotate(38)
            p.setPen(Qt.NoPen)
            p.setBrush(w)
            p.drawRoundedRect(QRectF(-u * 0.11, -u * 1.5, u * 0.22, u * 1.35), u * 0.11, u * 0.11)  # mango
            p.drawRoundedRect(QRectF(-u * 0.42, -u * 0.18, u * 0.84, u * 0.36), u * 0.1, u * 0.1)  # virola
            p.drawPolygon(QPolygonF([QPointF(-u * 0.38, u * 0.28), QPointF(u * 0.38, u * 0.28),
                                     QPointF(u * 0.8, u * 1.35), QPointF(-u * 0.8, u * 1.35)]))  # cerdas
            p.setPen(QPen(QColor(0, 0, 0, 120), max(u * 0.09, 0.8)))
            for fx in (-0.4, 0.0, 0.4):  # rayitas entre las cerdas
                p.drawLine(QPointF(u * fx * 0.55, u * 0.42), QPointF(u * fx * 1.05, u * 1.28))
            p.restore()
        elif k in ("compact", "expand"):
            pen = QPen(w, 1.7)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if k == "compact":  # una píldora baja
                p.drawRoundedRect(QRectF(x - s * 1.25, y - s * 0.55, s * 2.5, s * 1.1), s * 0.55, s * 0.55)
            else:               # la tarjeta
                p.drawRoundedRect(QRectF(x - s * 0.95, y - s * 0.95, s * 1.9, s * 1.9), s * 0.45, s * 0.45)
        elif k == "save":     # disquete
            pen = QPen(w, 1.6)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x - s * 0.95, y - s * 0.95, s * 1.9, s * 1.9), s * 0.3, s * 0.3)
            p.setPen(Qt.NoPen)
            p.setBrush(w)
            p.drawRoundedRect(QRectF(x - s * 0.5, y - s * 0.95, s * 0.95, s * 0.7), 1, 1)    # la tapa metálica
            p.drawRoundedRect(QRectF(x - s * 0.6, y + s * 0.2, s * 1.2, s * 0.75), 1, 1)     # la etiqueta
        elif k == "minus":
            p.drawRoundedRect(QRectF(x - s, y - s * 0.14, 2 * s, s * 0.28), 1, 1)
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
        self.dy = 0.0   # cuánto se corre hacia arriba (px): lo usa la transición hacia las barras
        self._tw = 0    # el ancho del texto: se mide una vez por texto
        self.timer = QTimer(self)               # solo corre si el texto no entra (si no, despertaría 30 veces por segundo en vano)
        self.timer.timeout.connect(self._avanzar)

    def sizeHint(self):
        return QSize(10, self.height())

    def set_text(self, texto):
        self.texto = texto
        self._tw = QFontMetrics(self.fuente).horizontalAdvance(texto)
        self.pos = 0
        self.espera = self.ESPERA
        self._revisar()
        self.update()

    def _ancho(self):
        return self._tw

    def _revisar(self):
        """Enciende el desplazamiento si el texto no entra y lo apaga si entra."""
        if self._ancho() > self.width():
            if not self.timer.isActive():
                self.timer.start(33)
        elif self.timer.isActive():
            self.timer.stop()
            self.pos = 0
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._revisar()

    def showEvent(self, e):
        super().showEvent(e)
        self._revisar()

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
        p.translate(0, self.dy)
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
    N = BANDAS
    SEG, HUECO_SEG, HUECO = 2, 1, 2

    def __init__(self, fuente):
        super().__init__()
        self.fuente = fuente  # callable(n) -> n valores 0..1
        self.vals = [0.0] * self.N
        self.picos = [0.0] * self.N
        self.espera = [0] * self.N
        self.entrada = 1.0   # 0 -> 1: la transición desde el texto; las barras suben de a una, de izquierda a derecha
        self._geom = None    # (tamaño, rectángulos de cada segmento de cada barra, cortes de color): se calcula una vez
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
    def factor(i, n, entrada):
        """Qué parte de su altura tiene la barra i (de n) cuando la entrada va por `entrada` (0-1). Cada una arranca un
        poquito después que la anterior y frena al llegar, así que el conjunto sube como una ola."""
        retraso = 0.5 * i / max(n - 1, 1)
        t = min(max((entrada - retraso) / 0.5, 0.0), 1.0)
        return 1 - (1 - t) ** 3

    @staticmethod
    def _color(frac):
        if frac < 0.55:
            return QColor(60, 220, 70)
        if frac < 0.8:
            return QColor(235, 215, 40)
        return QColor(240, 60, 40)

    def _geometria(self):
        """Los rectángulos de todos los segmentos (por barra, de abajo hacia arriba) y dónde cambia el color. Solo
        dependen del tamaño: se calculan una vez y no en cada cuadro."""
        clave = (self.width(), self.height())
        if self._geom is None or self._geom[0] != clave:
            h = self.height()
            paso = self.SEG + self.HUECO_SEG
            filas = h // paso
            bw = (self.width() - self.HUECO * (self.N - 1)) / self.N
            cols = [[QRectF(i * (bw + self.HUECO), h - (r + 1) * paso + self.HUECO_SEG, bw, self.SEG) for r in range(filas)]
                    for i in range(self.N)]
            verde = sum(1 for r in range(filas) if r / filas < 0.55)
            amarillo = sum(1 for r in range(filas) if r / filas < 0.8)
            self._geom = (clave, cols, filas, verde, amarillo)
        return self._geom[1:]

    def paintEvent(self, e):
        cols, filas, verde, amarillo = self._geometria()
        verdes, amarillos, rojos, picos = [], [], [], []
        for i in range(self.N):
            f = self.factor(i, self.N, self.entrada)
            col = cols[i]
            n = round(self.vals[i] * f * filas)
            if n > 0:
                verdes += col[:min(n, verde)]
                if n > verde:
                    amarillos += col[verde:min(n, amarillo)]
                if n > amarillo:
                    rojos += col[amarillo:n]
            if self.picos[i] * f > 0.02:
                r = min(round(self.picos[i] * f * filas), filas) - 1
                if r >= 0:
                    picos.append(col[r])
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        for lote, color in ((verdes, self._color(0.0)), (amarillos, self._color(0.6)), (rojos, self._color(0.9)),
                            (picos, QColor(255, 255, 255, 220))):
            if lote:
                p.setBrush(color)
                p.drawRects(lote)


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
            c = QColor(ACENTO)
            g.setColorAt(0, QColor("#ff7a2e") if ACENTO == NARANJA else c.lighter(130))
            g.setColorAt(1, QColor("#3a1200") if ACENTO == NARANJA else QColor.fromHsvF(max(c.hueF(), 0.0), c.saturationF(), 0.23))
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



_sombras = {}   # (ancho, alto, radio) -> imagen de la sombra ya difuminada


def _crear_sombra(w, h, radio):
    """Sombra gaussiana de un rectángulo redondeado de w x h, en una imagen con SOMBRA_MARGEN px de aire por lado.
    Se calcula a media resolución (el difuminado lo disimula) con una FFT: es lo que hace falta para que quede suave
    y sin escalones, y se guarda para no repetirlo."""
    m, k = SOMBRA_MARGEN, 2
    W, H = (w + 2 * m + k - 1) // k, (h + 2 * m + k - 1) // k
    forma = QImage(W, H, QImage.Format_Grayscale8)
    forma.fill(0)
    p = QPainter(forma)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(m / k, (m + SOMBRA_DY) / k, w / k, h / k), radio / k, radio / k)
    p.end()
    a = np.frombuffer(forma.constBits(), np.uint8).reshape(H, forma.bytesPerLine())[:, :W].astype(np.float32) / 255
    sigma = SOMBRA_BLUR / k
    fy, fx = np.fft.fftfreq(H)[:, None], np.fft.rfftfreq(W)[None, :]
    b = np.fft.irfft2(np.fft.rfft2(a) * np.exp(-2 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2)), s=(H, W))
    alfa = np.clip(b * SOMBRA_ALPHA * 255, 0, 255).astype(np.uint32)
    return QImage((alfa << 24).tobytes(), W, H, W * 4, QImage.Format_ARGB32_Premultiplied).copy()  # negro con alfa


def dibujar_sombra(p, rect, radio, factor=1.0):
    """Sombra suave bajo un rectángulo redondeado. `factor` (0-1) la atenúa, p. ej. mientras algo aparece."""
    if not SOMBRA or factor <= 0:
        return
    clave = (round(rect.width()), round(rect.height()), round(radio))
    img = _sombras.get(clave)
    if img is None:
        if len(_sombras) >= 24:
            _sombras.pop(next(iter(_sombras)))
        img = _sombras[clave] = _crear_sombra(*clave)
    m = SOMBRA_MARGEN
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setOpacity(factor)
    p.drawImage(QRectF(rect.x() - m, rect.y() - m, img.width() * 2, img.height() * 2), img)
    p.restore()


class Transicion(QWidget):
    """Capa que lleva la ventana de un modo al otro (tarjeta <-> barra compacta).

    Dibuja la captura del modo viejo y, encima, la del nuevo (que va apareciendo) dentro de un rectángulo redondeado
    que cambia de tamaño y de forma. Mientras dura, los widgets reales están ocultos y la ventana mide lo mismo todo el
    tiempo (el mayor de los dos tamaños): redimensionar la ventana en cada cuadro es lo que suele entrecortar estas
    animaciones.
    """
    BASE = QColor(22, 22, 24)  # lo que se ve en las zonas que ninguna de las dos capturas cubre todavía

    def __init__(self, parent, viejo, nuevo, tam1, tam2, radio1, radio2, ms=380):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.viejo, self.nuevo, self.tam1, self.tam2 = viejo, nuevo, tam1, tam2
        self.radio1, self.radio2 = radio1, radio2
        self.t = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(ms)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(self._avanzar)
        self.setGeometry(parent.rect())
        self.show()
        self.anim.start()

    def _avanzar(self, v):
        self.t = float(v)
        self.update()

    def paintEvent(self, e):
        t, m = self.t, SOMBRA_MARGEN       # las capturas incluyen el margen de la sombra; la forma va adentro
        w = self.tam1.width() + (self.tam2.width() - self.tam1.width()) * t - 2 * m
        h = self.tam1.height() + (self.tam2.height() - self.tam1.height()) * t - 2 * m
        r = self.radio1 + (self.radio2 - self.radio1) * t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        forma = QPainterPath()
        forma.addRoundedRect(QRectF(m, m, w, h), r, r)
        dibujar_sombra(p, QRectF(m, m, w, h), r)
        p.setClipPath(forma)
        p.fillRect(QRectF(m, m, w, h), self.BASE)
        # primero se va el modo viejo y después aparece el nuevo, con la base oscura entre ambos: si se mezclaran a la
        # vez se verían los dos textos superpuestos (el título está en un lugar distinto en cada modo)
        p.setOpacity(1.0 - self._suave(t / 0.5))
        p.drawPixmap(0, 0, self.viejo)
        p.setOpacity(self._suave((t - 0.45) / 0.55))
        p.drawPixmap(0, 0, self.nuevo)

    @staticmethod
    def _suave(x):
        x = min(max(x, 0.0), 1.0)
        return x * x * (3 - 2 * x)


if HAY_DBUS:
    # MPRIS es el estándar con el que el escritorio (KDE, GNOME...) manda las teclas multimedia
    # y muestra el reproductor en su panel. Las propiedades y métodos salen de los adaptadores.
    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2"})
    class _MprisRaiz(QDBusAbstractAdaptor):
        def __init__(self, parent, player):
            super().__init__(parent)
            self.p = player

        CanQuit = Property(bool, lambda s: True)
        CanRaise = Property(bool, lambda s: False)
        HasTrackList = Property(bool, lambda s: False)
        Identity = Property(str, lambda s: "simpleplay")
        DesktopEntry = Property(str, lambda s: "simpleplay")
        SupportedUriSchemes = Property("QStringList", lambda s: ["file"])
        SupportedMimeTypes = Property("QStringList", lambda s: ["audio/mpeg"])

        @Slot()
        def Quit(self):
            self.p.close()

        @Slot()
        def Raise(self):
            pass

    @ClassInfo({"D-Bus Interface": "org.mpris.MediaPlayer2.Player"})
    class _MprisPlayer(QDBusAbstractAdaptor):
        def __init__(self, parent, player):
            super().__init__(parent)
            self.p = player

        def _poner_shuffle(self, v):
            self.p.btn_shuffle.setChecked(bool(v))

        Seeked = Signal("qlonglong")  # posición en microsegundos, tras un salto

        PlaybackStatus = Property(str, lambda s: s.p.mpris_estado())
        Metadata = Property("QVariantMap", lambda s: s.p.mpris_metadata())
        Position = Property("qlonglong", lambda s: s.p.mpris_posicion())
        Rate = Property(float, lambda s: 1.0)
        MinimumRate = Property(float, lambda s: 1.0)
        MaximumRate = Property(float, lambda s: 1.0)
        Volume = Property(float, lambda s: 1.0)  # el volumen lo maneja el sistema
        Shuffle = Property(bool, lambda s: s.p.btn_shuffle.isChecked(), _poner_shuffle)

        def _poner_loop(self, v):
            self.p.poner_repetir({"None": "off", "Playlist": "all", "Track": "one"}.get(v, "off"))
            self.p.guardar_estado()

        LoopStatus = Property(str, lambda s: {"off": "None", "all": "Playlist", "one": "Track"}[s.p.repetir], _poner_loop)
        CanGoNext = Property(bool, lambda s: bool(s.p.pistas))
        CanGoPrevious = Property(bool, lambda s: bool(s.p.pistas))
        CanPlay = Property(bool, lambda s: bool(s.p.pistas))
        CanPause = Property(bool, lambda s: True)
        CanSeek = Property(bool, lambda s: s.p.actual >= 0 and s.p.duracion > 0)
        CanControl = Property(bool, lambda s: True)

        @Slot()
        def Next(self):
            self.p.siguiente()

        @Slot()
        def Previous(self):
            self.p.anterior()

        @Slot()
        def Play(self):
            if self.p.actual < 0 or self.p.pausado:
                self.p.play_pausa()

        @Slot()
        def Pause(self):
            if self.p.actual >= 0 and not self.p.pausado:
                self.p.play_pausa()

        @Slot()
        def PlayPause(self):
            self.p.play_pausa()

        @Slot()
        def Stop(self):
            self.p.parar()

        @Slot("qlonglong")
        def Seek(self, offset):
            self.p.saltar_rel(offset / 1e6)

        @Slot(QDBusObjectPath, "qlonglong")
        def SetPosition(self, trackid, pos):
            if self.p.actual >= 0 and self.p.duracion > 0:
                self.p.saltar(min(max(pos / 1e6 / self.p.duracion, 0.0), 0.999))

        @Slot(str)
        def OpenUri(self, uri):
            ruta = QUrl(uri).toLocalFile()
            if ruta.lower().endswith(EXTENSIONES) and Path(ruta).exists():
                self.p.agregar([ruta])
                self.p.reproducir(len(self.p.pistas) - 1)

    class Mpris(QObject):
        RUTA = "/org/mpris/MediaPlayer2"

        def __init__(self, player):
            super().__init__(player)
            self.activo = False
            self.raiz = _MprisRaiz(self, player)
            self.rep = _MprisPlayer(self, player)
            self.bus = QDBusConnection.sessionBus()
            if not self.bus.isConnected():
                log("MPRIS: no hay bus de sesión")
                return
            self.nombre = "org.mpris.MediaPlayer2.simpleplay"
            if not self.bus.registerService(self.nombre):  # ya hay otra ventana abierta
                self.nombre += f".instance{os.getpid()}"
                if not self.bus.registerService(self.nombre):
                    log("MPRIS: no se pudo registrar el nombre")
                    return
            self.activo = self.bus.registerObject(self.RUTA, self, QDBusConnection.ExportAdaptors)
            log("MPRIS:", self.nombre, "activo" if self.activo else "no se pudo exportar")

        def actualizar(self, *claves):
            """Avisa al escritorio que cambiaron esas propiedades (estado, tema, botones...)."""
            if not self.activo:
                return
            cambios = {k: getattr(self.rep, k) for k in claves}
            vacio = QDBusArgument()  # la lista de "invalidadas" tiene que viajar como 'as', no 'av'
            vacio.beginArray(QMetaType(QMetaType.Type.QString))
            vacio.endArray()
            m = QDBusMessage.createSignal(self.RUTA, "org.freedesktop.DBus.Properties", "PropertiesChanged")
            m.setArguments(["org.mpris.MediaPlayer2.Player", cambios, vacio])
            self.bus.send(m)

        def seeked(self, pos_us):
            """Avisa que la posición cambió de golpe (un salto): los paneles del escritorio la releen al instante."""
            if not self.activo:
                return
            self.rep.Seeked.emit(int(pos_us))

        def cerrar(self):
            if self.activo:
                self.bus.unregisterObject(self.RUTA)
                self.bus.unregisterService(self.nombre)
                self.activo = False


# --- motor de audio -----------------------------------------------------------------------------
# Reproduce con miniaudio (float32 estéreo a 44,1 kHz): la posición, la pausa, el salto, el fin de pista
# y las muestras para el espectro salen todos del mismo callback, así que no hay desfases entre ellos.
FS = 44100          # frecuencia fija del dispositivo: miniaudio convierte los archivos que usen otra
FADE = 220          # frames (5 ms) de los fundidos de salto y de cambio de tema, para que no haya clicks
FUNDIDO_SALIDA_S = 0.25   # al pausar, parar o cerrar el volumen baja en este tiempo (antes cortaba en 5 ms)
FUNDIDO_ENTRADA_S = 0.15  # al reanudar sube en este tiempo
# Qué casillas de la transformada entran en cada banda (se calcula una vez) y cuánto se compensa la caída natural de
# los agudos en la música.
_RES = FS / VENTANA
_LO = np.array([int(_BORDES[k] / _RES) for k in range(BANDAS)])
_HI = np.maximum(np.array([int(_BORDES[k + 1] / _RES) for k in range(BANDAS)]), _LO + 1)
_IDX = np.empty(2 * BANDAS, dtype=np.intp)
_IDX[0::2], _IDX[1::2] = _LO, _HI
_COMP = np.array([3 * math.log2(math.sqrt(_BORDES[k] * _BORDES[k + 1]) / 100) for k in range(BANDAS)])
LECTURA = 8192      # tope de frames por send() (el generador de miniaudio reserva 16384)
PREVIOS = 4         # frames mp3 que se decodifican de más antes de un salto (llenan la reserva de bits)

_BR1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_BR2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_FREC = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _sistemas_de_sonido():
    """Los sistemas de sonido reales de cada plataforma, en orden de preferencia. Sin lista, miniaudio termina
    cayendo a un dispositivo nulo que no suena: la barra avanzaría sin que se oiga nada y sin ningún aviso."""
    B = miniaudio.Backend
    if sys.platform == "win32":
        orden = (B.WASAPI, B.DSOUND, B.WINMM)
    elif sys.platform == "darwin":
        orden = (B.COREAUDIO,)
    else:
        orden = (B.PULSEAUDIO, B.ALSA, B.JACK, B.OSS, B.SNDIO, B.AUDIO4)  # PipeWire se ofrece como PulseAudio
    return list(orden)


def _cabecera_mp3(b, i):
    """(largo del frame, muestras por frame, frecuencia) del frame mp3 (capa III) que empieza en b[i], o None."""
    if i + 4 > len(b) or b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
        return None
    ver, capa = (b[i + 1] >> 3) & 3, (b[i + 1] >> 1) & 3
    if ver == 1 or capa != 1:
        return None
    br_i, fr_i, pad = b[i + 2] >> 4, (b[i + 2] >> 2) & 3, (b[i + 2] >> 1) & 1
    if br_i in (0, 15) or fr_i == 3:
        return None
    fr = _FREC[ver][fr_i]
    if ver == 3:
        return 144 * _BR1[br_i] * 1000 // fr + pad, 1152, fr
    return 72 * _BR2[br_i] * 1000 // fr + pad, 576, fr


def indexar_mp3(b):
    """Recorre los frames de un mp3 (bytes o mmap) -> (offsets de los frames de audio, muestras por frame,
    frecuencia, retardo en muestras que recorta el decodificador).

    Sirve para saltar a cualquier punto sin decodificar desde el principio (miniaudio lo hace linealmente: más
    de un segundo en un mix de una hora). El frame Xing/Info no tiene audio y no se cuenta; si trae la etiqueta
    LAME, de ahí sale el retardo del encoder (+529 del decodificador), que es lo que recorta el gapless.
    """
    i, n = 0, len(b)
    if b[:3] == b"ID3":
        i = 10 + ((b[6] << 21) | (b[7] << 14) | (b[8] << 7) | b[9])
    offs, spf, fr, retardo = [], 1152, 44100, 0
    while i < n - 4:
        h = _cabecera_mp3(b, i)
        if h is None:                      # perdió el hilo (basura o etiqueta): busca el próximo sincronismo
            j = b.find(b"\xff", i + 1)
            if j < 0:
                break
            i = j
            continue
        largo, spf, fr = h
        if not offs and retardo == 0 and spf == 1152:
            mono = (b[i + 3] >> 6) == 3
            x = i + (21 if mono else 36)   # dónde empieza "Xing"/"Info" en un frame MPEG-1
            if b[x:x + 4] in (b"Xing", b"Info"):
                lame = x + 120             # extensión LAME: 9 bytes de versión y, 21 bytes después, el retardo
                if b[lame:lame + 3] in (b"LAM", b"Lav") and lame + 24 < n:
                    ret = (b[lame + 21] << 4) | (b[lame + 22] >> 4)
                    retardo = (ret if 0 < ret < 2000 else 576) + 529
                else:
                    retardo = -1           # hay frame Xing pero sin etiqueta LAME: no se recorta nada
                i += largo
                continue
        offs.append(i)
        i += largo
    return offs, spf, fr, max(retardo, 0)


class FuenteMp3(miniaudio.StreamableSource):
    """Lee un mp3 desde un frame dado (y hasta otro, si se pide): para el decodificador, ese frame es el
    principio del archivo."""

    def __init__(self, datos, desde, hasta=None):
        self.d, self.base, self.p = datos, desde, desde
        self.fin = len(datos) if hasta is None else hasta

    def read(self, n):
        r = self.d[self.p:min(self.p + n, self.fin)]
        self.p += len(r)
        return r

    def seek(self, offset, origin):
        if origin == miniaudio.SeekOrigin.START:
            self.p = self.base + offset
        elif origin == miniaudio.SeekOrigin.CURRENT:
            self.p += offset
        return True


def _leer(gen, n):
    """Hasta n frames estéreo float32 del generador de miniaudio (menos si se acabó). Array (m, 2)."""
    trozos, falta = [], n
    while falta > 0:
        try:
            a = gen.send(min(falta, LECTURA))
        except StopIteration:
            break
        x = np.frombuffer(a, dtype=np.float32).reshape(-1, 2)
        if len(x) == 0:
            break
        trozos.append(x)
        falta -= len(x)
        if len(x) < min(falta + len(x), LECTURA):   # trozo corto: fin del archivo
            break
    return np.concatenate(trozos) if trozos else np.zeros((0, 2), np.float32)


# ------------------------------------------------------------------------------------------------
# Remuestreo. El dispositivo va fijo a 44,1 kHz (FS). Lo que no sea de 44,1 kHz (48, 96, 88,2, 32 kHz...) lo
# convertía el remuestreador interno de miniaudio, que es lineal con un filtro de poco orden: a 10 kHz sale
# 1,2 dB abajo, a 18 kHz 4,2 dB abajo y deja un alias a 14,1 kHz solo 13 dB debajo del tono. Este es un
# remuestreador polifásico de fase lineal (sinc con ventana Kaiser): plano hasta ~20 kHz, más de 90 dB de
# rechazo del alias, sin dependencias. Solo se usa con archivos que no son de 44,1 kHz; el resto pasa intacto.

RECHAZO_DB = 96        # atenuación mínima de lo que cae por encima de la frecuencia de Nyquist de salida
TRANSICION = 0.0465    # ancho de la banda de transición, en fracción de la frecuencia menor (2050 Hz a 44,1 kHz)
_COLA_REMUESTREO = 2048


def _razon(f_ent, f_sal):
    g = math.gcd(f_ent, f_sal)
    return f_sal // g, f_ent // g


@functools.lru_cache(maxsize=8)
def _tabla_remuestreo(f_ent, f_sal):
    """(L, M, H, A): razón L/M, medio ancho del filtro (en muestras de entrada) y la matriz A de L filas. Un bloque de
    L muestras de salida sale de M muestras nuevas de entrada: salida = A @ ventana, con una ventana de A.shape[1]
    muestras que arranca H-1 antes del primer punto del bloque. Cada fila es el filtro sinc con ventana Kaiser de la
    fase que le toca, desplazado donde corresponde."""
    L, M = _razon(f_ent, f_sal)
    parada = min(f_ent, f_sal) / 2                       # desde acá hay que rechazar
    ancho = TRANSICION * min(f_ent, f_sal)
    corte = (parada - ancho / 2) / f_ent                 # ciclos por muestra de entrada, en medio de la transición
    dw = 2 * math.pi * ancho / f_ent
    K = int(math.ceil((RECHAZO_DB - 8) / (2.285 * dw)))
    H = max(4, min((K + 1) // 2, 256))
    beta = 0.1102 * (RECHAZO_DB - 8.7)
    q = np.arange(L)
    i0, fase = (q * M) // L, (q * M) % L
    k = np.arange(2 * H)[None, :]
    tau = (fase / L)[:, None] + (H - 1 - k)              # distancia de cada muestra de entrada al punto de salida
    h = 2 * corte * np.sinc(2 * corte * tau)
    h = h * np.i0(beta * np.sqrt(np.clip(1 - (tau / H) ** 2, 0, None))) / np.i0(beta)
    h /= h.sum(axis=1, keepdims=True)                    # cada fase deja pasar el continuo con ganancia exacta 1
    A = np.zeros((L, int(i0[-1]) + 2 * H), np.float32)
    for r in range(L):
        A[r, i0[r]:i0[r] + 2 * H] = h[r]
    return L, M, H, A


class Remuestreador:
    """Envuelve un generador estéreo float32 de miniaudio (en la frecuencia del archivo) y entrega la misma
    interfaz (send(n) -> n frames) a FS. Si el origen se acaba, el último send() es corto y el siguiente corta."""
    def __init__(self, origen, f_ent, f_sal=FS):
        self.src, self.f_ent = origen, f_ent
        self.L, self.M, self.H, self.A = _tabla_remuestreo(f_ent, f_sal)
        self.buf = np.zeros((self.H - 1, 2), np.float32)  # antes del principio todo es silencio
        self.base = -(self.H - 1)                         # índice (en muestras de entrada) de buf[0]
        self.entrada = 0                                  # muestras reales leídas del origen
        self.fin = False
        self.b = 0                                        # próximo bloque de salida
        self.cola = np.zeros((0, 2), np.float32)          # salida ya calculada y todavía no entregada
        self.limite = None                                # al llegar el final: cuántas muestras de salida existen

    def _bloques(self, nb):
        """Calcula nb bloques más de salida y los agrega a la cola."""
        L, M, A = self.L, self.M, self.A
        ancho = A.shape[1]
        ini = self.b * M - (self.H - 1)                   # primera muestra de entrada del primer bloque
        ult = (self.b + nb - 1) * M - (self.H - 1) + ancho - 1
        while not self.fin and self.base + len(self.buf) <= ult:
            pedir = max(4096, ult + 1 - (self.base + len(self.buf)))
            x = _leer(self.src, pedir)
            self.entrada += len(x)
            if len(x) < pedir:
                self.fin = True
                self.limite = -(-self.entrada * L // M)  # salidas con t < fin del archivo
            if len(x):
                self.buf = np.concatenate((self.buf, x))
        falta = ult + 1 - (self.base + len(self.buf))
        if falta > 0:                                     # pasado el final del archivo: silencio
            self.buf = np.concatenate((self.buf, np.zeros((falta, 2), np.float32)))
        v = np.lib.stride_tricks.sliding_window_view(self.buf, ancho, axis=0)    # (m, 2, ancho), sin copiar
        X = v[ini - self.base::M][:nb]                    # (nb, 2, ancho): la ventana de cada bloque
        Y = np.matmul(X, A.T)                             # (nb, 2, L)
        y = np.ascontiguousarray(Y.transpose(0, 2, 1)).reshape(-1, 2)
        if self.limite is not None:
            y = y[:max(self.limite - self.b * L, 0)]
        self.cola = np.concatenate((self.cola, y)) if len(self.cola) else y
        self.b += nb
        corte = (self.b) * M - (self.H - 1) - self.base   # lo que ya no hace falta del buffer
        if corte > 0:
            self.buf = self.buf[corte:]
            self.base += corte

    def send(self, n):
        while len(self.cola) < n and not (self.limite is not None and self.b * self.L >= self.limite):
            self._bloques(max(1, -(-max(_COLA_REMUESTREO, n - len(self.cola)) // self.L)))
        if len(self.cola) == 0:
            raise StopIteration
        out, self.cola = self.cola[:n], self.cola[n:]
        return out.tobytes()


_frecuencias = {}


def frecuencia_de(ruta):
    """Frecuencia de muestreo del archivo (header solamente), o None si no se pudo saber."""
    try:
        clave = (ruta, os.stat(ruta).st_mtime_ns)
    except OSError:
        return None
    if clave not in _frecuencias:
        try:
            f = MutagenFile(ruta)
            fr = int(f.info.sample_rate) if f is not None and getattr(f.info, "sample_rate", 0) else None
        except Exception:
            fr = None
        if len(_frecuencias) > 256:
            _frecuencias.clear()
        _frecuencias[clave] = fr
    return _frecuencias[clave]


def abrir_fuente(ruta, frame=0, frames_to_read=1024):
    """Generador estéreo float32 a FS que empieza en `frame` (a FS). Lo que no es de 44,1 kHz pasa por el remuestreador."""
    F32 = miniaudio.SampleFormat.FLOAT32
    fr = frecuencia_de(ruta)
    if not fr or fr == FS or not (4000 <= fr <= 384000) or _razon(fr, FS)[0] > 640:
        return miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=FS,
                                     frames_to_read=frames_to_read, seek_frame=frame)
    g = miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=fr, frames_to_read=frames_to_read,
                              seek_frame=round(frame * fr / FS))
    return Remuestreador(g, fr)


# ------------------------------------------------------------------------------------------------
# Sonido: normalización de volumen, ecualizador y limitador. Corre al final del motor, antes del dispositivo.

BANDAS_HZ = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
# Ganancia en dB de cada banda. "plano" no toca nada (el audio pasa tal cual); el resto son retoques suaves.
PRESETS = {
    "plano":     (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "vivo":      (4, 3.5, 2, 0, -0.5, 0, 0.5, 2, 3.5, 3),
    "graves":    (6, 5, 3.5, 1.5, 0, 0, 0, 0, 0, 0),
    "voces":     (-2, -1.5, -1, 0, 1, 2.5, 3, 1.5, 0, -1),
    "brillante": (-1, -0.5, 0, 0, 0, 0.5, 2, 3.5, 4.5, 4),
    "calido":    (3, 2.5, 2, 1, 0, -0.5, -1, -2, -2.5, -3),
}
PRESET_INICIAL = "vivo"
NOMBRES_PRESETS = {"plano": ("Plano (sin ecualizar)", "Flat (no EQ)"), "vivo": ("Vivo", "Lively"),
                   "graves": ("Más graves", "More bass"), "voces": ("Voces", "Vocals"),
                   "brillante": ("Brillante", "Bright"), "calido": ("Cálido", "Warm")}
LIM_BANDA_DB = 12.0          # el ecualizador gráfico va de -12 a +12 dB por banda

# Ecualizador paramétrico: pocas bandas, pero cada una con su frecuencia, su ganancia y su ancho (Q). Se calcula como la suma
# de filtros "campana" (biquads de R. Bristow-Johnson) y suena por el mismo filtro de fase mínima que el gráfico.
PARAM_BANDAS_INICIAL = ((80.0, 0.0, 1.0), (250.0, 0.0, 1.0), (1000.0, 0.0, 1.0), (4000.0, 0.0, 1.0), (10000.0, 0.0, 1.0))
PARAM_HZ = (20.0, 20000.0)
PARAM_Q = (0.3, 10.0)

# Crossfeed (para auriculares): cada oído oye un poco del otro canal, apagado en agudos y con un retraso de ~0,3 ms, como pasa con
# parlantes. Las bocinas dejan de sentirse pegadas a las orejas y se cansa menos. Niveles: apagado, suave, medio, fuerte.
CROSSFEED_NIVELES = (0.0, 0.25, 0.4, 0.6)
CROSSFEED_CORTE_HZ = 700.0
CROSSFEED_RETRASO = 6        # muestras (0,14 ms); con el retraso propio del pasabajos, ~0,3 ms
CROSSFEED_TAPS = 64

# Cada eje del afinador mueve varias bandas a la vez con una forma suave (valor por banda de BANDAS_HZ): son pocos
# ajustes que se entienden al oído (graves, cuerpo, presencia, brillo) y no diez botones sueltos.
EJES_AFINADOR = {
    "graves":    (1.0, 1.0, 0.8, 0.4, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0),
    "cuerpo":    (0.0, 0.1, 0.5, 1.0, 0.8, 0.2, 0.0, 0.0, 0.0, 0.0),
    "presencia": (0.0, 0.0, 0.0, 0.0, 0.2, 0.6, 1.0, 0.9, 0.2, 0.0),
    "brillo":    (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.5, 1.0, 1.0),
}


OBJETIVO_LUFS = -16.0        # sonoridad a la que se lleva cada tema
GANANCIA_MAX_DB, GANANCIA_MIN_DB = 9.0, -12.0
LIM_TECHO = 0.9              # el limitador no deja pasar picos de más de esto (-0,9 dBFS: queda margen para los picos entre muestras)
LIM_ANTICIPO = 220           # muestras que mira hacia adelante (5 ms): el audio sale con ese retraso mientras la cadena está activa
LIM_SUELTA_S = 0.1           # constante de tiempo con la que la ganancia vuelve a 1 después de un pico
LIM_FUNDIDO = 4 * LIM_ANTICIPO   # fundido al prender o apagar el limitador (el retraso aparece o desaparece sin clicks)
LARGO_SIN_MEDIR = 15 * 60    # los temas más largos (mezclas, sets) no se miden: ya son una sola pieza
RAMPA_DB_S = 8.0             # cuando la medida llega con el tema sonando, la ganancia se acomoda a esta velocidad (dB por s)
TAPS = 4095                  # largo del filtro del ecualizador (con fase mínima no agrega retraso: solo cuesta CPU)
# Fase del ecualizador. "minima" (por defecto): la respuesta empieza de inmediato, sin retraso ni eco previo, y con el mismo
# largo resuelve los graves bastante mejor (como un ecualizador analógico o de biquads). "lineal": fase lineal, el retraso
# es de (TAPS-1)/2 muestras y la resolución en graves es menor. Para comparar de oído: SIMPLEPLAY_EQ_FASE=lineal
FASE_EQ = "lineal" if os.environ.get("SIMPLEPLAY_EQ_FASE", "minima") == "lineal" else "minima"


def _taps_ecualizador(gan_db, freqs=None):
    """Filtro FIR que aplica una curva de ganancias (dB), interpolada en escala logarítmica. Por defecto son las 10
    bandas de los presets (BANDAS_HZ); con `freqs` puede ser cualquier tabla (frecuencia, dB), por ejemplo la de un perfil
    de auriculares. Fase mínima (ver FASE_EQ): se parte del logaritmo de la magnitud, se pliega el cepstro y se vuelve."""
    m = 1 << 15
    f = np.fft.rfftfreq(m, 1 / FS)
    f[0] = 1.0
    curva = np.interp(np.log10(f), np.log10(BANDAS_HZ if freqs is None else freqs), gan_db)
    if FASE_EQ == "lineal":
        h0 = np.fft.irfft(10 ** (curva / 20), n=m)           # respuesta de fase cero
        medio = (TAPS - 1) // 2
        h = np.concatenate([h0[-medio:], h0[:medio + 1]]) * np.hanning(TAPS)
        return h.astype(np.float32)
    cepstro = np.fft.irfft(curva / 20 * math.log(10), n=m)   # cepstro real del logaritmo de la magnitud
    pliegue = np.zeros(m)
    pliegue[0], pliegue[1:m // 2], pliegue[m // 2] = 1, 2, 1  # duplica lo causal y anula lo anticausal
    h = np.fft.irfft(np.exp(np.fft.rfft(cepstro * pliegue)), n=m)[:TAPS]
    n = TAPS * 3 // 10                                        # la cola ya es casi nada: se baja suave hasta cero
    h[-n:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(n) / n)
    return h.astype(np.float32)


def _filtro_crossfeed():
    """Pasabajos de un polo (de fase mínima: casi no corre la fase de los graves) precedido del retraso; ganancia 1 en continua."""
    p = math.exp(-2 * math.pi * CROSSFEED_CORTE_HZ / FS)
    h = p ** np.arange(CROSSFEED_TAPS)
    return np.concatenate([np.zeros(CROSSFEED_RETRASO), h / h.sum()]).astype(np.float32)


_H_CROSSFEED = _filtro_crossfeed()


def curva_parametrica(bandas, freqs=None):
    """Ganancia total (dB) de varias bandas (frecuencia, ganancia, Q) a las frecuencias `freqs` (por defecto PUNTOS_PERFIL)."""
    f = PUNTOS_PERFIL if freqs is None else np.asarray(freqs, dtype=float)
    curva = np.zeros(len(f))
    for fc, g, q in bandas:
        if g:
            curva += _respuesta_biquad("PK", float(fc), float(g), float(q), f)
    return curva


class Cadena:
    """Ganancia por tema (normalización) + ecualizador + limitador suave, sobre bloques estéreo float32.

    Sin ecualizador ni ganancia, `activa` es False y el audio no se toca. Los cambios (otro preset, otra
    ganancia) se hacen con fundido dentro del bloque para que no haya clicks.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._h = None                    # filtro actual (None = sin ecualizar, sin retraso)
        self._pend = None                 # ("eq", taps o None, preamp lineal) a aplicar en el próximo bloque
        self._pre = 1.0                   # reducción por lo que sube el ecualizador (evita saturar)
        self._gan_obj = 1.0               # ganancia de la pista (normalización), lineal
        self._gan_act = 1.0
        self._suave = False               # la próxima ganancia se alcanza con una rampa lenta en vez de un fundido corto
        self._pre_act = 1.0
        self._hist = np.zeros((TAPS - 1, 2), np.float32)
        self._cache_h = {}
        self._lim_u = np.zeros((LIM_ANTICIPO - 1, 2), np.float32)     # audio que espera su turno (el retraso del limitador)
        self._lim_r = np.ones(2 * (LIM_ANTICIPO - 1), np.float32)     # ganancia que pide cada muestra reciente
        self._lim_def = 0.0               # cuánto falta para volver a ganancia 1 (1 - ganancia), baja con LIM_SUELTA_S
        self._lim_vivo = False            # el limitador está corriendo (y el audio sale retrasado)
        self._bal_obj = self._bal_act = (1.0, 1.0)       # ganancia de cada canal (balance)
        self._cf_obj = self._cf_act = 0.0                # cuánto del otro canal se mezcla (crossfeed)
        self._cf_hist = np.zeros((len(_H_CROSSFEED) - 1, 2), np.float32)

    @property
    def activa(self):
        return (self._h is not None or self._pend is not None or self._gan_obj != 1.0 or self._gan_act != 1.0
                or self._lim_vivo or self._espacial_activo())

    def _espacial_activo(self):
        return (self._cf_obj > 0 or self._cf_act > 0 or self._bal_obj != (1.0, 1.0) or self._bal_act != (1.0, 1.0))

    def poner_balance(self, pct):
        """Balance de -100 (todo a la izquierda) a +100 (todo a la derecha): baja el canal opuesto, el otro queda igual."""
        b = max(-100.0, min(100.0, float(pct))) / 100
        self._bal_obj = (1.0 - max(0.0, b), 1.0 + min(0.0, b))

    def poner_crossfeed(self, cantidad):
        """Cuánto del otro canal se mezcla en cada oído (0 = apagado; ver CROSSFEED_NIVELES)."""
        self._cf_obj = max(0.0, min(1.0, float(cantidad)))

    def _espacial(self, y):
        """Crossfeed y balance, con rampa dentro del bloque para que prender, apagar o mover no haga clicks."""
        n = len(y)
        if self._cf_obj > 0 or self._cf_act > 0:
            ext = np.concatenate([self._cf_hist, y])
            self._cf_hist = ext[-(len(_H_CROSSFEED) - 1):].copy()
            bajo = np.stack([np.convolve(ext[:, c], _H_CROSSFEED, "valid") for c in (0, 1)], axis=1)   # graves de cada canal, retrasados
            a = np.linspace(self._cf_act, self._cf_obj, n, dtype=np.float32)[:, None]
            y = y + a * (bajo[:, ::-1] - bajo)           # en los graves cada oído toma algo del otro; lo que es igual en los dos (mono) queda tal cual
            self._cf_act = self._cf_obj
        else:
            self._cf_hist[:] = 0.0
        if self._bal_obj != (1.0, 1.0) or self._bal_act != (1.0, 1.0):
            g = np.stack([np.linspace(self._bal_act[0], self._bal_obj[0], n),
                          np.linspace(self._bal_act[1], self._bal_obj[1], n)], axis=1).astype(np.float32)
            y = y * g
            self._bal_act = self._bal_obj
        return y

    def poner_ganancia(self, db, suave=False):
        """Ganancia del tema en dB. Con `suave`, se llega a ella de a poco (RAMPA_DB_S): para una medida que llega con el
        tema ya sonando; si no, un salto repentino se oye. Sin `suave` es un fundido de un bloque (cambio de tema)."""
        self._suave = suave
        self._gan_obj = 10 ** (max(GANANCIA_MIN_DB, min(GANANCIA_MAX_DB, db)) / 20)

    def poner_eq(self, gan_db, freqs=None, makeup_db=0.0, nivel_db=None):
        """gan_db: 10 valores en dB (BANDAS_HZ), o None / todo ceros para dejarlo plano. Con `freqs`, una tabla de
        ganancias en esas frecuencias (un perfil de auriculares); `makeup_db` sube el nivel general para compensar lo que
        el perfil baja (ver `nivel_relativo_db`). Con `nivel_db` (el nivel relativo de la curva) el preamplificador la
        deja a igual volumen que sin ecualizar: se usa al comparar curvas, para que la más fuerte no gane por serlo."""
        plano = gan_db is None or (not any(gan_db) and not makeup_db)
        with self._lock:
            if plano and self._h is None and self._pend is None:
                return
            if plano:
                self._pend = ("bypass", None, 1.0)  # se funde de vuelta al audio tal cual y el filtro deja de correr
            else:
                subida = max(0.0, max(gan_db))
                pre_db = -nivel_db if nivel_db is not None else (-0.5 * subida if freqs is None else makeup_db - subida)
                self._pend = ("eq", _taps_ecualizador(gan_db, freqs), 10 ** (pre_db / 20))

    def _filtrar(self, ext, h):
        n = len(ext) - (TAPS - 1)
        L = 1 << (len(ext) - 1).bit_length()
        clave = (id(h), L)
        H = self._cache_h.get(clave)
        if H is None:
            if len(self._cache_h) > 8:
                self._cache_h.clear()
            H = self._cache_h[clave] = (np.fft.rfft(h, L), h)       # se guarda h: mantiene vivo su id
        y = np.fft.irfft(np.fft.rfft(ext, L, axis=0) * H[0][:, None], L, axis=0)
        return y[TAPS - 1:TAPS - 1 + n].astype(np.float32)

    def procesar(self, x):
        n = len(x)
        with self._lock:
            pend, self._pend = self._pend, None
        ext = np.concatenate([self._hist, x])
        self._hist = ext[-(TAPS - 1):].copy()
        pre_obj = self._pre
        if pend is not None:
            _, h_nuevo, pre_obj = pend
            self._pre = pre_obj
            r = np.minimum(np.arange(1, n + 1) / 2205.0, 1.0).astype(np.float32)[:, None]   # fundido de 50 ms
            nuevo = self._filtrar(ext, h_nuevo) if h_nuevo is not None else x
            viejo = self._filtrar(ext, self._h) if self._h is not None else x     # sin filtro previo: se funde desde el audio tal cual, sin saltos
            y = viejo * (1 - r) + nuevo * r
            self._h = h_nuevo
        elif self._h is not None:
            y = self._filtrar(ext, self._h)
        else:
            y = x
        if self._suave and self._gan_act != self._gan_obj:
            # rampa en dB (se oye pareja): como mucho RAMPA_DB_S dB por segundo hacia el objetivo
            ini, meta = 20 * math.log10(self._gan_act), 20 * math.log10(self._gan_obj)
            tope = RAMPA_DB_S * n / FS
            fin = ini + max(-tope, min(tope, meta - ini))
            gan = 10 ** (np.linspace(ini, fin, n) / 20)
            gan_fin = self._gan_obj if abs(meta - fin) < 1e-6 else 10 ** (fin / 20)
        else:
            gan, gan_fin = np.linspace(self._gan_act, self._gan_obj, n), self._gan_obj
        pre = np.linspace(self._pre_act, pre_obj, n)
        if gan[0] != 1.0 or gan[-1] != 1.0 or pre[0] != 1.0 or pre[-1] != 1.0:
            y = y * (gan * pre).astype(np.float32)[:, None]
        self._gan_act, self._pre_act = gan_fin, pre_obj
        hay_espacial = self._espacial_activo()
        if hay_espacial:
            y = self._espacial(y)
        base = self._h is not None or self._gan_obj != 1.0 or self._gan_act != 1.0 or hay_espacial
        y = y.astype(np.float32, copy=False)
        if not base and not self._lim_vivo:
            return y                                   # nada que hacer: el audio pasa tal cual y sin retraso
        arranca = not self._lim_vivo
        if arranca:                                    # sin pasado: se llena el retraso con la primera muestra (sin saltos)
            self._lim_u[:] = y[0]
            self._lim_r[:] = min(1.0, LIM_TECHO / max(float(np.abs(y[0]).max()), 1e-9))
        d = self._limitar(y)
        cf = min(n, LIM_FUNDIDO)
        r = np.minimum(np.arange(1, n + 1) / cf, 1.0).astype(np.float32)[:, None]
        if arranca and base:                           # entra el limitador: del audio directo al retrasado
            self._lim_vivo = True
            directo = y * np.minimum(1.0, LIM_TECHO / np.maximum(np.abs(y).max(axis=1), 1e-9)).astype(np.float32)[:, None]
            return (directo * (1 - r) + d * r).astype(np.float32)     # (el directo también respeta el techo)
        if not base:                                   # sale: del retrasado al audio directo, y se reinicia
            self._lim_vivo = False
            self._lim_u[:] = 0.0
            self._lim_r[:] = 1.0
            self._lim_def = 0.0
            return (d * (1 - r) + y * r).astype(np.float32)
        return d

    def _limitar(self, y):
        """Limitador con anticipación: cada muestra sale LIM_ANTICIPO-1 muestras después de entrar, y en ese tiempo se mira
        lo que viene. La ganancia baja de a poco para llegar justo al pico (sin distorsionar la onda) y vuelve a 1 despacio.
        Es la misma para los dos canales, así la imagen estéreo no se corre. Nunca pasa de LIM_TECHO."""
        n, LA = len(y), LIM_ANTICIPO
        D = LA - 1
        pico = np.abs(y).max(axis=1)
        r = np.concatenate((self._lim_r, np.minimum(1.0, LIM_TECHO / np.maximum(pico, 1e-9)).astype(np.float32)))
        u = np.concatenate((self._lim_u, y))
        self._lim_r, self._lim_u = r[-2 * D:].copy(), u[-D:].copy()
        if self._lim_def < 1e-4 and r.min() >= 1.0:
            self._lim_def = 0.0
            return u[:n]                               # nada que limitar: solo el retraso
        m = np.lib.stride_tricks.sliding_window_view(r, LA).min(axis=1)       # el pedido más duro de los próximos LA
        c = np.concatenate(([0.0], np.cumsum(m, dtype=np.float64)))
        deficit = 1.0 - (c[LA:] - c[:-LA]) / LA                               # promedio móvil: el ataque llega en rampa
        b = math.exp(-1.0 / (LIM_SUELTA_S * FS))                              # suelta: el déficit decae de a poco
        q = np.empty(n)
        for k in range(0, n, 4096):                                           # q[i] = max(d[j] * b**(i-j)), sin bucle por muestra
            d = deficit[k:k + 4096]
            e = b ** np.arange(len(d))
            v = np.maximum.accumulate(d / e) * e
            q[k:k + len(d)] = np.maximum(v, self._lim_def * b ** (np.arange(len(d)) + 1))
            self._lim_def = float(q[k + len(d) - 1])
        return u[:n] * (1.0 - q).astype(np.float32)[:, None]


def _sonoridad(bloques):
    """Sonoridad integrada (LUFS aproximados, ponderación K de BS.1770 con puerta) de varios trozos estéreo
    de 44,1 kHz. Devuelve (lufs, pico de muestra) o None si todo es silencio."""
    medias, pico = [], 0.0
    for x in bloques:
        if len(x) < FS // 2:
            continue
        pico = max(pico, float(np.abs(x).max()))
        f = np.fft.rfftfreq(len(x), 1 / FS)
        w = 10 ** (4.0 / 20 * (f ** 2 / (f ** 2 + 1681.0 ** 2))) * (f ** 2 / (f ** 2 + 38.0 ** 2))   # estante + pasaaltos
        y = np.fft.irfft(np.fft.rfft(x, axis=0) * w[:, None], len(x), axis=0)
        n = int(0.4 * FS)
        for i in range(0, len(y) - n + 1, n):
            medias.append(float(np.mean(y[i:i + n] ** 2, axis=0).sum()))   # canales L+R con peso 1
    if not medias:
        return None
    m = np.array(medias)
    m = m[m > 10 ** ((-70 + 0.691) / 10)]                                 # puerta absoluta: -70 LUFS
    if not len(m):
        return None
    m = m[m > m.mean() * 10 ** (-10 / 10)]                                # puerta relativa: -10 dB
    if not len(m):
        return None
    return -0.691 + 10 * math.log10(m.mean()), pico


def medir_tema(ruta, duracion):
    """(lufs, pico) de un archivo, leyendo trozos repartidos (o todo si es corto). None si no se pudo medir.
    Pensado para correr en un hilo aparte."""
    F32 = miniaudio.SampleFormat.FLOAT32
    trozos = []
    try:
        if duracion <= 60:
            g = miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=FS, frames_to_read=4096)
            trozos.append(_leer(g, int(duracion * FS) + FS))
        else:
            for fr in (0.1, 0.3, 0.5, 0.7, 0.9):
                ini = max(0, int((duracion * fr - 2) * FS))
                g = miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=FS, frames_to_read=4096,
                                          seek_frame=ini)
                trozos.append(_leer(g, 4 * FS))
                time.sleep(0)       # deja respirar al hilo de audio
        return _sonoridad(trozos)
    except Exception as e:
        log("medir sonoridad falló:", ruta, e)
        return None


def ganancia_para(lufs, pico):
    """dB que hay que aplicar a un tema de esa sonoridad para llevarlo al objetivo, sin pasarse del pico."""
    g = OBJETIVO_LUFS - lufs
    if pico > 0:
        g = min(g, 20 * math.log10(1.25 / pico))       # el limitador absorbe hasta un pequeño exceso
    return max(GANANCIA_MIN_DB, min(GANANCIA_MAX_DB, g))


def leer_replaygain(ruta):
    """Ganancia de pista (dB) que traen las etiquetas del archivo (ReplayGain), llevada a nuestro objetivo; o None."""
    try:
        import mutagen
        t = mutagen.File(ruta)
        if t is None or not t.tags:
            return None
        for k, v in t.tags.items():
            if "replaygain_track_gain" in str(k).lower():
                texto = str(getattr(v, "text", [v])[0] if hasattr(v, "text") else (v[0] if isinstance(v, list) else v))
                m = re.search(r"[-+]?\d+(?:[.,]\d+)?", texto)
                if m:
                    return float(m.group().replace(",", ".")) + (OBJETIVO_LUFS + 18.0)   # ReplayGain apunta a -18 LUFS
    except Exception:
        pass
    return None


# --- perfiles de auriculares (AutoEq): la corrección de respuesta de frecuencia medida para cada modelo ---
# AutoEq (github.com/jaakkopasanen/AutoEq, licencia MIT) publica, para miles de auriculares, la curva que lleva su respuesta
# hacia una referencia pareja. Se baja solo el perfil que se elige y queda guardado: después anda sin internet.
AUTOEQ_RAIZ = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
COMPENSACION_MAX_DB = 4.0     # cuánto se sube el nivel general para igualar lo que el perfil baja (el limitador cuida los picos)
PUNTOS_PERFIL = np.geomspace(20, 20000, 127)


def leer_graphiceq(texto):
    """'GraphicEQ: 20 -1.6; 21 -1.7; ...' -> (frecuencias, ganancias en dB). Ya trae el preamp metido."""
    cuerpo = texto.split(":", 1)[1] if ":" in texto else texto
    pares = [(float(a), float(b)) for a, b in re.findall(r"([\d.]+)\s+(-?[\d.]+)", cuerpo)]
    if len(pares) < 2:
        raise ValueError("el perfil no tiene puntos")
    pares.sort()
    return [p[0] for p in pares], [p[1] for p in pares]


def _respuesta_biquad(tipo, fc, gan_db, q, freqs):
    """Respuesta en dB de un filtro paramétrico (receta de R. Bristow-Johnson) a las frecuencias `freqs`."""
    A = 10 ** (gan_db / 40)
    w0 = 2 * math.pi * fc / FS
    cs, alfa = math.cos(w0), math.sin(w0) / (2 * max(q, 0.05))
    if tipo == "PK":
        b = (1 + alfa * A, -2 * cs, 1 - alfa * A)
        a = (1 + alfa / A, -2 * cs, 1 - alfa / A)
    else:
        r = 2 * math.sqrt(A) * alfa
        if tipo == "LSC":
            b = (A * ((A + 1) - (A - 1) * cs + r), 2 * A * ((A - 1) - (A + 1) * cs), A * ((A + 1) - (A - 1) * cs - r))
            a = ((A + 1) + (A - 1) * cs + r, -2 * ((A - 1) + (A + 1) * cs), (A + 1) + (A - 1) * cs - r)
        else:   # HSC
            b = (A * ((A + 1) + (A - 1) * cs + r), -2 * A * ((A - 1) + (A + 1) * cs), A * ((A + 1) + (A - 1) * cs - r))
            a = ((A + 1) - (A - 1) * cs + r, 2 * ((A - 1) - (A + 1) * cs), (A + 1) - (A - 1) * cs - r)
    z = np.exp(-1j * 2 * math.pi * np.asarray(freqs) / FS)
    H = (b[0] + b[1] * z + b[2] * z ** 2) / (a[0] + a[1] * z + a[2] * z ** 2)
    return 20 * np.log10(np.abs(H) + 1e-12)


def leer_parametrico(texto):
    """El formato 'Preamp: -6.8 dB / Filter 1: ON PK Fc 1496 Hz Gain -2.9 dB Q 0.94 ...' -> la curva que resulta de sumar
    todos los filtros (y el preamp), a 127 frecuencias entre 20 Hz y 20 kHz."""
    texto = re.sub(r"(?<=\d),(?=\d)", ".", texto)       # Equalizer APO con la coma decimal del sistema: "Gain 2,2 dB"
    pre = re.search(r"Preamp:\s*(-?[\d.]+)\s*dB", texto, re.I)
    curva = np.full(len(PUNTOS_PERFIL), float(pre.group(1)) if pre else 0.0)
    n = 0
    for tipo, fc, gan, q in re.findall(r"Filter\s*\d+:\s*ON\s+(PK|PEQ|LSC|LS|HSC|HS)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+(-?[\d.]+)\s*dB"
                                       r"(?:\s+Q\s+([\d.]+))?", texto, re.I):
        tipo = {"PEQ": "PK", "LS": "LSC", "HS": "HSC"}.get(tipo.upper(), tipo.upper())
        curva += _respuesta_biquad(tipo, float(fc), float(gan), float(q) if q else 0.7, PUNTOS_PERFIL)
        n += 1
    if not n:
        raise ValueError("el perfil no tiene filtros")
    return list(PUNTOS_PERFIL), [float(x) for x in curva]


def leer_perfil(texto):
    """Lee un perfil de AutoEq en cualquiera de sus dos formatos (GraphicEQ o ParametricEQ)."""
    return leer_graphiceq(texto) if "GraphicEQ" in texto[:40] else leer_parametrico(texto)


def nivel_relativo_db(freqs, gan_db):
    """Cuánto cambia el volumen que se percibe con una curva, para música (la energía se reparte parejo por octavas):
    el promedio en energía de la curva a lo largo de las octavas. Un perfil que baja los medios 6 dB devuelve ~-6."""
    f = np.geomspace(31, 16000, 60)
    g = np.interp(np.log10(f), np.log10(freqs), gan_db)
    return float(10 * np.log10(np.mean(10 ** (g / 10))))


def indice_autoeq(texto):
    """[(nombre, fuente, ruta)] de las líneas del INDEX.md de AutoEq."""
    out = []
    for linea in texto.splitlines():
        m = re.match(r"^- \[(.+)\]\((\./.+?)\) by (.+)$", linea)
        if m:
            out.append((m.group(1), m.group(3), urllib.parse.unquote(m.group(2)[2:])))
    return out


def buscar_en_indice(entradas, consulta, limite=80):
    """Las entradas que contienen todas las palabras de la consulta (sin mayúsculas ni acentos); oratory1990 primero."""
    palabras = _norm(consulta).split()
    if not palabras:
        return []
    hallados = [e for e in entradas if all(p in _norm(e[0] + " " + e[1]) for p in palabras)]
    hallados.sort(key=lambda e: (0 if e[1].lower().startswith("oratory") else 1, e[0], e[1]))
    return hallados[:limite]


def url_perfil(ruta):
    """La dirección del archivo GraphicEQ de una entrada del índice (su ruta, sin el './')."""
    base = ruta.rstrip("/").rsplit("/", 1)[-1]
    return f"{AUTOEQ_RAIZ}/{urllib.parse.quote(ruta)}/{urllib.parse.quote(base + ' GraphicEQ.txt')}"


def slug_de(nombre):
    s = re.sub(r"[^a-z0-9]+", "-", _norm(nombre)).strip("-")
    return s[:60] or "perfil"


class Motor(QObject):
    """Motor de audio: un dispositivo siempre abierto y un callback que decide, bloque a bloque, qué suena.

    - Posición = frames entregados menos la latencia del dispositivo (se interpola entre callbacks).
    - Pausa, parar y cerrar: el volumen baja en 250 ms; reanudar sube en 150 ms. El dispositivo sigue andando (entrega silencio).
    - Saltar y cambiar de tema: fundido cruzado de 5 ms entre el audio viejo y el nuevo.
    - Fin de pista: la señal `fin_de_pista` se emite una sola vez (es segura entre hilos).
    - `muestras(n)`: las últimas n muestras (mono) que están sonando, para el espectro.
    """
    fin_de_pista = Signal()
    error_dispositivo = Signal(str)   # no se pudo abrir el audio (sin placa, ocupada por otro programa...)
    error_archivo = Signal(str, str)  # (ruta, motivo): el tema no se puede reproducir
    ANILLO = 32768

    def __init__(self, buffer_ms=120, latencia_ms=None, backend=None, parent=None, vigilancia_s=1.0, umbral_s=None, reintento_s=3.0,
                 fundido_salida_s=FUNDIDO_SALIDA_S, fundido_entrada_s=FUNDIDO_ENTRADA_S):
        super().__init__(parent)
        self.buffer_ms = buffer_ms
        self.f_sal = max(round(fundido_salida_s * FS), FADE)     # frames de la bajada (pausa, parar, cerrar)
        self.f_ent = max(round(fundido_entrada_s * FS), FADE)    # frames de la subida al reanudar
        self._fade_in = FADE          # largo de la subida en curso: corto al arrancar un tema, largo al reanudar
        self._gen = 0                 # cada orden nueva lo sube: cancela un parar() que estaba esperando su fundido
        # si el dispositivo deja de pedir audio durante tanto tiempo, se lo da por caído y se lo vuelve a abrir
        self.umbral = max(1.5, 8 * buffer_ms / 1000) if umbral_s is None else umbral_s
        self.reintento = reintento_s    # cada cuánto se reintenta abrir una placa que no estaba
        # cuánto tarda en oírse lo que se entrega (aproximado: sin medir con la placa real)
        self.lat = round((buffer_ms / 2 if latencia_ms is None else latencia_ms) * FS / 1000)
        self.backends = [backend] if backend is not None else _sistemas_de_sonido()
        self.espia = None             # para las pruebas: recibe cada bloque que se manda al dispositivo
        self._lock = threading.Lock()
        self._dev = None
        self._pend = None             # (fuente nueva o None, frame de inicio) a aplicar en el próximo callback
        self._fuente = None
        self._quiere = False          # True = sonando; False = en pausa
        self._gan = 0.0               # ganancia actual (rampa hacia 0 o 1)
        self.volumen = 1.0
        self.cadena = Cadena()        # normalización + ecualizador + limitador
        self._terminada = False
        self.duracion = 0.0
        self.ruta = None
        self._idx = None              # (ruta, offsets, muestras por frame, frecuencia, retardo, mmap)
        self._mm = None
        self._total = 0               # frames de audio entregados desde siempre (reloj del motor)
        self._tot0, self._pos0 = 0, 0  # a qué `total` corresponde la posición `_pos0` (frames de la pista)
        self._t_cb, self._tot_cb = None, 0
        self._anillo = np.zeros(self.ANILLO, np.float32)
        self._ent_fuente = 0          # frames que se leyeron de la fuente actual (0 al terminar = no tiene audio)
        self._t_abierto = self._t_intento = 0.0
        self._caido = False           # lo marca el aviso de miniaudio (que no siempre llega: por eso el vigilante)
        self._sin_aviso = True        # solo se avisa del primer fallo de una serie
        self._vigia = QTimer(self)
        self._vigia.timeout.connect(self._vigilar)
        if QCoreApplication.instance():   # sin aplicación (p. ej. en --diagnose) no hay bucle de eventos que lo mueva
            self._vigia.start(round(vigilancia_s * 1000))

    # --- estado ---
    @property
    def activo(self):
        # una orden pendiente de parar (fuente None) ya cuenta como inactivo, aunque el callback no la aplicó aún
        return self._fuente is not None or (self._pend is not None and self._pend[0] is not None)

    @property
    def reproduciendo(self):
        return self._quiere and self.activo and not self._terminada

    @property
    def terminada(self):
        """True si el tema abierto llegó a su fin (y nadie abrió otro ni saltó desde entonces)."""
        return self._terminada

    def posicion(self):
        """Segundos de la pista que están sonando ahora."""
        if self._pend is not None:
            return self._pend[1] / FS
        if self._fuente is None:
            return self.duracion if self._terminada else 0.0
        ph = self._total
        if self._quiere and self._t_cb is not None:
            ph = min(self._total, self._tot_cb + (time.perf_counter() - self._t_cb) * FS - self.lat)
        return min(max(self._pos0 + (ph - self._tot0), 0) / FS, self.duracion or 1e9)

    # --- control ---
    def cargar(self, ruta, inicio=0.0, reproducir=True):
        """Abre un tema (para sonar desde `inicio` segundos). Reemplaza al que suene con un fundido cruzado.

        Devuelve False (y emite `error_archivo`) si no se puede abrir: no existe, está roto o no es audio.
        """
        self._abrir_dispositivo()
        try:
            fuente = self._fuente_en(ruta, round(inicio * FS))
        except Exception as e:
            self._quiere, self.ruta, self._terminada = False, None, False
            self._soltar_indice()
            self._poner(None, 0)
            self.error_archivo.emit(ruta, str(e) or type(e).__name__)
            return False
        self._gen += 1
        self.ruta = ruta
        self._terminada = False
        self.duracion = self._duracion(ruta)
        self._soltar_indice()
        if ruta.lower().endswith(".mp3"):
            threading.Thread(target=self._indexar, args=(ruta,), daemon=True).start()
        self._quiere = reproducir
        self._poner(fuente, round(inicio * FS))
        return True

    def saltar(self, seg):
        """Salta a `seg` segundos del tema abierto. Devuelve False si no se pudo."""
        if not self.ruta:
            return False
        seg = min(max(seg, 0.0), max(self.duracion - 0.05, 0.0))
        try:
            fuente = self._fuente_en(self.ruta, round(seg * FS))
        except Exception as e:
            self.error_archivo.emit(self.ruta, str(e) or type(e).__name__)
            return False
        self._terminada = False
        self._poner(fuente, round(seg * FS))
        return True

    def pausar(self):
        self._quiere = False

    def reanudar(self):
        if self._dev is None:
            self._abrir_dispositivo()   # tal vez la placa volvió
        if self.activo and not self._terminada:
            self._gen += 1
            self._fade_in = self.f_ent
            self._quiere = True

    def parar(self):
        """Frena. Si está sonando, el volumen baja en `fundido_salida` y recién después se corta; cargar o reanudar
        en ese lapso lo cancela."""
        if self._dev is not None and self._quiere and self.activo and self._gan > 0.001 and QCoreApplication.instance():
            self._quiere = False
            self._gen += 1
            gen = self._gen
            QTimer.singleShot(round(self.f_sal / FS * 1000) + self.buffer_ms,
                              lambda: self._parar_ya() if gen == self._gen else None)
            return
        self._parar_ya()

    def _parar_ya(self):
        self._quiere = False
        self.ruta = None
        self._terminada = False
        self._soltar_indice()
        self._poner(None, 0)

    def cerrar(self, fundido=True):
        """Detiene el dispositivo y libera lo abierto (al cerrar la aplicación). Si suena, primero baja el volumen
        (unos 0,4 s) en vez de cortar de golpe."""
        if fundido and self._dev is not None and self.reproduciendo:
            self._quiere = False
            limite = time.perf_counter() + self.f_sal / FS + 0.3
            while self._gan > 0.001 and time.perf_counter() < limite:
                time.sleep(0.01)
            time.sleep(self.buffer_ms / 1000)       # lo que ya está en el búfer de la placa termina de salir
        self._vigia.stop()
        self._soltar_indice(ya=True)
        if self._dev is not None:
            dev, self._dev = self._dev, None
            try:
                dev.stop_callback = None
                dev.close()
            except Exception:
                pass

    def muestras(self, n):
        """Las últimas n muestras (mono, float32) que están sonando; ceros si todavía no hay tantas."""
        fin = int(self._total if not self._quiere or self._t_cb is None else
                  min(self._total, self._tot_cb + (time.perf_counter() - self._t_cb) * FS - self.lat))
        ini = fin - n
        if ini < 0 or fin > self._total or n > self.ANILLO or self._total - ini > self.ANILLO:
            return np.zeros(n, np.float32)
        i = ini % self.ANILLO
        if i + n <= self.ANILLO:
            return self._anillo[i:i + n].copy()
        return np.concatenate([self._anillo[i:], self._anillo[:i + n - self.ANILLO]])

    # --- por dentro ---
    def _abrir_dispositivo(self):
        if self._dev is not None:
            return
        self._t_intento = time.perf_counter()
        try:
            dev = miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.FLOAT32, nchannels=2, sample_rate=FS,
                buffersize_msec=self.buffer_ms, backends=self.backends, app_name="simpleplay")
            g = self._callback()
            next(g)
            dev.stop_callback = self._marcar_caido
            dev.start(g)
            self._dev = dev
            self._t_abierto = time.perf_counter()
            self._caido = False
            self._sin_aviso = True
        except Exception as e:  # sin placa de sonido, o la ocupa otro programa
            self._dev = None
            if self._sin_aviso:
                self._sin_aviso = False
                self.error_dispositivo.emit(str(e))

    def _marcar_caido(self):
        self._caido = True

    def _vigilar(self):
        """Cada segundo: si el dispositivo se cayó (parlante USB o Bluetooth desconectado, el equipo despertó de
        una suspensión...) se lo abre de nuevo y el tema sigue donde estaba, porque la fuente no se tocó."""
        ahora = time.perf_counter()
        if self._dev is None:
            if self.activo and ahora - self._t_intento > self.reintento:
                self._abrir_dispositivo()       # la placa no estaba: reintenta cada tanto
            return
        if self._caido or ahora - max(self._t_cb or 0.0, self._t_abierto) > self.umbral:
            log("audio: el dispositivo dejó de pedir datos, se vuelve a abrir")
            viejo, self._dev = self._dev, None
            try:
                viejo.stop_callback = None
                viejo.close()
            except Exception:
                pass
            self._abrir_dispositivo()

    def _soltar_indice(self, ya=False):
        """Suelta el índice del tema anterior y cierra su archivo mapeado (un segundo después: el audio puede estar
        terminando de leer la cola del tema viejo durante el fundido)."""
        viejo, self._idx = self._idx, None
        if viejo is None:
            return
        cerrar = lambda mm=viejo[5]: self._cerrar_mm(mm)
        cerrar() if ya else QTimer.singleShot(1000, cerrar)

    @staticmethod
    def _cerrar_mm(mm):
        try:
            mm.close()
        except Exception:
            pass

    @staticmethod
    def _duracion(ruta):
        try:
            return duracion_de(ruta) or float(miniaudio.get_file_info(ruta).duration)
        except Exception:
            return 0.0

    def _indexar(self, ruta):
        try:
            import mmap
            with open(ruta, "rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            offs, spf, fr, ret = indexar_mp3(mm)
            if self.ruta == ruta and offs:
                self._idx = (ruta, offs, spf, fr, ret, mm)
            else:
                mm.close()
        except Exception:
            pass

    def _fuente_en(self, ruta, frame):
        """Generador listo para send() que empieza en `frame` (a 44,1 kHz). Con el índice de frames el salto
        es instantáneo; sin él (otro formato, o el índice aún no está) se usa el salto lineal de miniaudio."""
        F32 = miniaudio.SampleFormat.FLOAT32
        idx = self._idx if self._idx and self._idx[0] == ruta else None
        if idx and frame > 0:
            try:
                g = self._fuente_indexada(idx, frame)
                if g is not None:
                    return g
            except Exception as e:
                log("salto por índice falló, se usa el lineal:", e)
        return abrir_fuente(ruta, frame)

    @staticmethod
    def _fuente_indexada(idx, frame):
        """El salto por índice (ver `_fuente_en`); None si no corresponde y hay que usar el salto lineal."""
        F32 = miniaudio.SampleFormat.FLOAT32
        _, offs, spf, fr, ret, mm = idx
        pos = frame * fr / FS                                  # posición en frames del archivo
        kf = min(int((pos + ret) // spf), len(offs) - 1)
        k0 = max(kf - PREVIOS, 0)                              # unos frames antes: llenan la reserva de bits
        if k0 == 0:
            return None                                        # principio del archivo: el decodificador normal
        # Al arrancar a mitad de archivo el decodificador no entrega los primeros frames (les falta la reserva de
        # bits de los anteriores): 0, 1 o 2 según el contenido. Se mide decodificando solo esos frames, y recién
        # ahí se sabe a qué punto de la pista corresponde su primera muestra.
        n = kf - k0
        corte = offs[kf] if kf < len(offs) else len(mm)
        sonda = miniaudio.stream_any(FuenteMp3(mm, offs[k0], corte), source_format=miniaudio.FileFormat.MP3,
                                     output_format=F32, nchannels=2, sample_rate=fr, frames_to_read=1024)
        perdidos = n - round(len(_leer(sonda, n * spf + spf)) / spf)
        ini = (k0 + max(perdidos, 0)) * spf - ret              # posición (frames del archivo) de su 1.ª muestra
        if ini > pos:
            return None
        g = miniaudio.stream_any(FuenteMp3(mm, offs[k0]), source_format=miniaudio.FileFormat.MP3,
                                 output_format=F32, nchannels=2, sample_rate=fr, frames_to_read=1024)
        if fr != FS:
            g = Remuestreador(g, fr)                           # el mismo remuestreo que el resto de los formatos
        _leer(g, round((pos - ini) * FS / fr))                 # descarta hasta el punto pedido
        return g

    def _poner(self, fuente, frame):
        with self._lock:
            self._pend = (fuente, frame)

    def _callback(self):
        req = yield b""
        while True:
            try:
                out = self._bloque(req)
            except Exception as e:  # un error acá cortaría el audio para siempre: se traga y se avisa
                out = np.zeros((req, 2), np.float32)
                log(f"motor: {e!r}")
            req = yield out

    def _rampa(self, n, objetivo, fade=FADE):
        """Ganancia de cada uno de n frames: de la actual al objetivo, a razón de 1/fade por frame (de 0 a 1 en `fade`
        frames). Lo que se oye sigue una curva de coseno: arranca y llega sin quiebres."""
        paso = np.arange(1, n + 1) / fade
        g = np.minimum(self._gan + paso, objetivo) if objetivo > self._gan else np.maximum(self._gan - paso, objetivo)
        self._gan = float(g[-1])
        return (0.5 - 0.5 * np.cos(np.pi * g)).astype(np.float32)

    def _bloque(self, req):
        """Arma los `req` frames que pide el dispositivo (corre en el hilo de audio)."""
        self._t_cb, self._tot_cb = time.perf_counter(), self._total
        out = np.zeros((req, 2), np.float32)
        with self._lock:
            pend, self._pend = self._pend, None
        hecho = 0
        if pend is not None:                       # cambio de tema o salto
            nueva, frame = pend
            cola = None
            if self._fuente is not None and self._gan >= 0.999 and self._quiere:
                cola = _leer(self._fuente, FADE)    # lo que quedaba del audio viejo: se funde hacia afuera
            self._fuente, self._pos0, self._tot0, self._ent_fuente = nueva, frame, self._total, 0
            if cola is not None:
                cabeza = _leer(nueva, FADE) if nueva is not None else np.zeros((0, 2), np.float32)
                self._ent_fuente = len(cabeza)
                r = np.arange(FADE, dtype=np.float32)[:, None] / FADE
                mezcla = np.zeros((FADE, 2), np.float32)
                mezcla[:len(cola)] += cola * (1 - r[:len(cola)])
                mezcla[:len(cabeza)] += cabeza * r[:len(cabeza)]
                hecho = max(len(cola), len(cabeza))
                out[:hecho] = mezcla[:hecho]
                if nueva is None:
                    self._gan = 0.0
                elif len(cabeza) < FADE:
                    self._fin_de_archivo()
            elif nueva is None:
                self._gan = 0.0
            else:                                   # arranque desde silencio (o salto en pausa): entra con fundido
                self._gan = 0.0
            if nueva is not None:
                self._fade_in = FADE                # un tema que empieza no se apaga: entra rápido, sin perder el ataque
        if self._fuente is not None and hecho < req:
            objetivo = 1.0 if self._quiere else 0.0
            fade = self._fade_in if self._quiere else self.f_sal
            quedan = req - hecho
            if objetivo == 0.0:                     # pausando: solo hace falta el fundido de salida
                quedan = min(quedan, int(round(self._gan * fade)))
            if quedan > 0:
                x = _leer(self._fuente, quedan)
                if len(x):
                    x = x * self._rampa(len(x), objetivo, fade)[:, None]
                    out[hecho:hecho + len(x)] = x
                    hecho += len(x)
                    self._ent_fuente += len(x)
                if len(x) < quedan:
                    self._fin_de_archivo()
        if self.cadena.activa:
            out = self.cadena.procesar(out)
        if hecho:
            self._escribir_anillo(out[:hecho])
            self._total += hecho
        if self.espia is not None:
            self.espia(out.copy())
        return out * self.volumen if self.volumen != 1.0 else out

    def _escribir_anillo(self, x):
        mono = x.mean(axis=1)
        if len(mono) > self.ANILLO:
            mono = mono[-self.ANILLO:]
            ini = self._total + (len(x) - self.ANILLO)
        else:
            ini = self._total
        i, n = ini % self.ANILLO, len(mono)
        if i + n <= self.ANILLO:
            self._anillo[i:i + n] = mono
        else:
            k = self.ANILLO - i
            self._anillo[i:] = mono[:k]
            self._anillo[:n - k] = mono[k:]

    def _fin_de_archivo(self):
        if self._terminada:
            return
        sin_audio = self._ent_fuente == 0
        self._fuente = None
        self._terminada = True
        self._quiere = False
        self._gan = 0.0
        if sin_audio:   # se abrió pero no entregó ni un frame: etiqueta sin audio, archivo roto
            self.error_archivo.emit(self.ruta or "", "el archivo no tiene audio")
        else:
            self.fin_de_pista.emit()


# ------------------------------------------------------------------------------------------------

class DialogoAuriculares(QDialog):
    """Busca un modelo de auriculares en la lista de AutoEq y baja su perfil. La lista de modelos (unos 800 KB) se baja una vez
    y queda guardada; sin conexión se sigue usando la guardada."""
    _indice_listo = Signal(str)
    _fallo = Signal(str)
    VIGENCIA_S = 30 * 24 * 3600     # la lista se vuelve a bajar pasado un mes

    def __init__(self, player, descargar=True):
        super().__init__(player)
        self.player = player
        self.entradas = []
        self.setWindowTitle(tr("Buscar auriculares (AutoEq)", "Find headphones (AutoEq)"))
        self.resize(480, 440)
        self.setStyleSheet(tinte("""QDialog { background: #1e1e22; } QLabel { color: #cfcfd4; }
            QLineEdit { background: rgba(255,255,255,26); color: white; border: none; border-radius: 10px; padding: 8px 12px; }
            QListWidget { background: rgba(0,0,0,70); color: white; border: none; border-radius: 10px; outline: 0; padding: 4px; }
            QListWidget::item { padding: 7px 8px; border-radius: 6px; } QListWidget::item:selected { background: #ff4e01; }
            QPushButton { background: rgba(255,255,255,40); color: white; border: none; border-radius: 10px; padding: 8px 18px; }
            QPushButton:hover { background: rgba(255,255,255,75); } QPushButton:disabled { color: rgba(255,255,255,90); }
            QPushButton#usar:enabled { background: #ff4e01; }"""))
        self.busca = QLineEdit()
        self.busca.setPlaceholderText(tr("Escribí el modelo, por ejemplo: ATH-M20x", "Type the model, e.g. ATH-M20x"))
        self.busca.setClearButtonEnabled(True)
        self.lista = QListWidget()
        self.estado = QLabel(tr("Bajando la lista de modelos…", "Downloading the list of models…"))
        self.estado.setWordWrap(True)
        self.usar = QPushButton(tr("Usar este perfil", "Use this profile"))
        self.usar.setObjectName("usar")
        self.usar.setEnabled(False)
        cancelar = QPushButton(tr("Cancelar", "Cancel"))
        abajo = QHBoxLayout()
        abajo.addWidget(self.estado, 1)
        abajo.addWidget(cancelar)
        abajo.addWidget(self.usar)
        lay = QVBoxLayout(self)
        lay.addWidget(self.busca)
        lay.addWidget(self.lista, 1)
        lay.addLayout(abajo)
        self.busca.textChanged.connect(self._filtrar)
        self.lista.itemSelectionChanged.connect(lambda: self.usar.setEnabled(self.lista.currentItem() is not None))
        self.lista.itemDoubleClicked.connect(lambda _: self._usar())
        self.usar.clicked.connect(self._usar)
        cancelar.clicked.connect(self.reject)
        self._indice_listo.connect(self._llenar)
        self._fallo.connect(self.estado.setText)
        if descargar:
            self._pedir_indice()

    def _cache(self):
        return ESTADO.parent / "autoeq-indice.md"

    def _pedir_indice(self):
        cache = self._cache()
        try:
            if time.time() - cache.stat().st_mtime < self.VIGENCIA_S:
                self._llenar(cache.read_text(encoding="utf-8"))
                return
        except OSError:
            pass

        def trabajo():
            try:
                texto = _http(AUTOEQ_RAIZ + "/INDEX.md", binario=True).decode("utf-8")
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(texto, encoding="utf-8")
                except OSError:
                    pass
                self._indice_listo.emit(texto)
            except Exception:
                try:                                    # sin conexión: la lista vieja sirve igual
                    self._indice_listo.emit(cache.read_text(encoding="utf-8"))
                except OSError:
                    self._fallo.emit(tr("No hay conexión: no se pudo bajar la lista de modelos.",
                                        "No connection: the list of models could not be downloaded."))
        threading.Thread(target=trabajo, daemon=True).start()

    def _llenar(self, texto):
        self.entradas = indice_autoeq(texto)
        self.estado.setText(tr(f"{len(self.entradas)} perfiles. Escribí el modelo para buscar.",
                               f"{len(self.entradas)} profiles. Type the model to search."))
        self._filtrar(self.busca.text())

    def _filtrar(self, texto):
        self.lista.clear()
        for nombre, fuente, ruta in buscar_en_indice(self.entradas, texto):
            it = QListWidgetItem(f"{nombre}   ·   {fuente}")
            it.setData(Qt.UserRole, (nombre, fuente, ruta))
            self.lista.addItem(it)
        self.usar.setEnabled(False)

    def _usar(self):
        it = self.lista.currentItem()
        if it is None:
            return
        nombre, fuente, ruta = it.data(Qt.UserRole)
        self.player.descargar_perfil(nombre, fuente, ruta)
        self.accept()

ESTILO_PANEL = """QDialog { background: transparent; } QLabel { color: #cfcfd4; background: transparent; }
    QFrame#cuerpo { background: rgba(22,22,24,235); border-radius: 18px; }
    QPushButton { background: rgba(255,255,255,40); color: white; border: none; border-radius: 12px; padding: 8px 16px; }
    QPushButton:hover { background: rgba(255,255,255,75); } QPushButton:disabled { color: rgba(255,255,255,90); }
    QPushButton#principal { background: #ff4e01; } QPushButton#principal:disabled { background: rgba(255,78,1,80); }
    QPushButton:checked { background: #ff4e01; }
    QComboBox { background: rgba(255,255,255,26); color: white; border: none; border-radius: 12px; padding: 6px 12px; }
    QComboBox QAbstractItemView { background: #1e1e22; color: white; selection-background-color: #ff4e01; outline: 0; }
    QSlider::groove:vertical { width: 3px; background: rgba(255,255,255,70); border-radius: 1px; }
    QSlider::sub-page:vertical { background: rgba(255,255,255,70); border-radius: 1px; }
    QSlider::add-page:vertical { background: #ff4e01; border-radius: 1px; }
    QSlider::handle:vertical { background: white; height: 11px; width: 11px; margin: 0 -4px; border-radius: 5px; }"""
HUECO_PANEL = 10          # separación entre la ventana y el panel pegado a su lado


def lado_para_panel(pantalla, vent, ancho):
    """Dónde poner un panel de `ancho` px pegado a una ventana: 'der' si entra a su derecha, si no 'izq', y si tampoco
    entra a la izquierda, el lado donde sobra más lugar (el panel se corre para no salirse de la pantalla).
    `pantalla` y `vent` son QRect: el área útil de la pantalla y la parte visible de la ventana."""
    libre_der = pantalla.right() + 1 - vent.right() - 1 - HUECO_PANEL
    libre_izq = vent.left() - HUECO_PANEL - pantalla.left()
    if libre_der >= ancho:
        return "der"
    if libre_izq >= ancho:
        return "izq"
    return "der" if libre_der >= libre_izq else "izq"


class PanelLateral(QDialog):
    """Base de los paneles del sonido: una ventana sin marco, con el mismo vidrio oscuro, esquinas y sombra que el
    reproductor. Se abre pegada al costado de la ventana (a la derecha si hay lugar, si no a la izquierda), la sigue
    cuando se mueve. Con una ventana de tipo Dialog también se puede arrastrar de cualquier zona vacía (se despega)."""
    RADIO = 18
    ESTILO_EXTRA = ""                       # reglas de estilo propias de cada panel, que se suman a ESTILO_PANEL
    # Tooltip (y no Dialog): en Wayland el sistema ignora la posición de una ventana común y la deja encima del
    # reproductor; una de este tipo se ubica respecto de su ventana madre. A cambio no recibe el teclado ni se arrastra.
    TIPO = Qt.ToolTip

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self._pegado = True
        self.setWindowFlags(self.TIPO | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(tinte(ESTILO_PANEL + self.ESTILO_EXTRA))
        self.cuerpo = QFrame()
        self.cuerpo.setObjectName("cuerpo")
        self.lay = QVBoxLayout(self.cuerpo)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(10)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(SOMBRA_MARGEN, SOMBRA_MARGEN, SOMBRA_MARGEN, SOMBRA_MARGEN)
        raiz.addWidget(self.cuerpo)
        self.ef = QGraphicsOpacityEffect(self.cuerpo)
        self.cuerpo.setGraphicsEffect(self.ef)
        raiz.setSizeConstraint(QLayout.SetFixedSize)
        player.installEventFilter(self)
        self._lado = "der"
        self._v = 0.0                          # cuánto está desplegado (0-1), como el panel de la lista de temas
        self._cerrando = self._sin_anim = False
        self._res = 0
        self.despliegue = QVariantAnimation(self)
        self.despliegue.setDuration(280)
        self.despliegue.setEasingCurve(QEasingCurve.OutCubic)
        self.despliegue.valueChanged.connect(self._desplegar)
        self.despliegue.finished.connect(self._fin_despliegue)

    def acoplar(self):
        """Lo pega al costado de la ventana del reproductor (alineado arriba) sin salirse de la pantalla."""
        if not self._pegado:
            return
        m = SOMBRA_MARGEN
        g = self.player.frameGeometry().adjusted(m, m, -m, -m)       # la parte visible: sin el aire de la sombra
        pant = (self.player.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = self.width() - 2 * m, self.height() - 2 * m
        self._lado = lado_para_panel(pant, g, w)
        if self._lado == "der":
            x = g.right() + 1 + HUECO_PANEL
        else:
            x = g.left() - HUECO_PANEL - w
        x = max(pant.left(), min(x, pant.right() + 1 - w))
        y = max(pant.top(), min(g.top(), pant.bottom() + 1 - h))
        self.move(x - m, y - m)

    def showEvent(self, e):
        super().showEvent(e)
        self.adjustSize()
        self.acoplar()
        QTimer.singleShot(0, self.acoplar)          # otra vez cuando el tamaño de ambas ventanas ya se asentó
        self._cerrando = False
        self._desplegar(0.0)
        self.despliegue.stop()
        self.despliegue.setStartValue(0.0)
        self.despliegue.setEndValue(1.0)
        self.despliegue.start()

    def _desplegar(self, v):
        """Sale desde detrás del reproductor: el cuerpo se va descubriendo desde el lado pegado a él, con un fundido.
        Se hace con el widget (máscara y efecto de opacidad) y no con la ventana: Wayland no permite ni opacidad ni
        máscara de ventana."""
        self._v = float(v)
        self.ef.setOpacity(self._v)
        self.ef.setEnabled(self._v < 1.0)           # abierto del todo se dibuja directo, sin pasar por una imagen
        c = self.cuerpo
        if self._v >= 1.0:
            c.clearMask()
        else:
            W, H = c.width(), c.height()
            w = max(1, round(W * self._v))
            c.setMask(QRegion(0, 0, w, H) if self._lado == "der" else QRegion(W - w, 0, w, H))
        self.update()

    def _fin_despliegue(self):
        if self._cerrando:
            self.player.removeEventFilter(self)
            super().done(self._res)
        else:
            self.clearMask()

    def eventFilter(self, obj, ev):
        if obj is self.player and ev.type() in (QEvent.Move, QEvent.Resize) and self.isVisible():
            self.acoplar()
        return super().eventFilter(obj, ev)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.cuerpo.geometry())
        if self._v < 1.0:                                   # la sombra acompaña a lo que ya se descubrió
            w = r.width() * self._v
            r = QRectF(r.x(), r.y(), w, r.height()) if self._lado == "der" else QRectF(r.right() - w, r.y(), w, r.height())
        if r.width() > 2 * self.RADIO:
            dibujar_sombra(p, r, self.RADIO, self._v)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.windowHandle() and self.TIPO != Qt.ToolTip:
            self._pegado = False
            self.windowHandle().startSystemMove()

    def done(self, r):
        """Se pliega de vuelta antes de cerrarse (salvo que haga falta cerrarlo ya, para abrir otro)."""
        if not self.isVisible() or self._sin_anim:
            self.despliegue.stop()
            self._cerrando = False
            self.player.removeEventFilter(self)
            super().done(r)
            return
        if self._cerrando:
            return
        self._cerrando, self._res = True, r
        self.despliegue.stop()
        self.despliegue.setStartValue(self._v)
        self.despliegue.setEndValue(0.0)
        self.despliegue.start()

    def cerrar_ya(self):
        self._sin_anim = True
        self.reject()


def titulo_panel(texto):
    t = QLabel(texto)
    t.setStyleSheet("color: white; font-size: 15px; font-weight: 700;")
    return t


def fmt_db(v):
    """+3,5 / -2 / 0 (con coma si el idioma es español)."""
    t = f"{v:+.1f}".rstrip("0").rstrip(".") if v else "0"
    return t.replace(".", ",") if tr("es", "en") == "es" else t


def curva_de_preset(nombre, personal=None, mios=None):
    """Las 10 ganancias (dB) de un preset, de 'personal' o de uno guardado por el usuario ('mio:nombre'); None si no es una curva de 10 bandas."""
    if nombre == "personal" and personal:
        return [float(x) for x in personal]
    if nombre.startswith("mio:") and mios and nombre[4:] in mios:
        return [float(x) for x in mios[nombre[4:]]]
    if nombre in PRESETS:
        return [float(x) for x in PRESETS[nombre]]
    return None


class DialogoEcualizador(PanelLateral):
    """Ecualizador gráfico de 10 bandas (31 Hz a 16 kHz, ±12 dB). Cada cambio suena enseguida y queda guardado como 'Mi sonido'."""
    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.setWindowTitle(tr("Ecualizador", "Equalizer"))
        curva = player.curva_actual()
        self.sliders, self.valores = [], []
        cols = QHBoxLayout()
        cols.setSpacing(6)
        for hz, g in zip(BANDAS_HZ, curva):
            col = QVBoxLayout()
            col.setSpacing(4)
            v = QLabel(fmt_db(g))
            v.setAlignment(Qt.AlignHCenter)
            v.setMinimumWidth(34)
            sl = QSlider(Qt.Vertical)
            sl.setRange(int(-LIM_BANDA_DB * 2), int(LIM_BANDA_DB * 2))       # pasos de 0,5 dB
            sl.setValue(round(g * 2))
            sl.setMinimumHeight(150)
            sl.setTickPosition(QSlider.NoTicks)
            f = QLabel(f"{hz // 1000}k" if hz >= 1000 else str(hz))
            f.setAlignment(Qt.AlignHCenter)
            col.addWidget(v)
            col.addWidget(sl, 1, Qt.AlignHCenter)
            col.addWidget(f)
            cols.addLayout(col)
            sl.valueChanged.connect(self._cambio)
            sl.sliderPressed.connect(self._asentar)
            self.sliders.append(sl)
            self.valores.append(v)
        self._destino = self._desde = [sl.value() for sl in self.sliders]
        self.anim_barras = QVariantAnimation(self)
        self.anim_barras.setDuration(420)
        self.anim_barras.setEasingCurve(QEasingCurve.OutCubic)
        self.anim_barras.valueChanged.connect(self._paso_barras)
        self.partir = QComboBox()
        self.partir.addItem(tr("Partir de…", "Start from…"), None)
        for clave, (es, en) in NOMBRES_PRESETS.items():
            self.partir.addItem(tr(es, en), clave)
        self.partir.activated.connect(self._partir)
        afinar = QPushButton(tr("Buscar mi sonido…", "Find my sound…"))
        afinar.clicked.connect(self._afinar)
        listo = QPushButton(tr("Listo", "Done"))
        listo.setObjectName("principal")
        listo.clicked.connect(self.accept)
        guardar = QPushButton(tr("Guardar preset…", "Save preset…"))
        guardar.setToolTip(tr("Guarda esta curva con un nombre, para volver a elegirla desde el menú Sonido.",
                              "Saves this curve under a name, so you can pick it again from the Sound menu."))
        guardar.clicked.connect(self._guardar_preset)
        abajo = QVBoxLayout()                       # en dos filas: con todo en una el panel se ensancha y no entra en pantallas chicas
        fila1, fila2 = QHBoxLayout(), QHBoxLayout()
        fila1.addWidget(self.partir)
        fila1.addWidget(afinar)
        fila1.addStretch(1)
        fila2.addStretch(1)
        fila2.addWidget(guardar)
        fila2.addWidget(listo)
        abajo.addLayout(fila1)
        abajo.addLayout(fila2)
        lay = self.lay
        lay.addWidget(titulo_panel(tr("Ecualizador", "Equalizer")))
        lay.addLayout(cols, 1)
        lay.addLayout(abajo)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)                       # varias barras seguidas = un solo cambio al motor
        self._timer.timeout.connect(self._aplicar)

    def curva(self):
        return [sl.value() / 2 for sl in self.sliders]

    def _cambio(self):
        for sl, v in zip(self.sliders, self.valores):
            v.setText(fmt_db(sl.value() / 2))
        self._timer.start()

    def _aplicar(self):
        self.player.poner_curva_personal(self.curva())

    def _guardar_preset(self):
        self._asentar()
        nombre = self.player.pedir_nombre_preset(tr("Mi preset", "My preset"))
        if nombre:
            self.player.guardar_mi_preset(nombre, self.curva())

    def poner_curva(self, curva, animar=False):
        """Lleva las barras a una curva y la aplica. Con `animar` el sonido cambia enseguida y las barras se deslizan
        hasta su lugar (subiendo o bajando según lo que haya que mover)."""
        self._asentar()
        destino = [round(max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(g))) * 2) for g in curva]
        self._destino = destino
        self._timer.stop()
        self.player.poner_curva_personal([d / 2 for d in destino])
        if not animar:
            self._mover_barras(destino)
            return
        self._desde = [sl.value() for sl in self.sliders]
        self.anim_barras.stop()
        self.anim_barras.setStartValue(0.0)
        self.anim_barras.setEndValue(1.0)
        self.anim_barras.start()

    def _mover_barras(self, valores):
        for sl, v in zip(self.sliders, valores):
            sl.blockSignals(True)
            sl.setValue(int(round(v)))
            sl.blockSignals(False)
        for sl, lbl in zip(self.sliders, self.valores):
            lbl.setText(fmt_db(sl.value() / 2))

    def _paso_barras(self, t):
        self._mover_barras([a + (b - a) * float(t) for a, b in zip(self._desde, self._destino)])

    def _asentar(self):
        """Si las barras estaban a medio camino, las deja en su destino (por ejemplo, al tocar una a mano)."""
        if self.anim_barras.state() == QVariantAnimation.Running:
            self.anim_barras.stop()
            self._mover_barras(self._destino)

    def _partir(self, i):
        clave = self.partir.itemData(i)
        if clave:
            self.poner_curva(curva_de_preset(clave), animar=True)
        self.partir.setCurrentIndex(0)

    def _afinar(self):
        self._timer.stop()
        self._aplicar()
        self.accept()
        self.player.afinar_al_oido()


# --- "Buscar mi sonido": se llega al sonido que a uno le gusta eligiendo entre versiones, de lo grande a lo fino ---
# Cada grupo empuja unos ejes (ver EJES_AFINADOR): graves = graves y cuerpo, voces = presencia, brillo = brillo y algo de presencia.
GRUPOS_BUSQUEDA = {"graves": ("graves", {"graves": 1.0, "cuerpo": 0.5}),
                   "voces": ("presencia", {"presencia": 1.0}),
                   "brillo": ("brillo", {"brillo": 1.0, "presencia": 0.3})}
RONDAS_DB = (6.0, 3.0, 1.5)      # cuánto se mueve cada versión en las tres rondas: primero se nota, después se afina
EJE_MAX_DB = 8.0                 # lo máximo que se puede empujar cada eje


class BuscadorSonido:
    """La lógica de la búsqueda, sin audio ni pantalla. En cada ronda hay cuatro versiones del sonido: la de ahora y una
    por grupo (graves, voces, brillo) movida `RONDAS_DB[ronda]` dB. En la primera todas empujan hacia arriba; después, un
    grupo que ya viene empujado 3 dB o más se prueba hacia abajo, así se encuentra el punto justo de los dos lados.
    Quien llama debe hacerlas sonar a igual volumen (`nivel_relativo_db`), si no lo más fuerte parecería lo mejor."""

    def __init__(self, inicial=None):
        self.base = [0.0] * len(BANDAS_HZ) if inicial is None else [float(x) for x in inicial]
        self.ejes = {k: 0.0 for k in EJES_AFINADOR}
        self.ronda = 0
        self._ops = self._armar()

    @property
    def terminado(self):
        return self.ronda >= len(RONDAS_DB)

    def curva(self, ejes=None):
        """Las 10 ganancias (dB) de la base más los ejes dados (por defecto los de ahora)."""
        c = np.array(self.base, dtype=float)
        for k, v in (self.ejes if ejes is None else ejes).items():
            c = c + v * np.array(EJES_AFINADOR[k])
        return [round(float(max(-LIM_BANDA_DB, min(LIM_BANDA_DB, x))), 2) for x in c]

    def _armar(self):
        if self.terminado:
            return []
        paso = RONDAS_DB[self.ronda]
        ops = [{"clave": "actual", "signo": 0, "ejes": dict(self.ejes)}]
        for grupo, (principal, pesos) in GRUPOS_BUSQUEDA.items():
            signo = -1 if self.ronda > 0 and self.ejes[principal] >= 3.0 else 1
            nuevo = dict(self.ejes)
            for k, w in pesos.items():
                nuevo[k] = max(-EJE_MAX_DB, min(EJE_MAX_DB, nuevo[k] + signo * paso * w))
            ops.append({"clave": grupo, "signo": signo, "ejes": nuevo})
        for o in ops:
            o["curva"] = self.curva(o["ejes"])
        return ops

    def opciones(self):
        """Las 4 versiones de esta ronda: la primera es la de ahora."""
        return self._ops

    def elegir(self, i):
        if self.terminado:
            return
        self.ejes = dict(self._ops[i]["ejes"])
        self.ronda += 1
        self._ops = self._armar()

    def poner_eje(self, eje, db):
        """El ajuste fino del final: mueve un eje a mano."""
        self.ejes[eje] = max(-EJE_MAX_DB, min(EJE_MAX_DB, round(float(db) * 2) / 2))


NOMBRES_RONDA1 = {"actual": ("Como está", "As it is"), "graves": ("Cálido", "Warm"),
                  "voces": ("Voces al frente", "Vocals forward"), "brillo": ("Brillante", "Bright")}
NOMBRES_AJUSTE = {"actual": ("Como ahora", "As it is now"),
                  ("graves", 1): ("Más graves", "More bass"), ("graves", -1): ("Menos graves", "Less bass"),
                  ("voces", 1): ("Más voces", "More vocals"), ("voces", -1): ("Menos voces", "Less vocals"),
                  ("brillo", 1): ("Más brillo", "More treble"), ("brillo", -1): ("Menos brillo", "Less treble")}


def nombre_opcion(op, ronda):
    """Cómo se llama una versión en pantalla: en la primera ronda dice cómo suena; en las siguientes, qué se cambió."""
    es_en = NOMBRES_RONDA1[op["clave"]] if ronda == 0 else NOMBRES_AJUSTE["actual" if op["clave"] == "actual" else (op["clave"], op["signo"])]
    return tr(*es_en)


def _curva_suave(rect, curva, rango_db):
    """Un camino que pasa por los 10 puntos de la curva, suave (Catmull-Rom llevado a Bézier), dentro de `rect`."""
    n = len(curva)
    pts = [QPointF(rect.left() + rect.width() * i / (n - 1),
                   rect.center().y() - max(-rango_db, min(rango_db, v)) / rango_db * rect.height() / 2) for i, v in enumerate(curva)]
    ruta = QPainterPath(pts[0])
    for i in range(n - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, n - 1)]
        ruta.cubicTo(p1 + (p2 - p0) / 6, p2 - (p3 - p1) / 6, p2)
    return ruta


class Ficha(QAbstractButton):
    """Una de las cuatro versiones: nombre, la forma de su curva y, si es la que suena, tres barritas que se mueven.
    Tocarla la hace sonar; elegirla es otro paso (el botón de abajo). Aparece con un leve deslizamiento escalonado."""
    ANCHO, ALTO = 176, 112

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.ANCHO, self.ALTO)
        self.nombre, self.curva = "", [0.0] * len(BANDAS_HZ)
        self._v = {"hover": 0.0, "sel": 0.0, "entrada": 1.0}
        self._anims = {}
        self._fase = 0.0
        self._reloj = QTimer(self)
        self._reloj.setInterval(60)
        self._reloj.timeout.connect(self._latido)
        self.toggled.connect(self._cambio_sel)

    def _ir(self, clave, destino, ms, curva=QEasingCurve.OutCubic, desde=None):
        a = self._anims.get(clave)
        if a is None:
            a = self._anims[clave] = QVariantAnimation(self)
            a.valueChanged.connect(lambda v, k=clave: (self._v.__setitem__(k, float(v)), self.update()))
        a.stop()
        a.setDuration(ms)
        a.setEasingCurve(curva)
        a.setStartValue(self._v[clave] if desde is None else desde)
        a.setEndValue(float(destino))
        a.start()

    def poner(self, nombre, curva, demora_ms=0):
        self.nombre, self.curva = nombre, list(curva)
        self._v["entrada"] = 0.0
        self.update()
        QTimer.singleShot(demora_ms, lambda: self._ir("entrada", 1.0, 320, desde=0.0))

    def _cambio_sel(self, si):
        self._ir("sel", 1.0 if si else 0.0, 180)
        if si:
            self._reloj.start()
        else:
            self._reloj.stop()
        self.update()

    def _latido(self):
        self._fase += 0.35
        self.update()

    def enterEvent(self, e):
        self._ir("hover", 1.0, 140)

    def leaveEvent(self, e):
        self._ir("hover", 0.0, 220)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t, sel, hov = self._v["entrada"], self._v["sel"], self._v["hover"]
        p.setOpacity(t)
        p.translate(0, (1 - t) * 8)
        ac = QColor(ACENTO)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(20 + 16 * hov)))
        p.drawRoundedRect(r, 14, 14)
        if sel > 0.01:
            p.setBrush(QColor(ac.red(), ac.green(), ac.blue(), int(42 * sel)))
            p.drawRoundedRect(r, 14, 14)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), int(255 * sel)), 1.5))
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 13, 13)
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QRectF(14, 11, r.width() - 52, 20), Qt.AlignLeft | Qt.AlignVCenter, self.nombre)
        # las tres barritas de "esta es la que suena"
        if sel > 0.01:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ac.red(), ac.green(), ac.blue(), int(255 * sel)))
            x0 = r.right() - 14 - 12
            for i in range(3):
                alto = 4 + 8 * (0.5 + 0.5 * math.sin(self._fase + i * 1.7))
                p.drawRoundedRect(QRectF(x0 + i * 5, r.top() + 21 - alto / 2, 3, alto), 1.5, 1.5)
        # la forma de la curva
        zona = QRectF(14, 44, r.width() - 26, r.height() - 44 - 14)
        ruta = _curva_suave(zona, self.curva, 7.5)
        base = zona.center().y()
        relleno = QPainterPath(ruta)
        relleno.lineTo(zona.right(), base)
        relleno.lineTo(zona.left(), base)
        relleno.closeSubpath()
        col = QColor(255, 255, 255, 150)
        col = QColor(int(col.red() + (ac.red() - col.red()) * sel), int(col.green() + (ac.green() - col.green()) * sel),
                     int(col.blue() + (ac.blue() - col.blue()) * sel), int(150 + 105 * sel))
        grad = QLinearGradient(0, zona.top(), 0, zona.bottom())
        c0 = QColor(col)
        c0.setAlpha(70)
        c1 = QColor(col)
        c1.setAlpha(0)
        grad.setColorAt(0, c0)
        grad.setColorAt(1, c1)
        p.setClipRect(zona.adjusted(-4, -6, 4, 6))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(relleno)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.DashLine))
        p.drawLine(QPointF(zona.left(), base), QPointF(zona.right(), base))
        p.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(ruta)


class Pasos(QWidget):
    """Tres segmentos finitos: cuántas rondas van. El actual se rellena de acento, los anteriores quedan llenos."""

    def __init__(self, total):
        super().__init__()
        self.total, self.actual = total, 0
        self._t = 1.0
        self.setFixedHeight(4)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(380)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(lambda v: (setattr(self, "_t", float(v)), self.update()))

    def poner(self, actual):
        self.actual = actual
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        ac = QColor(ACENTO)
        hueco = 6
        w = (self.width() - hueco * (self.total - 1)) / self.total
        for i in range(self.total):
            x = i * (w + hueco)
            p.setBrush(QColor(255, 255, 255, 36))
            p.drawRoundedRect(QRectF(x, 0, w, 4), 2, 2)
            lleno = 1.0 if i < self.actual else (self._t if i == self.actual else 0.0)
            if lleno > 0:
                p.setBrush(ac)
                p.drawRoundedRect(QRectF(x, 0, w * lleno, 4), 2, 2)


class CurvaSonido(QWidget):
    """La curva de "tu sonido" frente a la de antes, con el 0 dB y las frecuencias de referencia. Se redibuja al mover un control."""
    REF = ((31, "31"), (125, "125"), (500, "500"), (2000, "2k"), (8000, "8k"), (16000, "16k"))

    def __init__(self):
        super().__init__()
        self.setFixedHeight(118)
        self.nueva, self.vieja = [0.0] * len(BANDAS_HZ), None
        self.mostrar_vieja = True

    def poner(self, nueva, vieja=None):
        self.nueva, self.vieja = list(nueva), None if vieja is None else list(vieja)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ac = QColor(ACENTO)
        zona = QRectF(16, 8, self.width() - 32, self.height() - 8 - 20)
        base = zona.center().y()
        p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.DashLine))
        p.drawLine(QPointF(zona.left(), base), QPointF(zona.right(), base))
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 110))
        for hz, txt in self.REF:
            i = BANDAS_HZ.index(hz)
            x = zona.left() + zona.width() * i / (len(BANDAS_HZ) - 1)
            p.drawText(QRectF(x - 20, self.height() - 16, 40, 14), Qt.AlignCenter, txt)
        p.setBrush(Qt.NoBrush)
        if self.vieja is not None and self.mostrar_vieja:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1.5, Qt.DashLine))
            p.drawPath(_curva_suave(zona, self.vieja, 8.0))
        ruta = _curva_suave(zona, self.nueva, 8.0)
        relleno = QPainterPath(ruta)
        relleno.lineTo(zona.right(), base)
        relleno.lineTo(zona.left(), base)
        relleno.closeSubpath()
        grad = QLinearGradient(0, zona.top(), 0, zona.bottom())
        a0, a1 = QColor(ac), QColor(ac)
        a0.setAlpha(80)
        a1.setAlpha(0)
        grad.setColorAt(0, a0)
        grad.setColorAt(1, a1)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(relleno)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ac, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(ruta)


ESTILO_BUSCAR = """
    QPushButton#seg { background: rgba(255,255,255,22); padding: 6px 14px; border-radius: 11px; color: rgba(255,255,255,200); }
    QPushButton#seg:checked { background: rgba(255,255,255,60); color: white; }
    QPushButton#seg:hover { background: rgba(255,255,255,45); }
    QPushButton#texto { background: transparent; color: rgba(255,255,255,150); padding: 8px 6px; }
    QPushButton#texto:hover { color: white; }"""


class SliderCentrado(QSlider):
    """Un control horizontal con el cero en el medio: lo que se llena es el tramo entre el cero y la manija (hacia la izquierda si
    baja, hacia la derecha si sube). Doble clic lo devuelve a cero."""
    M = 8

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setCursor(Qt.PointingHandCursor)

    def _valor_en(self, x):
        f = (x - self.M) / max(1, self.width() - 2 * self.M)
        return int(round(self.minimum() + max(0.0, min(1.0, f)) * (self.maximum() - self.minimum())))

    def mousePressEvent(self, e):
        self.setSliderDown(True)
        self.setValue(self._valor_en(e.position().x()))

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self.setValue(self._valor_en(e.position().x()))

    def mouseReleaseEvent(self, e):
        self.setSliderDown(False)

    def mouseDoubleClickEvent(self, e):
        self.setValue(0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        x0, x1 = self.M, self.width() - self.M
        f = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        xh, xc = x0 + (x1 - x0) * f, (x0 + x1) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(x0, cy - 2, x1 - x0, 4), 2, 2)
        p.setBrush(QColor(ACENTO))
        p.drawRoundedRect(QRectF(min(xh, xc), cy - 2, abs(xh - xc), 4), 2, 2)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.drawLine(QPointF(xc, cy - 6), QPointF(xc, cy + 6))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(xh, cy + 1), 7.5, 7.5)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(xh, cy), 7, 7)


class DialogoBuscarSonido(PanelLateral):
    """'Buscar mi sonido': tres rondas de cuatro versiones (la de ahora y tres movidas ±6, ±3 y ±1,5 dB) que se escuchan a
    igual volumen sobre la música que suena; cada vez se elige la que gusta más. Al final, cuatro controles (graves, cuerpo,
    voces, brillo) para el ajuste fino, y se guarda con un nombre. Ver `BuscadorSonido`."""
    ESTILO_EXTRA = ESTILO_BUSCAR
    EJES_FINOS = (("graves", "Graves", "Bass"), ("cuerpo", "Cuerpo", "Body"), ("presencia", "Voces", "Vocals"), ("brillo", "Brillo", "Treble"))

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.inicial = player.curva_actual()
        self.buscador = BuscadorSonido(self.inicial)
        self.resultado = None
        self.guardado = False
        self.setWindowTitle(tr("Buscar mi sonido", "Find my sound"))
        self.cuerpo.setFixedWidth(Ficha.ANCHO * 2 + 10 + 36)
        lay = self.lay
        lay.setSpacing(0)
        lay.addWidget(titulo_panel(tr("Buscar mi sonido", "Find my sound")))
        self.sub = QLabel()
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet("color: rgba(255,255,255,150); font-size: 12px;")
        lay.addSpacing(3)
        lay.addWidget(self.sub)
        lay.addSpacing(14)
        self.paginas = QStackedWidget()
        lay.addWidget(self.paginas)
        lay.addSpacing(16)
        # ---- ronda ----
        pag = QWidget()
        v = QVBoxLayout(pag)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.pasos = Pasos(len(RONDAS_DB))
        v.addWidget(self.pasos)
        v.addSpacing(14)
        grilla = QGridLayout()
        grilla.setSpacing(10)
        self.fichas = [Ficha() for _ in range(4)]
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        for i, fch in enumerate(self.fichas):
            self.grupo.addButton(fch, i)
            grilla.addWidget(fch, i // 2, i % 2)
            fch.clicked.connect(lambda _=False, i=i: self._escuchar(i))
        v.addLayout(grilla)
        v.addSpacing(10)
        self.ayuda = QLabel(tr("Suenan igual de fuerte. Tocá cada una para escucharla.",
                               "They are all equally loud. Tap each one to hear it."))
        self.ayuda.setStyleSheet("color: rgba(255,255,255,110); font-size: 11px;")
        v.addWidget(self.ayuda)
        v.addStretch(1)
        self.paginas.addWidget(pag)
        # ---- ajuste fino ----
        fin = QWidget()
        w = QVBoxLayout(fin)
        w.setContentsMargins(0, 0, 0, 0)
        w.setSpacing(0)
        self.grafico = CurvaSonido()
        w.addWidget(self.grafico)
        w.addSpacing(10)
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self.b_antes = QPushButton(tr("Como estaba", "Before"))
        self.b_ahora = QPushButton(tr("Tu sonido", "Your sound"))
        self.cmp = QButtonGroup(self)
        for b in (self.b_antes, self.b_ahora):
            b.setObjectName("seg")
            b.setCheckable(True)
            self.cmp.addButton(b)
            seg.addWidget(b)
        self.b_ahora.setChecked(True)
        seg.addStretch(1)
        self.b_antes.clicked.connect(lambda: self._comparar(False))
        self.b_ahora.clicked.connect(lambda: self._comparar(True))
        w.addLayout(seg)
        w.addSpacing(14)
        self.sliders, self.valores = {}, {}
        for eje, es, en in self.EJES_FINOS:
            fila = QHBoxLayout()
            fila.setSpacing(10)
            nom = QLabel(tr(es, en))
            nom.setFixedWidth(58)
            nom.setStyleSheet("color: rgba(255,255,255,210); font-size: 13px;")
            sl = SliderCentrado()
            sl.setRange(int(-EJE_MAX_DB * 2), int(EJE_MAX_DB * 2))
            sl.setFixedHeight(24)
            val = QLabel("0")
            val.setFixedWidth(54)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setStyleSheet("color: rgba(255,255,255,150); font-size: 12px;")
            fila.addWidget(nom)
            fila.addWidget(sl, 1)
            fila.addWidget(val)
            w.addLayout(fila)
            sl.valueChanged.connect(lambda _=0, e=eje: self._ajuste(e))
            self.sliders[eje], self.valores[eje] = sl, val
        w.addStretch(1)
        self.paginas.addWidget(fin)
        # ---- sin música ----
        vacia = QLabel(tr("Agregá música primero: la búsqueda se hace escuchando un tema.",
                          "Add some music first: the search is done by listening to a track."))
        vacia.setWordWrap(True)
        vacia.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.paginas.addWidget(vacia)
        # ---- pie ----
        self.cancelar = QPushButton(tr("Cancelar", "Cancel"))
        self.cancelar.setObjectName("texto")
        self.cancelar.clicked.connect(self.reject)
        self.elegir = QPushButton(tr("Me quedo con esta", "I'll take this one"))
        self.elegir.setObjectName("principal")
        self.elegir.clicked.connect(self._elegir)
        pie = QHBoxLayout()
        pie.addWidget(self.cancelar)
        pie.addStretch(1)
        pie.addWidget(self.elegir)
        lay.addLayout(pie)
        self._temp = QTimer(self)
        self._temp.setSingleShot(True)
        self._temp.setInterval(90)
        self._temp.timeout.connect(self._sonar_fino)
        self._sel = 0
        if not player.pistas:
            self.sub.setText("")
            self.paginas.setCurrentIndex(2)
            self.paginas.setFixedHeight(48)
            self.elegir.setEnabled(False)
            return
        if player.actual < 0 or player.pausado:
            player.play_pausa()
        self.paginas.setFixedHeight(max(pag.sizeHint().height(), fin.sizeHint().height()))
        self._ronda()

    # --- rondas ---
    @property
    def curva_ronda(self):
        return self.buscador.opciones()[self._sel]["curva"]

    def _ronda(self):
        b = self.buscador
        self.paginas.setCurrentIndex(0)
        self.pasos.poner(b.ronda)
        self.sub.setText(tr(f"Ronda {b.ronda + 1} de {len(RONDAS_DB)}. Elegí la que más te gusta.",
                            f"Round {b.ronda + 1} of {len(RONDAS_DB)}. Pick the one you like most."))
        for i, (fch, op) in enumerate(zip(self.fichas, b.opciones())):
            fch.poner(nombre_opcion(op, b.ronda), op["curva"], demora_ms=60 * i)
        self._escuchar(0)

    def _escuchar(self, i):
        self._sel = i
        self.fichas[i].setChecked(True)
        self.player.escuchar_curva(self.curva_ronda)

    def _elegir(self):
        if self.paginas.currentIndex() == 1:
            self._guardar()
            return
        self.buscador.elegir(self._sel)
        if self.buscador.terminado:
            self._fino()
        else:
            self._ronda()

    # --- ajuste fino ---
    def _fino(self):
        self.paginas.setCurrentIndex(1)
        self.sub.setText(tr("Afinalo a tu gusto. Probá «Como estaba» para comparar.",
                            "Fine-tune it. Try “Before” to compare."))
        for eje, sl in self.sliders.items():
            sl.blockSignals(True)
            sl.setValue(int(round(self.buscador.ejes[eje] * 2)))
            sl.blockSignals(False)
            self.valores[eje].setText(self._fmt(self.buscador.ejes[eje]))
        self.b_ahora.setChecked(True)
        self.elegir.setText(tr("Guardar preset…", "Save preset…"))
        self._refrescar()

    @staticmethod
    def _fmt(db):
        return fmt_db(db) + " dB" if db else "0 dB"

    def _ajuste(self, eje):
        db = self.sliders[eje].value() / 2
        self.buscador.poner_eje(eje, db)
        self.valores[eje].setText(self._fmt(db))
        self.b_ahora.setChecked(True)
        self._refrescar()
        self._temp.start()

    def _refrescar(self):
        self.resultado = self.buscador.curva()
        self.grafico.poner(self.resultado, self.inicial)

    def _sonar_fino(self):
        self.player.escuchar_curva(self.resultado)

    def _comparar(self, nuevo):
        self.grafico.mostrar_vieja = True
        self.player.escuchar_curva(self.resultado if nuevo else self.inicial)

    def _guardar(self):
        nombre = self.player.pedir_nombre_preset(tr("Mi sonido", "My sound"))
        if not nombre:
            return                                             # canceló el nombre: sigue en el panel
        self.player.poner_curva_personal(self.resultado)       # 'Mi sonido' queda con esta curva y, además, el preset con nombre
        self.player.guardar_mi_preset(nombre, self.resultado)
        self.guardado = True
        self.accept()

    def done(self, r):
        self._temp.stop()
        if not self.guardado:
            self.player._aplicar_eq()                          # sin guardar: vuelve al sonido de antes
        super().done(r)


class CurvaParametrica(QWidget):
    """La respuesta del ecualizador paramétrico (20 Hz a 20 kHz, ±12 dB) con un punto por banda."""
    REF = (31, 125, 500, 2000, 8000)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(120)
        self.setMinimumWidth(320)
        self.bandas = [list(b) for b in PARAM_BANDAS_INICIAL]

    def poner(self, bandas):
        self.bandas = [list(b) for b in bandas]
        self.update()

    def _x(self, zona, hz):
        return zona.left() + zona.width() * (math.log10(hz) - math.log10(PARAM_HZ[0])) / (math.log10(PARAM_HZ[1]) - math.log10(PARAM_HZ[0]))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ac = QColor(ACENTO)
        zona = QRectF(14, 8, self.width() - 28, self.height() - 8 - 20)
        base = zona.center().y()
        p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.DashLine))
        p.drawLine(QPointF(zona.left(), base), QPointF(zona.right(), base))
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 110))
        for hz in self.REF:
            x = self._x(zona, hz)
            p.drawText(QRectF(x - 20, self.height() - 16, 40, 14), Qt.AlignCenter, f"{hz // 1000}k" if hz >= 1000 else str(hz))
        puntos = np.geomspace(PARAM_HZ[0], PARAM_HZ[1], 160)
        curva = curva_parametrica(self.bandas, puntos)
        ruta = QPainterPath()
        for i, (hz, g) in enumerate(zip(puntos, curva)):
            q = QPointF(self._x(zona, hz), base - max(-14.0, min(14.0, g)) / LIM_BANDA_DB * (zona.height() / 2) * 0.9)
            ruta.moveTo(q) if i == 0 else ruta.lineTo(q)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ac, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(ruta)
        p.setPen(Qt.NoPen)
        p.setBrush(ac)
        for fc, g, _ in self.bandas:
            p.drawEllipse(QPointF(self._x(zona, fc), base - g / LIM_BANDA_DB * (zona.height() / 2) * 0.9), 3.5, 3.5)


class DialogoParametrico(PanelLateral):
    """Ecualizador paramétrico: 5 bandas, cada una con su frecuencia, su ganancia (±12 dB) y su ancho Q. Suena enseguida y
    queda guardado."""
    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.setWindowTitle(tr("Ecualizador paramétrico", "Parametric equalizer"))
        self.filas = []
        self.curva = CurvaParametrica()
        lay = self.lay
        lay.addWidget(titulo_panel(tr("Ecualizador paramétrico", "Parametric equalizer")))
        lay.addWidget(self.curva)
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(8)
        grilla.setVerticalSpacing(6)
        for col, txt in enumerate((tr("Frecuencia", "Frequency"), tr("Ganancia", "Gain"), "Q")):
            t = QLabel(txt)
            t.setStyleSheet("color: rgba(255,255,255,120); font-size: 11px;")
            grilla.addWidget(t, 0, 1 + col * 3, 1, 2)
        for i, (fc, g, q) in enumerate(player.eq_param):
            n = QLabel(str(i + 1))
            n.setStyleSheet("color: rgba(255,255,255,140);")
            sf, sg, sq = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
            sf.setRange(0, 1000)
            sf.setValue(self._hz_a_pos(fc))
            sg.setRange(int(-LIM_BANDA_DB * 2), int(LIM_BANDA_DB * 2))
            sg.setValue(round(g * 2))
            sq.setRange(0, 1000)
            sq.setValue(self._q_a_pos(q))
            vf, vg, vq = QLabel(), QLabel(), QLabel()
            for v in (vf, vg, vq):
                v.setMinimumWidth(44)
                v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for sl in (sf, sg, sq):
                sl.setMinimumWidth(80)
                sl.valueChanged.connect(self._cambio)
            grilla.addWidget(n, i + 1, 0)
            for col, (sl, v) in enumerate(((sf, vf), (sg, vg), (sq, vq))):
                grilla.addWidget(sl, i + 1, 1 + col * 3)
                grilla.addWidget(v, i + 1, 2 + col * 3)
            self.filas.append((sf, sg, sq, vf, vg, vq))
        grilla.setColumnMinimumWidth(3, 18)
        grilla.setColumnMinimumWidth(6, 18)
        lay.addLayout(grilla)
        cero = QPushButton(tr("Dejar plano", "Reset"))
        cero.clicked.connect(self._cero)
        listo = QPushButton(tr("Listo", "Done"))
        listo.setObjectName("principal")
        listo.clicked.connect(self.accept)
        fila = QHBoxLayout()
        fila.addWidget(cero)
        fila.addStretch(1)
        fila.addWidget(listo)
        lay.addLayout(fila)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._aplicar)
        self._cambio(aplicar=False)

    @staticmethod
    def _hz_a_pos(hz):
        return round(1000 * (math.log10(hz) - math.log10(PARAM_HZ[0])) / (math.log10(PARAM_HZ[1]) - math.log10(PARAM_HZ[0])))

    @staticmethod
    def _pos_a_hz(pos):
        return 10 ** (math.log10(PARAM_HZ[0]) + pos / 1000 * (math.log10(PARAM_HZ[1]) - math.log10(PARAM_HZ[0])))

    @staticmethod
    def _q_a_pos(q):
        return round(1000 * (math.log10(q) - math.log10(PARAM_Q[0])) / (math.log10(PARAM_Q[1]) - math.log10(PARAM_Q[0])))

    @staticmethod
    def _pos_a_q(pos):
        return 10 ** (math.log10(PARAM_Q[0]) + pos / 1000 * (math.log10(PARAM_Q[1]) - math.log10(PARAM_Q[0])))

    def bandas(self):
        return [[self._pos_a_hz(sf.value()), sg.value() / 2, self._pos_a_q(sq.value())] for sf, sg, sq, *_ in self.filas]

    def _cambio(self, *_, aplicar=True):
        for (sf, sg, sq, vf, vg, vq), (fc, g, q) in zip(self.filas, self.bandas()):
            vf.setText(f"{fc / 1000:.1f}k".replace(".", ",") if fc >= 1000 else f"{fc:.0f}")
            vg.setText(fmt_db(g))
            vq.setText(f"{q:.1f}".replace(".", ","))
        self.curva.poner(self.bandas())
        if aplicar:
            self._timer.start()

    def _aplicar(self):
        self.player.poner_parametrico(self.bandas())

    def _cero(self):
        for sf, sg, sq, *_ in self.filas:
            sg.setValue(0)


class DialogoEspacial(PanelLateral):
    """Balance entre los dos lados y crossfeed (para auriculares)."""
    ESTILO_EXTRA = ESTILO_BUSCAR

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.setWindowTitle(tr("Balance y espacio", "Balance and space"))
        lay = self.lay
        lay.addWidget(titulo_panel(tr("Balance y espacio", "Balance and space")))
        lay.addWidget(QLabel(tr("Balance", "Balance")))
        fila = QHBoxLayout()
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(-100, 100)
        self.sl.setValue(player.balance)
        self.sl.setMinimumWidth(240)
        self.sl.setTickPosition(QSlider.NoTicks)
        self.val = QLabel()
        self.val.setMinimumWidth(62)
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fila.addWidget(QLabel("I" if tr("es", "en") == "es" else "L"))
        fila.addWidget(self.sl, 1)
        fila.addWidget(QLabel("D" if tr("es", "en") == "es" else "R"))
        fila.addWidget(self.val)
        lay.addLayout(fila)
        centrar = QPushButton(tr("Centrar", "Center"))
        centrar.clicked.connect(lambda: self.sl.setValue(0))
        lay.addWidget(centrar, 0, Qt.AlignLeft)
        sep = QLabel(tr("Crossfeed (auriculares)", "Crossfeed (headphones)"))
        sep.setStyleSheet("margin-top: 6px;")
        lay.addWidget(sep)
        nota = QLabel(tr("Cada oído oye un poco del otro lado, como con parlantes: el sonido deja de sentirse pegado a las orejas.",
                         "Each ear hears a little of the other side, as with speakers: the sound no longer feels stuck to your ears."))
        nota.setWordWrap(True)
        nota.setMaximumWidth(300)
        nota.setStyleSheet("color: rgba(255,255,255,120); font-size: 11px;")
        lay.addWidget(nota)
        seg = QHBoxLayout()
        self.botones = []
        for i, txt in enumerate((tr("Apagado", "Off"), tr("Suave", "Soft"), tr("Medio", "Medium"), tr("Fuerte", "Strong"))):
            b = QPushButton(txt)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == player.crossfeed)
            b.clicked.connect(lambda _=False, i=i: self._crossfeed(i))
            seg.addWidget(b)
            self.botones.append(b)
        lay.addLayout(seg)
        listo = QPushButton(tr("Listo", "Done"))
        listo.setObjectName("principal")
        listo.clicked.connect(self.accept)
        pie = QHBoxLayout()
        pie.addStretch(1)
        pie.addWidget(listo)
        lay.addLayout(pie)
        self.sl.valueChanged.connect(self._balance)
        self._texto()

    def _texto(self):
        v = self.sl.value()
        self.val.setText(tr("Centro", "Center") if v == 0 else (f"{tr('Izq.', 'Left')} {-v}" if v < 0 else f"{tr('Der.', 'Right')} {v}"))

    def _balance(self, v):
        self._texto()
        self.player.poner_balance(v)

    def _crossfeed(self, i):
        for k, b in enumerate(self.botones):
            b.setChecked(k == i)
        self.player.poner_crossfeed(i)


class FilaMusica(QFrame):
    """Una fila grande y tocable: un título, un detalle chico y, si corresponde, la marca de «es la que está abierta»."""
    clicked = Signal()

    def __init__(self, titulo, detalle="", marcada=False):
        super().__init__()
        self.setObjectName("fila")
        self.setCursor(Qt.PointingHandCursor)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(12, 8, 12, 8)
        fila.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel()
        t.setStyleSheet("color: white; font-size: 12px; font-weight: 600;")
        t.setText(QFontMetrics(t.font()).elidedText(titulo, Qt.ElideRight, 230))
        col.addWidget(t)
        if detalle:
            d = QLabel()
            d.setStyleSheet("color: rgba(255,255,255,110); font-size: 11px;")
            d.setText(QFontMetrics(d.font()).elidedText(detalle, Qt.ElideMiddle, 230))
            col.addWidget(d)
        fila.addLayout(col, 1)
        if marcada:
            m = QLabel("●")
            m.setStyleSheet(f"color: {ACENTO}; font-size: 12px;")
            fila.addWidget(m, 0, Qt.AlignVCenter)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class DialogoMusica(PanelLateral):
    """La música y las listas en un solo lugar: elegir una carpeta de la biblioteca o una lista guardada, reemplazando lo que
    hay o sumando, vaciar la lista y guardarla. Pensado para el dedo: filas grandes y todo a un toque."""
    ESTILO_EXTRA = ESTILO_BUSCAR + """
        QFrame#fila { background: rgba(255,255,255,16); border-radius: 12px; }
        QFrame#fila:hover { background: rgba(255,255,255,34); }
        QScrollArea { background: transparent; border: none; } QWidget#contenido { background: transparent; }
        QPushButton#texto_rojo { background: transparent; color: rgba(255,255,255,130); padding: 8px 6px; }
        QPushButton#texto_rojo:hover { color: #ff6b6b; }"""

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.sumar = False
        self._vaciar_pedido = False
        self.setWindowTitle(tr("Música y listas", "Music and playlists"))
        self.cuerpo.setMinimumWidth(320)
        lay = self.lay
        lay.setSpacing(10)
        cab = QHBoxLayout()
        cab.addWidget(titulo_panel(tr("Música y listas", "Music and playlists")))
        cab.addStretch(1)
        self.cuenta = QLabel()
        self.cuenta.setStyleSheet("color: rgba(255,255,255,150); font-size: 11px; font-weight: 600;")
        cab.addWidget(self.cuenta, 0, Qt.AlignVCenter)
        lay.addLayout(cab)

        modo = QHBoxLayout()
        modo.setSpacing(6)
        et = QLabel(tr("Al elegir:", "When I pick:"))
        et.setStyleSheet("color: rgba(255,255,255,150); font-size: 11px;")
        modo.addWidget(et)
        self.seg = []
        for i, txt in enumerate((tr("Reemplazar la lista", "Replace the list"), tr("Sumar a la lista", "Add to the list"))):
            b = QPushButton(txt)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _=False, i=i: self._modo(i))
            modo.addWidget(b)
            self.seg.append(b)
        modo.addStretch(1)
        lay.addLayout(modo)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(300)
        try:
            QScroller.grabGesture(self.scroll.viewport(), QScroller.LeftMouseButtonGesture)    # arrastrar con el dedo
        except NameError:
            pass
        lay.addWidget(self.scroll)

        pie = QHBoxLayout()
        pie.setSpacing(8)
        guardar = QPushButton(tr("Guardar lista", "Save list"))
        guardar.clicked.connect(self._guardar)
        self.vaciar = QPushButton(tr("Vaciar lista", "Empty list"))
        self.vaciar.clicked.connect(self._vaciar)
        listo = QPushButton(tr("Listo", "Done"))
        listo.setObjectName("principal")
        listo.clicked.connect(self.reject)
        pie.addWidget(guardar)
        pie.addWidget(self.vaciar)
        pie.addStretch(1)
        pie.addWidget(listo)
        lay.addLayout(pie)
        self._llenar()

    def _modo(self, i):
        self.sumar = bool(i)
        for k, b in enumerate(self.seg):
            b.setChecked(k == i)

    def _titulo_seccion(self, texto):
        t = QLabel(texto.upper())
        t.setStyleSheet("color: rgba(255,255,255,110); font-size: 10px; font-weight: 700; letter-spacing: 1px; margin-top: 4px;")
        return t

    def _llenar(self):
        p = self.player
        self.cuenta.setText(tr(f"{len(p.pistas)} temas en la lista", f"{len(p.pistas)} tracks in the list"))
        cont = QWidget()
        cont.setObjectName("contenido")
        v = QVBoxLayout(cont)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(6)

        v.addWidget(self._titulo_seccion(tr("Carpetas", "Folders")))
        carpetas = [c for c in p.carpetas_musica if Path(c).is_dir()]
        if p.carpeta_musica and Path(p.carpeta_musica).is_dir() and p.carpeta_musica not in carpetas:
            carpetas.append(p.carpeta_musica)
        for c in carpetas:
            f = FilaMusica(Path(c).name or c, c)
            f.clicked.connect(lambda c=c: self._carpeta(c))
            v.addWidget(f)
        nueva = QPushButton(tr("＋ Elegir otra carpeta…", "＋ Choose another folder…"))
        nueva.setObjectName("texto")
        nueva.clicked.connect(self._elegir_carpeta)
        v.addWidget(nueva, 0, Qt.AlignLeft)

        v.addWidget(self._titulo_seccion(tr("Listas guardadas", "Saved playlists")))
        carpeta_l = Path(p._carpeta_listas())
        listas = sorted((x for x in carpeta_l.iterdir() if x.suffix.lower() in LISTAS and x.is_file()),
                        key=lambda x: x.name.lower()) if carpeta_l.is_dir() else []
        for x in listas[:60]:
            try:
                n = sum(1 for l in x.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip() and not l.startswith("#"))
            except OSError:
                n = 0
            abierta = bool(p.lista_actual) and Path(p.lista_actual) == x.resolve()
            f = FilaMusica(x.stem, tr(f"{n} temas", f"{n} tracks"), abierta)
            f.clicked.connect(lambda x=x: self._lista(x))
            v.addWidget(f)
        if not listas:
            vacio = QLabel(tr(f"No hay listas en {carpeta_l}. Armá la lista y tocá «Guardar lista».",
                              f"No playlists in {carpeta_l}. Build one and tap “Save list”."))
            vacio.setWordWrap(True)
            vacio.setStyleSheet("color: rgba(255,255,255,110); font-size: 11px;")
            v.addWidget(vacio)
        v.addStretch(1)
        self.scroll.setWidget(cont)

    def _carpeta(self, ruta):
        p = self.player
        if not self.sumar:
            p.vaciar_lista()
        p.carpeta_musica = str(ruta)
        p.agregar([str(ruta)], avisar=True)
        p.recordar_carpeta(ruta)
        self.accept()

    def _elegir_carpeta(self):
        c = QFileDialog.getExistingDirectory(self, tr("Elegir carpeta", "Choose folder"), self.player._carpeta_inicial())
        if c:
            self._carpeta(c)

    def _lista(self, ruta):
        if self.sumar:
            try:
                temas, _ = leer_lista(str(ruta))
            except OSError:
                return
            self.player.agregar(temas, avisar=True)
        else:
            self.player.abrir_lista(str(ruta))
        self.accept()

    def _guardar(self):
        self.player._guardar_rapido()
        self._llenar()

    def _vaciar(self):
        """Dos toques: el primero pide confirmar, así un roce no borra la lista."""
        if not self.player.pistas:
            return
        if not self._vaciar_pedido:
            self._vaciar_pedido = True
            self.vaciar.setText(tr("¿Seguro? Tocá de nuevo", "Sure? Tap again"))
            QTimer.singleShot(3000, self._cancelar_vaciar)
            return
        self.player.vaciar_lista()
        self.accept()

    def _cancelar_vaciar(self):
        try:
            self._vaciar_pedido = False
            self.vaciar.setText(tr("Vaciar lista", "Empty list"))
        except RuntimeError:
            pass


class Interruptor(QAbstractButton):
    """Un interruptor de dos estados (pastilla con perilla), para las opciones de sí o no que van en una fila."""
    def __init__(self, marcado=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(marcado)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 24)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACENTO) if self.isChecked() else QColor(255, 255, 255, 50))
        p.drawRoundedRect(QRectF(0, 0, 40, 24), 12, 12)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(28 if self.isChecked() else 12, 12), 9, 9)


class PuntoEstado(QWidget):
    """El puntito del estado: gris si no hay nadie, con el acento y un halo si hay un celular conectado."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self.activo = False

    def poner(self, si):
        self.activo = si
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self.activo:
            halo = QColor(ACENTO)
            halo.setAlpha(60)
            p.setBrush(halo)
            p.drawEllipse(QPointF(7, 7), 7, 7)
            p.setBrush(QColor(ACENTO))
        else:
            p.setBrush(QColor(255, 255, 255, 90))
        p.drawEllipse(QPointF(7, 7), 4, 4)


class DialogoMosquito(PanelLateral):
    """El QR de Mosquito, en un panel al costado del reproductor (como los del sonido). Cerrarlo NO apaga el control
    remoto: sigue andando mientras el reproductor esté abierto; para cortarlo está «Apagar Mosquito»."""
    ESTILO_EXTRA = ESTILO_BUSCAR + """
        QFrame#paso { background: rgba(255,255,255,16); border-radius: 12px; }
        QFrame#enlace { background: rgba(255,255,255,14); border-radius: 12px; }
        QLabel#num { background: rgba(255,255,255,26); color: white; border-radius: 10px; font-size: 11px; font-weight: 700; }
        QPushButton#texto_rojo { background: transparent; color: rgba(255,255,255,130); padding: 8px 6px; }
        QPushButton#texto_rojo:hover { color: #ff6b6b; }"""

    def __init__(self, player, mosquito, pixmap_qr):
        super().__init__(player)
        self.mosquito = mosquito
        self.setWindowTitle("Mosquito")
        self.cuerpo.setMinimumWidth(300)
        lay = self.lay
        lay.setSpacing(12)

        cab = QHBoxLayout()
        cab.setSpacing(8)
        cab.addWidget(titulo_panel("Mosquito"))
        cab.addStretch(1)
        self.punto = PuntoEstado()
        self.estado = QLabel()
        self.estado.setStyleSheet("color: rgba(255,255,255,150); font-size: 11px; font-weight: 600;")
        cab.addWidget(self.punto, 0, Qt.AlignVCenter)
        cab.addWidget(self.estado, 0, Qt.AlignVCenter)
        lay.addLayout(cab)

        sub = QLabel(tr("Controlá la música desde el celular.", "Control the music from your phone."))
        sub.setStyleSheet("color: rgba(255,255,255,120); font-size: 11px;")
        lay.addWidget(sub)

        # el QR sobre una tarjeta blanca con aire alrededor: así el lector lo toma de lejos y no se pega al borde del panel
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjeta_qr")
        tarjeta.setStyleSheet("QFrame#tarjeta_qr { background: transparent; }")
        tl = QVBoxLayout(tarjeta)
        tl.setContentsMargins(0, 2, 0, 2)
        if pixmap_qr is not None:
            q = QLabel()
            q.setPixmap(pixmap_qr)
            q.setAlignment(Qt.AlignCenter)
            q.setStyleSheet("background: transparent;")
            tl.addWidget(q)
        else:
            f = QLabel(tr("Para ver el QR:\npip install qrcode", "To show the QR:\npip install qrcode"))
            f.setAlignment(Qt.AlignCenter)
            f.setStyleSheet("color: #333; background: transparent; padding: 40px;")
            tl.addWidget(f)
        lay.addWidget(tarjeta, 0, Qt.AlignHCenter)

        pasos = QFrame()
        pasos.setObjectName("paso")
        pl = QVBoxLayout(pasos)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(8)
        for n, txt in ((1, tr("Celular y PC en el mismo wifi", "Phone and PC on the same wifi")),
                       (2, tr("Abrí la cámara y escaneá el código", "Open the camera and scan the code"))):
            fila = QHBoxLayout()
            fila.setSpacing(10)
            num = QLabel(str(n))
            num.setObjectName("num")
            num.setFixedSize(20, 20)
            num.setAlignment(Qt.AlignCenter)
            t = QLabel(txt)
            t.setWordWrap(True)
            t.setStyleSheet("color: #e6e6ea; font-size: 12px;")
            fila.addWidget(num, 0, Qt.AlignTop)
            fila.addWidget(t, 1)
            pl.addLayout(fila)
        lay.addWidget(pasos)

        enlace = QFrame()
        enlace.setObjectName("enlace")
        el = QHBoxLayout(enlace)
        el.setContentsMargins(12, 4, 4, 4)
        el.setSpacing(6)
        url = QLabel()
        url.setStyleSheet("color: rgba(255,255,255,140); font-size: 11px;")
        url.setText(QFontMetrics(url.font()).elidedText(mosquito.url.replace("http://", ""), Qt.ElideRight, 190))
        url.setToolTip(mosquito.url)
        self.copiar = QPushButton(tr("Copiar", "Copy"))
        self.copiar.setObjectName("texto")
        self.copiar.setCursor(Qt.PointingHandCursor)
        self.copiar.clicked.connect(self._copiar)
        el.addWidget(url, 1)
        el.addWidget(self.copiar)
        lay.addWidget(enlace)

        rec = QHBoxLayout()
        rec.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(0)
        t1 = QLabel(tr("Recordar este celular", "Remember this phone"))
        t1.setStyleSheet("color: white; font-size: 12px; font-weight: 600;")
        t2 = QLabel(tr("No hay que escanear de nuevo", "No need to scan again"))
        t2.setStyleSheet("color: rgba(255,255,255,110); font-size: 11px;")
        col.addWidget(t1)
        col.addWidget(t2)
        self.recordar = Interruptor(mosquito.recordado)
        self.recordar.setToolTip(tr("La clave no cambia y Mosquito arranca solo con el reproductor.",
                                    "The key stays the same and Mosquito starts with the player."))
        self.recordar.toggled.connect(mosquito.recordar)
        rec.addLayout(col, 1)
        rec.addWidget(self.recordar, 0, Qt.AlignVCenter)
        lay.addLayout(rec)

        listo = QPushButton(tr("Listo", "Done"))
        listo.setObjectName("principal")
        listo.setToolTip(tr("Cierra el panel: Mosquito sigue activo", "Closes the panel: Mosquito stays on"))
        listo.clicked.connect(self.reject)
        apagar = QPushButton(tr("Apagar Mosquito", "Turn Mosquito off"))
        apagar.setObjectName("texto_rojo")
        apagar.setCursor(Qt.PointingHandCursor)
        apagar.clicked.connect(self._apagar)
        lay.addWidget(listo)
        lay.addWidget(apagar, 0, Qt.AlignHCenter)
        self.apagado = False

        self._vigia = QTimer(self)
        self._vigia.setInterval(1000)
        self._vigia.timeout.connect(self._estado)
        self._vigia.start()
        self._estado()

    def _estado(self):
        si = bool(self.mosquito.conectado)
        self.punto.poner(si)
        self.estado.setText(tr("Celular conectado", "Phone connected") if si else tr("Esperando el celular", "Waiting for a phone"))
        self.estado.setStyleSheet(f"color: {'white' if si else 'rgba(255,255,255,150)'}; font-size: 11px; font-weight: 600;")

    def _copiar(self):
        QApplication.clipboard().setText(self.mosquito.url)
        self.copiar.setText(tr("Copiado", "Copied"))
        QTimer.singleShot(1500, lambda: self.copiar.setText(tr("Copiar", "Copy")))

    def _apagar(self):
        self.apagado = True
        self.reject()


class Player(QWidget):
    perfil_listo = Signal(str, str)   # (perfil instalado, error): lo emite el hilo que baja un perfil

    def __init__(self):
        super().__init__()
        # SIMPLEPLAY_AUDIO=null: dispositivo de audio simulado (para las pruebas, sin placa de sonido)
        nulo = os.environ.get("SIMPLEPLAY_AUDIO") == "null"
        self.motor = Motor(backend=miniaudio.Backend.NULL if nulo else None, parent=self)
        self.motor.fin_de_pista.connect(self._motor_fin)
        self.motor.error_dispositivo.connect(self._motor_error)
        self.motor.error_archivo.connect(self._motor_error_archivo)
        self.perfil_listo.connect(self._perfil_listo)
        self._fallos = 0   # temas seguidos que no se pudieron reproducir (para no dar vueltas sin fin)
        self.normalizar = True
        self.preset = PRESET_INICIAL
        self._panel = None                 # el panel del sonido abierto (ecualizador o afinado)
        self.eq_personal = None            # 'Mi sonido': 10 ganancias en dB, del ecualizador gráfico o del afinado
        self.mis_presets = {}              # presets con nombre que guardó el usuario: {nombre: 10 ganancias en dB}
        self.eq_param = [list(b) for b in PARAM_BANDAS_INICIAL]   # ecualizador paramétrico: [frecuencia, ganancia dB, Q] por banda
        self.balance = 0                   # -100 (izquierda) a 100 (derecha)
        self.crossfeed = 0                 # índice en CROSSFEED_NIVELES
        self._midiendo = set()     # medidas de sonoridad en curso (clave de caché)
        self._sonoridades = None   # caché de sonoridad por archivo (se lee del disco la primera vez que se usa)
        self._aplicar_eq()
        self.setWindowTitle("simpleplay")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(tinte(ESTILO))

        self.pistas = []
        self.acento = "naranja"
        self.actual = -1
        self.pausado = False
        self.duracion = 0.0
        # espectro: lee del motor las muestras que están sonando; el nivel de referencia sale de los picos recientes
        self.picos = collections.deque(maxlen=HISTORIA)
        self._cuenta_ref = 0
        self.ref_suave = self._ref_p = None   # nivel de referencia que usan las barras, suavizado
        self.pendiente = None  # (índice, segundo) de la sesión restaurada, aún sin sonar
        self.vaciada = False   # el usuario quitó todos los temas (hay que guardar la lista vacía)
        self.meta = {"titulo": "", "artista": "", "arte": ""}
        self.mpris = None
        self.datos = {}              # ruta -> datos_lista(ruta): nombre, artista, título, álbum, pista
        self._ya_sonaron = set()     # shuffle: rutas que ya sonaron en la ronda actual
        self._sig_azar = None        # shuffle: (ruta, empieza_ronda_nueva) del tema que sigue, sorteado de antemano
        self.orden_original = []     # orden en que se agregaron (para volver con "Orden en que se agregaron")
        self.modo_orden = "original"
        self.repetir = "off"         # off | all | one
        self.carpeta_musica = ""     # última carpeta usada en los diálogos
        self.carpeta_listas = ""     # dónde se guardan las listas (la última usada)
        self.carpetas_musica = []    # la biblioteca: las carpetas de música usadas, la última primero
        self.lista_actual = ""       # archivo de la lista abierta o guardada: "Guardar lista" la reescribe
        self.etiquetando = False  # la escoba está trabajando
        self.etiquetador = None
        self.lote_undo = None

        # --- tarjeta ---
        self.card = Card()
        self.thumb = Miniatura(28)
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
        pill = self.pill = ClickFrame()
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
        self.ef_texto.setEnabled(False)         # los efectos de opacidad hacen que Qt pinte cada widget aparte y lo mezcle:
        self.ef_barras.setEnabled(False)        # solo se encienden mientras dura la transición
        self.barras.hide()
        self.modo_barras = False
        self.mezcla = 0.0
        self.fundido = QVariantAnimation(self)
        self.fundido.setDuration(380)
        self.fundido.setEasingCurve(QEasingCurve.InOutCubic)
        self.fundido.valueChanged.connect(self._fundir)
        self.fundido.finished.connect(self._fin_fundido)
        pill.clicked.connect(self.alternar_barras)

        self.btn_shuffle = IconButton("shuffle", 30)
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.toggled.connect(self._reiniciar_ronda)
        self.btn_lista = IconButton("list", 36)
        self.btn_lista.setCheckable(True)
        self.btn_escoba = IconButton("broom", 30)
        self.btn_escoba.setToolTip(tr("Buscar y completar los datos del tema (de los seleccionados)",
                                      "Look up and fill in the track info (for the selected tracks)"))
        self.btn_escoba.clicked.connect(self.limpiar_etiquetas)

        self.btn_compacto = IconButton("compact", 28)
        self.btn_compacto.setToolTip(tr("Modo compacto (M)", "Compact mode (M)"))
        top = self.top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(pill, 1)
        top.addWidget(self.btn_compacto, 0, Qt.AlignVCenter)
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
        self.btn_repetir = IconButton("repeat", 30)
        self.btn_repetir.clicked.connect(self.alternar_repetir)
        botones = QHBoxLayout()
        botones.setSpacing(14)
        # repetir a la izquierda y shuffle a la derecha: fila simétrica, el play queda en el centro justo
        botones.addWidget(self.btn_repetir)
        self.btn_escoba.setParent(self)  # la escoba (solo con SIMPLEPLAY_ESCOBA=1) va en la fila de la lista
        self.btn_escoba.hide()
        botones.addStretch()
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            botones.addWidget(b)
        botones.addStretch()
        botones.addWidget(self.btn_shuffle)

        # tiempos, barra y botones viven en un contenedor transparente: se funden juntos y la portada queda limpia
        self.controles = QWidget(self.card)
        cl = QVBoxLayout(self.controles)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        cl.addLayout(tiempos)
        cl.addWidget(self.linea)
        cl.addSpacing(6)
        cl.addLayout(botones)
        cc = QVBoxLayout(self.card)   # la píldora de arriba y sus dos iconos quedan siempre a la vista
        cc.setContentsMargins(14, 14, 14, 16)
        cc.setSpacing(4)
        cc.addLayout(top)
        cc.addStretch()
        cc.addWidget(self.controles)
        self.ef_controles = QGraphicsOpacityEffect(self.controles)
        self.controles.setGraphicsEffect(self.ef_controles)
        self.ef_controles.setEnabled(False)   # solo mientras dura el fundido (ver ef_texto)
        self.ocultar_controles = True         # se esconden solos si no pasa nada (menú: Ocultar controles solos)
        self._quietud = 0                     # ticks de 200 ms sin actividad
        self._ult_cursor = None
        self.vis_controles = 1.0
        self.fundido_ctrl = QVariantAnimation(self)
        self.fundido_ctrl.setDuration(350)
        self.fundido_ctrl.setEasingCurve(QEasingCurve.InOutCubic)
        self.fundido_ctrl.valueChanged.connect(self._fundir_controles)
        self.fundido_ctrl.finished.connect(self._fin_fundido_controles)

        self.lista = QListWidget()
        self.lista.setFixedHeight(168)  # unas 5 filas
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lista.setTextElideMode(Qt.ElideRight)
        self.lista.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Ctrl/Shift para varios
        self.lista.setDragDropMode(QAbstractItemView.InternalMove)        # arrastrar para reordenar
        self.lista.setDefaultDropAction(Qt.MoveAction)
        self.lista.model().rowsMoved.connect(self._reordenado)
        self.lista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista.customContextMenuRequested.connect(self._menu_tema)
        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText(tr("Buscar en la lista…", "Search the list…"))
        self.buscador.setClearButtonEnabled(True)
        pal = self.buscador.palette()
        pal.setColor(QPalette.PlaceholderText, QColor(255, 255, 255, 120))
        self.buscador.setPalette(pal)
        self.buscador.textChanged.connect(self._filtrar)
        self.buscador.returnPressed.connect(self._reproducir_primero)
        self.btn_orden = IconButton("sort", 28)
        self.btn_orden.setToolTip(tr("Ordenar la lista", "Sort the list"))
        self.btn_orden.clicked.connect(self._menu_orden)
        self.btn_quitar = IconButton("minus", 28)
        self.btn_quitar.setToolTip(tr("Quitar el tema seleccionado", "Remove the selected track"))
        self.btn_quitar.clicked.connect(self.quitar)
        self.btn_guardar = IconButton("save", 28)
        self.btn_guardar.setToolTip(tr("Guardar la lista (en la lista abierta, o como una nueva)",
                                       "Save the playlist (over the open one, or as a new one)"))
        self.btn_guardar.clicked.connect(self._guardar_rapido)
        self.btn_abrir = IconButton("plus", 32)
        self.btn_abrir.setToolTip(tr("Agregar archivos o una carpeta", "Add files or a folder"))
        self.btn_abrir.clicked.connect(self._menu_agregar)
        self.cuenta = QLabel()
        self.cuenta.setStyleSheet("font-size: 11px; font-weight: 500; color: rgba(255,255,255,150);")
        self._t_cuenta = QTimer(self)          # junta los cambios (agregar 5000 temas no recuenta 5000 veces)
        self._t_cuenta.setSingleShot(True)
        self._t_cuenta.setInterval(0)
        self._t_cuenta.timeout.connect(self._actualizar_cuenta)
        for senal in (self.lista.model().rowsInserted, self.lista.model().rowsRemoved, self.lista.model().modelReset):
            senal.connect(self._pedir_cuenta)
        self._actualizar_cuenta()
        abajo = QHBoxLayout()
        abajo.setSpacing(8)
        abajo.addWidget(self.btn_orden, 0, Qt.AlignVCenter)
        if ESCOBA:
            self.btn_escoba.setFixedSize(28, 28)
            abajo.addWidget(self.btn_escoba, 0, Qt.AlignVCenter)
        abajo.addWidget(self.cuenta, 0, Qt.AlignVCenter)
        abajo.addStretch()
        abajo.addWidget(self.btn_guardar, 0, Qt.AlignVCenter)
        abajo.addWidget(self.btn_quitar, 0, Qt.AlignVCenter)
        abajo.addWidget(self.btn_abrir, 0, Qt.AlignVCenter)
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(10, 10, 10, 10)
        pv.setSpacing(8)
        pv.addWidget(self.buscador)
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

        # modo compacto: la misma píldora de arriba pasa a esta barra, con los controles al lado
        self.mini = QFrame()
        self.mini.setObjectName("mini")
        self.mini.setFixedSize(380, 56)
        self.mini_prev = IconButton("prev", 30)
        self.mini_play = IconButton("play", 36)
        self.mini_next = IconButton("next", 30)
        self.mini_volver = IconButton("expand", 28)
        self.mini_volver.setToolTip(tr("Volver a la tarjeta (M)", "Back to the card (M)"))
        ml = self.mini_lay = QHBoxLayout(self.mini)
        ml.setContentsMargins(10, 10, 10, 10)
        ml.setSpacing(6)
        for b in (self.mini_prev, self.mini_play, self.mini_next, self.mini_volver):
            ml.addWidget(b, 0, Qt.AlignVCenter)
        self.mini.hide()
        self.compacto = False
        self._fade = None
        self._trans = None   # la transición en curso entre la tarjeta y la barra compacta

        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetFixedSize)  # la ventana crece al mostrar la lista
        root.setContentsMargins(SOMBRA_MARGEN, SOMBRA_MARGEN, SOMBRA_MARGEN, SOMBRA_MARGEN)  # lugar para la sombra
        root.setSpacing(0)
        root.addWidget(self.card, 0, Qt.AlignHCenter)
        root.addWidget(self.mini, 0, Qt.AlignHCenter)
        root.addWidget(self.caja)

        self.btn_play.clicked.connect(self.play_pausa)
        self.btn_prev.clicked.connect(self.anterior)
        self.btn_next.clicked.connect(self.siguiente)
        self.mini_play.clicked.connect(self.play_pausa)
        self.mini_prev.clicked.connect(self.anterior)
        self.mini_next.clicked.connect(self.siguiente)
        self.btn_compacto.clicked.connect(lambda: self.poner_compacto(True))
        self.mini_volver.clicked.connect(lambda: self.poner_compacto(False))
        self.btn_lista.toggled.connect(self.alternar_lista)
        self.lista.itemDoubleClicked.connect(lambda it: self.reproducir(self.lista.row(it)))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self.autoguardado = QTimer(self)
        self.autoguardado.timeout.connect(self.guardar_estado)
        self.autoguardado.start(15000)

        # atajos de teclado (con QShortcut mandan sobre el widget que tenga el foco)
        for tecla, accion in ((QKeySequence(Qt.Key_Space), self.play_pausa),
                              (QKeySequence(Qt.Key_Escape), self._esc),
                              (QKeySequence(Qt.Key_Left), lambda: self.saltar_rel(-5)),
                              (QKeySequence(Qt.Key_Right), lambda: self.saltar_rel(5)),
                              (QKeySequence(Qt.Key_N), self.siguiente),
                              (QKeySequence(Qt.Key_P), self.anterior),
                              (QKeySequence(Qt.Key_Delete), self.quitar),
                              (QKeySequence(QKeySequence.Open), self.abrir),
                              (QKeySequence("Ctrl+Shift+O"), self.abrir_carpeta),
                              (QKeySequence(QKeySequence.Find), self.enfocar_buscador),
                              (QKeySequence(Qt.Key_R), self.alternar_repetir),
                              (QKeySequence(Qt.Key_M), lambda: self.poner_compacto(not self.compacto))):
            QShortcut(tecla, self).activated.connect(accion)

        if HAY_DBUS and not os.environ.get("SIMPLEPLAY_NO_MPRIS"):
            self.mpris = Mpris(self)
        if MOSQUITO:
            QTimer.singleShot(0, self._mosquito_auto)
            QShortcut(QKeySequence("Ctrl+Shift+M"), self).activated.connect(self.abrir_mosquito)

    # --- teclas multimedia (MPRIS) ---
    def mpris_cambio(self, *claves):
        if self.mpris:
            self.mpris.actualizar(*claves)

    def mpris_seeked(self):
        if self.mpris:
            self.mpris.seeked(self.mpris_posicion())

    def mpris_estado(self):
        if self.actual >= 0:
            return "Paused" if self.pausado else "Playing"
        return "Paused" if self.pendiente else "Stopped"

    def mpris_posicion(self):
        pos = self.posicion() if self.actual >= 0 else (self.pendiente[1] if self.pendiente else 0.0)
        return int(pos * 1_000_000)

    def mpris_metadata(self):
        i = self.actual if self.actual >= 0 else (self.pendiente[0] if self.pendiente else -1)
        if not 0 <= i < len(self.pistas):
            return {"mpris:trackid": QDBusObjectPath("/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        d = {"mpris:trackid": QDBusObjectPath(f"/org/simpleplay/track/{i + 1}"),
             "mpris:length": int(self.duracion * 1_000_000),
             "xesam:title": self.meta["titulo"],
             "xesam:url": Path(self.pistas[i]).as_uri()}
        if self.meta["artista"]:
            d["xesam:artist"] = [self.meta["artista"]]
        if self.meta["arte"]:
            d["mpris:artUrl"] = self.meta["arte"]
        return d

    def _guardar_portada(self, datos):
        """Guarda la portada en la caché para ofrecérsela al escritorio (mpris:artUrl)."""
        if not datos:
            return ""
        try:
            ext = "png" if datos[:4] == b"\x89PNG" else "jpg"
            carpeta = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "covers"
            carpeta.mkdir(parents=True, exist_ok=True)
            f = carpeta / f"{hashlib.sha1(datos).hexdigest()[:16]}.{ext}"
            if not f.exists():
                f.write_bytes(datos)
            for viejo in sorted(carpeta.iterdir(), key=lambda x: x.stat().st_mtime)[:-50]:
                viejo.unlink()  # se conservan las últimas 50
            return f.as_uri()
        except OSError:
            return ""

    # --- archivos ---
    def _carpeta_inicial(self):
        if self.carpeta_musica and Path(self.carpeta_musica).is_dir():
            return self.carpeta_musica
        return QStandardPaths.writableLocation(QStandardPaths.MusicLocation)

    def abrir(self):
        archivos, _ = QFileDialog.getOpenFileNames(
            self, tr("Abrir", "Open"), self._carpeta_inicial(), tr("Audio (*.mp3 *.flac)", "Audio (*.mp3 *.flac)"))
        if archivos:
            self.carpeta_musica = str(Path(archivos[0]).parent)
            self.agregar(archivos, avisar=True)
            self.guardar_estado()

    def abrir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, tr("Abrir carpeta", "Open folder"), self._carpeta_inicial())
        if carpeta:
            self.carpeta_musica = carpeta
            self.agregar([carpeta], avisar=True)
            self.recordar_carpeta(carpeta)

    def _menu_agregar(self):
        menu = Menu(self)
        menu.addAction(tr("Música y listas…", "Music and playlists…"), self.abrir_musica)
        menu.addSeparator()
        menu.addAction(tr("Agregar archivos…", "Add files…"), self.abrir)
        menu.addAction(tr("Agregar una carpeta…", "Add a folder…"), self.abrir_carpeta)
        menu.addSeparator()
        menu.addAction(tr("Abrir lista…", "Open playlist…"), self.abrir_lista)
        if YOUTUBE:
            menu.addSeparator()
            menu.addAction("YouTube Music…", self.abrir_youtube)
            menu.addSeparator()
        if self.lista_actual:
            menu.addAction(tr(f"Guardar «{Path(self.lista_actual).stem}»", f"Save “{Path(self.lista_actual).stem}”"),
                           lambda: self.guardar_lista(self.lista_actual)).setEnabled(bool(self.pistas))
        menu.addAction(tr("Guardar lista como…", "Save playlist as…"),
                       lambda: self.guardar_lista()).setEnabled(bool(self.pistas))
        menu.exec(self.btn_abrir.mapToGlobal(QPoint(0, self.btn_abrir.height())))

    def _servidor_mosquito(self):
        """El servidor de Mosquito (lo crea y lo arranca si no está). None si no se pudo cargar."""
        if getattr(self, "_mosquito", None) is None:
            try:
                import simpleplay_mosquito
            except ImportError as e:
                self._aviso(tr("No se pudo cargar Mosquito", "Could not load Mosquito"), 5000)
                log("mosquito:", e)
                return None
            self._mosquito = simpleplay_mosquito.Mosquito(self, leer_meta, ESTADO.parent)
            self._mosquito.iniciar()
        return self._mosquito

    def _mosquito_auto(self):
        """Con «Recordar este celular» activado, Mosquito arranca solo con el reproductor."""
        if (ESTADO.parent / "mosquito.json").exists():
            self._servidor_mosquito()

    def abrir_mosquito(self):
        """Control remoto desde el navegador del celular. El servidor vive con el reproductor: cerrar el panel del QR no
        lo apaga (se apaga con su botón o al cerrar el reproductor)."""
        mosquito = self._servidor_mosquito()
        if mosquito is None:
            return
        import simpleplay_mosquito
        qr = simpleplay_mosquito.pixmap_qr(mosquito.url, 208)
        panel = self._abrir_panel(lambda p: DialogoMosquito(p, mosquito, qr))

        def cerrado(*_):
            if panel.apagado and getattr(self, "_mosquito", None) is mosquito:
                mosquito.detener()
                self._mosquito = None     # apagado a propósito (si está «recordado», vuelve a arrancar la próxima vez)
        panel.finished.connect(cerrado)

    def abrir_youtube(self):
        try:
            import simpleplay_youtube
        except ImportError as e:
            self._aviso(tr("Falta instalar: pip install -r requirements-youtube.txt", "Missing: pip install -r requirements-youtube.txt"), 5000)
            log("youtube:", e)
            return
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "youtube"
        simpleplay_youtube.DialogoYouTube(self, tr, ESTADO.parent, cache).exec()

    def vaciar_lista(self):
        """Saca todos los temas de la lista (los archivos no se borran). No depende de la selección."""
        self.buscador.clear()                # con un filtro activo "quitar" solo vería lo visible
        if self.pistas:
            self.quitar(list(range(len(self.pistas))))
        self.lista_actual = ""

    def recordar_carpeta(self, carpeta):
        """Anota la carpeta como una de las de la biblioteca (las últimas ocho, la más reciente primero)."""
        carpeta = str(carpeta)
        self.carpetas_musica = ([carpeta] + [c for c in self.carpetas_musica if c != carpeta])[:8]
        self.guardar_estado()

    def abrir_musica(self):
        return self._abrir_panel(DialogoMusica)

    def abrir_lista(self, ruta=None):
        """Reemplaza la lista actual por la de un archivo M3U/M3U8; avisa cuántas entradas no se encontraron."""
        if not ruta:
            ruta, _ = QFileDialog.getOpenFileName(
                self, tr("Abrir lista", "Open playlist"), self._carpeta_inicial(),
                tr("Listas (*.m3u *.m3u8)", "Playlists (*.m3u *.m3u8)"))
        if not ruta:
            return
        try:
            temas, faltan = leer_lista(ruta)
        except OSError:
            self._aviso(tr("No se pudo leer la lista", "Couldn't read the playlist"))
            return
        if not temas:
            self._aviso(tr("La lista no tiene temas que se encuentren", "No tracks of that list were found"))
            return
        self.buscador.clear()                # con un filtro activo "quitar" solo vería lo visible
        self.vaciar_lista()
        self.agregar(temas)
        self.carpeta_musica = str(Path(temas[0]).parent)
        self.lista_actual = str(Path(ruta).resolve())
        self.carpeta_listas = str(Path(ruta).resolve().parent)
        self._aviso(tr(f"{len(temas)} temas", f"{len(temas)} tracks") +
                    (tr(f" ({faltan} no se encontraron)", f" ({faltan} not found)") if faltan else ""), 3500)
        self.guardar_estado()

    def _carpeta_listas(self):
        if self.carpeta_listas and Path(self.carpeta_listas).is_dir():
            return self.carpeta_listas
        return self._carpeta_inicial()

    def _menu_tema(self, pos):
        """Clic derecho sobre un tema: agregarlo a una lista (existente o nueva) o quitarlo."""
        if not self.filas_elegidas():
            return
        menu = Menu(self)
        sub = menu.addMenu(tr("Agregar a lista", "Add to playlist"))
        sub.addAction(tr("Nueva lista…", "New playlist…"), self.nueva_lista)
        existentes = sorted(Path(self._carpeta_listas()).glob("*.m3u8"), key=lambda x: x.name.lower())
        if existentes:
            sub.addSeparator()
        for f in existentes[:30]:
            sub.addAction(f.stem, lambda f=f: self.agregar_a_lista(str(f)))
        sub.addSeparator()
        sub.addAction(tr("Otra lista…", "Another playlist…"), lambda: self.agregar_a_lista(None))
        menu.addAction(tr("Quitar de la lista", "Remove from the list"), self.quitar)
        menu.exec(self.lista.viewport().mapToGlobal(pos))

    def nueva_lista(self):
        """Crea una lista nueva con los temas elegidos."""
        ruta, _ = QFileDialog.getSaveFileName(
            self, tr("Nueva lista", "New playlist"), str(Path(self._carpeta_listas()) / "lista.m3u8"),
            tr("Lista M3U8 (*.m3u8)", "M3U8 playlist (*.m3u8)"))
        if ruta:
            self.agregar_a_lista(ruta if Path(ruta).suffix.lower() in LISTAS else ruta + ".m3u8")

    def agregar_a_lista(self, ruta):
        """Agrega los temas elegidos al final de una lista (la crea si no existe) sin tocar la lista que suena."""
        filas = self.filas_elegidas()
        if not filas:
            return
        if not ruta:
            ruta, _ = QFileDialog.getOpenFileName(
                self, tr("Agregar a lista", "Add to playlist"), self._carpeta_listas(),
                tr("Listas (*.m3u *.m3u8)", "Playlists (*.m3u *.m3u8)"))
            if not ruta:
                return
        try:
            n = agregar_a_lista(ruta, [self.pistas[i] for i in filas], self.datos)
        except OSError:
            self._aviso(tr("No se pudo guardar la lista", "Couldn't save the playlist"))
            return
        self.carpeta_listas = str(Path(ruta).resolve().parent)
        nombre = Path(ruta).stem
        self._aviso(tr(f"{n} agregado(s) a «{nombre}»", f"{n} added to “{nombre}”") if n
                    else tr(f"Ya estaban en «{nombre}»", f"Already in “{nombre}”"))

    def _guardar_rapido(self):
        """El disquete: reescribe la lista abierta; si no hay una, pide el nombre."""
        if not self.pistas:
            self._aviso(tr("No hay temas para guardar", "There are no tracks to save"))
        elif self.lista_actual and Path(self.lista_actual).parent.is_dir():
            self.guardar_lista(self.lista_actual)
        else:
            self.guardar_lista()

    def guardar_lista(self, ruta=None):
        """Guarda los temas de la lista, en el orden en que están, como M3U8 con rutas relativas."""
        if not self.pistas:
            return
        if not ruta:
            ruta, _ = QFileDialog.getSaveFileName(
                self, tr("Guardar lista", "Save playlist"), str(Path(self._carpeta_listas()) / "lista.m3u8"),
                tr("Lista M3U8 (*.m3u8)", "M3U8 playlist (*.m3u8)"))
        if not ruta:
            return
        if Path(ruta).suffix.lower() not in LISTAS:
            ruta += ".m3u8"
        try:
            escribir_lista(ruta, self.pistas, self.datos)
        except OSError:
            self._aviso(tr("No se pudo guardar la lista", "Couldn't save the playlist"))
            return
        self.lista_actual = str(Path(ruta).resolve())
        self.carpeta_listas = str(Path(ruta).resolve().parent)
        self.guardar_estado()
        self._aviso(tr(f"Lista guardada ({len(self.pistas)} temas)", f"Playlist saved ({len(self.pistas)} tracks)"))

    def agregar(self, archivos, mostrar=True, avisar=False):
        """Agrega mp3 (o carpetas, con sus subcarpetas) a la lista; los que ya estaban no se repiten."""
        primera = not self.pistas
        existentes = set(self.pistas)
        nuevos = [r for r in buscar_audio(archivos) if r not in existentes]
        for r in nuevos:
            self.pistas.append(r)
            self.orden_original.append(r)
            self.datos[r] = datos_lista(r)
            item = QListWidgetItem(self.datos[r]["nombre"])
            item.setData(Qt.UserRole, r)
            self.lista.addItem(item)
        if nuevos:
            self.vaciada = False
            self._filtrar(self.buscador.text())  # respeta una búsqueda en curso
        if primera and self.pistas:
            self.lista.setCurrentRow(0)
            if mostrar:
                self.mostrar_meta(0)
        if avisar:
            self._aviso(tr(f"{len(nuevos)} temas agregados", f"{len(nuevos)} tracks added") if nuevos
                        else tr("No hay temas nuevos para agregar", "No new tracks to add"))
        self.mpris_cambio("CanGoNext", "CanGoPrevious", "CanPlay")

    def filas_elegidas(self):
        """Filas seleccionadas y visibles en la lista; si no hay, la fila marcada."""
        filas = {self.lista.row(it) for it in self.lista.selectedItems() if not it.isHidden()}
        fila = self.lista.currentRow()
        if not filas and fila >= 0 and not self.lista.item(fila).isHidden():
            filas = {fila}
        return sorted(i for i in filas if 0 <= i < len(self.pistas))

    # --- buscar, ordenar y reordenar ---
    def _pedir_cuenta(self, *_):
        try:
            self._t_cuenta.start()
        except RuntimeError:       # la ventana se está destruyendo
            pass

    def _actualizar_cuenta(self):
        """Cuántos temas tiene la lista; con una búsqueda activa, cuántos se ven ("3 de 12")."""
        total = self.lista.count()
        visibles = sum(1 for i in range(total) if not self.lista.item(i).isHidden())
        if visibles != total:
            txt = tr(f"{visibles} de {total}", f"{visibles} of {total}")
        else:
            txt = tr("1 tema", "1 track") if total == 1 else tr(f"{total} temas", f"{total} tracks")
        self.cuenta.setText(txt)

    def _filtrar(self, texto):
        """Muestra solo los temas que contienen todas las palabras buscadas (sin acentos ni mayúsculas)."""
        palabras = _norm(texto).split()
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            d = self.datos.get(item.data(Qt.UserRole))
            pajar = _norm(f"{d['nombre']} {d['album']}") if d else ""
            item.setHidden(bool(palabras) and not all(w in pajar for w in palabras))
        # con una búsqueda activa no se arrastra: las posiciones visibles no son las reales
        self.lista.setDragDropMode(QAbstractItemView.NoDragDrop if palabras else QAbstractItemView.InternalMove)
        self._t_cuenta.start()

    def _reproducir_primero(self):
        for i in range(self.lista.count()):
            if not self.lista.item(i).isHidden():
                self.buscador.clearFocus()
                self.reproducir(i)
                return

    def enfocar_buscador(self):
        if not self.lista_abierta:
            self.btn_lista.setChecked(True)
        self.buscador.setFocus()
        self.buscador.selectAll()

    def _esc(self):
        """Esc primero sale de la búsqueda; con la búsqueda vacía cierra el reproductor."""
        if self.buscador.hasFocus() or self.buscador.text():
            self.buscador.clear()
            self.buscador.clearFocus()
            return
        self.close()

    def _menu_orden(self):
        menu = Menu(self)
        for modo, es, en in (("original", "En el orden en que se agregaron", "In the order they were added"),
                             ("artista", "Por artista", "By artist"),
                             ("titulo", "Por título", "By title"),
                             ("album", "Por álbum", "By album")):
            marca = "✓  " if modo == self.modo_orden else "     "
            menu.addAction(marca + tr(es, en), lambda m=modo: self.ordenar(m))
        menu.exec(self.btn_orden.mapToGlobal(QPoint(0, self.btn_orden.height())))

    def ordenar(self, modo):
        """Reordena la lista; el tema que suena sigue sonando y la selección se conserva."""
        if len(self.pistas) < 2 or modo not in ORDENES:
            return
        self.modo_orden = modo
        if modo == "original":
            presentes = set(self.pistas)
            nuevo = [r for r in self.orden_original if r in presentes]
        else:
            nuevo = sorted(self.pistas, key=lambda r: clave_orden(modo, self.datos[r]))
        self._rehacer_lista(nuevo)
        self.guardar_estado()

    def _ruta_en(self, indice):
        return self.pistas[indice] if 0 <= indice < len(self.pistas) else None

    def _rehacer_lista(self, nuevas):
        actual_r, pend = self._ruta_en(self.actual), self.pendiente
        pend_r = self._ruta_en(pend[0]) if pend else None
        elegidas = {self.pistas[i] for i in self.filas_elegidas()}
        self.lista.blockSignals(True)
        self.lista.clear()
        for r in nuevas:
            item = QListWidgetItem(self.datos[r]["nombre"])
            item.setData(Qt.UserRole, r)
            self.lista.addItem(item)
        self.lista.blockSignals(False)
        self.pistas = list(nuevas)
        if actual_r is not None:
            self.actual = nuevas.index(actual_r)
        if pend_r is not None:
            self.pendiente = (nuevas.index(pend_r), pend[1])
        fila = self.actual if self.actual >= 0 else (self.pendiente[0] if self.pendiente else -1)
        if fila >= 0:
            self.lista.setCurrentRow(fila, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.lista.scrollToItem(self.lista.item(fila))
        for i, r in enumerate(nuevas):
            if r in elegidas:
                self.lista.item(i).setSelected(True)
        self._filtrar(self.buscador.text())

    def _reordenado(self, *_):
        """El usuario arrastró temas en la lista: alinear las rutas y los índices con el nuevo orden."""
        nuevas = [self.lista.item(i).data(Qt.UserRole) for i in range(self.lista.count())]
        if sorted(nuevas) != sorted(self.pistas) or nuevas == self.pistas:
            return
        actual_r, pend = self._ruta_en(self.actual), self.pendiente
        pend_r = self._ruta_en(pend[0]) if pend else None
        self.pistas = nuevas
        if actual_r is not None:
            self.actual = nuevas.index(actual_r)
        if pend_r is not None:
            self.pendiente = (nuevas.index(pend_r), pend[1])
        self.modo_orden = "manual"
        self.guardar_estado()

    def quitar(self, filas=None):
        """Quita de la lista los temas seleccionados, o los de `filas` si se dan (los archivos no se borran)."""
        filas = self.filas_elegidas() if filas is None else sorted(set(filas))
        if not filas:
            return
        actual_quitado = self.actual in filas
        sonaba = actual_quitado and not self.pausado
        pend_quitado = bool(self.pendiente) and self.pendiente[0] in filas
        antes_actual = sum(1 for i in filas if i < self.actual)
        antes_pend = sum(1 for i in filas if self.pendiente and i < self.pendiente[0])
        for i in reversed(filas):
            self.lista.takeItem(i)
            del self.pistas[i]
        presentes = set(self.pistas)
        self.orden_original = [r for r in self.orden_original if r in presentes]
        if not self.pistas:
            self.vaciar()
        elif actual_quitado or pend_quitado:
            nuevo = min(filas[0], len(self.pistas) - 1)  # sigue el que ocupó su lugar
            if sonaba:
                self.reproducir(nuevo)
            else:
                self.motor.parar()
                self.actual = -1
                self.pausado = False
                self.lista.setCurrentRow(nuevo)
                self.mostrar_meta(nuevo)
                self._preparar(nuevo, 0.0)
                self.icono_play()
        else:
            if self.actual >= 0:
                self.actual -= antes_actual
            if self.pendiente:
                self.pendiente = (self.pendiente[0] - antes_pend, self.pendiente[1])
            # la fila marcada sigue siendo el tema actual, no el vecino del que se quitó
            fila = self.actual if self.actual >= 0 else (
                self.pendiente[0] if self.pendiente else min(filas[0], len(self.pistas) - 1))
            self.lista.setCurrentRow(fila)
        self.guardar_estado()
        self.mpris_cambio("CanGoNext", "CanGoPrevious", "CanPlay", "Metadata")

    # --- escoba: completar los datos de los temas elegidos ---
    def _preguntar(self, n):
        caja = QMessageBox(self)
        caja.setStyleSheet(tinte(ESTILO_DIALOGO))
        caja.setIcon(QMessageBox.Question)
        caja.setWindowTitle(tr("Completar datos", "Fill in track info"))
        caja.setText(tr(f"¿Buscar en MusicBrainz y escribir título, artista, álbum y portada en {n} archivo(s)?",
                        f"Look up {n} file(s) on MusicBrainz and write title, artist, album and cover art into them?"))
        caja.setInformativeText(tr(
            "Esto modifica los archivos mp3. Se guardan los datos originales para poder deshacerlo. "
            "Tarda unos 6 segundos por tema.",
            "This changes the mp3 files. The original tags are saved so you can undo it. "
            "It takes about 6 seconds per track."))
        si = caja.addButton(tr("Completar", "Fill in"), QMessageBox.AcceptRole)
        caja.addButton(tr("Cancelar", "Cancel"), QMessageBox.RejectRole)
        caja.setDefaultButton(si)
        caja.exec()
        return caja.clickedButton() is si

    def limpiar_etiquetas(self):
        if not ESCOBA or self.etiquetando:
            return
        filas = self.filas_elegidas()
        if not filas:  # sin selección: el tema actual
            i = self.actual if self.actual >= 0 else (self.pendiente[0] if self.pendiente else -1)
            filas = [i] if 0 <= i < len(self.pistas) else []
        if not filas:  # que no parezca que el botón no hace nada
            self._aviso(tr("Elegí temas en la lista primero", "Select tracks in the list first"))
            return
        filas = [i for i in filas if self.pistas[i].lower().endswith(".mp3")]      # escribe etiquetas ID3: solo mp3
        if not filas:
            self._aviso(tr("La escoba solo trabaja con mp3", "The broom only works with mp3 files"))
            return
        if not self._preguntar(len(filas)):
            return
        self.etiquetando = True
        self.btn_escoba.set_ocupado(True)
        self.lote_undo = carpeta_deshacer(nueva=True)
        self.etiquetador = Etiquetador([self.pistas[i] for i in filas], self.lote_undo)
        self.etiquetador.progreso.connect(self._etq_progreso)
        self.etiquetador.terminado.connect(self._etq_fin)
        self.etiquetador.iniciar()

    def _aviso(self, texto, ms=2500):
        """Un mensaje breve en la píldora; después vuelve a mostrar el tema."""
        self.titulo.set_text(texto)
        self.artista.hide()
        QTimer.singleShot(ms, lambda: None if self.etiquetando else self._refrescar_meta() if self.pistas else self.vaciar_texto())

    def vaciar_texto(self):
        self.titulo.set_text(tr("Sin pista", "No track"))

    def _etq_progreso(self, n, total, nombre):
        self.titulo.set_text(tr(f"Buscando datos {n}/{total}…", f"Looking up {n}/{total}…"))
        self.artista.set_text(nombre)
        self.artista.show()

    def _refrescar_meta(self):
        i = self.actual if self.actual >= 0 else (self.pendiente[0] if self.pendiente else self.lista.currentRow())
        if 0 <= i < len(self.pistas):
            self.mostrar_meta(i)

    def _mostrar_resumen(self, res, hubo_cambios):
        """Cuenta qué pasó con cada archivo. -> True si el usuario pidió deshacer."""
        ok = [r for r in res if r[1] == "ok"]
        sc = [r for r in res if r[1] == "sin_coincidencia"]
        er = [r for r in res if r[1] == "error"]
        caja = QMessageBox(self)
        caja.setStyleSheet(tinte(ESTILO_DIALOGO))
        caja.setIcon(QMessageBox.Information)
        caja.setWindowTitle(tr("Completar datos", "Fill in track info"))
        caja.setText(tr(f"{len(ok)} actualizado(s), {len(sc)} sin coincidencia, {len(er)} con error.",
                        f"{len(ok)} updated, {len(sc)} with no match, {len(er)} with errors."))
        if sc:
            caja.setInformativeText(tr("Los temas sin coincidencia no se tocaron: solo se acepta un álbum de estudio "
                                       "oficial que coincida bien.",
                                       "Tracks with no match were left alone: only a clearly matching official studio "
                                       "album is accepted."))
        lineas = [f"✓ {Path(r[0]).stem}  →  {r[2]}" for r in ok] + \
                 [f"– {Path(r[0]).stem}  ({tr('sin coincidencia', 'no match')})" for r in sc] + \
                 [f"✗ {Path(r[0]).stem}: {r[2]}" for r in er]
        caja.setDetailedText("\n".join(lineas))
        cerrar = caja.addButton(tr("Aceptar", "OK"), QMessageBox.AcceptRole)
        deshacer = caja.addButton(tr("Deshacer", "Undo"), QMessageBox.ActionRole) if hubo_cambios else None
        caja.setDefaultButton(cerrar)
        caja.exec()
        return deshacer is not None and caja.clickedButton() is deshacer

    def _etq_fin(self, res):
        self.etiquetando = False
        self.btn_escoba.set_ocupado(False)
        hubo = any(r[1] == "ok" for r in res)
        self._refrescar_meta()  # vuelve a leer las etiquetas: la píldora y la portada se actualizan
        if self._mostrar_resumen(res, hubo) and self.lote_undo:
            restaurar_originales(self.lote_undo)
            self._refrescar_meta()

    def vaciar(self):
        """La lista quedó sin temas: vuelve al estado inicial."""
        self.motor.parar()
        self.actual = -1
        self.pausado = False
        self.pendiente = None
        self.duracion = 0.0
        self.picos.clear()
        self.ref_suave = self._ref_p = None
        self.vaciada = True
        self.orden_original = []
        self.meta = {"titulo": "", "artista": "", "arte": ""}
        self.titulo.set_text(tr("Sin pista", "No track"))
        self.artista.set_text("")
        self.artista.hide()
        self.thumb.hide()
        self.pill_lay.setContentsMargins(16, 3, 14, 3)
        self.card.set_pixmap(None)
        self.linea.setValue(0)
        self.t_actual.setText("0:00")
        self.t_resta.setText("-0:00")
        self.icono_play()

    # --- sonido ---
    # --- perfiles de auriculares ---
    def _dir_perfiles(self):
        return ESTADO.parent / "perfiles"

    def perfiles_instalados(self):
        """[(identificador, nombre)] de los perfiles guardados."""
        out = []
        for f in sorted(self._dir_perfiles().glob("*.json")):
            try:
                out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))["nombre"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return out

    def _cargar_perfil(self, ident):
        try:
            d = json.loads((self._dir_perfiles() / f"{ident}.json").read_text(encoding="utf-8"))
            return [float(x) for x in d["freqs"]], [float(x) for x in d["ganancias"]], d.get("nombre", ident)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def instalar_perfil(self, nombre, fuente, freqs, ganancias):
        """Guarda un perfil y devuelve su identificador."""
        ident = slug_de(f"{nombre} {fuente}")
        carpeta = self._dir_perfiles()
        carpeta.mkdir(parents=True, exist_ok=True)
        tmp = carpeta / f"{ident}.tmp"
        tmp.write_text(json.dumps({"nombre": nombre, "fuente": fuente, "freqs": [round(f, 2) for f in freqs],
                                   "ganancias": [round(g, 2) for g in ganancias]}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, carpeta / f"{ident}.json")
        return ident

    def _aplicar_eq(self):
        if self.preset.startswith("perfil:"):
            p = self._cargar_perfil(self.preset[7:])
            if p is not None:
                freqs, gan, _ = p
                # un perfil suele bajar el nivel general (trae su preamp metido): se sube para que escucharlo y volver
                # a un preset suene igual de fuerte, sin que "el mejor" sea solo "el más fuerte"
                comp = min(max(-nivel_relativo_db(freqs, gan), 0.0), COMPENSACION_MAX_DB)
                self.motor.cadena.poner_eq(gan, freqs=freqs, makeup_db=comp)
                return
            self.preset = "plano"                                    # el perfil ya no está guardado
        if self.preset.startswith("mio:"):
            if self.preset[4:] in self.mis_presets:
                self.escuchar_curva(self.mis_presets[self.preset[4:]])
                return
            self.preset = "plano"                                    # ese preset ya no existe
        if self.preset == "parametrico":
            curva = curva_parametrica(self.eq_param)
            self.motor.cadena.poner_eq(list(curva), freqs=PUNTOS_PERFIL, nivel_db=nivel_relativo_db(PUNTOS_PERFIL, curva))
            return
        if self.preset == "personal" and self.eq_personal:
            self.escuchar_curva(self.eq_personal)
            return
        if self.preset == "personal":
            self.preset = "plano"                                    # no hay 'Mi sonido' guardado
        self.motor.cadena.poner_eq(PRESETS.get(self.preset, PRESETS["plano"]))

    def escuchar_curva(self, curva):
        """Aplica una curva de 10 bandas a igual volumen que sin ecualizar (así dos curvas se comparan por cómo suenan y no por
        cuál es más fuerte)."""
        self.motor.cadena.poner_eq(list(curva), nivel_db=nivel_relativo_db(BANDAS_HZ, curva))

    def curva_actual(self):
        """Las 10 ganancias (dB) que suenan ahora: las del preset, las de Mi sonido o, con un perfil de auriculares, esa
        corrección vista en las 10 bandas."""
        c = curva_de_preset(self.preset, self.eq_personal, self.mis_presets)
        if c is not None:
            return c
        if self.preset == "parametrico":
            v = np.interp(np.log10(BANDAS_HZ), np.log10(PUNTOS_PERFIL), curva_parametrica(self.eq_param))
            return [round(float(max(-LIM_BANDA_DB, min(LIM_BANDA_DB, x))) * 2) / 2 for x in v]
        if self.preset.startswith("perfil:"):
            p = self._cargar_perfil(self.preset[7:])
            if p is not None:
                v = np.interp(np.log10(BANDAS_HZ), np.log10(p[0]), p[1])
                return [round(float(max(-LIM_BANDA_DB, min(LIM_BANDA_DB, x))) * 2) / 2 for x in v]
        return [0.0] * len(BANDAS_HZ)

    def poner_curva_personal(self, curva):
        """Guarda una curva como 'Mi sonido' y la deja puesta."""
        self.eq_personal = [round(max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(x))) * 2) / 2 for x in curva][:len(BANDAS_HZ)]
        self.preset = "personal"
        self._aplicar_eq()
        self.guardar_estado()

    def pedir_nombre_preset(self, sugerido):
        """Le pregunta al usuario cómo llamar al preset que va a guardar -> el nombre, o None si canceló."""
        nombre, ok = QInputDialog.getText(self, tr("Guardar preset", "Save preset"),
                                          tr("Nombre del preset:", "Preset name:"), text=sugerido)
        nombre = " ".join(nombre.split())[:24] if ok else ""
        return nombre or None

    def guardar_mi_preset(self, nombre, curva=None):
        """Guarda una curva (por defecto la que suena ahora) con un nombre y la deja puesta. Si el nombre existe, lo reemplaza."""
        curva = self.curva_actual() if curva is None else curva
        self.mis_presets[nombre] = [round(max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(x))) * 2) / 2 for x in curva][:len(BANDAS_HZ)]
        self.preset = "mio:" + nombre
        self._aplicar_eq()
        self.guardar_estado()

    def borrar_mi_preset(self, nombre):
        self.mis_presets.pop(nombre, None)
        if self.preset == "mio:" + nombre:
            self.preset = "plano"
            self._aplicar_eq()
        self.guardar_estado()

    def _abrir_panel(self, clase):
        """Abre un panel del sonido al costado de la ventana (uno solo a la vez; la música y la ventana siguen libres)."""
        if self._panel is not None and self._panel.isVisible():
            self._panel.cerrar_ya()
        self._panel = clase(self)
        self._panel.show()
        return self._panel

    def ecualizador(self):
        return self._abrir_panel(DialogoEcualizador)

    def afinar_al_oido(self):
        return self._abrir_panel(DialogoBuscarSonido)

    def parametrico(self):
        return self._abrir_panel(DialogoParametrico)

    def espacial(self):
        return self._abrir_panel(DialogoEspacial)

    def poner_parametrico(self, bandas):
        """Pone las bandas del ecualizador paramétrico (frecuencia, ganancia, Q), lo elige y lo guarda."""
        self.eq_param = [[max(PARAM_HZ[0], min(PARAM_HZ[1], float(f))), max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(g))),
                          max(PARAM_Q[0], min(PARAM_Q[1], float(q)))] for f, g, q in bandas]
        self.preset = "parametrico"
        self._aplicar_eq()
        self.guardar_estado()

    def _aplicar_espacial(self):
        self.motor.cadena.poner_balance(self.balance)
        self.motor.cadena.poner_crossfeed(CROSSFEED_NIVELES[self.crossfeed])

    def poner_balance(self, pct):
        self.balance = max(-100, min(100, int(round(pct))))
        self._aplicar_espacial()
        self.guardar_estado()

    def poner_crossfeed(self, nivel):
        self.crossfeed = max(0, min(len(CROSSFEED_NIVELES) - 1, int(nivel)))
        self._aplicar_espacial()
        self.guardar_estado()

    def poner_preset(self, nombre):
        existe = (nombre in PRESETS or nombre == "parametrico" or (nombre == "personal" and bool(self.eq_personal))
                  or (nombre.startswith("mio:") and nombre[4:] in self.mis_presets)
                  or (nombre.startswith("perfil:") and self._cargar_perfil(nombre[7:]) is not None))
        self.preset = nombre if existe else "plano"
        self._aplicar_eq()
        self.guardar_estado()

    def buscar_auriculares(self):
        DialogoAuriculares(self).exec()

    def descargar_perfil(self, nombre, fuente, ruta):
        """Baja el perfil de AutoEq de un modelo, lo guarda y lo activa."""
        self._aviso(tr("Bajando el perfil…", "Downloading the profile…"), 4000)

        def trabajo():
            try:
                freqs, gan = leer_perfil(_http(url_perfil(ruta), binario=True).decode("utf-8"))
                self.perfil_listo.emit(self.instalar_perfil(nombre, fuente, freqs, gan), "")
            except Exception as e:
                self.perfil_listo.emit("", str(e) or type(e).__name__)
        threading.Thread(target=trabajo, daemon=True).start()

    @Slot(str, str)
    def _perfil_listo(self, ident, error):
        if error:
            self._aviso(tr("No se pudo bajar el perfil: ", "Could not download the profile: ") + error, 5000)
            return
        self.poner_preset("perfil:" + ident)
        p = self._cargar_perfil(ident)
        self._aviso((p[2] if p else ident) + tr(" listo", " ready"), 3500)

    def importar_perfil(self):
        """Lee un perfil de AutoEq (GraphicEQ.txt o ParametricEQ.txt) de un archivo."""
        ruta, _ = QFileDialog.getOpenFileName(self, tr("Importar un perfil de ecualización", "Import an equalizer profile"),
                                              str(Path.home()), tr("Perfiles de AutoEq (*.txt);;Todos (*)", "AutoEq profiles (*.txt);;All (*)"))
        if ruta:
            self.importar_perfil_de(ruta)

    def importar_perfil_de(self, ruta):
        try:
            freqs, gan = leer_perfil(Path(ruta).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as e:
            self._aviso(tr("No se pudo leer el perfil: ", "Could not read the profile: ") + str(e), 5000)
            return None
        nombre = re.sub(r"\s*(GraphicEQ|ParametricEQ)$", "", Path(ruta).stem, flags=re.I)
        ident = self.instalar_perfil(nombre, tr("importado", "imported"), freqs, gan)
        self.poner_preset("perfil:" + ident)
        self._aviso(nombre + tr(" listo", " ready"), 3500)
        return ident

    def poner_normalizar(self, si):
        self.normalizar = bool(si)
        if self.actual >= 0 and self.actual < len(self.pistas):
            self._sonoridad_del_tema(self.pistas[self.actual])
        else:
            self.motor.cadena.poner_ganancia(0.0)
        self.guardar_estado()

    def _cache_sonoridad(self):
        if self._sonoridades is None:
            try:
                self._sonoridades = json.loads((ESTADO.parent / "sonoridad.json").read_text())
            except (OSError, ValueError):
                self._sonoridades = {}
        return self._sonoridades

    def _sonoridad_del_tema(self, ruta):
        """Fija la ganancia del tema: ReplayGain de las etiquetas, o la sonoridad medida (y guardada en una caché)."""
        cadena = self.motor.cadena
        if not self.normalizar:
            cadena.poner_ganancia(0.0)
            return
        rg = leer_replaygain(ruta)
        if rg is not None:
            cadena.poner_ganancia(rg)
            return
        try:
            st = os.stat(ruta)
            clave = f"{ruta}|{st.st_size}|{st.st_mtime_ns}"
        except OSError:
            return
        cache = self._cache_sonoridad()
        if clave in cache:
            v = cache[clave]
            cadena.poner_ganancia(ganancia_para(v["lufs"], v["pico"]) if v else 0.0)
            return
        cadena.poner_ganancia(0.0)          # hasta tener la medida, el tema suena como viene
        self._medir_en_fondo(ruta, clave, self.duracion)

    def _medir_en_fondo(self, ruta, clave, dur=0.0):
        """Mide la sonoridad de un tema en otro hilo y la guarda en la caché. Si el tema está sonando cuando llega la
        medida, la ganancia se acomoda con una rampa suave. Sin `dur` (el tema de adelante) la lee del archivo."""
        if clave in self._midiendo:
            return
        self._midiendo.add(clave)
        cache = self._cache_sonoridad()

        def medir():
            try:
                d = dur or duracion_de(ruta)
                if d <= 0 or d > LARGO_SIN_MEDIR:
                    return
                r = medir_tema(ruta, d)
                cache[clave] = {"lufs": r[0], "pico": r[1]} if r else None
                try:
                    ESTADO.parent.mkdir(parents=True, exist_ok=True)
                    tmp = (ESTADO.parent / "sonoridad.json").with_suffix(".tmp")
                    tmp.write_text(json.dumps(cache))
                    os.replace(tmp, ESTADO.parent / "sonoridad.json")
                except OSError:
                    pass
                if r and self.normalizar and self.motor.ruta == ruta:
                    self.motor.cadena.poner_ganancia(ganancia_para(*r), suave=True)
            finally:
                self._midiendo.discard(clave)
        threading.Thread(target=medir, daemon=True).start()

    def _premedir_siguiente(self):
        """Mientras suena un tema, mide el que sigue (en orden): así empieza ya normalizado, sin el salto de la primera vez."""
        if not self.normalizar:
            return
        if self.btn_shuffle.isChecked():
            i = self._sortear_siguiente()          # en shuffle el que sigue se decide ahora y es el que va a sonar
        else:
            i = self.actual + 1
        if not 0 <= i < len(self.pistas):
            return
        ruta = self.pistas[i]
        if leer_replaygain(ruta) is not None:
            return
        try:
            st = os.stat(ruta)
        except OSError:
            return
        clave = f"{ruta}|{st.st_size}|{st.st_mtime_ns}"
        if clave not in self._cache_sonoridad():
            self._medir_en_fondo(ruta, clave)

    def _sortear_siguiente(self):
        """Shuffle: el tema que va a seguir, sorteado de antemano (así se lo puede medir antes de que suene y empieza ya
        normalizado). `siguiente` usa este mismo sorteo; se descarta si dejó de valer (la lista o la ronda cambiaron)."""
        if len(self.pistas) < 2:
            return -1
        ruta_actual = self._ruta_actual()
        sig = self._sig_azar
        if sig is not None:
            ruta, nueva = sig
            if ruta in self.pistas and ruta != ruta_actual and (nueva or ruta not in self._ya_sonaron):
                return self.pistas.index(ruta)
        i, nueva = elegir_al_azar(self.pistas, self._ya_sonaron, ruta_actual)
        self._sig_azar = (self.pistas[i], nueva)
        return i

    def _menu_sonido(self, menu, anidado=True):
        sub = menu.addMenu(tr("Sonido", "Sound")) if anidado else menu
        a = sub.addAction(tr("Normalizar el volumen", "Normalize volume"))
        a.setCheckable(True)
        a.setChecked(self.normalizar)
        a.toggled.connect(self.poner_normalizar)
        sub.addSeparator()
        for clave, (es, en) in NOMBRES_PRESETS.items():
            b = sub.addAction(tr(es, en))
            b.setCheckable(True)
            b.setChecked(self.preset == clave)
            b.triggered.connect(lambda _=False, c=clave: self.poner_preset(c))
        if EQ_GRAFICO:
            if self.eq_personal:
                b = sub.addAction(tr("Mi sonido", "My sound"))
                b.setCheckable(True)
                b.setChecked(self.preset == "personal")
                b.triggered.connect(lambda _=False: self.poner_preset("personal"))
            for n in self.mis_presets:
                b = sub.addAction(n)
                b.setCheckable(True)
                b.setChecked(self.preset == "mio:" + n)
                b.triggered.connect(lambda _=False, n=n: self.poner_preset("mio:" + n))
            if self.mis_presets:
                borrar = sub.addMenu(tr("Borrar un preset", "Delete a preset"))
                for n in self.mis_presets:
                    borrar.addAction(n, lambda n=n: self.borrar_mi_preset(n))
            b = sub.addAction(tr("Paramétrico", "Parametric"))
            b.setCheckable(True)
            b.setChecked(self.preset == "parametrico")
            b.triggered.connect(lambda _=False: self.poner_preset("parametrico"))
            sub.addSeparator()
            sub.addAction(tr("Ecualizador gráfico…", "Graphic equalizer…"), self.ecualizador)
            sub.addAction(tr("Ecualizador paramétrico…", "Parametric equalizer…"), self.parametrico)
            sub.addAction(tr("Buscar mi sonido…", "Find my sound…"), self.afinar_al_oido)
        sub.addSeparator()
        sub.addAction(tr("Balance y espacio…", "Balance and space…"), self.espacial)
        # los perfiles de auriculares: una corrección medida para cada modelo, que se baja una vez y queda guardada
        sub.addSeparator()
        aur = sub.addMenu(tr("Auriculares", "Headphones")) if anidado else sub
        instalados = self.perfiles_instalados()
        for ident, nombre in instalados:
            b = aur.addAction(nombre)
            b.setCheckable(True)
            b.setChecked(self.preset == f"perfil:{ident}")
            b.triggered.connect(lambda _=False, i=ident: self.poner_preset("perfil:" + i))
        if instalados:
            aur.addSeparator()
        aur.addAction(tr("Buscar auriculares…", "Find headphones…"), self.buscar_auriculares)
        aur.addAction(tr("Importar un perfil…", "Import a profile…"), self.importar_perfil)

    def _preparar(self, i, pos):
        """Deja el tema i listo para dar play: en pausa, en la posición pos y sin sonar."""
        self.duracion = duracion_de(self.pistas[i])
        if self.duracion > 0:
            pos = min(pos, self.duracion)
            self.linea.setValue(round(pos / self.duracion * 1000))
        else:
            self.linea.setValue(0)
        self.t_actual.setText(fmt(pos))
        self.t_resta.setText("-" + fmt(self.duracion - pos))
        self.pendiente = (i, pos)

    def guardar_estado(self):
        if not self.pistas and not self.vaciada:
            return  # nunca se cargó nada: no pisar la sesión guardada
        if not self.pistas:
            i, pos = 0, 0.0
        elif self.actual >= 0:
            i, pos = self.actual, self.posicion()
        elif self.pendiente:
            i, pos = self.pendiente
        else:
            i, pos = max(self.lista.currentRow(), 0), 0.0
        datos = {"pistas": self.pistas, "indice": i, "pos": round(pos, 1),
                 "shuffle": self.btn_shuffle.isChecked(), "repetir": self.repetir,
                 "shuffle_ya": sorted(self._ya_sonaron),
                 "carpeta": self.carpeta_musica, "carpeta_listas": self.carpeta_listas,
                 "carpetas_musica": self.carpetas_musica,
                 "lista_actual": self.lista_actual, "orden_original": self.orden_original,
                 "compacto": self.compacto, "ocultar_controles": self.ocultar_controles, "normalizar": self.normalizar, "preset": self.preset,
                 "eq_personal": self.eq_personal, "mis_presets": self.mis_presets,
                 "eq_param": self.eq_param, "balance": self.balance, "crossfeed": self.crossfeed}
        try:
            ESTADO.parent.mkdir(parents=True, exist_ok=True)
            tmp = ESTADO.with_suffix(".tmp")
            tmp.write_text(json.dumps(datos, ensure_ascii=False))
            os.replace(tmp, ESTADO)
        except OSError:
            pass

    def restaurar(self, con_pistas=True):
        """Carga la última sesión: muestra el tema (en pausa) y deja el play listo."""
        self._cargar_acento()
        try:
            d = json.loads((ESTADO if ESTADO.exists() else ESTADO_ANTIGUO).read_text())
        except (OSError, ValueError):
            return
        self.btn_shuffle.setChecked(bool(d.get("shuffle")))
        if self.btn_shuffle.isChecked():             # la ronda sigue donde quedó (la kiosk corre días seguidos)
            ya = d.get("shuffle_ya")
            if isinstance(ya, list):
                self._ya_sonaron = {r for r in ya if isinstance(r, str)}
        self.normalizar = bool(d.get("normalizar", True))
        self.ocultar_controles = bool(d.get("ocultar_controles", True))
        ep = d.get("eq_personal")
        if EQ_GRAFICO and isinstance(ep, list) and len(ep) == len(BANDAS_HZ) and all(isinstance(x, (int, float)) for x in ep):
            self.eq_personal = [max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(x))) for x in ep]
        mp = d.get("mis_presets")
        if EQ_GRAFICO and isinstance(mp, dict):
            self.mis_presets = {str(n)[:24]: [max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(x))) for x in c]
                                for n, c in mp.items() if isinstance(c, list) and len(c) == len(BANDAS_HZ)
                                and all(isinstance(x, (int, float)) for x in c)}
        bp = d.get("eq_param")
        if (isinstance(bp, list) and len(bp) == len(PARAM_BANDAS_INICIAL)
                and all(isinstance(b, list) and len(b) == 3 and all(isinstance(x, (int, float)) for x in b) for b in bp)):
            self.eq_param = [[max(PARAM_HZ[0], min(PARAM_HZ[1], float(f))), max(-LIM_BANDA_DB, min(LIM_BANDA_DB, float(g))),
                              max(PARAM_Q[0], min(PARAM_Q[1], float(q)))] for f, g, q in bp]
        b = d.get("balance", 0)
        self.balance = max(-100, min(100, int(b))) if isinstance(b, (int, float)) else 0
        c = d.get("crossfeed", 0)
        self.crossfeed = c if isinstance(c, int) and 0 <= c < len(CROSSFEED_NIVELES) else 0
        self._aplicar_espacial()
        p = d.get("preset", PRESET_INICIAL)
        self.preset = (p if p in PRESETS or p == "parametrico" or (p == "personal" and self.eq_personal)
                       or (isinstance(p, str) and p.startswith("mio:") and p[4:] in self.mis_presets)
                       or (isinstance(p, str) and p.startswith("perfil:")) else PRESET_INICIAL)
        self._aplicar_eq()
        self.poner_repetir(d.get("repetir", "off"))
        self.carpeta_musica = d.get("carpeta", "")
        self.carpeta_listas = d.get("carpeta_listas", "")
        cm = d.get("carpetas_musica")
        if isinstance(cm, list):
            self.carpetas_musica = [c for c in cm if isinstance(c, str)][:8]
        self.lista_actual = d.get("lista_actual", "")
        self.poner_compacto(bool(d.get("compacto")), animar=False)
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
        presentes = set(pistas)  # el "orden original" guardado, solo con los temas que siguen existiendo
        guardado = [r for r in d.get("orden_original", []) if r in presentes]
        self.orden_original = guardado + [r for r in pistas if r not in set(guardado)]
        self.lista.setCurrentRow(i)
        self.mostrar_meta(i)
        self._preparar(i, float(d.get("pos", 0)) if guardada in pistas else 0.0)
        self.mpris_cambio("Metadata", "PlaybackStatus", "CanSeek")

    def closeEvent(self, e):
        self.guardar_estado()
        if self.motor.reproduciendo:       # la ventana se va enseguida; el sonido baja de a poco en vez de cortarse
            self.hide()
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        if getattr(self, "_mosquito", None) is not None:
            self._mosquito.detener()
        self.motor.cerrar()
        if self.mpris:
            self.mpris.cerrar()
        super().closeEvent(e)

    def mostrar_meta(self, i):
        titulo, artista, portada = leer_meta(self.pistas[i])
        self.meta = {"titulo": titulo, "artista": artista,
                     "arte": self._guardar_portada(portada) if self.mpris and self.mpris.activo else ""}
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
        self.mpris_cambio("Metadata")

    # --- reproducción ---
    def reproducir(self, i=None):
        if i is None:
            i = self.lista.currentRow()
            if i < 0:
                if not self.pistas:
                    return
                i = 0
        self.actual = i
        self._anotar_sonado(self.pistas[i])
        self.pausado = False
        self.pendiente = None
        self.duracion = duracion_de(self.pistas[i])
        self.motor.cargar(self.pistas[i])
        self._sonoridad_del_tema(self.pistas[i])
        self._premedir_siguiente()
        self.picos.clear()
        self.ref_suave = self._ref_p = None
        self.lista.setCurrentRow(i)
        self.mostrar_meta(i)
        self.icono_play()
        self.guardar_estado()

    def _medir_panel(self):
        """Alto del panel de la lista según lo que realmente necesita su contenido (buscador, lista, botones).

        Se mide al abrirlo y no al arrancar: antes de mostrarse, los widgets todavía no tienen su tamaño
        final (fuente y estilos del escritorio) y el panel quedaba más bajo que su contenido.
        """
        self.panel.setMinimumHeight(0)
        self.panel.setMaximumHeight(16777215)
        lay = self.panel.layout()
        lay.invalidate()
        lay.activate()
        alto = max(lay.totalMinimumSize().height(), lay.totalSizeHint().height())
        self.panel.setFixedHeight(alto)
        self.caja_h = alto + self.caja.layout().contentsMargins().top()

    def alternar_lista(self, abrir):
        self.lista_abierta = abrir
        self.despliegue.stop()
        if abrir:
            self._medir_panel()
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

    def poner_compacto(self, si, animar=True):
        """Pasa entre la tarjeta y la píldora con los controles. La música no se corta."""
        if si == self.compacto:
            return
        self._fin_transicion()                       # si había una a medias, se completa al instante
        viejo = self.grab() if animar and self.isVisible() else None
        tam1 = self.size()
        self.compacto = si
        if si:  # la lista se cierra de golpe: en la píldora no hay lugar para ella
            self.despliegue.stop()
            self.lista_abierta = False
            self.mezcla_lista = 0.0
            self.caja.setMaximumHeight(0)
            self.caja.hide()
            self.btn_lista.blockSignals(True)
            self.btn_lista.setChecked(False)
            self.btn_lista.blockSignals(False)
            self.top.removeWidget(self.pill)
            self.mini_lay.insertWidget(0, self.pill, 1)
        else:
            self.mini_lay.removeWidget(self.pill)
            self.top.insertWidget(0, self.pill, 1)
        self.pill.show()
        self.card.setVisible(not si)
        self.mini.setVisible(si)
        self.btn_compacto.setVisible(not si)
        self.adjustSize()
        if viejo is not None:
            self._transicion(viejo, tam1)
        self.guardar_estado()

    def _transicion(self, viejo, tam1):
        """Anima el paso de la captura `viejo` (de tamaño tam1) al estado en que quedó la ventana."""
        self.layout().activate()
        tam2 = self.size()
        nuevo = self.grab()
        self._visibles = [(w, w.isVisible()) for w in (self.card, self.mini, self.caja)]
        for w, _ in self._visibles:
            w.hide()
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.setFixedSize(max(tam1.width(), tam2.width()), max(tam1.height(), tam2.height()))
        radio_tarjeta, radio_barra = 30, 28
        r1, r2 = (radio_tarjeta, radio_barra) if self.compacto else (radio_barra, radio_tarjeta)
        self._trans = Transicion(self, viejo, nuevo, tam1, tam2, r1, r2)
        self._trans.anim.finished.connect(self._fin_transicion)

    def _fin_transicion(self):
        t = self._trans
        if t is None:
            return
        self._trans = None
        t.anim.stop()
        t.hide()
        t.deleteLater()
        for w, visible in self._visibles:
            w.setVisible(visible)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.layout().setSizeConstraint(QLayout.SetFixedSize)
        self.adjustSize()

    def _entrada(self, w):
        """Aparece con un fundido corto (el efecto se saca al terminar: no cuesta nada después)."""
        ef = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(ef)
        a = QVariantAnimation(self)
        a.setDuration(220)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(ef.setOpacity)
        a.finished.connect(lambda: w.setGraphicsEffect(None))
        self._fade = a
        a.start()

    def alternar_barras(self):
        self.modo_barras = not self.modo_barras
        if self.modo_barras:
            self.barras.activar(True)
        self.fundido.stop()
        self.ef_texto.setEnabled(True)
        self.ef_barras.setEnabled(True)
        self.textos_w.show()
        self.barras.show()
        self.fundido.setStartValue(self.mezcla)
        self.fundido.setEndValue(1.0 if self.modo_barras else 0.0)
        self.fundido.start()

    def _fundir(self, v):
        """v: 0 = el nombre del tema, 1 = las barras. El texto se levanta un poco y se desvanece rápido; las barras
        aparecen y suben una por una (ver Barras.factor). Al volver pasa todo al revés."""
        self.mezcla = v
        self.ef_texto.setOpacity(min(max(1 - v * 1.7, 0.0), 1.0))
        self.ef_barras.setOpacity(min(max((v - 0.05) / 0.6, 0.0), 1.0))
        for m in (self.titulo, self.artista):
            m.dy = -6.0 * v
            m.update()
        self.barras.entrada = v
        self.barras.update()

    def _fin_fundido(self):
        if not self.modo_barras:
            self.barras.activar(False)
        self.textos_w.setVisible(not self.modo_barras)      # lo que no se ve no se pinta, y sin efectos se pinta directo
        self.barras.setVisible(self.modo_barras)
        self.ef_texto.setEnabled(False)
        self.ef_barras.setEnabled(False)

    def espectro(self, n):
        """BANDAS valores 0..1 con la energía por banda en este instante (escala log, autoajustada).

        Lee del motor las últimas VENTANA muestras que están sonando, así las barras van al compás del audio.
        El nivel de referencia es un percentil de los picos de los últimos ~10 s: un tema suave usa todo el rango
        igual que uno fuerte, y sigue los cambios de volumen dentro del tema.
        """
        if self.actual < 0 or self.pausado:
            return [0.0] * n
        v = self.motor.muestras(VENTANA)
        db = bandas_db(v)
        pico = float(db.max())
        if pico < -70:  # silencio digital (o todavía sin audio): barras planas y sin ensuciar el nivel de referencia
            return [0.0] * n
        self.picos.append(pico)
        self._cuenta_ref = (self._cuenta_ref + 1) % 6          # ordenar 300 valores 30 veces por segundo es de más:
        if self._ref_p is None or self._cuenta_ref == 0:       # el nivel de referencia ya se suaviza, alcanza cada ~0,2 s
            self._ref_p = float(np.percentile(self.picos, 90))
        ref = self._ref_p
        self.ref_suave = ref if self.ref_suave is None else self.ref_suave + (ref - self.ref_suave) * 0.08
        return [float(x) for x in np.clip((db - (self.ref_suave - RANGO_DB)) / RANGO_DB, 0.0, 1.0)]

    def icono_play(self):
        kind = "pause" if (self.actual >= 0 and not self.pausado) else "play"
        self.btn_play.set_kind(kind)
        self.mini_play.set_kind(kind)
        self.mpris_cambio("PlaybackStatus", "CanSeek")

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
            self.motor.reanudar()
        else:
            self.motor.pausar()
        self.pausado = not self.pausado
        self.icono_play()

    def parar(self):
        self.motor.parar()
        self.actual = -1
        self.pausado = False
        self.icono_play()
        self.linea.setValue(0)
        self.t_actual.setText("0:00")
        self.t_resta.setText("-0:00")

    def poner_repetir(self, modo):
        if modo not in ("off", "all", "one"):
            return
        self.repetir = modo
        b = self.btn_repetir
        b.badge = "1" if modo == "one" else ""
        b._animar("chk", 0.0 if modo == "off" else 1.0, 260)
        b.setToolTip({"off": tr("Repetir: no", "Repeat: off"),
                      "all": tr("Repetir: toda la lista", "Repeat: the whole list"),
                      "one": tr("Repetir: este tema", "Repeat: this track")}[modo])
        b.update()
        self.mpris_cambio("LoopStatus")

    def alternar_repetir(self):
        """No repetir -> toda la lista -> un tema -> no repetir."""
        self.poner_repetir({"off": "all", "all": "one", "one": "off"}[self.repetir])
        self.guardar_estado()

    @Slot()
    def _motor_fin(self):
        """El motor avisa (desde el hilo de audio, por la cola de Qt) que el tema se acabó. Se ignora si ya
        no corresponde: el usuario cambió de tema o saltó entre el aviso y este momento."""
        if self.actual >= 0 and not self.pausado and self.motor.terminada:
            self.fin_de_pista()

    @Slot(str)
    def _motor_error(self, mensaje):
        log("audio:", mensaje)
        self._aviso(tr("No se pudo abrir el audio", "Could not open the audio device"), 5000)

    @Slot(str, str)
    def _motor_error_archivo(self, ruta, motivo):
        """Un tema no se puede reproducir (no existe, está roto, no tiene audio): aviso y se pasa al siguiente.
        Si fallan todos los de la lista, se detiene en lugar de dar vueltas."""
        log("archivo:", ruta, motivo)
        self._fallos += 1
        if self._fallos >= max(len(self.pistas), 1):
            self._fallos = 0
            self.parar()
            self._aviso(tr("Ningún tema se pudo reproducir", "None of the tracks could be played"), 5000)
            return
        nombre = Path(ruta).name if ruta else ""
        self._aviso(tr(f"No se pudo reproducir {nombre}", f"Could not play {nombre}"), 3000)
        i = self.actual
        QTimer.singleShot(400, lambda: self._saltar_fallido(i))

    def _saltar_fallido(self, i):
        if self.actual == i and not self.motor.activo:   # nadie hizo otra cosa mientras tanto
            self.siguiente()

    def fin_de_pista(self):
        """El tema terminó solo: con 'repetir un tema' vuelve a empezar; si no, sigue con el próximo."""
        if self.repetir == "one" and self.actual >= 0:
            self.reproducir(self.actual)
        else:
            self.siguiente()

    def siguiente(self, *_):
        if not self.pistas:
            return
        if self.btn_shuffle.isChecked() and len(self.pistas) > 1:
            i = self._sortear_siguiente()
            nueva = self._sig_azar[1]
            self._sig_azar = None
            if nueva:
                self._ya_sonaron.clear()
            self.reproducir(i)
        elif self.actual + 1 < len(self.pistas):
            self.reproducir(self.actual + 1)
        elif self.repetir == "all":
            self.reproducir(0)  # al final de la lista, vuelve al principio
        else:
            self.parar()

    def _ruta_actual(self):
        i = self.actual if self.actual >= 0 else (self.pendiente[0] if self.pendiente else -1)
        return self.pistas[i] if 0 <= i < len(self.pistas) else None

    def _reiniciar_ronda(self, *_):
        """Al prender o apagar el shuffle se empieza de cero: el tema actual cuenta como ya sonado."""
        ruta = self._ruta_actual()
        self._ya_sonaron = {ruta} if ruta else set()
        self._sig_azar = None
        if self.btn_shuffle.isChecked():
            self._premedir_siguiente()             # recién prendido: que el que sigue ya esté medido

    def _anotar_sonado(self, ruta):
        if not self.btn_shuffle.isChecked():
            return
        self._ya_sonaron.add(ruta)

    def anterior(self, *_):
        if self.actual < 0:
            return
        if self.btn_shuffle.isChecked() and len(self.pistas) > 1:
            self.siguiente()         # en shuffle atrás y adelante hacen lo mismo: saltar a otro tema al azar
        # pasados 3 s vuelve al inicio de la pista, si no, a la anterior
        elif self.posicion() > 3:
            self.reproducir(self.actual)
        elif self.actual == 0:
            self.reproducir(len(self.pistas) - 1 if self.repetir == "all" else 0)
        else:
            self.reproducir(self.actual - 1)

    def posicion(self):
        return self.motor.posicion()

    def saltar(self, frac):
        if self.actual < 0 or self.duracion <= 0:
            return
        if self.motor.saltar(frac * self.duracion):  # si está en pausa, sigue en pausa
            self.mpris_seeked()

    def saltar_rel(self, delta):
        """Salta delta segundos (negativo = hacia atrás) dentro del tema actual."""
        if self.actual < 0 or self.duracion <= 0:
            return
        self.saltar(min(max((self.posicion() + delta) / self.duracion, 0.0), 0.999))

    SEGUNDOS_QUIETO = 4

    def _vigilar_controles(self):
        """Cada 200 ms: si suena un tema y nadie toca nada, los controles se funden y queda solo la portada.
        Mover el mouse los trae de vuelta."""
        cur = QCursor.pos()
        movio = cur != self._ult_cursor
        self._ult_cursor = cur
        encima = self.controles.rect().contains(self.controles.mapFromGlobal(cur))
        if (movio and self.frameGeometry().contains(cur)) or encima:   # sobre los controles nunca se esconden
            self._quietud = 0
        else:
            self._quietud += 1
        quiet = (self.ocultar_controles and self.actual >= 0 and not self.pausado and not self.compacto
                 and not self.lista_abierta and not self.linea.arrastrando
                 and QApplication.activePopupWidget() is None
                 and self._quietud * 0.2 >= self.SEGUNDOS_QUIETO)
        self._mostrar_controles(not quiet)

    def _mostrar_controles(self, si):
        meta = 1.0 if si else 0.0
        if self.fundido_ctrl.state() == QVariantAnimation.Running:
            if self.fundido_ctrl.endValue() == meta:
                return
        elif self.vis_controles == meta:
            return
        self.fundido_ctrl.stop()
        self.ef_controles.setEnabled(True)
        self.fundido_ctrl.setStartValue(self.vis_controles)
        self.fundido_ctrl.setEndValue(meta)
        self.fundido_ctrl.setDuration(180 if si else 450)   # vuelven rápido, se van despacio
        self.fundido_ctrl.start()

    def _fundir_controles(self, v):
        self.vis_controles = v
        self.ef_controles.setOpacity(v)

    def _fin_fundido_controles(self):
        if self.vis_controles >= 1.0:
            self.ef_controles.setEnabled(False)

    def tick(self):
        self._vigilar_controles()
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
        if pos > 2.0:
            self._fallos = 0   # un tema sonó de verdad: se acaba la racha de fallos

    def _formas(self):
        """(rectángulo, radio, opacidad) de cada pieza visible que proyecta sombra: la tarjeta o la barra, y el
        panel de la lista (solo la parte ya desplegada, con la opacidad de su animación)."""
        formas = []
        for w, radio in ((self.card, 30), (self.mini, 28)):
            if w.isVisible():
                formas.append((QRectF(w.geometry()), radio, 1.0))
        if self.caja.isVisible():
            a = self.panel.mapTo(self, QPoint(0, 0))
            r = QRectF(a.x(), a.y(), self.panel.width(), self.panel.height()).intersected(QRectF(self.caja.geometry()))
            if r.height() > 4:
                formas.append((r, 18, self.ef_caja.opacity()))
        return formas

    def _sombra_necesaria(self, zona):
        """False si `zona` cae entera dentro del cuerpo de la tarjeta: es opaca y la tapa, así que lo que cambió ahí
        (las barras, el tiempo, la barra de progreso) no necesita que se repinte la sombra de toda la ventana."""
        if not SOMBRA:
            return False
        if self.card.isVisible():
            g = QRectF(self.card.geometry())
            m = 30 * 0.3                       # las esquinas redondeadas dejan ver el fondo: se queda adentro de ellas
            if g.adjusted(m, m, -m, -m).contains(zona):
                return False
        return True

    def paintEvent(self, e):
        if not self._sombra_necesaria(QRectF(e.rect())):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for rect, radio, opacidad in self._formas():
            dibujar_sombra(p, rect, radio, opacidad)

    def mousePressEvent(self, e):
        # sin barra de título: se mueve arrastrando cualquier zona vacía
        if e.button() == Qt.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.agregar([u.toLocalFile() for u in e.mimeData().urls()], avisar=True)  # archivos o carpetas

    def contextMenuEvent(self, e):
        menu = Menu(self)
        menu.addAction(f"simpleplay v{VERSION}").setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Abrir archivos…", "Open files…"), self.abrir)
        menu.addAction(tr("Abrir carpeta…", "Open folder…"), self.abrir_carpeta)
        menu.addAction(tr("Modo normal", "Normal mode") if self.compacto else tr("Modo compacto", "Compact mode"),
                       lambda: self.poner_compacto(not self.compacto))
        if MOSQUITO:
            menu.addAction(tr("Mosquito (control remoto)…", "Mosquito (remote control)…") +
                           (tr(" · activo", " · on") if getattr(self, "_mosquito", None) is not None else ""),
                           self.abrir_mosquito, QKeySequence("Ctrl+Shift+M"))
        col = menu.addMenu(tr("Color de acento", "Accent color"))
        for clave, (es, en, hexa) in ACENTOS.items():
            b = col.addAction(_cubo(hexa), tr(es, en))
            b.setCheckable(True)
            b.setChecked(self.acento == clave)
            b.triggered.connect(lambda _=False, c=clave: self.poner_acento(c))
        oc = menu.addAction(tr("Ocultar controles solos", "Hide controls automatically"))
        oc.setCheckable(True)
        oc.setChecked(self.ocultar_controles)
        oc.triggered.connect(self.poner_ocultar_controles)
        self._menu_sonido(menu)
        menu.addSeparator()
        menu.addAction(tr("Apoyar el proyecto…", "Support the project…"), self.apoyar)
        menu.addAction(tr("Cerrar", "Close"), self.close)
        menu.exec(e.globalPos())

    def poner_ocultar_controles(self, si):
        self.ocultar_controles = bool(si)
        self._quietud = 0
        if not si:
            self._mostrar_controles(True)
        self.guardar_estado()

    def poner_acento(self, clave, guardar=True):
        """Cambia el color de acento en toda la app (la ventana, los paneles abiertos y lo que se pinta a mano)."""
        global ACENTO
        if clave not in ACENTOS:
            return
        ACENTO, self.acento = ACENTOS[clave][2], clave
        self.setStyleSheet(tinte(ESTILO))
        for panel in self.findChildren(PanelLateral):
            panel.setStyleSheet(tinte(ESTILO_PANEL + panel.ESTILO_EXTRA))
        for w in self.findChildren(QWidget):
            w.update()
        self.update()
        if guardar:
            try:
                ARCHIVO_ACENTO.parent.mkdir(parents=True, exist_ok=True)
                ARCHIVO_ACENTO.write_text(clave)
            except OSError:
                pass

    def tinte(self, css):
        return tinte(css)

    def _cargar_acento(self):
        try:
            self.poner_acento(ARCHIVO_ACENTO.read_text().strip(), guardar=False)
        except OSError:
            pass

    def apoyar(self):
        """Abre la página de donaciones en el navegador (es voluntario: nada en la ventana lo pide)."""
        QDesktopServices.openUrl(QUrl(URL_APOYO))


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        resto = [a for a in sys.argv[1:] if a != "--diagnose"]
        sys.exit(diagnosticar(resto[0]) if resto else print("uso: simpleplay.py --diagnose archivo.mp3|archivo.flac") or 2)
    app = QApplication(sys.argv)
    app.setApplicationName("simpleplay")
    app.setDesktopFileName("simpleplay")  # Wayland: une la ventana con su .desktop e ícono
    app.setWindowIcon(QIcon(recurso("icon/simpleplay-256.png")))
    w = Player()
    args = buscar_audio([a for a in sys.argv[1:] if not a.startswith("-")])  # archivos o carpetas
    w.restaurar(con_pistas=not args)  # con archivos por parámetro, solo se recuerdan shuffle, repetir y carpeta
    w.agregar(args)
    w.show()
    sys.exit(app.exec())
