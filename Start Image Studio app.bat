@echo off
rem Opens Image Studio as a desktop app. The app starts the engine itself and stops it on close.
cd /d "%~dp0"
start "" "..\..\work\image-env\Scripts\pythonw.exe" -m image_studio.desktop
