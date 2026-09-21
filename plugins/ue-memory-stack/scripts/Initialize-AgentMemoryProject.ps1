<#
.SYNOPSIS
    Writes the project-side half of the memory stack into an Unreal project, or reports what is missing.

.DESCRIPTION
    The plugin brings the tools. This writes the parts that have to live in your project: the C++
    plugin, the stack config, the routing table and the per-module rules.

    Everything here is decided by what is already on disk, and **nothing that you have edited is ever
    overwritten**. A second run on a finished project changes nothing and says so. That is not
    politeness: the routing table is an hour of somebody's writing about their own codebase, and a
    setup script that clobbers it on a re-run is worse than one that never existed.

    What it writes, each only when absent:

      <project>/Plugins/UEAgentAccelerator   the C++ plugin, copied from this plugin
      <root>/.claude/agent-memory-stack.json the tree's facts, filled in from what was found
      <root>/CLAUDE.md                       the routing table, from the template, for you to rewrite
      <root>/.claude/rules/*.md.template     per-module rules, as templates. The suffix stays until
                                             you fill one in and rename it, because .claude/rules/*.md
                                             is auto-loaded and a placeholder there reads as fact
      <root>/.claude/.uea-install.json       what was installed and from which plugin version,
                                             one entry per project because a tree can hold several

    That last file is generated and not for editing. It is how `-Check` can say "this project is on
    0.1.0 and the plugin is 0.2.0" instead of guessing from file dates.

    The one thing a re-run does change is a C++ plugin left behind by a plugin update. That is nobody's
    edit, it is the old source sitting in the project looking perfectly healthy: the editor builds it,
    the dump runs, and it writes the old format. So a version difference is copied over and the run
    says to rebuild. A copy that differs at the *same* version is somebody's edit, and that one is
    reported and left alone unless you pass -Force.

.PARAMETER ProjectPath
    The .uproject to set up.

.PARAMETER Root
    The tree root that owns .claude/ and CLAUDE.md. Defaults to the folder holding the .uproject,
    which is right for a single-project tree and wrong for a tree of several: pass the shared root
    there, so every project lands in one config.

.PARAMETER Check
    Report what would happen and write nothing. Exit code 0 when everything is in place, 1 when
    something is missing or has drifted from this plugin's copy, so it can gate a build step.

.PARAMETER Mode
    Copy writes the C++ plugin into <project>/Plugins. Reference leaves it in this plugin and adds an
    AdditionalPluginDirectories entry, which is what you want when several projects share one copy.
    The binaries are per project either way, so each one still needs its own build.

.PARAMETER PluginSource
    The folder holding UEAgentAccelerator.uplugin, if not this plugin's own copy. With -Mode Copy it
    only decides what gets copied. With -Mode Reference it is the path written into the descriptor, and
    then it matters: left to itself that is this plugin's folder inside the plugin manager's cache,
    which is not a path your colleagues have and not one that is guaranteed to survive a plugin update.
    A depot or share path is what you want there.

.PARAMETER Force
    Overwrite a project copy of the C++ plugin that has been edited. A version upgrade does not need
    it; only a same-version difference does.

.EXAMPLE
    .\Initialize-AgentMemoryProject.ps1 -ProjectPath D:\MyGame\MyGame.uproject
    .\Initialize-AgentMemoryProject.ps1 -ProjectPath D:\Tree\GameA\GameA.uproject -Root D:\Tree -Check
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $ProjectPath,
    [string] $Root,
    [switch] $Check,
    # Reference instead of copying the C++ plugin. Adds an AdditionalPluginDirectories entry rather
    # than a copy, which is right when several projects in one tree share a checkout of it.
    [ValidateSet('Copy', 'Reference')] [string] $Mode = 'Copy',
    # Where the C++ plugin is read from. Only interesting with -Mode Reference, where it becomes the
    # path written into the descriptor: point it somewhere your whole team has, not at this plugin.
    [string] $PluginSource,
    # Overwrite a project copy that has been edited. Version upgrades do not need it.
    [switch] $Force,
    [switch] $NoSourceControl
)

$ErrorActionPreference = 'Stop'

# Resolved in the body, not in a parameter default: on Windows PowerShell 5.1 $PSScriptRoot can be
# empty while defaults are evaluated, which is how the Serena installer became unrunnable on 5.1.
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$PluginRoot = Split-Path -Parent $here

function Say  { param([string] $M) Write-Host "  $M" }
function Add_ { param([string] $M) Write-Host "  +  $M" -ForegroundColor Green }
function Keep { param([string] $M) Write-Host "  =  $M" -ForegroundColor DarkGray }
function Want { param([string] $M) Write-Host "  ?  $M" -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $ProjectPath)) { throw "No .uproject at $ProjectPath" }
$ProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$projectDir  = Split-Path -Parent $ProjectPath
$projectName = [IO.Path]::GetFileNameWithoutExtension($ProjectPath)
if (-not $Root) { $Root = $projectDir }
$Root = (Resolve-Path -LiteralPath $Root).Path

Write-Host ""
Write-Host "Project : $projectName  ($ProjectPath)"
Write-Host "Root    : $Root"
Write-Host "Plugin  : $PluginRoot"
Write-Host ""

$missing = 0
$wrote   = 0
$drift   = 0

$pluginVersion = (Get-Content -LiteralPath (Join-Path $PluginRoot '.claude-plugin\plugin.json') -Raw | ConvertFrom-Json).version
$manifest = Join-Path $Root '.claude\.uea-install.json'
$manifestDoc = if (Test-Path -LiteralPath $manifest) { Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json } else { $null }

# One file at the root, keyed by project. It used to be a single flat object, which was wrong the
# moment a tree held more than one project: this script runs per project, so on a three-project tree
# each run overwrote the last and the file ended up describing whichever ran last. The other two then
# read somebody else's record, matched its version, and reported themselves already set up - so the
# check that exists to catch a stale plugin copy was answering about a different project entirely.
function Get-ProjectRecord {
    param($Doc, [string] $Name)
    if (-not $Doc) { return $null }
    if ($Doc.PSObject.Properties.Name -contains 'projects') {
        if ($Doc.projects -and ($Doc.projects.PSObject.Properties.Name -contains $Name)) { return $Doc.projects.$Name }
        return $null
    }
    # A flat record from before this change describes exactly one project, and names it. Read it for
    # that project only; anything else genuinely has no record and must say so.
    if ($Doc.project -eq $Name) { return $Doc }
    return $null
}
$record = Get-ProjectRecord $manifestDoc $projectName

# Content, not dates: a sync rewrites every timestamp, so "the project's copy is older" is not a
# question a file time can answer. Same argument as docs/06-keeping-it-fresh.md makes about artefacts.
function Get-TreeHash([string] $Path) {
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -notmatch '\\(Intermediate|Binaries|Saved)\\' } |
               Sort-Object FullName)
    if (-not $files) { return $null }
    $sha = [Security.Cryptography.SHA256]::Create()
    $acc = [Text.StringBuilder]::new()
    foreach ($f in $files) { [void]$acc.Append((Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash) }
    $bytes = [Text.Encoding]::UTF8.GetBytes($acc.ToString())
    return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').Substring(0, 32)
}

function Relative([string] $Path) {
    # Paths in the config are relative to the root, because the file is committed and read on
    # machines whose root is somewhere else entirely.
    $full = (Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue)
    $p = if ($full) { $full.Path } else { $Path }
    if ($p.ToLower().StartsWith($Root.ToLower())) { return $p.Substring($Root.Length).TrimStart('\', '/').Replace('\', '/') }
    return $p.Replace('\', '/')
}

# --- 1. the C++ plugin ---------------------------------------------------------------------------
$installed = Join-Path $projectDir 'Plugins\UEAgentAccelerator\UEAgentAccelerator.uplugin'
$upstream = if ($PluginSource) { $PluginSource } else { Join-Path $PluginRoot 'ue-plugin\UEAgentAccelerator' }
$sourceUPlugin = Join-Path $upstream 'UEAgentAccelerator.uplugin'
if (-not (Test-Path -LiteralPath $sourceUPlugin)) { throw "No UEAgentAccelerator.uplugin at $upstream." }

# -Mode Reference never writes a .uplugin under the project, so looking only there reported the
# plugin missing for ever: -Check exited 1 on a correctly set-up tree and a re-run kept reinstalling.
# The descriptor is where a referenced plugin is recorded, so that is what gets read.
$referencedFrom = $null
foreach ($dir in @((Get-Content -LiteralPath $ProjectPath -Raw | ConvertFrom-Json).AdditionalPluginDirectories)) {
    if (-not $dir) { continue }
    $candidate = if ([IO.Path]::IsPathRooted($dir)) { $dir } else { Join-Path $projectDir $dir }
    $probe = Join-Path $candidate 'UEAgentAccelerator\UEAgentAccelerator.uplugin'
    if (Test-Path -LiteralPath $probe) { $referencedFrom = (Resolve-Path -LiteralPath (Split-Path -Parent $probe)).Path; break }
}

$sourceHash = Get-TreeHash (Join-Path $upstream 'Source')
$projectPluginSource = Join-Path $projectDir 'Plugins\UEAgentAccelerator\Source'
$projectHash = if (Test-Path -LiteralPath $projectPluginSource) { Get-TreeHash $projectPluginSource } else { $null }
$versionMoved = $record -and $record.pluginVersion -and ($record.pluginVersion -ne $pluginVersion)
$contentMoved = $projectHash -and $sourceHash -and ($projectHash -ne $sourceHash)

# A referenced install writes a path into the descriptor rather than copying anything, so the path has
# to be one that keeps existing. This plugin's own folder is the plugin manager's to move.
if ($Mode -eq 'Reference' -and -not $PluginSource -and -not $referencedFrom) {
    Say "   -Mode Reference with no -PluginSource points the descriptor inside this plugin's own folder."
    Say "   That path is the plugin manager's, not yours: it is not on your colleagues' machines and an"
    Say "   update can move it, after which the editor has no plugin and says nothing. Pass -PluginSource"
    Say "   a depot or share path instead, unless this project is only ever built on this machine."
}

$installArgs = @{ ProjectPath = $ProjectPath; Mode = $Mode; NoSourceControl = $NoSourceControl }
if ($PluginSource) { $installArgs.PluginSource = $PluginSource }

if ($referencedFrom -and -not (Test-Path -LiteralPath $installed)) {
    # Referenced rather than copied, so there is no second copy to drift: the project reads this
    # plugin's own source and a plugin update reaches it without anything being rewritten. It still
    # needs its own build, because the binaries are per project whichever mode this is.
    Keep "C++ plugin referenced from $referencedFrom"
}
elseif (-not (Test-Path -LiteralPath $installed)) {
    if ($Check) { Want "C++ plugin is not in the project"; $missing++ }
    else {
        & (Join-Path $here 'Install-UEAgentAccelerator.ps1') @installArgs | Out-Null
        Add_ "C++ plugin installed ($Mode)"; $wrote++
    }
}
elseif ($versionMoved) {
    # A plugin update leaves every project on the old C++ source, and nothing about that looks wrong:
    # the editor builds, the dump runs, and it writes the old format. So this is not a report, it is
    # the one thing a re-run exists to fix.
    if ($Check) { Want "C++ plugin in the project came from plugin $($record.pluginVersion); this plugin is $pluginVersion"; $drift++ }
    else {
        & (Join-Path $here 'Install-UEAgentAccelerator.ps1') @installArgs -Force | Out-Null
        Add_ "C++ plugin updated, $($record.pluginVersion) -> $pluginVersion. REBUILD before the next dump"
        $wrote++
    }
}
elseif ($contentMoved) {
    # Same version, different bytes: somebody edited the copy in the project. That is theirs to decide
    # about, so it is never overwritten without -Force.
    if ($Check) { Want "the project's copy of the C++ plugin differs from this plugin's, at the same version"; $drift++ }
    elseif ($Force) {
        & (Join-Path $here 'Install-UEAgentAccelerator.ps1') @installArgs -Force | Out-Null
        Add_ "C++ plugin overwritten from this plugin's copy (-Force)"; $wrote++
    }
    else {
        Want "the project's copy of the C++ plugin differs from this plugin's, at the same version."
        Say  "   Somebody edited it here. Pass -Force to overwrite it, or keep it and know the two have parted."
        $drift++
    }
}
else {
    Keep "C++ plugin matches this plugin's copy ($pluginVersion)"
}

# --- 2. the stack config -------------------------------------------------------------------------
$configPath = Join-Path $Root '.claude\agent-memory-stack.json'
if (Test-Path -LiteralPath $configPath) {
    Keep ".claude/agent-memory-stack.json exists, left alone"
}
elseif ($Check) {
    Want ".claude/agent-memory-stack.json is missing"; $missing++
}
else {
    # Filled in from what is actually here. Anything that cannot be found from the project stays an
    # <ANGLE BRACKET> placeholder rather than a plausible guess, because a wrong path in this file is
    # worse than an obviously empty one: the scripts would run against the wrong tree and say nothing.
    $source = @()
    foreach ($d in 'Source', 'Plugins') {
        $p = Join-Path $projectDir $d
        if (Test-Path -LiteralPath $p) { $source += (Relative $p) }
    }
    $artefacts = Relative (Join-Path $projectDir 'Docs\AgentMemory')
    $cfg = [ordered]@{
        stackVersion = 1
        serena       = [ordered]@{
            projectName   = '<the name in .serena/project.yml>'
            taskName      = '<the scheduled task running the long lived server>'
            port          = 24290
            pinnedVersion = '1.7.0'
        }
        compileDbDir = '.clangd-db'
        engineSource = '<Engine/Source, if your engine is inside this tree>'
        engineFolder = 'Engine'
        projects     = @(
            [ordered]@{
                name      = $projectName
                uproject  = (Relative $ProjectPath)
                artefacts = $artefacts
                source    = $source
            }
        )
    }
    $dir = Split-Path -Parent $configPath
    if (-not (Test-Path -LiteralPath $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
    ($cfg | ConvertTo-Json -Depth 6) | Out-File -FilePath $configPath -Encoding utf8
    Add_ ".claude/agent-memory-stack.json written, with $($source.Count) source path(s) found"
    Say  "   fill in the <angle brackets>: they are the things this script cannot know"
    $wrote++
}

# --- 3. the routing table, never overwritten -----------------------------------------------------
$claudeMd = Join-Path $Root 'CLAUDE.md'
$template = Join-Path $PluginRoot 'templates\CLAUDE.md.template'
if (Test-Path -LiteralPath $claudeMd) {
    # Deliberately not compared against the template, and not merged. If it is there, it is somebody's
    # writing about their own tree and this script has no business touching it.
    Keep "CLAUDE.md exists, left alone (the routing table is yours)"
}
elseif ($Check) {
    Want "CLAUDE.md is missing"; $missing++
}
else {
    Copy-Item -LiteralPath $template -Destination $claudeMd
    Add_ "CLAUDE.md written from the template"
    Say  "   REWRITE IT for this tree. Budget an hour. It is the part that does most of the work,"
    Say  "   and a row naming a tool you do not have is worse than no row at all."
    $wrote++
}

# --- 4. per-module rules -------------------------------------------------------------------------
$rulesDir = Join-Path $Root '.claude\rules'
$ruleTemplates = @(Get-ChildItem -LiteralPath (Join-Path $PluginRoot 'templates\rules') -Filter '*.md.template' -ErrorAction SilentlyContinue)
foreach ($t in $ruleTemplates) {
    # The .template suffix is kept on arrival, and that is the whole point of this block.
    #
    # .claude/rules/*.md is loaded into every session as project instructions. Stripping the suffix
    # put a file full of <PLACEHOLDER> text in there, and a session then read "<Property> replicates
    # COND_OwnerOnly" as fact, with exactly the authority of the hand-written file next to it. On a
    # tree where the real answer was "nothing in this module replicates", an agent got a true
    # statement and an invented one and no way to tell them apart. That is this stack's own failure
    # mode - something that looks like knowledge and is not - arriving through the tool built to
    # prevent it.
    #
    # So it lands as Module.md.template, which nothing auto-loads, and filling it in means renaming
    # it. An unfilled template then costs nothing instead of costing the truth.
    $filled   = Join-Path $rulesDir ($t.Name -replace '\.template$', '')
    $dest     = Join-Path $rulesDir $t.Name
    $leafFill = Split-Path -Leaf $filled
    $leafDest = Split-Path -Leaf $dest

    # Either one counts as present. Somebody who filled it in and deleted the template has finished
    # with it, and writing the template back is how a deliberate deletion gets undone on every run.
    if (Test-Path -LiteralPath $filled) { Keep ".claude/rules/$leafFill exists, left alone"; continue }
    if (Test-Path -LiteralPath $dest)   { Keep ".claude/rules/$leafDest exists, left alone"; continue }

    if ($Check) { Want ".claude/rules/$leafDest is missing"; $missing++; continue }
    if (-not (Test-Path -LiteralPath $rulesDir)) { $null = New-Item -ItemType Directory -Path $rulesDir -Force }
    Copy-Item -LiteralPath $t.FullName -Destination $dest
    Add_ ".claude/rules/$leafDest written; rename it to $leafFill once filled in, and it is loaded from then on"
    $wrote++
}

# --- 5. the record, so a later check can compare versions rather than dates ----------------------
if ($Check) {
    if (-not $record) { Want "no install record; this project has not been set up by this script"; $missing++ }
    else { Keep "installed from plugin $($record.pluginVersion)" }
}
else {
    # Merge, never replace: the other projects in this tree have entries here and this run knows
    # nothing about them.
    $projects = [ordered]@{}
    if ($manifestDoc) {
        if ($manifestDoc.PSObject.Properties.Name -contains 'projects') {
            foreach ($p in $manifestDoc.projects.PSObject.Properties) { $projects[$p.Name] = $p.Value }
        }
        elseif ($manifestDoc.project) {
            # Carry a flat record forward under the project it named, rather than dropping it and
            # silently losing the one warning that project would get on the next plugin update.
            $projects[[string]$manifestDoc.project] = $manifestDoc
        }
    }
    $projects[$projectName] = [ordered]@{
        pluginVersion = $pluginVersion
        installedAt   = (Get-Date).ToString('o')
        mode          = if ($referencedFrom) { 'Reference' } else { $Mode }
        uproject      = (Relative $ProjectPath)
        ueSourceHash  = $sourceHash
    }

    ([ordered]@{
        version   = 2
        generated = 'Written by Initialize-AgentMemoryProject.ps1, one entry per project. Do not edit; it is how a later check compares versions.'
        projects  = $projects
    } | ConvertTo-Json -Depth 6) | Out-File -FilePath $manifest -Encoding utf8
    Keep "install record updated for $projectName ($pluginVersion)"
}

Write-Host ""
if ($Check) {
    if ($missing -gt 0) { Write-Host "$missing thing(s) missing. Run without -Check to write them." -ForegroundColor Yellow }
    if ($drift -gt 0) {
        Write-Host "$drift thing(s) have drifted from this plugin's copy." -ForegroundColor Yellow
        Write-Host "  A version difference is fixed by re-running without -Check; an edited copy needs -Force." -ForegroundColor Yellow
    }
    if ($missing -gt 0 -or $drift -gt 0) { exit 1 }
    Write-Host "Everything is in place." -ForegroundColor Green
    exit 0
}

if ($wrote -eq 0) { Write-Host "Nothing to do: this project was already set up." -ForegroundColor Green }
else { Write-Host "$wrote thing(s) written." -ForegroundColor Green }

Write-Host ""
Write-Host "Next: build and generate the layers." -ForegroundColor Cyan
Write-Host "  Update-MemoryStack.ps1 -StackConfig `"$configPath`""
