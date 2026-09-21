<#
.SYNOPSIS
    Runs one long-lived Serena MCP server for an Unreal project, warms it up, and restarts it if it
    stops answering.

.DESCRIPTION
    Serena registered as a `stdio` server is spawned once per client session, so N chats mean N
    Serena processes and N language servers, all reading and writing the same clangd index. One
    long-lived HTTP server means one clangd, one index, and one startup cost instead of one per
    session.

    The startup cost is the reason this script warms up rather than just starting. Project
    activation is LAZY: language servers are not started until the first symbolic tool call arrives,
    and on a large Unreal tree that can take minutes against a tool timeout measured in seconds. The
    first caller after a restart burns two or three failed calls and reasonably concludes the server
    is broken. Paying that cost at logon, where nothing is waiting, turns a confusing failure into an
    invisible delay.

    Nothing here is required to use the memory stack. It is worth registering if you keep several
    sessions open, or if your first Serena call after a restart routinely times out.

.PARAMETER Project
    The Unreal project root to activate. Required: there is no sensible default, and a launcher that
    guesses wrong starts a server pointed at nothing.

.PARAMETER Port
    Port for the MCP endpoint. Must match what your client is configured to connect to.

.PARAMETER Context
    Serena context name. Leave as the default unless you have derived a local variant.

.PARAMETER FreshnessSkip
    Directory names excluded from Serena's freshness poll, comma separated. See the note beside the
    variable below before changing it - on an Unreal tree this is the difference between a fast tool
    call and a slow one, and it is not a micro-optimisation.

.PARAMETER ToolTimeoutSeconds
    Must stay BELOW your client's idle timeout. See the ordering rule below; getting it the wrong way
    round takes the server's listening socket down and is genuinely hard to diagnose.

.PARAMETER NoWarmUp
    Start and watch, but skip the warm-up.

.PARAMETER Stop
    Stop the running server completely and exit: the watchdog that spawned it, serena.exe, every
    language server, and any orphan from an earlier generation. This is the restart path. Stopping
    the scheduled task alone kills only the watchdog, which is this script; the server it started
    lives on, the next start finds the port busy and exits with nothing to do, and the old server
    runs on unwatched with none of whatever change prompted the restart. Start the task afterwards.

.EXAMPLE
    .\Start-SerenaForUE.ps1 -Project C:\Work\MyGame

.EXAMPLE
    # Restart: stop everything, then start the task again.
    .\Start-SerenaForUE.ps1 -Stop
    Start-ScheduledTask -TaskName "Serena MCP"

