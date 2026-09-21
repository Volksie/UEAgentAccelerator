<#
.SYNOPSIS
    Shared helpers. Dot source this, don't run it.

.DESCRIPTION
    Everything in here exists because the scripts write into somebody else's working tree, and a
    working tree is very often under source control that makes files read only until you say you
    are going to change them.

        . (Join-Path $PSScriptRoot 'Common.ps1')

    Perforce is the case that has actually bitten, so that is what is implemented. Git and
    Subversion leave files writable, so they need nothing. If your source control is something else
    that locks files, pass -NoSourceControl and check the files out yourself first.

    Find-EditorTarget is here too, because both the build and the compile database need it and
    getting it wrong is a five minute wait for a wrong answer.
#>

function Get-ModuleManifestBuildId {
    # BuildId out of an UnrealEditor.modules, or $null if there isn't one to read.
    param([Parameter(Mandatory)] [string] $Path)

    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json).BuildId }
    catch { return $null }
}

function Test-EditorBuildIdMismatch {
    <#
    .SYNOPSIS
        Says whether this project's editor modules still match the engine, or $null if they do.

    .DESCRIPTION
        Two projects sharing one source engine cannot both have a current editor build, and this is
        the check that turns that into a sentence instead of a mystery.

        Each project keeps its own <Project>\Binaries\Win64\UnrealEditor.modules, so they don't
        overwrite each other, and it's tempting to conclude they're independent. They're not. The
        manifests are matched to the engine's own
        <Engine>\Engine\Binaries\Win64\UnrealEditor.modules by BuildId, and building any editor
        target regenerates that one. So building project B gives the engine a new BuildId, project
        A's manifest keeps the old one, and A's modules stop resolving.

        What that looks like is nothing like what it is. The editor puts up "The game module 'X'
        could not be found. Please ensure that this module exists and that it is compiled", where X
        is one of your own modules, sitting there compiled, next to a manifest that lists it. Under
        -unattended the dialog is answered for you and the process is gone in about a second.

        Rebuild the project you're about to use. Order matters more than anything else here: build
        and dump one project, then build and dump the next. Building both and then dumping both
        leaves the first one broken.

    .OUTPUTS
        A description of the mismatch, or $null when they match or when it can't be determined.
    #>
    param(
        [Parameter(Mandatory)] [string] $EnginePath,
        [Parameter(Mandatory)] [string] $ProjectDir
    )

    $engineId  = Get-ModuleManifestBuildId (Join-Path $EnginePath 'Engine\Binaries\Win64\UnrealEditor.modules')
    $projectId = Get-ModuleManifestBuildId (Join-Path $ProjectDir 'Binaries\Win64\UnrealEditor.modules')

    # A project with no manifest hasn't been built as an editor target at all, which is a different
    # problem with its own message, and an engine with none isn't a source build. Neither is ours.
    if (-not $engineId -or -not $projectId) { return $null }
    if ($engineId -eq $projectId)           { return $null }

    return "engine BuildId is $engineId, this project's is $projectId"
}

function Find-EditorTarget {
    <#
    .SYNOPSIS
        The name of a project's editor target, read from its Target.cs files.

    .DESCRIPTION
        <ProjectName>Editor is a convention, not a rule, and plenty of real projects don't follow
        it: a descriptor named one thing can perfectly well build a target named another,
        because the target name comes from the Target.cs file and nothing makes it match the
        descriptor. Assuming the convention there sends UnrealBuildTool after a target that doesn't
        exist, and it doesn't fail quickly or say anything about the real one.

        So the file that assigns TargetType.Editor is what we go by. If there is more than one,
        say so and let the caller choose rather than picking the first and being wrong quietly.

        Note the pattern matches the assignment specifically, not the words appearing anywhere in
        the file. Matching any mention looks equivalent and is not: a game target routinely branches
        on "Target.Type == TargetType.Editor" to decide what to include, and Lyra's does it six
        times. On that project a mention-based match reported LyraEditor and LyraGame as two editor
        targets and stopped, asking for a -Target that was never ambiguous.
    #>
    param([Parameter(Mandatory)] [string] $ProjectDir)

    $sourceDir = Join-Path $ProjectDir 'Source'
    if (-not (Test-Path $sourceDir)) { return $null }

    $targets = @()
    foreach ($file in Get-ChildItem $sourceDir -Filter '*.Target.cs' -File -ErrorAction SilentlyContinue) {
        # The (?!=) keeps a single = from matching the first half of ==.
        if ((Get-Content $file.FullName -Raw) -match '\bType\s*=(?!=)\s*TargetType\.Editor\b') {
            $targets += ($file.Name -replace '\.Target\.cs$', '')
        }
    }

    if ($targets.Count -eq 1) { return $targets[0] }
    if ($targets.Count -gt 1) {
        throw "$ProjectDir has more than one editor target ($($targets -join ', ')). Pass -Target to say which."
    }
    return $null
}

