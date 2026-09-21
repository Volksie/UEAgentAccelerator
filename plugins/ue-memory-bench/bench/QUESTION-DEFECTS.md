# Question set defects, and the v2 wording for each

The set froze when the baseline was recorded. Nothing in this file is applied to the frozen runset or the two markdown sources, because changing them invalidates comparison with the recorded run in `arm-comparison.md`.

This file accumulates the fixes so they stop propagating into future runs. When someone decides to cut a v2 set, this is the changelist. **Record the decision somewhere a later session will look** so it knows whether the set it holds is v1 or v2.

Status of each entry: **recorded** (written down, not applied) or **applied in v2**.

---

## I22 — self-referential, unanswerable by construction

**Status:** recorded, 2026-09-08.

**Current wording**

> What is the smallest fix for I21 that keeps the author's decision intact?

**Why it is broken.** It names another question by ID. Every question runs in a fresh session, and `bench/` is moved out of the tree during a measured run so the answer keys cannot leak — so no session in either arm can resolve "I21". All three recorded measurements say so explicitly; the with-layers one reports that `bench/`, which `CLAUDE.md` says holds the questions, does not exist.

It is the **only** question in the 160 that refers to another by ID. Checked by scanning every question for `[QDGI]\d+` tokens matching another question in the set.

**What it scored:** baseline N, N; layers P. Two of Group I's six baseline wrong answers. Excluding it moves Group I from 76% to 79% baseline and 93% to 95% with layers. Group I remains the weakest group and the largest accuracy gain either way, so the conclusion does not turn on this.

**Second-order effect worth knowing.** This is also the question that ran *slower* with the layers than without (55.6s against 120.2s, 0.46x) — the only such case outside noise. `CLAUDE.md` points at `bench/`, the harness removes `bench/`, so the with-layers session spent 18 tool calls chasing a directory Layer 4 told it about. A reminder that Layer 4 describing the tree accurately matters as much as it describing the code accurately, and that the isolation harness changes the tree Layer 4 describes.

**v2 wording** — self-contained, same answer, same difficulty:

> Two log writer translation units each define `SanitizeForFileName`, `WorldTypeToJson`, `AppendJsonEscaped` and `CrcUpdate` in anonymous namespaces, deliberately and with a comment explaining why. Under a unity build the two anonymous namespaces merge into one translation unit and the definitions collide. What is the smallest fix that keeps the author's decision intact?

**Key is unchanged and correct:** name the namespace in one of the two files (giving it a project specific name) and qualify its references — smaller than factoring out a shared header, and it preserves the documented duplication.

**Route, which the question set does not currently define for group I:** that project's own rules file, section "The 5.7 to 5.8.3 upgrade, and why it is worth remembering". Layer 4, should cost one read. Worth adding as the expected route when the group G and I route column is filled in.

---

## I20 — the answer became false when the tree changed

**Status:** recorded, 2026-09-08. **This is not a wording defect; the key is now factually wrong.**

**Question:** "Why does `find_symbol(\"ModuleRules\")` return nothing when `find_declaration` on it works?"

**v1 key:** UBT is registered as an additional workspace folder in *.serena/project.yml* but is not indexed by Serena. Navigation crosses into it, search does not.

**Why it broke.** That arrangement existed because `.claude/rules/Building.md` said indexing engine C# would time out. Tested 2026-09-08: **all 7,594 C# files in the tree index in 20 seconds**, no timeout. The claim did not reproduce, so UBT and AutomationTool are now indexed workspace folders of the root project and `find_symbol` can see them. **The question's premise no longer holds.**

**What it measured, and what to do with it.** I20 was one of the questions where the layers arm scored on route, and it is also one of the ten whose keys had never been checked by a person - which is how a key survived that described a workaround rather than a fact about the codebase.

Options for v2, and the second is better:
1. Reword to the historical framing: "why *did* `find_symbol` not see UBT before it was indexed". Keeps the question, but it becomes a history question about our own config rather than a retrieval question about the tree.
2. **Drop it and replace it.** The thing it was really testing - does the agent understand the difference between a registered and an indexed workspace folder - is a good question, but it should be asked about a case that is still true. There is no longer one in this tree.

