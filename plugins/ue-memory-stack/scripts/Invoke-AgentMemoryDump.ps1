<#
.SYNOPSIS
    Runs the AgentMemoryDump commandlet against a project and writes Docs/AgentMemory.

.DESCRIPTION
    Three of the arguments this passes are not optional and each one cost real time to find:

    -Multiprocess   Without it the editor calls Turnkey, which shells out to Build.bat
                    -Mode=ValidatePlatforms, which takes a global lock and sits in a ping loop
                    forever. The flag skips the SetupPlatforms UBT call entirely.
    -NullRHI        There's no graphics device in a commandlet.
    The module qualified -run name. The module loads at PostEngineInit, which is after commandlet
                    class lookup, so a bare -run=AgentMemoryDump gives "looked like a commandlet,
                    but we could not find the class".

.EXAMPLE
    .\Invoke-AgentMemoryDump.ps1 -ProjectPath D:\Game\Game.uproject -EnginePath D:\UE_5.8
#>
[CmdletBinding()]
param(
    # Path to the .uproject to dump.
    [Parameter(Mandatory)] [string] $ProjectPath,

    # Root of the engine, the folder containing Engine\Binaries.
    [Parameter(Mandatory)] [string] $EnginePath,

    # Where to write the artefacts. Relative paths are relative to the folder holding the .uproject,
    # which is not the root of every tree: a descriptor in a subfolder with the docs a level above
    # it wants an explicit path, or you get a second Docs folder next to the real one.
    [string] $OutDir = 'Docs/AgentMemory',

    # Restrict the walk to these modules instead of discovering them from the project descriptor.
    [string[]] $Modules,

    # Skip the Blueprint graph walk. This is the expensive half, and it's also the half that
    # produces the blast radius answers, so only use it if the walk becomes a problem.
    [switch] $NoBlueprintGraphs,

    # Seconds to wait before giving up.
    [int] $TimeoutSeconds = 1800,

    # Don't touch Perforce. Read only artefacts are made writable instead, so use it when you
    # intend to put the output in a changelist yourself.
    [switch] $NoSourceControl
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Common.ps1')

$ProjectPath = (Resolve-Path $ProjectPath).Path
$EnginePath  = (Resolve-Path $EnginePath).Path
$projectDir  = Split-Path -Parent $ProjectPath
$projectName = [IO.Path]::GetFileNameWithoutExtension($ProjectPath)

$editorCmd = Join-Path $EnginePath 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
if (-not (Test-Path $editorCmd)) {
    throw "UnrealEditor-Cmd.exe not found at $editorCmd. Check -EnginePath points at the engine root."
}

# An interrupted engine build loses this and the commandlet then fails to start in a way that
# looks like our problem rather than a missing file.
$scw = Join-Path $EnginePath 'Engine\Binaries\Win64\ShaderCompileWorker.exe'
if (-not (Test-Path $scw)) {
    Write-Warning "ShaderCompileWorker.exe is missing. If the dump fails to start, rebuild it with:"
    Write-Warning "  UnrealBuildTool.exe ShaderCompileWorker Win64 Development"
}

# Checked before launching, because the failure it catches costs about a second and explains
# nothing. See Test-EditorBuildIdMismatch: building another project's editor target against this
# engine gives the engine a new BuildId and leaves this project's modules unresolvable.
$mismatch = Test-EditorBuildIdMismatch -EnginePath $EnginePath -ProjectDir $projectDir
if ($mismatch) {
    Write-Warning "This project's editor modules no longer match the engine ($mismatch)."
    Write-Warning "Another project's editor target has been built against this engine since this one was."
    Write-Warning "The editor will fail to find this project's own modules and exit almost immediately."
    throw "Rebuild first: .\Build-UEAgentAccelerator.ps1 -ProjectPath $ProjectPath -EnginePath $EnginePath"
}

$argv = @(
    $ProjectPath
    '-run=UEAgentAcceleratorTools.AgentMemoryDump'
    "-Out=$OutDir"
    '-unattended'
    '-nopause'
    '-nosplash'
    '-NullRHI'
    '-Multiprocess'
)
if ($Modules)           { $argv += "-Modules=$($Modules -join ',')" }
if ($NoBlueprintGraphs) { $argv += '-NoBlueprintGraphs' }

# The artefacts are meant to be committed, which on Perforce means the second dump onto a project
# that committed its first one meets a folder of read only files. The commandlet writes them from
# C++ so there is no per file hook to hang a checkout on, and it does not stop on the first failed
# write: it carries on, reports its usual summary and exits 0, leaving the output part old and part
# new. That is the worst of the failure modes here, because nothing about it looks like a failure.
$resolvedOut = if ([IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path $projectDir $OutDir }
# Collapsed, so a path given as ..\Docs\AgentMemory is reported and checked out as the folder it
# actually is rather than as <project>\..\Docs\AgentMemory.
$resolvedOut = [IO.Path]::GetFullPath($resolvedOut)
if (Test-Path $resolvedOut) {
    Write-Host "Output folder: $(Unlock-TreeForWrite -Path $resolvedOut -NoSourceControl:$NoSourceControl)"
}

$stdout = Join-Path $env:TEMP "agentmemorydump-$projectName.out.log"
$stderr = Join-Path $env:TEMP "agentmemorydump-$projectName.err.log"

Write-Host "Dumping $projectName..."
# A couple of seconds of slack, because file timestamp granularity and the clock don't have to
# agree to the millisecond and a file written in the first instant shouldn't be missed.
$startedAt = (Get-Date).AddSeconds(-2)
$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $editorCmd -ArgumentList $argv -NoNewWindow -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$proc | Wait-Process -Timeout $TimeoutSeconds -ErrorAction SilentlyContinue
$sw.Stop()

if (-not $proc.HasExited) {
    $proc | Stop-Process -Force
    throw "Timed out after $TimeoutSeconds seconds. Log: $stdout"
}

# The commandlet logs its own summary lines, and they say more than the exit code does.
$ueLog = Join-Path $projectDir "Saved\Logs\$projectName.log"
if (Test-Path $ueLog) {
    Select-String -Path $ueLog -Pattern 'AgentMemoryDump:' |
        Select-Object -Last 8 |
        ForEach-Object { '  ' + ($_.Line -split '\]')[-1].Trim() }
}

# Counted by what this run wrote, not by what is in the folder.
#
# The folder is meant to be committed, so on a re-dump it is full before the run starts, and a
# plain count of it comes back reassuringly large whatever just happened. A run that died in one
# second having written nothing at all reported files=1383 and "Wrote 1383 files", which is a
# success message for a total failure. Only files touched since the process started count.
$existing  = if (Test-Path $resolvedOut) { @(Get-ChildItem $resolvedOut -Recurse -File) } else { @() }
$written   = @($existing | Where-Object { $_.LastWriteTime -ge $startedAt })
$fileCount = $written.Count

Write-Host ("exit={0}  wall={1}s  written={2}  in folder={3}" -f `
    $proc.ExitCode, [math]::Round($sw.Elapsed.TotalSeconds, 1), $fileCount, $existing.Count)

# Output left over from a previous run, sitting next to what this one wrote. Worth saying, because
# a class deleted from the code leaves its file behind and nothing else will ever mention it.
$stale = $existing.Count - $fileCount
if ($fileCount -gt 0 -and $stale -gt 0) {
    Write-Warning "$stale file(s) in the output folder were not written by this run. They describe"
    Write-Warning "code that no longer exists, or a dump that covered different modules. Delete the"
    Write-Warning "folder and dump again if you want it to match the tree exactly."
}

# Whether files were written is the thing to judge this on, not the exit code, and the difference
# needs saying out loud. UnrealEditor-Cmd returns non-zero if anything logged an Error at any point,
# including Blueprint load errors in content that has nothing to do with us. The first real project
# this was run against dumped 967 classes perfectly and exited 1, on 567 pre-existing errors about a
# null ProxyFactoryClass in somebody's developer folder. Printing the code with no comment invites
# people to throw away a good dump.
if ($proc.ExitCode -ne 0 -and $fileCount -gt 0) {
    $errors = @(Select-String -Path $ueLog -Pattern ': Error: ' -ErrorAction SilentlyContinue)
    Write-Host "Non-zero exit with output written. The editor returns non-zero if anything logged an"
    Write-Host "Error during the run, so on a project with pre-existing content errors this is normal"
    Write-Host "and says nothing about the dump. Judge it on the summary above and the file count."
    if ($errors.Count -gt 0) {
        Write-Host "  $($errors.Count) error line(s) in $ueLog, first:"
        Write-Host "  $((($errors[0].Line -split '\]')[-1]).Trim())"
    }
}

if ($fileCount -eq 0) {
    Write-Warning "No files written. Two things to check first:"
    Write-Warning "  1. Did the plugin load? Look for 'Skipping load of' in $ueLog. A .uplugin"
    Write-Warning "     declaring an older EngineVersion compiles fine and is then skipped at startup."
    Write-Warning "  2. Is the DLL stale? Run Build-UEAgentAccelerator.ps1 and try again."
    throw "Dump produced no output. Log: $stdout"
}

# A transient load failure straight after a successful build is a known thing and re-running fixes
# it. It's worth saying so, because the alternative is an afternoon with dumpbin.
$loadFail = Select-String -Path $ueLog -Pattern "Failed to load .*UEAgentAcceleratorTools" -ErrorAction SilentlyContinue
if ($loadFail) {
    Write-Warning "The module failed to load. If this happened straight after a successful build it's"
    Write-Warning "transient, so run the same command again before investigating."
}

Write-Host "Wrote $fileCount files to $resolvedOut"
