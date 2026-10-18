import random
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

import pygame
from mutagen.mp3 import MP3

pygame.mixer.init()

root = tk.Tk()
root.title("mp3")
root.geometry("460x400")

pistas = []
actual = -1
pausado = False
duracion = 0.0
offset = 0.0  # segundo desde el que arrancó la reproducción (por seek)
arrastrando = False

lista = tk.Listbox(root, activestyle="none")
lista.pack(fill="both", expand=True, padx=8, pady=8)

estado = tk.Label(root, text="—", anchor="w")
estado.pack(fill="x", padx=8)

tiempo = tk.Label(root, text="0:00 / 0:00", anchor="e")
tiempo.pack(fill="x", padx=8)

linea = ttk.Scale(root, from_=0, to=1)
linea.pack(fill="x", padx=8, pady=(0, 4))


def fmt(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def posicion():
    return offset + max(pygame.mixer.music.get_pos(), 0) / 1000


def abrir():
    archivos = filedialog.askopenfilenames(
        initialdir=Path.home() / "Música", filetypes=[("MP3", "*.mp3")]
    )
    for a in archivos:
        pistas.append(a)
        lista.insert("end", Path(a).stem)
    if pistas and not lista.curselection():
        lista.selection_set(0)


def reproducir(i=None):
    global actual, pausado, duracion, offset
    if i is None:
        sel = lista.curselection()
        if sel:
            i = sel[0]
        elif pistas:
            i = 0
        else:
            return
    actual = i
    pausado = False
    offset = 0.0
    try:
        duracion = MP3(pistas[i]).info.length
    except Exception:
        duracion = 0.0
    linea.config(to=max(duracion, 1))
    pygame.mixer.music.load(pistas[i])
    pygame.mixer.music.play()
    lista.selection_clear(0, "end")
    lista.selection_set(i)
    estado.config(text="▶ " + Path(pistas[i]).stem)
    btn_play.config(text="⏸")


def play_pausa():
    global pausado
    if actual < 0:
        reproducir()
        return
    if pausado:
        pygame.mixer.music.unpause()
        estado.config(text="▶ " + Path(pistas[actual]).stem)
        btn_play.config(text="⏸")
    else:
        pygame.mixer.music.pause()
        estado.config(text="⏸ " + Path(pistas[actual]).stem)
        btn_play.config(text="▶")
    pausado = not pausado


def parar():
    global actual
    pygame.mixer.music.stop()
    actual = -1
    estado.config(text="—")
    btn_play.config(text="▶")
    tiempo.config(text="0:00 / 0:00")
    linea.set(0)


def siguiente():
    if not pistas:
        return
    if shuffle.get() and len(pistas) > 1:
        reproducir(random.choice([n for n in range(len(pistas)) if n != actual]))
    elif actual + 1 < len(pistas):
        reproducir(actual + 1)
    else:
        parar()


def anterior():
    if actual < 0:
        return
    # pasados 3 s vuelve al inicio de la pista, si no, a la anterior
    if posicion() > 3 or actual == 0:
        reproducir(actual)
    else:
        reproducir(actual - 1)


def saltar():
    global offset, arrastrando
    arrastrando = False
    if actual < 0:
        return
    offset = float(linea.get())
    pygame.mixer.music.play(start=offset)
    if pausado:
        pygame.mixer.music.pause()


def empezar_arrastre(_):
    global arrastrando
    arrastrando = True


def soltar(_):
    # el ttk.Scale actualiza su valor después de este binding
    root.after_idle(saltar)


def vigilar():
    if actual >= 0:
        pos = min(posicion(), duracion)
        if not arrastrando:
            linea.set(pos)
        tiempo.config(text=f"{fmt(pos)} / {fmt(duracion)}")
        if not pausado and not pygame.mixer.music.get_busy():
            siguiente()
    root.after(200, vigilar)


barra = tk.Frame(root)
barra.pack(pady=6)
btn_play = None
for texto, cmd in [("⏮", anterior), ("▶", play_pausa), ("⏹", parar),
                   ("⏭", siguiente), ("⏏", abrir)]:
    b = tk.Button(barra, text=texto, command=cmd, width=3, font=("DejaVu Sans", 14))
    b.pack(side="left", padx=3)
    if texto == "▶":
        btn_play = b
shuffle = tk.BooleanVar(value=False)
tk.Checkbutton(barra, text="⇄", variable=shuffle, indicatoron=False, width=3,
               font=("DejaVu Sans", 14), selectcolor="#ff4e01").pack(side="left", padx=3)

vol = tk.Scale(root, from_=0, to=100, orient="horizontal", label="Volumen",
               command=lambda v: pygame.mixer.music.set_volume(int(v) / 100))
vol.set(70)
vol.pack(fill="x", padx=8, pady=(0, 8))

linea.bind("<ButtonPress-1>", empezar_arrastre)
linea.bind("<ButtonRelease-1>", soltar)
lista.bind("<Double-Button-1>", lambda e: reproducir())
vigilar()
root.mainloop()