**The general lesson, which is the valuable part.** A question whose answer describes *our configuration* rather than *the codebase* has a shelf life, and expires silently when the configuration improves. Group I is full of these. Worth auditing the other 29 for the same shape before v2 freezes.

---

## Group I: 13 of 30 questions describe our configuration rather than the codebase

**Status:** audited 2026-09-08, full analysis recorded at the time.

Two are already broken (I20, I22). Eleven more are true today but keyed to our own setup, so they expire silently when the setup improves: **I1, I4, I5, I7, I8, I19, I23, I25, I28, I29, I30**. Seventeen are durable, keyed to engine behaviour or UBT's own source.

**The v2 changes, in priority order:**

1. **I20** - drop and replace. Its premise (UBT registered but not indexed) is gone.
2. **I7, I8** - re-key to substance rather than wording. Both ask "what does *CLAUDE.md* say", so their keys quote Layer 4 verbatim and break on any rewrite. The underlying questions are good - they test whether the routing table gets read, which is what Layer 4 is for - but the key should state the fact the file conveys, not the file's sentence.
3. **I25, I29, I30** - date the keys. "As of 2026-09-08 no language server exists for XML/INI/shader references" is honest and visibly ages. "There is no language server" rots silently. Note **I30 is one enable away from false**: Serena supports `hlsl`, it is simply not switched on.

**Rule for new questions:** if the answer changes when we improve our own tooling, it is a documentation question wearing a retrieval question's clothes. Sometimes that is what you want - but make it deliberate, and date it.

---

## Carried from `HANDOVER-TO-CLAUDE-CODE.md`, not yet investigated

These came from a separate review and are listed here so the changelist is in one place. Each still needs the check that I22 got.

- **Group F wording** — "Which properties on X replicate?" does not say whether inherited ones count. 15 questions. Proposed fix: "declared on X". **Measured effect on the recorded run: none.** All 42 group F measurements scored correct, and Q081 — the question cited as the one a strict scorer would fail — scored Y in both arms with the judge noting it committed cleanly to "none" and added correct inherited context. Real defect, zero observed cost. Low priority.
- **Keys I13 and D15** are weaker than answers that came back. I13's answer named `bAllowUBAExecutor` and the executor fallback order; D15's added sample-plugin sync and build-verification steps. Both checkable against the tree.
- **Ten hand-written keys never checked by a person:** I11, I12, I18, I20, I21-I24, I25, I28, I29, I30, plus the 25% hand check on group C that the method asks for. Measured: the non-Y rate inside that set is 10/35, and in the rest of group I it is 15/52 — the same 29%, so the unverified keys are not distorting the group I result.

---

## Q008 — the set named two routes to a fact that has three

**Status:** recorded and applied at scoring time, 2026-09-18. **This one moves a published figure.**

**The question.** Q008 asks for the declared type of a `UPROPERTY` on `CommonPlayerInputKey`. The set's
expected route was *"classes/CommonPlayerInputKey.md, or the header"*.

**Why it is wrong.** That is two of the three places the fact lives. The engine API store holds the same
declared type in its `properties.cpp_type` column, and the routing table sends "what a class declares"
straight at it — so the tool is a first-class route for this question and the set simply did not list
it. Both routes were checked on 2026-09-18 and agree exactly:

    engine_api_members('CommonPlayerInputKey', 'properties')
        -> `ECommonKeybindForcedHoldStatus ForcedHoldKeybindStatus`
    LyraStarterGame/Docs/AgentMemory/classes/CommonPlayerInputKey.md, line 53
        -> | `ForcedHoldKeybindStatus` | `ECommonKeybindForcedHoldStatus` | ...

This is a defect in the set rather than a finding about the model. The distinction matters and the
corrections file states it: *"reached the answer another way"* is a finding; *"the route we wrote down
was not the only correct one"* is a defect.

