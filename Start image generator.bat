@echo off
cd /d "%~dp0"
"..\..\work\image-env\Scripts\python.exe" -m image_studio.cli.manage
if errorlevel 1 pause
