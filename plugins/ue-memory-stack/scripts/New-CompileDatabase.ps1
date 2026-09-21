<#
.SYNOPSIS
    Generates compile_commands.json for a project, which is what clangd indexes.

.DESCRIPTION
    This is Layer 0. You only need it if you're running the clangd based symbol queries, so skip it
    if all you want is the reflection dump.

    Regenerate it after any .Build.cs or module change, because the database is a set of pointers
    into per-module response files and a stale one points at files that no longer describe the
    build.

    Note: the database references response files under <Project>\Intermediate\Build. Deleting those
    breaks clangd in a way that looks like clangd being broken rather than a missing file, so leave
    them alone.

.EXAMPLE
    .\New-CompileDatabase.ps1 -ProjectPath D:\Game\Game.uproject -EnginePath D:\UE_5.8
#>
[CmdletBinding()]
param(
    # One or more .uproject files. Several are put into a SINGLE UnrealBuildTool invocation, which
    # matters: see the comment above the invocation for why concatenating separate runs is wrong.
    [Parameter(Mandatory)] [string[]] $ProjectPath,
    [Parameter(Mandatory)] [string] $EnginePath,

    # Editor target names, in the same order as -ProjectPath. Discovered per project if omitted.
    [string[]] $Target,

    [ValidateSet('Debug', 'DebugGame', 'Development', 'Shipping')]
    [string] $Configuration = 'Development',

    # Where to write compile_commands.json. Defaults to the project folder.
    [string] $OutputDir,

    # Include engine source in the database. Bigger index, but it means symbol queries reach engine
    # types instead of stopping at your own code.
    [switch] $IncludeEngine,

    # Don't touch Perforce. A read only database is made writable instead.
    [switch] $NoSourceControl
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Common.ps1')

$ProjectPath = @($ProjectPath | ForEach-Object { (Resolve-Path $_).Path })
$EnginePath  = (Resolve-Path $EnginePath).Path
$firstDir    = Split-Path -Parent $ProjectPath[0]
$projectName = [IO.Path]::GetFileNameWithoutExtension($ProjectPath[0])

# One target per project, discovered unless given. Read from Target.cs rather than assuming
# <ProjectName>Editor: the target name comes from the Target.cs file and has nothing to do with the
# descriptor name, so on real projects the two often differ.
$targets = @()
for ($i = 0; $i -lt $ProjectPath.Count; $i++) {
    $dir  = Split-Path -Parent $ProjectPath[$i]
    $name = if ($Target -and $Target.Count -gt $i) { $Target[$i] } else { Find-EditorTarget $dir }
    if (-not $name) { throw "No editor target found under $dir\Source. Pass -Target." }
    $targets += [pscustomobject]@{ Name = $name; Project = $ProjectPath[$i] }
    Write-Host "Editor target: $name"
}

if (-not $OutputDir) {
    if ($ProjectPath.Count -gt 1) { throw "-OutputDir is required when you pass more than one -ProjectPath." }
    $OutputDir = $firstDir
}

$ubt = Join-Path $EnginePath 'Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe'
if (-not (Test-Path $ubt)) { throw "UnrealBuildTool.exe not found at $ubt." }

# UBT does not create the output directory, and it finds that out only after it has resolved every
# target and filtered every compile action. On a multi project run with -IncludeEngine that is about
# a minute of work thrown away, and the message is an unhandled DirectoryNotFoundException with a
# stack trace, which reads like a bug rather than a missing folder. This was only reachable once
# -OutputDir became a place you choose rather than the project folder, which always exists.
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# compile_commands.json lands in the project root and some teams commit it, so it can be read only
# by the time we come to regenerate it. UBT fails the write and then reports success anyway, which
# leaves clangd indexing against a database describing a build that no longer exists.
$existingDb = Join-Path $OutputDir 'compile_commands.json'
if (Test-Path $existingDb) {
    Write-Host "compile_commands.json: $(Unlock-FileForWrite -Path $existingDb -NoSourceControl:$NoSourceControl)"
}

# One invocation for all the targets, not one per target with the results concatenated.
#
# UnrealBuildTool accumulates repeatable -Target= arguments and -TargetList= files
# (TargetDescriptor.ParseCommandLine), so it can describe several targets in a single database and
# resolve shared engine files once. Running it per target and merging the outputs by hand leaves
# several entries for the same shared file, and whichever merged first wins. That is right only for
# as long as your targets happen to agree on the flags for shared code, and it fails silently on the
# first one that does not.
#
# The targets go in a file rather than on the command line because each descriptor contains spaces,
# and quoting them through PowerShell's argument handling is a trap this project has already been
# caught by once.
$targetList = Join-Path ([IO.Path]::GetTempPath()) "uea-targets-$PID.txt"
$targets | ForEach-Object { "$($_.Name) Win64 $Configuration -Project=`"$($_.Project)`"" } |
    Set-Content -LiteralPath $targetList -Encoding UTF8

$argv = @(
    "-TargetList=$targetList"
    '-game'
    '-mode=GenerateClangDatabase'
    '-NoExecCodeGenActions'
    "-OutputDir=$OutputDir"
)
if ($IncludeEngine) { $argv += '-engine' }

# Separate streams again, for the same PowerShell 5.1 reason as the build script.
$stdout = Join-Path $env:TEMP "compiledb-$projectName.out.log"
$stderr = Join-Path $env:TEMP "compiledb-$projectName.err.log"

Write-Host "Generating compile database for $($targets.Name -join ', '). This takes about half a minute."
$proc = Start-Process -FilePath $ubt -ArgumentList $argv -NoNewWindow -PassThru -Wait `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr

Remove-Item -LiteralPath $targetList -Force -ErrorAction SilentlyContinue

if ($proc.ExitCode -ne 0) {
    Get-Content $stdout -Tail 15
    throw "Generation failed with exit code $($proc.ExitCode). Full log: $stdout"
}

$db = Join-Path $OutputDir 'compile_commands.json'
if (-not (Test-Path $db)) { throw "UBT reported success but $db doesn't exist." }

$entries = (Get-Content $db -Raw | ConvertFrom-Json).Count
Write-Host "Wrote $db with $entries entries."
