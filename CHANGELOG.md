# Changelog

All notable changes to simpleplay. The version number lives in the `VERSION` constant in
`simpleplay.py` and is shown when you right click the window.

## [1.0] - 2026-10-18

First complete release.

### Window
- Frameless window: just the card, with rounded corners. Move it by dragging any empty
  area; close it with `Esc` or right click > Close.
- The track's cover art as the card background, or an orange gradient when there is none.
- Top pill with a round thumbnail, title and artist. Long text scrolls in a loop.
- Clicking the pill swaps the text for a Winamp-style equalizer (24 green/yellow/red
  segmented bars with falling peaks) driven by the real audio.

### Playback
- Previous, play/pause (one button), next, shuffle, and a time bar with elapsed and
  remaining time. Click or drag the bar to seek.
- "Previous" restarts the track if more than 3 s have played, otherwise it goes back one.
- When a track ends it moves to the next one (or a random one with shuffle).
- The space bar toggles play/pause. Volume is left to the system.

### Playlist and files
- The list button slides open the playlist; the **+** button inside it adds more tracks.
  Double click plays a track.
- Files can also be opened from right click > Open files, by dragging mp3 files onto the
  window, or from the command line.

### Session
- Remembers the playlist, track, position and shuffle in
  `~/.config/simpleplay/estado.json`. On start it shows the last track paused; play
  resumes from where it was. Missing files are skipped.
- It always starts in text mode, not spectrum mode.
- A session saved under the previous name (`~/.config/mp3player/`) is picked up
  automatically.

### Animations
- Play <-> pause: the icon cross-fades with a slight rotation (0.2 s).
- Cover art: cross-fade between the old and the new cover (0.38 s).
- Text <-> spectrum: cross-fade inside the pill (0.24 s).
- Playlist: reveals like a curtain with a fade (0.28 s).
- Buttons: background fades from gray to orange when toggled (shuffle, list), and
  brightens on hover and press.

### Interface language
- English or Spanish, following the system language (`LANGUAGE`/`LANG`).

### Technical notes
- Audio through `pygame.mixer`; interface with PySide6 (Qt).
- The spectrum decodes only ~40 s around the current position (not the whole track), so
  it appears instantly and does not use much memory on long mixes. It uses `ffmpeg` when
  installed (it seeks faster inside huge files) and otherwise the bundled `miniaudio`
  decoder, so nothing else needs to be installed.
- Python dependencies: PySide6, pygame, mutagen, numpy, miniaudio.
- Quiet terminal: the pygame welcome banner is hidden, and the harmless libmpg123 warning
  ("No comment text / valid description?", printed for malformed ID3 comment tags such as
  those in yt-dlp downloads) is silenced while a track loads.

### Packaging
- Own icon (`icon/`): orange square with a play button and a progress bar.
- `packaging/build.sh` builds `dist/simpleplay-1.0-x86_64.AppImage`, a single file for
  x86_64 Linux with glibc >= 2.35 (Ubuntu 22.04+, Debian 12+, Fedora 36+, Mint 21+, Arch).
  It is built inside an Ubuntu 22.04 container so it does not inherit the newer glibc of
  the development machine.
- Built with Python 3.13 (through `uv`, inside the container). With the Python 3.10 that
  ships in Ubuntu 22.04 the app crashed after a few seconds
  (`Fatal Python error: none_dealloc`).
- Running it needs FUSE 2 (`libfuse2`); without it use `--appimage-extract-and-run`. It
  also needs `libGL` and `libEGL` from the system. The file must be marked executable.
- It does not integrate itself into the applications menu.

### Testing
- Tried on real desktops with sound: Debian 13 (KDE Plasma, Wayland) and Ubuntu 26.04
  (GNOME 50, Wayland). The Ubuntu 26.04 run used the build from before the rename to
  simpleplay.
- Starting up (virtual display, no real audio) was checked on Debian 12, Ubuntu 24.04 and
  Fedora 44 with an earlier build (Python 3.10).

### Notes
- Renamed from "mp3player" to "simpleplay". Licensed under GPL-3.0-or-later.
- `legacy/player_tk.py` is the first, minimal Tkinter version, kept just in case.