**Effect on the recorded numbers.** The layers arm scored `route_match=N` on all three judge passes, the
judge noting each time that the answer was right but reached through the engine-api tool rather than the
expected route. **Correctness was Y on all three passes and does not move.** Route match for Q008 should
have been Y, so the recorded layers route-match figure is one question pessimistic; the group A and
overall route-match figures move by that one question. The baseline arm used a text search and is
unaffected.

**How it is applied.** At scoring time, through `expected-routes-corrections.json`, so the runset stays
byte-identical and the result document keeps saying what the run did score. A rescore with the
correction present reports what it should have scored — and those are two different numbers that must
not be quoted as one.

**Not carried in this repository's corrections file, deliberately.** That file ships empty: corrections
are keyed by question id, and ids are reused between sets. The seed set here has its own Q008, about
RPCs on `ADCharacter`, and an entry copied across would override it with a route naming a class the seed
project does not contain — a wrong answer key, which is the failure this harness has published and
corrected twice already.

## Q019 — the key says "14 Blueprints" where the artefact has 14 ROWS and 12 Blueprints

**Status:** recorded 2026-09-19. **Pre-existing**: it predates the Blueprint-index work of 2026-09-19 and has
cost the layers arm half a point in **three published results** (v3, v4, v5).

**Current wording and key**

> `ULyraInventoryItemInstance::GetStatTagStackCount` is the most-called project function from
> Blueprint graphs. From how many Blueprints, and how many call nodes?

Key: **"14 Blueprints, 30 call nodes."**

**Why it is wrong.** Counted in `LyraStarterGame/Docs/AgentMemory/bpcallers/LyraInventoryItemInstance.md`
before that regeneration, that symbol has **14 rows, 12 distinct Blueprints, 30 call nodes**. A row
is one (Blueprint, graph) pair, so `/Game/Weapons/GA_Weapon_ReloadMagazine` contributes three rows on
its own — `EventGraph`, `K2_CanActivateAbility` and `ReloadAmmoIntoMagazine`. The 14 in the key is the
row count wearing the word "Blueprints". The node total of 30 is right, and "most-called project
function" still holds (next are `GameplayMessageSubsystem::K2_BroadcastMessage` at 16 and
`LyraGameplayAbility::GetLyraCharacterFromActorInfo` at 11).

The correct answer is **12 Blueprints, 14 graphs, 30 call nodes**.

**What it cost.** The layers arm answered **12 Blueprints / 30 nodes in v3, v4 and v5** — and was
scored **P in all nine judging passes** (three per version), every note giving the same reason: the
node count matches but "the Blueprint count is given as 12 rather than 14". It was right and was marked
down for it, three rounds running, by the key rather than by the judge.

**The sharper half.** In v3 the *baseline* arm said "14 (likely 15)" from a byte search over the assets
and also scored P. A byte search finds the function NAME, which two owners declare — `LyraPlayerState`
declares `GetStatTagStackCount` as well, with 5 nodes across 4 more Blueprints — so the baseline's 14
was a different wrong number reached by a method that cannot distinguish owners. **The key made a wrong
baseline answer and a right layers answer score identically**, which is exactly the failure this file
exists to catch.

**Fix, and what it moves.** Restate the key as 12 Blueprints / 14 graphs / 30 call nodes, and say which
owner is meant, since `LyraPlayerState::GetStatTagStackCount` exists too (union of both owners is 16
distinct Blueprints — a third number an answer can legitimately reach). Rescoring Q019 layers P→Y adds
0.5 of a point in each of v3, v4 and v5. Treat it
the way J1 and J5 were treated: the published figures record what the run scored; say which of the two
any quoted number is.

**How it was found.** Not by re-reading the key. The Blueprint-index work of 2026-09-19 needed a
before/after diff of every artefact, and checking the BEFORE snapshot against the keys — rather than
only the after — separated this pre-existing defect from the ones today's change could cause. Without
that column it would have been recorded as caused by the bind/macro-graph walk, which it is not.

**RESCORED 2026-09-19**, all three versions, three passes each, from the recorded answers under the
corrected key via `answer-key-corrections.json`. The pre-rescore score rows are kept beside the rescored ones in the tree that produced them; this repository publishes the documents, not the run records.

