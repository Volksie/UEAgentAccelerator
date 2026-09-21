<#
.SYNOPSIS
    Rebuilds the generated layers in dependency order, and checks they were actually written.

.DESCRIPTION
    Build -> CompileDb -> Reflection -> Verify. One command instead of remembering the order and the
    traps, and it fails loudly on the ones that otherwise pass quietly.

    The point is not convenience. Every stage asserts a postcondition on the *artefacts* rather than
    trusting an exit code, because almost every silent failure this stack has hit looked like
    success: a tool that exits 0 having written nothing, a dump against a stale DLL that writes the
    old format, a commandlet that carries on past failed writes and reports its usual summary. A
    stage whose tool exits 0 without leaving anything newer than the moment it started is a failure
    here.

    Artefact directories are moved aside and restored if the stage fails, never wiped in place. An
    interrupted run that has already deleted the old output leaves an index claiming there are no
    Blueprint callers anywhere, which is indistinguishable from the truth.

    Pass more than one -ProjectPath and Build, Reflection and Verify run per project, in turn. That
    is not a convenience: the plugin's binaries are built per project, so building one and dumping
    three writes stale output for two of them and reports success. Building each project immediately
    before dumping it also keeps the editor module manifests in step, which matters when several
    projects share one source engine.

    CompileDb is the exception and runs once, for all of them together, after the builds. One
    invocation describing several targets resolves the shared engine files once and consistently;
    a database per project leaves several entries for the same engine file, agreeing only for as
    long as the targets happen to agree. See 03-running-the-dump.md.

.PARAMETER Preset
    All        every stage
    Artefacts  regenerate the dump without rebuilding first
    Layer1     the compile database only

