# IBKR-yhteenveto - asennus/päivitys + käynnistys yhdellä komennolla (Windows PowerShell):
#
#   irm https://raw.githubusercontent.com/vilpponen/IBKR-yhteenveto/main/install.ps1 | iex
#
# Mitä skripti tekee:
#   1. tarkistaa, että Python 3.10+ löytyy - mitään ei asenneta järjestelmään
#   2. lataa uusimman version zip-pakettina GitHubista väliaikaiskansioon
#   3. asentaa sen kansioon, jossa komento ajetaan (suositus: luo ensin tyhjä kansio ja siirry siihen):
#        - jos nykyinen kansio on tyhjä -> asentaa siihen
#        - jos nykyinen kansio on jo IBKR-yhteenveto -> päivittää sen
#        - muuten (esim. kotikansio) luo/päivittää alikansion .\IBKR-yhteenveto
#      (.venv ja kansioon itse tallentamasi tiedostot säilyvät päivityksessä)
#   4. käynnistää run.ps1:n -> http://127.0.0.1:8501 (lopetus Ctrl+C)
#
# Saman komennon voi ajaa uudelleen samassa paikassa milloin tahansa: se päivittää ja käynnistää.
# Myöhemmin pelkkä käynnistys: kaksoisklikkaa kansion run.cmd.
# Asetukset: $env:IBKR_DIR (ohittaa yllä olevan), $env:IBKR_ZIP_URL (zip-osoite tai paikallinen polku),
#            $env:IBKR_RUN_ARGS (lisäargumentit server.py:lle, esim. "--port 8600").
# Poisto: poista IBKR-yhteenveto-kansio.

# Kaikki on funktiossa: muuttujat ja asetukset eivät jää PowerShell-istuntoon, ja virhe ei sulje ikkunaa.
function Install-IbkrYhteenveto {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest on muuten hyvin hidas
    $url = 'https://github.com/vilpponen/IBKR-yhteenveto/archive/refs/heads/main.zip'
    if ($env:IBKR_ZIP_URL) { $url = $env:IBKR_ZIP_URL }
    $here = (Get-Location).ProviderPath

    function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
    function Test-App($d) {
        (Test-Path -LiteralPath (Join-Path $d 'server.py')) -and (Test-Path -LiteralPath (Join-Path $d 'ibkr_yhteenveto'))
    }
    function Test-Empty($d) {
        -not (Get-ChildItem -LiteralPath $d -Force -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -notin @('desktop.ini', '.DS_Store') })
    }

    if ($env:IBKR_DIR) { $dir = $env:IBKR_DIR }
    elseif ((Test-App $here) -or (Test-Empty $here)) { $dir = $here }
    else { $dir = Join-Path $here 'IBKR-yhteenveto' }

    Step '1/4  Tarkistetaan Python'
    $found = $false
    foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $pre = @($c | Select-Object -Skip 1)
        $ErrorActionPreference = 'Continue'
        & $c[0] @pre -c 'import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        $ok = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = 'Stop'
        if ($ok) { $found = $true; break }
    }
    if (-not $found) {
        throw ("Tarvitaan Python 3.10 tai uudempi. Asenna osoitteesta https://www.python.org/downloads/ " +
               "(ruksi 'Add python.exe to PATH') tai: winget install Python.Python.3.12 - avaa sitten uusi " +
               "PowerShell-ikkuna ja aja sama komento uudelleen.")
    }

    Step "2/4  Ladataan $url"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('ibkr-yhteenveto-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'app.zip'
        if (Test-Path -LiteralPath $url) {
            Copy-Item -LiteralPath $url -Destination $zip   # testikäyttöön: paikallinen zip
        } else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing }
            catch { throw "Lataus epäonnistui: $url ($($_.Exception.Message))" }
        }
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp 'x')
        $src = Get-ChildItem -LiteralPath (Join-Path $tmp 'x') -Directory | Select-Object -First 1
        if (-not $src -or -not (Test-App $src.FullName)) { throw 'Ladattu paketti ei ole IBKR-yhteenveto.' }

        if (Test-App $dir) {
            Step "3/4  Päivitetään $dir"
        } elseif ((Test-Path -LiteralPath $dir) -and -not (Test-Empty $dir)) {
            throw "$dir on olemassa, mutta se ei ole IBKR-yhteenveto-kansio. Aja komento toisessa kansiossa."
        } else {
            Step "3/4  Asennetaan kansioon $dir"
            try { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            catch { throw "Kansioon $dir ei voi kirjoittaa. Luo kansio esim. kotikansioon: mkdir `$HOME\IBKR-yhteenveto" }
        }
        # Paketin kansiot korvataan kokonaan (vanhentuneet tiedostot pois); .venv ja omat tiedostot jäävät.
        foreach ($item in Get-ChildItem -LiteralPath $src.FullName -Force) {
            $target = Join-Path $dir $item.Name
            if ($item.PSIsContainer -and (Test-Path -LiteralPath $target)) { Remove-Item -LiteralPath $target -Recurse -Force }
            Copy-Item -LiteralPath $item.FullName -Destination $dir -Recurse -Force
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }

    Step '4/4  Käynnistetään'
    $runArgs = @()
    if ($env:IBKR_RUN_ARGS) { $runArgs = @($env:IBKR_RUN_ARGS -split '\s+' | Where-Object { $_ }) }
    $shell = (Get-Process -Id $PID).Path    # sama PowerShell (5.1 tai 7), ExecutionPolicy ohitetaan vain tälle ajolle
    & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'run.ps1') @runArgs
}

try { Install-IbkrYhteenveto }
catch { Write-Host "`nVirhe: $($_.Exception.Message)" -ForegroundColor Red; $global:LASTEXITCODE = 1 }
