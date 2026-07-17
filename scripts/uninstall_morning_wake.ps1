<#
  uninstall_morning_wake.ps1 — rimuove l'automazione "risveglio mattina"
  e ripristina le impostazioni di alimentazione precedenti.
  RICHIEDE PRIVILEGI AMMINISTRATORE.
#>
$ErrorActionPreference = 'Continue'
$root       = Split-Path -Parent $PSScriptRoot
$taskName   = 'MediaFlow - Risveglio mattina'
$backupFile = Join-Path $root 'scripts\.morning_prev_standby_ac.txt'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host '[ERRORE] Servono privilegi amministratore.' -ForegroundColor Red
  exit 1
}

# 1) Rimuovi il task
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  Write-Host "✓ Task '$taskName' rimosso."
} else {
  Write-Host "Task '$taskName' non presente."
}

# 2) Ripristina auto-sleep CA dal backup
if (Test-Path $backupFile) {
  $prev = (Get-Content $backupFile -Raw).Trim()
  if ($prev -match '^\d+$') {
    powercfg -change -standby-timeout-ac ([int]$prev) | Out-Null
    Write-Host "✓ Auto-sleep CA ripristinato a $prev min."
  }
  Remove-Item $backupFile -Force -ErrorAction SilentlyContinue
} else {
  Write-Host 'Nessun backup auto-sleep: ripristino a 30 min (default).'
  powercfg -change -standby-timeout-ac 30 | Out-Null
}

# 3) Wake timer CA → ripristina a "solo importanti" (valore di fabbrica tipico)
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 2 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null
Write-Host '✓ Wake timer CA riportato a "solo importanti".'
Write-Host 'Disinstallazione completata.'