| | Layers Q019 | Baseline Q019 | Layers credit | Baseline credit | Gap |
|---|---|---|---|---|---|
| v3 | P → **Y** 3/3 | P, unstable (P/N/P) | 93.8% → **94.1%** | 76.5% unchanged | 17.3 → **17.6** |
| v4 | P → **Y** 3/3 | N, no answer (timed out) | 93.2% → **93.5%** | 74.4% unchanged | 18.8 → **19.1** |
| v5 | P → **Y** 3/3 | N, no answer (timed out) | 95.6% → **95.9%** | 75.3% unchanged | 20.3 → **20.6** |

**It had to be judged twice, and the reason is a lesson about correcting keys.** The first corrected key
said only what the right answer is: 12 / 14 / 30. Under it, v3's baseline — which answered "14 (likely
15)" from a byte search over the assets — scored **N** in all three passes, and the layers arm Y. That
looked like a clean result and was an artefact of the correction being under-specified: it never said
what a byte search can legitimately yield. `ULyraPlayerState` declares a `GetStatTagStackCount` of its
own (5 nodes across 4 further Blueprints), a byte search finds the shared name and cannot separate the
owners, so ~16 is a defensible number to arrive at and 14 is a near miss rather than an invention. With
that stated in the key, v3's baseline scores **P, N, P** — majority P, exactly what it was published as.

So: **the layers arm gains 0.3 points in every version and no baseline figure moves.** v3's baseline
Q019 is now an unstable measurement (`judge_reliability.py` lists it), which is the honest description of
an answer that is partly right about a genuinely ambiguous symbol.

**The rule this establishes for this file:** a corrected key must state what a *defensible alternative*
answer looks like, not only the right one. A key that says only "the answer is X" makes every other
reachable number an invention, and that is a second scoring error replacing the first.

**Version-scoped from here on.** The count itself changes on artefacts generated by the Blueprint walk
this repository now ships - the next measured run, v6. That walk follows macro
graphs, `WeaponAudioMacros/LyraGetWeaponAmmo` adds one call row, and the true answer becomes **13
Blueprints / 15 graphs / 31 call nodes** (union across both owners 17). That is not a defect in v6, it is
a different true answer, so `answer-key-corrections.json` entries may be objects keyed by run tag and a
tag with no entry gets **no** correction rather than inheriting another run's number. In the tree that measured these runs Q019 carries `v3`, `v4`, `v5` and `v6` keys; the copy of
`answer-key-corrections.json` in this repository ships **empty**, because these ids belong to that
question set and applying them to another set is the defect, not the fix.

**Not republished.** `arm-comparison-v{3,4,5}.md` still carry the as-scored figures, per the rule this file has followed since Q008: the comparison for a run records what that run
scored. Any quotation of a Q019-affected figure has to say which of the two it is.

## J1 — correct for v3 to v5, and its supporting numbers go stale in v6

**Status:** recorded 2026-09-19, with a `v6`-scoped key in the measuring tree's
`answer-key-corrections.json` and nothing for the earlier runs. v3, v4 and v5 get no correction: the original
key is right for those runs, and applying v6's numbers to them would be the error this file exists to
prevent.

J1's headline survives the v6 Blueprint walk unchanged: `UMaterialInstanceDynamic::SetScalarParameterValue`
at **91 call nodes across 32 Blueprints**, with `KismetSystemLibrary::PrintString` at 71 / 38 Blueprints.
Two supporting numbers inside the key do not:

- it names `UserWidget::PlayAnimationForward` at **62** as third by call nodes. In v6
  `AActor::GetComponentByClass` takes third place at **64**.
- it cites `AActor::GetComponentByClass` at **56 call nodes, 37 Blueprints** as the pure-node contrast.
  The v6 count is **64**.

Both move for the same reason as Q019: macro graphs are walked, and 11 ordinary Blueprints turned out to
contain local macros as well as the three macro libraries. The purity argument the question is really
about is unaffected — only the counts are.

