# Build the Windows app and its installer:
#   dist\rmpp-studio\rmpp-studio.exe          (PyInstaller, one folder, no console)
#   dist\rmpp-studio-setup-<version>.exe       (Inno Setup, per-user install)
# Needs: Python 3 with Pillow + PyInstaller, Inno Setup 6, and the tablet binaries in build\ (./build.sh).
#   powershell -ExecutionPolicy Bypass -File windows\build.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (Select-String -Path rmpp_ctl.py -Pattern '^__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "rmpp-studio $version"

foreach ($f in 'build\librmpp-remote.so', 'build\rmpp-remote') {
    if (-not (Test-Path $f)) { throw "$f missing: run ./build.sh (Git Bash) first" }
}
if (-not (Test-Path windows\rmpp-studio.ico)) { python windows\make_icon.py }

# exe version resource
$v = ($version.Split('.') + @('0', '0', '0', '0'))[0..3] -join ', '
$vs = ($version.Split('.') + @('0', '0', '0', '0'))[0..3] -join '.'
New-Item -ItemType Directory -Force build\pyinstaller | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v), prodvers=($v), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'lorancecall'),
    StringStruct('FileDescription', 'rmpp-studio'),
    StringStruct('FileVersion', '$vs'),
    StringStruct('InternalName', 'rmpp-studio'),
    StringStruct('LegalCopyright', 'GPL-3.0-only'),
    StringStruct('OriginalFilename', 'rmpp-studio.exe'),
    StringStruct('ProductName', 'rmpp-studio'),
    StringStruct('ProductVersion', '$vs')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding utf8 build\pyinstaller\version.txt

python -m PyInstaller --noconfirm --clean --windowed --name rmpp-studio `
    --icon "$root\windows\rmpp-studio.ico" `
    --version-file "$root\build\pyinstaller\version.txt" `
    --add-data "$root\windows\rmpp-studio.ico;." `
    --add-data "$root\windows\rmpp-studio.png;." `
    --add-data "$root\windows\pen-cursor.png;." `
    --add-data "$root\tutorials\*.tut;tutorials" `
    --add-data "$root\build\librmpp-remote.so;tablet" `
    --add-data "$root\build\rmpp-remote;tablet" `
    --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module tkinter `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtCharts `
    --distpath dist --workpath build\pyinstaller --specpath build\pyinstaller `
    rmpp-studio.pyw
if ($LASTEXITCODE) { throw "PyInstaller failed" }

# the command-line tool: its own self-contained console program (Python + Pillow, no Qt), installed into {app}\cli
python -m PyInstaller --noconfirm --clean --console --name rmpp-ctl `
    --icon "$root\windows\rmpp-studio.ico" `
    --version-file "$root\build\pyinstaller\version.txt" `
    --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module tkinter --exclude-module PySide6 `
    --distpath dist --workpath build\pyinstaller-cli --specpath build\pyinstaller-cli `
    rmpp-ctl.py
if ($LASTEXITCODE) { throw "PyInstaller (rmpp-ctl) failed" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc /Q "/DAppVersion=$version" windows\rmpp-studio.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Get-Item "dist\rmpp-studio-setup-$version.exe" | Select-Object Name, Length
