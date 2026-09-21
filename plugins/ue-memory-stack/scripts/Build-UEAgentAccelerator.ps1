<#
.SYNOPSIS
    Builds a project's editor target so the plugin's DLL is current, then checks that it actually is.

.DESCRIPTION
    We call UnrealBuildTool directly rather than Build.bat, because Build.bat takes a batch level
    lock that survives a cancelled build and blocks the next one.

    The plugin is shared by source but its binaries are built per project, so each project you use
    it on has its own UnrealEditor-UEAgentAcceleratorTools.dll and each one needs building. Building
    one project and dumping another writes old format files, reports success and exits 0.

.EXAMPLE
    .\Build-UEAgentAccelerator.ps1 -ProjectPath D:\Game\Game.uproject -EnginePath D:\UE_5.8
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $ProjectPath,
    [Parameter(Mandatory)] [string] $EnginePath,

    # Editor target name. Discovered from the project's Target.cs files if you don't pass it.
    [string] $Target,

    [ValidateSet('Debug', 'DebugGame', 'Development', 'Shipping')]
    [string] $Configuration = 'Development',

    # Where the plugin source lives, for the staleness check. Resolved in the body, not here: on
    # Windows PowerShell 5.1 $PSScriptRoot is empty while parameter defaults are evaluated, and
    # Join-Path then refuses the empty string and kills the script before its first line.
    [string] $PluginSource,

    # Check whether the DLL is older than the source and stop, without building.
    [switch] $CheckOnly
)

$ErrorActionPreference = 'Stop'

if (-not $PluginSource) {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $PluginSource = Join-Path $here '..\ue-plugin\UEAgentAccelerator'
}

. (Join-Path $PSScriptRoot 'Common.ps1')

$ProjectPath  = (Resolve-Path $ProjectPath).Path
$EnginePath   = (Resolve-Path $EnginePath).Path
$PluginSource = (Resolve-Path $PluginSource).Path
$projectDir   = Split-Path -Parent $ProjectPath
$projectName  = [IO.Path]::GetFileNameWithoutExtension($ProjectPath)

# Where the DLL lands depends on how the plugin was installed, and it is not where the first
# version of this script looked. A plugin's modules build into the plugin's own Binaries folder,
# not the project's, so checking <Project>\Binaries found nothing however good the build was and
# every run ended on "build reported success but the DLL is still older than the source".
#
# All three are checked rather than worked out from the install mode, because the script is not
# told which mode was used and a leftover from the other one is worth finding.
$dllCandidates = @(
    (Join-Path $projectDir  'Plugins\UEAgentAccelerator\Binaries\Win64\UnrealEditor-UEAgentAcceleratorTools.dll')
    (Join-Path $PluginSource 'Binaries\Win64\UnrealEditor-UEAgentAcceleratorTools.dll')
    (Join-Path $projectDir  'Binaries\Win64\UnrealEditor-UEAgentAcceleratorTools.dll')
)

