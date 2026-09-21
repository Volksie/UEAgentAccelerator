<#
.SYNOPSIS
  Builds the baseline arm's room: a clean root beside the tree holding only what that arm may see.

.DESCRIPTION
  The reasoning is in bench/BASELINE-ARM-SPEC.md, under "What the arm can SEE". Read it before
  changing anything here: two things that look like obvious improvements were considered and rejected,
  and the reasons are not obvious from the code.

  WHY A ROOM AT ALL. Move-aside isolation is a denylist: every file that exists, or that anyone later
  creates, is readable by the measured agent until somebody classifies it. Fifteen leak channels over
  three attempts, thirteen in-tree, and each round found them in places the previous round had blessed.
  The room inverts the default - it contains only what was deliberately put there, so a file nobody
  thought about is absent by construction.

  The argument is about VERIFICATION COST, not tightness. Proving a denylist complete never ends;
  enumerating what to copy is a bounded list of about twenty items. "We kept finding leaks" invites
  "so keep fixing them"; this does not.

  WHAT THE ROOM IS *NOT*. It is not the control. You cannot prove unreachability for an agent with
  Bash - the real tree remains one absolute path away, and this room sits beside it rather than
  replacing it. **The control is the per-question leak gate in run_bench.py**, which proves NON-ACCESS
  from the run's own record and aborts on the first hit. The room is defence in depth: it removes
  everything that is present by default, so nothing is stumbled into.

  WHAT GOES IN, and the three decisions worth knowing:

    copied     Source/, Config/, Plugins/ minus build output, and the .uproject
    HARDLINKED Content/ - see below, this is not a copy
    junctioned the engine, from where it already is
    absent     Docs/, CLAUDE.md, .claude/, bench/, tools/, Shared/, .serena/, .clangd-db/, every root
               document, every build log - none of it by exclusion rule, all of it by never being named

  1. CONTENT IS HARDLINKED, NOT COPIED. On our own tree that is 2,967 files and 1.8 GB for the
     sample game alone, on the same volume. A hardlink
     costs no bytes, and unlike a junction it leaks nothing: a hardlink has no target path, so
     `readlink -f` returns its own path and `cd -P ..` stays inside the room. It also removes drift for
     the largest part of the room, because an in-place edit is seen through the link.
     CAVEAT, and it is why the drift manifest still exists: a file that is REPLACED (delete then
     create, which is what most tools actually do) breaks the link, and the room silently keeps the old
     content. Hardlinking reduces drift; it does not remove it.

  2. CONTENT IS REQUIRED. Those .uasset files ARE the codebase for the Blueprint group, whose entire
     baseline cost signature is grepping them. Excluding them would not make the comparison cleaner -
     it would make that group unanswerable and its result meaningless.

  3. THE ENGINE IS JUNCTIONED FROM WHERE IT IS, not moved. An earlier draft moved it to a neutral path
     so `readlink -f` would land somewhere harmless. That was needed only under a layout where the tree
     is renamed aside; the decided layout leaves the tree in place and readable, so the junction points
     at something already in reach rather than opening anything new. Cancelling the move avoids
     rewriting 76,822 path references and risking 1.1 GB and ~2 hours of clangd indexing - a cost that
     would have landed on the LAYERS arm, the one that needs the symbol index.

  THE PROOF STEP. `Assert-NoLayerVocabulary` greps the built room for anything that describes the
  layers and FAILS THE BUILD if it finds any. This is the method that caught the last three leaks -
  apply isolation, then grep what is actually left - promoted from something I did by hand into a named
  build step with a stated exit condition. The room is not built until it passes.

.PARAMETER Mode
  Build   - create or refresh the room. Refuses while a run is in progress.
  Verify  - compare the room against the live tree and report drift. Writes nothing.
  Status  - report what exists.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Build', 'Verify', 'Status')]
    [string]$Mode,

    # The tree being measured. No default: a wrong guess here builds a room out of the wrong
    # codebase and every number afterwards is about something else.
    [Parameter(Mandatory = $true)]
    [string]$TreeRoot,

    # Where the room goes. Beside the tree by default, never inside it - a room inside the tree would
    # be copied into itself on the next build, and is reachable from the arm it is meant to isolate.
    [string]$Root,

    # Which projects to admit, and how much of each. Defaults to the benchmark's own project list, so
    # one file describes the projects for the generator and for the room.
    [string]$Config
)