**Counted from the rebuilt store, one `SELECT` over `bp_edges`** (Lyra, `kind='call'`, summing `uses` and
counting distinct `blueprint_path`):

| Function | v6 nodes | v6 Blueprints | What the v5 key says |
|---|---|---|---|
| `MaterialInstanceDynamic::SetScalarParameterValue` | **91** | **32** | 91 / 32 — unchanged, the headline holds |
| `KismetSystemLibrary::PrintString` | 71 | 38 | 71 / 38 — unchanged |
| `Actor::GetComponentByClass` | **64** | **38** | 56 / 37, and not in third place |
| `UserWidget::PlayAnimationForward` | 62 | 37 | named as third at 62; now fourth |

**One more thing the after-column did not name, found in that query:** ranked by Blueprint count,
`PrintString` and `GetComponentByClass` now **tie at 38**. The v5 key states that "ranked by Blueprint
count instead, `PrintString` leads with 38", which is no longer true in v6. The v6 key says so explicitly,
because an answer that reports the tie is right and would otherwise be marked against a key claiming a
sole leader.

## J6 — a row count headed as a thing count. The Q019 defect, fourth occurrence

**Found 2026-09-20**, re-deriving every key against the v6 dump, minutes after the identical defect was
corrected in the new question **F5** — which asks a neighbouring question off the same table.

The key opens **"Seven writes, across five properties"**. Seven is the **row** count, one row per
(Blueprint, property). There are **eight write nodes**, because `GA_ADS` writes `MaxWalkSpeed` from two.
Re-derived from the store: `kind='write'` gives **7 rows, 8 nodes, 5 properties, 6 Blueprints**.

**The key discloses the two nodes in its own body and still heads the answer with 7.** That is what makes
it a defect rather than a shorthand: an answer of "eight write nodes" is correct, and a judge reading the
headline marks it wrong. Same failure as J1, J5 and Q019 — the key, not the arm.

**Six Blueprints hold seven rows** because `B_Grenade` writes two different properties. So three distinct
counts sit behind one question — 7 rows, 8 nodes, 6 Blueprints — and the question's wording picks none of
them. The v6 correction accepts either headline *provided the answer names its unit*, and says explicitly
that 8 must not be marked against the key's 7.

**Scoped to v6 only, and that is a deliberate limit rather than an oversight.** The ambiguity is older
than v6 and the counts were plausibly 7/8 in v3–v5 as well, but only the v6 artefacts were checked.
Asserting what v5's node count was without re-deriving it would be the same class of error as the defect
being corrected. Under this file's version-scoping rule, a tag with no entry gets no correction.

**The reasoning half of the key is untouched** and still carries the credit: a graph writing an engine
component's state bypasses whatever setter the C++ side would have used, so invalidation, dirtying and
replication hooks do not run, and none of these writes is visible to any C++ tool. One caveat added in
v6: the Blueprint walk does not check `IsNodeEnabled()` on write nodes, so "a node exists" is not
strictly "it runs".

**Why this keeps happening, stated plainly.** Every one of these tables is one row per
(container, thing) with a `uses` count on the row. Reading `COUNT(*)` gives rows; the thing count is
`SUM(uses)`; and the container count is `COUNT(DISTINCT ...)`. Three numbers, all plausible, and the
larger the answer set the less likely anyone notices which was taken. The fix that has actually worked is
not more care — it is **every key naming its unit on every figure**, which all 52 new keys now do.

## Q063 — the tree moved under a question nobody edited

**Found 2026-09-20**, re-deriving every "which Blueprint graphs break" key against the v6 store.

The key says **"1 Blueprint graph(s)"** and names the EventGraph read. In v6, `Button_Action` is reached
**three ways inside that one Blueprint**, `W_SettingsListEntry_Action`:

| Where | Kind | Breaks on a rename? |
|---|---|---|
| `EventGraph` | read | yes — the key has this one |
| `GetPrimaryGamepadFocusWidget` | read | yes |
| `WidgetTree` | **bind** | **yes, and silently** |

