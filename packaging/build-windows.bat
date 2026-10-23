@echo off
rem simpleplay - builds the Windows version on a Windows machine.
rem Result: dist\simpleplay\simpleplay.exe  and  dist\simpleplay-VERSION-windows-x64.zip
rem Needs Python 3.13 from python.org with "Add Python to PATH" ticked. Run it from anywhere.
setlocal
cd /d "%~dp0\.."

for /f "tokens=2 delims== " %%v in ('findstr /b /c:"VERSION = " simpleplay.py') do set VER=%%~v

if not exist .venv-build (
    py -3.13 -m venv .venv-build || goto :error
)
.venv-build\Scripts\python -m pip install --upgrade pip || goto :error
.venv-build\Scripts\pip install -r requirements.txt pyinstaller || goto :error

.venv-build\Scripts\pyinstaller --noconfirm --clean --onedir --windowed --name simpleplay ^
    --icon icon\simpleplay.ico --add-data "icon\simpleplay-256.png;icon" --add-data "icon\simpleplay-512.png;icon" ^
    --hidden-import simpleplay_mosquito --hidden-import qrcode --hidden-import miniaudio --hidden-import _cffi_backend --collect-data certifi ^
    --exclude-module tkinter --exclude-module PIL simpleplay.py || goto :error

powershell -NoProfile -Command "Compress-Archive -Path 'dist\simpleplay\*' -DestinationPath 'dist\simpleplay-%VER%-windows-x64.zip' -Force" || goto :error

echo.
echo Done: dist\simpleplay\simpleplay.exe  and  dist\simpleplay-%VER%-windows-x64.zip
exit /b 0

:error
echo.
echo Something failed. Copy the messages above and send them.
exit /b 1