# Keyed by directory, because which server and client you get depends on where you ask from.
$script:P4Probe = @{}

function Get-P4Directory {
    <#
        The directory to run p4 from, which is the one holding the file we are about to change.

        This matters more than it looks. Most people's Perforce settings come from a P4CONFIG file
        somewhere up the tree from their workspace, and p4 searches upwards from its current
        directory to find it. These scripts run from wherever the accelerator was cloned to, which
        is usually nowhere near the project, so a p4 invoked without this finds no config, falls
        back to the machine wide defaults, and reports the workspace as unknown. Everything then
        looks like "this project is not under Perforce", which is the wrong answer arrived at
        confidently.
    #>
    param([Parameter(Mandatory)] [string] $Path)

    if (Test-Path -LiteralPath $Path -PathType Container) { return (Resolve-Path $Path).Path }
    $parent = Split-Path -Parent $Path
    if ($parent -and (Test-Path -LiteralPath $parent)) { return (Resolve-Path $parent).Path }
    return (Get-Location).Path
}

function Test-P4Available {
    <#
        True if a p4 client exists on PATH and can reach a server from the given directory with a
        workspace that exists. Anything else, including a server that is down, is false: work should
        not stall because Perforce is having a bad day.
    #>
    param([Parameter(Mandatory)] [string] $Directory)

    if ($script:P4Probe.ContainsKey($Directory)) { return $script:P4Probe[$Directory] }

    $script:P4Probe[$Directory] = $false
    if (-not (Get-Command p4 -ErrorAction SilentlyContinue)) {
        Write-Verbose "p4 is not on PATH."
        return $false
    }
    $out = Invoke-P4 $Directory info
    if (-not (Test-P4Succeeded)) {
        Write-Verbose "p4 info failed in $Directory."
        return $false
    }
    # p4 info succeeds and prints "Client unknown" when the workspace name doesn't resolve, so a
    # clean exit on its own says nothing about whether anything else will work.
    if ($out -match 'Client unknown') {
        Write-Verbose "p4 has no workspace for $Directory."
        return $false
    }
    $script:P4Probe[$Directory] = $true
    return $true
}

# Set by Invoke-P4. Read the exit status through Test-P4Succeeded rather than directly.
$script:P4LastExit    = 0
$script:P4LastError   = @()
$script:P4LastWarning = @()

function Invoke-P4 {
    <#
        Runs p4 from the right directory and returns its output as plain strings.

        The -s is doing real work. Without it p4 writes its errors to stderr, and on PowerShell 5.1
        there is no way to get a native command's stderr out of the way that is safe here: 2>&1
        wraps each line in an ErrorRecord, and 2>$null still raises one, so with the caller's
        $ErrorActionPreference = 'Stop' an ordinary "file not opened on this client" kills the
        script. That is a status answer, not a failure, and it happens on nearly every run.

        With -s everything comes back on stdout tagged info:, warning:, error: or exit:, and there
        is nothing on stderr to trip over.

        Only info and text lines are returned. Keeping warnings out of the result is the point of
        the split rather than tidiness: "file(s) not opened on this client" is a warning, arrives
        with exit 0, and is the answer no. Fold it in with the real output and a caller testing
        whether the result is empty concludes the file is already checked out.

        Do not pass -- to end the options. p4 has no such convention and rejects it with a usage
        error, which is easy to miss because PowerShell's binder eats a bare -- before p4 ever sees
        it, so it works from a script and fails when the same line is typed at a prompt.
    #>
    param(
        [Parameter(Mandatory)] [string] $Directory,
        [Parameter(Mandatory, ValueFromRemainingArguments)] [string[]] $Arguments
    )

    $script:P4LastExit    = 0
    $script:P4LastError   = @()
    $script:P4LastWarning = @()
    $out = @()

    foreach ($line in (& p4 -s -d $Directory @Arguments)) {
        if ($line -match '^exit:\s*(\d+)')    { $script:P4LastExit = [int]$Matches[1]; continue }
        if ($line -match '^error:\s?(.*)$')   { $script:P4LastError += $Matches[1]; continue }
        if ($line -match '^warning:\s?(.*)$') { $script:P4LastWarning += $Matches[1]; continue }
        $out += ($line -replace '^(info\d*|text):\s?', '')
    }
    return $out
}

function Test-P4Succeeded {
    # True if the last Invoke-P4 exited clean and logged no error line. Warnings are answers, not
    # failures, so they don't count here.
    return ($script:P4LastExit -eq 0 -and $script:P4LastError.Count -eq 0)
}

