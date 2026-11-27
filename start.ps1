[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$StatusOnly,
    # Leave services running after the launcher exits (the old Ctrl+C behaviour).
    [switch]$KeepRunning,
    # Stop services left behind by an earlier launcher, then exit.
    [switch]$Stop,
    # Accepted for compatibility; stopping on exit is now the default.
    [switch]$StopOnExit,
    # Internal: run as the cleanup watchdog for the launcher with this PID.
    [int]$WatchPid = 0
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $ProjectRoot 'runtime'
$LauncherRoot = Join-Path $RuntimeRoot 'launcher'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Hubble = Join-Path $RuntimeRoot 'hubble-cli\hubble.exe'
$Kubeconfig = Join-Path $RuntimeRoot 'securecloud.kubeconfig'
$HubbleExport = Join-Path $RuntimeRoot 'hubble-current.jsonl'
$RetailManifest = Join-Path $RuntimeRoot 'vendor-spikes\online-boutique-securecloud.yaml'
# One line per service this launcher started ("name pid start-filetime"), after a header line
# "launcher <pid> <keep 0|1>". It lets cleanup find everything even after a hard kill.
$SessionFile = Join-Path $LauncherRoot 'session.txt'
$CleanupLog = Join-Path $LauncherRoot 'cleanup.log'
$script:LogPositions = @{}

New-Item -ItemType Directory -Force -Path $LauncherRoot | Out-Null

function Write-Banner {
    Clear-Host
    Write-Host '  SECURECLOUD CONTROL PLANE' -ForegroundColor Cyan
    Write-Host '  Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation' -ForegroundColor White
    Write-Host ('  ' + ('-' * 72)) -ForegroundColor DarkGray
    Write-Host '  Live output below is collected from the local API, Kubernetes and Hubble.' -ForegroundColor DarkGray
    Write-Host ''
}

function Write-Event([string]$Source, [string]$Message, [ConsoleColor]$Colour = 'Gray') {
    $stamp = Get-Date -Format 'HH:mm:ss.fff'
    Write-Host "[$stamp] " -NoNewline -ForegroundColor DarkGray
    Write-Host ("{0,-10}" -f $Source) -NoNewline -ForegroundColor $Colour
    Write-Host " $Message"
}

function Test-LoopbackPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return $task.Wait(350) -and $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot,
        [hashtable]$Environment = @{},
        [string]$StandardOutput,
        [switch]$DoNotTail
    )
    $stdout = if ($StandardOutput) { $StandardOutput } else { Join-Path $LauncherRoot "$Name.out.log" }
    $stderr = Join-Path $LauncherRoot "$Name.err.log"
    foreach ($path in @($stdout, $stderr)) {
        if (-not (Test-Path $path)) { New-Item -ItemType File -Path $path | Out-Null }
        if (-not $DoNotTail -and $path -ne $StandardOutput) {
            $script:LogPositions[$path] = (Get-Content $path -ErrorAction SilentlyContinue).Count
        }
    }
    $old = @{}
    foreach ($entry in $Environment.GetEnumerator()) {
        $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
        [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, 'Process')
    }
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
            -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    } finally {
        foreach ($entry in $Environment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $old[$entry.Key], 'Process')
        }
    }
    Set-Content -Path (Join-Path $LauncherRoot "$Name.pid") -Value $process.Id
    $started = try { $process.StartTime.ToFileTimeUtc() } catch { 0 }
    Add-Content -Path $SessionFile -Value "$Name $($process.Id) $started"
    Write-Event 'LAUNCHER' "started $Name (PID $($process.Id))" Green
    return $process
}

function Start-HubbleCapture {
    # Restarting truncates the export; the API collector notices the smaller file and re-reads it.
    $script:Capture = Start-LoggedProcess -Name 'hubble-capture' -FilePath $Hubble `
        -Arguments @('observe','--server','127.0.0.1:4245','--follow','--output','json') `
        -StandardOutput $HubbleExport -DoNotTail
    Write-Event 'HUBBLE' "capturing live flow records to $HubbleExport" Green
}

