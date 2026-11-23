@echo off
setlocal

rem ---------------------------------------------------------------------------
rem  ArcGIS Pro Imagery Browser — Windows batch launcher
rem  Launches the GUI using the ArcGIS Pro 3.3 Python interpreter.
rem  No installation or admin rights required.
rem
rem  Usage:
rem    launch.bat                    — open browser (canvas-only if no arcpy)
rem    launch.bat "path\to\map.aprx" — pre-load a specific ArcGIS Pro project
rem ---------------------------------------------------------------------------

rem Check system-wide install first, then per-user install (ArcGIS Pro 3.x supports both).
set "ARCPY=%ProgramFiles%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
if not exist "%ARCPY%" set "ARCPY=%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

if not exist "%ARCPY%" (
    echo WARNING: ArcGIS Pro Python interpreter not found.
    echo Searched:
    echo   %ProgramFiles%\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
    echo   %LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
    echo.
    echo Falling back to system Python ^(arcpy features will be unavailable^)...
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found in PATH.
        echo Install Python 3.9+ or ArcGIS Pro, then try again.
        pause
        exit /b 1
    )
    set "ARCPY=python"
)

rem Change to the directory that contains this batch file so relative imports work.
cd /d "%~dp0"

"%ARCPY%" imagery_browser.py %*

if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)

endlocal
