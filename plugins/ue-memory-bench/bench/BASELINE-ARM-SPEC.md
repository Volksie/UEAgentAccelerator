# Baseline arm and full run: brief for the Claude Code side

This phase needs a harness that can invoke `claude -p` unattended. Not every one can, and where the figures below name the harness that produced them, that is why.

This is a specification, not a procedure. It says what the run has to satisfy and what to report. How you get there is yours, and you know the host better than I can from a VM.

## Why this phase exists at all

**Every number recorded so far is indicative and nothing more.** The 20-question smoke run measured the with-layers configuration against a baseline *mean from a different question set*, taken weeks earlier. That comparison cannot answer any of the three goals. Until a baseline arm runs on the same questions, nothing in the smoke results should be quoted as a before-and-after.

## What a baseline arm has to satisfy

One invariant, and it is the whole point:

> **The baseline agent must not be able to reach `CLAUDE.md`, `.claude/rules/`, or any `Docs/AgentMemory/` directory.** Not "is told not to use them". Cannot see them.

Being told not to look is not good enough. The smoke run showed the agent reads `CLAUDE.md` and then routes from it; an instruction not to would be measuring compliance, not architecture.

Three ways to get there. This list was originally in the order I trusted them, and **that order turned out to be exactly backwards**, so it is now in the order we arrived at:

1. **A parallel root of directory junctions.** Cheap, no copying, and it does not work: a junction resolves back to the real tree, the compile database holds absolute paths, and an agent reads an absolute path whatever its working directory.
2. **A scripted rename with a guaranteed restore.** Move the layers aside, run, move back in a `finally`. This does hold, and it is what the script in this repository does — but it is a **denylist**, and see "What the arm can SEE" below for what that cost us.
3. **A built room: a clean root holding only what the arm may see.** Source, config and content copied or hardlinked in, the engine junctioned from where it already is, and nothing else ever named. Expensive-sounding and the one we ended up with, because the cost that matters is not disk, it is the cost of *proving* the thing is complete.

**Whichever you pick, prove it before trusting the run**: have the baseline agent try to read the routing file and confirm it cannot, and record that check in the results. And prove it again per question — see the gate described below.

### The boundary: the baseline arm is an agent with nothing we built

This is the governing rule, and it exists because the boundary was moving. Our first two versions gave the baseline arm semantic code search, justified in the runner as "the thing a competent engineer would already have". The third removed it, and the compile databases went the same day. Each narrowing was argued on its own merits, each one makes the stack's win easier, and **none of them shows up in the headline figure**.

> **The baseline arm is an agent with nothing we built.**

Not "an agent with a reasonable toolkit", not "an agent as a new hire would find it". Nothing of ours.

**The reason is that we cannot guess what a competent engineer would have.** That standard is unfalsifiable. It is a claim about a hypothetical person, and every time someone invokes it they are choosing the baseline's strength by assertion — which sets the size of the result. A language server sat in both arms for two whole versions on exactly that basis, cancelling out, and the justification was one sentence nobody could check.

"Nothing we built" is a different kind of statement: **it is observable.** You can look at a thing and establish whether you made it. It settles cases instead of inviting them, and it cannot be nudged by whoever is arguing that week.

**It also makes the difference legible to a reader.** "Nothing against our system" is a comparison anyone outside the project can evaluate on sight. "What we imagined a competent engineer would have, against our system" asks the reader to accept our guess about a stranger's toolkit first — and a reader who does not share that guess cannot use the number at all.

**The honest limitation, stated here so it travels with the claim.** This measures *"is the stack worth building"*, not *"is it worth adding to a codebase that already has good semantic search"*. Those are different questions and the second is the one a team with a language server already installed would ask. It needs a third arm, stack minus the language server, which only became answerable once the language server stopped being present in both arms.

**How to apply it to the next case.** Ask: *did we make this, or generate it, or configure it for this tree?* If yes, the baseline arm does not get it, and no argument about what a competent engineer would have re-opens the question. That covers the symbol index, every MCP server you wrote, every generated artefact, the compile databases, the routing rules, the design documents and anything a future layer adds.

**What it does NOT license, and this is the half that gets got wrong.** It is a rule about *your tooling*, not about the codebase. **The baseline arm still gets the real codebase, unaltered.** If your accelerator plugin is now part of the tree's source, it stays — removing it would mean measuring against a doctored codebase, which is a worse contamination than the one it prevents. One of our questions asks which plugins the project enables, and the answer has to be the true one. Where such a file *described* the layers, the fix was to reword the description, not to delete the file.

