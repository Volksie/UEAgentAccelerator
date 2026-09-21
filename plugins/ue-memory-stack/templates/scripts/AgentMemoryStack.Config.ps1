<#
.SYNOPSIS
    Loads and validates .claude/agent-memory-stack.json, and resolves it against this client root.

.DESCRIPTION
    Dot-source this. It defines Get-AgentMemoryStackConfig and nothing else, so it is safe to load
    from any script.

    It exists because the same handful of facts - which projects there are, where each one's
    artefacts live, which directory clangd reads its database from - were written out twice, in
    Setup-AgentMemoryStack.ps1 and in Update-AgentMemoryLayers.ps1, and the two have to agree.
    Nothing checked that they did. Setup writes the project list into Serena's project.yml and
    points clangd at the database directory; Update dumps the artefacts and writes that database.
    Add a fourth project to one and not the other and the result is not an error: the freshness
    check simply never looks at it, and its artefacts go quietly stale, which is the failure mode
    this whole stack is built to avoid.

    Every path in the file is relative to the client root. That is not tidiness either - the file is
    checked in and read on machines whose client root is somewhere else entirely, so an absolute
    path in it is wrong everywhere but the machine that wrote it.

    What is deliberately NOT in the file: where the tools are. They arrive as a Claude Code plugin,
    they address themselves through the plugin root, and a path to them stored in a checked-in file
    would be right on the machine that wrote it and wrong everywhere else.
#>

# Where this file is, captured at dot-source time rather than read inside the function.
#
# $PSScriptRoot is not reliable in a parameter default: on Windows PowerShell 5.1 there are scripts
# whose defaults are evaluated with it still empty, and `Split-Path -Parent ''` is a terminating error
# before the body runs. The installer in serena/ was unrunnable on 5.1 for exactly that.
$script:AgentMemoryStackLoaderDir = $PSScriptRoot
if (-not $script:AgentMemoryStackLoaderDir -and $MyInvocation.MyCommand.Path) {
    $script:AgentMemoryStackLoaderDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}


function Find-AgentMemoryStackRoot {
    <#
    .SYNOPSIS
        The tree root: the nearest directory at or above $From that holds .claude\agent-memory-stack.json.

    .DESCRIPTION
        Searched for rather than derived from this file's own depth. The first version assumed the
        loader sat exactly two levels under the root, in .claude\scripts, and kept it in a parameter
        default. Put the loader anywhere else - tools\, a nested folder, beside the config - and the
        root came out wrong by a level, which made the config look missing, and the error said so in
        the worst possible way: that the sync had not brought it down. The file was there all along.

        Returns $null if there is none, and lets the caller say what to do about it.
    #>
    param([string] $From)

    if (-not $From) { return $null }
    $dir = (Resolve-Path -LiteralPath $From -ErrorAction SilentlyContinue).Path
    while ($dir) {
        if (Test-Path -LiteralPath (Join-Path $dir '.claude\agent-memory-stack.json')) { return $dir }
        $parent = Split-Path -Parent $dir
        if ($parent -eq $dir) { return $null }   # at the volume root
        $dir = $parent
    }
    return $null
}


