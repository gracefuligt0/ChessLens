param([string]$Python='python',[switch]$SkipInstall)
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $SkipInstall) {
    $taskEnvironment=Join-Path $taskRoot '.venv-build'
    if (-not (Test-Path -LiteralPath (Join-Path $taskEnvironment 'Scripts\python.exe'))) {
        & $Python -m venv $taskEnvironment
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
    }
    $Python=Join-Path $taskEnvironment 'Scripts\python.exe'
    & $Python -m pip install -r (Join-Path $taskRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $Python (Join-Path $PSScriptRoot 'fetch_engine.py')
if ($LASTEXITCODE -ne 0) { throw 'Stockfish verification failed.' }
& $Python (Join-Path $PSScriptRoot 'generate_extensions.py')
if ($LASTEXITCODE -ne 0) { throw 'Connector generation failed.' }
$taskAssets=Join-Path $taskRoot 'src\assets'
$env:PYTHONHASHSEED='0'
& $Python -m PyInstaller --noconfirm --windowed --onedir --name ChessLens --contents-directory _internal --distpath (Join-Path $taskRoot 'dist') --workpath (Join-Path $taskRoot 'build\pyinstaller') --specpath (Join-Path $taskRoot 'build') --add-data "$taskAssets;assets" --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtMultimedia --exclude-module tkinter (Join-Path $taskRoot 'src\overlay.py')
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
$taskApp=Join-Path $taskRoot 'dist\ChessLens'
# Use the supported Windows 10/11 ICU interface, not an incompatible DLL from PATH.
$taskIcu=Join-Path $taskApp '_internal\icuuc.dll'
if (Test-Path -LiteralPath $taskIcu) { Move-Item -LiteralPath $taskIcu -Destination (Join-Path $taskRoot 'build\icuuc-excluded.dll') -Force }
Copy-Item -LiteralPath (Join-Path $taskRoot 'browser-extension\chromium') -Destination (Join-Path $taskApp 'Browser-Connector') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $taskRoot 'browser-extension\firefox') -Destination (Join-Path $taskApp 'Firefox-Connector') -Recurse -Force
foreach ($taskFile in @('README.md','LICENSE','THIRD-PARTY-NOTICES.md')) { Copy-Item -LiteralPath (Join-Path $taskRoot $taskFile) -Destination $taskApp -Force }
Copy-Item -LiteralPath (Join-Path $taskRoot 'licenses') -Destination $taskApp -Recurse -Force
Copy-Item -LiteralPath (Join-Path $taskRoot 'docs') -Destination $taskApp -Recurse -Force
Copy-Item -LiteralPath (Join-Path $taskRoot 'SOURCE.txt') -Destination $taskApp -Force
Write-Host "Built $taskApp\ChessLens.exe"
