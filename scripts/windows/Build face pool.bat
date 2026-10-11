@echo off
cd /d "%~dp0..\.."
rem Fills the work\face-pool folder with 48 generated portraits of invented people (about 15 minutes).
rem Stop the image generator first so the GPU is free.
"..\..\work\image-env\Scripts\python.exe" -m image_studio.services.faces build
if not "%1"=="nopause" pause
