<#
.SYNOPSIS
    Compares and syncs the files this repo shares with a working tree, in either direction.

.DESCRIPTION
    The plugin source, the benchmark tools and these scripts exist in two places: this repository,
    and whatever tree you actually develop and measure in. They're real copies rather than links, so
    they can drift, and this script is what stops that being a surprise.

    Check   Compares every shared path by hash and prints what differs. Writes nothing. This is the
            default, and it's what you run before a commit.
    Push    Copies this repository over the working tree.
    Pull    Copies the working tree over this repository. This is the common direction, because
            fixes usually get made in the tree that builds.

    Important: Push and Pull both refuse to run when the destination holds changes the source
    doesn't, unless you pass -Force. Without that guard, a Push after an afternoon of editing in the
    working tree throws the afternoon away and says nothing.

    CLAUDE.md and the rules files are deliberately not synced. They're tree specific, and a lesson
    about one project doesn't belong in a template verbatim, so those get reported and left to you.

.EXAMPLE
    .\Sync-Shared.ps1 -TreePath C:\Work\MyTree
    .\Sync-Shared.ps1 -TreePath C:\Work\MyTree -Mode Pull
#>
[CmdletBinding()]
param(
    # Root of the working tree to compare against.
    [Parameter(Mandatory)] [string] $TreePath,

    [ValidateSet('Check', 'Push', 'Pull')]
    [string] $Mode = 'Check',

    # Root of this repository. Resolved in the body rather than here: on Windows PowerShell 5.1
    # $PSScriptRoot is empty while parameter defaults are evaluated, and Join-Path then refuses the
    # empty string and kills the script before its first line. Found by running this on 5.1 for the
    # first time; it had only ever been run from pwsh 7.
    [string] $RepoPath,

    # Overwrite changes in the destination that the source doesn't have.
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

# Files a hash could not be taken of, because something holds them open. Reported at the end: a file
# silently missing from a comparison reads as identical, which is the one thing this script must not do.
$InUse = @()

# Pairs whose tree side is missing, so nothing about them was compared. Reported at the end, loudly.
$BadPairs = @()

if (-not $RepoPath) {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $RepoPath = Split-Path -Parent $here
}
$RepoPath = (Resolve-Path $RepoPath).Path
$TreePath = (Resolve-Path $TreePath).Path

# A benchmark run isolates the tree by moving whole directories out of it, so a tree mid-run looks
# exactly like one somebody deleted half of. Copying into it then restores files the run needs
# absent, and turns a baseline arm into a with-layers arm wearing the wrong label - silently, because
# nothing about it fails.
#
# The isolation script writes this marker at the tree root, and removes it on restore.
$lockMarker = Join-Path $TreePath 'BENCH-RUN-IN-PROGRESS.md'
if (Test-Path -LiteralPath $lockMarker) {
    Write-Host ""
    Write-Host "A benchmark run is holding $TreePath." -ForegroundColor Yellow
    Write-Host "  $lockMarker"
    Write-Host ""
    Write-Host "The tree is deliberately incomplete while that is there, so a comparison against it"
    Write-Host "reports files as missing that are only moved aside, and a Push would corrupt the run."
    if ($Mode -eq 'Check' -and -not $Force) {
        Write-Host "Refusing to compare. Pass -Force if you know the run has died and the marker is stale."
        exit 2
    }
    if (-not $Force) {
        Write-Host "Refusing to $($Mode.ToLower()). Wait for the run, or restore the tree first."
        exit 2
    }
    Write-Warning "Proceeding anyway because -Force was passed."
}

# Shared code. These should be byte identical in both places.
$Shared = @(
    @{ Repo = 'plugins\ue-memory-stack\ue-plugin\UEAgentAccelerator\Source'; Tree = 'Shared\UEAgentAccelerator\Source' }
    # Only the repository side moved, when the benchmark became a plugin's contents. The working
    # tree still keeps bench/ at its root, and pointing both sides at the same new path would have
    # compared the repository against a directory that does not exist there.
    @{ Repo = 'plugins\ue-memory-bench\bench\tools';   Tree = 'bench\tools' }
    # The tree keeps these in `tools`, not `scripts`. This pair named `scripts` for months, and since
    # that directory does not exist there, every file reported as "repo only" - including the one file
    # that IS shared, Update-MemoryStack.ps1, whose 674-line divergence nobody could see. Excluding the
    # two subdirectories that are not part of this pair: engine-api-db has a pair of its own below, and
    # archive is the tree's own graveyard of one-shots.
    #
    # Seven of the eight ARE repo-only and always will be: the tree drives its layers through its own
    # one-shots (rebuild2.ps1, rundump6.ps1) rather than through the plugin's scripts.
    @{ Repo = 'plugins\ue-memory-stack\scripts';          Tree = 'tools'
       Exclude = '^(engine-api-db|archive)(\\|$)' }
    # Layer 3. Curated on the public side: no phase numbering, no citations to unpublished
    # design documents, and - the part that matters - no hardcoded project list or Blueprint
    # totals, which would be this tree's numbers reported as somebody else's truth.
    @{ Repo = 'plugins\ue-memory-stack\engine-api';       Tree = 'tools\engine-api-db' }
)

# Files that differ on purpose and always will, with what to do after pulling one. The public copy
# of the exporter carries comment edits that remove project names, so it can never be byte identical
# to the working tree's copy. It still needs pulling when the working tree changes it; it just needs
# the edits re-applying afterwards. Without this note the row looks like ordinary drift.
$KnownDelta = @{
    'UEAgentAcceleratorUht\UEAgentAcceleratorUhtExporter.cs' =
        'public copy has project names and citations to unpublished phase documents removed from comments; re-apply after a pull. Names no console: every console platform name is replaced with "console" (tools/check_publication_scrub.py enforces it).'
    'UEAgentAcceleratorTools\Public\ModuleAvailabilityCommandlet.h' =
        'public copy drops a citation to an internal design doc; re-apply after a pull. Names no console: every console platform name is replaced with "console" (tools/check_publication_scrub.py enforces it).'
    'UEAgentAcceleratorTools\Public\BlueprintIndex.h' =
        'public copy drops a citation to the benchmark spec, which is not published; re-apply after a pull'
    'UEAgentAcceleratorTools\Private\AgentMemoryDumpCommandlet.cpp' =
        'public copy drops review-task ids and benchmark question ids, and points at scripts/ rather than tools/; some of that is inside emitted strings, so it reads as a code difference'
    'budget.py' =
        'public docstring names tiktoken generically instead of citing a measurement script that is not published; re-apply after a pull'
    'uncertainty.py' =
        'public _REBUILD hint says scripts/Update-MemoryStack.ps1 rather than tools/ - inside a string, so it reads as a code difference; re-apply after a pull'
    'UEAgentAcceleratorTools\Private\BlueprintIndex.cpp' =
        'public copy drops review-task ids, a benchmark question id and a token figure from comments, points the walk-coverage note at engine-api/ rather than tools/engine-api-db/, and generalises the sample and seed project names the detail-dump comments cite as evidence. Names no console in comments; the controller-label note it WRITES is generic in code in both copies, and a tree supplies console wording through InputLabelNoteFile in its Editor ini (tools/check_publication_scrub.py enforces the public side).'
}

# The .uplugin version is NOT a known delta - the two copies must MATCH. They drifted to 0.2.0 in the
# tree and 0.3.0 here from code identical apart from comment scrubbing, and because the dump writes it
# into MANIFEST.md as "Written by plugin", the two trees' artefacts then claimed two builds where
# there was one. Both are 0.4.0 as of 2026-09-20. If they ever differ again that is drift rather than
# a decision - bump both together.
#
# tools/check_publication_scrub.py gates the scrub described above. It shares no word list with the
# benchmark's isolation scan, and a file can pass either and fail the other, so run both.

# Curated: the public copy is a GENERALISED version of the tree's, not a stale one. These are never
# copied in either direction, whatever the timestamps say.
#
# Added 2026-09-11 after a near miss. $KnownDelta above compares code hashes and so only covers files
# whose *comments* differ; these seven differ in code on purpose - hardcoded paths replaced by
# parameters, this tree's project names replaced by a plugins/ue-memory-bench/bench/projects.json lookup, internal document
# citations replaced by published ones. baseline-isolation.ps1 is 289 lines here against 423 in the
# tree for exactly that reason.
#
# The mtime guard further down was the only thing standing between a Pull and losing all of it, and
# mtime is not load-bearing enough for the job: it already reports baseline-isolation.ps1 as
# "Newer: tree", so that one would have been overwritten without a warning. Hence a list by name.
$Curated = @{
    'baseline-isolation.ps1'   = 'parameterised: -Root, -Holding, -Config, -ExtraLayerPaths, no hardcoded tree path. ALSO 424 lines shorter: it has no root-entry classification, because that is wired to the unpublished leak gate. The docs point users at Build-BaselineRoot.ps1 instead and name the two manual habits that substitute'
    'score_answers.py'         = 'parameterised: UEAA_TREE / UEAA_CLAUDE / UEAA_BENCH_SETTINGS environment overrides'
    'check_keys.py'            = 'reads plugins/ue-memory-bench/bench/projects.json instead of a hardcoded project map'
    'extract_comments.py'      = 'projects discovered from the tree, or named with --projects; the tree copy hardcodes three project names'
    # uncertainty.py used to be listed here, for a fix of its own that has since been superseded by the
    # tree's: coverage now comes from the line the generator writes into the artefact, which is not
    # hardcoded anywhere, so the two copies are identical again and this one must SYNC. Left as a
    # comment rather than deleted, because an exemption that quietly stops applying is the failure.
    'build_api_db.py'          = 'drops the phase numbering; default root is the working directory rather than a position relative to this script, and it refuses a root with no project in it; report filename matches the .gitignore pattern. Names no console: every console platform name is replaced with "console" (tools/check_publication_scrub.py enforces it).'
    'mcp_server.py'            = 'drops the phase numbering; the build hint names a path that exists publicly. Names no console: every console platform name is replaced with "console" (tools/check_publication_scrub.py enforces it).'
    'build_descriptor_tier.py' = 'drops citations to the unpublished design document; reads the availability matrices where the commandlet writes them rather than from a staging directory; plugin identity key is relative to the root rather than split on a literal tree name'
    'make_questions.py'        = 'reads plugins/ue-memory-bench/bench/projects.json; cites plugins/ue-memory-bench/bench/METHOD.md, not the unpublished spec'
    'make_runset.py'           = 'generic question filenames and --questions/--handwritten arguments'
    'make_smoke.py'            = 'cites plugins/ue-memory-bench/bench/METHOD.md, not the unpublished spec'
    'measure_clangd_index.py'  = 'tier descriptions carry no counts from this particular tree'
    'sample_candidates.py'     = 'cites plugins/ue-memory-bench/bench/METHOD.md, not the unpublished spec'
    'measure_floor.py'         = 'no hardcoded interpreter or settings path: sys.executable, UEAA_CLAUDE, UEAA_BENCH_SETTINGS'
    'measure_schema_cost.py'   = 'takes --server and --results rather than this tree own server path and run filenames'
    'compare_arms.py'          = '--notes defaults to a "no notes supplied" block, not the tree''s v3 figures'
    'judge_reliability.py'     = 'defaults to scores.jsonl, the scorer''s own default, not a tree run tag'
    'route_split.py'           = 'takes --runset/--scores/--overlay/--corrections and fails with a sentence, not a traceback; LAYER_TERMS drops this tree''s own instruction filenames and tells the reader to add theirs, so the two copies bucket the same run slightly differently on purpose'
    'assess_new_questions.py'  = 'default results filename is the public one; leak vocabulary flagged as ours'
    'summarise_run.py'         = 'review-task ids dropped from comments'
    'Build-BaselineRoot.ps1'   = 'parameterised: -TreeRoot required, -Root derived, projects read from plugins/ue-memory-bench/bench/projects.json, $ScanExcludePaths added'
    # Newly visible, and it must never be copied: the tree's copy hardcodes an interpreter path under
    # a user profile, and the public copy is parameterised and takes no -Python at all. The two also
    # differ in structure - the public one runs Build then Reflection PER PROJECT, which is the
    # interleave the BuildId trap needs; the tree's runs each stage across all projects and instead
    # asserts engine-vs-project BuildId before each dump, which catches the case where a build in
    # another tree moved the shared engine. Port between them by hand, in whichever direction, and
    # keep both defences.
    'Update-MemoryStack.ps1'   = 'public copy is parameterised and has no hardcoded interpreter; the two differ in stage structure on purpose - public interleaves per project, the tree asserts BuildId before each dump'
    'run_bench.py'             = 'parameterised; --isolation room/--room; MCP surface from plugins/ue-memory-bench/bench/arms.json with a generic serena_gate. No leak gate, no touched log, no memory wipe - port those deliberately, never by Pull'
}

# Deliberately NOT published, with the reason. Checked by hand rather than by the drift table, because
# the table can only report what both trees have - a file that is absent on purpose looks identical to
# one nobody has got round to.
#
# These two are a pair and ship together or not at all: the room is built by one and PROVEN by the
# other, and the room without the gate is defence in depth presented as a control. The public
# run_bench.py is still the move-aside runner, so the gate has nothing to hook into yet.
$NotPublished = @{
    'leak_audit.py'          = 'reads the `touched` log, which the published run_bench.py does not record yet'
    'test_leak_gate.py'      = 'the control for that gate; nothing to test until the gate is ported'
    'verify_v3_additions.py' = 'verifies OUR answer keys against OUR database; nothing generic in it'
    # The Serena patches are NO LONGER published in any form, and these notes used to say "published
    # as ..." for each one. They are commits on the fork that the public installer installs, which is
    # what keeps GPL-derived files out of an MIT repository - see NOTICE.md. The tree's copies below
    # are the working originals; nothing in the repository corresponds to them any more, so there is
    # nothing to keep in step. What IS published is ours: the installer and layer1-state.json.
    'serena-accept-hardening.py'        = 'NOT published; the fix is serena/util/accept_hardening.py on the fork'
    'serena-csharp-skip-ignored.diff'   = 'NOT published; the fix is a commit on the fork (solidlsp, still MIT upstream)'
    'serena-find-symbol-indexed.py'     = 'NOT published; the tool is a commit on the fork, with three fixes this copy never had'
    'serena-freshness-skip-engine.diff' = 'NOT published; the fix is a commit on the fork'
    'test_accept_hardening.py'          = 'an A/B test of the accept fix against this machine; not reviewed for publication'
    'serena-find-symbol-scope-guard.diff' = 'NOT published; the fix is a commit on the fork, in serena/repl/api/lsp_api.py on 2.x'
}

# Related but not identical. Reported, never copied.
$Reported = @(
    @{ Repo = 'plugins\ue-memory-stack\templates\CLAUDE.md.template'; Tree = 'CLAUDE.md' }
    @{ Repo = 'plugins\ue-memory-stack\templates\rules';              Tree = '.claude\rules' }
)

function Get-FileMap([string] $Root, [string] $Exclude) {
    $map = @{}
    if (-not (Test-Path $Root)) { return $map }
    # A pair can name two single files with different names, CLAUDE.md.template against CLAUDE.md
    # for instance, so a leaf gets a fixed key. Otherwise the names never match and every compare
    # reports both sides as missing.
    if (Test-Path $Root -PathType Leaf) {
        $map['.'] = [pscustomobject]@{ Hash = (Get-FileHash $Root -Algorithm SHA256).Hash; Time = (Get-Item $Root).LastWriteTime; Path = $Root }
        return $map
    }
    Get-ChildItem $Root -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
        # Subdirectories that belong to another pair, or to one side only. Without this a nested
        # shared directory is compared twice under two group names and both reports look wrong.
        if ($Exclude -and $rel -match $Exclude) { return }
        # Build output and caches aren't shared, they're just whatever each side last did.
        if ($rel -match '(^|\\)(__pycache__|Binaries|Intermediate|Saved|\.cache)(\\|$)') { return }
        if ($rel -match '\.(pyc|log|err|obj|dll|pdb)$') { return }
        # Backups and move-aside copies belong to whoever made them on that side. Without this, a
        # .bak-<date> beside an edited file reports as "tree only" and a Push publishes somebody's
        # undo file. This tree's convention is <name>.bak-<yyyymmdd>; .prev-<runid> is what the
        # refresh script leaves when it moves artefacts aside.
        if ($rel -match '\.(bak|orig|rej)([.-][\w-]+)?$|\.prev-[\w-]+$|\.before-[\w-]+$') { return }
        # A file another process holds open cannot be hashed, and one of the shared directories now
        # holds a live SQLite database: -shm and -wal are locked whenever the engine-api server is
        # running. Killing the whole comparison over a generated file nobody syncs is the wrong
        # trade, so record it as in-use and carry on. Generated database files are skipped outright.
        if ($rel -match '\.(db|db-shm|db-wal|sqlite|sqlite3)$') { return }
        try {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
        }
        catch {
            $script:InUse += $rel
            return
        }
        $map[$rel] = [pscustomobject]@{ Hash = $hash; Time = $_.LastWriteTime; Path = $_.FullName }
    }
    return $map
}

