@echo off
cd /d "%~dp0..\.."
set tries=0
:retry
"..\..\work\image-env\Scripts\python.exe" -m image_studio.cli.download_model --model brain
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
