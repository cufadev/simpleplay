# simpleplay - a small, clean mp3 player
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
import contextlib
import difflib
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

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # sin el cartel de bienvenida
import pygame
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TDRC, APIC
from mutagen.mp3 import MP3
from PySide6.QtCore import (Qt, QTimer, QRectF, QPointF, QSize, Signal, QLocale, QUrl, QObject,
                            ClassInfo, Property, Slot, QMetaType,
                            QStandardPaths, QVariantAnimation, QEasingCurve)
from PySide6.QtGui import (QShortcut, QKeySequence, QIcon, QFont, QFontMetrics, QPainter, QColor, QPixmap, QImage, QLinearGradient,
                           QPainterPath, QPolygonF, QPen)
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QSlider, QAbstractButton, QListWidget,
                               QFileDialog, QFrame, QLayout, QMenu, QSizePolicy,
                               QStackedLayout, QGraphicsOpacityEffect, QMessageBox,
                               QAbstractItemView)

try:
    from PySide6.QtDBus import (QDBusConnection, QDBusAbstractAdaptor, QDBusObjectPath,
                                QDBusMessage, QDBusArgument)
    HAY_DBUS = True
except ImportError:  # sin QtDBus no hay teclas multimedia; el resto anda igual
    HAY_DBUS = False

VERSION = "1.1"
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
@contextlib.contextmanager
def sin_stderr():
    """Silencia stderr a nivel de descriptor mientras dura el bloque.

    libmpg123 (dentro de SDL_mixer) imprime "No comment text / valid description?" por cada
    etiqueta ID3 de comentario mal formada, algo común en mp3 bajados con yt-dlp. Es solo una
    advertencia, pero sale por C, así que hay que redirigir el descriptor 2.

    Si no hay stderr (un .exe sin consola en Windows, pythonw), no hay nada que silenciar y se sigue.
    """
    try:
        sys.stderr.flush()
        guardado = os.dup(2)
    except (OSError, AttributeError, ValueError):
        yield
        return
    try:
        nulo = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        os.close(guardado)
        yield
        return
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


DEBUG = bool(os.environ.get("SIMPLEPLAY_DEBUG"))


def log(*partes):
    """Mensajes de diagnóstico: solo se ven con SIMPLEPLAY_DEBUG=1."""
    if DEBUG:
        print("[simpleplay]", *partes, file=sys.stderr, flush=True)


# --- análisis de audio para el espectro ---
SR = 22050       # muestreo del análisis (basta para ver hasta ~10 kHz)
VENTANA = 1024   # ≈ 46 ms
TRAMO = 40       # segundos que se decodifican por pedido
BANDAS = 24
RANGO_DB = 36    # cuántos dB bajo el nivel de referencia del tema separan una barra vacía de una llena
_BORDES = np.geomspace(50, 10000, BANDAS + 1)
_HANN = np.hanning(VENTANA)


def entorno_del_sistema():
    """Entorno para lanzar programas del sistema (ffmpeg) desde dentro del AppImage.

    PyInstaller apunta LD_LIBRARY_PATH a las librerías del paquete, y esas rompen a los programas
    del sistema (ffmpeg devolvía 0 s de audio). Se les devuelve el valor original.
    """
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        env.pop("LD_LIBRARY_PATH", None)
        if original is not None:
            env["LD_LIBRARY_PATH"] = original
    return env