The third is the one worth the question. `Button_Action` is a **BindWidget**, resolved **by name** at
compile time, so renaming the `UPROPERTY` breaks the binding without breaking any graph node — precisely
the failure a C++ rename tool cannot see and the reason this question exists.

**This is NOT a defect in v3–v5.** Their artefacts carried neither widget bindings nor the second graph,
so "1 graph" was the true answer for those runs. It is v6-scoped, and it is **the clearest example of why
"139 unchanged" means the question TEXT and not the key**: nobody edited Q063, and its correct answer
changed anyway because the walk got better. A review flagged this as a gap in the v6 section of
`BASELINE-ARM-SPEC.md` before anyone had found an instance; this is the instance.

**The sweep that found it, so it can be repeated.** Every shared question of the form
*"N Blueprint graph(s): …"* had its N compared against `bp_edges` for the symbol in its question text.
**Seven questions, one mismatch.** Q066, Q069, Q072, Q078, Q079 and Q080 are exact on rows, graphs and
Blueprints. Running that comparison takes seconds and it is now the standing check after any dump that
changes what the walk covers — the walk getting better is indistinguishable, from inside a key, from the
key being wrong.

**Revised 2026-09-20, decision-5 review.** The correction above said Button_Action has **no C++ callers**.
It has two, in the owning class's own implementation: `GameSettingListEntry.cpp:303`
(`NativeOnInitialized`, binds `OnClicked`) and `:318` (`RefreshEditableState`, `SetIsEnabled`). I
re-derived the Blueprint side and asserted the C++ side without checking it, which is an unverified
negative in a key written to correct one. The question asks for "C++ and Blueprint". The layers arm named
both uses and was marked P for them. The v6 entry now lists them.

## Decision-5 review of v6 — ten more keys that marked a correct answer down

Decision 5, taken before the run: the run is the second route to a key defect, so **every question on which the layers
arm was marked N or P is reviewed before any v6 figure is published.** After two judge passes that was 32
questions. Each was re-derived from `engine-api.db` and the source, not from the arms' answers. Twenty-one
are genuine shortfalls of the arm or judge coin-flips that pass 3 settles. **Ten keys were wrong**, plus the
Q063 revision above. All eleven are v6-scoped entries in the measuring tree's `answer-key-corrections.json`.

**How to read this list.** The review was deliberately one-sided: it looked only where the layers arm lost
credit. A key defect that marked the baseline down while the layers arm agreed with the key could only
arise if both were wrong the same way, and that was not searched for. Several of these corrections lift
the baseline too (F10, F14, Q031 and Q098 were P or N for both arms), so the gap does not move by the full
amount the layers arm gains.

| Q | What the key said | What is true | How it was established |
|---|---|---|---|
| **F10** | UWITFunctionActionBase declares 7 UFUNCTIONs | **12**. The five the judge called "invented" in **both** arms are real | `WITFunctionActionBase.h:79,94,147,214,224`; the artefact itself says "12 functions" |
| **F14** | 35 replicate, and grep matches 42 | **41** over the tree's own headers, and grep matches **122** lines. Both arms said 41 and 122 | The key counted MemBench + Lyra/Source only. The question also covers Lyra's plugins (4) and WIT (2) |
| **K14** | One function, `GetEmoteAudioComponent`; FAIL_IF on "an empty list means the walk didn't look" | Both Get **and** `SetEmoteAudioComponent`. Set is a void function, so it's implemented as a wired **event**. The FAIL_IF penalised a true statement | `bp_functions` event:override, wired=1, on all three. **Store defect** below |
| **K20** | 34/35/11, and 65 Blueprints | That set counts **casts**. The question says "called into": 32/33/10, and 50. Both sets are accepted | `bp_bp_edges`: 179 calls and 29 casts |
| **Q018** | Largest native parent is LyraGameplayAbility, 21 | **UserWidget 55**; LyraGameplayAbility is fourth. The layers arm said 55 and was marked **N** | `bp_assets`; agrees with B8's key, which was cross-checked path by path |
| **Q034** | 128, and the largest group is LyraGameplayAbility 21 | 128 is right; the largest group is UserWidget 55 | as Q018 |
| **Q031** | 27 = 21 + LyraGamePhaseAbility 6 | **43**. Five more native subclasses have Blueprints: _FromEquipment 6, _RangedWeapon 6, _Death 2, _Interact 1, _Jump 1 | `classes.super_name` closure joined to `bp_assets.native_parent` |
| **Q098** | 671 | That figure counts **any target type**. Everything above ~246 comes from the **Program** target alone, and the other console is also 671. A Game target gives **238** | `module_platforms` split by `target_type` |
| **I16** | One console 671, the other "same order" | Game target: one console **238**, the other **242**; the layers arm gave exactly these | as Q098 |
| **D2** | A direct write "skips the replication bookkeeping" | **False**: the key repeated the header comment. There's no push model, and `ApplyDamage` writes `Health` with a plain assignment. The real reasons are the authority gate, the clamp, the stamina pause, the hit reaction and the death handling | `MBCharacter.cpp:37-59`; no `MARK_PROPERTY_DIRTY` or `bIsPushBased` in MemBench |

