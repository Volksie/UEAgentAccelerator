<#
.SYNOPSIS
    Installs the UE Agent Accelerator plugin from this depot copy. Run it once, in your project.

.DESCRIPTION
    This sits beside the marketplace in your depot, and it is the whole installation for everybody who
    is not the person who put it there. You do not need the GitHub repository and you do not need to
    know any paths: this script is in the marketplace directory, so it knows where that is.

    Why a script rather than "it's already in the project's settings file": a marketplace declared in a
    project's .claude/settings.json is *added* when you trust the folder, but the plugin itself is not
    installed by that, and an uninstalled plugin does not load. Claude Code says so explicitly as of
    2.1.195. So one command per person, once per project, is the real shape of this - and this is that
    command.

    It is safe to run again, and running it again is how a synced change reaches a machine: an
    already-added marketplace is refreshed rather than duplicated, and an already-installed plugin is
    uninstalled and reinstalled, because replacing the cached copy is the only thing that changes what a
    session loads.

.PARAMETER ProjectPath
    The project to install into, which decides where the project-scope entry is written. Defaults to
    the current directory, so the usual thing is to cd to your project and run it.

.PARAMETER Bench
    Also install the benchmark plugin. Only needed if you are reproducing published numbers.

.PARAMETER WhatIfOnly
    Print the two commands and run neither.

.EXAMPLE
    cd D:\p4\MyGame
    ..\Tools\ClaudePlugins\UEAgentAccelerator\Install-FromDepot.ps1
#>
[CmdletBinding()]
param(
    [string] $ProjectPath = (Get-Location).Path,
    [switch] $Bench,
    [switch] $WhatIfOnly
)

$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }

$manifestPath = Join-Path $here '.claude-plugin\marketplace.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "No .claude-plugin\marketplace.json beside this script. It has to stay in the marketplace directory: that is how it knows what to install."
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$marketplace = $manifest.name

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    throw "claude is not on PATH. Install Claude Code first, then run this again."
}

$plugins = @('ue-memory-stack')
if ($Bench) { $plugins += 'ue-memory-bench' }

if (-not (Test-Path -LiteralPath $ProjectPath)) { throw "No such project directory: $ProjectPath" }
$ProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path

Write-Host ""
Write-Host "Marketplace : $marketplace"
Write-Host "  from      : $here"
Write-Host "Project     : $ProjectPath"
Write-Host "Installing  : $($plugins -join ', ')"
Write-Host ""

if ($WhatIfOnly) {
    Write-Host "  claude plugin marketplace add `"$here`""
    foreach ($p in $plugins) { Write-Host "  claude plugin install $p@$marketplace --scope project" }
    Write-Host ""
    Write-Host "Run without -WhatIfOnly to do it." -ForegroundColor Yellow
    exit 0
}

# Perforce marks depot files read-only, and `claude plugin install` copies them into the cache with
# that attribute intact. The uninstall below is a recursive delete, which fails on a read-only file,
# so it is the *second* install on a machine that breaks - with an EPERM naming a rename and not the
# cause. Clearing the attribute on the cached copy is what keeps a reinstall working. It runs before
# the uninstall too, so a machine that already has a read-only copy from an earlier version heals
# itself rather than needing the cache cleared by hand.
function Clear-CachedPluginReadOnly {
    param([Parameter(Mandatory)] [string] $Plugin)

    $configRoot = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
    $cached = Join-Path $configRoot "plugins\cache\$marketplace\$Plugin"
    if (-not (Test-Path -LiteralPath $cached)) { return }

    $readOnly = @(Get-ChildItem -LiteralPath $cached -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.IsReadOnly })
    if ($readOnly.Count -eq 0) { return }

    $readOnly | ForEach-Object { $_.IsReadOnly = $false }
    Write-Host "  = cleared the read-only flag Perforce put on $($readOnly.Count) cached file(s)" -ForegroundColor DarkGray
}

# --scope project writes into the project's own settings, so this has to run from the project.
Push-Location -LiteralPath $ProjectPath
try {
    $known = (& claude plugin marketplace list 2>&1) -join "`n"
    if ($known -match [regex]::Escape($marketplace)) {
        Write-Host "  = marketplace $marketplace is already known; refreshing it" -ForegroundColor DarkGray
        & claude plugin marketplace update $marketplace | Out-Null
    }
    else {
        & claude plugin marketplace add "$here"
        if ($LASTEXITCODE -ne 0) { throw "claude plugin marketplace add failed." }
    }

    foreach ($p in $plugins) {
        # A plugin is loaded from a cached copy under ~/.claude/plugins/cache/<marketplace>/<plugin>/
        # <version>, and the version string is the cache key. So a depot sync that changes content
        # without changing the version reaches nobody: `install` reports "already installed", `update`
        # reports "already at the latest version", and every session keeps loading the old copy with
        # nothing anywhere saying so. Uninstalling first is what makes a sync land.
        $listed = (& claude plugin list 2>&1) -join "`n"
        if ($listed -match [regex]::Escape("$p@$marketplace")) {
            Write-Host "  = $p is installed; reinstalling so a synced change actually lands" -ForegroundColor DarkGray
            Clear-CachedPluginReadOnly -Plugin $p
            & claude plugin uninstall "$p@$marketplace" --scope project | Out-Null
        }
        & claude plugin install "$p@$marketplace" --scope project
        if ($LASTEXITCODE -ne 0) { throw "claude plugin install $p@$marketplace failed." }
        Clear-CachedPluginReadOnly -Plugin $p
    }

    Write-Host ""
    & claude plugin list
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Open the project in Claude and accept the workspace trust prompt if you are asked:" -ForegroundColor Green
Write-Host "a project-scope plugin loads only after that, and dismissing it gives a session with no"
Write-Host "plugin and no error to explain why. Then /ue-memory-stack:setup, once per project."
Write-Host ""
Write-Host "Later, when somebody syncs a change into the depot: p4 sync, then run this again, then restart"
Write-Host "Claude. Running it again is not optional: a session loads the plugin from a cached copy keyed by"
Write-Host "version, so a synced change under the same version reaches nothing until the reinstall this"
Write-Host "script does. `"claude plugin update`" will tell you that you are already up to date, and be wrong."
Write-Host ""
