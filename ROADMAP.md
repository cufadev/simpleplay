# Roadmap

Ideas for future versions. What is already done is in [CHANGELOG.md](CHANGELOG.md).

## The broom: fill in track info from inside the player (written, switched off)

A button next to the controls that looks the selected tracks up on MusicBrainz and writes title,
artist, album, year and cover art into the mp3 files, with undo. The code is in `simpleplay.py`
and is enabled with `SIMPLEPLAY_ESCOBA=1`, but it is hidden in 1.1 because on the author's machine
it did not recognize tracks and the cause was not found. In tests it completed about three
quarters of the tracks that have an artist in their name (33 of 44 in two samples of a real
library) with no wrong artist, so the problem may be in how it is used or in the environment.
The command-line tool `tools/limpiar_biblioteca.py` shares the same search code and prints why
each file was skipped, which should help find out.

### Recognize tracks from the audio (second stage)

Tracks whose name carries no artist (`Black [id]`: 45 of 155 in the author's library) cannot be
looked up by text.

### How it would work
- Audio fingerprint with **Chromaprint** (`fpcalc`, package `chromaprint-tools`), looked up on
  **AcoustID** (`pyacoustid`). It is an open, free service, but it needs your own application key.
- The result gives the MusicBrainz recording, so the rest of the broom (album choice, cover art,
  safe writing, undo) is reused as it is.
- Only the fingerprint (a short string) leaves the computer, never the audio.
- It works well for known studio recordings. With remixes, live versions or obscure music it may
  find nothing; in that case the file is left untouched.
- The AppImage would have to bundle `fpcalc`.

### Still to decide
- Register an AcoustID key and decide where to store it (a config file, never in the code).
- Whether to offer the fingerprint automatically when the text search finds nothing.

### Ideas to improve the text search
- Let the user correct a wrong match, or pick from the candidates, before writing.
- Remember tracks that were skipped, so the broom does not ask MusicBrainz about them again.

## Windows and macOS versions

The libraries used (PySide6, numpy, mutagen, miniaudio) all run on both systems, so
this is mostly packaging and a few small code changes.

Status: `requirements.txt` is ready and checked to have Windows wheels; a first run on a real Windows
machine is pending, and the macOS handler for opened files is not written yet.

### Code changes needed
- Store the session file with `QStandardPaths` (`%APPDATA%` on Windows,
  `~/Library/Application Support` on macOS) instead of the hard-coded `~/.config`.
- macOS delivers "open with" files through an event, not the command line: handle
  `QFileOpenEvent`.
- Check the frameless, translucent window and dragging it on both systems; Qt supports
  them, but they have only been tried on Linux so far.
- Audio on Windows goes through WASAPI (via `miniaudio`) and on macOS through Core Audio; neither has been
  tried on a real machine yet. There is no `ffmpeg` dependency anywhere.

### Packaging
- PyInstaller can produce a Windows build (portable zip, or an installer with Inno Setup)
  and a macOS `.app` (inside a `.dmg`), but each must be built on its own system.
- Practical route: a GitHub Actions workflow with a Linux, Windows and macOS runner that
  builds all three and attaches them to each release (free for public repositories).
- Unsigned builds show warnings: Windows SmartScreen, and macOS Gatekeeper (right click >
  Open). Removing them needs a code-signing certificate (Windows) and an Apple Developer
  account (macOS, paid).

### Still to decide
- Who can test on a real Mac and a real Windows machine: a CI build proves it compiles,
  not that it works.
- Whether to sign the builds or just document the warnings.

## Ruled out
- Recognizing songs inside a long mix.