.EXAMPLE
    .\Update-MemoryStack.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8 -CompileDbDir D:\MyGame
    .\Update-MemoryStack.ps1 -ProjectPath D:\A\A.uproject,D:\B\B.uproject -EnginePath C:\UE_5.8 -DryRun

    A tree whose projects sit in subfolders, with the docs a level above them, wants both
    directory arguments spelled out:

    .\Update-MemoryStack.ps1 -EnginePath D:\Tree `
      -ProjectPath D:\Tree\GameA\GameA.uproject,D:\Tree\GameB\GameB.uproject `
      -OutDir 'D:\Tree\Docs\AgentMemory','Docs\AgentMemory' `
      -CompileDbDir D:\Tree\.clangd-db -IncludeEngine

    Or keep those four facts in one file and pass that instead. Everything above comes from it, and
    the setup half of your stack reads the same file, so the two cannot disagree about which projects
    exist:

    .\Update-MemoryStack.ps1 -StackConfig D:\Tree\.claude\agent-memory-stack.json
#>
[CmdletBinding()]
param(
    # One or more .uproject files. Each is built and dumped in turn.
    # Not mandatory only because -StackConfig can supply it; one of the two is required.
    [string[]] $ProjectPath,

    [string] $EnginePath,

    # A tree's facts in one file: templates/agent-memory-stack.json.template, usually copied to
    # .claude/agent-memory-stack.json. Fills -ProjectPath, -OutDir, -CompileDbDir and -EnginePath from
    # it, and anything passed explicitly still wins.
    #
    # The point is not brevity. The other half of a working stack - whatever script registers Serena's
    # workspace folders and points clangd at the compile database - needs the same project list and the
    # same database directory. Written out twice, adding a project to one and not the other fails in
    # the worst way available: the artefacts are regenerated for ever and no symbol query can see them.
    [string] $StackConfig,

    [ValidateSet('All', 'Artefacts', 'Layer1')]
    [string] $Preset = 'All',

    # Override the preset with an explicit list.
    [ValidateSet('Build', 'CompileDb', 'Reflection', 'Verify')]
    [string[]] $Stages,

    # Print every command that would run, and skip the postcondition checks.
    [switch] $DryRun,

    # Passed through to the dump. Worth setting on a project with a lot of middleware.
    [string[]] $Modules,

    # Passed through to the build and the compile database when a project has more than one editor
    # target. Only makes sense with a single -ProjectPath.
    [string] $Target,

    # Where each project's artefacts live, matched to -ProjectPath by position. Relative paths are
    # relative to the folder holding that .uproject.
    #
    # Needed because <project>\Docs\AgentMemory is only right when the .uproject sits at the root of
    # its own tree. Where it doesn't, this ran the dump into a Docs folder beside the real one and
    # then checked that same wrong folder for freshness, so every stage passed and the artefacts the
    # routing table points at were never touched.
    [string[]] $OutDir,

    # Where the compile database goes. Required by the CompileDb stage and deliberately not
    # defaulted: it is one database describing every -ProjectPath, so there is no project folder it
    # sensibly belongs in, and it has to match the directory your clangd --compile-commands-dir
    # names or Layer 1 keeps answering from a stale one.
    [string] $CompileDbDir,

    [switch] $NoSourceControl,

    # Include engine source in the compile database.
    [switch] $IncludeEngine
)

$ErrorActionPreference = 'Stop'

if ($StackConfig) {
    $loader = Join-Path $PSScriptRoot '..\templates\scripts\AgentMemoryStack.Config.ps1'
    if (-not (Test-Path $loader)) { throw "Cannot find the config loader at $loader." }
    . $loader
    # Only the file goes in. The loader works the tree root out from it, and this script working
    # it out as well would be a second copy of the same assumption, which is the thing the config
    # file exists to remove.
    $cfg = Get-AgentMemoryStackConfig -ConfigPath (Resolve-Path $StackConfig).Path

    if (-not $ProjectPath) { $ProjectPath = @($cfg.ProjectNames | ForEach-Object { $cfg.Projects[$_].UProject }) }
    if (-not $OutDir)      { $OutDir      = @($cfg.ProjectNames | ForEach-Object { $cfg.Projects[$_].OutDir }) }
    if (-not $CompileDbDir) { $CompileDbDir = $cfg.CompileDbDir }
    # EngineSource is <root>\Engine\Source; UnrealBuildTool wants the directory holding Engine\.
    if (-not $EnginePath)  { $EnginePath  = Split-Path -Parent (Split-Path -Parent $cfg.EngineSource) }
    Write-Host ("Stack config: {0}" -f $cfg.Path) -ForegroundColor Cyan
    Write-Host ("  projects: {0}" -f ($cfg.ProjectNames -join ', '))
}

if (-not $ProjectPath) { throw "Pass -ProjectPath, or -StackConfig to read it from your tree's config." }
if (-not $EnginePath)  { throw "Pass -EnginePath, or -StackConfig to read it from your tree's config." }

if (-not $Stages) {
    $Stages = switch ($Preset) {
        'All'       { @('Build', 'CompileDb', 'Reflection', 'Verify') }
        'Artefacts' { @('Reflection', 'Verify') }
        'Layer1'    { @('CompileDb') }
    }
}

$RunId   = Get-Date -Format 'yyyyMMdd-HHmmss'
$Results = @()
$Aborted = $false

function Write-Head { param([string] $Text) Write-Host ""; Write-Host "=== $Text ===" -ForegroundColor Cyan }
function Write-Step { param([string] $Text) Write-Host "  -> $Text" -ForegroundColor Gray }
function Write-Ok   { param([string] $Text) Write-Host "  OK   $Text" -ForegroundColor Green }
function Write-Bad  { param([string] $Text) Write-Host "  FAIL $Text" -ForegroundColor Red }

function Get-Stamp {
    param([string] $Path)
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue)
    $newest = $null; $bytes = 0
    if ($files.Count -gt 0) {
        $newest = ($files | Measure-Object -Property LastWriteTime -Maximum).Maximum
        $bytes  = ($files | Measure-Object -Property Length -Sum).Sum
    }
    [pscustomobject]@{ Count = $files.Count; Newest = $newest; Bytes = $bytes }
}

function Assert-Fresh {
    # The check that matters. An exit code says the tool ran; this says it wrote something.
    param(
        [Parameter(Mandatory)] [string]   $Path,
        [Parameter(Mandatory)] [datetime] $Since,
        [Parameter(Mandatory)] [string]   $What,
        [int] $MinFiles = 1
    )
    if ($DryRun) { return }
    $s = Get-Stamp -Path $Path
    if ($s.Count -lt $MinFiles) {
        throw "$What produced $($s.Count) files at $Path, expected at least $MinFiles"
    }
    if ($null -eq $s.Newest -or $s.Newest -lt $Since) {
        throw "$What left $Path untouched (newest file $($s.Newest)). The tool exited 0 and wrote nothing new."
    }
    Write-Ok ("{0}: {1:n0} files, {2:n1} MB" -f $What, $s.Count, ($s.Bytes / 1MB))
}

function Push-Artefacts {
    # Moved aside, not deleted. A run that dies half way through otherwise leaves an index that says
    # nothing has any Blueprint callers, which reads exactly like the truth.
    param([string] $Path)
    if ($DryRun -or -not (Test-Path -LiteralPath $Path)) { return $null }
    $bak = "$Path.prev-$RunId"
    Move-Item -LiteralPath $Path -Destination $bak
    return $bak
}

function Pop-Artefacts {
    param([string] $Backup, [string] $Path, [bool] $Success)
    if (-not $Backup) { return }
    if ($Success) {
        Remove-Item -LiteralPath $Backup -Recurse -Force -ErrorAction SilentlyContinue
    }
    else {
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue }
        Move-Item -LiteralPath $Backup -Destination $Path -ErrorAction SilentlyContinue
        Write-Host "     restored the previous artefacts from $Backup" -ForegroundColor Yellow
    }
}

function Invoke-Stage {
    # A failed stage skips the rest rather than killing the script, so the summary still prints. A
    # run that stops with no summary means rerunning everything to find out what broke.
    param([string] $Name, [string] $Project, [scriptblock] $Body)
    if ($Stages -notcontains $Name) { return }
    if ($Script:Aborted) {
        $Script:Results += [pscustomobject]@{ Project = $Project; Stage = $Name; Status = 'skipped'; Seconds = 0; Detail = 'earlier stage failed' }
        return
    }
    Write-Head "$Project - $Name"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $status = 'ok'; $detail = ''
    try { & $Body }
    catch {
        $status = 'FAILED'; $detail = $_.Exception.Message
        Write-Bad $detail
        $Script:Aborted = $true
    }
    $sw.Stop()
    $Script:Results += [pscustomobject]@{
        Project = $Project; Stage = $Name; Status = $status
        Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1); Detail = $detail
    }
}

# A running editor holds the plugin DLLs open, so a build fails on a locked file with a message about
# permissions rather than about the editor. Cheaper to say so up front.
#
# Only for the stages that touch binaries or run a second editor, though. Verify reads files that are
# already on disk, and refusing to run it because an editor is open is a check getting in the way of
# the one thing you might want while a long build is going.
$needsExclusive = @('Build', 'CompileDb', 'Reflection') | Where-Object { $Stages -contains $_ }
if ($needsExclusive -and -not $DryRun) {
    $editors = @(Get-Process -Name 'UnrealEditor', 'UnrealEditor-Cmd' -ErrorAction SilentlyContinue)
    if ($editors.Count -gt 0) {
        throw "Close the editor first: $($editors.Count) UnrealEditor process(es) running. They hold the plugin DLLs open, and UBT refuses a second instance."
    }
}

$scriptDir = $PSScriptRoot

for ($projIndex = 0; $projIndex -lt $ProjectPath.Count; $projIndex++) {
    $proj     = (Resolve-Path $ProjectPath[$projIndex]).Path
    $projName = [IO.Path]::GetFileNameWithoutExtension($proj)
    $projDir  = Split-Path -Parent $proj

    # Matched to -ProjectPath by position, the same way -Target is in New-CompileDatabase.ps1.
    $outForProject = if ($OutDir -and $OutDir.Count -gt $projIndex) { $OutDir[$projIndex] } else { $null }
    $artefactDir = if ($outForProject) {
        [IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($outForProject)) { $outForProject } else { Join-Path $projDir $outForProject }))
    } else {
        Join-Path $projDir 'Docs\AgentMemory'
    }

    Invoke-Stage 'Build' $projName {
        $a = @{ ProjectPath = $proj; EnginePath = $EnginePath }
        if ($Target) { $a.Target = $Target }
        Write-Step "Build-UEAgentAccelerator.ps1"
        if (-not $DryRun) { & (Join-Path $scriptDir 'Build-UEAgentAccelerator.ps1') @a }
    }

    Invoke-Stage 'Reflection' $projName {
        # The DLL gate before the dump, not after. A dump against a stale DLL succeeds, logs its
        # usual summary and writes the old format, and nothing downstream can tell.
        Write-Step "checking the plugin DLL is current"
        if (-not $DryRun) {
            $a = @{ ProjectPath = $proj; EnginePath = $EnginePath; CheckOnly = $true }
            if ($Target) { $a.Target = $Target }
            & (Join-Path $scriptDir 'Build-UEAgentAccelerator.ps1') @a
        }

        $since  = Get-Date
        $backup = Push-Artefacts $artefactDir
        $ok     = $false
        try {
            $a = @{ ProjectPath = $proj; EnginePath = $EnginePath; NoSourceControl = $NoSourceControl }
            if ($Modules)       { $a.Modules = $Modules }
            if ($outForProject) { $a.OutDir = $artefactDir }
            Write-Step "Invoke-AgentMemoryDump.ps1"
            if (-not $DryRun) { & (Join-Path $scriptDir 'Invoke-AgentMemoryDump.ps1') @a }
            Assert-Fresh -Path $artefactDir -Since $since -What 'reflection dump' -MinFiles 2
            $ok = $true
        }
        finally { Pop-Artefacts -Backup $backup -Path $artefactDir -Success $ok }
    }

    Invoke-Stage 'Verify' $projName {
        if ($DryRun) { Write-Step "would check the artefacts are readable and internally consistent"; return }

        $index = Join-Path $artefactDir 'index.md'
        if (-not (Test-Path $index)) { throw "No index.md at $index" }

        # One row per class in the index, one file per class on disk. A mismatch means a partial
        # write, which is the failure the move-aside protects against but cannot detect.
        $rows = @(Select-String -Path $index -Pattern '^\| `' -ErrorAction SilentlyContinue)
        $classDir = Join-Path $artefactDir 'classes'
        $files = @(Get-ChildItem -LiteralPath $classDir -Filter *.md -File -ErrorAction SilentlyContinue)
        if ($rows.Count -eq 0) { throw "index.md has no class rows" }
        if ($files.Count -ne $rows.Count) {
            throw "index.md lists $($rows.Count) classes but classes\ holds $($files.Count) files"
        }
        Write-Ok "index and class files agree: $($rows.Count) classes"

        $bpc = Join-Path $artefactDir 'BlueprintCallers.md'
        if (Test-Path $bpc) {
            $size = (Get-Item $bpc).Length
            Write-Ok ("BlueprintCallers.md present, {0:n0} bytes" -f $size)
        }
    }
}

