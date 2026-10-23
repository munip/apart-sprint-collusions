<#
  One-time setup on Windows (PowerShell 5+ / 7).  Run from the repo root:
      powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
  Creates:
    .venv\                 project environment (clab, inspect, monitor)
    .cache\fastapi\        FastAPI clone used to build task workspaces
    .cache\fapi-venv\      separate venv in which agents' code + tests run (never the monitor's interpreter)
#>
param([string]$Python = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-Python {
  if ($Python) { return $Python }
  foreach ($c in @("py -3.12", "py -3.13", "py -3.11", "python")) {
    try { $v = & ([scriptblock]::Create("$c -c `"import sys;print(sys.version_info[:2]>=(3,11))`"")) 2>$null
          if ($v -eq "True") { return $c } } catch {}
  }
  throw "Python 3.11+ not found. Install from https://www.python.org/downloads/ (tick 'Add to PATH')."
}
function Run($cmd) { Write-Host "> $cmd" -ForegroundColor DarkGray; & ([scriptblock]::Create($cmd)); if ($LASTEXITCODE) { throw "failed: $cmd" } }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git not found. Install Git for Windows: https://git-scm.com/download/win" }
$py = Find-Python
Write-Host "Using $py" -ForegroundColor Cyan

# UTF-8 mode for Python (FastAPI sources and tests are UTF-8)
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User"); $env:PYTHONUTF8 = "1"

# 1) project venv
if (-not (Test-Path .venv)) { Run "$py -m venv .venv" }
Run ".\.venv\Scripts\python.exe -m pip install -q --upgrade pip"
Run ".\.venv\Scripts\python.exe -m pip install -q -e `".[dev]`""

# 2) FastAPI checkout + isolated test venv
$Cache = Join-Path $Root ".cache"
New-Item -ItemType Directory -Force -Path $Cache | Out-Null
if (-not (Test-Path "$Cache\fastapi\.git")) { Run "git -c core.autocrlf=false clone --filter=blob:none https://github.com/fastapi/fastapi `"$Cache\fastapi`"" }
if (-not (Test-Path "$Cache\fapi-venv")) { Run "$py -m venv `"$Cache\fapi-venv`"" }
$fpy = "$Cache\fapi-venv\Scripts\python.exe"
Run "git -C `"$Cache\fastapi`" -c core.autocrlf=false checkout -q 43f46fb14feeee78f4077a55eb3f95f792b7cd9d"
Push-Location "$Cache\fastapi"
try {
  Run "& `"$fpy`" -m pip install -q --upgrade pip"
  Run "& `"$fpy`" -m pip install -q --group tests pytest-timeout"
  Run "& `"$fpy`" -m pip install -q -e ."
  Run "& `"$fpy`" -m pip uninstall -y -q fastapi"
} finally { Pop-Location }
Run "git -C `"$Cache\fastapi`" checkout -q master"

# 3) smoke checks
Run ".\.venv\Scripts\python.exe -m pytest -q tests"
Run ".\.venv\Scripts\clab.exe providers list"
Write-Host "`nSetup complete. Activate with:  .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
