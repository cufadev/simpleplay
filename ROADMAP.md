# Roadmap

Ideas for future versions. What is already done is in [CHANGELOG.md](CHANGELOG.md).

## Fill in an mp3's metadata automatically

Identify a song and fill in its title, artist and cover art without the user doing anything.

### How it would work
- Audio fingerprint with **Chromaprint** (`fpcalc`, package `chromaprint-tools`), looked up
  on **AcoustID** (`pyacoustid`). It is an open, free service, but it needs your own
  application key.
- The result is then queried against **MusicBrainz** (title, artist, album) and
  **Cover Art Archive** (cover art). MusicBrainz requires a descriptive User-Agent and
  limits requests to about 1 per second.
- Only the fingerprint (a short string) leaves the computer, never the audio.
- It works well for known studio recordings. With remixes, live versions or obscure music
  it may find nothing; in that case the file is left untouched.

### What "automatic" would mean
- When opening a track that is missing its title or artist, identify it in the background
  without interrupting playback, and fill in the data when the answer arrives (the pill
  and the cover update by themselves, with the existing transitions).
- Fill in only empty fields, and never overwrite tags that already exist.
- Accept a result only on a high-confidence match; if in doubt, leave it as it is.
- Writing tags into the mp3 changes the file for good. Decide beforehand whether to write
  directly, keep a backup copy, or store the data separately (in the session file)
  without touching the mp3.

### Still to decide
- Register an AcoustID key and install `chromaprint-tools`.
- Where to store the key (a config file, never in the code).
- Whether to write into the mp3 or keep the data aside.

### Before starting
Try it with 5 or 6 real tracks to measure how many are actually recognized.

## Windows and macOS versions

The libraries used (PySide6, pygame, numpy, mutagen, miniaudio) all run on both systems, so
this is mostly packaging and a few small code changes.

### Code changes needed
- Store the session file with `QStandardPaths` (`%APPDATA%` on Windows,
  `~/Library/Application Support` on macOS) instead of the hard-coded `~/.config`.
- macOS delivers "open with" files through an event, not the command line: handle
  `QFileOpenEvent`.
- Check the frameless, translucent window and dragging it on both systems; Qt supports
  them, but they have only been tried on Linux so far.
- `ffmpeg` is not installed on those systems; the bundled `miniaudio` decoder already
  covers the spectrum bars there.

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
