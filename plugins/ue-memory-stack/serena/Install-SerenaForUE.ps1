<#
.SYNOPSIS
    Installs the Serena build Layer 1 needs on an Unreal tree, and derives the context variant.

.DESCRIPTION
    Run this from a shell whose %APPDATA% writes are not redirected. It checks, and refuses if they are.

    That is not a style preference. A packaged app can run its shells in a container that redirects
    %APPDATA%, and Serena's environment lives under %APPDATA%\uv. An install made from a redirected
    shell lands in that app's private copy, the real server never loads it, and every check made from
    the same shell says it worked. This stack's own notes record losing a day to exactly that.
    The check writes a file into %APPDATA% and looks for it at the physical path a container redirects
    to, because the environment variable reads the same either way.

    WHAT CHANGED, AND WHY THIS IS NOT A PATCH SCRIPT ANY MORE. The five fixes used to ship here as
    diffs and loose files, applied to an installed Serena. Every `uv tool upgrade serena-agent`
    silently reverted all of them. They are now commits on a fork branch, so they arrive with the
    install and survive it - and this repository ships none of Serena's code, which also keeps it MIT:
    Serena is GPL-3.0-or-later from v2 onward (solidlsp stays MIT), so a diff against it would be a
    GPL-derived file in an MIT repository. See NOTICE.md.

    What you get, from serena/README.md:

      1. freshness skip list      every symbolic call walked the whole tree first, ~190s
      2. C# .csproj ignore fix    the C# server opened every engine .csproj, ThirdParty included
      3. find_symbol scope guard  an unscoped find_symbol kept walking after the client gave up,
                                  and has crashed clangd
      4. accept-loop hardening    Windows: one transient accept() error killed the HTTP listener
                                  while the process still looked healthy
      5. find_symbol_indexed      new tool, whole-tree lookup from clangd's index in ~0.1s

    And one thing that is NOT a fix and is NOT in the fork:

      6. the context variant      the stock claude-code context excludes search_for_pattern, which a
                                  routing table naming it then points at nothing. This script derives
                                  the variant from YOUR installed stock context, so no copy of
                                  Serena's file is distributed here.

    Re-running is safe. The install is idempotent by way of --force, and the context is left alone if
    it already carries search_for_pattern.

.PARAMETER Source
    The pip-installable source. Defaults to the fork branch in serena/layer1-state.json. Point it at
    your own fork if you would rather not install from somebody else's.

.PARAMETER TaskName
    The scheduled task running the long-lived server, from docs/05-serena-clangd.md. Yours will be
    named after your own tree; pass it, or skip it and restart the server yourself.

.PARAMETER DryRun
    Report what would change and write nothing.

.NOTES
    Files on disk are not a working server. Verify from OUTSIDE this shell, by asking the running
    server for its tool list - see the end of the output.
