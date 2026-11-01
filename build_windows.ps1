# B-Roll Finder local Windows build. Run on Windows 10/11 with Python 3.12.
#   powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
# Optional code signing (only if you own a certificate):
#   .\build_windows.ps1 -Sign -CertThumbprint "ABC123..."
# Without a certificate the installer is UNSIGNED: Windows SmartScreen will
# show "More info -> Run anyway", and PCs with Smart App Control may block it.
# See README.md section "Code signing" before sending it to students.
param(
  [switch]$Sign,
  [string]$CertThumbprint = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "1. Python packages..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

Write-Host "2. Tests..."
python -m pytest tests -q

Write-Host "3. Frontend (React)..."
Set-Location frontend
npm ci
npm run build
Set-Location ..

Write-Host "4. PyInstaller (onedir, no console)..."
pyinstaller broll_finder.spec

Write-Host "5. Bundled helpers: ffmpeg + yt-dlp + WebView2 bootstrapper..."
$dist = "dist\BRollFinder"
if (-not (Test-Path "$dist\ffmpeg.exe")) {
  Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile "$env:TEMP\ffmpeg.zip"
  Expand-Archive "$env:TEMP\ffmpeg.zip" -DestinationPath "$env:TEMP\ffmpeg" -Force
  Copy-Item "$env:TEMP\ffmpeg\ffmpeg-*-essentials_build\bin\ffmpeg.exe" "$dist\ffmpeg.exe"
}
if (-not (Test-Path "$dist\yt-dlp.exe")) {
  Invoke-WebRequest -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile "$dist\yt-dlp.exe"
}
if (-not (Test-Path "installer\MicrosoftEdgeWebview2Setup.exe")) {
  Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile "installer\MicrosoftEdgeWebview2Setup.exe"
}

if ($Sign) {
  if (-not $CertThumbprint) { throw "Signing needs -CertThumbprint (your code-signing certificate)." }
  Write-Host "6. Signing (signtool)..."
  $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" | Select-Object -First 1 -ExpandProperty FullName
  Get-ChildItem -Recurse -Include *.exe,*.dll $dist | ForEach-Object {
    & $signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /sha1 $CertThumbprint $_.FullName
  }
}

Write-Host "7. Inno Setup installer..."
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\broll_finder.iss

if ($Sign) {
  $signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" | Select-Object -First 1 -ExpandProperty FullName
  Get-ChildItem installer-output\*.exe | ForEach-Object {
    & $signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /sha1 $CertThumbprint $_.FullName
  }
}

Write-Host "DONE. Installer is in installer-output\BRollFinder-Setup-1.0.0.exe"
