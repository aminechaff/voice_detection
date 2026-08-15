$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvironmentDir = Join-Path $ProjectDir ".venv"
$PythonExe = Join-Path $EnvironmentDir "Scripts\python.exe"
$UvCommand = Get-Command uv -ErrorAction SilentlyContinue

$env:UV_LINK_MODE = "copy"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:PYTHONUTF8 = "1"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Installation initiale de Voice Master..." -ForegroundColor Cyan
    if ($UvCommand) {
        & $UvCommand.Source venv $EnvironmentDir --python 3.11
    }
    else {
        py -3.11 -m venv $EnvironmentDir
    }
}

Write-Host "Verification des dependances..." -ForegroundColor Cyan
if ($UvCommand) {
    & $UvCommand.Source pip install --quiet --python $PythonExe -e $ProjectDir
}
else {
    & $PythonExe -m ensurepip --upgrade
    & $PythonExe -m pip install --quiet --upgrade pip
    & $PythonExe -m pip install --quiet -e $ProjectDir
}

& $PythonExe -c "import customtkinter, faster_whisper, pyaudiowpatch, voicemaster"
if ($LASTEXITCODE -ne 0) {
    throw "L'installation de Voice Master est incomplete."
}

Write-Host "Demarrage de Voice Master..." -ForegroundColor Green
& $PythonExe -m voicemaster
