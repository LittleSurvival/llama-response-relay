@echo off
setlocal
cd /d "%~dp0"

set "BUILD_PYTHON=%CD%\.build-venv\Scripts\python.exe"
set "OUTPUT_EXE=%CD%\dist\LlamaCppLauncher.exe"
set "LEGACY_EXE=%CD%\dist\LlamaCppLauncher\LlamaCppLauncher.exe"
set "LEGACY_DIR=%CD%\dist\LlamaCppLauncher"

echo [1/7] Checking whether the packaged app is running...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$targets=@([IO.Path]::GetFullPath('%OUTPUT_EXE%'),[IO.Path]::GetFullPath('%LEGACY_EXE%'));" ^
  "$apps=Get-Process | Where-Object { $_.Path -and $targets -contains [IO.Path]::GetFullPath($_.Path) };" ^
  "if ($apps) {" ^
  "  $answer=if ($env:LRR_BUILD_NONINTERACTIVE) { 'Y' } else { Read-Host 'The packaged Launcher is running. Close it cleanly and continue? [Y/N]' };" ^
  "  if ($answer -notmatch '^(?i)y(es)?$') { exit 2 };" ^
  "  $windows=@($apps | Where-Object MainWindowHandle -ne 0);" ^
  "  if (-not $windows) { Write-Error 'The app is running without a closeable window.'; exit 3 };" ^
  "  foreach ($app in $windows) { if (-not $app.CloseMainWindow()) { Write-Error 'Could not request a clean app shutdown.'; exit 4 } };" ^
  "  $deadline=[DateTime]::UtcNow.AddSeconds(15);" ^
  "  do { Start-Sleep -Milliseconds 100; $remaining=Get-Process | Where-Object { $_.Path -and $targets -contains [IO.Path]::GetFullPath($_.Path) } } while ($remaining -and [DateTime]::UtcNow -lt $deadline);" ^
  "  if ($remaining) { Write-Error 'The app did not close within 15 seconds.'; exit 5 };" ^
  "}"
if errorlevel 1 goto :failed

if not exist "%BUILD_PYTHON%" (
  echo [2/7] Creating isolated build environment...
  python -m venv ".build-venv"
  if errorlevel 1 goto :failed
) else (
  echo [2/7] Reusing isolated build environment...
)

echo [3/7] Installing project and build dependencies...
"%BUILD_PYTHON%" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :failed
"%BUILD_PYTHON%" -m pip install --disable-pip-version-check -e ".[dev]"
if errorlevel 1 goto :failed

echo [4/7] Running automated tests...
set "QT_QPA_PLATFORM=offscreen"
"%BUILD_PYTHON%" -m pytest
if errorlevel 1 goto :failed

echo [5/7] Building console-free onefile package...
"%BUILD_PYTHON%" -m PyInstaller --clean --noconfirm LlamaCppLauncher.spec
if errorlevel 1 goto :failed

if not exist "%OUTPUT_EXE%" (
  echo ERROR: Build finished without producing the expected executable.
  goto :failed
)

echo [6/7] Removing legacy onedir output...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dist=[IO.Path]::GetFullPath('%CD%\dist');" ^
  "$legacy=[IO.Path]::GetFullPath('%LEGACY_DIR%');" ^
  "if (-not $legacy.StartsWith($dist + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { Write-Error 'Unsafe legacy output path.'; exit 6 };" ^
  "if (Test-Path -LiteralPath $legacy) { Remove-Item -LiteralPath $legacy -Recurse -Force }"
if errorlevel 1 goto :failed

echo [7/7] Build complete:
echo %OUTPUT_EXE%
if defined LRR_BUILD_NONINTERACTIVE exit /b 0
explorer.exe /select,"%OUTPUT_EXE%"
pause
exit /b 0

:failed
echo.
echo BUILD FAILED. Review the error above.
if defined LRR_BUILD_NONINTERACTIVE exit /b 1
pause
exit /b 1