# Once for every project, not once per project, and after the builds so the generated headers all
# exist. This used to run inside the loop above with no -OutputDir, which meant each project wrote
# its own compile_commands.json into its own folder. Three databases, none of them the one clangd is
# pointed at, and each describing shared engine files on its own terms - the exact hand merge that
# 03-running-the-dump.md explains is only ever right by coincidence. Nothing failed; Layer 1 just
# went on answering from whichever database it had been given, quietly out of date.
Invoke-Stage 'CompileDb' '(all projects)' {
    if (-not $CompileDbDir) {
        throw "-CompileDbDir is required for the CompileDb stage: it is one database covering every -ProjectPath, so it cannot default to a project folder. Point it at the directory your clangd --compile-commands-dir names."
    }
    $a = @{ ProjectPath = $ProjectPath; EnginePath = $EnginePath; OutputDir = $CompileDbDir; NoSourceControl = $NoSourceControl }
    if ($Target)        { $a.Target = $Target }
    if ($IncludeEngine) { $a.IncludeEngine = $true }
    Write-Step "New-CompileDatabase.ps1 -> $CompileDbDir"
    $since = Get-Date
    if (-not $DryRun) {
        & (Join-Path $scriptDir 'New-CompileDatabase.ps1') @a
        # Asserted on the file, not the folder. clangd writes its index shards into
        # <db dir>\.cache\clangd\index, thousands of them, so a folder level freshness check
        # passes on index churn alone and would go green on a database that was never rewritten.
        $db = Join-Path $CompileDbDir 'compile_commands.json'
        if (-not (Test-Path $db)) { throw "UBT reported success but $db does not exist." }
        $written = (Get-Item $db).LastWriteTime
        if ($written -lt $since) { throw "compile database at $db was not rewritten (last write $written). The tool exited 0 and changed nothing." }
        Write-Ok ("compile_commands.json, {0:n0} entries, {1:n1} MB" -f (Get-Content $db -Raw | ConvertFrom-Json).Count, ((Get-Item $db).Length / 1MB))
    }
}

Write-Head 'Summary'
$Results | Format-Table Project, Stage, Status, Seconds, Detail -AutoSize -Wrap

if ($Results | Where-Object { $_.Status -eq 'FAILED' }) {
    Write-Host "One or more stages failed. The previous artefacts have been restored." -ForegroundColor Red
    exit 1
}
Write-Host "All stages green." -ForegroundColor Green