.EXAMPLE
    # Registered as a logon task, which is the intended use:
    schtasks /create /tn "Serena MCP" /sc onlogon /rl highest /f /tr `
      "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\Start-SerenaForUE.ps1 -Project C:\Work\MyGame"
#>
[CmdletBinding()]
param(
    [string] $Project,
    [int]    $Port = 24290,
    [string] $Context = 'claude-code',
    [string] $FreshnessSkip = 'UnrealEngine,Engine',
    [int]    $ToolTimeoutSeconds = 45,
    [switch] $NoWarmUp,
    [switch] $Stop
)

$ErrorActionPreference = 'Stop'

$LogDir = Join-Path $env:USERPROFILE '.serena\logs'

# WHY THIS EXISTS AND WHY IT DEFAULTS TO SOMETHING. Serena polls tracked files for freshness before
# symbolic tool calls, and the cost scales with the file COUNT, not with the number of changes. On an
# Unreal tree the overwhelming majority of those files are engine source that nothing edits, so
# polling them detects nothing and costs real seconds out of every tool timeout. Excluding the engine
# directories is the single largest difference between a fast install and one that feels broken.
#
# If you do edit engine source, remove it from this list and accept the cost.
$env:SERENA_FRESHNESS_SKIP = $FreshnessSkip

# WHY A PRIVATE COPY OF serena.exe, and not the one on PATH. Both are uv trampolines with the target
# script path baked in. The hazard is a packaged desktop app with a virtualised file system: an
# install run from inside that container writes a trampoline pointing into the container's private
# AppData, which resolves for processes the app spawns and fails with "uv trampoline failed to
# canonicalize script path" for a detached one like a scheduled task.
#
# So this launcher starts its own copy, and an in-container install cannot change what runs here.
# COPY IT AGAIN AFTER EVERY REINSTALL, or this task keeps starting the previous generation.
$Serena = Join-Path $env:USERPROFILE '.serena\bin\serena.exe'
if (-not (Test-Path $Serena)) {
    throw @"
serena.exe not found at $Serena.
Install Serena first (Install-SerenaForUE.ps1), then copy the installed entrypoint there:
    Copy-Item "$env:USERPROFILE\.local\bin\serena.exe" "$Serena"
Re-copy it after every reinstall - see the note in this script for why the copy is deliberate.
"@
}
if (-not $Stop) {
    if (-not $Project) { throw "-Project is required to start a server; only -Stop works without it" }
    if (-not (Test-Path $Project)) { throw "project root not found at $Project" }
}
if (-not (Test-Path $LogDir))  { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Single instance. A second server on the same port would fail to bind; exiting cleanly keeps the
# task history readable.
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening -and -not $Stop) {
    Write-Output "Serena already listening on $Port (pid $($listening[0].OwningProcess)). Nothing to do. Use -Stop first to restart."
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log   = Join-Path $LogDir "http-server-$stamp.log"
function Say($t) { "[$(Get-Date -Format s)] $t" | Add-Content $log }
"" | Out-File $log -Encoding utf8

# These get large: at INFO level Serena echoes the language servers' entire stderr, which can reach
# tens of megabytes in a couple of hours. Keep the last few sets.
Get-ChildItem $LogDir -Filter 'http-server-*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 |
    Remove-Item -Force -ErrorAction SilentlyContinue

# THE ORDERING RULE, and it is not a preference.
#
# --tool-timeout MUST stay below the client's idle timeout. With it the wrong way round: the client
# gives up and disconnects, Serena keeps working to its own longer timeout, and the reply to a
# vanished client raises a disconnect error on the LISTENING socket. On Windows the asyncio proactor
# loop then stops accepting. The process survives, the dashboard survives, the MCP endpoint does not
# - so the server looks alive and answers nothing.
#
# The server must always answer before the client gives up.
$serenaArgs = @(
    'start-mcp-server'
    '--transport', 'streamable-http'
    '--host', '127.0.0.1'
    '--port', "$Port"
    '--context', $Context
    '--project', $Project
    '--tool-timeout', "$ToolTimeoutSeconds"
    '--log-level', 'WARNING'          # INFO echoes every language server stderr line into the log
    '--enable-web-dashboard', 'true'
    '--open-web-dashboard', 'false'
    '--enable-gui-log-window', 'false'
)

function Get-SerenaPids {
    @(Get-CimInstance Win32_Process |
      Where-Object { $_.CommandLine -like '*\.serena\bin\serena.exe*' } |
      Select-Object -ExpandProperty ProcessId)
}

function Stop-SerenaTree {
    <#
      THE ORPHAN LEAK, and why this is a tree kill rather than a Stop-Process.

      Killing serena.exe alone leaves every language server it spawned running. They are not children
      of anything that then dies, so nothing reaps them. Left alone across a few restarts they
      accumulate into gigabytes, and a reboot is the only thing that clears them - which defeats the
      point of a long-lived server that is supposed to survive restarts.

      This kills descendants first, then the roots, then sweeps anything still running out of the
      language-server directory whose parent is already gone. That last sweep is what clears orphans
      from EARLIER generations, which a tree walk alone cannot reach.
    #>
    $all = Get-CimInstance Win32_Process
    $roots = @($all | Where-Object { $_.CommandLine -like '*\.serena\bin\serena.exe*' } |
                 Select-Object -ExpandProperty ProcessId)

    # Descendants, breadth-first, collected BEFORE killing anything: a dead parent loses the link to
    # its children and they become unreachable orphans, which is the exact bug being fixed.
    $tree = New-Object System.Collections.Generic.List[int]
    $frontier = $roots
    while ($frontier.Count -gt 0) {
        $next = @($all | Where-Object { $frontier -contains $_.ParentProcessId } |
                    Select-Object -ExpandProperty ProcessId)
        foreach ($id in $next) { if (-not $tree.Contains($id)) { $tree.Add($id) } }
        $frontier = @($next | Where-Object { $tree -contains $_ })
        if ($tree.Count -gt 500) { break }   # guard against a cycle in reported parentage
    }

    foreach ($id in $tree)  { Stop-Process -Id $id -Force -EA SilentlyContinue }
    foreach ($id in $roots) { Stop-Process -Id $id -Force -EA SilentlyContinue }
    Start-Sleep -Milliseconds 500

    # MATCHED ON ExecutablePath, NOT CommandLine, and that distinction is the whole safety of this
    # function. A first version matched the command line, and a dry run against the live process
    # table showed it selecting THE DIAGNOSTIC POWERSHELL PROCESS RUNNING THE QUERY - because that
    # command line happened to contain the directory name. Anything merely MENTIONING the path would
    # have been killed, which in practice means whoever is debugging this.
    #
    # ExecutablePath is where the binary actually lives and cannot be spoofed by a shell argument.
    #
    # Known limitation: wrapper processes around some servers have their own ExecutablePath and are
    # not matched. They exit when the child they wrap dies, which is sufficient in practice and far
    # better than a command-line match that cannot tell a language server from a person looking at one.
    $me = $PID
    $orphans = @(Get-CimInstance Win32_Process |
                 Where-Object {
                     $_.ProcessId -ne $me -and
                     $_.ExecutablePath -and
                     $_.ExecutablePath -like "$env:USERPROFILE\.serena\language_servers\*"
                 } | Select-Object -ExpandProperty ProcessId)
    foreach ($id in $orphans) { Stop-Process -Id $id -Force -EA SilentlyContinue }

    return ($tree.Count + $roots.Count + $orphans.Count)
}

function Find-CompileDb {
    <#
      The compilation database clangd is pointed at: named in the project's Serena config when there
      is one, otherwise the conventional folder. Nothing here is required; the caller falls back to a
      file search when this returns nothing.
    #>
    param([string] $Root)

    $dirs = @()
    $yml = Join-Path $Root '.serena\project.yml'
    if (Test-Path -LiteralPath $yml) {
        foreach ($m in [regex]::Matches((Get-Content -LiteralPath $yml -Raw), '--compile-commands-dir=([^\s"'']+)')) {
            $d = $m.Groups[1].Value
            if (-not [IO.Path]::IsPathRooted($d)) { $d = Join-Path $Root $d }
            $dirs += $d
        }
    }
    $dirs += (Join-Path $Root '.clangd-db'), $Root
    foreach ($d in $dirs) {
        $db = Join-Path $d 'compile_commands.json'
        if (Test-Path -LiteralPath $db) { return $db }
    }
    return $null
}

function Get-CompileDbWarmUpFile {
    <#
      The first source file the compilation database knows, preferring one under a project folder.

      A file the database does not describe still activates clangd, but that is all it does: clangd
      parses it with no flags, reports nothing useful, and the first real query still has to load the
      database. A file the database DOES describe makes clangd load it here, which is the cost this
      warm-up exists to pay. The database can be tens of megabytes and lists the engine first, so this
      streams it line by line rather than parsing it, and stops at the first preferred hit.
    #>
    param([string] $Root, [string] $Db, [string[]] $Skip, [string[]] $PreferUnder)

    $rootPrefix = $Root.Replace('/', [IO.Path]::DirectorySeparatorChar).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $prefixes = @($PreferUnder | ForEach-Object { $_.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar })
    $fallback = $null
    $reader = New-Object IO.StreamReader($Db)
    try {
        while ($null -ne ($line = $reader.ReadLine())) {
            if (-not $line.Contains('"file"')) { continue }
            $m = [regex]::Match($line, '"file"\s*:\s*"([^"]+)"')
            if (-not $m.Success) { continue }
            $f = $m.Groups[1].Value.Replace('/', [IO.Path]::DirectorySeparatorChar)
            if (-not $f.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { continue }
            if ($Skip | Where-Object { $f -like "*\$_\*" }) { continue }
            if (-not (Test-Path -LiteralPath $f)) { continue }
            if ($prefixes | Where-Object { $f.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }) { return $f }
            if (-not $fallback) { $fallback = $f }
        }
    } finally { $reader.Dispose() }
    return $fallback
}

function Get-WarmUpTargets {
    <#
      One real file per language, DISCOVERED rather than hardcoded, so this works on a project the
      author has never seen. Stability matters more than size: a warm-up pointing at a file someone
      deletes becomes a confusing log line about a missing path.

      ONE FILE PER LANGUAGE, not one call. A single call activates the manager and therefore starts
      every server, but each server still does lazy per-file work on its first document. clangd in
      particular loads no compilation database until a file is opened, and a workspace symbol query
      answers INSTANTLY WITH NOTHING until then - an empty result that reads exactly like "no such
      symbol". Touching one real file per language retires that trap for every session that follows.

      WHICH file matters too. The tree holds more than game code: vendored tools, a build system, an
      audio team's scratch folder, and the alphabetically first match is as likely to be one of those
      as anything the project author would recognise. A file like that starts the server but warms
      nothing, because it is outside the compilation database and outside every index the author
      cares about. So the C++ file comes from the compilation database when there is one, and every
      search looks under the folders holding a .uproject before it looks anywhere else.

      The search also has to be CHEAP. This runs in the foreground before the warm-up job is
      dispatched, and a full-tree walk per language on an engine checkout cost two minutes on one
      machine, all of it before the watchdog was armed. Each search stops at its first hit.
    #>
    param([string] $Root)

    $skip = @('Binaries', 'Intermediate', 'Saved', 'DerivedDataCache', '.git', 'node_modules')
    $notSkipped = { param($path) -not ($skip | Where-Object { $path -like "*\$_\*" }) }
    $relative = { param($full) $full.Substring($Root.Length).TrimStart('\', '/') }

    $projectDirs = @(Get-ChildItem -Path $Root -Filter *.uproject -Recurse -Depth 2 -File -ErrorAction SilentlyContinue |
                     Where-Object { & $notSkipped $_.FullName } |
                     ForEach-Object { $_.DirectoryName } | Sort-Object -Unique)

    # Where game code conventionally lives, narrowest first, then the whole project, then the tree.
    $scopes = @()
    foreach ($p in $projectDirs) { foreach ($sub in 'Source', 'Plugins', 'Content\Python') { $scopes += (Join-Path $p $sub) } }
    $scopes += $projectDirs
    $scopes += $Root
    $scopes = @($scopes | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique)

    $pick = {
        param($pattern)
        foreach ($scope in $scopes) {
            $hit = Get-ChildItem -LiteralPath $scope -Filter $pattern -Recurse -File -ErrorAction SilentlyContinue |
                   Where-Object { & $notSkipped $_.FullName } |
                   Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
        return $null
    }

    $targets = [ordered]@{}

    $cpp = $null
    $db = Find-CompileDb -Root $Root
    if ($db) { $cpp = Get-CompileDbWarmUpFile -Root $Root -Db $db -Skip $skip -PreferUnder $projectDirs }
    if (-not $cpp) { $cpp = & $pick '*.cpp' }
    if ($cpp) { $targets['cpp'] = & $relative $cpp }

    foreach ($pair in @(
        @{ lang = 'csharp';     pattern = '*.Build.cs' },
        @{ lang = 'python';     pattern = '*.py' },
        @{ lang = 'powershell'; pattern = '*.ps1' }
    )) {
        $full = & $pick $pair.pattern
        if ($full) { $targets[$pair.lang] = & $relative $full }
    }
    return $targets
}

function Start-SerenaWarmUp {
    <#
      Force activation and one file open per language, so the startup cost is paid here rather than
      by whoever calls first.

      Best effort throughout. A warm-up that fails must never stop the server starting: the server is
      already up and usable by the time this runs, and the only thing at stake is whether the first
      real caller waits.
    #>
    param([int] $Port, [string] $Root, [string] $LogFile)

    # NEVER Invoke-WebRequest HERE, AND NEVER ON THE LAUNCHER'S OWN THREAD.
    #
    # Learned expensively. MCP streamable HTTP answers with `text/event-stream`, and
    # Invoke-WebRequest's -TimeoutSec bounds only the response HEADERS, not the body read. An inline
    # call sat on an open stream for ELEVEN MINUTES, so the launcher never reached the next line and
    # THE WATCHDOG NEVER ARMED. A convenience feature had disabled the thing that restarts a dead
    # server.
    #
    # Two defences, because either alone would have been enough and neither was there:
    #   1. the response body is never read - HttpClient with ResponseHeadersRead, disposed at once.
    #      The tool call does its work server-side whether or not anyone reads the reply.
    #   2. the whole warm-up runs in a BACKGROUND JOB, so no bug in it can delay the watchdog again.
    $uri = "http://127.0.0.1:$Port/mcp"
    $targets = Get-WarmUpTargets -Root $Root
    if ($targets.Count -eq 0) {
        Say 'WARM-UP: no candidate files found under the project; skipping'
        return
    }

    $work = {
        param($uri, $targets, $logFile, $projectRoot)

        # A background job gets a fresh runspace, and Windows PowerShell does not load
        # System.Net.Http into one by default - the type resolves in the launcher's session and not
        # here.
        Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue

        function JobSay($m) {
            "[{0}] {1}" -f (Get-Date -Format s), $m | Add-Content -Path $logFile -Encoding utf8
        }

        # Headers-only send. The reply is an event stream we deliberately never read.
        function Send-Mcp($uri, $json, $sid, $timeoutSec) {
            $client = New-Object System.Net.Http.HttpClient
            $client.Timeout = [TimeSpan]::FromSeconds($timeoutSec)
            try {
                $req = New-Object System.Net.Http.HttpRequestMessage ([System.Net.Http.HttpMethod]::Post), $uri
                $req.Content = New-Object System.Net.Http.StringContent($json, [System.Text.Encoding]::UTF8, 'application/json')
                $req.Headers.Accept.ParseAdd('application/json, text/event-stream')
                if ($sid) { $req.Headers.Add('Mcp-Session-Id', $sid) }
                $resp = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
                $out = @{ ok = $resp.IsSuccessStatusCode; sid = $null }
                $val = $null
                if ($resp.Headers.TryGetValues('Mcp-Session-Id', [ref]$val)) { $out.sid = @($val)[0] }
                $resp.Dispose()
                return $out
            } finally {
                $client.Dispose()
            }
        }

        $t0 = Get-Date
        try {
            $init = @{ jsonrpc = '2.0'; id = 1; method = 'initialize'; params = @{
                           protocolVersion = '2025-06-18'; capabilities = @{}
                           clientInfo = @{ name = 'serena-launcher-warmup'; version = '1' } } } |
                    ConvertTo-Json -Depth 6 -Compress
            $r = Send-Mcp $uri $init $null 30
            if (-not $r.sid) { JobSay 'WARM-UP: no session id returned; skipping'; return }
            $sid = $r.sid
            $null = Send-Mcp $uri (@{ jsonrpc = '2.0'; method = 'notifications/initialized' } | ConvertTo-Json -Compress) $sid 30
        } catch {
            JobSay "WARM-UP: handshake failed ($($_.Exception.Message)); the server is up, the first caller pays the cost"
            return
        }

        foreach ($lang in $targets.Keys) {
            $file = $targets[$lang]
            if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $file))) {
                JobSay "WARM-UP: $lang skipped, no file at $file"
                continue
            }
            $s = Get-Date
            $body = @{ jsonrpc = '2.0'; id = 100; method = 'tools/call'; params = @{
                           name = 'get_symbols_overview'
                           arguments = @{ relative_path = $file } } } | ConvertTo-Json -Depth 6 -Compress
            try {
                # Generous, because the FIRST call pays for activation and the server's own tool
                # timeout may fire inside it. Either way the work continues server-side, so a timeout
                # here is not a failed warm-up - only an unobserved one.
                $null = Send-Mcp $uri $body $sid 420
                JobSay ("WARM-UP: {0} requested, returned in {1:N0}s ({2})" -f $lang, ((Get-Date) - $s).TotalSeconds, $file)
            } catch {
                JobSay ("WARM-UP: {0} did not return within {1:N0}s - {2}" -f $lang, ((Get-Date) - $s).TotalSeconds, $_.Exception.Message)
            }
        }
        JobSay ("WARM-UP: finished in {0:N0}s" -f ((Get-Date) - $t0).TotalSeconds)
    }

    $null = Start-Job -ScriptBlock $work -ArgumentList $uri, $targets, $LogFile, $Root
    Say ("WARM-UP: dispatched in the background for {0}; the watchdog is not waiting for it" -f ($targets.Keys -join ', '))
}

if ($Stop) {
    # THE WATCHDOG FIRST. The task's launcher process sits in the watch loop below and restarts the
    # server the moment the port goes quiet, so killing the tree before it would only hand it a
    # restart to do. It is found as the PARENT of serena.exe rather than by command line: the
    # parent link is a fact about who spawned the server, whereas a command-line match would also
    # select any shell that merely mentions this script's name, such as the one debugging it.
    #
    # A root is never a watchdog, even though one generation is three serena.exe processes and two
    # of them are parents of another. Killing a root here, before Stop-SerenaTree takes its
    # snapshot, strands that root's children with a dead parent, and the tree walk can no longer
    # reach them: a first version did exactly that and left a pwsh behind under a cmd.exe wrapper,
    # which the orphan sweep cannot see either because cmd.exe lives in System32.
    $all = Get-CimInstance Win32_Process
    $roots = @($all | Where-Object { $_.CommandLine -like '*\.serena\bin\serena.exe*' })
    $rootIds = @($roots | Select-Object -ExpandProperty ProcessId)
    $watchdogs = @($all | Where-Object { $p = $_; $p.ProcessId -ne $PID -and $rootIds -notcontains $p.ProcessId -and @($roots | Where-Object { $_.ParentProcessId -eq $p.ProcessId }).Count -gt 0 })
    foreach ($w in $watchdogs) { Stop-Process -Id $w.ProcessId -Force -EA SilentlyContinue }
    $n = Stop-SerenaTree
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    $still = Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue
    $state = if ($still) { "still listening, pid $($still[0].OwningProcess)" } else { 'closed' }
    Say ("STOP: {0} watchdog(s) and {1} server process(es) stopped; port {2} {3}" -f $watchdogs.Count, $n, $Port, $state)
    Write-Output ("stopped {0} watchdog(s) and {1} server process(es); port {2} {3}. Start the scheduled task to bring the server back." -f $watchdogs.Count, $n, $Port, $state)
    if ($still) { exit 1 }
    exit 0
}

# Clear anything left behind before starting fresh. Reaching here means the port is NOT listening, so
# any language server still running is an orphan from a previous generation. Without this sweep only
# FUTURE restarts are clean and the existing backlog stays resident.
$swept = Stop-SerenaTree
if ($swept -gt 0) { Say "swept $swept stale process(es) before starting" }

$attempt = 0
while ($true) {
    $attempt++
    $outLog = [IO.Path]::ChangeExtension($log, ".$attempt.out.log")
    $errLog = [IO.Path]::ChangeExtension($log, ".$attempt.err.log")

    Say "start attempt $attempt : $Serena $($serenaArgs -join ' ')"
    # Start-Process with explicit redirection rather than a redirect operator: under Task Scheduler
    # there is no console, and stream redirection of a native exe can capture nothing at all.
    $p = Start-Process -FilePath $Serena -ArgumentList $serenaArgs -NoNewWindow -PassThru `
            -RedirectStandardOutput $outLog -RedirectStandardError $errLog -WorkingDirectory $Project
    Say "pid $($p.Id)"

    # Publish the dashboard URL. The dashboard port cannot be configured - Serena scans upward from
    # its base port for the first free one - so it is deterministic when only one Serena runs, and
    # anything higher means a second instance is alive.
    $deadline = (Get-Date).AddMinutes(3)
    $dashPort = $null
    while (-not $dashPort -and (Get-Date) -lt $deadline -and -not $p.HasExited) {
        Start-Sleep -Seconds 5
        $kids = Get-SerenaPids
        $dashPort = Get-NetTCPConnection -State Listen -EA SilentlyContinue |
            Where-Object { $kids -contains $_.OwningProcess -and $_.LocalPort -ge 24282 -and $_.LocalPort -ne $Port } |
            Sort-Object LocalPort | Select-Object -First 1 -ExpandProperty LocalPort
    }
    $urlFile = Join-Path $env:USERPROFILE '.serena\dashboard-url.txt'
    if ($dashPort) {
        "http://127.0.0.1:$dashPort/dashboard/index.html" | Set-Content $urlFile -Encoding utf8
        Say "dashboard on $dashPort"
        if ($dashPort -ne 24282) { Say "NOTE: dashboard not on the base port, so another Serena holds it" }
    } else {
        "unknown - no dashboard port bound within 3 minutes" | Set-Content $urlFile -Encoding utf8
        Say "WARNING: no dashboard port detected"
    }

    if (-not $NoWarmUp) { Start-SerenaWarmUp -Port $Port -Root $Project -LogFile $log }

    Say "watchdog armed on port $Port"
    while (-not $p.HasExited) {
        Start-Sleep -Seconds 60
        $up = Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue
        if (-not $up) {
            Say "WATCHDOG: port $Port stopped listening while pid $($p.Id) is alive. Restarting."
            $killed = Stop-SerenaTree
            Say "stopped $killed process(es), including language servers"
            Start-Sleep -Seconds 5
            break
        }
    }

    if ($p.HasExited) { Say "process exited with $($p.ExitCode)" }
    Say "restarting in 10s"
    Start-Sleep -Seconds 10
}
