# Security

## Check a download

Every file on the [Releases](../../releases) page comes with a `.sha256` file next to it: the SHA-256 sum of that
exact file. Download both into the same folder and compare them before running anything.

**Linux**

```sh
sha256sum -c simpleplay-1.8.5-x86_64.AppImage.sha256
```

**macOS**

```sh
shasum -a 256 -c simpleplay-1.8.2-macos-x86_64.dmg.sha256
```

**Windows (PowerShell)**

```powershell
(Get-FileHash simpleplay-1.8.2-windows-x64.zip -Algorithm SHA256).Hash.ToLower()
Get-Content simpleplay-1.8.2-windows-x64.zip.sha256
```

On Linux and macOS the answer must be `OK`. On Windows the two lines must show the same sum. If they do not match,
the file is damaged or it is not the one that was published: delete it and download it again from the Releases page.

Only download from the Releases page of this repository. The builds are not signed, so the sum tells you the file is
the published one, not who built it. The Windows and macOS files are built by GitHub Actions from the tagged source
(see `.github/workflows/`); the AppImage is built with `packaging/build.sh`.

## Report a problem

If you find a security problem, please report it privately with **Security > Report a vulnerability** on the
repository page, instead of opening a public issue. Include the version, the system and the steps to reproduce it.
