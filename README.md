# simpleplay

A small, clean mp3 player for Linux, for people who just want to play their own music.
No streaming, no accounts, no ads.

<p align="center">
  <img src="docs/screenshots/player.png" alt="Player card with cover art" width="250">
  <img src="docs/screenshots/spectrum.png" alt="Winamp-style spectrum bars" width="250">
  <img src="docs/screenshots/playlist.png" alt="Playlist panel" width="250">
</p>

<sub>Screenshots use a generated demo track and cover art.</sub>

## Features

- A single rounded card with the track's cover art. No title bar, no clutter.
- Title and artist scroll when they don't fit.
- Click the top pill to switch between the track info and **Winamp-style spectrum bars**
  that react to the real audio.
- Previous, play/pause, next, shuffle, and a time bar you can click or drag to seek.
- A playlist panel that slides open; add files with the **+** button, with a right click,
  by dragging mp3 files onto the window, or from the command line.
- Remembers your last session (playlist, track, position, shuffle) and starts paused,
  ready to resume.
- Smooth transitions for play/pause, cover changes, the playlist and the buttons.
- Volume is left to the system mixer.
- The interface is in English or Spanish, following your system language.

## Download

Get the AppImage from the [Releases](../../releases) page, then make it executable and run it:

```
chmod +x simpleplay-1.0-x86_64.AppImage
./simpleplay-1.0-x86_64.AppImage
```

On GNOME you can also right click the file, open **Properties > Permissions** and enable
**Allow executing file as program**.

Requirements:

- A 64-bit (x86_64) Linux desktop with glibc 2.35 or newer (Ubuntu 22.04+, Debian 12+,
  Fedora 36+, Linux Mint 21+, Arch and similar).
- `libGL` and `libEGL` (every desktop install has them).
- FUSE 2 to run AppImages directly (`libfuse2t64` on recent Ubuntu). Without it, run
  `./simpleplay-1.0-x86_64.AppImage --appimage-extract-and-run`.

It does not add itself to your applications menu. Use
[AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher), or copy
`packaging/simpleplay.desktop` and the icon by hand.

## Run from source

```
python3 -m venv .venv
.venv/bin/pip install PySide6 pygame mutagen numpy miniaudio
.venv/bin/python simpleplay.py [file.mp3 ...]
```

`ffmpeg` is optional: if installed, the spectrum bars seek faster inside very long files;
otherwise the bundled `miniaudio` decoder is used.

## Controls

| Action | How |
|---|---|
| Play / pause | center button, or the space bar |
| Seek | click or drag the time bar |
| Track info / spectrum | click the top pill |
| Playlist | the list button (inside it, **+** adds more tracks) |
| Open files | **+**, right click > Open files, drag and drop, or command line |
| Move the window | drag any empty area |
| Quit | `Esc`, or right click > Close |

## Build the AppImage

`packaging/build.sh` builds `dist/simpleplay-<version>-x86_64.AppImage` inside an
Ubuntu 22.04 container (Docker required), so it does not depend on the glibc of the
machine that builds it.

## Project files

- `simpleplay.py`: the application (PySide6 + pygame.mixer).
- `icon/`: app icon as SVG and PNG.
- `packaging/`: AppImage build scripts and desktop entry.
- `legacy/`: the first, minimal Tkinter version.
- [CHANGELOG.md](CHANGELOG.md) and [ROADMAP.md](ROADMAP.md).

## License

simpleplay is free software, released under the
[GNU General Public License v3.0 or later](LICENSE).

Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>

It uses PySide6, pygame, mutagen, numpy and miniaudio, each under its own license.
