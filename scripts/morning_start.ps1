<#
  morning_start.ps1 — routine mattutina MediaFlow.
  Lanciato dal task "MediaFlow - Risveglio mattina" quando il PC si sveglia
  dall'ibernazione (vedi install_morning_wake.ps1).

  Fa 3 cose:
    1. Avvia il server MediaFlow (localhost:8000) — libera prima la porta da
       eventuali processi zombie.
    2. Avvia il tunnel cloudflared → URL pubblico trycloudflare (loggato).
    3. Apre una console visibile con `claude remote-control` nella cartella
       progetto (resta aperta: e' un daemon, mostra URL/QR per il telefono).

  Tutto loggato in logs\morning.log. Non interattivo, idempotente sulla porta.
#>

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot          # ...\mediaflow_fase1bis
$py   = Join-Path $root '.venv\Scripts\python.exe'
$cfd  = Join-Path $env:USERPROFILE 'cloudflared\cloudflared.exe'
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$log = Join-Path $logDir 'morning.log'

function Log($msg) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content -Path $log -Value "[$ts] $msg"
}

Log '──────── risveglio: avvio routine mattutina ────────'

# 1) Server MediaFlow — libera porta 8000 da zombie, poi avvia
try {
  Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  if (Test-Path $py) {
    Start-Process -FilePath $py -ArgumentList 'run.py' -WorkingDirectory $root -WindowStyle Hidden
    Log "server avviato ($py run.py)"
  } else {
    Log "ERRORE: venv python non trovato in $py"
  }
} catch { Log "ERRORE avvio server: $($_.Exception.Message)" }

# Attendi /health (max ~60s)
$up = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  try {
    $r = & curl.exe -s http://localhost:8000/health
    if ($r -match '"status":"ok"') { $up = $true; break }
  } catch {}
}
if ($up) { Log 'server UP (/health ok)' } else { Log 'server NON risponde dopo 60s (continuo comunque)' }

# 2) Tunnel cloudflared → URL pubblico
try {
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  if (Test-Path $cfd) {
    $terr = Join-Path $logDir 'tunnel.err'
    $tout = Join-Path $logDir 'tunnel.out'
    if (Test-Path $terr) { Clear-Content $terr }
    Start-Process -FilePath $cfd -ArgumentList 'tunnel','--url','http://localhost:8000' `
      -WorkingDirectory $root -WindowStyle Hidden `
      -RedirectStandardError $terr -RedirectStandardOutput $tout
    # Cattura URL pubblico
    $url = $null
    for ($i = 0; $i -lt 20; $i++) {
      Start-Sleep -Seconds 2
      $m = Select-String -Path $terr,$tout -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($m) { $url = $m.Matches[0].Value; break }
    }
    if ($url) {
      Log "tunnel UP: $url"
      Set-Content -Path (Join-Path $logDir 'tunnel-url.txt') -Value $url -Encoding utf8
    } else { Log 'tunnel avviato ma URL non catturato (vedi logs\tunnel.err)' }
  } else {
    Log "cloudflared non trovato in $cfd — tunnel saltato"
  }
} catch { Log "ERRORE tunnel: $($_.Exception.Message)" }

# 3) Claude Code in remote-control (console visibile, resta aperta)
try {
  # cmd /k mantiene la finestra aperta; claude remote-control mostra URL+QR.
  Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/k', "cd /d `"$root`" && claude remote-control --name `"MediaFlow RC`"" `
    -WorkingDirectory $root
  Log 'claude remote-control avviato (console visibile)'
} catch { Log "ERRORE claude remote-control: $($_.Exception.Message)" }

Log 'routine mattutina completata'