function Get-PluginDll {
    $found = @($dllCandidates | Where-Object { Test-Path $_ })
    if ($found.Count -eq 0) { return $null }
    # Newest wins, so a stale copy from an older install doesn't mask the one just built.
    return (Get-Item $found | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}

# The plugin source the build actually compiled. After a -Mode Copy install that is the copy under
# the project, not this repository, and the difference is the whole of the next two functions.
$installedSource = Join-Path $projectDir 'Plugins\UEAgentAccelerator\Source'
$compiledSource  = if (Test-Path $installedSource) { $installedSource } else { Join-Path $PluginSource 'Source' }

function Test-DllIsCurrent {
    # Re-resolved on each call rather than captured once, because before the build there may be no
    # DLL anywhere and the whole point of the call afterwards is to find the one that just appeared.
    $dll = Get-PluginDll
    if (-not $dll) { return $false }

    # Compare against the editor module only, not the whole Source tree. A UHT exporter alongside it
    # compiles into a separate assembly through its own csproj, so editing that file says nothing
    # about whether this DLL is current, and comparing against it reports a false stale.
    #
    # And compare against the source that was compiled, not this repository's copy. Timestamps here
    # are only meaningful between a build output and its own inputs. Against a working copy they are
    # meaningless: git and Perforce both stamp every file they write with the time they wrote it, so
    # a rebase or a sync that changes nothing at all makes the repository look newer than any DLL.
    # 06-keeping-it-fresh.md makes this exact point about artefacts; it applies here too.
    $moduleSource = Join-Path $compiledSource 'UEAgentAcceleratorTools'
    if (-not (Test-Path $moduleSource)) { return $false }
    $newestSource = Get-ChildItem $moduleSource -Recurse -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return (Get-Item $dll).LastWriteTime -ge $newestSource.LastWriteTime
}

function Test-InstalledCopyDiffers {
    <#
        Whether the installed copy's contents differ from this repository's, compared by hash.

        By content rather than by date, for the reason above: after a rebase the repository's files
        are newer than an install that matches them byte for byte, and a date comparison then sends
        you to re-install something that is already identical.
    #>
    if (-not (Test-Path $installedSource)) { return $false }

    $hashTree = {
        param($root)
        (Get-ChildItem $root -Recurse -File | Sort-Object FullName | ForEach-Object {
            $_.FullName.Substring($root.Length) + ':' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        }) -join '|'
    }
    return (& $hashTree $installedSource) -ne (& $hashTree (Join-Path $PluginSource 'Source'))
}

if ($CheckOnly) {
    if (Test-DllIsCurrent) {
        Write-Host "DLL is current: $(Get-PluginDll)"
        exit 0
    }
    if (-not (Get-PluginDll)) {
        throw "No plugin DLL anywhere. Looked in:`n  $($dllCandidates -join "`n  ")"
    }
    throw "Stale DLL, do not dump. $(Get-PluginDll) is older than the plugin source. Run this script without -CheckOnly."
}

# After the -CheckOnly branch, because that one answers a question about a file on disk and has no
# business failing on a project with two editor targets when it isn't going to build either of them.
if (-not $Target) {
    $Target = Find-EditorTarget $projectDir
    if (-not $Target) { throw "No editor target found under $projectDir\Source. Pass -Target." }
    Write-Host "Editor target: $Target"
}

$ubt = Join-Path $EnginePath 'Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe'
if (-not (Test-Path $ubt)) { throw "UnrealBuildTool.exe not found at $ubt." }

# Important: don't wrap this in 2>&1. On PowerShell 5.1, redirecting a native executable's stderr
# wraps each line in an ErrorRecord and corrupts $?, so a build that succeeded is reported as
# Result: Failed (OtherCompilationError). We redirect the two streams to separate files instead.
$stdout = Join-Path $env:TEMP "ubt-$projectName.out.log"
$stderr = Join-Path $env:TEMP "ubt-$projectName.err.log"

Write-Host "Building $Target $Configuration..."
$proc = Start-Process -FilePath $ubt -NoNewWindow -PassThru -Wait `
    -ArgumentList @($Target, 'Win64', $Configuration, "-Project=$ProjectPath") `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr

Get-Content $stdout -Tail 15

if ($proc.ExitCode -ne 0) {
    Write-Host "--- stderr ---"
    Get-Content $stderr -Tail 20 -ErrorAction SilentlyContinue
    throw "Build failed with exit code $($proc.ExitCode). Full log: $stdout"
}

# Checking the build succeeded isn't the same as checking the artefact is current, and this is the
# only check that has ever caught a stale DLL before a dump silently wrote the old format.
if (-not (Test-DllIsCurrent)) {
    if (-not (Get-PluginDll)) {
        throw "Build reported success but there is no plugin DLL. Looked in:`n  $($dllCandidates -join "`n  ")`nIs the plugin enabled in the .uproject?"
    }
    # A -Mode Copy install compiles the copy under <Project>\Plugins, not the source in this
    # repository, so the two drift the moment you edit the repository and don't re-install. That
    # needs a different fix from an ordinary stale DLL, so say which.
    if (Test-InstalledCopyDiffers) {
        throw "$installedSource differs from $PluginSource, so the build compiled a stale copy. Re-run Install-UEAgentAccelerator.ps1 -Force, then build again."
    }
    throw "Build reported success but $(Get-PluginDll) is still older than the plugin source. Don't dump yet."
}

Write-Host "Built. DLL is current: $(Get-PluginDll)"
