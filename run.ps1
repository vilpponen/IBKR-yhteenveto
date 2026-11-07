# IBKR-yhteenveto - käynnistys Windowsissa: kaksoisklikkaa run.cmd
# (tai PowerShellissä: powershell -ExecutionPolicy Bypass -File run.ps1)
#
# Mitä skripti tekee:
#   1. etsii Pythonin 3.10+ (py -3, python, python3)
#   2. luo yksityisen virtuaaliympäristön .\.venv (mitään ei asenneta järjestelmään)
#   3. asentaa requirements.txt:n (pdfplumber, openpyxl) - vain jos ei jo asennettu
#   4. käynnistää paikallisen palvelimen (server.py) -> http://127.0.0.1:8501, lopetus Ctrl+C
# Lisäargumentit välitetään server.py:lle, esim. run.cmd --port 8600
# Poisto: poista .venv-kansio.

$ErrorActionPreference = 'Continue'   # natiivikomentojen virheet tarkistetaan $LASTEXITCODE:lla
Set-Location -LiteralPath $PSScriptRoot

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`nVirhe: $m" -ForegroundColor Red; exit 1 }

function Find-Python {
    foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $pre = @($c | Select-Object -Skip 1)
        & $c[0] @pre -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return , $c }
    }
    return $null
}

Step '1/4  Python'
$py = Find-Python
if (-not $py) {
    Fail ("Tarvitaan Python 3.10 tai uudempi. Asenna osoitteesta https://www.python.org/downloads/ " +
          "(ruksi 'Add python.exe to PATH') tai: winget install Python.Python.3.12 - avaa sitten uusi ikkuna ja yritä uudelleen.")
}
$pyArgs = @($py | Select-Object -Skip 1)
& $py[0] @pyArgs --version

Step '2/4  Virtuaaliympäristö (.venv)'
$vpy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $vpy)) {
    & $py[0] @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $vpy)) { Fail '.venv-kansion luonti epäonnistui.' }
} else {
    Write-Host '.venv on jo olemassa - käytetään sitä'
}

Step '3/4  Riippuvuudet (requirements.txt)'
$marker = Join-Path $PSScriptRoot '.venv\.install-complete'
$req = Join-Path $PSScriptRoot 'requirements.txt'
if ((Test-Path -LiteralPath $marker) -and ((Get-FileHash $marker).Hash -eq (Get-FileHash $req).Hash)) {
    Write-Host 'Riippuvuudet jo asennettu - ohitetaan (poista .venv pakottaaksesi uudelleenasennuksen)'
} else {
    & $vpy -m pip install --upgrade pip
    & $vpy -m pip install -r $req
    if ($LASTEXITCODE -ne 0) { Fail 'Riippuvuuksien asennus epäonnistui (verkkoyhteys?). Aja uudelleen - asennus jatkuu.' }
    & $vpy -c "import pdfplumber, openpyxl; print('imports OK')"
    if ($LASTEXITCODE -ne 0) { Fail 'Riippuvuudet eivät lataudu.' }
    Copy-Item -LiteralPath $req -Destination $marker -Force
}

Step '4/4  Käynnistetään http://127.0.0.1:8501  (Ctrl+C lopettaa)'
& $vpy server.py @args
exit $LASTEXITCODE
