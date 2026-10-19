# simpleplay - a small, clean mp3 player
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
import collections
import difflib
import hashlib
import json
import math
import os
import random
import re
import shutil
import ssl
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
from mutagen.mp3 import MP3
from PySide6.QtCore import (Qt, QTimer, QRectF, QPointF, QSize, Signal, QLocale, QUrl, QObject,
                            ClassInfo, Property, Slot, QMetaType,
                            QStandardPaths, QVariantAnimation, QEasingCurve, QPoint, QItemSelectionModel)
from PySide6.QtGui import (QShortcut, QKeySequence, QIcon, QFont, QFontMetrics, QPainter, QColor, QPixmap, QImage, QLinearGradient,
                           QPainterPath, QPolygonF, QPen, QPalette)
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QSlider, QAbstractButton, QListWidget,
                               QFileDialog, QFrame, QLayout, QMenu, QSizePolicy,
                               QStackedLayout, QGraphicsOpacityEffect, QMessageBox,
                               QAbstractItemView, QLineEdit, QListWidgetItem)

try:
    from PySide6.QtDBus import (QDBusConnection, QDBusAbstractAdaptor, QDBusObjectPath,
                                QDBusMessage, QDBusArgument)
    HAY_DBUS = True
except ImportError:  # sin QtDBus no hay teclas multimedia; el resto anda igual
    HAY_DBUS = False

VERSION = "1.3"
# La escoba (completar los datos del tema desde MusicBrainz) está escrita pero desactivada en esta
# versión. Para seguir trabajando en ella: SIMPLEPLAY_ESCOBA=1 python simpleplay.py
ESCOBA = bool(os.environ.get("SIMPLEPLAY_ESCOBA"))
NARANJA = "#ff4e01"

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


def datos_lista(ruta):
    """Lo que la lista necesita de un tema: nombre para mostrar, artista, título, álbum y n.º de pista."""
    art = tit = alb = ""
    pista = 0
    try:
        t = ID3(ruta)
        tit = str(t["TIT2"]).strip() if "TIT2" in t else ""
        art = str(t["TPE1"]).strip() if "TPE1" in t else ""
        alb = str(t["TALB"]).strip() if "TALB" in t else ""
        m = re.match(r"\d+", str(t["TRCK"])) if "TRCK" in t else None
        pista = int(m.group()) if m else 0
    except Exception:
        pass
    # sin etiquetas útiles: el nombre del archivo, sin "[id de YouTube]" ni "(Official Video)" (solo para mostrar)
    limpio = limpiar_nombre(Path(ruta).stem) or Path(ruta).stem
    return {"nombre": f"{art} - {tit}" if tit and art else (tit or limpio),
            "artista": art, "titulo": tit or limpio, "album": alb, "pista": pista}


def nombre_para_lista(ruta):
    """Lo que se ve en la lista: "Artista - Título" de las etiquetas; si faltan, el título o el nombre limpio."""
    return datos_lista(ruta)["nombre"]


def buscar_mp3(rutas):
    """Expande carpetas (con sus subcarpetas) y devuelve los mp3, sin repetir y en orden."""
    out, vistos = [], set()
    for r in rutas:
        p = Path(r)
        if p.is_dir():
            hallados = sorted((x for x in p.rglob("*") if x.suffix.lower() == ".mp3" and x.is_file()),
                              key=lambda x: str(x).lower())
        else:
            hallados = [p] if p.suffix.lower() == ".mp3" and p.is_file() else []
        for x in hallados:
            if str(x) not in vistos:
                vistos.add(str(x))
                out.append(str(x))
    return out


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
    res = FS / VENTANA
    out = np.empty(BANDAS)
    for k in range(BANDAS):
        a, b = _BORDES[k], _BORDES[k + 1]
        lo = int(a / res)
        hi = max(int(b / res), lo + 1)
        # la segunda parte compensa la caída natural de los agudos en la música
        out[k] = 20 * math.log10(mag[lo:hi].max() + 1e-9) + 3 * math.log2(math.sqrt(a * b) / 100)
    return out


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
        inicio = min(5.0, max(0.0, MP3(ruta).info.length - 3))
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


