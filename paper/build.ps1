# Build paper\main.pdf from the LaTeX sources on Windows.
#   powershell -ExecutionPolicy Bypass -File paper\build.ps1
# Needs MiKTeX or TeX Live (latexmk; MiKTeX also needs Perl, or use pdflatex+bibtex below),
# or tectonic:  winget install tectonic  (single exe, downloads packages on first run).
# Optional: -Figures regenerates the two LLM-study figures from the run folders first.
param([switch]$Figures, [string]$SweRun = "runs\peer_study", [string]$MarketRun = "runs\market_entrant")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Figures) {
  Push-Location (Split-Path -Parent $here)
  python paper\analysis\llm_study.py $SweRun $MarketRun --out paper\figs
  Pop-Location
}
Push-Location $here
try {
  if (Get-Command tectonic -ErrorAction SilentlyContinue) {
    tectonic main.tex
  } elseif (Get-Command latexmk -ErrorAction SilentlyContinue) {
    latexmk -xelatex -interaction=nonstopmode -halt-on-error main.tex
  } elseif (Get-Command xelatex -ErrorAction SilentlyContinue) {
    xelatex -interaction=nonstopmode main.tex; bibtex main; xelatex -interaction=nonstopmode main.tex; xelatex -interaction=nonstopmode main.tex
  } else {
    throw "No LaTeX found. Install tectonic (winget install tectonic) or MiKTeX, then re-run."
  }
  Write-Host "Built $here\main.pdf"
} finally { Pop-Location }
