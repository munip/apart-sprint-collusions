#!/usr/bin/env bash
# Build paper/main.pdf from the LaTeX sources. Usage: bash paper/build.sh   (run from anywhere)
# Needs TeX Live / MacTeX (latexmk) or tectonic (https://tectonic-typesetting.github.io, one binary).
set -e
cd "$(dirname "$0")"
if command -v latexmk >/dev/null; then
  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
elif command -v tectonic >/dev/null; then
  tectonic main.tex
else
  echo "No LaTeX found. Install TeX Live (latexmk) or tectonic, then re-run." >&2; exit 1
fi
echo "Built $(pwd)/main.pdf"