**The pattern, because it is one pattern five times.** F14, K20, Q031, Q098 and I16 are all a key that
measured **a narrower or different set than its question names**. That's rule 1 (the question text is the
contract) broken in the direction a key-writer can't see from inside the key. In all five, the store
answered the question as asked, and the arm reading the store gave that answer. D2 is the other failure
this tree already names: the key trusted a comment over a body.

**Store defect found on the way (K14).** The *Functions implemented here* column in the bp/ cards' interface
table lists only function graphs. An interface function with no return value is implemented as an event,
so it is **silently absent** from that column, even though `bp_functions` has it. The same gap hides
B_Hero_Explorer's `AnimMotionEffect` override of LyraContextEffectsInterface. A reader of the card is told
"implements Get" and nothing warns them that Set is missing. That is the absence-versus-ignorance confusion
K14 was written to test, in the tier K14 tests.

**Checked and NOT corrected: Q037.** Four of WIT's eight Blueprints have `unknown` parents, and three are
named like function actions. The layers arm therefore called the key's "no Blueprints derive from them"
unreliable. In the bytes all four have `ParentClass None` and **no WITRuntime import at all**. They are
orphans whose parent class no longer exists, not hidden subclasses. The key's "no" is right, and the arm's
P stands. The store still prints `unknown` where the truth is *no parent*, and that is the distinction the
arm needed.

**Two of these were already wrong in v5, so the v6-only scope understates them.** v5's layers arm
answered Q018 with **UserWidget, 55**, quoting the same table the v6 store gives, and was marked N on all
three passes. Q098 was N for the layers arm in v5 as well. The corrections stay v6-scoped under this file's
rule. **v5 had not been rescored at this point**, because that changes a published figure and its shared page. That decision had not been taken, and until it was, v5's 95.9% understates the layers arm by at least one question.

**Resolved 2026-09-21: v5 was corrected.** It was corrected for six keys, not two:
Q018, Q034, Q031, Q098, I16 and D2. Each concerns a fact nothing between v5 and v6 changed (native
parents, the class hierarchy, engine plugin descriptors, MemBench source unchanged since 2026-09-06).
Q063 stays v6-only, because its answer depends on v6's widget-binding walk. v5 was re-judged from its
recorded answers, three passes each. v5 is now **76.8% vs 97.1%** (was
75.3% vs 95.9%), and its layers arm has no outright-wrong answers. Both arms rose, because the baseline
had also reached the true Q018, Q031 and Q034 from source.

**Q098 and I16 were refined on the same day.** v5's layers answer to Q098 was 138, scoped to engine plugins
and a Game target. 238 is **138 engine plugins plus 100 platform-extension plugins**
(`Engine/Platforms/*/Plugins`); the other console is 138 plus 104. So 138 is right for the narrower scope it states, and
now earns P, as F14's 35 does. **The difference between the two consoles lies entirely in the platform extensions**, and
I16's key now says so.