# Hash of the file with comments and blank lines removed.
#
# A file carrying an intentional comment-only difference will always show as differing, which makes
# real drift in the same file invisible. Comparing the stripped form separates the two: same code
# with different comments is expected, different code is drift that needs pulling.
function Get-CodeHash([string] $Path) {
    $raw = Get-Content $Path -Raw
    if ($null -eq $raw) { $raw = '' }

    # Comment syntax is per language, and getting it wrong breaks this both ways. Stripping only
    # // missed a change inside a /* */ block and called it code. Stripping # as a comment in a C++
    # header threw away #include and #pragma, which are code, so a changed include would have been
    # reported as comment-only - the failure that actually matters.
    switch -Regex ([IO.Path]::GetExtension($Path)) {
        '\.(cs|cpp|h|hpp|c|inl|usf|ush)$' {
            $raw = [regex]::Replace($raw, '/\*.*?\*/', '', 'Singleline')
            $raw = [regex]::Replace($raw, '(?m)//.*$', '')
        }
        '\.ps1$' {
            $raw = [regex]::Replace($raw, '<#.*?#>', '', 'Singleline')
            $raw = [regex]::Replace($raw, '(?m)#.*$', '')
        }
        '\.py$' {
            $raw = [regex]::Replace($raw, '(?m)#.*$', '')
        }
        default {
            # Unknown language: compare the whole file. Better to report a comment change as drift
            # than to guess at syntax and hide a real one.
        }
    }

    $stripped = $raw -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
    $text = ($stripped -join "`n")
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-','')
    } finally { $sha.Dispose() }
}

