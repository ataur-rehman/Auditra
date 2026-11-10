<#
Builds agent\dist\AuditraAgent.exe: one file that is both the installer and the Windows service.

    powershell -ExecutionPolicy Bypass -File agent\build.ps1 -Server https://auditra-api.up.railway.app
    powershell -ExecutionPolicy Bypass -File agent\build.ps1 -Server http://192.168.43.20:8000   # LAN demo

-Server is only the address pre-filled in the setup window; the person installing can change it.
No secret is built in: each laptop enrols with a one-time code from the console.
Optional -Release uploads the exe to the latest GitHub release of this repository (needs gh).
#>
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [switch]$Release
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -m pip install --quiet -r requirements.txt
python -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw 'Agent tests failed; not building.' }

$build = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force -Path $build | Out-Null
$defaults = Join-Path $build 'defaults.json'
@{ server = $Server.TrimEnd('/') } | ConvertTo-Json | Set-Content -Path $defaults -Encoding utf8

python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name AuditraAgent `
    --add-data "$defaults;." `
    --hidden-import win32timezone `
    --hidden-import watchdog.observers.read_directory_changes `
    --collect-submodules watchdog `
    --distpath (Join-Path $PSScriptRoot 'dist') `
    --workpath $build `
    --specpath $build `
    run_agent.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

$exe = Join-Path $PSScriptRoot 'dist\AuditraAgent.exe'
Write-Host "Built $exe (server $Server)" -ForegroundColor Green

if ($Release) {
    gh release upload (gh release view --json tagName -q .tagName) $exe --clobber
    Write-Host 'Uploaded to the latest GitHub release.' -ForegroundColor Green
}