#>
[CmdletBinding()]
param(
    # Resolved in the body, NOT as a default here: on Windows PowerShell 5.1 parameter defaults are
    # evaluated with $PSScriptRoot still empty, and the script then dies before its first line. It
    # works under PowerShell 7, which is how the earlier version of this got as far as it did.
    [string] $StatePath,

    [string] $Source,

    [string] $TaskName = 'Serena MCP',

    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

if (-not $StatePath) {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    if (-not $here) { throw "Could not work out where this script lives. Pass -StatePath <path to layer1-state.json>." }
    $StatePath = Join-Path $here 'layer1-state.json'
}
if (-not (Test-Path -LiteralPath $StatePath)) {
    throw "No $StatePath. That file describes what a correctly installed Layer 1 looks like, and this script will not guess."
}
$state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
if (-not $Source) { $Source = ($state.source.install -split '\s+')[-1] }

function Step { param([string] $T) Write-Host "  -> $T" -ForegroundColor Gray }
function Ok   { param([string] $T) Write-Host "  OK   $T" -ForegroundColor Green }
function Skip { param([string] $T) Write-Host "  --   $T" -ForegroundColor DarkGray }
function Warn { param([string] $T) Write-Host "  WARN $T" -ForegroundColor Yellow }

# uv and git print advisories to stderr for ordinary answers. On PowerShell 5.1 a native command's
# stderr becomes an ErrorRecord, and under $ErrorActionPreference = 'Stop' that terminates the script
# on the SUCCESSFUL path. Run them with the preference relaxed and read the exit code.
function Invoke-Native {
    param([Parameter(Mandatory)] [string] $Exe,
          [Parameter(Mandatory, ValueFromRemainingArguments)] [string[]] $Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $script:NativeOutput = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prev }
}

# --- the redirection check ------------------------------------------------------------------------
# Worth refusing over rather than warning about, because the whole failure mode is that it looks like
# it worked.
#
# Do not test this by reading %APPDATA%. Inside a packaged app's container that variable still reads as
# the ordinary path; the redirection is at the filesystem layer, so a string check passes happily and
# the install goes to the private copy anyway.
#
# Do not test it by process name either. That was an earlier version of this check, and it refused
# shells that would have worked: one desktop app's Bash tool is redirected and its PowerShell tool is
# not, and both are descendants of the same process. A proxy that is wrong in both directions is worse
# than no check, because this one refuses to run.
#
# So test the thing itself. Write a file into %APPDATA% and look for it at the physical path a
# container redirects to. If it turns up there, the write was redirected, whatever the variable says.
$probeName = '.uea-redirect-probe-' + [guid]::NewGuid().ToString('N') + '.tmp'
$probePath = Join-Path $env:APPDATA $probeName
$redirectedTo = $null
try {
    New-Item -ItemType File -Path $probePath -Force | Out-Null
    $mirror = Join-Path $env:LOCALAPPDATA "Packages\*\LocalCache\Roaming\$probeName"
    $redirectedTo = @(Resolve-Path -Path $mirror -ErrorAction SilentlyContinue) | Select-Object -First 1
}
finally {
    Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
}
if ($redirectedTo) {
    throw ("This shell's %APPDATA% writes are redirected into a packaged app's private storage " +
           "($redirectedTo). Serena's environment lives under the real %APPDATA%, so this install " +
           "would land in a copy the real server never loads, and every check made from here would " +
           "say it worked. Run this from a normal PowerShell window.")
}

Write-Host ""
Write-Host "Layer 1: Serena for an Unreal tree" -ForegroundColor Cyan
Write-Host "  source: $Source"
Write-Host "  licence: $($state.source.licence)"
if ($DryRun) { Write-Host "  DRY RUN - nothing will be written" -ForegroundColor Yellow }
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not on PATH in this window. Install uv first: https://docs.astral.sh/uv/"
}

# --- 1. install ------------------------------------------------------------------------------------
Write-Host "1. The install" -ForegroundColor Cyan
if ($DryRun) {
    Skip "would run: uv tool install --force $Source"
}
else {
    Step "uv tool install --force $Source"
    # VERIFY THE INSTALLED FILE, NOT THE INSTALLER'S EXIT CODE. `uv tool install --force` can report
    # success and leave the OLD file in site-packages, because the fork's version string does not
    # move between builds and uv reuses a cached one. It happened twice in one day to two different
    # people. Section 3 below is what actually proves the install landed: it greps the installed
    # files for each fix's sentinel. If a fix reports missing straight after a successful install,
    # clear the cache and reinstall rather than debugging the fix:
    #     uv cache clean serena-agent
    #     uv tool install --force --reinstall <source>
    if ((Invoke-Native uv tool install --force $Source) -ne 0) {
        throw ("uv tool install failed. It said: " + ($script:NativeOutput -join '; '))
    }
    Ok "installed"
}

# --- 2. where it landed, and which build it actually is --------------------------------------------
Write-Host ""
Write-Host "2. Which build is installed" -ForegroundColor Cyan
$toolDir = $null
if ((Invoke-Native uv tool dir) -eq 0) {
    $toolDir = $script:NativeOutput | Where-Object { $_ -notmatch '^(warning|error)' } | Select-Object -First 1
}
if (-not $toolDir) { throw "uv tool dir did not return a usable path. Got: '$($script:NativeOutput -join '; ')'" }

$sitePackages = Join-Path $toolDir 'serena-agent\Lib\site-packages'
if (-not (Test-Path -LiteralPath $sitePackages)) {
    if ($DryRun) { Skip "no install yet at $sitePackages, which a real run would create"; return }
    throw "Installed, but $sitePackages is not there. Look at what uv printed above."
}
Ok "site-packages: $sitePackages"

# More than one dist-info means one of two things, and both mislead anything taking the first match:
# an in-place upgrade left the old one behind, or this shell is inside a packaged app and is seeing a
# union of its private copy and the real one. The probe above already refused the second case.
$dists = @(Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'serena_agent-*.dist-info' -ErrorAction SilentlyContinue)
$versions = @($dists | ForEach-Object { $_.Name -replace '^serena_agent-', '' -replace '\.dist-info$', '' })
if ($versions.Count -gt 1) {
    Warn ("site-packages holds more than one dist-info: " + ($versions -join ', ') +
          ". That is left over from an in-place upgrade. Do not read the version from the first match.")
}
foreach ($d in $dists) {
    $directUrl = Join-Path $d.FullName 'direct_url.json'
    if (Test-Path -LiteralPath $directUrl) {
        $u = Get-Content -LiteralPath $directUrl -Raw
        Ok ("$($d.Name) came from: " + ($u -replace '\s+', ' '))
    }
}