function Compare-Pair($pair, [switch] $ReportOnly) {
    $repoRoot = Join-Path $RepoPath $pair.Repo
    $treeRoot = Join-Path $TreePath $pair.Tree

    # A pair whose tree side is not there compares against nothing and reports every file as "repo
    # only" - which reads as "the tree is missing all of this" and is indistinguishable from the truth.
    # That hid a real 674-line divergence in Update-MemoryStack.ps1, because this pair named a
    # `scripts` directory the tree does not have. Say so rather than producing a confident comparison
    # of one side against an empty set.
    if (-not (Test-Path -LiteralPath $treeRoot)) {
        Write-Host ""
        Write-Host "PAIR NOT COMPARED: $($pair.Repo)" -ForegroundColor Red
        Write-Host "  its tree side, $($pair.Tree), does not exist at $treeRoot."
        Write-Host "  Every file here would report as 'repo only', which is not the same claim as"
        Write-Host "  'the tree does not have it'. Fix the pair, or remove it."
        $script:BadPairs += $pair.Repo
        return @()
    }

    $repoMap  = Get-FileMap $repoRoot $pair.Exclude
    $treeMap  = Get-FileMap $treeRoot $pair.Exclude

    $rows = @()
    foreach ($rel in ($repoMap.Keys + $treeMap.Keys | Sort-Object -Unique)) {
        $inRepo = $repoMap.ContainsKey($rel)
        $inTree = $treeMap.ContainsKey($rel)
        $status =
            if     ($inRepo -and -not $inTree) { 'repo only' }
            elseif ($inTree -and -not $inRepo) { 'tree only' }
            elseif ($repoMap[$rel].Hash -eq $treeMap[$rel].Hash) { 'same' }
            else { 'differs' }

        # Which side is newer matters more than the fact that they differ: a Pull that overwrites
        # the newer side destroys work, and "differs" on its own does not tell you which way to go.
        $newer = ''
        if ($status -eq 'differs') {
            $newer = if ($repoMap[$rel].Time -gt $treeMap[$rel].Time) { 'repo' } else { 'tree' }

            # For a file with a known intentional comment difference, say whether the CODE differs
            # too. Otherwise "always differs" hides real drift in exactly the file most likely to
            # have some.
            foreach ($k in $KnownDelta.Keys) {
                if ($rel -like "*$k") {
                    if ((Get-CodeHash $repoMap[$rel].Path) -eq (Get-CodeHash $treeMap[$rel].Path)) {
                        $status = 'comments only'
                        $newer  = ''
                    } else {
                        $status = 'CODE differs'
                    }
                }
            }
        }

        $leaf = Split-Path -Leaf $rel
        # Both tables exclude a file from copying. Curated means the public copy is a generalised
        # version; NotPublished means there is no public copy and that is the decision. Without the
        # second one here, a Pull would quietly publish a file that was withheld on purpose.
        $isCurated = $Curated.ContainsKey($leaf) -or $NotPublished.ContainsKey($leaf)

        $rows += [pscustomobject]@{
            Group  = $pair.Repo
            File   = if ($rel -eq '.') { Split-Path -Leaf $pair.Repo } else { $rel }
            Rel    = $rel
            Status = $status
            Newer  = $newer
            Synced = (-not $ReportOnly) -and (-not $isCurated)
        }
    }
    return $rows
}

