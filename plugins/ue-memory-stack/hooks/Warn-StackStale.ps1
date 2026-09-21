<#
    SessionStart. Says one line when the stack is wired wrong or the binaries have moved past the
    artefacts, and says nothing at all otherwise.

    Silence when healthy is the whole design. Whatever this prints goes into the session's context, so a
    cheerful "all good" banner is a few tokens of nothing in every session for ever, and a hook that costs
    a second at startup gets turned off - and then so does everything else in the file.

    It is deliberately not the doctor. No recursive walks: on a large tree those cost seconds, and this
    runs before anybody has asked for anything. Two checks, both direct file reads:

      1. A plugin this project enables that nobody installed. Enabling is not installing, nothing loads,
         and there is no error - so a session with no commands is the only symptom.
      2. A plugin DLL older than the plugin source. A dump against it writes the old format and reports
         success.

    /ue-memory-stack:doctor is the thorough version, and this points at it rather than repeating it.
#>
$ErrorActionPreference = 'SilentlyContinue'

$root = $env:CLAUDE_PROJECT_DIR
if (-not $root) { $root = (Get-Location).Path }

$lines = @()

function Read-Json([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $text = Get-Content -LiteralPath $Path -Raw
    if (-not $text) { return $null }
    return ($text -replace "^﻿", '') | ConvertFrom-Json
}

# 1. enabled but not installed
$claudeHome = $env:CLAUDE_CONFIG_DIR
if (-not $claudeHome) { $claudeHome = Join-Path $env:USERPROFILE '.claude' }
$settings = Read-Json (Join-Path $root '.claude\settings.json')
if ($settings -and $settings.enabledPlugins) {
    $installed = Read-Json (Join-Path $claudeHome 'plugins\installed_plugins.json')
    $have = @()
    if ($installed -and $installed.plugins) { $have = @($installed.plugins.PSObject.Properties.Name) }
    foreach ($p in $settings.enabledPlugins.PSObject.Properties) {
        if (-not $p.Value) { continue }
        if ($have -notcontains $p.Name) {
            $lines += "$($p.Name) is enabled by this project but not installed on this machine, so its commands are absent. Enabling is not installing: run the depot bootstrap, or claude plugin install $($p.Name) --scope project."
        }
    }
}

# 2. a DLL older than the plugin source, checked by direct path rather than by walking anything
$cfg = Read-Json (Join-Path $root '.claude\agent-memory-stack.json')
$projectDirs = @()
if ($cfg -and $cfg.projects) {
    foreach ($p in $cfg.projects) {
        if (-not $p.uproject) { continue }
        $up = $p.uproject
        if ([IO.Path]::IsPathRooted($up)) { $projectDirs += (Split-Path -Parent $up) }
        else { $projectDirs += (Split-Path -Parent (Join-Path $root ($up -replace '/', '\'))) }
    }
}

foreach ($dir in $projectDirs) {
    $pluginSource = Join-Path $dir 'Plugins\UEAgentAccelerator\Source'
    if (-not (Test-Path -LiteralPath $pluginSource)) { continue }   # referenced, not copied: nothing to compare here
    $dll = $null
    foreach ($candidate in @(
        (Join-Path $dir 'Plugins\UEAgentAccelerator\Binaries\Win64\UnrealEditor-UEAgentAcceleratorTools.dll'),
        (Join-Path $dir 'Binaries\Win64\UnrealEditor-UEAgentAcceleratorTools.dll'))) {
        if (Test-Path -LiteralPath $candidate) { $dll = Get-Item -LiteralPath $candidate; break }
    }
    if (-not $dll) { continue }

    # One level of Get-ChildItem over the plugin's own source, which is a few dozen files, not the tree.
    $newest = Get-ChildItem -LiteralPath $pluginSource -Recurse -File |
              Where-Object { $_.Extension -in '.cpp', '.h', '.cs' } |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest -and $newest.LastWriteTime -gt $dll.LastWriteTime) {
        $lines += "$(Split-Path -Leaf $dir): the UEAgentAccelerator DLL is older than its source, so a reflection dump would write the old format and report success. Rebuild before dumping."
    }
}

if ($lines) {
    Write-Output "UE memory stack:"
    foreach ($l in $lines) { Write-Output "- $l" }
    Write-Output "/ue-memory-stack:doctor checks the rest."
}

exit 0