So the line is: **strip everything you built to help an agent; change nothing about the code being asked about.**

### The tool surface

The invariant above is about what an arm can *see*. This is about what it can *do*, and our v2 run left both questions half answered. It is written down because "nobody chose" is how the last two confounds got in.

**Identical in both arms:**

- Built-in tools are `Bash, Read, Grep, Glob, ToolSearch`, set with `--tools`, which controls what *exists* rather than what is merely permitted. **Neither arm has `Write` or `Edit`.** In v2 both had them and the baseline arm used them 33 times during a measured run; a retrieval question must not be answerable by leaving notes for the next one, and a run that measures a tree must not be able to modify it.
- A language server's mutating and memory tools are removed explicitly, for the same reason plus one more: project memories persist across sessions, so reading one is a channel from question N to question N+1 in either arm.
- `ToolSearch` is in the list because MCP schemas are deferred on this harness. Without it an arm can see that a server exists and never be able to call it, which silently measures something else.
- The harness settings file **is not a layer** and stays in both arms. Ours registers the language server's session hook, and that hook's whole payload is a prompt telling the agent the server is there. Both arms are defined as having it, so both arms get told. In v2 only one arm did, which is visible in the result: 19 calls against 0.

**Different between the arms, and this is the entire difference:** the layers arm has the artefact directories, the routing files and the engine-API server. The baseline arm has none of them.

Record the surface in each run's meta file. Otherwise the only way to find out what an arm had is to look at which tools happen to appear in its results, which is how a baseline arm went 160 questions with `Write` available before anybody noticed.

### What the arm can SEE, and why a list is not a boundary

Our first v3 run was discarded. It proved the invariant was being enforced against a list of *known* files, and a list is not a boundary. Five channels got through, and only two were documents anyone had thought about:

1. **A version file at the tree root.** One question read its exact answer out of line 149.
2. **A review document** dropped at the root the previous day.
3. **The stack update script's own logs**, which narrate the pipeline stage by stage.
4. **The run's own marker file**, which named the arm, said the routing file had been moved, and printed the holding directory path. **37 of 159 answers knew a benchmark was running; five declined to answer until it finished.**
5. **Forty-three unclassified root build logs and generator scripts.** Two of them state Blueprint and edge counts per project; one carries a project's design documents as heredocs. One question cited a log file by line number.

**The rule that replaces the list.** Every entry at the tree root is classified before a run starts:

| Category | Meaning |
|---|---|
| allowed | a baseline agent reading it learns nothing about the layers |
| held by pattern | `*.log`, `*.err`, `*.bak`, `*.ps1`, `*.txt` and friends — the pipeline's own output, which narrates the layers by construction |
| neither | **the run fails and names it.** A person decides |

**If in doubt, hold it.** A held file costs the run nothing; a leaked one costs the whole run. That asymmetry is the whole argument, and it is why the third category fails rather than warns.

**The marker file says only that the tree is locked** — no arm, no counts, no holding path, no mention of a benchmark. It cannot move out of the tree: the refresh script's preflight and the two-tree sync script both look for it there, and relocating it would disarm both silently. Operator detail for recovering a dead run belongs in the holding directory, where only a recovering human looks.

**And prove it per question.** None of the above establishes that a given question stayed clean, because an agent with a shell can read an absolute path from anywhere. Record every path, pattern and command each question reached for, check that record against the held list, and abort on the first hit. Searching the *answers* for mentions instead undercounts by an unknown amount: on the discarded run, 30% of answers showed evidence and 70% showed none, and "no evidence in the answer" is not "did not read the file".

## The questions

| File | What |
|---|---|
| the generated question list | 105 generated questions, human-readable |
| the same, machine readable | The same, machine-readable, with `keyset` for set-scored questions |
| the hand-written additions | 55 hand written: groups D, G and I |
| the smoke tier | The 20-question smoke tier, sampled across groups |

**Start with the 20, not the 160.** If the smoke tier runs cleanly in both arms, the full set is the same thing with more of it. If it does not, you have found the problem for the price of 40 sessions instead of 320.

**The set is frozen the moment the baseline is recorded.** Any change after that destroys comparability with everything already measured. If a question needs fixing, fix it before you start and say so in the results.

