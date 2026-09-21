<#
.SYNOPSIS
    Checks the memory stack on this machine and in this tree, and reports what is broken in a way that
    names the remedy. Changes nothing.

.DESCRIPTION
    Every layer in this stack fails quietly. That is not a figure of speech: a missing artefact is not an
    error, a stale DLL dumps the old format and reports success, an unpatched Serena answers in a tenth of
    a second with nothing, and a plugin that nobody installed simply has no commands. None of that
    produces a message. This is the script that produces the messages.

    It is read only. It runs no build, no dump, and no source control write.

    Each check reports one of four verdicts, and the difference between the last two matters:

      OK       checked, and correct
      WARN     checked, and probably wrong - or right but worth knowing
      FAIL     checked, and wrong
      UNKNOWN  **not checked**, because the thing that would answer it is not available here

    UNKNOWN is a first-class result rather than a quiet pass. A health report that silently omits what it
    could not test reads exactly like one where everything is fine, and that is the failure this whole
    stack is about.

.PARAMETER ProjectPath
    A .uproject to check. Repeatable. Left out, every project in the stack config is checked, and failing
    that every .uproject under -Root.

.PARAMETER Root
    The tree root holding .claude/. Defaults to the current directory.

.PARAMETER Json
    Emit the findings as JSON instead of text, for a hook or a build step to read.

.PARAMETER SkipSerena
    Do not look for Serena. Use it on a machine that deliberately runs without Layers 0 and 1.

.PARAMETER SerenaPath
    Serena's site-packages directory, for an install that is not under a uv tools directory.

.EXAMPLE
    .\Test-MemoryStackHealth.ps1
    .\Test-MemoryStackHealth.ps1 -Root D:\Tree -ProjectPath D:\Tree\GameA\GameA.uproject
    .\Test-MemoryStackHealth.ps1 -Json
#>
[CmdletBinding()]
param(
    [string[]] $ProjectPath,
    [string] $Root = (Get-Location).Path,
    [switch] $Json,
    [switch] $SkipSerena,
    # Serena's site-packages, when it is not under a uv tools directory. Also what makes the patch
    # check testable: a health check nobody can point at a broken install is a health check nobody has
    # seen fail.
    [string] $SerenaPath
)

$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$PluginRoot = Split-Path -Parent $here

$Root = (Resolve-Path -LiteralPath $Root).Path
$findings = [System.Collections.Generic.List[object]]::new()

function Add-Finding([string] $Area, [string] $Check, [string] $Verdict, [string] $Detail, [string] $Remedy = '') {
    $findings.Add([pscustomobject]@{
        Area = $Area; Check = $Check; Verdict = $Verdict; Detail = $Detail; Remedy = $Remedy
    })
}

function Get-ClaudeHome {
    if ($env:CLAUDE_CONFIG_DIR) { return $env:CLAUDE_CONFIG_DIR }
    return (Join-Path $env:USERPROFILE '.claude')
}

