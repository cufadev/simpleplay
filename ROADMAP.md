# Roadmap

Ideas for future versions. What is already done is in [CHANGELOG.md](CHANGELOG.md).

## Priorities (2026-10-23)

The sections below keep the detail of each idea; this is the order to do them in.

**Before the next release (1.7)**
1. **macOS.** The build script and the manual GitHub Actions workflow exist but were never run. Test the `.dmg` on a real Intel
   Mac, note the macOS version, then bring back the `release: published` trigger and enable the button on the website.
   Apple Silicon is untested; signing and notarization are still to decide.
2. **Import playlists from other players** (`.m3u`, `.pls`, `.xspf`; iTunes/Music and Rhythmbox libraries) and, from a
   Spotify/YouTube Music CSV export, a list that matches each title against the user's own folders and says which ones are
   missing. Metadata only, never audio from a streaming service. First check what the Spotify API still allows for playlists.
3. **Dither** on the float→16-bit conversion (item 4 of the audio list below). Exclusive / bit-perfect output stays last.
4. **Website clean-up.** Remove the `?idioma=` language-switch test modes (`cascada`, `barrido`, `cruce`), keeping the
   letter-by-letter one.

**Next (1.8 or later)**
5. **Connect to a server the user owns** (Navidrome, Jellyfin, any Subsonic-compatible one).
6. **Weigh shuffle by artist** so two tracks of the same artist rarely play back to back.
7. **The broom** (fill in track info from inside the player): understand why it recognised nothing on the user's machine
   before switching it on again; second stage with an audio fingerprint (needs a free AcoustID key).
8. **Rename and domain.** The new name (Tarab, `playtarab`) needs the domain, then a full rename: repository, download
   file names, icon, texts and links. Best done together with 2.0.

**2.0**
9. **Split `simpleplay.py` into modules** (plan below). Never mixed with feature work.

**Separate tracks (not tied to a release)**
- **Pocket player** (ESP32-S3; parts and phases below). The simulator already runs and nothing sounds yet; the enclosure
  designs are a first draft still to improve.
- **Touch kiosk variant** (private): make the touch input permanent, start on boot, rows with small covers.
- **YouTube Music** stays a development-only build (it downloads with `yt-dlp`, which goes against YouTube's terms and breaks
  often). Notes are kept out of the repository.
- **CD ripping**, for a later, bigger version.

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

## CD ripping (for a later, bigger version)
Turn an audio CD into FLAC (or mp3) files from inside the player, so the library can grow from the discs
people still own. Not started; written down after comparing with MusicBee, which has it.

### How it would work
- Read the disc with `libcdio-paranoia` / `cdparanoia` (Linux) and the platform's own drive access on Windows
  and macOS. Offer a secure mode that re-reads damaged sectors.
- Identify the disc from its table of contents (MusicBrainz **disc ID**, a short hash computed locally) to get
  album, artist, track titles, year and cover art; this reuses the look-up and safe-writing code of the broom.
- Encode to FLAC by default (lossless) with an mp3 option; write the tags and cover art, name the files
  `Artist/Album/NN - Title`, and put them in the music folder.
- Optional check against **AccurateRip** to know whether the copy is bit-perfect.

### Still to decide
- Whether to bundle the ripping and encoding tools in the AppImage and the Windows build (size, licenses) or to
  ask the user to install them.
- Whether it belongs in the player at all or in a companion tool like `tools/convertir.sh`: it is the opposite of
  "a card that just plays". Probably a separate window that only appears when a disc is inserted.

## Desktop ideas noted on 2026-10-20 (not started)
- **Open a file = add it to the queue.** Opening a file with "Open with simpleplay" (or from the command line) while
  the player is already running must append it to the current queue instead of starting a second player. Needs a
  single-instance check (a local socket or the D-Bus name the MPRIS code already owns) that forwards the paths to
  the running window; only the first instance opens a window.
- **Add a track to a chosen playlist.** In the general list, a track's menu offers "Add to playlist..." with the
  existing `.m3u8` files to pick from. Only lists that already exist are offered (it never creates one), and the file
  is written safely (atomic copy) with relative paths like the rest of the M3U code.
- **The big one: audio CDs, with tags, album and cover.** Play a disc straight from the drive and load every track's
  title, artist, album and cover automatically (MusicBrainz disc ID and Cover Art Archive, as in the CD ripping
  section below). Tags and cover would be written into the files once the disc is copied.
