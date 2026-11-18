$ErrorActionPreference = 'Stop'

$running = @(wsl.exe --list --running --quiet 2>$null | ForEach-Object { $_.Trim() })
if ('Ubuntu' -notin $running) {
    $startArguments = @('-d', 'Ubuntu', '--', 'tail', '-f', '/dev/null')
    Start-Process -FilePath "$env:SystemRoot\System32\wsl.exe" -ArgumentList $startArguments -WindowStyle Hidden
}

Write-Host 'SecureCloud Ubuntu lab started.'
Write-Host 'K3s will start through its enabled systemd service.'