$ErrorActionPreference = 'Stop'

$TreeRoot = (Resolve-Path -LiteralPath $TreeRoot).Path
if (-not $Root) {
    $Root = Join-Path (Split-Path $TreeRoot -Parent) ('.' + (Split-Path $TreeRoot -Leaf) + '-baseline-room')
}
if ($Root.ToLower().StartsWith($TreeRoot.ToLower())) {
    throw "-Root must sit outside -TreeRoot. A room inside the tree gets copied into itself."
}
if (-not $Config) { $Config = Join-Path $PSScriptRoot '..\projects.json' }

# BESIDE the room, never in it. The first version wrote this into the room root, and on a live run
# six of the first 51 baseline questions read it: it names the real tree's path and describes every
# admissible directory, so a procedure question gets told where the tree is and that something is
# watching it. The room's one invariant is that it holds only what was deliberately put there, and its
# own bookkeeping is exactly the kind of thing that never gets thought of as "put there".
#
# Same rule for anything else a run wants to leave: a marker, a log, a status file. Nothing of ours in
# the room, however innocuous its wording.
$ManifestPath = "$($Root).manifest.json"
# Where the first version put it. Build removes it; Verify refuses while it is still there.
$LegacyManifestPath = Join-Path $Root '.baseline-manifest.json'
$MarkerName   = 'BENCH-RUN-IN-PROGRESS.md'

