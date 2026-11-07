@echo off
rem IBKR-yhteenveto - kaynnistys Windowsissa: kaksoisklikkaa tata tiedostoa.
rem Ajaa run.ps1:n (Python-tarkistus, .venv, riippuvuudet, palvelin http://127.0.0.1:8501).
rem Lopetus: Ctrl+C tai sulje ikkuna.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
