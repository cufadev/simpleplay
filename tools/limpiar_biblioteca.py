#!/usr/bin/env python3
# simpleplay - limpiar_biblioteca.py
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Limpia las etiquetas de una carpeta de mp3, sin abrir el reproductor.

Toma el artista y el título del nombre del archivo (o de las etiquetas que ya tiene), quitando lo
que sobra de un video de YouTube: "(Official Video)", "[id]", "- Topic", "ft. ..." Por ejemplo:

    Gustavo Cerati - Pulsar (Official Video) [FCdOGM-Ac-8].mp3   ->   artista "Gustavo Cerati", título "Pulsar"

Uso (desde la carpeta del proyecto, con su entorno de Python):

    python tools/limpiar_biblioteca.py CARPETA                  muestra qué cambiaría; NO toca nada
    python tools/limpiar_biblioteca.py CARPETA --aplicar        escribe título y artista limpios
    python tools/limpiar_biblioteca.py CARPETA --musicbrainz    además busca álbum, año y portada (internet)
    python tools/limpiar_biblioteca.py --deshacer               devuelve el último lote a como estaba

Los archivos se escriben a través de una copia temporal y antes se guardan las etiquetas y la portada
originales, así que se puede deshacer. Los nombres de archivo no se modifican.
"""
import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no abre ninguna ventana
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mutagen.id3 import ID3, ID3NoHeaderError  # noqa: E402
from mutagen.mp3 import MP3  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

import simpleplay as sp  # noqa: E402


def etiquetas(ruta):
    try:
        t = ID3(ruta)
    except ID3NoHeaderError:
        return "", ""
    return (str(t["TIT2"]) if "TIT2" in t else ""), (str(t["TPE1"]) if "TPE1" in t else "")


def proponer(ruta, usar_mb):
    """-> (estado, datos, detalle). estado: 'cambia', 'limpio', 'sin_datos' o 'sin_coincidencia'."""
    tit, art = etiquetas(ruta)
    cands = sp.candidatos(ruta, tit, art)
    if not cands:
        return "sin_datos", None, "el nombre no tiene artista y no hay etiqueta de artista"
    if usar_mb:
        try:
            dur = MP3(ruta).info.length
        except Exception:
            dur = None
        for artista, titulo in cands:
            info = sp.buscar_mb(artista, titulo, dur)
            if info:
                return _comparar(tit, art, info), info, ""
        return "sin_coincidencia", None, "MusicBrainz no tiene una coincidencia confiable"
    artista, titulo = cands[0]
    return _comparar(tit, art, {"titulo": titulo, "artista": artista}), {"titulo": titulo, "artista": artista}, ""


def _comparar(tit, art, info):
    return "limpio" if (tit, art) == (info["titulo"], info["artista"]) and not info.get("album") else "cambia"


def main():
    ap = argparse.ArgumentParser(description="Limpia las etiquetas de una carpeta de mp3 (por defecto, solo muestra).")
    ap.add_argument("carpeta", nargs="?", help="carpeta con los mp3 (se revisan también las subcarpetas)")
    ap.add_argument("--aplicar", action="store_true", help="escribir los cambios (por defecto solo se muestran)")
    ap.add_argument("--musicbrainz", action="store_true", help="buscar álbum, año y portada en MusicBrainz (internet, ~6 s por tema)")
    ap.add_argument("--deshacer", action="store_true", help="deshacer el último lote aplicado")
    ap.add_argument("--si", action="store_true", help="no pedir confirmación al aplicar")
    ap.add_argument("--limite", type=int, help="procesar solo los primeros N archivos (para probar)")
    a = ap.parse_args()

    QCoreApplication.setApplicationName("simpleplay")
    base = sp.carpeta_deshacer()

    if a.deshacer:
        lotes = sorted(base.glob("*")) if base.exists() else []
        if not lotes:
            print("No hay ningún lote para deshacer.")
            return 1
        n = sp.restaurar_originales(lotes[-1])
        print(f"Deshecho el lote {lotes[-1].name}: {n} archivo(s) devueltos a como estaban.")
        return 0

    if not a.carpeta:
        ap.print_help()
        return 2
    carpeta = Path(a.carpeta).expanduser()
    if not carpeta.is_dir():
        print(f"No existe la carpeta: {carpeta}")
        return 2
    archivos = sorted(p for p in carpeta.rglob("*") if p.suffix.lower() == ".mp3")
    if a.limite:
        archivos = archivos[:a.limite]
    if not archivos:
        print("No se encontró ningún mp3.")
        return 1

    print(f"{len(archivos)} mp3 en {carpeta}" + ("  (con MusicBrainz: va a tardar)" if a.musicbrainz else ""))
    resultados, cuenta = [], {}
    for i, ruta in enumerate(archivos, 1):
        try:
            estado, datos, detalle = proponer(str(ruta), a.musicbrainz)
        except Exception as e:  # un archivo con problemas no frena al resto
            estado, datos, detalle = "error", None, repr(e)[:100]
        cuenta[estado] = cuenta.get(estado, 0) + 1
        resultados.append((ruta, estado, datos))
        if estado == "cambia":
            extra = f"  [{datos['album']}{', ' + datos['anio'] if datos.get('anio') else ''}]" if datos.get("album") else ""
            print(f"  cambia   {ruta.stem[:52]:52s} -> {datos['artista']} | {datos['titulo']}{extra}")
        elif estado != "limpio":
            print(f"  {estado:8s} {ruta.stem[:52]:52s}   {detalle}")
    etiqueta = {"cambia": "para cambiar", "limpio": "ya limpios", "sin_datos": "sin datos para buscar",
                "sin_coincidencia": "sin coincidencia", "error": "con error"}
    print("\nResumen: " + ", ".join(f"{n} {etiqueta[k]}" for k, n in cuenta.items()))

    cambios = [(r, d) for r, e, d in resultados if e == "cambia"]
    if not a.aplicar:
        if cambios:
            print("No se tocó ningún archivo. Para escribir los cambios, agregá --aplicar.")
        return 0
    if not cambios:
        print("No hay nada para cambiar.")
        return 0
    if not a.si and sys.stdin.isatty():
        if input(f"¿Escribir las etiquetas de {len(cambios)} archivo(s)? Se guarda lo anterior para deshacer. [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado, no se tocó nada.")
            return 0
    lote = sp.carpeta_deshacer(nueva=True)
    hechos = 0
    for n, (ruta, datos) in enumerate(cambios, 1):
        try:
            portada = sp.descargar_portada(datos) if a.musicbrainz and datos.get("rg") else None
            sp.guardar_original(lote, n, str(ruta))
            sp.escribir_etiquetas(str(ruta), datos, portada)
            hechos += 1
        except OSError as e:
            print(f"  no se pudo escribir {ruta.name}: {e}")
    print(f"Listo: {hechos} archivo(s) actualizados. Para deshacer: python tools/limpiar_biblioteca.py --deshacer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