# --- 3. the fixes, checked in the installed files --------------------------------------------------
Write-Host ""
Write-Host "3. The fixes, in the installed files" -ForegroundColor Cyan
$missing = @()
# If one of these reports missing immediately after a successful install, suspect the install before
# the fix: uv can report success and leave the old file in place. `uv cache clean serena-agent` then
# `uv tool install --force --reinstall` is the fix, and this section is how you tell.
foreach ($fix in $state.fixes) {
    if ($fix.id -eq 'ue-context') { continue }          # handled below; it is not in the install
    $target = Join-Path $sitePackages ($fix.file -replace '/', '\')
    if (-not (Test-Path -LiteralPath $target)) {
        $missing += "$($fix.id) (no $($fix.file))"
        continue
    }
    if ((Get-Content -LiteralPath $target -Raw) -match [regex]::Escape($fix.sentinel)) {
        Ok "$($fix.id)"
    }
    else {
        $missing += "$($fix.id): $($fix.matters)"
    }
}
if ($missing) {
    Warn ("$($missing.Count) fix(es) are not in the installed files: " + ($missing -join ' | '))
    Warn "Either the branch has moved, or this is not the fork. Check the direct_url above."
}

# --- 4. the context variant, derived from the installed stock one -----------------------------------
Write-Host ""
Write-Host "4. The context variant" -ForegroundColor Cyan
$contextsDir = Join-Path $env:USERPROFILE '.serena\contexts'
$ueContext = Join-Path $contextsDir 'claude-code-ue.yml'

$existing = @()
if (Test-Path -LiteralPath $contextsDir) {
    $existing = @(Get-ChildItem -LiteralPath $contextsDir -File -Filter '*.yml' -ErrorAction SilentlyContinue |
                  Where-Object { (Get-Content -LiteralPath $_.FullName -Raw) -match 'search_for_pattern' })
}
if ($existing) {
    Skip ("a context carrying search_for_pattern is already there: " + (($existing | ForEach-Object Name) -join ', ') +
          ". Start the server with --context <that name>.")
}
else {
    $stock = Join-Path $sitePackages 'serena\resources\config\contexts\claude-code.yml'
    if (-not (Test-Path -LiteralPath $stock)) {
        Warn "No stock context at $stock, so there is nothing to derive from. Write one by hand: copy your Serena's claude-code context and remove search_for_pattern from excluded_tools."
    }
    elseif ($DryRun) {
        Skip "would derive $ueContext from $stock by removing search_for_pattern from excluded_tools"
    }
    else {
        # Derived here, on this machine, from the file Serena installed. That is the whole point: the
        # accelerator distributes no copy of Serena's context, and what lands in your profile is your
        # own install's file with one line removed.
        $lines = Get-Content -LiteralPath $stock
        $out = New-Object System.Collections.Generic.List[string]
        $out.Add('# Derived on this machine by Install-SerenaForUE.ps1 from the stock claude-code context')
        $out.Add('# that your Serena install provides, at:')
        $out.Add("#   $stock")
        $out.Add('#')
        $out.Add('# ONE CHANGE: search_for_pattern is NOT excluded.')
        $out.Add('#')
        $out.Add('# WHY IT IS EXCLUDED UPSTREAM. Serena removes every tool that duplicates the host agent''s')
        $out.Add('# built-ins. Deliberate, not a bug: two greps cost schema tokens and split the choice.')
        $out.Add('#')
        $out.Add('# WHY UN-EXCLUDE IT HERE. It honours the project''s ignored_paths, so it skips engine')
        $out.Add('# ThirdParty, Content and Intermediate, where a root-level Grep walks the whole engine. And if')
        $out.Add('# your routing table names it, under the stock context every one of those routes points at a')
        $out.Add('# tool that does not exist - we measured a benchmark arm calling it zero times for exactly')
        $out.Add('# that reason, and read that as the agent''s choice.')
        $out.Add('#')
        $out.Add('# Start the server with --context claude-code-ue. Re-run the installer after a Serena')
        $out.Add('# upgrade to re-derive this from the new stock file rather than keeping a stale copy.')
        $out.Add('')
        $dropped = 0
        foreach ($line in $lines) {
            if ($line -match '^\s*-\s*search_for_pattern\s*$') { $dropped++; continue }
            $out.Add($line)
        }
        if ($dropped -eq 0) {
            Warn "the stock context did not exclude search_for_pattern, so the variant is only a copy with a header. Nothing is wrong; upstream may have changed its mind."
        }
        New-Item -ItemType Directory -Path $contextsDir -Force | Out-Null
        Set-Content -LiteralPath $ueContext -Value $out -Encoding UTF8
        Ok "wrote $ueContext ($dropped exclusion removed)"
    }
}

# --- 5. restart, properly --------------------------------------------------------------------------
Write-Host ""
Write-Host "5. The server" -ForegroundColor Cyan
if ($DryRun) {
    Skip "would restart scheduled task '$TaskName'"
}
elseif (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    # Stopping the task is not enough. When the task runs the launcher, stopping it kills only the
    # watchdog; serena.exe and its language servers live on, the restarted launcher finds the port
    # busy and exits with nothing to do, and the OLD build keeps serving. The launcher's -Stop kills
    # the watchdog, the whole tree and any orphans, which is the only stop that makes the start real.
    Step "restarting scheduled task '$TaskName'"
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $launcher = Join-Path $PSScriptRoot 'Start-SerenaForUE.ps1'
    if (Test-Path $launcher) { & $launcher -Stop | ForEach-Object { Step $_ } }
    Start-ScheduledTask -TaskName $TaskName
    Ok "restarted"
}
else {
    Skip "no scheduled task '$TaskName' - restart the server yourself, and stop it fully first"
}

# --- 6. the long-lived launcher, OFFERED and never installed ----------------------------------------
#
# Runs on every path including an upgrade, deliberately. An upgrade is usually where someone meets
# this script, and "Serena got slow" is the symptom the launcher exists for - so an offer that only
# appeared on a first install would miss most of the people who want it.
Write-Host ""
Write-Host "6. Optional: one long-lived server, warmed up at logon" -ForegroundColor Cyan

$launcher = Join-Path (Split-Path -Parent $StatePath) 'Start-SerenaForUE.ps1'
if (-not (Test-Path -LiteralPath $launcher)) {
    Skip "Start-SerenaForUE.ps1 is not beside this script; nothing to offer"
}
elseif (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Ok "scheduled task '$TaskName' already exists - it was restarted above"
    Write-Host "       If it predates this plugin it may not warm up. Compare it with:" -ForegroundColor DarkGray
    Write-Host "         $launcher" -ForegroundColor DarkGray
}
else {
    Skip "no scheduled task '$TaskName' - this is an OFFER, nothing has been installed"
    Write-Host ""
    Write-Host "  Serena registered as a stdio server is started once per session, so several chats" -ForegroundColor Gray
    Write-Host "  mean several Serena processes and several language servers over one index. One" -ForegroundColor Gray
    Write-Host "  long-lived server means one of each." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  It also fixes a first-call problem. Activation is LAZY, so the language servers do" -ForegroundColor Gray
    Write-Host "  not start until the first symbolic call arrives - on a large Unreal tree that has" -ForegroundColor Gray
    Write-Host "  been measured at around 190s against a 45s tool timeout. Whoever calls first burns" -ForegroundColor Gray
    Write-Host "  two or three failed calls and reasonably concludes Serena is broken. The launcher" -ForegroundColor Gray
    Write-Host "  pays that at logon instead: warm-up finished in 154s on that tree, and a genuinely" -ForegroundColor Gray
    Write-Host "  cold client afterwards got a 0.1s handshake and a 0.1s find_symbol." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Those are one tree's numbers, not a promise. Read the script before registering it:" -ForegroundColor Gray
    Write-Host "  it starts a server, kills stale language servers, and restarts on a watchdog." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  To register it yourself:" -ForegroundColor Cyan
    # Built in variables rather than escaped inline: this is a command containing quotes,
    # printed from a script, and nesting the quoting three deep is how the first version of
    # these two lines failed to parse at all.
    $q = [char]34
    $inner = "powershell -NoProfile -ExecutionPolicy Bypass -File $launcher -Project <your project root>"
    Write-Host ("    schtasks /create /tn {0}{1}{0} /sc onlogon /rl highest /f /tr {0}{2}{0}" -f $q, $TaskName, $inner) -ForegroundColor White
    Write-Host ""
    Write-Host "  Then point your client at http://127.0.0.1:24290/mcp instead of a stdio command." -ForegroundColor Gray
}

Write-Host ""
Write-Host "Now check from OUTSIDE this shell." -ForegroundColor Cyan
Write-Host "  The proof is the running server's tool list, not the files above:"
Write-Host "    - find_symbol_indexed present"
Write-Host "    - search_for_pattern present, if you started the server with --context claude-code-ue"
Write-Host "  A correct install with an unrestarted server is the usual disagreement."
Write-Host ""
Write-Host "  Upstream is GPL-3.0-or-later from v2 (solidlsp stays MIT). You installed it from source;"
Write-Host "  nothing in this repository is derived from it."
Write-Host ""