- **Next version after that: convert to mp3.** Turn the copied CD tracks (and other files) into mp3, keeping tags
  and cover. This is the "mp3 option" of the CD ripping section, promoted to its own step; it fits the decision
  that the library is mp3 only.

## simpleplay in hardware: a pocket player (prototype plan)
A small, offline, one-purpose player in the spirit of the Hidizs AP30 Music Boy (a Kickstarter that raised about
80 times its goal): music from a microSD card, a square screen, no accounts and no cloud. Not started; this is
the agreed plan for a first prototype, written down so it can be picked up later.

It would be separate firmware (C++ on an ESP32), not the Python app. What can be reused is the logic: the
round-based shuffle, M3U8 playlists, and the card-style interface.

### Chosen board
**Waveshare ESP32-S3-Touch-LCD-1.54** (also sold without touch). Per Waveshare's wiki it has an ESP32-S3R8
(dual core, 240 MHz, 16 MB flash, 8 MB PSRAM), a 1.54" **240x240 square** ST7789 screen with capacitive touch,
an ES8311 audio codec with NS4150B amplifier and speaker header, a microSD slot, a lithium battery header
(MX1.25) with its own charger, an IMU, and USB-C. Seen in Argentina at about $60,900 as a kit (price varies a lot).
Rejected: the 1.47" board (tall, not square), and a Lafvin 1.83" board (about twice the price, slow delivery,
and no sign of codec, SD or charger).

### Parts for the prototype
1. The board above.
2. A **PCM5102A DAC module with a 3.5 mm jack** (stereo, line level around 2 V, no hardware volume).
3. A **3.7 V LiPo, 1000-1200 mAh, MX1.25 connector**. No separate charger is needed (it is on the board).
   Check the polarity against the board before plugging it in: some cables come reversed.
4. A microSD card and thin wires.

### Phases
1. **Board alone:** play mp3 and FLAC from the card through the onboard codec and speaker (no soldering).
   Interface on the square screen: cover, title, artist, play/pause, previous/next, volume. Shuffle by rounds.
2. **External DAC with jack:** send I2S to the PCM5102A and switch the output to it. Volume in software.
3. **Battery:** run on the LiPo, measure the battery life, add a battery gauge on screen.
4. Later: playlists (M3U8), tags and cover from the files, motion sensor (shake to skip), a case.

### Things to check before buying or soldering
- **Schematic of the board** (Waveshare "Resources"): which GPIOs are free for I2S (bit clock, word select,
  data). The ESP32-S3 can route I2S to almost any pin, but the wiki only shows I2C, USB and UART pads. If three
  are not free, tap the same I2S lines the codec uses, in parallel, and mute the codec by software.
- That the microSD slot does not share pins with the codec or the screen.
- What the kit includes (case, speaker, battery) before paying for it.
- **exFAT** support in the firmware if cards above 32 GB are wanted.

### Known limits
- The **ESP32-S3 has Bluetooth LE only, not classic Bluetooth (A2DP)**, so it cannot play to ordinary Bluetooth
  headphones. Options later: a small Bluetooth audio transmitter module fed from the DAC, or the classic ESP32
  (without this board).
- The onboard **ES8311 is a mono codec** (as far as is known): a jack taken from the speaker output would be mono,
  and that output must not be used as headphone ground. True stereo needs the external DAC.
- **USB-C DAC dongle (pilot idea):** the S3 can act as a USB host and Espressif has a USB audio class component,
  but the port is full speed (12 Mbps, enough for 44.1/48 kHz and tight at 96 kHz, no 192 kHz); the board may not
  supply 5 V on that port; and it is also the charging and flashing port. Treat it as a later experiment.
- This is hobby-grade audio, not the hi-res performance of the AP30 (DSD, 192 kHz, balanced output).

### Bluetooth uses (S3, LE only)
The simulator (`hardware/pocket/`) already has the screens. With BLE the S3 can be controlled from the phone, and take music or firmware updates. Audio to ordinary
headphones still needs an external Bluetooth audio transmitter module or a classic ESP32 (see the limits above).

### The player as the phone's DAC (idea, 2026-10-22, not started)
Use the Pocket as an output device for the phone: the phone sends the sound and the player plays it through its own DAC
(PCM5102A) and jack. Two ways, with very different results:
1. **Over Bluetooth (the phone is the A2DP source, the player the sink).** Needs **classic Bluetooth, which the ESP32-S3
   does not have**, so it is not possible with this board. Options: a **classic ESP32** (it can be an A2DP sink and feed
   the PCM5102A through I2S; the Bluedroid stack only does **SBC**), or a small **Bluetooth audio receiver module** with
   I2S output (some chips also do AAC, aptX or LDAC). A classic ESP32 can also be the source for headphones, but not both
   roles at once. With AVRCP the screen could show the title and artist and the buttons could control the phone (no cover
   art). Honest caveat: the audio is lossy before it reaches the DAC (SBC/AAC), so this is a **wireless receiver**, not a
   hi-fi DAC, and Bluetooth latency makes it a poor fit for video.