def candidatos(ruta, titulo_tag, artista_tag):
    """Posibles (artista, título) del tema, de lo más a lo menos probable, con etiquetas y nombre de archivo."""
    nombre, tit, art = limpiar_nombre(Path(ruta).stem), limpiar_nombre(titulo_tag), limpiar_nombre(artista_tag)
    out, invertidos = [], []
    for base in (tit, nombre):
        if " - " in base:
            a, t = (limpiar_nombre(x) for x in base.split(" - ", 1))  # cada parte por separado
            out.append((a, t))
            invertidos.append((t, a))  # por si el archivo dice "Título - Artista"
    if art and tit:
        out.append((art, tit))
    if art and nombre and " - " not in nombre:
        out.append((art, nombre))
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


def descargar_portada(info):
    """Portada de 500 px del álbum desde Cover Art Archive -> (bytes, mime) o None."""
    for tipo, mbid in (("release-group", info.get("rg")), ("release", info.get("release"))):
        if not mbid:
            continue
        try:
            time.sleep(0.3)
            datos = _http(f"https://coverartarchive.org/{tipo}/{mbid}/front-500", binario=True)
            if datos[:2] == b"\xff\xd8":
                return datos, "image/jpeg"
            if datos[:4] == b"\x89PNG":
                return datos, "image/png"
        except urllib.error.HTTPError:
            continue  # ese álbum no tiene portada
    return None


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
        try:
            duracion = MP3(ruta).info.length
        except Exception:
            duracion = None
        for artista, titulo in candidatos(ruta, tit, art):
            info = buscar_mb(artista, titulo, duracion)
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
    N = BANDAS
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
        t = self.t
        w = self.tam1.width() + (self.tam2.width() - self.tam1.width()) * t
        h = self.tam1.height() + (self.tam2.height() - self.tam1.height()) * t
        r = self.radio1 + (self.radio2 - self.radio1) * t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        forma = QPainterPath()
        forma.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.setClipPath(forma)
        p.fillRect(QRectF(0, 0, w, h), self.BASE)
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
            if ruta.lower().endswith(".mp3") and Path(ruta).exists():
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
FADE = 220          # frames (5 ms) de los fundidos de pausa y de salto, para que no haya clicks
LECTURA = 8192      # tope de frames por send() (el generador de miniaudio reserva 16384)
PREVIOS = 4         # frames mp3 que se decodifican de más antes de un salto (llenan la reserva de bits)

_BR1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_BR2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_FREC = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


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


class Motor(QObject):
    """Motor de audio: un dispositivo siempre abierto y un callback que decide, bloque a bloque, qué suena.

    - Posición = frames entregados menos la latencia del dispositivo (se interpola entre callbacks).
    - Pausa y reanudar: fundido de 5 ms, el dispositivo sigue andando (entrega silencio).
    - Saltar y cambiar de tema: fundido cruzado de 5 ms entre el audio viejo y el nuevo.
    - Fin de pista: la señal `fin_de_pista` se emite una sola vez (es segura entre hilos).
    - `muestras(n)`: las últimas n muestras (mono) que están sonando, para el espectro.
    """
    fin_de_pista = Signal()
    error_dispositivo = Signal(str)   # no se pudo abrir el audio (sin placa, ocupada por otro programa...)
    error_archivo = Signal(str, str)  # (ruta, motivo): el tema no se puede reproducir
    ANILLO = 32768

    def __init__(self, buffer_ms=120, latencia_ms=None, backend=None, parent=None, vigilancia_s=1.0, umbral_s=None, reintento_s=3.0):
        super().__init__(parent)
        self.buffer_ms = buffer_ms
        # si el dispositivo deja de pedir audio durante tanto tiempo, se lo da por caído y se lo vuelve a abrir
        self.umbral = max(1.5, 8 * buffer_ms / 1000) if umbral_s is None else umbral_s
        self.reintento = reintento_s    # cada cuánto se reintenta abrir una placa que no estaba
        # cuánto tarda en oírse lo que se entrega (aproximado: sin medir con la placa real)
        self.lat = round((buffer_ms / 2 if latencia_ms is None else latencia_ms) * FS / 1000)
        self.backends = [backend] if backend is not None else None
        self.espia = None             # para las pruebas: recibe cada bloque que se manda al dispositivo
        self._lock = threading.Lock()
        self._dev = None
        self._pend = None             # (fuente nueva o None, frame de inicio) a aplicar en el próximo callback
        self._fuente = None
        self._quiere = False          # True = sonando; False = en pausa
        self._gan = 0.0               # ganancia actual (rampa hacia 0 o 1)
        self.volumen = 1.0
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
            self._quiere = True

    def parar(self):
        self._quiere = False
        self.ruta = None
        self._terminada = False
        self._soltar_indice()
        self._poner(None, 0)

    def cerrar(self):
        """Detiene el dispositivo y libera lo abierto (al cerrar la aplicación)."""
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
            if ruta.lower().endswith(".mp3"):
                return float(MP3(ruta).info.length)
            return float(miniaudio.get_file_info(ruta).duration)
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
        return miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=FS,
                                     frames_to_read=1024, seek_frame=frame)

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
                                 output_format=F32, nchannels=2, sample_rate=FS, frames_to_read=1024)
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

    def _rampa(self, n, objetivo):
        """Ganancia de cada uno de n frames: de la actual al objetivo en FADE frames."""
        g = self._gan + (objetivo - self._gan) * np.minimum(np.arange(1, n + 1) / FADE, 1.0)
        self._gan = float(g[-1])
        return g.astype(np.float32)

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
        if self._fuente is not None and hecho < req:
            objetivo = 1.0 if self._quiere else 0.0
            quedan = req - hecho
            if objetivo == 0.0:                     # pausando: solo hace falta el fundido de salida
                quedan = min(quedan, int(round(self._gan * FADE)))
            if quedan > 0:
                x = _leer(self._fuente, quedan)
                if len(x):
                    x = x * self._rampa(len(x), objetivo)[:, None]
                    out[hecho:hecho + len(x)] = x
                    hecho += len(x)
                    self._ent_fuente += len(x)
                if len(x) < quedan:
                    self._fin_de_archivo()
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