$all = @()
foreach ($p in $Shared)   { $all += Compare-Pair $p }
foreach ($p in $Reported) { $all += Compare-Pair $p -ReportOnly }

$drift = $all | Where-Object { $_.Status -ne 'same' }

if (-not $drift) {
    Write-Host "In sync. $($all.Count) files compared, no differences."
    if ($Mode -ne 'Check') { Write-Host "Nothing to $($Mode.ToLower())." }
    exit 0
}

Write-Host ""
Write-Host "Differences:"
$drift | Sort-Object Group, File | Format-Table Group, File, Status, Newer, Synced -AutoSize -Wrap

foreach ($row in $drift) {
    foreach ($k in $KnownDelta.Keys) {
        if ($row.File -like "*$k") {
            Write-Host ""
            Write-Host "Expected difference: $($row.File)" -ForegroundColor DarkYellow
            Write-Host "  $($KnownDelta[$k])"
        }
    }
}

foreach ($row in $drift) {
    $leaf = Split-Path -Leaf $row.File
    if ($NotPublished.ContainsKey($leaf)) {
        Write-Host ""
        Write-Host "Not published on purpose: $($row.File)" -ForegroundColor DarkGray
        Write-Host "  $($NotPublished[$leaf])"
        continue
    }
    if ($Curated.ContainsKey($leaf)) {
        Write-Host ""
        Write-Host "Curated, never copied: $($row.File)" -ForegroundColor DarkYellow
        Write-Host "  $($Curated[$leaf])"
        Write-Host "  Port changes into it by hand; do not Pull over it."
    }
}

