# Pasang / lepas autostart FinTrack Bot (Windows Task Scheduler, jalan saat login).
#
#   powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 install
#   powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 uninstall
#   powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 status

param([ValidateSet("install", "uninstall", "status")][string]$Action = "status")

$ErrorActionPreference = "Stop"
$TaskName = "FinTrack Bot"
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

switch ($Action) {
    "install" {
        if (-not (Test-Path $Pythonw)) { throw "Tidak menemukan $Pythonw" }
        $taskAction = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m scripts.run_server" -WorkingDirectory $Root
        # Tunda 30 dtk setelah login supaya Wi-Fi sempat tersambung.
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $trigger.Delay = "PT30S"
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -MultipleInstances IgnoreNew -StartWhenAvailable
        Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $trigger -Settings $settings `
            -Description "Bot Telegram FinTrack (pencatat keuangan). Log: $Root\logs" -Force | Out-Null
        Write-Output "Autostart '$TaskName' terpasang."
    }
    "uninstall" {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
            Where-Object { $_.CommandLine -like "*scripts.run_server*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Write-Output "Autostart '$TaskName' dilepas dan bot dihentikan."
    }
    "status" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) { Write-Output "Autostart belum terpasang."; break }
        $proc = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
            Where-Object { $_.CommandLine -like "*scripts.run_server*" }
        Write-Output ("Autostart: terpasang ({0})" -f $task.State)
        if ($proc) {
            # venv pythonw = peluncur kecil + interpreter asli, jadi bisa 2 proses.
            $mb = ($proc | ForEach-Object { (Get-Process -Id $_.ProcessId).WorkingSet64 } | Measure-Object -Sum).Sum / 1MB
            Write-Output ("Bot: BERJALAN ({0:N0} MB RAM)" -f $mb)
        } else {
            Write-Output "Bot: tidak berjalan"
        }
    }
}
