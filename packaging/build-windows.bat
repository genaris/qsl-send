@echo off
REM Build the Windows application locally.
REM Run this from the project root on a Windows PC that has Python 3.11+:
REM     packaging\build-windows.bat

setlocal
echo === Creating a clean build environment ===
python -m venv .build-venv || goto :err
call .build-venv\Scripts\activate.bat || goto :err

echo === Installing dependencies ===
python -m pip install --upgrade pip >nul
python -m pip install pyinstaller Pillow PyYAML requests || goto :err

echo === Building the application ===
pyinstaller packaging\qsl-send.spec --noconfirm --distpath dist --workpath build || goto :err

echo.
echo Done. The application is in:  dist\QSL Sender\
echo Run "dist\QSL Sender\QSL Sender.exe" to test it.
echo.
echo To build the installer as well, install Inno Setup and run:
echo     iscc packaging\installer.iss
goto :eof

:err
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
