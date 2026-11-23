@echo off
setlocal
rem ---------------------------------------------------------------------------
rem  Imagery Browser — self-contained build
rem  Produces dist\ImageryBrowser\ImageryBrowser.exe, which runs with NO ArcGIS
rem  Pro and NO pre-installed Python on the target machine.
rem
rem  Run this on a DEV machine that has internet access. Then copy the whole
rem  dist\ImageryBrowser folder to the air-gapped target.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"
echo === Imagery Browser - standalone build ===

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH. Install Python 3.11+ and retry.
    pause
    exit /b 1
)

echo.
echo [1/4] Installing build dependencies...
python -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo ERROR: dependency install failed.
    pause
    exit /b 1
)

echo.
echo [2/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist "dist\ImageryBrowser" rmdir /s /q "dist\ImageryBrowser"

echo.
echo [3/4] Building with PyInstaller (this can take a few minutes)...
python -m PyInstaller --noconfirm --clean imagery_browser.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Verifying the build (self-test)...
"dist\ImageryBrowser\ImageryBrowser.exe" --selftest
if exist "dist\ImageryBrowser\selftest_result.txt" type "dist\ImageryBrowser\selftest_result.txt"
if errorlevel 1 (
    echo.
    echo WARNING: self-test reported a problem - see output above.
) else (
    echo.
    echo Self-test passed.
)

echo.
echo === Build complete ===
echo Output: dist\ImageryBrowser\ImageryBrowser.exe
echo Copy the ENTIRE dist\ImageryBrowser folder to the target machine and run the .exe.
pause
endlocal
