#!/usr/bin/env python3
# simpleplay - quitar_duplicados.py
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Encuentra los temas repetidos de una carpeta y se queda siempre con la versión de mejor calidad de audio.

Dos archivos son el mismo tema si coinciden el artista y el título (leídos de las etiquetas o del nombre del archivo,
sin "(Official Video)", "[id]", "feat." ...) y su duración difiere menos de 3 segundos. Un remix, una versión en vivo
o una acústica NO se toman como repetidos: su paréntesis hace que el título sea otro.

Entre las copias se queda la de mejor calidad: sin pérdida (FLAC, WAV, ALAC) antes que con pérdida; entre las que no
tienen pérdida, la de más profundidad y frecuencia de muestreo; entre las otras, la de más bits por segundo (un AAC u
Opus cuenta más que un mp3 del mismo número). Si empatan, la que tiene etiquetas y portada, y luego la más grande.

Uso (desde la carpeta del proyecto, con su entorno de Python):

    python tools/quitar_duplicados.py CARPETA                muestra qué quitaría; NO toca nada
    python tools/quitar_duplicados.py CARPETA --aplicar      manda las copias peores a la papelera
    python tools/quitar_duplicados.py CARPETA --aplicar --definitivo   las borra para siempre (sin papelera)
"""
import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mutagen import File as MutagenFile  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

import simpleplay as sp  # noqa: E402

EXTENSIONES = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".aiff", ".aif"}
TOLERANCIA_S = 3.0
# cuánto "rinde" un bit por segundo según el códec, comparado con el mp3
EFICIENCIA = {"mp3": 1.0, "aac": 1.25, "m4a": 1.25, "ogg": 1.25, "opus": 1.5}


def _clave_titulo(t):
    """Título para comparar: sin acentos ni mayúsculas ni signos, pero CON lo que dicen los paréntesis (remix, live...)."""
    t = unicodedata.normalize("NFKD", sp.sin_feat(sp.limpiar_nombre(t)).casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _primer_artista(a):
    a = re.split(r"\s+(?:feat|ft|featuring|with|con|x|&|y)\.?\s+|,|;|/", sp.sin_feat(sp.limpiar_nombre(a)), maxsplit=1, flags=re.I)[0]
    return a.strip()


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
    if sin_perdida:
        calidad = (1, bits * hz, 0)
        desc = f"{ext.upper() if codec != 'alac' else 'ALAC'} {hz / 1000:g} kHz {bits} bit"
    else:
        calidad = (0, kbps * EFICIENCIA.get(ext if ext != "m4a" else "aac", 1.0), 0)
        desc = f"{ext.upper()} {kbps:.0f} kbps"
    tiene_etq = bool(tit and art)
    claves = [str(k) for k in (f.tags or {})]
    tiene_portada = bool(getattr(f, "pictures", None) or any(k.startswith(("APIC", "covr")) for k in claves))
    return {"ruta": Path(ruta), "duracion": float(f.info.length), "desc": desc, "calidad": calidad,
            "tags": (tiene_etq, tiene_portada), "tam": Path(ruta).stat().st_size, "tit": tit, "art": art}


def _llaves(d):
    """Pares (artista, título) con los que se puede identificar el tema, normalizados."""
    out = set()
    for a, t in sp.candidatos(str(d["ruta"]), d["tit"], d["art"]):
        a2, t2 = _primer_artista(a), _clave_titulo(t)
        if a2 and t2:
            out.add((a2, t2))
    return out


def _mismo(d1, d2, l1, l2):
    if abs(d1["duracion"] - d2["duracion"]) > TOLERANCIA_S:
        return False
    return any(t1 == t2 and sp.parecido(a1, a2) >= 0.85 for a1, t1 in l1 for a2, t2 in l2)


def agrupar(archivos):
    """Grupos de 2 o más archivos que son el mismo tema -> lista de listas de dicts (de `leer`)."""
    datos = [d for d in (leer(r) for r in archivos) if d]
    llaves = [_llaves(d) for d in datos]
    orden = sorted(range(len(datos)), key=lambda i: datos[i]["duracion"])
    padre = list(range(len(datos)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i
    for pos, i in enumerate(orden):
        for j in orden[pos + 1:]:
            if datos[j]["duracion"] - datos[i]["duracion"] > TOLERANCIA_S:
                break  # ordenados por duración: ninguno más adelante puede coincidir
            if llaves[i] and llaves[j] and _mismo(datos[i], datos[j], llaves[i], llaves[j]):
                padre[raiz(i)] = raiz(j)
    grupos = {}
    for i in range(len(datos)):
        grupos.setdefault(raiz(i), []).append(datos[i])
    return [g for g in grupos.values() if len(g) > 1]


def mejor_primero(grupo):
    """El grupo ordenado de mejor a peor: calidad de audio, luego etiquetas/portada, luego tamaño y por último la ruta más corta."""
    return sorted(grupo, key=lambda d: (d["calidad"], d["tags"], d["tam"], -len(str(d["ruta"]))), reverse=True)


def mandar_a_papelera(ruta):
    r = subprocess.run(["gio", "trash", str(ruta)], capture_output=True, text=True)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "gio trash falló")


def revisar(carpeta, limite=None):
    """-> (grupos ordenados mejor primero, rutas a quitar). No toca nada."""
    archivos = sorted(p for p in Path(carpeta).rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES)
    if limite:
        archivos = archivos[:limite]
    grupos = [mejor_primero(g) for g in agrupar(archivos)]
    return len(archivos), grupos, [d["ruta"] for g in grupos for d in g[1:]]


def mostrar(grupos):
    for g in grupos:
        print(f"\n  {g[0]['art'] or '?'} - {g[0]['tit'] or g[0]['ruta'].stem}")
        for k, d in enumerate(g):
            print(f"    {'SE QUEDA' if k == 0 else 'se quita':8s} {d['desc']:22s} {d['tam'] / 1048576:6.1f} MB  {d['ruta']}")


def quitar(rutas, definitivo=False):
    hechos = 0
    for r in rutas:
        try:
            os.remove(r) if definitivo else mandar_a_papelera(r)
            hechos += 1
        except OSError as e:
            print(f"  no se pudo quitar {r.name}: {e}")
    return hechos


def main():
    ap = argparse.ArgumentParser(description="Quita los temas repetidos de una carpeta y deja el de mejor calidad.")
    ap.add_argument("carpeta")
    ap.add_argument("--aplicar", action="store_true", help="quitar las copias peores (por defecto solo se muestran)")
    ap.add_argument("--definitivo", action="store_true", help="borrar para siempre en vez de mandar a la papelera")
    ap.add_argument("--si", action="store_true", help="no pedir confirmación")
    a = ap.parse_args()
    QCoreApplication.setApplicationName("simpleplay")
    carpeta = Path(a.carpeta).expanduser()
    if not carpeta.is_dir():
        print(f"No existe la carpeta: {carpeta}")
        return 2
    total, grupos, quitar_rutas = revisar(carpeta)
    print(f"{total} archivos de audio en {carpeta}")
    mostrar(grupos)
    print(f"\n{len(grupos)} tema(s) repetido(s): se quitarían {len(quitar_rutas)} archivo(s).")
    if not a.aplicar:
        if quitar_rutas:
            print("No se tocó nada. Para quitarlos, agregá --aplicar.")
        return 0
    if quitar_rutas and not a.si and sys.stdin.isatty():
        destino = "BORRAR PARA SIEMPRE" if a.definitivo else "mandar a la papelera"
        if input(f"¿{destino} {len(quitar_rutas)} archivo(s)? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado, no se tocó nada.")
            return 0
    print(f"Listo: {quitar(quitar_rutas, a.definitivo)} archivo(s) " + ("borrados." if a.definitivo else "en la papelera."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
