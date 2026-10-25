# simpleplay - limpieza.py
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor para ordenar una carpeta de música: encuentra los temas repetidos y elige la versión de mejor calidad.

No depende del reproductor ni de Qt (solo de `mutagen` y, para reconocer por sonido, del programa `fpcalc` de Chromaprint):
lo usan la línea de comandos (`tools/quitar_duplicados.py`) y, más adelante, una pantalla del reproductor.

Dos archivos son el mismo tema si se cumple CUALQUIERA de estas dos cosas, y siempre que no se contradigan en lo que dicen
sus títulos ("remix", "live", "acústico", "instrumental"...):

* por nombre: coinciden artista y título (de las etiquetas o del nombre del archivo, sin "(Official Video)", "[id]",
  "feat."...) y la duración difiere menos de TOLERANCIA_S;
* por sonido: la huella acústica de los primeros minutos es casi la misma (aunque cambien el formato, la tasa de bits o
  el nombre del archivo). Se compara con un pequeño desfase, porque cada codificador agrega algo de silencio al principio.

Entre las copias se queda la de mejor calidad: sin pérdida (FLAC, WAV, ALAC) antes que con pérdida; entre las que no
tienen pérdida, la de más profundidad y frecuencia de muestreo; entre las otras, la de más bits por segundo (un AAC u
Opus cuenta más que un mp3 del mismo número). Si empatan, la que tiene etiquetas y portada, y luego la más grande.