def tramo_ffmpeg(ruta, inicio):
    out = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-ss", f"{inicio:.2f}", "-i", ruta,
         "-t", str(TRAMO), "-vn", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True, timeout=20, env=entorno_del_sistema(),
        **({"creationflags": 0x08000000} if os.name == "nt" else {})).stdout  # sin ventana de consola en Windows
    return np.frombuffer(out[:len(out) // 2 * 2], np.int16)


def tramo_miniaudio(ruta, inicio):
    # decodificador incluido en el paquete: no depende de nada instalado en el sistema
    # (seek_frame cuenta en cuadros de la frecuencia de salida)
    import miniaudio
    gen = miniaudio.stream_file(
        ruta, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
        sample_rate=SR, frames_to_read=SR, seek_frame=int(inicio * SR))
    bloques, n = [], 0
    for b in gen:
        bloques.append(np.frombuffer(b, np.int16))
        n += len(bloques[-1])
        if n >= TRAMO * SR:
            break
    return np.concatenate(bloques) if bloques else np.zeros(0, np.int16)


def tramo(ruta, inicio):
    """Decodifica ~TRAMO s desde `inicio` -> (muestras, método).

    Usa ffmpeg si está (salta más rápido dentro de archivos enormes) y, si no está o falla
    o devuelve audio vacío, el decodificador miniaudio incluido. Si ninguno sirve, levanta
    un error que explica qué pasó con cada uno.
    """
    errores = []
    if shutil.which("ffmpeg"):
        try:
            m = tramo_ffmpeg(ruta, inicio)
            if len(m) > VENTANA:
                return m, "ffmpeg"
            errores.append("ffmpeg devolvió audio vacío")
        except Exception as e:
            errores.append(f"ffmpeg: {e!r}")
    try:
        m = tramo_miniaudio(ruta, inicio)
        if len(m) > VENTANA:
            return m, "miniaudio"
        errores.append("miniaudio devolvió audio vacío")
    except Exception as e:
        errores.append(f"miniaudio: {e!r}")
    raise RuntimeError("; ".join(errores))


def bandas_db(v):
    """Nivel en dB de cada banda (escala log) para una ventana de VENTANA muestras."""
    mag = np.abs(np.fft.rfft(v / 32768.0 * _HANN)) / (VENTANA / 4)  # senoidal a fondo ≈ 1.0
    res = SR / VENTANA
    out = np.empty(BANDAS)
    for k in range(BANDAS):
        a, b = _BORDES[k], _BORDES[k + 1]
        lo = int(a / res)
        hi = max(int(b / res), lo + 1)
        # la segunda parte compensa la caída natural de los agudos en la música
        out[k] = 20 * math.log10(mag[lo:hi].max() + 1e-9) + 3 * math.log2(math.sqrt(a * b) / 100)
    return out


def nivel_referencia(m):
    """Nivel (dB) de los momentos fuertes de un tramo.

    Las barras se miden contra este nivel, así un tema suave usa todo el rango igual que uno
    fuerte, en vez de quedar casi planas.
    """
    picos = [bandas_db(m[i:i + VENTANA]).max() for i in range(0, len(m) - VENTANA, SR // 4)]
    return float(np.percentile(picos, 90)) if picos else -20.0


def diagnosticar(ruta):
    """`simpleplay.py --diagnose archivo.mp3`: prueba la decodificación del espectro sin abrir la ventana."""
    print(f"simpleplay {VERSION} - Python {sys.version.split()[0]}")
    print("archivo:", ruta)
    print("ffmpeg:", shutil.which("ffmpeg") or "no está instalado (se usa miniaudio)")
    mejor = None
    for nombre, fn in (("ffmpeg", tramo_ffmpeg), ("miniaudio", tramo_miniaudio)):
        if nombre == "ffmpeg" and not shutil.which("ffmpeg"):
            continue
        t0 = time.time()
        try:
            m = fn(ruta, 5.0)
            rms = float(np.sqrt(np.mean(m.astype(float) ** 2))) if len(m) else 0.0
            print(f"{nombre}: {len(m) / SR:.1f} s de audio en {time.time() - t0:.2f} s, nivel RMS {rms:.0f}")
            if len(m) > VENTANA and mejor is None:
                mejor = m
        except Exception as e:
            print(f"{nombre}: ERROR {e!r}")
    if mejor is None:
        print("resultado: NO se pudo decodificar; las barras del espectro quedarían planas")
        return 1
    ref = nivel_referencia(mejor)
    db = bandas_db(mejor[SR:SR + VENTANA])
    vals = np.clip((db - (ref - RANGO_DB)) / RANGO_DB, 0, 1)
    print("espectro de ejemplo:", "".join(" ▁▂▃▄▅▆▇█"[int(round(v * 8))] for v in vals), f"(referencia {ref:.1f} dB)")
    print("resultado: el espectro debería funcionar")
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
            a, t = base.split(" - ", 1)
            out.append((a.strip(), t.strip()))
            invertidos.append((t.strip(), a.strip()))  # por si el archivo dice "Título - Artista"
    if art and tit:
        out.append((art, tit))
    if art and nombre and " - " not in nombre:
        out.append((art, nombre))
    vistos, res = set(), []
    for a, t in out + invertidos:
        if "|" in a + t or len(a) > 60 or len(t) > 90:
            continue  # parece un mix o una lista de temas, no un tema: no se adivina
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

        PlaybackStatus = Property(str, lambda s: s.p.mpris_estado())
        Metadata = Property("QVariantMap", lambda s: s.p.mpris_metadata())
        Position = Property("qlonglong", lambda s: s.p.mpris_posicion())
        Rate = Property(float, lambda s: 1.0)
        MinimumRate = Property(float, lambda s: 1.0)
        MaximumRate = Property(float, lambda s: 1.0)
        Volume = Property(float, lambda s: 1.0)  # el volumen lo maneja el sistema
        Shuffle = Property(bool, lambda s: s.p.btn_shuffle.isChecked(), _poner_shuffle)
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

        def cerrar(self):
            if self.activo:
                self.bus.unregisterObject(self.RUTA)
                self.bus.unregisterService(self.nombre)
                self.activo = False


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
        # espectro: se decodifica solo un tramo alrededor de la posición
        self.token = 0
        self.chunk = None  # (token, inicio_seg, muestras mono int16, nivel de referencia dB)
        self.pidiendo = False
        self.fallo_hasta = 0.0  # tras un fallo de decodificación, no reintentar hasta este instante
        self.ref_suave = None   # nivel de referencia que usan las barras, suavizado entre tramos
        self.pendiente = None  # (índice, segundo) de la sesión restaurada, aún sin sonar
        self.vaciada = False   # el usuario quitó todos los temas (hay que guardar la lista vacía)
        self.meta = {"titulo": "", "artista": "", "arte": ""}
        self.mpris = None
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
        self.btn_escoba = IconButton("broom", 30)
        self.btn_escoba.setToolTip(tr("Buscar y completar los datos del tema (de los seleccionados)",
                                      "Look up and fill in the track info (for the selected tracks)"))
        self.btn_escoba.clicked.connect(self.limpiar_etiquetas)

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
        if ESCOBA:
            botones.addWidget(self.btn_escoba)  # mismo ancho que el shuffle: los 3 botones quedan centrados
        else:
            self.btn_escoba.setParent(self)
            self.btn_escoba.hide()
            botones.addSpacing(30)  # el mismo hueco, para que los 3 botones sigan centrados
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
        self.lista.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Ctrl/Shift para varios
        self.btn_quitar = IconButton("minus", 36)
        self.btn_quitar.setToolTip(tr("Quitar el tema seleccionado", "Remove the selected track"))
        self.btn_quitar.clicked.connect(self.quitar)
        self.btn_abrir = IconButton("plus", 36)
        self.btn_abrir.setToolTip(tr("Agregar temas", "Add tracks"))
        self.btn_abrir.clicked.connect(self.abrir)
        abajo = QHBoxLayout()
        abajo.setSpacing(8)
        abajo.addStretch()
        abajo.addWidget(self.btn_quitar)
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

        # atajos de teclado (con QShortcut mandan sobre el widget que tenga el foco)
        for tecla, accion in ((QKeySequence(Qt.Key_Space), self.play_pausa),
                              (QKeySequence(Qt.Key_Escape), self.close),
                              (QKeySequence(Qt.Key_Left), lambda: self.saltar_rel(-5)),
                              (QKeySequence(Qt.Key_Right), lambda: self.saltar_rel(5)),
                              (QKeySequence(Qt.Key_N), self.siguiente),
                              (QKeySequence(Qt.Key_P), self.anterior),
                              (QKeySequence(Qt.Key_Delete), self.quitar),
                              (QKeySequence(QKeySequence.Open), self.abrir)):
            QShortcut(tecla, self).activated.connect(accion)

        if HAY_DBUS and not os.environ.get("SIMPLEPLAY_NO_MPRIS"):
            self.mpris = Mpris(self)

    # --- teclas multimedia (MPRIS) ---
    def mpris_cambio(self, *claves):
        if self.mpris:
            self.mpris.actualizar(*claves)

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
        if archivos:
            self.vaciada = False
        if primera and self.pistas:
            self.lista.setCurrentRow(0)
            if mostrar:
                self.mostrar_meta(0)
        self.mpris_cambio("CanGoNext", "CanGoPrevious", "CanPlay")

    def filas_elegidas(self):
        """Filas seleccionadas en la lista; si no hay, la fila marcada."""
        filas = {self.lista.row(it) for it in self.lista.selectedItems()}
        if not filas and self.lista.currentRow() >= 0:
            filas = {self.lista.currentRow()}
        return sorted(i for i in filas if 0 <= i < len(self.pistas))

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
        if not self.pistas:
            self.vaciar()
        elif actual_quitado or pend_quitado:
            nuevo = min(filas[0], len(self.pistas) - 1)  # sigue el que ocupó su lugar
            if sonaba:
                self.reproducir(nuevo)
            else:
                pygame.mixer.music.stop()
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
        pygame.mixer.music.stop()
        self.actual = -1
        self.pausado = False
        self.pendiente = None
        self.duracion = 0.0
        self.chunk = None
        self.token += 1
        self.vaciada = True
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
        self._preparar(i, float(d.get("pos", 0)) if guardada in pistas else 0.0)
        self.mpris_cambio("Metadata", "PlaybackStatus", "CanSeek")

    def closeEvent(self, e):
        self.guardar_estado()
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
        self.ref_suave = None
        self.fallo_hasta = 0.0
        self.pedir_tramo(0.0)
        self.lista.setCurrentRow(i)
        self.mostrar_meta(i)
        self.icono_play()
        self.guardar_estado()

    def pedir_tramo(self, inicio):
        if self.pidiendo or time.monotonic() < self.fallo_hasta:
            return
        self.pidiendo = True
        threading.Thread(target=self._decodificar,
                         args=(self.pistas[self.actual], self.token, max(inicio, 0.0)),
                         daemon=True).start()

    def _decodificar(self, ruta, token, inicio):
        try:
            m, metodo = tramo(ruta, inicio)
            ref = nivel_referencia(m)
            log(f"tramo de {len(m) / SR:.0f} s desde {inicio:.0f} s con {metodo}, referencia {ref:.1f} dB")
            if token == self.token:
                self.chunk = (token, inicio, m, ref)
            self.fallo_hasta = 0.0
        except Exception as e:
            log("no se pudo decodificar el tramo:", e)
            self.fallo_hasta = time.monotonic() + 3  # no martillar: reintentar en unos segundos
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
        """BANDAS valores 0..1 con la energía por banda en este instante (escala log, autoajustada)."""
        if self.actual < 0 or self.pausado:
            return [0.0] * n
        pos = self.posicion()
        v = None
        if self.chunk and self.chunk[0] == self.token:
            _, ini, m, ref = self.chunk
            i = int((pos - ini) * SR)
            if 0 <= i and i + VENTANA <= len(m):
                v = m[i:i + VENTANA]
            fin = ini + len(m) / SR
            if fin - pos < 8 and fin < self.duracion - 1:
                self.pedir_tramo(pos)  # se acerca el final del tramo: pedir el siguiente a tiempo
        if v is None:
            if pos < self.duracion - 1:
                self.pedir_tramo(pos)  # pista nueva o salto: el tramo actual no cubre pos
            if self.pidiendo:  # llega en un instante: leve movimiento en vez de barras planas
                t = time.monotonic() * 3
                return [0.12 + 0.08 * math.sin(t + k * 0.7) for k in range(n)]
            return [0.0] * n   # sin datos (p. ej. falló la decodificación): barras planas, no un engaño
        self.ref_suave = ref if self.ref_suave is None else self.ref_suave + (ref - self.ref_suave) * 0.08
        db = bandas_db(v)
        return [float(x) for x in np.clip((db - (self.ref_suave - RANGO_DB)) / RANGO_DB, 0.0, 1.0)]

    def icono_play(self):
        self.btn_play.set_kind("pause" if (self.actual >= 0 and not self.pausado) else "play")
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


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        resto = [a for a in sys.argv[1:] if a != "--diagnose"]
        sys.exit(diagnosticar(resto[0]) if resto else print("uso: simpleplay.py --diagnose archivo.mp3") or 2)
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