# What a session actually loads out of a plugin directory. Not the whole tree: a cached copy can
# legitimately lack things the source has, and a comparison that counts those as drift cries wolf for
# ever. Per file, so the finding can name what moved.
function Get-RuntimeFingerprint([string] $Root) {
    if (-not (Test-Path -LiteralPath $Root)) { return $null }
    $map = [ordered]@{}
    foreach ($sub in '.claude-plugin', 'hooks', 'commands', 'skills', 'agents', 'scripts', 'serena', 'templates') {
        $dir = Join-Path $Root $sub
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        foreach ($f in Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue) {
            $rel = $f.FullName.Substring($Root.Length).TrimStart('\').ToLower()
            $map[$rel] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        }
    }
    return $map
}

function Compare-Fingerprint($Loaded, $Source) {
    # Returns the paths that differ, loudest first: hooks decide behaviour without anybody asking.
    $diff = @()
    foreach ($k in $Source.Keys) {
        if (-not $Loaded.Contains($k)) { $diff += "$k (missing from the loaded copy)" }
        elseif ($Loaded[$k] -ne $Source[$k]) { $diff += $k }
    }
    foreach ($k in $Loaded.Keys) {
        if (-not $Source.Contains($k)) { $diff += "$k (only in the loaded copy)" }
    }
    return @($diff | Sort-Object { if ($_ -like 'hooks\*') { 0 } elseif ($_ -like 'commands\*' -or $_ -like 'skills\*') { 1 } else { 2 } }, { $_ })
}

function Read-JsonFile([string] $Path) {
    # -Raw and a BOM: a .uproject written by the editor carries one, and ConvertFrom-Json on PowerShell
    # 5.1 chokes on it.
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $text = Get-Content -LiteralPath $Path -Raw
    if (-not $text) { return $null }
    return ($text -replace "^\xEF\xBB\xBF", '' -replace "^\uFEFF", '') | ConvertFrom-Json
}

# --- 1. is the plugin actually installed, or only enabled? ----------------------------------------
# This is the failure that cost a whole phase of this project's own design: a project's settings file
# enables a plugin and names its marketplace, and none of that installs anything. The commands are
# simply absent, and the settings file reads as perfectly correct.
function Test-PluginWiring {
    $claudeHome = Get-ClaudeHome
    $projectSettings = Read-JsonFile (Join-Path $Root '.claude\settings.json')
    $enabled = @()
    if ($projectSettings -and $projectSettings.enabledPlugins) {
        $enabled = @($projectSettings.enabledPlugins.PSObject.Properties | Where-Object { $_.Value } | ForEach-Object { $_.Name })
    }

    $installedFile = Join-Path $claudeHome 'plugins\installed_plugins.json'
    $installed = Read-JsonFile $installedFile
    $installedIds = @()
    if ($installed -and $installed.plugins) { $installedIds = @($installed.plugins.PSObject.Properties.Name) }

    if (-not $enabled) {
        Add-Finding 'Plugin' 'enabled in this project' 'WARN' `
            "No enabledPlugins in $Root\.claude\settings.json." `
            'Fine if everybody installs the plugin personally. In a shared tree, commit the entry so the tree says what it wants.'
    }
    foreach ($id in $enabled) {
        if ($installedIds -contains $id) {
            Add-Finding 'Plugin' "$id installed" 'OK' 'Enabled by this project and present in installed_plugins.json.'
        }
        else {
            Add-Finding 'Plugin' "$id installed" 'FAIL' `
                "This project enables $id, but it is not in $installedFile. Enabling is not installing: nothing loads, and there is no error anywhere." `
                "Run the depot bootstrap, or: claude plugin install $id --scope project"
        }
    }

    # Is the copy a session loads the copy the marketplace holds? For a directory marketplace these can
    # differ silently and indefinitely: the plugin is loaded from ~/.claude/plugins/cache/<marketplace>/
    # <plugin>/<version>, the version string is the cache key, and a content change under an unchanged
    # version reaches nobody. `claude plugin update` reports "already at the latest version" and is right
    # about the version and wrong about the content. This cost two rounds of hook testing to notice.
    $markets = Read-JsonFile (Join-Path $claudeHome 'plugins\known_marketplaces.json')
    foreach ($id in $installedIds) {
        $entries = @($installed.plugins.$id)
        foreach ($e in $entries) {
            if (-not $e.installPath) { continue }
            $marketName = ($id -split '@')[-1]
            $pluginName = ($id -split '@')[0]
            $market = $null
            if ($markets) { $market = $markets.$marketName }
            if (-not $market -or $market.source.source -ne 'directory') { continue }

            $sourceDir = Join-Path $market.source.path ("plugins\" + $pluginName)
            if (-not (Test-Path -LiteralPath (Join-Path $sourceDir '.claude-plugin\plugin.json'))) { continue }
            $sourceVersion = (Read-JsonFile (Join-Path $sourceDir '.claude-plugin\plugin.json')).version

            if ($sourceVersion -ne $e.version) {
                Add-Finding 'Plugin' "$id is the installed version" 'FAIL' `
                    "Installed $($e.version); the marketplace at $($market.source.path) now declares $sourceVersion." `
                    "claude plugin update $pluginName --scope $($e.scope), then restart. Sessions load the installed copy, not the marketplace."
                continue
            }

            # Same version, different bytes: the case nothing else reports at all.
            $loaded = Get-RuntimeFingerprint $e.installPath
            $source = Get-RuntimeFingerprint $sourceDir
            if (-not $loaded -or -not $source) {
                Add-Finding 'Plugin' "$id matches its marketplace" 'UNKNOWN' `
                    "Could not read one of the two copies ($($e.installPath), $sourceDir), so whether your sessions load what the marketplace holds was not tested." ''
            }
            else {
                $diff = Compare-Fingerprint $loaded $source
                if ($diff.Count -gt 0) {
                    $shown = ($diff | Select-Object -First 5) -join ', '
                    if ($diff.Count -gt 5) { $shown += ", and $($diff.Count - 5) more" }
                    Add-Finding 'Plugin' "$id matches its marketplace" 'FAIL' `
                        ("The copy your sessions load differs from the marketplace it came from, at the same version " +
                         "$($e.version): $shown. Commands, skills and especially hooks are read from the loaded copy " +
                         "($($e.installPath)), so changes in the marketplace are being ignored and nothing else says so.") `
                        "Uninstall and reinstall it - a same-version update reports success and replaces nothing - or bump the plugin's version. Then restart, because hooks load at session start."
                }
                else {
                    Add-Finding 'Plugin' "$id matches its marketplace" 'OK' "The loaded copy and the marketplace agree, at $($e.version)."
                }
            }
        }
    }

    # Trust, which gates project-scope plugins, their hooks and their MCP servers.
    $dotClaude = Join-Path (Split-Path -Parent $claudeHome) '.claude.json'
    if ($claudeHome -ne (Join-Path $env:USERPROFILE '.claude')) { $dotClaude = Join-Path $claudeHome '.claude.json' }
    $top = Read-JsonFile $dotClaude
    $entry = $null
    if ($top -and $top.projects) {
        foreach ($p in $top.projects.PSObject.Properties) {
            if ($p.Name.Replace('/', '\').TrimEnd('\') -ieq $Root.TrimEnd('\')) { $entry = $p.Value; break }
        }
    }
    if (-not $entry) {
        Add-Finding 'Plugin' 'workspace trusted' 'UNKNOWN' `
            "No entry for $Root in $dotClaude, so this tree has not been opened by this CLI, or trust is recorded somewhere this script cannot see." `
            'If the commands are missing, reopen the project and accept the trust prompt.'
    }
    elseif ($entry.hasTrustDialogAccepted) {
        Add-Finding 'Plugin' 'workspace trusted' 'OK' 'Trust accepted, so project-scope plugins, hooks and MCP servers can load.'
    }
    else {
        Add-Finding 'Plugin' 'workspace trusted' 'FAIL' `
            'The workspace trust prompt has not been accepted. A project-scope plugin does not load at all until it is, with no error.' `
            'Reopen the project and accept the prompt.'
    }
}

# --- 2. the stack config --------------------------------------------------------------------------
function Test-StackConfig {
    $path = Join-Path $Root '.claude\agent-memory-stack.json'
    if (-not (Test-Path -LiteralPath $path)) {
        Add-Finding 'Config' 'agent-memory-stack.json' 'WARN' `
            "Not at $path. Every tool then needs its paths spelled out on the command line, and setup and refresh can disagree about which projects exist." `
            'Run /ue-memory-stack:setup, which writes it from what it finds.'
        return $null
    }
    $cfg = $null
    try { $cfg = Read-JsonFile $path }
    catch {
        Add-Finding 'Config' 'agent-memory-stack.json' 'FAIL' "It does not parse: $($_.Exception.Message)" 'Fix the JSON; every tool that reads it stops here.'
        return $null
    }

    $raw = Get-Content -LiteralPath $path -Raw
    $placeholders = [regex]::Matches($raw, '<[A-Z][A-Z ]+>') | ForEach-Object { $_.Value } | Sort-Object -Unique
    if ($placeholders) {
        Add-Finding 'Config' 'config placeholders' 'FAIL' `
            "Still carries $($placeholders.Count) unfilled placeholder(s): $($placeholders -join ', '). Setup writes those where it could not know the answer." `
            'Fill them in. A run that reads one of these fails forty minutes into a build, not now.'
    }
    else {
        Add-Finding 'Config' 'config placeholders' 'OK' 'No unfilled placeholders.'
    }
    return $cfg
}

# --- 3. the C++ plugin in the project -------------------------------------------------------------
function Test-ProjectPlugin([string] $UProject) {
    $projectDir = Split-Path -Parent $UProject
    $name = [IO.Path]::GetFileNameWithoutExtension($UProject)
    $descriptor = Read-JsonFile $UProject

    $entry = $null
    if ($descriptor.Plugins) { $entry = $descriptor.Plugins | Where-Object { $_.Name -eq 'UEAgentAccelerator' } | Select-Object -First 1 }
    if (-not $entry) {
        Add-Finding "Project:$name" 'plugin enabled in the descriptor' 'FAIL' `
            'UEAgentAccelerator is not in the Plugins array. A plugin on disk but not enabled is loaded by nothing, and the dump reports 0 modules.' `
            'Run /ue-memory-stack:setup.'
    }
    elseif ($entry.Enabled -eq $false) {
        Add-Finding "Project:$name" 'plugin enabled in the descriptor' 'FAIL' 'Listed with Enabled false.' 'Set Enabled true, or re-run setup.'
    }
    else {
        Add-Finding "Project:$name" 'plugin enabled in the descriptor' 'OK' 'Listed and enabled.'
    }

    # Copy, or referenced through AdditionalPluginDirectories. Both are legitimate, and looking only in
    # <project>\Plugins reports a referenced install as missing - a bug this project shipped once.
    $copy = Join-Path $projectDir 'Plugins\UEAgentAccelerator'
    $source = $null
    if (Test-Path -LiteralPath (Join-Path $copy 'UEAgentAccelerator.uplugin')) { $source = $copy }
    else {
        foreach ($dir in @($descriptor.AdditionalPluginDirectories)) {
            if (-not $dir) { continue }
            $candidate = if ([IO.Path]::IsPathRooted($dir)) { $dir } else { Join-Path $projectDir $dir }
            $probe = Join-Path $candidate 'UEAgentAccelerator\UEAgentAccelerator.uplugin'
            if (Test-Path -LiteralPath $probe) { $source = Split-Path -Parent $probe; break }
        }
    }

    if (-not $source) {
        Add-Finding "Project:$name" 'plugin present' 'FAIL' 'No UEAgentAccelerator.uplugin in the project or in any AdditionalPluginDirectories entry.' 'Run /ue-memory-stack:setup.'
        return
    }
    Add-Finding "Project:$name" 'plugin present' 'OK' "At $source$(if ($source -ne $copy) { ' (referenced, not copied)' })."

    # Version drift against the plugin this script ships inside.
    # Keyed by project. A flat record predates that and describes exactly one project, so it counts
    # only for the project it names - reading it for any other reports a version this copy never came
    # from, which is worse than reporting nothing.
    $installDoc = Read-JsonFile (Join-Path $Root '.claude\.uea-install.json')
    $record = $null
    if ($installDoc) {
        if ($installDoc.PSObject.Properties.Name -contains 'projects') {
            if ($installDoc.projects -and ($installDoc.projects.PSObject.Properties.Name -contains $name)) { $record = $installDoc.projects.$name }
        }
        elseif ($installDoc.project -eq $name) { $record = $installDoc }
    }
    $pluginVersion = (Read-JsonFile (Join-Path $PluginRoot '.claude-plugin\plugin.json')).version
    if ($source -ne $copy) {
        Add-Finding "Project:$name" 'plugin version' 'OK' "Referenced rather than copied, so there is no second copy to fall behind. Still needs its own build."
    }
    elseif (-not $record) {
        $why = if ($installDoc) {
            ".claude/.uea-install.json has no entry for $name, so nothing records which plugin version this project's copy came from."
        } else {
            'No .claude/.uea-install.json, so there is nothing recording which plugin version this copy came from.'
        }
        Add-Finding "Project:$name" 'plugin version' 'UNKNOWN' $why `
            "Run /ue-memory-stack:setup for $name to write its entry. Until then a plugin update cannot be detected here."
    }
    elseif ($record.pluginVersion -ne $pluginVersion) {
        Add-Finding "Project:$name" 'plugin version' 'FAIL' `
            "The copy in the project came from plugin $($record.pluginVersion); this plugin is $pluginVersion. The old source builds and dumps happily, in the old format." `
            'Run /ue-memory-stack:setup, then rebuild before the next dump.'
    }
    else {
        Add-Finding "Project:$name" 'plugin version' 'OK' "Copy matches this plugin ($pluginVersion)."
    }

    # The stale DLL: the single most expensive silent failure in this stack.
    $dll = Get-ChildItem -LiteralPath $projectDir -Recurse -Filter 'UnrealEditor-UEAgentAcceleratorTools.dll' -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $newestSource = Get-ChildItem -LiteralPath (Join-Path $source 'Source') -Recurse -File -ErrorAction SilentlyContinue |
                    Where-Object { $_.Extension -in '.cpp', '.h', '.cs' } |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $dll) {
        Add-Finding "Project:$name" 'plugin binaries' 'WARN' 'No UnrealEditor-UEAgentAcceleratorTools.dll under this project. Nothing has built it here yet.' 'Build the editor target: /ue-memory-stack:update does it.'
    }
    elseif ($newestSource -and $dll.LastWriteTime -lt $newestSource.LastWriteTime) {
        Add-Finding "Project:$name" 'plugin binaries' 'FAIL' `
            "The DLL ($($dll.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))) is older than the plugin source ($($newestSource.Name), $($newestSource.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))). A dump against it logs its usual summary and writes the old format." `
            'Rebuild before dumping.'
    }
    else {
        Add-Finding "Project:$name" 'plugin binaries' 'OK' "DLL is newer than the plugin source ($($dll.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))."
    }
}

# --- 4. the artefacts -----------------------------------------------------------------------------
function Test-Artefacts([string] $UProject, [string] $OutDir) {
    $projectDir = Split-Path -Parent $UProject
    $name = [IO.Path]::GetFileNameWithoutExtension($UProject)
    if (-not $OutDir) { $OutDir = Join-Path $projectDir 'Docs\AgentMemory' }

    if (-not (Test-Path -LiteralPath $OutDir)) {
        Add-Finding "Project:$name" 'artefacts exist' 'FAIL' "Nothing at $OutDir. An agent that finds no artefacts does not complain, it goes back to grepping and answers worse." 'Run /ue-memory-stack:update.'
        return
    }

    $classes = @(Get-ChildItem -LiteralPath (Join-Path $OutDir 'classes') -Filter '*.md' -ErrorAction SilentlyContinue)
    $bps     = @(Get-ChildItem -LiteralPath (Join-Path $OutDir 'blueprints') -Filter '*.md' -ErrorAction SilentlyContinue)
    $callers = @(Get-ChildItem -LiteralPath (Join-Path $OutDir 'bpcallers') -Filter '*.md' -ErrorAction SilentlyContinue)
    Add-Finding "Project:$name" 'artefacts exist' 'OK' "$($classes.Count) class file(s), $($bps.Count) blueprint file(s), $($callers.Count) caller file(s) under $OutDir."

    # 0 modules and 0 Blueprints are the two summaries that look like a clean run.
    $index = Join-Path $OutDir 'index.md'
    if (-not (Test-Path -LiteralPath $index)) {
        Add-Finding "Project:$name" 'reflection index' 'FAIL' 'No index.md, so the dump did not finish.' 'Re-run the dump and read its summary lines.'
    }
    elseif ($classes.Count -eq 0) {
        Add-Finding "Project:$name" 'reflection index' 'FAIL' 'index.md exists and there are no class files. That is a dump that reported success and wrote nothing usable.' 'See troubleshooting.md, "It reports 0 modules".'
    }
    else {
        Add-Finding "Project:$name" 'reflection index' 'OK' "index.md present with $($classes.Count) class file(s) beside it."
    }

    # An interrupted run leaves a ~1 KB BlueprintCallers.md that still reads as an authoritative "no
    # Blueprint callers anywhere", which is the most confidently wrong artefact this stack can produce.
    $callerIndex = Join-Path $OutDir 'BlueprintCallers.md'
    if (Test-Path -LiteralPath $callerIndex) {
        $size = (Get-Item -LiteralPath $callerIndex).Length
        if ($callers.Count -eq 0 -and $size -lt 2KB) {
            Add-Finding "Project:$name" 'Blueprint callers' 'FAIL' `
                "BlueprintCallers.md is $size bytes with no bpcallers/ files behind it. An empty index reads as 'no Blueprint calls this', and the dump wipes that directory before rewriting it - so an interrupted run leaves exactly this." `
                'Re-run the dump. Until then, treat absence in that index as unknown rather than as no callers.'
        }
        else {
            Add-Finding "Project:$name" 'Blueprint callers' 'OK' "Index is $([math]::Round($size / 1KB, 1)) KB with $($callers.Count) per-class file(s)."
        }
    }
    else {
        Add-Finding "Project:$name" 'Blueprint callers' 'WARN' 'No BlueprintCallers.md. The Blueprint half of a blast radius question has no source here.' 'Re-run the dump.'
    }

    # Staleness. Revisions where source control can answer; file times only as the weaker answer, said
    # to be the weaker answer.
    $sourceDir = Join-Path $projectDir 'Source'
    if (Test-Path -LiteralPath $sourceDir) {
        $newestSource = Get-ChildItem -LiteralPath $sourceDir -Recurse -File -ErrorAction SilentlyContinue |
                        Where-Object { $_.Extension -in '.cpp', '.h', '.cs' } |
                        Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $newestArtefact = Get-ChildItem -LiteralPath $OutDir -Recurse -File -ErrorAction SilentlyContinue |
                          Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($newestSource -and $newestArtefact) {
            if ($newestSource.LastWriteTime -gt $newestArtefact.LastWriteTime) {
                Add-Finding "Project:$name" 'artefacts current' 'WARN' `
                    "By file time, $($newestSource.Name) is newer than anything in the artefacts. File times are the weak answer - a sync stamps every file with the time it wrote it - so treat this as a prompt to compare revisions, not as proof." `
                    'Compare revisions (p4 changes -m1, or git log -1 over each path). If the artefacts really are behind, regenerate.'
            }
            else {
                Add-Finding "Project:$name" 'artefacts current' 'OK' 'No source file is newer than the artefacts by file time. Revisions are the real test; this is the cheap one.'
            }
        }
    }

    # The format stamp, which is what makes "these artefacts are from before that change" answerable
    # at all. MANIFEST.md carries it; artefact-format.json says what this plugin expects.
    $expected = $null
    $formatFile = Join-Path $PluginRoot 'artefact-format.json'
    if (Test-Path -LiteralPath $formatFile) { $expected = (Read-JsonFile $formatFile).artefactFormat }

    $manifest = Join-Path $OutDir 'MANIFEST.md'
    if (-not $expected) {
        Add-Finding "Project:$name" 'artefact format' 'UNKNOWN' `
            "No artefact-format.json in this plugin, so there is nothing to compare the artefacts against." ''
    }
    elseif (-not (Test-Path -LiteralPath $manifest)) {
        Add-Finding "Project:$name" 'artefact format' 'WARN' `
            'No MANIFEST.md, so these artefacts carry no format, no engine version and no generation time.' `
            'Regenerate: /ue-memory-stack:update.'
    }
    else {
        $manText = Get-Content -LiteralPath $manifest -Raw
        $m = [regex]::Match($manText, '\|\s*Artefact format\s*\|\s*(\d+)\s*\|')
        $w = [regex]::Match($manText, '\|\s*Written by plugin\s*\|\s*([^|]+?)\s*\|')
        $writtenBy = if ($w.Success) { $w.Groups[1].Value } else { 'an unrecorded version' }

        if (-not $m.Success) {
            # Not a failure: it is what every artefact set written before the stamp existed looks like,
            # and saying "unknown" here would hide the one thing that is actually known about them.
            Add-Finding "Project:$name" 'artefact format' 'WARN' `
                "MANIFEST.md carries no format row, so these artefacts were written before the dump stamped one - by $writtenBy. Whether they match what this plugin expects (format $expected) cannot be told by reading them." `
                'Regenerate once to get a stamp, and then this question has an answer for ever after.'
        }
        elseif ([int]$m.Groups[1].Value -ne [int]$expected) {
            Add-Finding "Project:$name" 'artefact format' 'FAIL' `
                "These artefacts are format $($m.Groups[1].Value), written by plugin $writtenBy; this plugin expects format $expected. The shape has changed, so reading them gives answers that are wrong in ways the files do not show." `
                'Regenerate: /ue-memory-stack:update. Build first if the plugin also moved.'
        }
        else {
            Add-Finding "Project:$name" 'artefact format' 'OK' "Format $expected, written by plugin $writtenBy."
        }
    }
}

# --- 5. Layer 0, the compile database -------------------------------------------------------------
function Test-CompileDatabase([string] $Dir) {
    $db = Join-Path $Dir 'compile_commands.json'
    if (-not (Test-Path -LiteralPath $db)) {
        Add-Finding 'Layer 0' 'compile_commands.json' 'WARN' "Not at $db. Without it clangd cannot parse Unreal source at all, so Layer 1 has nothing to stand on." 'Run New-CompileDatabase.ps1, or skip Layers 0 and 1 deliberately.'
        return
    }
    $item = Get-Item -LiteralPath $db
    Add-Finding 'Layer 0' 'compile_commands.json' 'OK' "$([math]::Round($item.Length / 1MB, 1)) MB, written $($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))."

    $newestBuildCs = Get-ChildItem -LiteralPath $Dir -Recurse -Filter '*.Build.cs' -ErrorAction SilentlyContinue |
                     Where-Object { $_.FullName -notmatch '\\(Intermediate|Binaries)\\' } |
                     Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newestBuildCs -and $newestBuildCs.LastWriteTime -gt $item.LastWriteTime) {
        Add-Finding 'Layer 0' 'compile database current' 'WARN' `
            "$($newestBuildCs.Name) is newer than the database. Timestamps are sound here, because this file is never synced." `
            'Regenerate the compile database.'
    }
    elseif ($newestBuildCs) {
        Add-Finding 'Layer 0' 'compile database current' 'OK' 'Newer than the newest .Build.cs.'
    }

    # The database is pointers into response files under Intermediate. Delete those and clangd breaks in
    # a way that looks like clangd being broken, which is a bad afternoon.
    $missing = 0
    $sampled = 0
    try {
        $text = Get-Content -LiteralPath $db -Raw
        # Not anchored on @ followed by a drive letter: the database writes @\"C:/...\", so that
        # pattern matched nothing and the check reported UNKNOWN on a file full of them. Response files
        # are the only .rsp paths in there, so matching the path alone is enough.
        $refs = [regex]::Matches($text, '(?<p>[A-Za-z]:[^"]+?\.(?:rsp|response))')
        $sample = @($refs | Select-Object -First 40)
        foreach ($m in $sample) {
            $sampled++
            if (-not (Test-Path -LiteralPath $m.Groups['p'].Value)) { $missing++ }
        }
    }
    catch { }
    if ($sampled -eq 0) {
        Add-Finding 'Layer 0' 'response files' 'UNKNOWN' 'No @response-file references found to sample, so whether the database still points at real files was not tested.'
    }
    elseif ($missing -gt 0) {
        Add-Finding 'Layer 0' 'response files' 'FAIL' `
            "$missing of $sampled sampled @response files are gone. The database is pointers into Intermediate, so a cleaned Intermediate breaks clangd in a way that looks like clangd being broken." `
            'Regenerate the compile database. Do not delete Intermediate\Build\**\*GCD\ while using it.'
    }
    else {
        Add-Finding 'Layer 0' 'response files' 'OK' "$sampled sampled @response files all exist."
    }
}

# --- 6. Layer 1, Serena ---------------------------------------------------------------------------
# The fixes are no longer patches applied to an install: they are commits on the fork the installer
# installs, so this asks whether the right BUILD is there rather than whether a diff was applied.
function Test-SerenaPatches {
    $statePath = Join-Path $PluginRoot 'serena\layer1-state.json'
    $state = Read-JsonFile $statePath
    if (-not $state) {
        Add-Finding 'Layer 1' 'layer 1 state' 'UNKNOWN' "No $statePath, so there is nothing describing what a working Layer 1 looks like." ''
        return
    }

    # Writes from a packaged app can be redirected into private storage, and then every check made from
    # here reads a copy the real server never loads - and says it worked.
    $probe = Join-Path $env:APPDATA ('uea-health-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $redirected = $false
    try {
        Set-Content -LiteralPath $probe -Value 'probe' -ErrorAction Stop
        $mirror = Join-Path $env:LOCALAPPDATA "Packages\*\LocalCache\Roaming\$(Split-Path -Leaf $probe)"
        if (@(Resolve-Path -Path $mirror -ErrorAction SilentlyContinue).Count -gt 0) { $redirected = $true }
    }
    catch { }
    finally { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
    if ($redirected) {
        Add-Finding 'Layer 1' 'shell can see Serena' 'UNKNOWN' `
            "This shell's %APPDATA% writes are redirected into a packaged app's private storage, so anything read here about Serena describes a copy the real server never loads." `
            'Re-run this from a normal PowerShell window before trusting any Layer 1 result.'
        return
    }

    $sitePackages = $null
    if ($SerenaPath) {
        if (-not (Test-Path -LiteralPath $SerenaPath)) {
            Add-Finding 'Layer 1' 'Serena installed' 'FAIL' "-SerenaPath points at $SerenaPath, which is not there." 'Give it the site-packages directory, or leave it out and let it search.'
            return
        }
        $sitePackages = (Resolve-Path -LiteralPath $SerenaPath).Path
    }
    foreach ($root in @($env:APPDATA, $env:LOCALAPPDATA, (Join-Path $env:USERPROFILE '.local\share'))) {
        if ($sitePackages) { break }
        if (-not $root) { continue }
        $candidate = Join-Path $root 'uv\tools\serena-agent\Lib\site-packages'
        if (Test-Path -LiteralPath $candidate) { $sitePackages = $candidate; break }
    }
    if (-not $sitePackages) {
        Add-Finding 'Layer 1' 'Serena installed' 'WARN' 'No Serena environment found under uv tools. Layers 0 and 1 are optional, so this is only a problem if you expected them.' 'Install Serena, or pass -SkipSerena.'
        return
    }

    # EVERY dist-info, not the first. Two ways more than one turns up: an in-place upgrade leaves the
    # old one behind, and a packaged app's shell sees a UNION of its redirected copy and the real one.
    # On the machine this was written on the real site-packages holds 2.0.0.dev0 alone and the app
    # container's private copy holds 1.7.0 alone, yet a shell inside the container lists both at the
    # same path - and `-First 1` then reports 1.7.0, which is serving nothing. The redirection probe
    # above is the real protection; this is so the version line cannot lie on its own.
    $versions = @(Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'serena_agent-*.dist-info' -ErrorAction SilentlyContinue |
                  ForEach-Object { $_.Name -replace '^serena_agent-', '' -replace '\.dist-info$', '' })
    $version = $versions -join ', '
    if ($versions.Count -gt 1) {
        Add-Finding 'Layer 1' 'Serena version' 'WARN' `
            "site-packages holds more than one dist-info: $version. That is left over from an in-place upgrade, so anything reading the version from the first match reports the wrong one." `
            'Harmless in itself. Read direct_url.json in each dist-info, or ask the running server, for which build is actually live.'
    }
    elseif ($versions.Count -eq 1 -and $state.serenaVersion -and $versions[0] -ne $state.serenaVersion) {
        Add-Finding 'Layer 1' 'Serena version' 'WARN' `
            "Serena is $version; this plugin expects $($state.serenaVersion), the build carrying the fixes below." `
            'Re-run serena\Install-SerenaForUE.ps1 from a normal PowerShell window, then restart the server.'
    }
    elseif ($versions.Count -eq 1) {
        Add-Finding 'Layer 1' 'Serena version' 'OK' "Serena $version, which is the build these fixes are in."
    }

    $absent = @()
    $notes  = @()
    foreach ($fix in $state.fixes) {
        $base = if ($fix.root -eq 'home') { $env:USERPROFILE } else { $sitePackages }
        $target = Join-Path $base ($fix.file -replace '/', '\')

        # Some fixes are satisfied by any file in a directory rather than by one name. A team running its
        # own Serena context is the case: the installer warns about it, so failing on the canonical name
        # would report a deliberate local choice as a broken install.
        if ($fix.anyFileIn -and -not (Test-Path -LiteralPath $target)) {
            $dir = Join-Path $base ($fix.anyFileIn -replace '/', '\')
            $alt = @(Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue |
                     Where-Object { (Get-Content -LiteralPath $_.FullName -Raw) -match [regex]::Escape($fix.sentinel) })
            if ($alt) {
                $notes += "$($fix.id): not $(Split-Path -Leaf $target), but $(($alt | ForEach-Object Name) -join ', ') carries it - start the server with --context <that name>"
                continue
            }
        }

        if (-not (Test-Path -LiteralPath $target)) { $absent += "$($fix.id) (no $($fix.file))"; continue }
        if ((Get-Content -LiteralPath $target -Raw) -notmatch [regex]::Escape($fix.sentinel)) { $absent += "$($fix.id): $($fix.matters)" }
    }
    if ($notes) {
        Add-Finding 'Layer 1' 'context variant' 'WARN' `
            (($notes -join ' | ') + '.') `
            'Nothing to fix if that is deliberate. Check the server is actually started with that context, because a name nobody passes is a context nobody loads.'
    }
    if ($absent) {
        Add-Finding 'Layer 1' 'fixes present' 'FAIL' `
            ("$($absent.Count) of $($state.fixes.Count) fixes are not in the installed Serena: " + ($absent -join ' | ')) `
            'Run serena\Install-SerenaForUE.ps1 from a normal PowerShell window, then restart the server. If it persists, the installed build is not the fork - read direct_url.json.'
    }
    else {
        Add-Finding 'Layer 1' 'fixes present' 'OK' "All $($state.fixes.Count) fixes present in $sitePackages."
    }

    # Files on disk are not the same claim as a working server, and this is the distinction that has
    # wasted the most time on this stack.
    Add-Finding 'Layer 1' 'server answers' 'UNKNOWN' `
        'Whether the running server actually exposes these tools is not something a script can see: it needs a tool call from inside your agent.' `
        'Ask for find_symbol_indexed and search_for_pattern in a session. A correct install with an unrestarted server is the usual disagreement.'
}

# --- run ------------------------------------------------------------------------------------------
Test-PluginWiring
$cfg = Test-StackConfig

$projects = @()
if ($ProjectPath) { $projects = @($ProjectPath) }
elseif ($cfg -and $cfg.projects) {
    foreach ($p in $cfg.projects) {
        $up = $p.uproject
        if (-not $up) { continue }
        # Not `+= (if ...)`: an if used as an expression is PowerShell 7 syntax, and on 5.1 the script
        # dies on the first line with "the term 'if' is not recognized". A run on a healthy tree never
        # reaches here, because that path passes -ProjectPath; a fixture of a broken tree found it.
        if ([IO.Path]::IsPathRooted($up)) { $projects += $up }
        else { $projects += (Join-Path $Root ($up -replace '/', '\')) }
    }
}
else {
    $projects = @(Get-ChildItem -LiteralPath $Root -Recurse -Filter '*.uproject' -Depth 2 -ErrorAction SilentlyContinue |
                  Where-Object { $_.FullName -notmatch '\\(Intermediate|Binaries|Saved)\\' } | ForEach-Object { $_.FullName })
}

if (-not $projects) {
    Add-Finding 'Project' 'any project found' 'FAIL' "No .uproject named in the config and none under $Root. Nothing else here can be checked." 'Pass -ProjectPath, or run this from the tree root.'
}

foreach ($p in $projects) {
    if (-not (Test-Path -LiteralPath $p)) {
        Add-Finding 'Project' (Split-Path -Leaf $p) 'FAIL' "The config names $p, which is not there. A run using it fails once it gets to this project, not now." 'Fix the path in .claude/agent-memory-stack.json.'
        continue
    }
    $full = (Resolve-Path -LiteralPath $p).Path
    Test-ProjectPlugin $full

    $outDir = $null
    if ($cfg -and $cfg.projects) {
        $match = $cfg.projects | Where-Object { $_.uproject -and ((Split-Path -Leaf $_.uproject) -ieq (Split-Path -Leaf $full)) } | Select-Object -First 1
        if ($match -and $match.artefacts) {
            $outDir = if ([IO.Path]::IsPathRooted($match.artefacts)) { $match.artefacts } else { Join-Path $Root ($match.artefacts -replace '/', '\') }
        }
    }
    Test-Artefacts $full $outDir
}

$compileDbDir = $Root
if ($cfg -and $cfg.compileDbDir) {
    $compileDbDir = if ([IO.Path]::IsPathRooted($cfg.compileDbDir)) { $cfg.compileDbDir } else { Join-Path $Root ($cfg.compileDbDir -replace '/', '\') }
}
elseif ($projects -and (Test-Path -LiteralPath $projects[0])) {
    $compileDbDir = Split-Path -Parent (Resolve-Path -LiteralPath $projects[0]).Path
}
Test-CompileDatabase $compileDbDir

if (-not $SkipSerena) { Test-SerenaPatches }

# --- report ---------------------------------------------------------------------------------------
$fails    = @($findings | Where-Object Verdict -eq 'FAIL')
$warns    = @($findings | Where-Object Verdict -eq 'WARN')
$unknowns = @($findings | Where-Object Verdict -eq 'UNKNOWN')

if ($Json) {
    [pscustomobject]@{
        root     = $Root
        checked  = (Get-Date).ToString('o')
        summary  = [ordered]@{
            ok      = @($findings | Where-Object Verdict -eq 'OK').Count
            warn    = $warns.Count
            fail    = $fails.Count
            unknown = $unknowns.Count
        }
        findings = $findings
    } | ConvertTo-Json -Depth 6
    exit ([int]($fails.Count -gt 0))
}

$colour = @{ OK = 'Green'; WARN = 'Yellow'; FAIL = 'Red'; UNKNOWN = 'Cyan' }
$area = ''
Write-Host ""
foreach ($f in $findings) {
    if ($f.Area -ne $area) { $area = $f.Area; Write-Host $area -ForegroundColor White }
    Write-Host ("  {0,-8} {1}" -f $f.Verdict, $f.Check) -ForegroundColor $colour[$f.Verdict]
    if ($f.Verdict -ne 'OK') {
        Write-Host ("           $($f.Detail)")
        if ($f.Remedy) { Write-Host ("           -> $($f.Remedy)") -ForegroundColor DarkGray }
    }
}

Write-Host ""
Write-Host ("{0} ok, {1} warning(s), {2} failure(s), {3} not checked." -f
    @($findings | Where-Object Verdict -eq 'OK').Count, $warns.Count, $fails.Count, $unknowns.Count)
if ($unknowns.Count -gt 0) {
    Write-Host "The not-checked ones are listed above with what would answer them. They are not passes." -ForegroundColor Cyan
}
Write-Host ""
exit ([int]($fails.Count -gt 0))