Nada se borra acá: `revisar` devuelve un plan y `quitar` lo ejecuta (papelera por defecto)."""
import difflib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mutagen import File as MutagenFile

try:                     # solo para medir el corte de frecuencias; sin ellos la calidad se juzga por la tasa de bits
    import miniaudio
    import numpy as np
except ImportError:      # pragma: no cover
    miniaudio = np = None

EXTENSIONES = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".aiff", ".aif"}
TOLERANCIA_S = 3.0          # por nombre: diferencia de duración permitida
TOLERANCIA_SONIDO_S = 5.0   # por sonido: dos ediciones del mismo master pueden diferir un poco más (silencio final)
HUELLA_S = 120              # cuánto del tema se huella (segundos desde el principio)
DESFASE_MAX = 24            # cuadros de huella (~0,12 s cada uno) que se prueban hacia cada lado al comparar
UMBRAL_SONIDO = 0.78        # parecido mínimo (0-1; 1 = idénticas bit a bit) para decir "es el mismo sonido"
SOLAPE_MIN = 0.6            # fracción mínima de la huella más corta que tiene que haberse comparado
SALTO_MIN_DB = 12           # caída mínima (en 500 Hz) para decir que el audio tiene un corte de frecuencias
# a qué tasa de un mp3 corresponde cada corte: un mp3 de 128 kbps no pasa de ~16 kHz, uno de 192 llega a ~19 kHz
CORTE_A_KBPS = [(11000, 64), (14000, 96), (16500, 128), (17500, 160), (19500, 192), (20500, 256), (21500, 320)]
# cuánto "rinde" un bit por segundo según el códec, comparado con el mp3
EFICIENCIA = {"mp3": 1.0, "aac": 1.25, "m4a": 1.25, "ogg": 1.25, "opus": 1.5}


# ---------------------------------------------------------------- nombres
RUIDO = re.compile(r"official|oficial|video|audio|lyrics?|letra|\bhd\b|4k|1080p|720p|visuali[sz]er|\bmv\b|"
                   r"videoclip|clip|full album|\bhq\b|remaster", re.I)
_INDICE = re.compile(r"^\s*\d{1,4}\s*[-–.)]\s+")   # "391 - ", "12. ", "07) ": el número de orden de una lista descargada
# lo que cambia el tema aunque el nombre sea el mismo: un remix o una versión en vivo NO es un repetido
_VARIANTE = re.compile(r"remix|\bmix\b|live|en vivo|ac[uú]stic|unplugged|instrumental|karaoke|cover|\bedit\b|demo|"
                       r"sesi[oó]n|session|extended|radio|version|versi[oó]n|slowed|sped up|speed up|nightcore|reverb|chopped|8d\b|bass boost", re.I)


def limpiar_nombre(texto):
    """Quita lo que sobra de un título bajado de YouTube: (Official Video), [id], '- Topic'..."""
    t = unicodedata.normalize("NFKC", texto or "").replace("⧸", "/")
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\([^)]*\)", lambda m: "" if RUIDO.search(m.group(0)) else m.group(0), t)
    t = re.sub(r"\s*[-–—|]\s*(topic|vevo)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+(official|oficial)(\s+(music|video|audio|lyrics?|hd|4k|videoclip))*\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -–—|")


def sin_feat(titulo):
    """El título sin '(feat. ...)' / 'ft. ...'."""
    t = re.sub(r"\s*[\(\[]\s*(feat|ft|con|with)\b[^)\]]*[\)\]]", "", titulo, flags=re.I)
    t = re.sub(r"\s+(feat|ft)\.?\s.*$", "", t, flags=re.I)
    return t.strip()


def candidatos(ruta, titulo_tag, artista_tag):
    """Posibles (artista, título) del tema, de lo más a lo menos probable, con etiquetas y nombre de archivo."""
    nombre, tit, art = limpiar_nombre(Path(ruta).stem), limpiar_nombre(titulo_tag), limpiar_nombre(artista_tag)
    sin_n = _INDICE.sub("", nombre)
    bases = [tit, sin_n] + ([nombre] if sin_n != nombre and " - " not in sin_n else [])
    out, invertidos = [], []
    for base in bases:
        if " - " in base:
            a, t = (limpiar_nombre(x) for x in base.split(" - ", 1))
            out.append((a, t))
            invertidos.append((t, a))
    if art and tit:
        out.append((art, tit))
    if art and nombre and " - " not in sin_n:
        out.append((art, sin_n))
    vistos, res = set(), []
    for a, t in out + invertidos:
        if "|" in a + t or len(a) > 60 or len(t) > 90:
            continue
        if re.search(r'[()"]', a) or t.count("_") >= 2:
            continue
        if a and t and (a.lower(), t.lower()) not in vistos:
            vistos.add((a.lower(), t.lower()))
            res.append((a, t))
    return res


def _norm(t):
    t = unicodedata.normalize("NFKD", (t or "").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def parecido(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _clave_titulo(t):
    """Título para comparar: sin acentos ni mayúsculas ni signos, pero CON lo que dicen los paréntesis (remix, live...)."""
    t = unicodedata.normalize("NFKD", sin_feat(limpiar_nombre(t)).casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _primer_artista(a):
    a = re.split(r"\s+(?:feat|ft|featuring|with|con|x|&|y)\.?\s+|,|;|/", sin_feat(limpiar_nombre(a)), maxsplit=1, flags=re.I)[0]
    return a.strip()


def _variantes(d):
    """Las marcas de versión que dicen el título, las etiquetas y el nombre del archivo ('live', 'remix'...)."""
    texto = " ".join([d["tit"], Path(d["ruta"]).stem])
    texto = re.sub(r"\[[^\]]*\]", " ", texto)
    texto = re.sub(r"\([^)]*\)", lambda m: "" if RUIDO.search(m.group(0)) and not _VARIANTE.search(m.group(0)) else m.group(0), texto)
    return {m.group(0).lower().replace("ú", "u").replace("ó", "o") for m in _VARIANTE.finditer(texto)}


# ---------------------------------------------------------------- lectura de archivos
def leer(ruta):
    """Lo que hace falta de un archivo para compararlo -> dict, o None si no es audio legible."""
    try:
        f = MutagenFile(ruta)
        if f is None or not getattr(f, "info", None):
            return None
        fac = MutagenFile(ruta, easy=True)
    except Exception:
        return None
    etq = (fac.tags if fac is not None and fac.tags else {}) or {}
    tit = (etq.get("title") or [""])[0]
    art = (etq.get("artist") or [""])[0]
    ext = Path(ruta).suffix.lower().lstrip(".")
    codec = getattr(f.info, "codec", "") or ""
    sin_perdida = ext in ("flac", "wav", "aiff", "aif") or codec == "alac"
    bits = getattr(f.info, "bits_per_sample", 0) or 0
    hz = getattr(f.info, "sample_rate", 0) or 0
    kbps = (getattr(f.info, "bitrate", 0) or 0) / 1000
    if not kbps and f.info.length:                       # Opus y algún otro formato no informan la tasa: se calcula
        kbps = Path(ruta).stat().st_size * 8 / f.info.length / 1000
    if sin_perdida:
        calidad = (1, bits * hz, 0)
        desc = f"{ext.upper() if codec != 'alac' else 'ALAC'} {hz / 1000:g} kHz {bits} bit"
    else:
        calidad = (0, kbps * EFICIENCIA.get(ext if ext != "m4a" else "aac", 1.0), 0)
        desc = f"{ext.upper()} {kbps:.0f} kbps"
    tiene_etq = bool(tit and art)
    claves = [str(k) for k in (f.tags or {})]
    tiene_portada = bool(getattr(f, "pictures", None) or any(k.startswith(("APIC", "covr")) for k in claves))
    st = Path(ruta).stat()
    return {"ruta": Path(ruta), "duracion": float(f.info.length), "desc": desc, "calidad": calidad,
            "tags": (tiene_etq, tiene_portada), "tam": st.st_size, "mtime": st.st_mtime_ns, "tit": tit, "art": art}


def _llaves(d):
    """Pares (artista, título) con los que se puede identificar el tema por nombre, normalizados."""
    out = set()
    for a, t in candidatos(str(d["ruta"]), d["tit"], d["art"]):
        a2, t2 = _primer_artista(a), _clave_titulo(t)
        if a2 and t2:
            out.add((a2, t2))
    return out


# ---------------------------------------------------------------- calidad real (corte de frecuencias)
def corte_de(ruta, seg=15):
    """Hasta qué frecuencia (Hz) llega realmente el audio: un mp3 hecho de otro de baja tasa sigue diciendo 192 kbps pero
    se corta mucho antes. Mide 15 s del medio del tema. Devuelve 22050 si no hay corte, o None si no se pudo medir."""
    if miniaudio is None:
        return None
    try:
        sr = 44100
        info = miniaudio.get_file_info(str(ruta))
        total = info.num_frames * sr // info.sample_rate
        ini = int(total * 0.3) if total > sr * seg * 3 else 0
        gen = miniaudio.stream_file(str(ruta), output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1, sample_rate=sr,
                                    frames_to_read=sr * seg, seek_frame=ini * info.sample_rate // sr)
        x = np.asarray(next(gen), dtype=np.float32)
        n = 4096
        k = len(x) // n
        if k < 4:
            return None
        p = (np.abs(np.fft.rfft(x[:k * n].reshape(k, n) * np.hanning(n), axis=1)) ** 2).mean(0)
        db = 10 * np.log10(p + 1e-20)
        f = np.fft.rfftfreq(n, 1 / sr)
        paso = 250.0
        centros = np.arange(8000, 21500, paso)
        nivel = np.array([db[(f >= c) & (f < c + 500)].mean() for c in centros])
        saltos = nivel[:-2] - nivel[2:]                      # cuánto cae el nivel en los siguientes 500 Hz
        i = int(saltos.argmax())
        return int(centros[i] + 500) if saltos[i] >= SALTO_MIN_DB else 22050
    except Exception:
        return None


def kbps_por_corte(hz):
    pts = CORTE_A_KBPS
    if hz <= pts[0][0]:
        return pts[0][1]
    for (h1, k1), (h2, k2) in zip(pts, pts[1:]):
        if hz <= h2:
            return k1 + (k2 - k1) * (hz - h1) / (h2 - h1)
    return pts[-1][1] + 64


def refinar_calidad(grupo, cache):
    """Corrige la calidad de cada copia con lo que realmente llega el audio. Un mp3 no puede valer más que lo que su corte
    permite, y un FLAC que se corta a 16 kHz es un mp3 convertido: pasa a valer como tal."""
    for d in grupo:
        hz = cache.corte(d)
        if hz is None:
            continue
        d["corte_hz"] = hz
        sin_perdida = d["calidad"][0] == 1
        if sin_perdida and hz < 19500:                  # un CD de verdad llega a 20 kHz o más
            d["calidad"] = (0, kbps_por_corte(hz), 0)
            d["desc"] += f" (corte {hz / 1000:.1f} kHz: parece venir de un mp3)"
        elif not sin_perdida:
            d["calidad"] = (0, min(d["calidad"][1], kbps_por_corte(hz)), 0)
            d["desc"] += f" (corte {hz / 1000:.1f} kHz)" if hz < 22050 else ""


# ---------------------------------------------------------------- huella acústica
def hay_fpcalc():
    return shutil.which("fpcalc") is not None


def _huella_de(ruta):
    """Huella cruda (lista de enteros de 32 bits, ~8 por segundo) de los primeros HUELLA_S segundos, o None."""
    try:
        r = subprocess.run(["fpcalc", "-raw", "-json", "-length", str(HUELLA_S), str(ruta)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None
        h = json.loads(r.stdout).get("fingerprint")
        return [int(x) & 0xFFFFFFFF for x in h] if h else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class Cache:
    """Guarda las huellas ya calculadas (por ruta, tamaño y fecha) para no repetir el trabajo en la próxima limpieza."""

    def __init__(self, ruta=None):
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.ruta = Path(ruta) if ruta else base / "simpleplay" / "huellas.json"
        try:
            self.datos = json.loads(self.ruta.read_text())
        except (OSError, ValueError):
            self.datos = {}
        self.cambios = False

    def huella(self, d):
        clave = f"{d['ruta']}|{d['tam']}|{d['mtime']}"
        if clave not in self.datos:
            h = _huella_de(d["ruta"])
            if h is None:
                return None
            self.datos[clave] = h
            self.cambios = True
        return self.datos[clave]

    def corte(self, d):
        clave = f"corte|{d['ruta']}|{d['tam']}|{d['mtime']}"
        if clave not in self.datos:
            hz = corte_de(d["ruta"])
            if hz is None:
                return None
            self.datos[clave] = hz
            self.cambios = True
        return self.datos[clave]

    def guardar(self):
        if not self.cambios:
            return
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.ruta.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.datos))
            os.replace(tmp, self.ruta)
        except OSError:
            pass


def parecido_huellas(a, b):
    """0-1: qué tanto se parecen dos huellas, probando pequeños desfases. 1 = idénticas; dos temas distintos dan ~0,5."""
    if not a or not b:
        return 0.0
    corta = min(len(a), len(b))
    mejor = 0.0
    for desfase in range(-DESFASE_MAX, DESFASE_MAX + 1):
        ini_a, ini_b = (desfase, 0) if desfase >= 0 else (0, -desfase)
        n = min(len(a) - ini_a, len(b) - ini_b)
        if n < corta * SOLAPE_MIN:
            continue
        bits = sum((x ^ y).bit_count() for x, y in zip(a[ini_a:ini_a + n], b[ini_b:ini_b + n]))
        mejor = max(mejor, 1.0 - bits / (32.0 * n))
    return mejor


# ---------------------------------------------------------------- agrupar
def _mismo_nombre(d1, d2, l1, l2):
    if abs(d1["duracion"] - d2["duracion"]) > TOLERANCIA_S:
        return False
    return any(t1 == t2 and parecido(a1, a2) >= 0.85 for a1, t1 in l1 for a2, t2 in l2)


def agrupar(archivos, sonido=True, nombre=True, cache=None, progreso=None, hilos=4):
    """Grupos de 2 o más archivos que son el mismo tema -> lista de listas de dicts (de `leer`).

    Cada dict del grupo lleva "motivo": cómo se supo ("nombre" o "sonido NN %"). `progreso(hecho, total)` se llama al ir
    leyendo los archivos y al ir huellándolos."""
    archivos = list(archivos)
    datos = []
    for i, r in enumerate(archivos):
        d = leer(r)
        if d:
            datos.append(d)
        if progreso:
            progreso(i + 1, len(archivos))
    sonido = sonido and hay_fpcalc()
    llaves = [_llaves(d) if nombre else set() for d in datos]
    variantes = [_variantes(d) for d in datos]
    orden = sorted(range(len(datos)), key=lambda i: datos[i]["duracion"])
    padre = list(range(len(datos)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def unir(i, j, motivo):
        ri, rj = raiz(i), raiz(j)
        if ri != rj:
            padre[ri] = rj
        for k in (i, j):
            datos[k].setdefault("motivo", motivo)

    por_sonido = []     # pares que el nombre no resolvió y que por duración podrían ser lo mismo
    for pos, i in enumerate(orden):
        for j in orden[pos + 1:]:
            dur = datos[j]["duracion"] - datos[i]["duracion"]
            if dur > (TOLERANCIA_SONIDO_S if sonido else TOLERANCIA_S):
                break
            if variantes[i] != variantes[j]:
                continue            # uno dice "live" o "remix" y el otro no: son temas distintos
            if nombre and llaves[i] and llaves[j] and _mismo_nombre(datos[i], datos[j], llaves[i], llaves[j]):
                unir(i, j, "nombre")
            elif sonido:
                por_sonido.append((i, j))
    if sonido and por_sonido:
        cache = cache or Cache()
        necesarios = sorted({k for par in por_sonido for k in par if raiz(par[0]) != raiz(par[1])})
        huellas = {}
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            for n, (k, h) in enumerate(zip(necesarios, ex.map(lambda k: cache.huella(datos[k]), necesarios)), 1):
                huellas[k] = h
                if progreso:
                    progreso(n, len(necesarios))
        cache.guardar()
        for i, j in por_sonido:
            if raiz(i) == raiz(j):
                continue
            p = parecido_huellas(huellas.get(i), huellas.get(j))
            if p >= UMBRAL_SONIDO:
                unir(i, j, f"sonido {p * 100:.0f} %")
    grupos = {}
    for i in range(len(datos)):
        grupos.setdefault(raiz(i), []).append(datos[i])
    return [g for g in grupos.values() if len(g) > 1]


def mejor_primero(grupo):
    """El grupo ordenado de mejor a peor: calidad de audio, luego etiquetas/portada, luego tamaño y por último la ruta más corta."""
    return sorted(grupo, key=lambda d: (d["calidad"], d["tags"], d["tam"], -len(str(d["ruta"]))), reverse=True)


# ---------------------------------------------------------------- plan y ejecución
def archivos_de(carpeta):
    return sorted(p for p in Path(carpeta).rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES)


def revisar(carpeta, limite=None, calidad_real=True, cache=None, **opciones):
    """-> (cantidad de archivos, grupos ordenados mejor primero, rutas a quitar). No toca nada."""
    archivos = archivos_de(carpeta)
    if limite:
        archivos = archivos[:limite]
    cache = cache or Cache()
    grupos = agrupar(archivos, cache=cache, **opciones)
    if calidad_real:
        for g in grupos:
            refinar_calidad(g, cache)
        cache.guardar()
    grupos = [mejor_primero(g) for g in grupos]
    return len(archivos), grupos, [d["ruta"] for g in grupos for d in g[1:]]


def mandar_a_papelera(ruta):
    r = subprocess.run(["gio", "trash", str(ruta)], capture_output=True, text=True)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "gio trash falló")


def quitar(rutas, definitivo=False, aviso=print):
    hechos = 0
    for r in rutas:
        try:
            os.remove(r) if definitivo else mandar_a_papelera(r)
            hechos += 1
        except OSError as e:
            aviso(f"  no se pudo quitar {Path(r).name}: {e}")
    return hechos
