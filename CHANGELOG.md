# Changelog

All notable changes to simpleplay. The version number lives in the `VERSION` constant in
`simpleplay.py` and is shown when you right click the window.

## [Unreleased]

## [1.5.2] - 2026-10-20

### Fixed
- **Shuffle no longer repeats tracks.** It used to pick any track at random each time, so with a long list some came
  up again and again before others played even once. Now every track plays once per round, and a new round starts
  only when all of them have played (the last track of a round never opens the next one). It keeps working if you add,
  remove, sort or drag tracks in the middle of a round, and the round is saved with the session. **Previous** in
  shuffle now goes back to the track that played before, not to the one above it in the list.
- **Imported ParametricEQ profiles with a decimal comma** (`Gain 2,2 dB`, as Equalizer APO writes them on some
  systems) were rejected with "the profile has no filters". They now load like the ones with a decimal point.

### Changed
- **New icon:** a vinyl record with an orange label and a play button, on a dark rounded square. The previous icon
  and two more designs (a bold "n" and a progress ring) are kept in `icon/alternativos/`.

## [1.5.1] - 2026-10-20

### Fixed
- **The normalizer no longer jumps.** The first time a track played, it sounded unchanged for about a second
  (measuring takes 0.4–1.4 s) and then the gain was applied in a single audio block, so the volume dropped
  suddenly. Now a late measurement is reached with a gentle ramp (8 dB per second), and while a track plays the
  next one is measured in the background, so it starts already normalized.

## [1.5] - 2026-10-20

### Added
- **Playlists.** The **+** menu has **Open playlist…** (replaces the current list) and **Save playlist as…**.
  Plain M3U/M3U8 files, readable by VLC, mpv or Navidrome, with paths relative to the playlist so it keeps working
  when you move it together with the music. Dragging a `.m3u`/`.m3u8` onto the window, or passing one on the
  command line, adds its tracks. Entries that cannot be found are skipped and counted.
  To build lists: right click one or more tracks > **Add to playlist** > a saved list, **New playlist…** or
  **Another playlist…**. It appends to the file without touching the list that is playing (or the entries that
  are missing right now). The **+** menu also has **Save “name”** to overwrite the list you opened.
  A floppy-disk button next to the list saves it in one click (over the open list, or asks for a name).
  All pop-up menus now have rounded corners.
- **FLAC.** The player opens `.flac` files next to `.mp3`: from the file dialog, by dragging files or folders onto
  the window, and from the command line. It reads the Vorbis tags (title, artist, album, track number) and the
  embedded cover art, the ReplayGain tags, and seeks inside the file. Tested with 16-bit/44.1 kHz and
  24-bit/96 kHz files (converted to the device rate while playing). The broom (MusicBrainz look-up) still only
  writes ID3 tags, so it skips FLAC files.