$reportOnlyDrift = $drift | Where-Object { -not $_.Synced }
if ($reportOnlyDrift) {
    Write-Host "The rows with Synced False are the curated files. They're never copied, so if a"
    Write-Host "lesson landed in the working tree, port it into the template by hand."
}

if ($BadPairs) {
    Write-Host ""
    Write-Host ("PAIRS NOT COMPARED: " + ($BadPairs -join ', ')) -ForegroundColor Red
    Write-Host "Nothing above says anything about those, in either direction."
}

if ($InUse) {
    # Said out loud, because a file left out of the comparison reads exactly like a file that matched.
    Write-Host ""
    Write-Host ("Not compared, held open by another process: " + (($InUse | Sort-Object -Unique) -join ', ')) -ForegroundColor Yellow
    Write-Host "Nothing is known about those either way. Stop whatever holds them and re-run if they matter."
}

if ($Mode -eq 'Check') { exit 1 }

$syncable = $drift | Where-Object { $_.Synced }
if (-not $syncable) {
    Write-Host "Nothing to $($Mode.ToLower()): every difference is in a curated file."
    exit 0
}

# The guard. "tree only" during a Push, or "repo only" during a Pull, means the destination holds
# something the source doesn't, and copying over it destroys work.
$destinationOnly = if ($Mode -eq 'Push') { 'tree only' } else { 'repo only' }
$destinationSide = if ($Mode -eq 'Push') { 'tree' } else { 'repo' }
$atRisk = $syncable | Where-Object {
    $_.Status -eq $destinationOnly -or ($_.Status -eq 'differs' -and $_.Newer -eq $destinationSide)
}
if ($atRisk -and -not $Force) {
    Write-Host ""
    Write-Host "Refusing to $($Mode.ToLower()): $($atRisk.Count) file(s) on the destination side are newer,"
    Write-Host "or exist only there. Copying over them would throw that work away:"
    $atRisk | Sort-Object Group, File | ForEach-Object { Write-Host "  $($_.Group)\$($_.File)  [$($_.Status)]" }
    Write-Host ""
    Write-Host "Sync the ones you actually want by hand, or pass -Force if you are sure."
    exit 1
}

