@echo off
cd /d "%~dp0..\.."
"..\..\work\image-env\Scripts\python.exe" -m image_studio.cli.download_model
pause
