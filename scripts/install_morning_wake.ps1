<#
  install_morning_wake.ps1 — installa l'automazione "risveglio mattina".

  Crea:
    1. Wake timer abilitato su alimentazione CA (necessario per svegliarsi
       da ibernazione a orario). Batteria (CC) lasciata disabilitata →
       il PC NON si sveglia mai a batteria/in borsa. Sicuro.
    2. Auto-sleep CA disabilitato (standby-timeout-ac = 0) così, dopo il
       risveglio, il PC resta sveglio e raggiungibile. Il valore precedente
       viene salvato per il ripristino. Batteria invariata.
    3. Task pianificato "MediaFlow - Risveglio mattina": ogni giorno alle
       08:00, "Riattiva il computer", lancia morning_start.ps1.

  RICHIEDE PRIVILEGI AMMINISTRATORE (powercfg + WakeToRun).
  Disinstalla con: uninstall_morning_wake.ps1

  Orario modificabile col parametro -At (es. -At '07:30').
#>
param(
  [string]$At = '08:00'
)

$ErrorActionPreference = 'Stop'
$root       = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $root 'scripts\morning_start.ps1'
$taskName   = 'MediaFlow - Risveglio mattina'
$backupFile = Join-Path $root 'scripts\.morning_prev_standby_ac.txt'

# --- Check elevazione ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host '[ERRORE] Servono privilegi amministratore.' -ForegroundColor Red
  Write-Host 'Apri PowerShell come amministratore e rilancia:' -ForegroundColor Yellow
  Write-Host "  & '$PSCommandPath'" -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path $scriptPath)) { throw "morning_start.ps1 non trovato in $scriptPath" }

# --- 1) Abilita wake timer su CA (lascia CC disabilitato) ---
Write-Host '[1/3] Abilito wake timer (CA)…'
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null

# --- 2) Disabilita auto-sleep su CA (backup del valore corrente) ---
Write-Host '[2/3] Disabilito auto-sleep su CA (con backup)…'
$q = powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Out-String
$m = [regex]::Match($q, 'CA[^:]*:\s*0x([0-9a-fA-F]+)')
if ($m.Success) {
  $prevSeconds = [Convert]::ToInt32($m.Groups[1].Value, 16)
  $prevMinutes = [int]($prevSeconds / 60)
  Set-Content -Path $backupFile -Value $prevMinutes -Encoding utf8
  Write-Host "      valore precedente CA: $prevMinutes min (salvato)"
} else {
  Write-Host '      impossibile leggere il valore precedente (uso 30 min come ripristino di default)'
  Set-Content -Path $backupFile -Value 30 -Encoding utf8
}
powercfg -change -standby-timeout-ac 0 | Out-Null

# --- 3) Registra il task pianificato ---
Write-Host "[3/3] Registro il task pianificato (ogni giorno $At)…"
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force `
  -Description 'Sveglia il PC dall''ibernazione e avvia MediaFlow (server + tunnel + claude remote-control).' | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Host ''
Write-Host "✓ Installato. Prossima esecuzione: $($info.NextRunTime)" -ForegroundColor Green
Write-Host "  Task: '$taskName'  ·  orario: $At ogni giorno"
Write-Host '  TEST: iberna il PC (Start ▸ Arresta ▸ Iberna, collegato a corrente).'
Write-Host '        Se all''orario impostato si sveglia da solo → funziona.'
Write-Host '  Disinstalla: scripts\uninstall_morning_wake.ps1 (come admin)'