class Player(QWidget):
    def __init__(self):
        super().__init__()
        # SIMPLEPLAY_AUDIO=null: dispositivo de audio simulado (para las pruebas, sin placa de sonido)
        nulo = os.environ.get("SIMPLEPLAY_AUDIO") == "null"
        self.motor = Motor(backend=miniaudio.Backend.NULL if nulo else None, parent=self)
        self.motor.fin_de_pista.connect(self._motor_fin)
        self.motor.error_dispositivo.connect(self._motor_error)
        self.motor.error_archivo.connect(self._motor_error_archivo)
        self._fallos = 0   # temas seguidos que no se pudieron reproducir (para no dar vueltas sin fin)
        self.setWindowTitle("simpleplay")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(ESTILO)

        self.pistas = []
        self.actual = -1
        self.pausado = False
        self.duracion = 0.0
        # espectro: lee del motor las muestras que están sonando; el nivel de referencia sale de los picos recientes
        self.picos = collections.deque(maxlen=HISTORIA)
        self.ref_suave = None   # nivel de referencia que usan las barras, suavizado
        self.pendiente = None  # (índice, segundo) de la sesión restaurada, aún sin sonar
        self.vaciada = False   # el usuario quitó todos los temas (hay que guardar la lista vacía)
        self.meta = {"titulo": "", "artista": "", "arte": ""}
        self.mpris = None
        self.datos = {}              # ruta -> datos_lista(ruta): nombre, artista, título, álbum, pista
        self.orden_original = []     # orden en que se agregaron (para volver con "Orden en que se agregaron")
        self.modo_orden = "original"
        self.repetir = "off"         # off | all | one
        self.carpeta_musica = ""     # última carpeta usada en los diálogos
        self.etiquetando = False  # la escoba está trabajando
        self.etiquetador = None
        self.lote_undo = None

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

        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(14, 14, 14, 16)
        cl.setSpacing(4)
        cl.addLayout(top)
        cl.addStretch()
        cl.addLayout(tiempos)
        cl.addWidget(self.linea)
        cl.addSpacing(6)
        cl.addLayout(botones)

        self.lista = QListWidget()
        self.lista.setFixedHeight(168)  # unas 5 filas
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lista.setTextElideMode(Qt.ElideRight)
        self.lista.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Ctrl/Shift para varios
        self.lista.setDragDropMode(QAbstractItemView.InternalMove)        # arrastrar para reordenar
        self.lista.setDefaultDropAction(Qt.MoveAction)
        self.lista.model().rowsMoved.connect(self._reordenado)
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
        self.btn_abrir = IconButton("plus", 32)
        self.btn_abrir.setToolTip(tr("Agregar archivos o una carpeta", "Add files or a folder"))
        self.btn_abrir.clicked.connect(self._menu_agregar)
        abajo = QHBoxLayout()
        abajo.setSpacing(8)
        abajo.addWidget(self.btn_orden, 0, Qt.AlignVCenter)
        if ESCOBA:
            self.btn_escoba.setFixedSize(28, 28)
            abajo.addWidget(self.btn_escoba, 0, Qt.AlignVCenter)
        abajo.addStretch()
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
        root.setContentsMargins(0, 0, 0, 0)
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
            self, tr("Abrir", "Open"), self._carpeta_inicial(), "MP3 (*.mp3)")
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
            self.guardar_estado()

    def _menu_agregar(self):
        menu = QMenu(self)
        menu.addAction(tr("Agregar archivos…", "Add files…"), self.abrir)
        menu.addAction(tr("Agregar una carpeta…", "Add a folder…"), self.abrir_carpeta)
        menu.exec(self.btn_abrir.mapToGlobal(QPoint(0, self.btn_abrir.height())))

    def agregar(self, archivos, mostrar=True, avisar=False):
        """Agrega mp3 (o carpetas, con sus subcarpetas) a la lista; los que ya estaban no se repiten."""
        primera = not self.pistas
        existentes = set(self.pistas)
        nuevos = [r for r in buscar_mp3(archivos) if r not in existentes]
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
        menu = QMenu(self)
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

    def quitar(self):
        """Quita de la lista los temas seleccionados (los archivos no se borran)."""
        filas = self.filas_elegidas()
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
        caja.setStyleSheet(ESTILO_DIALOGO)
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
        caja.setStyleSheet(ESTILO_DIALOGO)
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
        self.ref_suave = None
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

    def _preparar(self, i, pos):
        """Deja el tema i listo para dar play: en pausa, en la posición pos y sin sonar."""
        try:
            self.duracion = MP3(self.pistas[i]).info.length
        except Exception:
            self.duracion = 0.0
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
                 "carpeta": self.carpeta_musica, "orden_original": self.orden_original,
                 "compacto": self.compacto}
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
        self.poner_repetir(d.get("repetir", "off"))
        self.carpeta_musica = d.get("carpeta", "")
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
        self.pausado = False
        self.pendiente = None
        try:
            self.duracion = MP3(self.pistas[i]).info.length
        except Exception:
            self.duracion = 0.0
        self.motor.cargar(self.pistas[i])
        self.picos.clear()
        self.ref_suave = None
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
        ref = float(np.percentile(self.picos, 90))
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
            self.reproducir(random.choice([n for n in range(len(self.pistas)) if n != self.actual]))
        elif self.actual + 1 < len(self.pistas):
            self.reproducir(self.actual + 1)
        elif self.repetir == "all":
            self.reproducir(0)  # al final de la lista, vuelve al principio
        else:
            self.parar()

    def anterior(self, *_):
        if self.actual < 0:
            return
        # pasados 3 s vuelve al inicio de la pista, si no, a la anterior
        if self.posicion() > 3:
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
        if pos > 2.0:
            self._fallos = 0   # un tema sonó de verdad: se acaba la racha de fallos

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
        menu = QMenu(self)
        menu.addAction(f"simpleplay v{VERSION}").setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Abrir archivos…", "Open files…"), self.abrir)
        menu.addAction(tr("Abrir carpeta…", "Open folder…"), self.abrir_carpeta)
        menu.addAction(tr("Modo normal", "Normal mode") if self.compacto else tr("Modo compacto", "Compact mode"),
                       lambda: self.poner_compacto(not self.compacto))
        menu.addAction(tr("Cerrar", "Close"), self.close)
        menu.exec(e.globalPos())


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        resto = [a for a in sys.argv[1:] if a != "--diagnose"]
        sys.exit(diagnosticar(resto[0]) if resto else print("uso: simpleplay.py --diagnose archivo.mp3") or 2)
    app = QApplication(sys.argv)
    app.setApplicationName("simpleplay")
    app.setDesktopFileName("simpleplay")  # Wayland: une la ventana con su .desktop e ícono
    app.setWindowIcon(QIcon(recurso("icon/simpleplay-256.png")))
    w = Player()
    args = buscar_mp3([a for a in sys.argv[1:] if not a.startswith("-")])  # archivos o carpetas
    w.restaurar(con_pistas=not args)  # con archivos por parámetro, solo se recuerdan shuffle, repetir y carpeta
    w.agregar(args)
    w.show()
    sys.exit(app.exec())
