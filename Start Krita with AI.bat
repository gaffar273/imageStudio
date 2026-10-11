@echo off
cd /d "%~dp0"
rem Start Local Image Studio (browser) and Krita with the AI panel; they work together.
"..\..\work\image-env\Scripts\python.exe" -m image_studio.cli.manage --krita
if errorlevel 1 pause
