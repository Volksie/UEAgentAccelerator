<#
.SYNOPSIS
    Copies this marketplace into a depot or share, and writes the project settings file that points at
    it with a relative path.

.DESCRIPTION
    This is the first developer's job, so that nobody else needs the repository. A marketplace can be a
    **directory**, so the depot can hold one; what a colleague then needs is a sync and one install
    command, which ships beside the copy as Install-FromDepot.ps1.

    What it does:

      1. Copies the marketplace manifest, both plugins and the licence files into <DepotPath>.
      2. Puts Install-FromDepot.ps1 beside them: the one command each of your colleagues runs, once.
      3. Writes <ProjectRoot>\.claude\settings.json with a **relative** path to that directory and the
         plugin enabled, merging into whatever is already in the file.
      4. Prints the source control commands, because reconciling somebody's depot is not this script's
         business.

    **The settings file does not install anything, and this is the thing to be clear about.** A
    marketplace declared in a project's settings is added when somebody trusts the folder, but the
    plugin is not installed by that, and an uninstalled plugin does not load: Claude Code documents
    this as of 2.1.195. So the committed settings file enables the plugin and names where it comes
    from, and Install-FromDepot.ps1 is what actually installs it - one command per person, per project.
    A workflow where syncing alone is enough does not exist today, and a page claiming otherwise sends
    people to a session with no plugin and no error.

    The relative path in that file still matters. `claude plugin marketplace add` resolves what you
    give it - relative path included - to an absolute path and stores that in the person's own
    settings, which is correct per machine and wrong in a file everybody syncs.

    Nothing here talks to Perforce. A depot layout is somebody's own, and a script that runs `p4 edit`
    against a guess at it does more harm than printing the two commands it would have run.

.PARAMETER DepotPath
    Where the marketplace copy goes, inside the workspace that maps to your depot. This is the
    directory that ends up holding .claude-plugin\marketplace.json.

.PARAMETER ProjectRoot
    The tree whose .claude\settings.json should point at the copy. Optional: without it, the copy is
    made and the settings file is printed rather than written, which is what you want when several
    projects share one depot copy.

.PARAMETER MarketplaceName
    The name the marketplace is known by in settings, and the half after the @ in a plugin id. It
    defaults to the name inside marketplace.json, and that is almost certainly what you want: the CLI
    registers a marketplace under its declared name, so an alias in a settings file names a marketplace
    nothing else agrees exists. Overriding it is allowed and warned about.

.PARAMETER Plugins
    Which plugins to enable in the settings file. Both are always copied, because the manifest lists
    both and a manifest naming a directory that is not there is a broken marketplace. Defaults to the
    stack alone: the benchmark is machinery for reproducing published numbers, not for making a game.

.PARAMETER Check
    Compare the depot copy against this repository and report. Writes nothing, exits 1 on any
    difference. This is the one to put in front of a release, and the one that answers "is the depot
    copy behind?" without anybody having to remember.

.EXAMPLE
    .\Export-ToDepot.ps1 -DepotPath D:\p4\Tools\ClaudePlugins\UEAgentAccelerator -ProjectRoot D:\p4\MyGame
    .\Export-ToDepot.ps1 -DepotPath D:\p4\Tools\ClaudePlugins\UEAgentAccelerator -Check
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $DepotPath,
    [string] $ProjectRoot,
    # Defaults to the name declared in marketplace.json; see the note on the parameter above.
    [string] $MarketplaceName,
    [string[]] $Plugins = @('ue-memory-stack'),
    [switch] $Check,
    # Root of this repository.
    [string] $RepoPath
)

$ErrorActionPreference = 'Stop'

# Resolved here rather than in a parameter default: on Windows PowerShell 5.1 $PSScriptRoot can be
# empty while defaults are evaluated.
if (-not $RepoPath) {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $RepoPath = Split-Path -Parent $here
}
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path

function Say([string] $Text) { Write-Host $Text }
function Add_([string] $Text) { Write-Host "  + $Text" -ForegroundColor Green }
function Keep([string] $Text) { Write-Host "  = $Text" -ForegroundColor DarkGray }
function Want([string] $Text) { Write-Host "  ? $Text" -ForegroundColor Yellow }