## Scoring: six columns

One question per fresh session, per the method note. Revised 2026-09-08.

| Column | Meaning |
|---|---|
| Correct | Matches the key. Y or N, nuance in Notes |
| Route | Reached the fact through the layer the routing table says it should have. **Baseline arm: record what it actually did instead** |
| Seconds | Wall clock |
| Calls | Tool calls |
| Retrieval | **Bytes of file content read.** This is what goal 3 measures |
| Tokens | Session total input, and **turns**. Not "tokens above the floor" — see below |

Seconds and turns are the headline. Session tokens are not a criterion on their own: the standing floor dominates them, and the measurement below is what settled that.

**Do not record "tokens above the floor".** We did for two versions and it cannot be right. A session pays its standing context on every turn rather than once, so subtracting one floor understates a long answer; and the obvious correction, floor times turns, goes negative on most questions because the implied per-turn input is not a constant — it ran 21,278 to 70,129 on one arm of one run, because cache reads dominate the total and do not accumulate at a flat rate. Record total input tokens and turns. A turn is one model call, which is what the standing context is actually paid on.

Group E and F are scored recall and precision **separately**, never collapsed. Group G scores "refused correctly" as a pass.

## Which harness to measure on, now that both work

`claude -p` needs an `ANTHROPIC_API_KEY`; with one set it runs headless. So there are two working harnesses and the cheap one is **much** cheaper. Cheapness is the wrong tie-breaker here, and it is worth being explicit about why before someone reasonably picks the cheap one.

| | `bench` sub-agent | `claude -p` |
|---|---|---|
| Floor | **3,426 tokens** | Claude Code's own system prompt, tool schemas and auto-loaded `CLAUDE.md`. Measure it |
| Layer 4 | **Simulated.** The prompt tells the agent to read the routing file | **Real.** It loads automatically, which is the actual design |
| Layer 1 | **Absent.** One shell tool, so clangd and Serena are unreachable | Present, the way the team has it |
| Measures | Can the artefacts answer the question | Can a working session answer the question |

**The minimal-tool agent is cheap precisely because it removed the tools the benchmark exists to choose between.** An agent holding one shell tool cannot reach Layer 1 at all, so every question it answers, it answers by grepping. It cannot tell us whether `find_symbol` beat a per-class artefact, because it never had `find_symbol`. Half the architecture is unmeasurable in that harness, and the half it can measure is the half we already have numbers for.

The Layer 4 difference is subtler and matters as much. In `claude -p`, `CLAUDE.md` is auto-loaded on every turn: that *is* Layer 4, tax and all. In the sub-agent harness it was loaded because the prompt said to, which measures whether the routing table is any good but not whether it gets read.

**So: the measured arms run on `claude -p`.** Keep the `bench` agent for cheap sweeps where only Correct matters — re-checking answer keys after regenerating artefacts, or confirming nothing broke after a dump change. Those are worth having and they are worth having cheaply.

**Do not shrink the `claude -p` floor below the toolset the arm is defined as having.** Trimming MCP servers that play no part is fair game and worth doing. Trimming the symbol index to save tokens would delete Layer 1 from the *layers* arm, which is the one thing here that cannot be traded for cost.

That is not a reason to leave it in the baseline arm, and for two versions we read it as one. Layer 1 is ours by the rule above, so it belongs on the stack's side of the line — with the consequence stated there, that the gap then includes it and a third arm is needed to separate them.

**And the way to deal with a floor you cannot remove is not to subtract it.** Report the total and the turns, per the scoring table above.

## The floor, which is most of the bill

Measured in a sub-agent harness on 2026-09-08:

| Agent | Prompt | Tools available | Cost |
|---|---|---|---|
| general-purpose | "Reply with exactly: OK" | full MCP surface | **52,884 tokens** |
| `bench` | same | one | **3,426 tokens** |

**A 15x reduction in the floor from declaring a minimal tool surface**, and nothing else changed. That is the difference between about 17 million tokens of pure overhead across 160 questions and two arms, and about 1.1 million. It is the single biggest lever in this whole exercise and it has nothing to do with the memory layers.

