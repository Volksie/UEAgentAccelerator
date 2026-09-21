<#
.SYNOPSIS
  Moves the memory layers and the answer keys out of the tree for a measured benchmark run,
  and puts them back.

.DESCRIPTION
  The baseline arm must not be able to REACH CLAUDE.md, .claude/rules/ or Docs/AgentMemory - not
  merely be told not to use them (bench/BASELINE-ARM-SPEC.md).

  A parallel root of directory junctions cannot achieve that here: compile_commands.json is written
  in absolute paths into the real tree, so Layer 0 and Layer 1 resolve back to it
  from any working directory, and Bash reads any absolute path regardless of cwd. Moving the files
  aside is the only method that actually holds.

  Two profiles:
    layers   - moves only bench/ (the answer keys). For the with-layers arm.
    baseline - moves bench/ AND every memory layer. For the baseline arm.

  bench/ is moved in BOTH arms because the question files
  contain the answer keys in plain text, greppable from the tree root. A run with those present
  is not measuring retrieval.

.PARAMETER Mode
  Apply, Restore, Verify or Status.

.PARAMETER Arm
  baseline or layers. Required for Apply and Verify.

.NOTES
  While applied, the tree is modified. Do not build, regenerate dumps, or run another Claude
  session in this tree. Restore is idempotent and safe to run after a crash.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Apply', 'Restore', 'Verify', 'Status', 'Check')]
    [string]$Mode,

    [ValidateSet('baseline', 'layers')]
    [string]$Arm,

    # Tree to isolate. Defaults to the repository root two levels above this script.
    [string]$Root,

    # Where moved paths are parked. Must be OUTSIDE the tree, or you move it into itself.
    [string]$Holding,

    # Benchmark config, used to find each project's artefact and design directories.
    [string]$Config,

    # Anything else that would leak a layer: stray copies, zips, backup directories.
    [string[]]$ExtraLayerPaths = @()
)

$ErrorActionPreference = 'Stop'

$TreeRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ($Root) { $TreeRoot = (Resolve-Path $Root).Path }
# Outside the tree on purpose, so a run can move tree paths aside without moving them within it.
if (-not $Holding) { $Holding = Join-Path (Split-Path -Parent $TreeRoot) '.uea-bench-holding' }
$Manifest = Join-Path $Holding 'manifest.json'
if (-not $Config) { $Config = Join-Path $TreeRoot 'bench\projects.json' }

# Answer keys. Moved in both arms - a visible key is not a retrieval measurement.
$CommonPaths = @(
    'bench'
)

# The memory layers. The per project artefact and design directories come from the benchmark config
# rather than being listed here, so adding a project to the benchmark cannot silently leave its
# artefacts readable by the baseline arm.
$LayerPaths = @(
    'CLAUDE.md',
    'CLAUDE.local.md',
    '.claude'
)
if (Test-Path $Config) {
    $cfg = Get-Content $Config -Raw | ConvertFrom-Json
    foreach ($p in $cfg.projects) {
        $LayerPaths += (Join-Path $p.dir 'Docs\AgentMemory')
        $LayerPaths += (Join-Path $p.dir 'Docs\Design')
    }
} else {
    Write-Warning "No benchmark config at $Config. Per project artefact paths will NOT be isolated."
}
$LayerPaths += $ExtraLayerPaths

# Important, and learned the hard way twice: a COPY of the artefacts anywhere in the tree defeats all
# of this, and neither copy was found by a name based exclusion list. One was a zip at the tree root
# holding 104 class files. The other was a backup directory whose name did not contain "AgentMemory"
# at all, and it was only noticed because a baseline answer cited a file inside it, after that arm
# had already run. Put anything of that shape in -ExtraLayerPaths. run_bench.py's leak check
# recognises artefact trees by SHAPE rather than by name for the same reason.

# Deliberately NOT moved:
#   A project's OWN CLAUDE.md or AGENTS.md, where a question asks what that file says.
#     They are the codebase's content, not our layer. Below the run's cwd, so readable but
#     not auto-loaded, which is what D15's one-file-read route expects.
#   The plugin source. It is the commandlet's SOURCE, not a generated artefact.