# What a marketplace needs to work, and nothing else. The benchmark corpus, the seed project, the
# examples and the design notes are repository things: they are not read by a plugin and copying them
# puts hundreds of files in somebody's depot for no reason.
$Payload = @(
    '.claude-plugin\marketplace.json'
    'plugins'
    'LICENSE'
    'NOTICE.md'
)

# Files that live somewhere else in the repository and are wanted at the root of the depot copy.
$ExtraPayload = @{ 'tools\depot-payload\Install-FromDepot.ps1' = 'Install-FromDepot.ps1' }

# Backups and editor droppings, which have been published from here once already.
$Ignore = '\.(bak|orig|rej)$|\\__pycache__\\|\\\.git\\|\\(prev|before)-'

function Get-PayloadFiles([string] $Root) {
    $out = @()
    foreach ($item in $Payload) {
        $p = Join-Path $Root $item
        if (-not (Test-Path -LiteralPath $p)) { continue }
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            $out += [pscustomobject]@{ Relative = $item; Full = $p }
            continue
        }
        foreach ($f in Get-ChildItem -LiteralPath $p -Recurse -File) {
            if ($f.FullName -match $Ignore) { continue }
            $out += [pscustomobject]@{ Relative = $f.FullName.Substring($Root.Length).TrimStart('\'); Full = $f.FullName }
        }
    }
    return $out
}

function Get-SourceFiles([string] $Root) {
    # The repository side: payload, plus the files that move to a different place in the copy.
    $out = @(Get-PayloadFiles $Root)
    foreach ($from in $ExtraPayload.Keys) {
        $p = Join-Path $Root $from
        if (Test-Path -LiteralPath $p) { $out += [pscustomobject]@{ Relative = $ExtraPayload[$from]; Full = $p } }
        else { throw "Missing from this repository: $from" }
    }
    return $out
}

function Get-Relative([string] $From, [string] $To) {
    # [IO.Path]::GetRelativePath is .NET Core only, and half the machines this runs on are 5.1.
    $f = @(($From.TrimEnd('\', '/') -split '[\\/]') | Where-Object { $_ })
    $t = @(($To.TrimEnd('\', '/') -split '[\\/]') | Where-Object { $_ })
    if ($f[0].ToLower() -ne $t[0].ToLower()) { return $null }   # different drive or share
    $i = 0
    while ($i -lt $f.Count -and $i -lt $t.Count -and $f[$i].ToLower() -eq $t[$i].ToLower()) { $i++ }
    $up = @(@('..') * ($f.Count - $i))
    $down = if ($i -lt $t.Count) { @($t[$i..($t.Count - 1)]) } else { @() }
    $parts = @($up + $down)
    if (-not $parts) { return '.' }
    return ($parts -join '/')
}

$repoFiles = Get-SourceFiles $RepoPath
if (-not $repoFiles) { throw "No marketplace payload found under $RepoPath. Is -RepoPath right?" }

# The manifest declares a version per plugin and each plugin.json declares its own. They are written
# by hand in two places, so they drift, and a depot copy is the worst place to find that out.
$manifest = Get-Content -LiteralPath (Join-Path $RepoPath '.claude-plugin\marketplace.json') -Raw | ConvertFrom-Json
if (-not $MarketplaceName) { $MarketplaceName = $manifest.name }
elseif ($MarketplaceName -ne $manifest.name) {
    Write-Host ""
    Write-Host "You are calling the marketplace '$MarketplaceName', but it declares itself" -ForegroundColor Yellow
    Write-Host "'$($manifest.name)'. The CLI registers a marketplace under its declared name, so a plugin" -ForegroundColor Yellow
    Write-Host "id of ue-memory-stack@$MarketplaceName will not resolve for anybody who installs it" -ForegroundColor Yellow
    Write-Host "the normal way. Leave this alone unless you know why you are changing it." -ForegroundColor Yellow
}
$versionMismatch = @()
foreach ($p in $manifest.plugins) {
    $own = Join-Path $RepoPath (($p.source -replace '^\./', '') -replace '/', '\')
    $ownManifest = Join-Path $own '.claude-plugin\plugin.json'
    if (-not (Test-Path -LiteralPath $ownManifest)) { throw "The manifest lists $($p.name) at $own, which has no plugin.json." }
    $ownVersion = (Get-Content -LiteralPath $ownManifest -Raw | ConvertFrom-Json).version
    if ($p.version -and $p.version -ne $ownVersion) {
        $versionMismatch += "$($p.name): marketplace.json says $($p.version), its plugin.json says $ownVersion"
    }
}
if ($versionMismatch) {
    Write-Host ""
    Write-Host "The marketplace manifest and a plugin disagree about its version:" -ForegroundColor Red
    $versionMismatch | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    throw "Fix that before copying it into a depot, where everybody gets the disagreement."
}

Write-Host ""
Say "Repository : $RepoPath"
Say "Depot copy : $DepotPath"
Say "Marketplace: $MarketplaceName"
Write-Host ""

# --- 1. the copy ---------------------------------------------------------------------------------
$changed = 0
$stale = @()
foreach ($f in $repoFiles) {
    $dest = Join-Path $DepotPath $f.Relative
    $same = $false
    if (Test-Path -LiteralPath $dest) {
        $same = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $f.Full -Algorithm SHA256).Hash
    }
    if ($same) { continue }
    $stale += $f.Relative
    if (-not $Check) {
        $dir = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
        Copy-Item -LiteralPath $f.Full -Destination $dest -Force
        $changed++
    }
}

# A file in the depot copy that this repository no longer has. Left behind, a removed command keeps
# working for everybody who syncs, which is the confusing way round.
$extra = @()
if (Test-Path -LiteralPath $DepotPath) {
    $depotRoot = (Resolve-Path -LiteralPath $DepotPath).Path
    $depotFiles = @(Get-PayloadFiles $depotRoot)
    foreach ($name in $ExtraPayload.Values) {
        $p = Join-Path $depotRoot $name
        if (Test-Path -LiteralPath $p) { $depotFiles += [pscustomobject]@{ Relative = $name; Full = $p } }
    }
    $known = @{}
    $repoFiles | ForEach-Object { $known[$_.Relative.ToLower()] = $true }
    $ExtraPayload.Values | ForEach-Object { $known[$_.ToLower()] = $true }
    $extra = @($depotFiles | Where-Object { -not $known.ContainsKey($_.Relative.ToLower()) } | ForEach-Object { $_.Relative })
}

if ($Check) {
    if ($stale) {
        Want "$($stale.Count) file(s) in the depot copy differ from this repository or are missing"
        $stale | Select-Object -First 10 | ForEach-Object { Say "      $_" }
        if ($stale.Count -gt 10) { Say "      ... and $($stale.Count - 10) more" }
    }
    else { Keep "the depot copy matches this repository" }
    if ($extra) {
        Want "$($extra.Count) file(s) in the depot copy are not in this repository any more"
        $extra | Select-Object -First 10 | ForEach-Object { Say "      $_" }
    }
}
else {
    if ($changed) { Add_ "$changed file(s) copied into the depot" } else { Keep "the depot copy was already current" }
    if ($extra) {
        Want "$($extra.Count) file(s) in the depot copy are not in this repository any more, and were left alone"
        $extra | Select-Object -First 10 | ForEach-Object { Say "      $_" }
        Say "      Delete them in your depot deliberately: until you do, everybody who syncs keeps them."
    }
}

# --- 2. the settings file ------------------------------------------------------------------------
$relative = $null
if ($ProjectRoot) {
    if (-not (Test-Path -LiteralPath $ProjectRoot)) { throw "No such project root: $ProjectRoot" }
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $depotFull = if (Test-Path -LiteralPath $DepotPath) { (Resolve-Path -LiteralPath $DepotPath).Path } else { $DepotPath }
    $relative = Get-Relative $ProjectRoot $depotFull
    if (-not $relative) {
        throw @"
$depotFull and $ProjectRoot are not on the same drive, so no relative path joins them.
They have to be, because the path is written into a file everybody syncs: an absolute one names a
directory that exists on your machine only. Put the marketplace copy in the same client workspace as
the project.
"@
    }
}
else {
    $relative = '<RELATIVE PATH FROM THE PROJECT TO THE DEPOT COPY>'
}

$settingsJson = [ordered]@{
    extraKnownMarketplaces = [ordered]@{
        $MarketplaceName = [ordered]@{ source = [ordered]@{ source = 'directory'; path = $relative } }
    }
    enabledPlugins = [ordered]@{}
}
foreach ($p in $Plugins) { $settingsJson.enabledPlugins["$p@$MarketplaceName"] = $true }

if (-not $ProjectRoot) {
    Write-Host ""
    Say "No -ProjectRoot given, so nothing was written. Put this in each project's .claude\settings.json,"
    Say "with the path made relative to that project:"
    Write-Host ""
    Say ($settingsJson | ConvertTo-Json -Depth 6)
}
else {
    $settingsPath = Join-Path $ProjectRoot '.claude\settings.json'
    $existing = if (Test-Path -LiteralPath $settingsPath) { Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json } else { $null }

    $marketOk = $existing -and $existing.extraKnownMarketplaces -and
                $existing.extraKnownMarketplaces.$MarketplaceName -and
                $existing.extraKnownMarketplaces.$MarketplaceName.source.path -eq $relative
    $pluginsOk = $true
    foreach ($p in $Plugins) {
        if (-not ($existing -and $existing.enabledPlugins -and $existing.enabledPlugins."$p@$MarketplaceName")) { $pluginsOk = $false }
    }

    if ($marketOk -and $pluginsOk) {
        Keep ".claude/settings.json already points at $relative"
    }
    elseif ($Check) {
        Want ".claude/settings.json does not point at $relative with $($Plugins -join ', ') enabled"
    }
    else {
        # Merged rather than written: this file is the project's, and permissions and hooks in it are
        # nothing to do with us.
        $out = [ordered]@{}
        if ($existing) { foreach ($prop in $existing.PSObject.Properties) { $out[$prop.Name] = $prop.Value } }

        $markets = [ordered]@{}
        if ($out.Contains('extraKnownMarketplaces') -and $out['extraKnownMarketplaces']) {
            foreach ($prop in $out['extraKnownMarketplaces'].PSObject.Properties) { $markets[$prop.Name] = $prop.Value }
        }
        $markets[$MarketplaceName] = [ordered]@{ source = [ordered]@{ source = 'directory'; path = $relative } }
        $out['extraKnownMarketplaces'] = $markets

        $enabled = [ordered]@{}
        if ($out.Contains('enabledPlugins') -and $out['enabledPlugins']) {
            foreach ($prop in $out['enabledPlugins'].PSObject.Properties) { $enabled[$prop.Name] = $prop.Value }
        }
        foreach ($p in $Plugins) { $enabled["$p@$MarketplaceName"] = $true }
        $out['enabledPlugins'] = $enabled

        $dir = Split-Path -Parent $settingsPath
        if (-not (Test-Path -LiteralPath $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
        if ($existing) {
            $backup = "$settingsPath.bak"
            if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $settingsPath -Destination $backup }
        }
        ($out | ConvertTo-Json -Depth 12) | Out-File -FilePath $settingsPath -Encoding utf8
        Add_ ".claude/settings.json points at $relative, with $($Plugins -join ', ') enabled"
    }
}

# --- 3. what is left for a person ----------------------------------------------------------------
Write-Host ""
if ($Check) {
    if ($stale -or $extra -or ($ProjectRoot -and -not ($marketOk -and $pluginsOk))) {
        Write-Host "The depot copy is not current. Run this without -Check, then submit." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "The depot copy is current." -ForegroundColor Green
    exit 0
}

Say "Now submit it. Nothing above touched source control:"
Write-Host ""
Say "  p4 reconcile `"$DepotPath\...`""
if ($ProjectRoot) { Say "  p4 reconcile `"$(Join-Path $ProjectRoot '.claude\settings.json')`"" }
Say "  p4 submit"
Write-Host ""
Say 'Then everybody else, once each, having cloned nothing:'
Write-Host ""
Say '  p4 sync'
Say ('  cd <their project>   and run   ' + (Join-Path $DepotPath 'Install-FromDepot.ps1'))
Write-Host ""
Say 'That second step is not optional and it is not a convenience. A marketplace declared in a project'
Say 'settings file is added when the folder is trusted, but the plugin is not installed by that, and an'
Say 'uninstalled plugin does not load - with no error, which is how this looks like nothing happening.'
Say 'They must also accept the workspace trust prompt, for the same reason.'
Write-Host ""