function Invoke-Wsl([string]$Command) {
    # Send the command over standard input. This preserves kubectl jsonpath
    # quoting and works on Windows PowerShell 5.1, which lacks ArgumentList.
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = 'wsl.exe'
    $startInfo.Arguments = '-d Ubuntu -u root -- bash'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    # Standard input uses the console input encoding. Some non-interactive hosts
    # use UTF-8 *with* a BOM, which bash would read as part of the first command.
    $previousEncoding = [Console]::InputEncoding
    try {
        [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
        [void]$process.Start()
    } finally { [Console]::InputEncoding = $previousEncoding }
    $process.StandardInput.Write($Command)
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        $detail = $stderr.Trim()
        throw "WSL command failed: $Command$(if ($detail) { "`n$detail" })"
    }
    return $stdout.Trim()
}

function Wait-Port([int]$Port, [string]$Name, [int]$Seconds = 45) {
    $until = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) {
        if (Test-LoopbackPort $Port) {
            Write-Event 'READY' "$Name is accepting connections on 127.0.0.1:$Port" Green
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Event 'WARNING' "$Name did not become ready within ${Seconds}s" Yellow
    return $false
}

function Show-LogChanges {
    foreach ($path in @($script:LogPositions.Keys)) {
        if (-not (Test-Path $path)) { continue }
        $lines = @(Get-Content $path -ErrorAction SilentlyContinue)
        $position = [int]$script:LogPositions[$path]
        if ($lines.Count -gt $position) {
            $source = [IO.Path]::GetFileName($path).Replace('.out.log','').Replace('.err.log','').ToUpperInvariant()
            for ($i = $position; $i -lt $lines.Count; $i++) {
                if (-not [string]::IsNullOrWhiteSpace($lines[$i])) { Write-Event $source $lines[$i] DarkGray }
            }
            $script:LogPositions[$path] = $lines.Count
        }
    }
}

function Show-LiveStatus {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        $infra = $health.infrastructure
        $telemetry = $health.telemetry
        $provider = if ($infra.provider) { $infra.provider } else { 'kubernetes' }
        $version = if ($infra.version) { " $($infra.version)" } else { '' }
        Write-Event 'API' "provider=$provider connected=$($infra.connected)$version" Cyan
        $fields = @('accepted','rejected','unresolved','findings','events')
        $values = foreach ($field in $fields) {
            if ($null -ne $telemetry.$field) { "$field=$($telemetry.$field)" }
        }
        if ($values.Count) { Write-Event 'DETECTOR' ($values -join ' ') Magenta }
    } catch {
        Write-Event 'API' 'health endpoint unavailable' Yellow
    }
    if (Test-Path $HubbleExport) {
        $file = Get-Item $HubbleExport
        $age = [math]::Round(((Get-Date) - $file.LastWriteTime).TotalSeconds, 1)
        $mib = [math]::Round($file.Length / 1MB, 1)
        Write-Event 'HUBBLE' "capture=${mib}MiB last-flow=${age}s-ago" DarkCyan
    }
}

function Read-SessionHeader {
    if (-not (Test-Path $SessionFile)) { return $null }
    $first = @(Get-Content $SessionFile -TotalCount 1 -ErrorAction SilentlyContinue)
    if (-not $first -or $first[0] -notmatch '^launcher (\d+) ([01])$') { return $null }
    return [pscustomobject]@{ Pid = [int]$Matches[1]; Keep = ($Matches[2] -eq '1') }
}

function Test-LauncherAlive([int]$LauncherPid) {
    $process = Get-Process -Id $LauncherPid -ErrorAction SilentlyContinue
    return [bool]($process -and $process.ProcessName -in @('powershell', 'pwsh'))
}

function Stop-SessionServices {
    # Idempotent: the launcher's finally block and the watchdog may both call it.
    if (-not (Test-Path $SessionFile)) { return }
    $names = @()
    foreach ($line in @(Get-Content $SessionFile -ErrorAction SilentlyContinue | Select-Object -Skip 1)) {
        $name, $id, $started = $line -split ' '
        if (-not $id) { continue }
        $names += $name
        $process = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        # Skip a PID that Windows has since reused for an unrelated process.
        try {
            if ([long]$started -ne 0 -and $process.StartTime.ToFileTimeUtc() -ne [long]$started) { continue }
        } catch { continue }
        # /T takes the whole tree: npm.cmd -> cmd -> node (Vite) would otherwise orphan node.
        & cmd.exe /c "taskkill /PID $id /T /F >nul 2>&1"
        Write-Event 'CLEANUP' "stopped $name (PID $id) and its child processes" Yellow
    }
    if ($names -contains 'hubble-relay' -or $names -contains 'demo-apps') {
        # Killing wsl.exe does not reliably end the Linux side, so stop the forwarders there too.
        # The second pass catches a kubectl a forward loop restarted while it was being stopped.
        try {
            Invoke-Wsl "for _ in 1 2; do pkill -f 'port-forward-(demo-apps|hubble).sh'; pkill -f 'port-forward service/[^ ]+ (4245|8094|8095):80'; sleep 1; done; true" | Out-Null
            Write-Event 'CLEANUP' 'stopped Kubernetes port-forwards in WSL' Yellow
        } catch { Write-Event 'CLEANUP' "could not stop WSL port-forwards: $($_.Exception.Message)" Yellow }
    }
    Remove-Item $SessionFile -Force -ErrorAction SilentlyContinue
}

if ($WatchPid) {
    # Watchdog: runs hidden in its own console, so it outlives a closed window or a killed launcher.
    Start-Transcript -Path $CleanupLog -Append | Out-Null
    try { (Get-Process -Id $WatchPid -ErrorAction Stop).WaitForExit() } catch {}
    $header = Read-SessionHeader
    if ($header -and $header.Pid -eq $WatchPid -and -not $header.Keep) {
        Write-Event 'WATCHDOG' "launcher PID $WatchPid exited; cleaning up" Yellow
        Stop-SessionServices
    }
    Stop-Transcript | Out-Null
    exit 0
}

Write-Banner

if ($Stop) {
    $header = Read-SessionHeader
    if ($header -and (Test-LauncherAlive $header.Pid)) {
        Write-Event 'LAUNCHER' "a launcher is still running (PID $($header.Pid)); close it instead" Yellow
        exit 1
    }
    if (Test-Path $SessionFile) { Stop-SessionServices; Write-Event 'LAUNCHER' 'services stopped' Green }
    else { Write-Event 'LAUNCHER' 'no recorded services to stop' DarkGray }
    exit 0
}

if ($StatusOnly) {
    foreach ($service in @(@('Portal',4174), @('API',8000), @('Hubble Relay',4245), @('Retail app',8094), @('Vendor app',8095))) {
        $state = if (Test-LoopbackPort $service[1]) { 'READY' } else { 'OFFLINE' }
        Write-Event $state "$($service[0]) 127.0.0.1:$($service[1])" $(if ($state -eq 'READY') {'Green'} else {'Yellow'})
    }
    Show-LiveStatus
    exit 0
}

$previous = Read-SessionHeader
if ($previous -and (Test-LauncherAlive $previous.Pid)) {
    Write-Event 'LAUNCHER' "another launcher is already running (PID $($previous.Pid)); close it first" Yellow
    exit 1
}
$adopted = @()
if ($previous -and $previous.Keep) {
    # Services deliberately left by -KeepRunning are reused below, so this session owns them now.
    $adopted = @(Get-Content $SessionFile | Select-Object -Skip 1)
} elseif (Test-Path $SessionFile) {
    Write-Event 'LAUNCHER' 'cleaning up services left by a launcher that did not exit cleanly' Yellow
    Stop-SessionServices
}
Set-Content -Path $SessionFile -Value (@("launcher $PID $(if ($KeepRunning) {1} else {0})") + $adopted)
if (-not $KeepRunning) {
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-WatchPid', $PID
    ) | Out-Null
}

try {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'WSL is required for the local K3s lab.' }
    if (-not (Test-Path $Python)) { throw "Python environment not found: $Python" }

    Write-Event 'LAB' 'starting Ubuntu/K3s if it is not already running' Cyan
    & (Join-Path $ProjectRoot 'backend\manifests\lab\start-lab.ps1') | ForEach-Object { Write-Event 'LAB' $_ DarkGray }
    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try { if ((Invoke-Wsl 'k3s kubectl get --raw=/readyz') -match 'ok') { $ready = $true; break } } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'K3s did not report ready within 60 seconds.' }
    $versionInfo = (Invoke-Wsl 'k3s kubectl version -o json') | ConvertFrom-Json
    $kubeVersion = $versionInfo.serverVersion.gitVersion
    Write-Event 'K3S' "API ready; server=$kubeVersion" Green

    $drive = $ProjectRoot.Substring(0, 1).ToLowerInvariant()
    $linuxRoot = "/mnt/$drive$($ProjectRoot.Substring(2).Replace('\', '/'))"

    if (-not (Test-LoopbackPort 4245)) {
        # The script retries the forward, so a relay that is still settling after boot heals itself.
        Start-LoggedProcess -Name 'hubble-relay' -FilePath 'wsl.exe' `
            -Arguments @('-d','Ubuntu','-u','root','--',"$linuxRoot/backend/manifests/lab/port-forward-hubble.sh") | Out-Null
        Wait-Port 4245 'Hubble Relay' 90 | Out-Null
    } else { Write-Event 'REUSE' 'Hubble Relay already listening on port 4245' DarkGreen }

    if (Test-Path $Hubble) {
        # Reuse only a capture process that is actually alive; a recently written file alone can
        # belong to a capture that has just exited, which would leave telemetry silently stopped.
        $captureAlive = [bool](Get-Process -Name 'hubble' -ErrorAction SilentlyContinue)
        $captureFresh = $captureAlive -and (Test-Path $HubbleExport) -and (((Get-Date) - (Get-Item $HubbleExport).LastWriteTime).TotalSeconds -lt 5)
        if ($captureFresh) {
            $script:Capture = Get-Process -Name 'hubble' | Select-Object -First 1
            Write-Event 'REUSE' 'live Hubble capture is already updating' DarkGreen
        }
        elseif (Test-LoopbackPort 4245) { Start-HubbleCapture }
        else { Write-Event 'HUBBLE' 'relay not reachable yet; the capture starts as soon as it is' Yellow }
    }

    $retailNamespace = Invoke-Wsl "k3s kubectl get namespace -l securecloud.io/purpose=northstar-shop-stack -o jsonpath='{.items[0].metadata.name}'"
    $vendorNamespace = Invoke-Wsl "k3s kubectl get namespace -l securecloud.io/purpose=bloom-shop-stack -o jsonpath='{.items[0].metadata.name}'"
    if ($retailNamespace -and $vendorNamespace -and (-not (Test-LoopbackPort 8094) -or -not (Test-LoopbackPort 8095))) {
        $forwardScript = "$linuxRoot/backend/manifests/lab/port-forward-demo-apps.sh"
        Start-LoggedProcess -Name 'demo-apps' -FilePath 'wsl.exe' `
            -Arguments @('-d','Ubuntu','-u','root','--',$forwardScript,$retailNamespace,$vendorNamespace,'northstar-web','bloom-web') | Out-Null
    } else {
        $retailLabel = if ($retailNamespace) { $retailNamespace } else { 'not deployed' }
        $vendorLabel = if ($vendorNamespace) { $vendorNamespace } else { 'not deployed' }
        Write-Event 'LAB' "retail=$retailLabel vendor=$vendorLabel" Cyan
    }

    if (-not (Test-LoopbackPort 8000)) {
        # Catalogue plus local demo accounts from the gitignored runtime\demo-accounts.env.
        & $Python -m backend.retail_seed | ForEach-Object { Write-Event 'SEED' $_ DarkCyan }
        $apiEnvironment = @{
            SECURECLOUD_DB = (Join-Path $RuntimeRoot 'securecloud-retail.sqlite')
            SECURECLOUD_ORIGIN = 'http://127.0.0.1:4174'
            SECURECLOUD_INFRASTRUCTURE = 'kubernetes'
            SECURECLOUD_KUBECONFIG = $Kubeconfig
            SECURECLOUD_HUBBLE_EXPORT = $HubbleExport
        }
        if (Test-Path $RetailManifest) { $apiEnvironment.SECURECLOUD_RETAIL_MANIFEST = $RetailManifest }
        Start-LoggedProcess -Name 'api' -FilePath $Python -Arguments @('-m','backend.main') -Environment $apiEnvironment | Out-Null
    } else { Write-Event 'REUSE' 'management API already listening on port 8000' DarkGreen }

    if (-not (Test-LoopbackPort 4174)) {
        Start-LoggedProcess -Name 'portal' -FilePath 'npm.cmd' -Arguments @('run','dev','--','--port','4174') `
            -WorkingDirectory (Join-Path $ProjectRoot 'frontend') `
            -Environment @{ VITE_USE_API = 'true' } | Out-Null
    } else { Write-Event 'REUSE' 'portal already listening on port 4174' DarkGreen }

    Wait-Port 8000 'Management API' | Out-Null
    Wait-Port 4174 'Portal' | Out-Null
    if ($retailNamespace) { Wait-Port 8094 'Retail application' 15 | Out-Null }
    if ($vendorNamespace) { Wait-Port 8095 'Vendor application' 15 | Out-Null }

    Write-Host ''
    Write-Event 'URL' 'SecureCloud portal  http://127.0.0.1:4174' White
    Write-Event 'URL' 'Customer storefront http://127.0.0.1:4174/shop' White
    Write-Event 'URL' 'Owner dashboard     http://127.0.0.1:4174/admin' White
    Write-Event 'URL' 'Management API     http://127.0.0.1:8000/docs' White
    if (Test-LoopbackPort 8094) { Write-Event 'URL' 'Retail application  http://127.0.0.1:8094' White }
    if (Test-LoopbackPort 8095) { Write-Event 'URL' 'Vendor application  http://127.0.0.1:8095' White }
    $exitHint = if ($KeepRunning) { 'press Ctrl+C to leave services running' } else { 'press Ctrl+C or close this window to stop everything' }
    Write-Event 'LAUNCHER' "streaming component logs and health; $exitHint" Green
    Write-Host ''

    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:4174' }
    $lastStatus = [datetime]::MinValue
    while ($true) {
        Show-LogChanges
        if (((Get-Date) - $lastStatus).TotalSeconds -ge 5) {
            # The capture exits whenever the relay connection drops (relay restart, forward retry);
            # restart it so telemetry does not silently stop for the rest of the demo.
            if ((Test-Path $Hubble) -and (-not $script:Capture -or $script:Capture.HasExited) -and (Test-LoopbackPort 4245)) {
                if ($script:Capture) { Write-Event 'HUBBLE' 'capture stopped; restarting it' Yellow }
                Start-HubbleCapture
            }
            Show-LiveStatus
            $lastStatus = Get-Date
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    # Ctrl+C lands here. A closed window or a killed launcher may never reach this block;
    # the watchdog started above performs the same cleanup in that case.
    if ($KeepRunning) {
        Write-Event 'LAUNCHER' 'leaving services running; run start.ps1 -Stop to stop them' Yellow
    } else {
        Stop-SessionServices
        Write-Event 'LAUNCHER' 'stopped everything this launcher started' Yellow
    }
}