function Test-P4Controlled {
    <#
        True if the path is a file Perforce knows about in this client. A file that exists on disk
        but not in the depot is not controlled, and neither is one outside the client view.
    #>
    param([Parameter(Mandatory)] [string] $Path)

    $dir = Get-P4Directory $Path
    if (-not (Test-P4Available $dir)) { return $false }
    $out = Invoke-P4 $dir fstat -T depotFile $Path
    return ((Test-P4Succeeded) -and ($out -match 'depotFile'))
}

function Unlock-FileForWrite {
    <#
    .SYNOPSIS
        Makes one existing file safe to overwrite, checking it out of Perforce if it is controlled.

    .DESCRIPTION
        Two failures this prevents, and they look nothing like each other:

        A read only file. Perforce marks controlled files read only until they are open for edit, so
        the write throws UnauthorizedAccessException and the script dies part way through, after the
        plugin has been copied but before the descriptor knows about it. That is the loud one.

        A file of type +w. The +w modifier keeps the file writable whether or not it is open, so the
        write succeeds, the file never joins a changelist, and nobody finds out until the change
        turns out not to be in the submit. That is the quiet one, and it is why this checks out on
        the strength of the file being controlled rather than on the strength of it being read only.
        Testing IsReadOnly first would skip exactly the case that needs the checkout most.

        If Perforce is unavailable or refuses, we clear the read only flag and carry on, because a
        server outage should not stop somebody installing a plugin. The caller is warned so they can
        put the file in a changelist themselves.

    .OUTPUTS
        A short string saying what was done, suitable for printing.
    #>
    param(
        [Parameter(Mandatory)] [string] $Path,

        # Skip Perforce entirely and just clear the read only flag.
        [switch] $NoSourceControl
    )

    if (-not (Test-Path -LiteralPath $Path)) { return "not present, nothing to unlock" }

    $did = @()

    if (-not $NoSourceControl -and (Test-P4Controlled $Path)) {
        $dir = Get-P4Directory $Path
        if (Invoke-P4 $dir opened $Path) {
            $did += "already open in Perforce"
        }
        else {
            $null = Invoke-P4 $dir edit $Path
            if (Test-P4Succeeded) {
                $did += "checked out of Perforce"
            }
            else {
                Write-Warning "p4 edit failed for $Path : $($script:P4LastError -join '; ')"
                Write-Warning "Falling back to the read only flag. Put the file in a changelist yourself."
            }
        }
    }

    # Always, even after a checkout that reported success. Being open in Perforce is not the same as
    # being writable on disk: a file opened in a workspace that was later reverted or re-synced by
    # something else comes back read only while p4 still lists it as open, and then the write throws
    # after we have said everything is fine.
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.IsReadOnly) {
        $item.IsReadOnly = $false
        $did += "cleared the read only flag"
    }

    if ($did.Count -eq 0) { return "already writable" }
    return ($did -join ", ")
}

function Unlock-TreeForWrite {
    <#
    .SYNOPSIS
        The same, for every controlled file under a folder, ahead of a tool that rewrites the lot.

    .DESCRIPTION
        This is for the dump, which is a commandlet writing hundreds of files from C++. We cannot
        wrap each individual write, so the whole output folder is opened for edit up front. Without
        it, a second dump on a project that committed its first one fails on the first file it tries
        to overwrite and the artefacts are left half old and half new.

        p4 edit is given the ... wildcard rather than a file list, so files on disk that are not in
        the depot are skipped by the server rather than turning into an error each.
    #>
    param(
        [Parameter(Mandatory)] [string] $Path,

        [switch] $NoSourceControl
    )

    if (-not (Test-Path -LiteralPath $Path)) { return "not present, nothing to unlock" }

    $dir = Get-P4Directory $Path
    if (-not $NoSourceControl -and (Test-P4Available $dir)) {
        # No Test-P4Succeeded here: a folder holding both controlled and new files reports an error
        # line for the new ones and still opens the rest, which is exactly what we want.
        $out = Invoke-P4 $dir edit (Join-Path $Path '...')
        $count = @($out | Where-Object { $_ -match 'opened for edit' }).Count
        if ($count -gt 0) { return "checked $count file(s) out of Perforce" }
    }

    $cleared = 0
    Get-ChildItem -LiteralPath $Path -Recurse -File -Force | Where-Object { $_.IsReadOnly } | ForEach-Object {
        $_.IsReadOnly = $false
        $cleared++
    }
    if ($cleared -gt 0) { return "cleared the read only flag on $cleared file(s)" }
    return "nothing needed unlocking"
}