- **Headphone profiles** (right click > **Sound** > **Headphones**). Pick your model from the
  [AutoEq](https://github.com/jaakkopasanen/AutoEq) database (about 800 models, searched from inside the player) or
  import a `GraphicEQ.txt` / `ParametricEQ.txt` file. The profile is downloaded only when you choose it and then
  kept, so it works offline. The overall level is raised (up to 4 dB) to make up for what the profile lowers, so
  comparing it with the other presets is fair.
- **A transition between the track name and the spectrum bars:** the text lifts and fades while the bars rise
  one by one from left to right.

- **`tools/convertir.sh`**: turns the audio of every video in a folder (subfolders included) into mp3 or FLAC, keeping the
  folder structure and the tags, never overwriting what is already converted, and reporting the files that could not be
  converted. Needs `ffmpeg`.

### Changed
- **Lower CPU use** (about a third less with the bars on): the bars are drawn in four batches instead of one call
  per segment, the opacity effects only exist while a transition runs, the title timers only run when the text does
  not fit, the window shadow is not repainted for changes inside the card, and the spectrum is computed with fewer
  Python loops. The equalizer now really switches off when you go back to Flat.

## [1.4.1] - 2026-10-19

### Added
- **Volume normalizer.** Every track is brought to the same loudness, so a quiet recording is not
  drowned by a loud one. If the file carries ReplayGain tags they are used; if not, the loudness is
  measured once in the background (K-weighted, like EBU R128) and remembered. Very long files
  (mixes, sets) are left as they are. The gain never goes past what would clip.
- **Equalizer with presets** (right click > **Sound**): Flat, Lively (the default, a gentle lift of
  bass and treble), More bass, Vocals, Bright and Warm. 10 bands with a linear-phase filter, so it
  changes the tone without smearing it. Flat leaves the audio untouched, bit for bit.
- **Soft limiter** at the end of the chain: boosting bass or volume bends the peaks instead of clipping.
- Both settings are remembered between sessions.

### Fixed
- **Look-up on MusicBrainz now understands list numbers.** A file called `391 - Artist - Title.mp3` (what
  a downloaded playlist leaves behind) was searched with `391` as the artist and never found. The number is
  now ignored, and bands that start with a number (`3 Doors Down`, `311`) still work.
- The tests no longer overwrite the real configuration folder (they use a temporary home).

## [1.4] - 2026-10-19

### Changed
- **New audio engine.** Playback no longer goes through pygame and SDL: simpleplay plays through
  [miniaudio](https://miniaud.io/) directly. The position is exact (it was a rough estimate after a seek),
  pausing and seeking fade over 5 ms so there are no clicks, and the end of a track is signalled by the
  engine instead of being polled every 200 ms.
- **The spectrum reads what is playing.** The bars analyze the same audio that goes to the speakers, so they
  follow the music to the sample and the file is decoded once instead of twice. The level the bars are
  measured against now follows the last ten seconds, so a quiet passage still uses the whole range.
- **Seeking inside long files is instant.** A jump into an hour-long mix used to take over a second with
  the decoder alone; the player now indexes the mp3 frames and goes straight to the right one (0.2 ms).
- Lighter download: SDL and pygame are no longer bundled. `ffmpeg` is not used any more.

### Added
- **Animated transition** between the card and the compact bar: the window morphs from one shape to the
  other (380 ms). Pressing the button or `M` again halfway completes the previous one instantly.
- **Soft shadow** around the card, the compact bar and the playlist panel, so the frameless window does not
  look glued to light desktops. `SIMPLEPLAY_SOMBRA=0` turns it off.
- **It recovers from a lost sound device.** If a USB or Bluetooth speaker is unplugged, or the computer
  wakes from suspend, the device is reopened by itself and the track continues where it was. With no sound
  card at all it retries every few seconds and warns once.
- **Tracks that cannot be played are skipped** (missing, empty, corrupted or without audio), with a notice in
  the pill. If none of the tracks in the list can be played, the player stops instead of looping forever.
- MPRIS: the KDE and GNOME media widgets update immediately after a seek (the `Seeked` signal).
- `--diagnose` also tests the sound device. Running from source with a missing Python module now prints
  which one and the command to install it.
- Support link (`.github/FUNDING.yml` and a short section in the README).

### Removed
- The `pygame` and `ffmpeg` dependencies.

## [1.3] - 2026-10-18

### Added
- **Compact mode:** the same pill with a small cover and the scrolling title, plus previous, play
  and next buttons and a button to go back to the card. The window goes from 320x320 to a 380x56
  bar. Toggle it with the new button next to the playlist one, the `M` key, or the right-click
  menu. The music keeps playing when you switch, the playlist closes when going compact, and the
  mode is remembered between sessions.

## [1.2] - 2026-10-18

### Added
- **Search box** in the playlist (`Ctrl+F`): it shows only the tracks that contain every word you
  type, ignoring accents and capitals, and also looks at the album. `Enter` plays the first result
  and `Esc` clears the search before it closes the player.
- **Sorting** by artist, title or album, or back to the order the tracks were added. The track that
  is playing keeps playing and the selection is kept. The order is saved with the session.
- **Reorder by dragging** tracks in the playlist.
- **Repeat mode**: off, the whole list, or one track (`R` or the button at the left of the
  controls). It is remembered, and desktop media widgets can change it too (MPRIS `LoopStatus`).
  The previous button restarts the track, or goes to the last one when repeating the list.
- **Add a whole folder** (with its subfolders) from the **+** button (`Ctrl+Shift+O`), by dragging a
  folder onto the window, or from the command line. Tracks already in the list are not added again,
  and the last folder used is remembered.
- A short message in the pill when tracks are added.
- **Windows build:** a `simpleplay-<version>-windows-x64.zip` is built and attached to every release
  automatically (GitHub Actions), after checking that the decoder and the window work. It comes with
  a Windows icon and `packaging/build-windows.bat` for building it by hand.

### Changed
- The playlist shows **"Artist - Title" from the tags** instead of the file name, so a library
  cleaned with `tools/limpiar_biblioteca.py` or tagged with MusicBrainz Picard looks clean. Tracks
  without useful tags show their file name without the `[YouTube id]` and `(Official Video)` noise
  (only on screen, the file is not renamed).
- The **+**, **-** and sort buttons of the playlist are smaller (32, 28 and 28 px).

### Fixed
- `tools/limpiar_biblioteca.py` no longer proposes nonsense for names written the other way round
  (`Title (Cover) - Artist`, now read correctly), for DJ mixes and track lists, or for a loose
  `Official Video HD` at the end of a title.

## [1.1] - 2026-10-18

### Added
- **Media keys and desktop integration (MPRIS).** The play/pause, next and previous keys of
  the keyboard, and the media widgets of KDE and GNOME, now control simpleplay. The desktop
  also sees the title, artist, cover art, duration and position. It registers on the session
  bus as `org.mpris.MediaPlayer2.simpleplay`.
- **Remove tracks:** a **-** button in the playlist (and the `Delete` key) removes the
  selected track from the list; the file itself is never touched. Removing the track that is
  playing moves on to the next one. Removing every track is remembered between sessions.
- Several tracks can be selected in the playlist (`Ctrl`/`Shift`+click); the **-** button and
  `Delete` remove all of them.
- **`tools/limpiar_biblioteca.py`**: cleans the title and artist tags of a whole folder from the
  file names (`(Official Video)`, `[id]`, `- Topic` removed), without the player. It only shows
  what it would change unless `--aplicar` is given, saves the previous tags and cover, and can
  undo (`--deshacer`). With `--musicbrainz` it also looks up album, year and cover art.
- Keyboard shortcuts: `Left` / `Right` seek 5 s, `N` / `P` next and previous, `Delete`
  removes the selected track, `Ctrl+O` opens files. They work even when the playlist has the
  keyboard focus.
- `requirements.txt` with the Python dependencies (it uses `PySide6-Essentials`, about 100 MB
  to download instead of 270 MB), checked to have wheels for Windows x64 with Python 3.11-3.13.
- Small hardening for Windows: no crash when the program has no console (the trick that silences
  the `libmpg123` warnings is skipped), and no black console window when `ffmpeg` is launched.
  Not yet tried on a real Windows machine.
- `--diagnose file.mp3` checks the audio decoding used by the spectrum without opening the
  window, and `SIMPLEPLAY_DEBUG=1` prints what the player is doing. Both are meant for bug
  reports.

### Not included
- A **broom** button that looks tracks up on MusicBrainz and writes the info into the files is in
  the code but switched off in this release. Set `SIMPLEPLAY_ESCOBA=1` to try it.

### Fixed
- Inside the AppImage the system `ffmpeg` returned no audio (PyInstaller's library path broke
  it), so every spectrum request wasted a call before falling back to `miniaudio`. `ffmpeg`
  now runs with the original environment.
- **The AppImage could not draw the spectrum on a computer without `ffmpeg`.** The bundled
  `miniaudio` decoder was missing its `_cffi_backend` module, so decoding always failed (and
  version 1.0 hid that behind a fake wave: bars that "move" without reacting to the music).
  Found with the new `--diagnose` mode; the build now includes the module.
- **Spectrum bars barely moved with some music.** The scale was tuned on loud tracks, so soft
  ones stayed almost flat. Each stretch of audio now sets its own reference level, and the
  median bar height is similar across the 30 tracks measured (0.34 to 0.67, peaks at 1.0).
- If decoding failed (for example `ffmpeg` present but unable to read the file, or not
  installed and `miniaudio` missing) the bars kept showing a fake wave and requested new data
  about 30 times a second. Now: an empty or failed result tries the other decoder, retries
  wait 3 s, and with no data the bars stay flat instead of pretending.
- At the end of a track the spectrum could keep asking for more audio that does not exist.

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