# Copy exactly the rows the report above marked Synced, one file at a time. This loop used to copy
# each pair's whole DIRECTORY with Copy-Item -Recurse, which ignored every decision made above it: the
# Curated and NotPublished tables, the __pycache__/backup/database exclusions in Get-FileMap, and the
# Synced column the report had just printed. A Pull overwrote the curated public copies with the
# tree's - the exact near miss the Curated table was added for - while the report said they were
# left alone. Copy-Item of a directory onto an existing directory also nests the source INSIDE it
# rather than over it. Found 2026-09-21 by reading the loop against the report, not by running it.
$copied = 0
foreach ($row in ($syncable | Sort-Object Group, File)) {
    # 'same' needs nothing; destination-only is a file the source lacks, and deleting it is not a
    # sync decision this script makes.
    if ($row.Status -eq 'same' -or $row.Status -eq $destinationOnly) { continue }

    $pair = $Shared | Where-Object { $_.Repo -eq $row.Group } | Select-Object -First 1
    if (-not $pair) { continue }   # a $Reported pair, never copied
    $repoFile = if ($row.Rel -eq '.') { Join-Path $RepoPath $pair.Repo } else { Join-Path (Join-Path $RepoPath $pair.Repo) $row.Rel }
    $treeFile = if ($row.Rel -eq '.') { Join-Path $TreePath $pair.Tree } else { Join-Path (Join-Path $TreePath $pair.Tree) $row.Rel }
    $src  = if ($Mode -eq 'Push') { $repoFile } else { $treeFile }
    $dest = if ($Mode -eq 'Push') { $treeFile } else { $repoFile }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dest -Force
    Write-Host "$($Mode.ToLower())ed $($row.Group)\$($row.File)  [$($row.Status)]"
    $copied++
}
Write-Host "$copied file(s) copied. Curated and not-published files were left alone, as reported."

Write-Host ""
Write-Host "Done. Run with -Mode Check to confirm."
