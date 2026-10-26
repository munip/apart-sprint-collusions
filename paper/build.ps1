# Build main_long.pdf (default; -Doc main for the short version) from the LaTeX sources on Windows (run from this folder or anywhere):
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
# Looks for tectonic / latexmk / xelatex first NEXT TO THIS SCRIPT, then on PATH.
# Needs XeLaTeX (fonts in .\fonts): tectonic (winget install tectonic, or tectonic.exe in this folder) or MiKTeX.
# Optional: -Figures regenerates the LLM-study figures from the run folders first (run from the repo's paper\ folder).
param([string]$Doc = "main_long", [switch]$Figures, [string]$SweRun = "runs\peer_study", [string]$MarketRun = "runs\market_entrant")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Tool([string]$name) {
  $local = Join-Path $here "$name.exe"
  if (Test-Path $local) { return $local }
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

if ($Figures) {
  Push-Location (Split-Path -Parent $here)
  python paper\analysis\llm_study.py $SweRun $MarketRun --out paper\figs
  Pop-Location
}
Push-Location $here
try {
  $tectonic = Find-Tool "tectonic"
  $latexmk  = Find-Tool "latexmk"
  $xelatex  = Find-Tool "xelatex"
  if ($tectonic) {
    Write-Host "Using $tectonic"
    & $tectonic "$Doc.tex"
  } elseif ($latexmk -and $xelatex) {
    Write-Host "Using $latexmk (XeLaTeX)"
    & $latexmk -xelatex -interaction=nonstopmode -halt-on-error "$Doc.tex"
  } elseif ($xelatex) {
    Write-Host "Using $xelatex"
    & $xelatex -interaction=nonstopmode "$Doc.tex"; & bibtex $Doc; & $xelatex -interaction=nonstopmode "$Doc.tex"; & $xelatex -interaction=nonstopmode "$Doc.tex"
  } else {
    throw "No LaTeX found. Put tectonic.exe next to build.ps1, or install tectonic (winget install tectonic) or MiKTeX."
  }
  if ($LASTEXITCODE -ne 0) { throw "LaTeX build failed (exit $LASTEXITCODE); see the log above." }
  Write-Host "Built $here\$Doc.pdf"
} finally { Pop-Location }
