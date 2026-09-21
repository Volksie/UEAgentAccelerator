# Changelog

## 0.4.2

Fixes and a change of defaults. Nothing here changes an answer on the benchmark's trees, so v6 still
stands and the next measured run is still **v7**.

- **No console platform is named anywhere in the repository.** The docs say "console", and the two
  places that used a console name as an identifier now find consoles at run time. `tools/check_publication_scrub.py`
  fails on a console name in any file git would publish.
- **The ModuleAvailability commandlet's platform list is configuration.** `-Platforms=` first, then
  `+Platforms=` under `[/Script/UEAgentAcceleratorTools.ModuleAvailabilityCommandlet]` in the project's
  Editor ini, then a default of the public platforms plus the engine's confidential ones. That last part
  comes from `FDataDrivenPlatformInfoRegistry::GetConfidentialPlatforms()`, so a machine licensed for a
  console gets it without naming it and one that isn't gets nothing it isn't entitled to.
- **`-Platforms=a,b,c` resolved only `a`.** `FParse::Value` stops at the first comma by default, and
  nothing had ever passed a list, so it went unnoticed. Fixed.
- **The controller-label note in *Input.md* is generic unless you configure it.** `InputLabelNoteFile`
  under `[/Script/UEAgentAcceleratorTools.AgentMemoryDumpCommandlet]`, or `-InputLabelNote=`, names a
  file whose lines replace the note's bullets. A configured file that can't be read is an error, not a
  quiet fallback.
- **`engine_api_platform` no longer defaults to a console.** With no platform it lists every declared
  one, and "declared, never observed" is decided from the data rather than a list of names.
- **Layer 3 is opt-in, not experimental**, and its guide gains *Choosing platforms* and *Adding a
  platform*. It also says plainly that a misspelt platform name isn't rejected: the engine reads any
  module without a platform list as available on it.
- **`run_bench.py --resume` moves void rows out of the results file** instead of only skipping them,
  because the scorer counts every row and a left-behind refusal scored its question twice. One run
  writes a results file at a time, a fresh run refuses a file that already has rows, a file with two
  real rows for one question is copied back as `.DUPLICATE-IDS.jsonl`, and `--dry-run` no longer
  copies the previous run's results. `test_results_lock.py` covers it.

## 0.4.1: since v6

**v6 is measured and is the current result**, in *plugins/ue-memory-bench/bench/arm-comparison-v6.md*.
On the 139 questions it shares with v5, partial credit is **67.6% baseline against 92.1% with the
stack**, +24.5 points, where v5's own verdicts on the same 139 were +25.2: the gap is unchanged. On
the 52 new questions it is 63.5% against 92.3%. The two are reported separately because the new ones
were written for the baseline to fail, and the README says why no figure over all 191 appears. Eleven
answer keys were found wrong before publishing, by re-deriving every key the stack arm was marked
down on; *QUESTION-DEFECTS.md* has them.

**v5 is corrected too.** Six of those keys were wrong in v5 as well, because the facts behind them
didn't change between the runs, so v5 was re-judged on them from its recorded answers. Its headline
moves from 75.3% against 95.9% to **76.8% against 97.1%**, a gap of 20.3 where it was 20.6, and its
stack arm has no outright-wrong answers left. Under the corrected keys the 139 shared questions give
v5 +24.8 and v6 +26.6, so the gap holds at about 25 under either generation of keys.
*arm-comparison-v5.md* is regenerated with the correction at the top of its caveats and a pointer to
v6 at the foot.

The changes below came after the layers for that run were generated, so by this repository's rule
the next measured run is **v7**. None of them changes an answer.

- **The dump writes its artefacts with Windows line endings**, through one helper,
  `AgentMemoryFile::SaveStringToFileCRLF`, rather than twenty call sites. The first dump after this
  rewrites every artefact as the endings flip, which is a content-free change, but it does change
  every artefact's byte size.
- **The .uplugin declares `EnhancedInput`**, which the input tier has depended on since it landed.
  Project generation warned about it and is now warning-free.
- **The Serena launcher warms up on files the project would recognise, and has a `-Stop`**, because
  stopping the scheduled task never stopped the server it had started.
- **A depot reinstall clears the read-only attribute** Perforce puts on cached plugin files, which
  made the second install on a machine fail.
- **`run_bench.py --resume` no longer counts a refused row as done.** When an account hits its session
  limit mid-run, every remaining question is recorded in seconds with the platform's refusal as its
  answer, and nothing in the row says it's void. v6's first baseline attempt did exactly that. A resume
  now re-asks those rows, keeps a genuine timeout as a measurement, and prints any error row it can't
  classify rather than trusting it.

## 0.4.0: since v5, measured as v6

These change Layer 2's generator and Layer 3's query surface, so the next measured run was **v6**, and no v5 figure carries across.

**This section was written before the v6 run, and the counts below are artefact counts from a
development tree, not results.** The v6 result is in the section above. The comparison sentence
this section asked for is the one the result makes: **the question set itself changed** for v6 — a
new group was added and two groups were partly replaced — so a v6 score is not a v5 score on harder
code, it is a different examination, and only the 139 shared questions sit beside v5.

**The v5 documents describe the v5 run and nothing later.** They were regenerated once, on
2026-09-21, for the six corrected keys and the pointer to v6, and their text was not brought up to
the current stack. They describe a tree that no longer exists and a set that no longer applies, and
rewriting them to match would destroy the only record of what was actually measured.

### What one Blueprint is, which the stack could not say at all

The dump described Blueprints from the outside: parent, interfaces, replicated count, component
counts. It could not say what a Blueprint *contains*. For a **data-only** Blueprint — no graph, the
asset is its defaults — the stack said "data only: true" and stopped, which is the whole content of
the asset withheld. On Epic's sample game that is over a hundred and fifty assets described by one
boolean.

