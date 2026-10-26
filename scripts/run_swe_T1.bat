@echo off
REM ============================================================================================
REM  SWE study 2, T1 half (docs/PREREG.md section 6b): 20 episodes, roughly 2-3 hours with 2 workers.
REM  Needs: Windows 10/11, Git for Windows, Python 3.11+ (tick "Add to PATH"), an Ollama Cloud API key.
REM  Usage: put this file in an empty folder, double-click it (or run it from cmd). It is safe to re-run:
REM         the run resumes and skips finished episodes (e.g. after the free-tier quota refills).
REM ============================================================================================
setlocal
set REPO_URL=https://github.com/munip/apart-sprint-collusions
set BRANCH=feature/swe-study2

REM ---- 1. get the code (first time only), then update it
if not exist apart-sprint-collusions (
  git clone %REPO_URL% || goto :fail
)
cd apart-sprint-collusions || goto :fail
git fetch origin || goto :fail
git checkout %BRANCH% || goto :fail
git pull --ff-only || goto :fail

REM ---- 2. one-time setup: project venv, FastAPI checkout, isolated test venv (~10 minutes)
if not exist .cache\fapi-venv (
  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 || goto :fail
)

REM ---- 3. API key: create .env with your own Ollama Cloud key (first time only)
if not exist .env (
  echo OLLAMA_API_KEY=paste-your-ollama-cloud-key-here> .env
  echo.
  echo A file .env was created. Put your Ollama Cloud API key in it, save, close Notepad.
  notepad .env
)

call .venv\Scripts\activate.bat || goto :fail
set PYTHONUTF8=1

REM ---- 4. check the model answers (should print text=ok for ollama_cloud/gemma4:31b)
clab models check --profile free_pinned --probe --role default=ollama_cloud/gemma4:31b

REM ---- 5. run the 20 T1 episodes (resumable)
clab run configs\experiments\swe_study2_T1.yaml --out runs\swe_study2_T1 --workers 2 --role default=ollama_cloud/gemma4:31b
if errorlevel 1 echo The run stopped with an error (often the usage cap). Re-run this file later to continue.

REM ---- 6. pack the results to send back (zip next to this folder)
powershell -Command "Compress-Archive -Force -Path runs\swe_study2_T1 -DestinationPath ..\swe_study2_T1.zip"
echo.
echo Done. Send ..\swe_study2_T1.zip back. Re-running this file continues any unfinished episodes.
goto :eof

:fail
echo Something failed above. Check that Git and Python 3.11+ are installed and on PATH, then re-run.
exit /b 1