# A marker INSIDE the tree, saying the tree is locked.
#
# It has to be in the tree. The manifest lives in the holding directory, outside it, so anyone
# opening the repository never sees that one. And on a baseline run **CLAUDE.md is itself moved
# aside**, so the usual channel for telling a session what is going on is gone at precisely the
# moment it is needed. A run interrupted by a forced restart otherwise leaves somebody looking at a
# tree with no CLAUDE.md, no .claude/ and no explanation.
#
# It must name no moved path. Benchmark agents run with their working directory here and can read
# this file, so "<project>/Docs/AgentMemory is hidden" would tell a baseline agent those artefacts
# exist, which is the contamination the arm exists to prevent. A count, never names.
$Marker = Join-Path $TreeRoot 'BENCH-RUN-IN-PROGRESS.md'

function Write-Marker([string]$a, [int]$count) {
    $body = @"
# A measured benchmark run is in progress. This tree is locked.

**Do not edit anything under ``$TreeRoot`` while this file exists.** A measured run records what an
agent can see and what it costs, so any edit changes the result silently.

- arm: **$a**
- started: **$((Get-Date).ToString('o'))**
- paths held aside: **$count**, deliberately not listed, because naming them would leak the thing the
  run is measuring
- held in: ``$Holding``

Some files you expect are temporarily moved, ``CLAUDE.md`` among them on a baseline run. They are not
lost.

## If no benchmark is actually running, the run died and the tree needs restoring

A crash, a killed terminal or a forced restart leaves this file behind.

``````
powershell -File "<this script>" -Mode Check -Root "$TreeRoot"
powershell -File "<this script>" -Mode Restore -Root "$TreeRoot"
``````

``-Mode Check`` exits non-zero when isolation is applied, which is the "something failed" case if you
know no run is alive. Restore is safe at any time and does nothing when there is nothing to restore.
"@
    Set-Content -LiteralPath $Marker -Value $body -Encoding UTF8
}

function Remove-Marker {
    if (Test-Path -LiteralPath $Marker) {
        Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
    }
}

function Get-PathsForArm([string]$a) {
    if ($a -eq 'baseline') { return $CommonPaths + $LayerPaths }
    return $CommonPaths
}

function Write-Status([string]$msg, [string]$colour = 'Gray') {
    Write-Host $msg -ForegroundColor $colour
}