`bp/<stem>.md` now carries, per Blueprint: **what it changed from its parent** (class defaults,
component templates, inherited-component overrides and components built in a C++ constructor — four
different storage locations, kept apart because a query that merges them cannot answer "what does
this *class* default to" separately from "what does this *component* default to"), the variables it
declares with types rendered by the editor's own schema, the component and widget tree including
inherited ones with where they come from, tick as four separate facts, functions with signatures,
events with their net flags, dispatchers, timelines, interfaces, the Blueprints it calls into, and
what loading it drags in.

**A Blueprint that REPLACES a native component's class is diffed too, not just reported as
swapped.** The walk over components built in a C++ constructor required both sides to be the same
class, so a Blueprint that swapped one got a single row saying the class had changed and not one of
the new component's values. Every layer then answered questions about that component from the
**parent**: a character that swaps its movement component and retunes six speeds on it reported the
parent's speeds, confidently, with nothing marking the answer as unreliable. The diff now runs over
the properties the two classes share, which is also the only safe property list — iterating the new
class's properties over the parent template's memory reads past the end of that object.

Two details decide whether such a diff tells the truth. It is compared against the **parent's
template**, not the new class's defaults: a replaced subobject's archetype is its own class's CDO,
so everything the parent's constructor already set is serialised into the asset and looks changed.
On the sample game's one case that distinction is the difference between ten real rows and fourteen,
four of which never changed. And the class-level row is kept, because it is the only row that names
what the component now is.

**The store carries the fourth tick fact, and reaches Blueprint components.** The dump has written
`tick_node_disabled` since the wired fix, but `v_bp_tick_cost` exposed only three columns, so a
Blueprint with a **linked but switched-off** tick node was the same row as one with no tick node at
all — the exact case the field was added for. The view now carries it, with its own verdict.

The filter mattered as much as the column. `WHERE can_ever_tick IS NOT NULL` looks like a
null-safety guard and is actually a **content** filter: a Blueprint **component** has no
`PrimaryActorTick`, so its `can_ever_tick` is null, and a component can hold a disabled tick node
perfectly well. On one sample game that filter returned 9 where the artefacts said 11, both missing
rows being components — a documented route quietly disagreeing with the data underneath it, which is
worse than either being wrong alone, because both look right in isolation.

**A Blueprint whose parent class no longer resolves is stored as `unknown`, not as an empty string.**
An empty string is a value: it counts as a parent under `COUNT(DISTINCT native_parent)`, and a
closure query over it can never match, which reads as *no Blueprint derives from X*. `unknown` is the
word the generated index already used, so the two now agree.

**Blueprint-to-Blueprint edges get their own reverse index, `bpusers/`, and are kept out of
`bpcallers/`.** A call into another Blueprint's function is invisible to every compile-time tool for
the same reason a call into C++ is — but `bpcallers/` means *C++ symbols used by Blueprints*, and
blast-radius counts depend on that meaning. Mixing a new edge kind into it would silently change
what a row count means rather than fail.

### The asset registry, and the one tier that loads

`Assets.md` and `assets/<Class>.md` describe every asset from registry tags with **nothing
loaded** — a DataTable's row struct, a StateTree's schema — which is what makes it affordable at
scale. It covers **enabled content only**, states that in the file, and names any disabled plugins
it therefore could not see: a disabled plugin never mounts and the registry holds nothing for it, so
absence there means "not in enabled content", not "not on disk".

`Input.md`, `input/` and `inputkeys/` are the deliberate exception. A key binding lives in no
registry tag, so before this the layers could say an `InputMappingContext` existed and nothing
else — not what any key does, not whether a key drives two actions, not whether one context
re-binds a key another already bound. There are few enough contexts that loading them costs
nothing. `inputkeys/<Key>.md` is the reverse index, so "what is on this button" is one read.

**A controller label is not a key, and the files say so.** A person says "the cross button"; the
asset stores `Gamepad_FaceButton_Bottom`. That translation is per label set, lives in the engine,
and has two traps: a newer console can have **no label set of its own**, so it uses its predecessor's,
and a row claiming a label set for it would be inventing one; and **"Gamepad X" resolves to two
different keys** depending on which console's labels it is read under. Layer 3 carries the translation table and a
view holding that one ambiguity.

### The data sidecars, and why Layer 3 stopped parsing documents

The store used to re-parse the formatted Markdown to get its Blueprint edges, which its own code
called out as fragile: a second parse of a document meant for reading breaks silently when the
layout moves. The commandlet now builds one model and writes it **twice** — once as Markdown, once
as JSON — from the same loop, so the document and the data cannot disagree about what a row is.
Layer 3 reads the JSON. The Markdown path is kept as a fallback for artefact sets written before the
sidecars existed, and the loader logs which route each project took, because a silent switch is how
a reader ends up unable to tell an empty table from a missing file.

Verified by row-for-row comparison across both routes rather than by matching totals: a swap that
loses one row and gains another passes a count and fails a set comparison.

### Two corrections to what the dump reported

**A wired Event Tick was counted from the link, not from whether the node compiles.** A *disabled*
node is linked and never compiled, so Blueprints were reported as having a live tick that does
nothing — including some that claimed a tick on a class the Kismet compiler says cannot tick, a
state the compiler cannot produce. Reported by review against the engine's own compiler source. The
field now means **linked and enabled**, and a separate field records that a disabled tick node
exists, because "there is a tick node and it is switched off" is what a performance pass wants to
know.

**The asset tier was not deterministic.** Assets were sorted by package name alone, which is not a
total order — a single package can hold several registry assets, and Unreal's sort is not stable, so
those permuted between runs. Sorted on package *and* asset name now. The same wrong assumption —
that one package holds one asset — had already cost a silently collapsed row elsewhere.

### Coverage is stated rather than implied

`MANIFEST.md` gains a table naming which tiers a set contains, read off the disk rather than off the
code's intentions. **Every tier is emitted even when empty**, and that is load-bearing: a tier that
writes nothing when it has nothing is indistinguishable from a tier that does not exist. A count of
**0** means the walk ran and found none; **not in this set** means the artefacts predate that tier.
Those need different actions.

**The artefact format number does not move.** The rule is that it bumps when a change makes an older
set *wrong* rather than merely smaller. Everything here is a new file or a column appended at the
end; nothing stopped being written, and `bpcallers/` is byte-identical throughout. An older set is
smaller, not wrong — which is a coverage question, and coverage is what the manifest table answers.

### A publication gate

`tools/check_publication_scrub.py` refuses to publish plugin source that still names the private
tree it was written in — internal review ids, question numbers, paths that exist only there. The
rule was already written down in prose in the sync script; this makes it fail. It found two defects
in already-published source on its first clean run, one of them a user-facing string telling people
to run a script at a path that does not exist in an install.

**Both plugins are 0.4.0**, and so is the Unreal plugin descriptor. The version is the cache key, so
a content change under an unchanged version reaches nobody — and the two had drifted apart, which
mattered because the dump writes the descriptor version into every manifest it produces.

**The v5 benchmark result is published**, in *plugins/ue-memory-bench/bench/arm-comparison-v5.md*, and it is now the current one: 75.3% against **95.9%** with partial credit, **+20.6 points**, 24 outright wrong answers down to 2, and 2,326 turns against 1,417. Read its first screen before quoting any of it — three things there matter more than the headline. **One answer key was wrong and the figures are the rescored ones:** a question asked how many Blueprints call a function, the key gave the artefact's *row* count, and the stack arm was marked down for answering correctly in nine judging passes across three runs. **The cost gap widened mostly because the baseline arm got more expensive** — 97,294 input tokens a question in v3, 161,479 in v4, 180,563 here, on an unchanged set in an unchanged room — so the widening is not a gain for the stack. And **Layer 1 as measured was a Serena 2.x fork, not the 1.7.0 patch set this repository ships**, which is a licensing decision before an engineering one.

**The Blueprint walk stops claiming absences it cannot prove.** Three gaps, all of them cases where `bpcallers/` said "no Blueprint users" about a class that had them:

- **`BindWidget` bindings are edges.** A `UPROPERTY(meta=(BindWidget))` is bound *by name* to the widget of that name in a Widget Blueprint's designer tree. The widget compiler enforces it, renaming the C++ property breaks the Blueprint, and no graph node records it — so a resolved graph walk saw nothing. On Epic's sample game, 11 of the 88 Blueprints that produced no graph edge are widgets whose only contact with C++ is this binding. They now emit `bind` edges, attributed to the class that declares the property.
- **Macro graphs are walked.** A macro is expanded into its callers at compile time, so the caller's graphs hold only the instance node and the real call lives in `MacroGraphs`. Macro libraries therefore produced no edges at all.
- **The walk states its own coverage.** `BlueprintCallers.md` gains one fixed line: how many Blueprints there are, how many are data-only, how many were walked, how many produced edges. A data-only Blueprint has no graphs by construction and cannot produce an edge, so it is not a gap — counting it as one made coverage read as 54% on a large project and every true negative look weak.

**This changes artefact counts, which changes answer keys.** A question whose answer is a call-node count has a different right answer on artefacts generated after this. That is not a defect in either set, and it is why `answer-key-corrections.json` entries are scoped by run tag: a tag with no entry gets no correction rather than inheriting another run's number. *QUESTION-DEFECTS.md* works two examples through, one of them the v5 rescore above. The artefact format number does **not** move: the rule in *artefact-format.json* is that it bumps when a change makes an older set wrong rather than merely smaller, and an added row and an added line are smaller.

**The engine API store answers its own schema, and the questions that cost the most turns get a view each.** `engine_api_sql` with `query='schema'` returns every table and view with its columns plus the enumerations a query needs — edge kinds, loading phases, platforms, target types — in one call instead of the multi-call poke the benchmark measured. Five named views cover the recurring shapes: most-called symbol, Blueprint writes to C++ properties with the owning module, plugins with modules unavailable per platform, modules by loading phase, and what the search index holds. A view is a query, not a copy; the file does not grow.

**Three defects in the published Layer 3 builders, all of the same kind: code that was only true of the tree it was written in.** The default tree root was derived from the script's own position, which is right two directories below a tree and wrong inside a plugin install — it would have scanned `plugins/` and written an empty store while reporting success, so both builders now default to the working directory and **refuse a root with no project in it**. The availability matrices were read from a staging directory that only exists in the development tree, while the commandlet writes them to `<Project>/Docs/AgentMemory/`; the published copy looked where nothing writes and told you to run a commandlet you had already run. And the plugin identity key was built by splitting descriptor paths on the author's tree name, which left it absolute anywhere else.

**The scorer can correct a wrong answer key without invalidating a recorded run.** `answer-key-corrections.json` overrides the key at scoring time, never the measurement: the recorded answer stands and only what it is judged against changes. It ships empty, because ids belong to the set they came from and applying one set's correction to another is the defect rather than the fix.

**Layer 1 switched to the Serena 2.x fork, and this repository stopped shipping Serena code at all.** The five fixes used to be here as diffs and loose files, applied to an installed Serena — and every `uv tool upgrade serena-agent` reverted all of them without saying so. They are commits on a fork now, so they arrive with the install and survive it. `/ue-memory-stack:serena-patches` becomes **`/ue-memory-stack:serena-setup`**, and *plugins/ue-memory-stack/serena/Install-SerenaForUE.ps1* installs the branch, checks each fix in the installed files by a sentinel string, derives the context variant, and restarts the server.

**It is also a licensing fix, and that is the part that decided the shape.** Serena is licensed per component: `solidlsp` under MIT, the application under **GPL-3.0-or-later from v2 onward**, with v1.7.0 (`mit-final`) the last MIT release. A diff carries the lines it changes, so patches against 2.x would put GPL-derived files inside this MIT repository and hand every redistributor an obligation nobody told them about. So `find_symbol_indexed.py`, three diffs, the `sitecustomize.py` shim carrying a CPython method, both licence texts and the modified context are **gone**. What is left is ours: an installer and `layer1-state.json`. The context variant is now **derived on your machine** from the stock context your own install provides, so you end up with your file minus one line and nothing was distributed to you. *NOTICE.md* states it in full.

**The fork carries more than the patch set did.** `find_symbol_indexed` gained three fixes the 1.7.0 copy never had — it never returns a bare empty list, one failing language server cannot sink the whole call, and the default language is cpp — and the `is_ignored_path` performance fix on it has landed **upstream**, which is the argument for the fork over a pinned 1.7.0: the patches stop being carried forever. **No measured benefit is claimed.** The v5 run changed Serena and Layer 3 together, so nothing in it isolates the version; the defensible claim is that the switch cost nothing.

**Two of the five moved between versions, and one lied about it.** The `find_symbol` scope guard now lives in `serena/repl/api/lsp_api.py` rather than `serena/tools/symbol_tools.py`, and the accept-loop hardening is `serena/util/accept_hardening.py` called from `cli.py` rather than a shim. Worse, the C# fix reworded its log line: checked with the old sentinel, **a working fix reported as absent**. The sentinels are re-derived against 2.x, and the doctor now says to re-derive them by grepping the install rather than trusting the file.

**The health check stopped reading the version from the first match.** More than one `serena_agent-*.dist-info` can sit in one `site-packages`, and on the machine this was written on the real one holds 2.0.0.dev0 while a packaged app's private copy holds 1.7.0 — a shell inside that app lists **both** at the same absolute path, so `-First 1` reported a build that is serving nothing. It now reads every one, says when there is more than one, and points at `direct_url.json` for which is real.


## 0.2.0: setup, a doctor, hooks and a migration

These changed Layer 1 and the harness, so v5 was measured after them rather than with them, and no v4 figure carries across to it.

**A template written into `.claude/rules/` was being read as fact.** Setup stripped the `.template` suffix, so `Module.md.template` landed as `Module.md` - and that directory is auto-loaded into every session as project instructions. A session on a real tree read "`<Property>` replicates `COND_OwnerOnly` with `OnRep_<Property>`" out of the placeholder text, with exactly the authority of the hand-written file beside it, on a module where the true answer was that nothing replicates at all. A true statement and an invented one, no way to tell them apart. That is this stack's own failure mode arriving through the tool built to prevent it.

The suffix is kept on arrival now. An unfilled template is inert, and filling it in means renaming it. Either name counts as present, so a template is not written back over a deliberate deletion - which is how the file kept reappearing after somebody removed it. Verified on a scratch tree across three runs: fresh writes `*.md.template`, a re-run leaves them, and a filled-in `Module.md` with its template deleted stays deleted.

**The install record is per project, and on a multi-project tree it was describing only one of them.** `.claude/.uea-install.json` was a single flat object at the tree root, written by `Initialize-AgentMemoryProject.ps1` - which runs **per project**. On a three-project tree each run overwrote the last, so the file ended up describing whichever project ran last. The other two then read that record, found a version that matched, and reported themselves already set up. The check that exists to catch a stale plugin copy was answering about a different project, and `doctor` reported `UNKNOWN` for all three while looking at one. Found on a live three-project tree, where setup reported "nothing to do" for two projects it had never actually examined.

It is now `{ version: 2, projects: { <name>: {...} } }`, merged rather than replaced on each run, and both the writer and `Test-MemoryStackHealth.ps1` read the entry for the project in hand. A flat record from before this change still counts, but **only for the project it names** - reading it for any other would report a version that copy never came from, which is worse than reporting nothing - and it is carried forward under that name on the next write rather than dropped. `doctor` now distinguishes "no record at all" from "no entry for this project", because those have different remedies. Verified on the same tree: three separate entries, the legacy record migrated with its own version intact, and the three `plugin version` rows moved from `UNKNOWN` to `OK`.

**The dump stamps the artefact format, so "are these from before that change" has an answer.** `MANIFEST.md` gains two rows - the artefact format, a number the commandlet owns, and the plugin version that wrote the set - and `/ue-memory-stack:doctor` compares the format against what the installed plugin expects. A set written before this carries no format row, which is how it is recognised. This closes the oldest unmet claim in the design: the risk table had promised a stamped and checked format from the first draft, and until now the health check reported it as UNKNOWN rather than passing it. The number lives in three places that must agree - the C++ constant, `artefact-format.json` for the PowerShell side, and the row in the file - so `tools/check_artefact_format.py` fails the repository when they drift.

**`$PSScriptRoot` in a parameter default, for the fourth time, now with a gate.** `Build-UEAgentAccelerator.ps1` derived `-PluginSource` that way and died before its first line on Windows PowerShell 5.1 - which means it had never been run on 5.1. `tools/check_ps_script_root.py` fails any shipped script that does it, because four occurrences is a missing check rather than bad luck.

**Setup, a doctor, two hooks, a benchmark plugin and a migration.** Phases 3 to 7, and the plugins are **0.2.0**.

- **`/ue-memory-stack:setup`** writes a project's own half of the stack - the C++ plugin, the stack config filled in from what it found, the routing table from the template, the per-module rules - and writes each thing only when it is absent. A second run changes nothing. The exception is deliberate: a C++ plugin copy left behind by a plugin update is replaced, because the old source builds and dumps happily in the old format, and that is the quietest failure here. An edited copy is reported and kept unless `-Force`.
- **`/ue-memory-stack:doctor`** checks the layers that fail silently, and reports four verdicts rather than two: OK, WARN, FAIL, and **UNKNOWN meaning not checked**, counted separately. Thirteen failure modes are detected against a deliberately broken fixture, including a plugin enabled but not installed, a DLL older than its source, an index with no class files, a compile database pointing at response files that are gone, and a Serena an upgrade has quietly unpatched.
- **Two hooks**, priced before shipping: a session-start warning that prints nothing when the stack is healthy, and a guard that refuses hand-edits of generated artefacts **through the shell as well as through the edit tools**. Hooks add no always-on tokens; the cost is ~220ms per matching call, and the guard's first version matched `Write|Edit` only, which a session editing with `sed` walked straight through. `tools/Test-WriteGuard.ps1` is 24 cases, positives and negatives.
- **The benchmark is its own plugin**, `ue-memory-bench`: the harness, the method notes and the recorded results, with two commands and a skill, ~183 always-on tokens that only somebody measuring pays.
- **An eval suite**, four cases, run with `claude plugin eval`. It scores 1.00 with the plugin - and three of the four also score 1.00 without it, because a four-file fixture has no wrong route to take. A green suite there means "nothing regressed", not "the layers help".
- **A depot route** for teams with no GitHub access, and a **migration** for trees installed the old way: *plugins/ue-memory-stack/docs/09-installing-from-a-depot.md* and *11-migrating.md*. Install, update and rollback are exercised end to end, and an existing hand-written *CLAUDE.md* survives a migration byte for byte.

**Two things about Claude Code that cost a phase each to learn, and both are now documented.** A plugin that only a project's `.claude/settings.json` enables **does not install** - trusting the folder adds the marketplace and nothing else, and the commands are simply absent with no error. And a session loads a plugin from a **cached copy keyed by version**, so editing a directory marketplace without bumping the version reaches nobody while `claude plugin update` reports you are already up to date.

**The stack now ships as the plugin, and the clone route is gone.** Phase 2: `scripts/`, the C++ plugin (as `ue-plugin/`), the Serena patches, the templates and every guide moved into *plugins/ue-memory-stack/*, which also gains three commands (`update`, `status`, `serena-patches`) and three skills (`ue-memory-layers`, `ue-memory-refresh`, `ue-memory-setup`). Installing it is `claude plugin marketplace add` and `claude plugin install`; the scripts address themselves as `${CLAUDE_PLUGIN_ROOT}/scripts/...`, and the config loader no longer hunts for a checkout because there is not one. Measured on install: six components, **~482 always-on tokens** a session. `tools/Sync-Shared.ps1` stays in the repository, because keeping two trees in step is maintainer work and not something a user should be shipped.

**This repository is now a Claude Code marketplace**, offering `ue-memory-stack` and `ue-memory-bench`. Phase 1 of *docs/DESIGN-plugin-packaging.md*: manifests only, no behaviour, nothing moved. Both validate under `claude plugin validate --strict`, both install from a directory marketplace, and both cost nothing per session because they are empty. The design doc has the full plan, including how a team distributes this through Perforce without anyone cloning the repository.

**The two-tree sync ignores backups.** A `<name>.bak-<date>` beside an edited file used to report as "tree only", which meant a Push would publish somebody's undo file. Move-aside copies (`.prev-`, `.before-`) go the same way.

**The benchmark tools find the tree the same way.** All seven derived it as two directories above themselves. That is right until something moves, and then the path still resolves, every path built on it is wrong by a level, and what you see is a missing runset or an empty results file rather than the cause. New *plugins/ue-memory-bench/bench/tools/_tree_root.py* searches upwards for `plugins/ue-memory-bench/bench/projects.json`, warns loudly and falls back to the old behaviour when there is nothing to find, and still lets `UEAA_TREE` override both. Checked against the old answer on a normal checkout (identical for all seven) and on tools moved a level deeper, where counting gives `<tree>/bench` and searching gives `<tree>`.

**The config loader finds the tree root instead of assuming its own depth.** It derived the root two levels above itself and kept that in a parameter default, so keeping the loader anywhere but `.claude/scripts` put the root out by one level — and the error then said the configuration was missing and that the sync had not brought it down, when the file was there all along. It searches upwards for `.claude/agent-memory-stack.json` now, takes the root from `-ConfigPath` when given one, and when it finds nothing it says what it searched and which two arguments override it. Tested from two locations, on both PowerShell 5.1 and 7, plus each override and the two failure messages.

Also out of a parameter default, for the reason the Serena installer could not run on 5.1 at all: `$PSScriptRoot` is empty there when some scripts' defaults are evaluated. The loader's own directory is captured once, at dot-source time.

**`Update-MemoryStack.ps1` takes `-StackConfig`**, so a tree's facts can live in one file instead of four repeated arguments. It fills the project list, each project's artefact directory, the compile database directory and the engine path from *.claude/agent-memory-stack.json*; anything passed explicitly still wins, and a project whose *.uproject* is not where the file says stops the run rather than failing forty minutes into a build. The install steps, the refresh page, the Serena page and both command templates now use it. The point is that the setup half of a stack needs the same project list as the refresh half, and when it is written out twice the copies disagree silently.

**A per-tree config file, because the wrapper scripts had already duplicated themselves.** New *plugins/ue-memory-stack/templates/agent-memory-stack.json.template* and *plugins/ue-memory-stack/templates/scripts/AgentMemoryStack.Config.ps1*. Wrapping the accelerator on a three-project tree produced two scripts - one that sets Layer 1 up, one that refreshes Layers 0 and 2 - and within a day the project list existed twice, the compile database directory seven times, and the accelerator search path twice. Nothing checked they agreed. The failure that arrangement produces is the usual one here: a project added to the refresh script but not to Serena's `ls_workspace_folders` is not an error, it is a project regenerated for ever that no symbol query can see. The loader validates on load, so a project whose `.uproject` does not exist is reported at the top of a run rather than forty minutes into a build. Two things stay out of the file on purpose: the depot paths, derived from the source and artefact paths rather than stored again, and the accelerator clone, which lives outside the tree and would be right for whoever committed it and wrong for everyone else.

**Slash commands and a skill, so the stack is driven from the agent rather than from memory.** New *plugins/ue-memory-stack/commands/* and *plugins/ue-memory-stack/commands/update.md*, and *plugins/ue-memory-stack/skills/*. Everything they carry was already written down somewhere in *docs/*; the point is that a doc is only read by someone who already suspects there is something to read, and every failure in this stack looks like success, so nobody suspects. The commands put the traps at the moment of the action: check before you pay for a run, build every project you dump, spell `-OutDir` out, and do not read `find_symbol_indexed` returning `[]` as a failure.

**A freshness check that is actually sound, in *06-keeping-it-fresh.md*.** That document said you cannot check freshness automatically, on the grounds that both git and Perforce stamp what they write with the time they wrote it. That is right about *timestamps* and wrong as a conclusion: comparing **revisions** works, because a revision is a server fact a sync cannot forge. `p4 changes -m1 <source>#have` against the same for the artefact folder answers it, plus `p4 opened` for the uncommitted edits no revision comparison can see. The old paragraph stands as the reason the obvious version fails. The compile database keeps using timestamps, and that is sound precisely because it is ignored by source control and therefore never synced.

**The Serena patch installer ships here now**, as `Install-SerenaUEPatches.ps1` under the plugin's *serena/* directory (removed in 0.3.0, when the patches became commits on a fork), instead of being steps in *plugins/ue-memory-stack/serena/README.md* that each site retyped. It applies the three diffs, *sitecustomize.py* and `find_symbol_indexed`, installs the context, points a scheduled task at it, and skips anything already applied so re-running after `uv tool upgrade` is the normal use. It **refuses to run inside a packaged agent app**, by walking the process ancestry rather than reading `%APPDATA%` — inside that container the variable still reads as the ordinary path and only writes are redirected, so a string test on it passes and the patches go to the private copy anyway. That is the failure that cost us a day and the reason the check is a refusal rather than a warning.

**Serena refuses an unscoped `find_symbol`.** New `find-symbol-scope-guard.diff` (removed in 0.3.0; the fix is a commit on the fork now, in `serena/repl/api/lsp_api.py`). The client's timeout bounds the reply, not the work. On our tree an unscoped call that timed out at 45s kept walking the engine on the server for four hours, and crashed clangd twice on a third-party file. The guard refuses an empty `relative_path`, and any directory holding more than 1,000 source files, before any work starts. It was checked on the live server in both directions, and the diff was proven to apply to a pristine Serena 1.7.0 and to one with `find_symbol_indexed` already added.

**Three more engine ThirdParty trees in the *05* `ignored_paths` example**, for platform extensions, engine plugins and `Extras/ThirdPartyNotUE`. Each was confirmed with Serena's own `is_ignored_path` against real files.

**The runner watches clangd per question.** If the clangd process changes during a question, the record says so, the runner waits for the index again before the next question, and the run stops if the index doesn't come back. A replacement clangd answers `find_symbol_indexed` with an empty list for minutes. This path compiles and lists the live process, but hasn't been exercised by a real clangd death.

## Unreleased: v4

**The v4 benchmark result is published**, in *plugins/ue-memory-bench/bench/arm-comparison-v4.md*: 74.4% against **93.2%** with partial credit, **+18.8 points**, and 24 outright wrong answers down to 2. The stack arm took 1,442 turns to the baseline's 2,251 and 20.7M input tokens to 27.5M. **The token figure needs its caveat:** the baseline arm got much heavier between v3 and v4 on the same CLI, model, room and questions. How is measured: its sessions reached for the shell more and took smaller steps. Why isn't proven.

**v4 is v3 with Layer 1 working, and Layer 1 hadn't been.** Every Serena symbolic call walked the whole tree before doing anything, 189s on ours. Epic's `.gitignore` overrode the project's excluded paths. The stock context removed `search_for_pattern`, which the routing table named in five places. None of it raised an error. New *plugins/ue-memory-stack/serena/* has the fixes: two patches, a new `find_symbol_indexed` tool that answers "where is X defined" from clangd's index in about 0.1s, a context variant, and a Windows fix for a CPython bug that stops the HTTP listener accepting connections while the process looks healthy. It also has the check that matters most: confirm from **outside** your agent that a patch is live. We wrote and checked every patch from inside a packaged app whose shell sees a redirected `%APPDATA%`, and none of them had loaded. Each file carries the licence notice it needs, Serena's MIT or the PSF's for the CPython method; see *NOTICE.md*.

**Published figures corrected:**

- **v3 was +17.3 points, not +16.8.** Two answer keys were wrong, and the stack arm had answered one of them exactly right and been scored wrong. *plugins/ue-memory-bench/bench/arm-comparison-v3.md* carries the corrected table and a marked addendum.
- **The v3 diagnosis that groups J and F failed on tree-wide aggregate questions is withdrawn** from the README, *01-concepts.md*, *04-writing-your-claude-md.md* and the v3 document. Most of F's questions are about a single class, and J's aggregates already went to the database.
- **"Unscoped `find_symbol` times out at 300s, scoped 0s"** was measured with the file walk in place. Re-measured without it: scoped 0.01–12s, and unscoped still times out. The routing template, *04*, *05* and troubleshooting are corrected.
- **The *05* configuration example set `ignore_all_files_in_gitignore: true`** a few screens above the section explaining why it should be `false`.
- **v3's baseline could read the run's own manifest and lock file**, 49 and 60 sessions of 170. v4's could too, 25 and 50. Both results say so. The public room builder had already stopped writing the manifest into the room, and now refuses a room whose root holds anything but the projects and the engine.

**The harness now defines each arm's tool surface instead of inheriting yours.** New *plugins/ue-memory-bench/bench/arms.json*, passed with `--strict-mcp-config`. Before it, the runner inherited every MCP server in `~/.claude.json`, which put a language server into an arm defined as having nothing we built. The runner also:

- starts every stdio MCP server after isolation and requires a tool list, because a missing server just removes tools;
- waits for Serena to answer and for clangd's index to resolve a known class, because `find_symbol_indexed` answers `[]` in 0.1s until it has;
- captures tool errors;
- keeps a timed-out question's partial record instead of writing 0 calls.

Tested offline with a fake CLI and a fake MCP server in both directions, and the index gate live against a running server.

**`compare_arms.py --notes`** takes the caveat block from a per-run file. Without one it says no notes were supplied, instead of printing another run's judge agreement.

**Design documents for the seed project**: combat and health, character startup, and module layout. Every claim was checked against the seed's source. They give two comment-and-design questions a second route to their answer, knowingly, and the README says the design group's jump from 73% to 97% is partly that.

**A step in *07-benchmarking.md* could not work as written.** It told you to apply isolation by hand and then run the harness, which refuses to start while isolation is applied. The harness applies and restores isolation itself.

**Unscoped `find_symbol` doesn't stop when the client gives up.** One ran on the server for four hours after a 45s client timeout and killed clangd at the end, on a third-party file under `Engine/Platforms`. *05* now says so and excludes that path. We haven't re-run the walk to confirm the exclusion fixes it.

## Earlier, unreleased: v3

> Two figures below were later corrected. v3's gap is +17.3 points and the stack arm 93.8%. The J/F diagnosis is withdrawn. See the v4 entry above.

**The v3 benchmark result is published**, in *plugins/ue-memory-bench/bench/arm-comparison-v3.md*: 170 questions, both arms, every answer judged three times. **+16.8 points of partial credit and +24.7 strictly**, against a measured error bar of 0.3 and 0.6 points a pass. Twenty outright wrong answers became five. The two groups the baseline is worst at — engine API surface, and build and tooling procedure — are two of the stack's best, 25% to 90% and 50% to 97%.

**The token column reversed, and the stack did not get heavier.** v2 reported the stack 1.53x cheaper; v3 reports it 1.94x dearer, because the baseline arm changed. It is now an agent with *nothing we built* — a clean room holding source, config and content, five built-in tools, no language server, no MCP server, no rules files. Turn counts are within 5% of each other, so the whole token gap is standing context rather than extra work. *plugins/ue-memory-bench/bench/BASELINE-ARM-SPEC.md* carries the rule and the argument for it, including what it costs: the symbol index sits on the stack's side of the line, so the gap answers "is this worth building" rather than "is it worth adding to a codebase that already has good semantic search".

**Three published claims were wrong and are corrected.**

- **"Took the intended route 81% against 27%" was not a comparison.** Most expected routes name a layer artefact and the baseline arm runs where those have never existed, so it scored near zero by construction. On the routes both arms can reach, the two are level. Route is now documented as a diagnostic within an arm, and `route_split.py` reports the half of a set that is comparable.
- **"Tokens above the floor" cannot be computed** and is gone from the tools rather than corrected. A session pays its standing context on every turn, not once; the obvious correction goes negative on most questions because the implied per-turn input ranged 21,278 to 70,129 on one arm of one run.
- **A comparison document built on three judging passes was quoting one of them.** The score key had no pass field, so each pass overwrote the last and the table reported whichever ran last. `compare_arms.py` votes the majority now, ties to partial credit.

**Isolation by moving files aside is a denylist, and there is now an allowlist to use instead.** New *plugins/ue-memory-bench/bench/tools/Build-BaselineRoot.ps1* builds the baseline arm a clean room — each project's *Source*, *Config* and *Plugins* copied, *Content* hardlinked so the assets cost nothing, the engine junctioned from where it is, and nothing else ever named — then greps the finished room for artefact vocabulary and **refuses to finish if it finds any**. `run_bench.py --isolation room` runs the arm in it and verifies it is not stale first. The projects come from *plugins/ue-memory-bench/bench/projects.json*, so the room admits exactly what the question generator draws from.

It earned its keep immediately: on its first run against this repository the proof step caught a stale comment in the seed project naming the plugin by its pre-rename name.

Why it replaced moving files aside: fifteen leak channels over three attempts, each round finding them where the round before had approved — a version file whose line 149 was one question's exact answer, the pipeline's own logs, forty-three unclassified build logs, and the isolation run's own marker file, which told 37 of 159 answers that a benchmark was running. **The per-question leak gate that would actually *prove* a clean run is still not published**, and both documents say so rather than letting a room be mistaken for a proof.

**New in *plugins/ue-memory-bench/bench/tools***: `judge_reliability.py` (agreement across passes, per-pass spread, majority verdict), `route_split.py`, `measure_floor.py` (what a configuration costs before it is asked anything), `measure_schema_cost.py` (points at any stdio MCP server), `assess_new_questions.py`. `run_bench.py` pins the tool surface with `--tools` and records it in the run's meta — `--allowedTools` looks like the same flag and only suppresses prompts, and in v2 both arms could write files and the baseline arm did so 33 times.

**A rules file cost the stack 20% of its answers.** A line asking sessions to log what they change was read by benchmark agents that have no write tool: 34 of 170 answers mention trying to comply, three of the four questions that ran past the time ceiling are among them, and one question the baseline got right the stack got wrong after 43 calls. It had been checked against the byte budget and against the routing it was meant to improve, and never against what else reads it. The lesson is in *04-writing-your-claude-md.md*: everything in an always-loaded file is read by every session, including the ones that cannot act on it.

**The Blueprint artefacts state their own grouping rule**, and say that a negative is real. A question found the exact set of Blueprints under an ultimate native parent and then offered a longer alternative with equal weight, because the file never said what it was a set of.

**The comparison generator no longer announces that accuracy was not measured** underneath a table of accuracy figures. That footer went out unconditionally for two versions.

## Also unreleased: the first install onto projects other than the seed

This found five things the seed project could never have shown, because it isn't in source control, is named to the convention, and had only ever been dumped once.

**The scripts check files out of Perforce before writing them.** New *plugins/ue-memory-stack/scripts/Common.ps1*, dot sourced by the rest. It covers the descriptor, the dump's output folder and *compile_commands.json*. Checkout is decided on whether the file is *controlled*, not on whether it's read only, because a `text+w` file is writable whether or not it's open: the write succeeds, the file never joins a changelist, and the change goes missing at submit time. `p4` is invoked from the file's own directory so a `P4CONFIG` above the workspace is found. If Perforce is unavailable the read only flag is cleared instead, with a warning; `-NoSourceControl` opts out.

**The descriptor is edited as text, not reserialised.** Adding one plugin to an 18 KB descriptor used to produce a 2,292 line diff, grow the file to 44 KB and add a byte order mark. It's now four added lines and 65 bytes. Indentation, line endings and the byte order mark are preserved, the new entry copies the style of the one above it, every edit is parsed back and checked before it's written, a descriptor that already enables the plugin is left alone, and an existing *.uproject.bak* is no longer overwritten by a second run.

**The editor target is discovered, not assumed.** `<ProjectName>Editor` is a convention plenty of projects don't follow, and a project renamed part way through development, whose descriptor now says one thing while its target still carries the old name, broke the install on the second project tried. The *Target.cs* file declaring `TargetType.Editor` is what's used now.

**The plugin DLL is looked for where it actually is.** A plugin's modules build into the plugin's own *Binaries*, not the project's, so the staleness guard was checking a path the file could never appear at and would have thrown on every build. "No DLL anywhere" is now reported separately from "DLL is stale", since the first usually means the plugin isn't enabled.

**A non-zero exit from the dump is explained rather than just printed.** *UnrealEditor-Cmd* returns non-zero if anything logged an `Error`, so on a project of any age it's the normal result and says nothing about the dump.

**An absolute `-Out` lands where it was asked for.** `FPaths::Combine` doesn't notice its second argument is already rooted, so an absolute path used to write the whole dump to a folder named after the drive letter underneath the project, successfully and silently.

**index.md is deterministic.** Classes were sorted within a module but the modules themselves came out in `TMap` hash order, so the file reordered itself on every dump: same rows, same byte count, different order. Two runs of one project now produce 1,383 of 1,383 identical files, where before it was 1,382.

**The dump counts what it wrote, not what's in the folder.** A run that died in a second having written nothing reported `files=1383`, because the folder was already full from the previous dump. It also refuses to launch when the project's editor modules no longer match the engine's `BuildId`, which is what happens to the first project after you build the second one against the same source engine.

## 0.1 — unreleased

First cut. The reflection dump and the Blueprint index are what we use daily; everything else is either supporting it or documented as experimental.

**The plugin.** An editor-only commandlet that walks the live reflection system and the Blueprint graphs, and writes one Markdown file per class plus two indexes. It depends on no game module and discovers what to describe from the project descriptor and the enabled non-engine plugins, so it runs on any project.

**Blueprint to C++ edges.** Resolved through each node's member reference rather than matched by name, which is what makes the negative form usable: a class absent from the index has no Blueprint users at all.

**Scripts.** Install, build, dump, compile database, and a sync script for keeping two trees in step. They call UnrealBuildTool directly rather than *Build.bat*, and the build script refuses to let you dump against a stale DLL.

**Docs.** Getting started, one per layer, and a troubleshooting page that mostly consists of failures that cost us an afternoon each.

**Templates.** *CLAUDE.md* with the routing table, per module rules, a design doc, and the minimal benchmark agent.

**Seed project.** *seed/AccelDemo*: three gameplay classes, three Blueprints, both replication conditions, and one function whose comment disagrees with its body on purpose. It exists so you can watch the whole loop work on something known good before pointing it at your own code.

**Benchmark.** A question generator that builds a set from your own project's artefacts, a key checker that re-derives what it can from source, an isolation script that moves the layers out of the tree rather than asking an agent not to look at them, and the scoring and comparison tools. Multi project by design, single project by default.

**Layer 3, experimental.** A UHT exporter and the shim plugin pattern that gets it compiled and registered. It builds; what it emits is not settled. Nothing depends on it.

### Known limits

- The scripts are Windows and PowerShell. The plugin is not, but you'll be running the commandlet by hand on other platforms.
- The published benchmark figures are v4, measured on our tree. They are not comparable to a number from any other version, and re-running is the only way to move a result across that line. v3, v2 and v1 are kept beside them for the same reason, and neither v2's nor v4's baseline is the same arm as v3's, so none of them can be read as a trend.
- The per-question leak gate that proves a clean baseline run is not published. The room builder is, and so is the move-aside isolation script, with the limits of each documented.
- The Serena patches are against Serena 1.7.0, and an upgrade reverts them silently.
- The run-to-run variance paragraph in the generated comparison is still ours. Everything else in that caveat block comes from your own notes file.
- Layer 3 has no consumer in this repository.