# Per project, what is admissible. Per-project rather than global because the thing that must never
# come across - the generated artefact directory - lives inside each one.
#
# Read from bench/projects.json rather than listed here, so the room admits exactly the projects the
# question generator draws from. A project in one list and not the other is how an arm ends up being
# asked about a codebase it cannot see. Override per project with a "room" object:
#
#     "room": { "copy": ["Source", "Config"], "link": ["Content"] }
$Projects = @()
if (-not (Test-Path -LiteralPath $Config)) { throw "No project config at $Config" }
$cfg = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
foreach ($p in $cfg.projects) {
    $room = $p.PSObject.Properties['room']
    $Projects += @{
        Name = ($p.dir -replace '/', '\')
        Copy = if ($room) { @($room.Value.copy) } else { @('Source', 'Config', 'Plugins') }
        Link = if ($room) { @($room.Value.link) } else { @('Content') }
    }
}
if ($Projects.Count -eq 0) { throw "$Config lists no projects" }

# Excluded at any depth. Build output and tool state: the arm never builds, and this is where the
# compile databases and the clangd index live.
$ExcludeDirs = @('Binaries', 'Intermediate', 'Saved', 'DerivedDataCache', 'Build',
                 '.git', '.vs', '.serena', '.clangd-db', 'Docs')

# Must not appear anywhere in the built room. Every term here is one that a real leak used on our
# tree. ADD YOUR OWN: whatever you named your artefact directories, your MCP tools and your rules
# files belongs in this list, or the proof step passes by not knowing what to look for.
$LayerVocabulary = @('AgentMemory', 'bpcallers', 'BlueprintCallers', 'Blueprints\.md',
                     'engine_api_', 'engine-api', 'classes/<Class>')

# Directories exempt from that scan, matched anywhere in the path.
#
# The accelerator plugin is the awkward case, and it is awkward on purpose. The boundary rule says the
# baseline arm gets the real codebase unaltered, so if the plugin is installed into a project it stays -
# and its own source names the artefacts by construction, because it is the code that writes them.
# Removing it would mean measuring against a doctored codebase, which is worse than what it prevents.
# So it is exempt from the vocabulary scan and NOT from the room: an agent reading the dump's source
# learns that a dump exists, which is true of the tree it is being asked about.
#
# Give anything you add here a reason. This list is the one place the proof step can be blunted.
$ScanExcludePaths = @('UEAgentAccelerator')

# Text-like files are scanned exhaustively. Content binaries are not: they are generated from game
# assets and cannot contain layer prose by construction, and scanning 1.8 GB of .uasset would take
# minutes on every build, which is how a check stops being run. The leak gate catches access to
# anything regardless of what this scan covers.
$ScanExtensions = @('.cs', '.cpp', '.h', '.hpp', '.inl', '.json', '.uproject', '.uplugin',
                    '.ini', '.md', '.txt', '.ps1', '.py', '.xml', '.yml', '.yaml', '.bat')

function Write-Step([string]$m) { Write-Host "  -> $m" -ForegroundColor Cyan }
function Write-Ok  ([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Write-Bad ([string]$m) { Write-Host "  BAD  $m" -ForegroundColor Red }

function Assert-NoRunInProgress {
    foreach ($r in @($TreeRoot, $Root)) {
        if (Test-Path -LiteralPath (Join-Path $r $MarkerName)) {
            throw ("A benchmark run holds $r. Building the room now would change the codebase under a " +
                   "live measurement.")
        }
    }
}

function Copy-Admissible([string]$from, [string]$to) {
    # robocopy rather than Copy-Item: incremental, handles long paths, takes an exclude list without a
    # per-file filter over thousands of files. /MIR mirrors, so a file deleted from the tree disappears
    # from the room - without it a stale copy of a deleted layer could survive indefinitely, which is
    # the leak this whole design exists to prevent.
    $xd = @()
    foreach ($d in $ExcludeDirs) { $xd += '/XD'; $xd += $d }
    $rcArgs = @($from, $to, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1') + $xd
    $null = & robocopy @rcArgs
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) copying $from" }
    # robocopy uses exit codes 1-7 to mean "work was done", not "failure". Left unreset it becomes the
    # SCRIPT's exit code, so a successful build exits 1 and any caller checking the code concludes the
    # room failed to build. Found by the build succeeding and reporting failure in the same breath.
    $global:LASTEXITCODE = 0
}

function Link-Tree([string]$from, [string]$to) {
    <#
      Hardlinks every file, recreating the directory structure. Windows has no directory hardlinks, so
      this is per-file - fast, but not a single call.

      Existing files are left alone rather than re-linked. A hardlink IS the same file, so size and
      mtime always match and cannot distinguish a good link from a stale copy; the drift manifest is
      what catches that, and a full rebuild is the cure.
    #>
    $made = 0; $kept = 0
    $srcFiles = Get-ChildItem -LiteralPath $from -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $d = $_.DirectoryName; -not ($ExcludeDirs | Where-Object { $d -like "*\$_\*" -or $d -like "*\$_" }) }

    foreach ($f in $srcFiles) {
        $rel = $f.FullName.Substring($from.Length).TrimStart('\')
        $dest = Join-Path $to $rel
        if (Test-Path -LiteralPath $dest) { $kept++; continue }
        $destDir = Split-Path $dest -Parent
        if (-not (Test-Path -LiteralPath $destDir)) { $null = New-Item -ItemType Directory -Path $destDir -Force }
        try {
            $null = New-Item -ItemType HardLink -Path $dest -Target $f.FullName -ErrorAction Stop
            $made++
        }
        catch {
            # A hardlink can fail across volumes or on a locked file. Falling back to a copy keeps the
            # room correct; it only costs disk and reintroduces drift for that one file.
            Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
            $made++
        }
    }
    return @{ made = $made; kept = $kept; total = $srcFiles.Count }
}

function New-EngineJunction {
    # Only when the engine lives inside the tree, which is the source-build layout. An installed
    # engine is already outside it and needs no junction, so its absence is not a failure.
    $link = Join-Path $Root 'UnrealEngine'
    $target = Join-Path $TreeRoot 'UnrealEngine'
    if (-not (Test-Path -LiteralPath $target)) {
        Write-Ok 'no engine inside the tree, nothing to junction'
        return
    }
    if (Test-Path -LiteralPath $link) {
        $item = Get-Item -LiteralPath $link -Force
        if ($item.LinkType -eq 'Junction') { Write-Ok 'engine junction already in place'; return }
        throw "$link exists and is not a junction. Remove it by hand - refusing to delete an engine."
    }
    $null = New-Item -ItemType Junction -Path $link -Target $target
    Write-Ok "engine junction -> $target (not copied)"
}

function Assert-NoLayerVocabulary {
    <#
      THE PROOF STEP. The allowlist should make this impossible; this establishes that it did, rather
      than assuming it. It also catches the case the allowlist cannot: an admissible file that GAINS
      layer prose later, which is exactly how a .gitignore, a module's .Build.cs and the UHT plugin
      descriptors leaked under the old design.

      The engine junction is skipped - hundreds of gigabytes of stock Epic source, and the only thing
      in the tree that has never appeared in a leak finding.
    #>
    Write-Step 'proof step: scanning the room for layer vocabulary'
    $pattern = ($LayerVocabulary -join '|')
    $files = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object {
            $f = $_.FullName
            $f -notlike "*\UnrealEngine\*" -and
            $ScanExtensions -contains $_.Extension.ToLower() -and
            -not ($ScanExcludePaths | Where-Object { $f -like "*\$_\*" })
        }

    $hits = @($files | Select-String -Pattern $pattern -List -ErrorAction SilentlyContinue |
              Select-Object -ExpandProperty Path -Unique)

    if ($hits.Count -gt 0) {
        foreach ($h in $hits) { Write-Bad ($h -replace [regex]::Escape($Root), '<room>') }
        throw ("$($hits.Count) file(s) in the room name a layer. Either the allowlist let something " +
               "through, or an admissible file gained layer prose. Fix the SOURCE, then rebuild - " +
               "editing the room would be fixed until the next build and nobody would know.")
    }
    Write-Ok "no layer vocabulary in $($files.Count) scanned files"
}

function Assert-RoomRootClean {
    <#
      The room root may hold the projects' top-level directories and the engine junction, nothing else.

      Assert-NoLayerVocabulary cannot catch run metadata: a manifest or a lock file names no layer, and
      on our tree both were read by measured baseline sessions for two whole benchmark versions, 49 and
      60 sessions out of 170 in one of them. Checking what the root SHOULD hold is the allowlist applied
      to the room itself.

      Runs in Verify as well as Build, and run_bench.py calls Verify before a room-mode run, so a stray
      file stops the run before its first question.
    #>
    # A project dir like seed\AccelDemo lives under a top-level seed\ in the room, so compare first
    # segments rather than whole names.
    $allowed = @($Projects | ForEach-Object { ($_.Name -split '[\\/]')[0] } | Select-Object -Unique) + 'UnrealEngine'
    $extra = @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue |
               Where-Object { $allowed -notcontains $_.Name } | ForEach-Object { $_.Name })
    if ($extra.Count -gt 0) {
        foreach ($e in $extra) { Write-Bad "room root holds $e" }
        throw ("The room root holds $($extra.Count) thing(s) that are not a project or the engine. " +
               "Anything a run or a build leaves goes BESIDE the room, never in it: measured sessions " +
               "read whatever is there.")
    }
    Write-Ok 'room root holds only the projects and the engine junction'
}

function Get-DriftManifest {
    # Per admissible directory: file count, total bytes, newest write time. Cheap enough to run before
    # every run, which matters more than being exact - content hashes over 3 GB would be precise and
    # too slow to actually get used, and a check nobody runs detects nothing.
    $out = [ordered]@{}
    foreach ($p in $Projects) {
        foreach ($item in ($p.Copy + $p.Link)) {
            $rel = Join-Path $p.Name $item
            $src = Join-Path $TreeRoot $rel
            if (-not (Test-Path -LiteralPath $src)) { continue }
            $files = @(Get-ChildItem -LiteralPath $src -Recurse -File -Force -ErrorAction SilentlyContinue |
                Where-Object { $d = $_.DirectoryName; -not ($ExcludeDirs | Where-Object { $d -like "*\$_\*" -or $d -like "*\$_" }) })
            $newestUtc = ($files | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
            $out[$rel] = [ordered]@{
                files  = $files.Count
                bytes  = [int64](($files | Measure-Object -Property Length -Sum).Sum)
                # TICKS, not a DateTime. A DateTime written by ConvertTo-Json and read back by
                # ConvertFrom-Json comes home with a different Kind, so a UTC value is compared against
                # a local one and every directory looks stale by exactly the timezone offset. That is
                # what it did: eleven directories reported "newer content" with dates FIVE DAYS BEFORE
                # the build. An int64 has no timezone semantics to lose.
                newestTicks = if ($null -ne $newestUtc) { [int64]$newestUtc.Ticks } else { $null }
            }
        }
    }
    return $out
}

switch ($Mode) {

    'Status' {
        if (-not (Test-Path -LiteralPath $Root)) { Write-Host 'No room built.'; break }
        $n = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -notlike "*\UnrealEngine\*" }).Count
        Write-Host "Room: $Root"
        Write-Host "  $n files (excluding the engine junction)"
        Write-Host "  engine junction: $(Test-Path (Join-Path $Root 'UnrealEngine'))"
        if (Test-Path -LiteralPath $ManifestPath) {
            $m = Get-Content $ManifestPath -Raw | ConvertFrom-Json
            Write-Host "  built $($m.builtAt) from $($m.treeRoot)"
        }
    }

    'Build' {
        Assert-NoRunInProgress
        if (-not (Test-Path -LiteralPath $Root)) { $null = New-Item -ItemType Directory -Path $Root }

        foreach ($p in $Projects) {
            foreach ($item in $p.Copy) {
                $src = Join-Path $TreeRoot (Join-Path $p.Name $item)
                if (-not (Test-Path -LiteralPath $src)) { continue }
                Write-Step "copy    $($p.Name)\$item"
                Copy-Admissible $src (Join-Path $Root (Join-Path $p.Name $item))
            }
            foreach ($item in $p.Link) {
                $src = Join-Path $TreeRoot (Join-Path $p.Name $item)
                if (-not (Test-Path -LiteralPath $src)) { continue }
                Write-Step "link    $($p.Name)\$item"
                $r = Link-Tree $src (Join-Path $Root (Join-Path $p.Name $item))
                Write-Ok "$($p.Name)\$item - $($r.made) linked, $($r.kept) already present, $($r.total) total"
            }
            foreach ($u in @(Get-ChildItem -LiteralPath (Join-Path $TreeRoot $p.Name) -Filter '*.uproject' -File -ErrorAction SilentlyContinue)) {
                Copy-Item -LiteralPath $u.FullName -Destination (Join-Path $Root $p.Name) -Force
            }
        }

        New-EngineJunction
        Assert-NoLayerVocabulary

        # A room built by the first version has its manifest inside. It is rewritten beside the room
        # below, so the old one is only a leak now.
        if (Test-Path -LiteralPath $LegacyManifestPath) {
            Remove-Item -LiteralPath $LegacyManifestPath -Force
            Write-Ok 'removed the legacy in-room manifest'
        }
        Assert-RoomRootClean

        ([ordered]@{
            builtAt  = (Get-Date).ToString('o')
            treeRoot = $TreeRoot
            drift    = Get-DriftManifest
        }) | ConvertTo-Json -Depth 6 | Out-File -FilePath $ManifestPath -Encoding utf8

        Write-Ok "manifest written"
        Write-Host ''
        Write-Host "Room ready: $Root" -ForegroundColor Green
        Write-Host 'Run -Mode Verify before each measured run. A stale room measures a codebase that no longer exists,'
        Write-Host 'which is this design''s own failure mode and the price of not having leaks.'
    }

    'Verify' {
        if (-not (Test-Path -LiteralPath $ManifestPath)) {
            if (Test-Path -LiteralPath $LegacyManifestPath) {
                throw ("The manifest is still INSIDE the room ($LegacyManifestPath), where measured sessions " +
                       "read it. Run -Mode Build once: it moves the manifest beside the room.")
            }
            throw "No manifest at $ManifestPath. Build first."
        }
        Assert-RoomRootClean
        $stored = (Get-Content $ManifestPath -Raw | ConvertFrom-Json).drift
        $live = Get-DriftManifest
        $drifted = @()
        foreach ($k in $live.Keys) {
            $was = $stored.$k
            $now = $live[$k]
            if (-not $was) { $drifted += "$k (new since the build)"; continue }
            if ($was.files -ne $now.files -or $was.bytes -ne $now.bytes) {
                $drifted += "$k  files $($was.files)->$($now.files), bytes $($was.bytes)->$($now.bytes)"
            }
            elseif ($null -ne $was.newestTicks -and $null -ne $now.newestTicks -and
                    [int64]$was.newestTicks -lt [int64]$now.newestTicks) {
                # Integer comparison, for the reason given beside newestTicks above. Still guarded for
                # null because an EMPTY admissible directory has no newest write time at all - a
                # plugin with no Content folder is the usual case - and an unguarded cast fails Verify
                # on a room that is fine. A drift check that errors on a healthy room gets ignored.
                $when = [datetime]::new([int64]$now.newestTicks, [DateTimeKind]::Utc)
                $drifted += "$k  same size, newer content ($($when.ToString('u')))"
            }
        }
        if ($drifted.Count -gt 0) {
            foreach ($d in $drifted) { Write-Bad $d }
            throw "The room is STALE in $($drifted.Count) place(s). Rebuild before measuring."
        }
        Write-Ok 'room matches the tree'
    }
}