`plugins/ue-memory-stack/templates/agents/bench.md` declares `Bash, Read, Grep, Glob` and is the minimal agent we used. **Verify the equivalent saving on your side before committing to the full run** — one "reply OK" probe against `bench` and one against the default agent, and compare. If your harness does not defer tool schemas the way that one did, your floor and your saving will both be different, and it is worth ten seconds to know which.

Do **not** batch questions to save tokens. Measured: 4.6x cheaper, all answers still correct, but tool calls dropped from 21 to 9 across five questions because each one inherited what the last one learned. That is exactly the column we now report.

## Method

1. **One question per fresh session.** Run them in sequence and later questions inherit context.
2. Record the tree state with the results: engine build, whether the clangd index is warm, the changelist.
3. If a question flips between runs, run it three times and record all three. Do not keep the good one.
4. Report per group as **median seconds and median retrieval bytes**. Session tokens as a mean with the floor beside it.
5. Never average the representative and coverage sets into one number.

## What we already measured, for comparison

With the layers, 20 questions, sub-agent harness:

- **20 of 20 correct, 17 of 20 on Route**
- Mean 60,875 tokens, 240 seconds, 4.6 calls
- Artefact route **3.3 calls / 166s** against source-search **6.0 calls / 346s**, for the same answers
- Two routing fixes since: one question went 386s to **13.7s**, another 201s to 100s
- Blueprint artefact split: blast-radius read path from ~94,000 tokens to ~650

Those with-layers numbers came from a different harness than yours, so **re-run the with-layers arm too**. Do not compare your baseline against my with-layers figures; the floors differ and the comparison would be meaningless.

## When a version changes the question set

Sooner or later both arms pass most of a group and it stops telling you anything, so you replace those questions and add new ones for whatever the stack has learned to answer. That's the right thing to do, and it breaks every comparison with the runs before it unless you report it this way. We did it for v6: 139 questions kept their text, 52 were new, and these are the rules we held ourselves to.

1. **Report the kept questions and the new ones separately, and never a figure over all of them on its own.** New questions written so that removing a layer changes the answer are questions the baseline is *designed* to fail. A gap over the whole set is a real measurement of a set you built to produce it.
2. **Only the kept questions sit beside an earlier run, and the earlier number is that run's own verdicts on the same questions.** Not its headline. The questions you removed were the ones both arms passed, so the earlier run scores lower on the kept set than on its full set, and putting its headline next to your kept-set figure invents a drop that didn't happen.
3. **A cost series stops where the set changes.** If the baseline's tokens a question have been rising run on run, the new run isn't the next point on that line. A point that mixes a set change with a baseline drift can't be separated afterwards.
4. **A group that was mostly replaced has no comparable rate.** It was replaced *because* it was too easy, so a lower rate there is the change working, not a regression. Say so where the rate appears.

Two things "kept" doesn't mean, both of which caught us:

- **It means the question text, not the key and not the tree.** Regenerating the layers can change the right answer to a question nobody edited: a walk that starts covering macro graphs changes a call-node count. Re-derive every kept key against the new artefacts before the run, and list the ones that changed.
- **The kept questions were selected on the earlier run's outcomes.** The removed ones were all passes, so the kept set holds every question an arm failed, and some of those failures were noise. Noise regresses upward, so both arms look a little better on the kept set with nothing having improved. It barely moves the gap, but "the stack improved on the kept questions" isn't a claim the kept set can support on its own.

**Note:** a set change is also the moment to review the keys properly. We made every question the stack arm was marked down on a reason to re-derive its key before publishing, and eleven of 32 were wrong. *QUESTION-DEFECTS.md* has them.

## What to report back

Write a per-question results document with the per-question table. If anyone else will read the result later, leave a note somewhere they will look: a session that starts cold has no way of knowing the file exists.

The three things worth calling out explicitly whatever the numbers say:

1. **Did the baseline arm's isolation actually hold?** The check from the section above.
2. **Which questions the layers made no difference to.** Those are the ones that tell us where the design is wrong, and they are easy to skim past when the averages look good.
3. **Anything the agent said about its own route.** Both routing bugs we have found came from reading that, not from inspecting files. It is worth more than the scores.

## One standing lesson, because it will save you a run

Twice the artefact held the answer, the agent could reach it, and it still took the long way, because no rule named that file for that question. Once for inheritance chains, once for blast radius. Layer 2 being correct is not sufficient; Layer 4 has to name it.

So if a question scores Correct but fails Route, **that is a finding about `CLAUDE.md`, not noise**.