switch ($Mode) {

    'Status' {
        if (Test-Path $Manifest) {
            $m = Get-Content $Manifest -Raw | ConvertFrom-Json
            Write-Status "APPLIED - arm '$($m.arm)', $($m.paths.Count) paths, since $($m.appliedAt)" 'Yellow'
            Write-Status "Holding: $Holding"
            Write-Status "Run -Mode Restore before building, regenerating dumps, or other work in this tree." 'Yellow'
        }
        else {
            Write-Status 'CLEAN - nothing is moved aside.' 'Green'
        }
    }

    'Apply' {
        if (-not $Arm) { throw '-Arm is required for Apply.' }
        if (Test-Path $Manifest) {
            $m = Get-Content $Manifest -Raw | ConvertFrom-Json
            throw "Isolation is already applied for arm '$($m.arm)'. Run -Mode Restore first."
        }

        $paths = Get-PathsForArm $Arm
        if (-not (Test-Path $Holding)) { New-Item -ItemType Directory -Path $Holding -Force | Out-Null }

        $moved = @()
        try {
            foreach ($rel in $paths) {
                $src = Join-Path $TreeRoot $rel
                if (-not (Test-Path $src)) {
                    Write-Status "  skip (absent): $rel"
                    continue
                }
                $dst = Join-Path $Holding $rel
                $dstParent = Split-Path $dst -Parent
                if (-not (Test-Path $dstParent)) { New-Item -ItemType Directory -Path $dstParent -Force | Out-Null }
                Move-Item -LiteralPath $src -Destination $dst -Force
                $moved += $rel
                Write-Status "  moved: $rel"
            }
        }
        catch {
            Write-Status "FAILED partway. Rolling back $($moved.Count) moves." 'Red'
            foreach ($rel in $moved) {
                $back = Join-Path $TreeRoot $rel
                $from = Join-Path $Holding $rel
                if (Test-Path $from) { Move-Item -LiteralPath $from -Destination $back -Force }
            }
            throw
        }

        $manifestObj = [ordered]@{
            arm       = $Arm
            appliedAt = (Get-Date).ToString('o')
            treeRoot  = $TreeRoot
            paths     = $moved
        }
        $manifestObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $Manifest -Encoding utf8
        Write-Marker $Arm $moved.Count
        Write-Status "APPLIED arm '$Arm': $($moved.Count) paths moved to $Holding" 'Green'
        Write-Status "  tree marked locked: $Marker" 'Gray'
    }

    'Restore' {
        if (-not (Test-Path $Manifest)) {
            Write-Status 'Nothing to restore - no manifest.' 'Green'
            break
        }
        $m = Get-Content $Manifest -Raw | ConvertFrom-Json
        $failed = @()
        foreach ($rel in $m.paths) {
            $from = Join-Path $Holding $rel
            $back = Join-Path $TreeRoot $rel
            if (-not (Test-Path $from)) {
                if (Test-Path $back) { Write-Status "  already back: $rel" }
                else { $failed += $rel; Write-Status "  MISSING BOTH SIDES: $rel" 'Red' }
                continue
            }
            if (Test-Path $back) { $failed += $rel; Write-Status "  CONFLICT, exists in tree: $rel" 'Red'; continue }
            $backParent = Split-Path $back -Parent
            if (-not (Test-Path $backParent)) { New-Item -ItemType Directory -Path $backParent -Force | Out-Null }
            Move-Item -LiteralPath $from -Destination $back -Force
            Write-Status "  restored: $rel"
        }
        if ($failed.Count -gt 0) {
            throw "Restore incomplete. Unresolved: $($failed -join ', '). Holding kept at $Holding - resolve by hand."
        }
        Remove-Item -LiteralPath $Manifest -Force
        Remove-Marker
        Write-Status "RESTORED $($m.paths.Count) paths." 'Green'
    }

    'Check' {
        # Separates "a run is holding this tree" from "a run died and left it holding". Both look
        # identical from outside, and the second is the one that needs a human.
        $hasManifest = Test-Path -LiteralPath $Manifest
        $hasMarker   = Test-Path -LiteralPath $Marker
        if (-not $hasManifest -and -not $hasMarker) {
            Write-Status 'CLEAN - nothing is held aside.' 'Green'
            exit 0
        }
        if ($hasManifest -and $hasMarker) {
            $m = Get-Content $Manifest -Raw | ConvertFrom-Json
            Write-Status "ISOLATION APPLIED - arm '$($m.arm)', $($m.paths.Count) paths, since $($m.appliedAt)." 'Yellow'
            Write-Status 'If no benchmark is running, the run died: -Mode Restore puts it back.' 'Yellow'
            exit 1
        }
        if ($hasMarker) {
            Write-Status 'Marker present but no manifest. Inconsistent - a Restore got part way.' 'Red'
        } else {
            Write-Status 'Manifest present but no marker. Inconsistent - the tree may be held.' 'Red'
        }
        exit 1
    }

    'Verify' {
        if (-not $Arm) { throw '-Arm is required for Verify.' }
        $paths = Get-PathsForArm $Arm
        $leaks = @()
        foreach ($rel in $paths) {
            $p = Join-Path $TreeRoot $rel
            if (Test-Path $p) { $leaks += $rel }
        }
        if ($leaks.Count -gt 0) {
            Write-Status "ISOLATION FAILED for arm '$Arm'. Still present in tree:" 'Red'
            foreach ($l in $leaks) { Write-Status "  $l" 'Red' }
            exit 1
        }
        Write-Status "ISOLATION HOLDS for arm '$Arm': none of the $($paths.Count) excluded paths are present in $TreeRoot." 'Green'
    }
}
