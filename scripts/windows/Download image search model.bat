@echo off
cd /d "%~dp0..\.."
if exist "..\..\work\search-env\Scripts\python.exe" goto packages
echo Setting up the image search environment (about 1 GB of libraries, one time)...
"..\..\work\image-env\Scripts\python.exe" -m venv "..\..\work\search-env"
if errorlevel 1 goto failed
:packages
"..\..\work\search-env\Scripts\python.exe" -c "import sentence_transformers" 2>nul
if not errorlevel 1 goto model
"..\..\work\search-env\Scripts\python.exe" -m pip install -r backend\requirements-search.txt
if errorlevel 1 goto failed
:model
set tries=0
:retry
"..\..\work\image-env\Scripts\python.exe" -m image_studio.cli.download_model --model search
if not errorlevel 1 goto done
set /a tries+=1
if %tries% geq 40 goto failed
echo Connection dropped. Resuming in 10 seconds... (retry %tries% of 40)
timeout /t 10 /nobreak >nul
goto retry
:failed
echo The download did not finish. Run this file again to resume where it stopped.
:done
if not "%1"=="nopause" pause