2. **Over USB (the player shows up as a USB sound card).** The S3 has native USB and Espressif has a USB audio class
   (speaker) device component, so the phone could see it as a **USB DAC** through a USB-C cable: bit-perfect, no
   compression, works on this board. Limits: the port is full speed (12 Mbps, enough for 44.1/48 kHz 16-bit, not for
   hi-res), it is the same port used for charging and flashing, and the phone has to be able to power or work with it.
It could be a mode in Settings ("Player / Bluetooth receiver / USB DAC"). The USB route is the one that fits the current
board; the Bluetooth one means changing the chip (see the limits above) and is worth deciding together with how the
player will talk to Bluetooth headphones.

### Software
- First try: the **ESP32-audioI2S** library (mp3, FLAC, WAV, AAC, tags, external I2S DAC); the serious route is
  **ESP-ADF**. 24-bit/96 kHz FLAC has to be tested, 16-bit/44.1 kHz should be comfortable.
- Develop with Arduino or ESP-IDF; Waveshare publishes examples for both for this board.

### Still to decide
- Whether to stay at a prototype or aim at a product (custom board, case, certification, and maybe a campaign).
- Touch only, or also physical buttons or a wheel.

## First desktop batch after 1.5.3: cleaner cover and better sound (shipped in 1.6, except the dither check)

Two things that go together: a calmer window and measurably better audio.

- **Controls that fade out by themselves.** After a few seconds without the mouse, the controls fade to transparent and the
  hidden cursor leaves only the cover; moving the mouse or pressing a key brings them back. Rules: never hide while the pointer
  is over a control, a menu or dialog is open, or playback is paused; space/arrows keep working and also reveal the controls;
  it is an option (some Winamp/AIMP users expect everything to stay visible). Cost is low: there are already opacity
  effects and transitions, but the opacity effect makes Qt paint each widget separately, so it is switched on only during the fade.
- **Audio, in order of benefit/effort** (measured 2026-10-22):
  1. **Done in the development version (1.6):** proper resampler for files that are not 44.1 kHz (a 48 kHz tone at 18 kHz came out 4.2 dB low and a 14.1 kHz alias sat
     13 dB under the tone). Options: `soxr`, or open the device at the file's rate.
  2. **Done in the development version (1.6):** bass resolution of the equalizer (minimum-phase filter, 4095 taps). Original problem: the 2047-tap FIR resolves ~22 Hz, so +6 dB at 31 Hz gives +4.8 and at 62 Hz +4.2, and
     it leaks into the neighbours. Longer filter, or IIR sections for the low bands (the Pocket already uses biquads).
  3. **Done in the development version (1.6):** look-ahead limiter (the normalization can raise up to 9 dB).
  4. Check dither on the float→16-bit conversion; exclusive / bit-perfect output is last (small gain, big complication).
- **Accent color** (done in the development version): six solid colors (orange + five), chosen from the right-click menu.

## Split `simpleplay.py` into modules (for 2.x)
The single file is past 4,500 lines and `Player` alone is about 1,600. Decided to leave it for 2.x, as its own step
and never mixed with feature work. Plan, lowest risk first: (1) pure logic without Qt (equalizer presets, `Afinador`,
AutoEq profiles, M3U lists, tags, shuffle choice); (2) audio (`Cadena`, `Motor`, loudness); (3) widgets and panels;
(4) split `Player` by topic (sound, list, session). Keep `simpleplay.py` as a thin entry point that re-exports the
names so the tests and `--diagnose` keep working. Watch: the Windows workflow reads `VERSION` from `simpleplay.py`
with a regex; shared globals (shadow cache, `ESTADO`) that the tests redirect; the loss of "copy one file and run".

## Done
- **A better shuffle** (1.5.2): every track plays once per round and a new round starts only when all have
  played; it follows playlist edits, is saved in the session, and `anterior` walks back through the order
  that actually played. Still open: weigh by artist so two tracks of the same artist rarely play back to back.

## Ruled out
- Recognizing songs inside a long mix.