function Get-AgentMemoryStackConfig {
    <#
    .SYNOPSIS
        The parsed configuration, with every path resolved to an absolute one for this machine.

    .PARAMETER P4Root
        The client root. Found by searching upwards from this file for .claude\agent-memory-stack.json,
        so it does not matter where in the tree the loader is kept. Pass it to override.

    .PARAMETER ConfigPath
        The configuration file itself. Implies the root, which is its grandparent directory.
    #>
    [CmdletBinding()]
    param(
        [string] $P4Root,
        [string] $ConfigPath
    )

    # Whichever of the two you were given, work the other one out; given neither, search.
    if (-not $P4Root -and -not $ConfigPath) {
        $P4Root = Find-AgentMemoryStackRoot -From $script:AgentMemoryStackLoaderDir
        if (-not $P4Root) {
            throw ("No .claude\agent-memory-stack.json in or above '$script:AgentMemoryStackLoaderDir'. " +
                   "Pass -P4Root <your tree root> or -ConfigPath <the file>. Copy " +
                   "templates/agent-memory-stack.json.template to .claude/agent-memory-stack.json if " +
                   "your tree has not got one yet.")
        }
    }
    elseif ($ConfigPath -and -not $P4Root) {
        # <root>\.claude\agent-memory-stack.json, so the root is two levels up from the file.
        $ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
        $P4Root = Split-Path -Parent (Split-Path -Parent $ConfigPath)
    }

    $P4Root = (Resolve-Path $P4Root).Path
    if (-not $ConfigPath) { $ConfigPath = Join-Path $P4Root '.claude\agent-memory-stack.json' }
    if (-not (Test-Path $ConfigPath)) {
        throw ("No stack configuration at $ConfigPath, and the tree root was taken as $P4Root. If that root " +
               "is right, the file is checked in and a missing one means the sync did not bring it down. If it " +
               "is wrong, pass -ConfigPath or -P4Root.")
    }

    try { $raw = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json }
    catch { throw "$ConfigPath is not valid JSON: $($_.Exception.Message)" }

    foreach ($required in 'projects', 'compileDbDir', 'engineSource', 'serena') {
        if (-not $raw.PSObject.Properties.Name.Contains($required)) {
            throw "$ConfigPath has no '$required'."
        }
    }
    if (@($raw.projects).Count -eq 0) { throw "$ConfigPath lists no projects." }

    function Resolve-Rooted {
        param([string] $Relative)
        if ([IO.Path]::IsPathRooted($Relative)) { return $Relative }
        return [IO.Path]::GetFullPath((Join-Path $P4Root $Relative))
    }

    $projects = [ordered]@{}
    foreach ($p in $raw.projects) {
        foreach ($field in 'name', 'uproject', 'artefacts', 'source') {
            if (-not $p.PSObject.Properties.Name.Contains($field)) {
                throw "A project entry in $ConfigPath has no '$field'."
            }
        }

        # Validated here rather than left to fail inside a stage. A project whose .uproject does not
        # exist is a typo somebody made a month ago, and finding out forty minutes into a build is
        # the expensive way to learn it.
        $uproject = Resolve-Rooted $p.uproject
        if (-not (Test-Path -LiteralPath $uproject)) {
            throw "$ConfigPath names $($p.name) at '$($p.uproject)', and there is no such file under $P4Root."
        }

        $projects[$p.name] = [pscustomobject]@{
            Name     = $p.name
            UProject = $uproject
            # The folder holding the .uproject. This is what Serena wants in ls_workspace_folders,
            # and it is not always the project's name: a descriptor can sit in a folder called
            # something else entirely.
            Folder   = Split-Path -Leaf (Split-Path -Parent $uproject)
            OutDir   = Resolve-Rooted $p.artefacts
            Source   = @($p.source | ForEach-Object { Resolve-Rooted $_ })

            # Depot-side forms, derived rather than stored. Storing them as well would mean two
            # descriptions of the same location that can disagree, which is the thing being fixed.
            P4Source = @($p.source | ForEach-Object { "$($_.TrimEnd('/'))/..." })
            P4Out    = "$($p.artefacts.TrimEnd('/'))/..."
        }
    }

    [pscustomobject]@{
        Path          = $ConfigPath
        P4Root        = $P4Root
        StackVersion  = $(if ($raw.stackVersion) { [int] $raw.stackVersion } else { 0 })
        Serena        = $raw.serena
        CompileDbDir  = Resolve-Rooted $raw.compileDbDir
        CompileDbRel  = $raw.compileDbDir.TrimEnd('/')
        EngineSource  = Resolve-Rooted $raw.engineSource
        EngineFolder  = $(if ($raw.engineFolder) { $raw.engineFolder } else { 'Engine' })
        Projects      = $projects
        ProjectNames  = @($projects.Keys)
    }
}

