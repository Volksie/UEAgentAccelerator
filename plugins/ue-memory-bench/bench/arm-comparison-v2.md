# Arm comparison, v2

**Measured 2026-09-09 to 2026-09-10.** 160 questions, both arms, 320 measurements. No errors, no
timeouts, no blank answers.

Same numbers, same findings, with the per-group cost chart drawn. Use that link for anything going
outside this tree (a writeup, a review, anyone asking what the stack is worth) rather than pasting the
tables somewhere new, so there is one place the figures live and one place to correct them. It is
private until shared from the page's own share menu. If the numbers here change, the page needs
republishing to the same URL or the two will disagree.

This is the v2 run. The numbers in *arm-comparison.md* are v1 and are not comparable, because the
question set changed and so did the harness. Read that file for history, not for a baseline.

## What the two arms are

The layers arm is the stack as we ship it: *CLAUDE.md* and *.claude/rules/* auto-loaded, the
generated artefacts under each project's *Docs/AgentMemory/*, and the *engine-api* MCP server.

The baseline arm has none of that. It is not told to avoid them, it cannot see them, because
*baseline-isolation.ps1* moves 20 paths out of the tree for the duration of the run. Serena stays in
both arms, because Layer 1 is code search that any competent engineer would already have and taking
it away would measure a different question.

## Headline

The layers arm answers more questions correctly and costs less to do it.

| | baseline | layers |
|---|---|---|
| Strictly correct (Y) | 142/160, 88.8% | **151/160, 94.4%** |
| Partial (P) | 12 | 8 |
| Wrong (N) | 6 | **1** |
| With partial credit (Y + 0.5P) | 92.5% | **96.9%** |
| Total input tokens | 58,186,897 | **38,121,692** |
| Tool calls | 1,488 | **703** |
| **Tokens per correct answer** | 393,155 | **245,946** |
| Used the intended route | 43/160, 27% | **129/160, 81%** |

So we pay about 1.6x less per correct answer, and we get one outright wrong answer instead of six.

**Note:** the token figures include each arm's standing floor, which is not the same for both. We
measure the floor per arm now, inside isolation, because the arms no longer share an MCP surface and
the baseline arm has no *CLAUDE.md* to load. Baseline sits at 35,872 tokens a turn and layers at
52,084, so the layers arm pays 16,212 more before it retrieves anything. That difference is the
standing cost of the stack and it is already in the totals above.

## Per group

Cost and correctness together, because either one on its own is misleading.

| Group | What it asks | n | baseline tokens | layers tokens | ratio | baseline Y | layers Y |
|---|---|---|---|---|---|---|---|
| A | Class structure, parents | 20 | 2,480,032 | 3,878,666 | 0.6x | 16/20 | 19/20 |
| B | Members, signatures | 20 | 3,765,579 | 3,841,651 | 1.0x | 20/20 | 20/20 |
| C | Specifiers | 20 | 3,752,415 | 3,687,692 | 1.0x | 17/20 | 20/20 |
| D | Comments and prose | 15 | 3,662,083 | 3,268,477 | 1.1x | 12/15 | 12/15 |
| E | Blueprints | 20 | 25,045,808 | 6,286,721 | **4.0x** | 19/20 | 18/20 |
| F | Replication | 15 | 3,155,625 | 2,815,018 | 1.1x | 15/15 | 15/15 |
| G | Traps | 10 | 1,763,489 | 2,436,372 | 0.7x | 10/10 | 10/10 |
| H | Engine API | 10 | 2,474,360 | 3,104,996 | 0.8x | 10/10 | 10/10 |
| I | Build, tooling, procedure | 30 | 12,087,506 | 8,802,099 | 1.4x | 23/30 | 27/30 |

## Group E pays for the whole stack

Group E is 20 questions about Blueprints and it cost the baseline arm 25 million tokens, which is 43%
of everything it spent on 160 questions. With no *Blueprints.md* and no *bpcallers/* the only way to
answer is to grep `.uasset` binaries and reason about byte offsets, and that is what it did: 569 tool
calls against group E alone.

The layers arm read the generated artefacts and did the same 20 questions for 6.3 million tokens and
142 calls.

**Important:** the layers arm scored 18/20 on group E against baseline's 19/20, so it was slightly
*less* accurate while being four times cheaper. At n=20 one question is 5% and this is inside the
noise, but we should not round it up to a win. The honest statement is that group E is where the
artefacts save almost all of the money and correctness is a wash.

## Group I is the quieter win

Group I is build commands, tooling and procedure, 30 questions. Baseline got 23/30 and layers got
27/30, and four of baseline's six outright wrong answers are in here. Those four are worth reading
because they are all the same failure:

- **I4.** Asked which artefact to regenerate after a replication change. Baseline answered with build
  pipeline advice and never mentioned the reflection dumps.
- **I5.** Never mentioned the compile database or `-mode=GenerateClangDatabase`, gave generic UBT
  advice instead.
- **I8.** Reached a *different project's* CLAUDE.md, concluded the topic was absent, and missed the
  routing table's `.uasset` row completely.
- **D6.** Asserted that no *DefaultGameplayTags.ini* exists and that tags are declared in C++, which
  is the opposite of what this tree does.

None of these are hard questions. They are all facts that live in one file, and an agent that cannot
read that file has no way to recover them from the code. This is the clearest argument for Layer 4
that the run produces, and it does not show up in the token figures at all, because a confidently
wrong answer is cheap.

## Where the layers cost us, and why it is not what it looks like

Groups G and H are both 10/10 in both arms, and the layers arm spent 38% and 25% more tokens getting
there. Group A is the same shape except the extra spend does buy something, 19/20 against 16/20.

**Corrected 2026-09-10.** This section first said the cause was the layers arm opening artefacts where
a grep would have been cheaper, and that the standing floor was excluded from the ratio. Both were
wrong. Mean retrieval per question is **9.2 KB baseline against 6.1 KB layers on group A**, and
**11.4 KB against 5.3 KB on group H**, so the layers arm reads *less*, not more.

The real cause is that **`tokens_above_floor` subtracts the floor once per question while a multi-turn
session pays it on every turn**, so the floor was never out of these figures. The per-turn floor
difference accounts for 116% of the group A gap and 124% of the group G gap. The layers arm is not
retrieving badly, it is carrying 16,212 more tokens of context on every turn.

That gap is mostly instruction files: *CLAUDE.md* ~3,003 tokens, *.claude/rules/* ~6,554,
*MEMORY.md* ~1,264, *CLAUDE.local.md* ~159. Across the run it is about **14M tokens, roughly 37% of
the layers arm's 38.1M**, and the arm still won by 1.53x while carrying it.

**Corrected again 2026-09-10.** An earlier version of this section attributed ~4,781 tokens a turn to
MCP tool schemas and called them the sharpest case. Measured directly rather than inferred, they cost
**102 tokens a turn**: the harness defers MCP tools, so only their names load and not their schemas.
The figure had been derived by subtracting one version's floor from another's, and the difference was
actually the instruction files growing between them. The lesson is the one this whole document keeps
arriving at, which is that a number you inferred is not a number you measured.

What remains true is that the cost is packaging rather than retrieval, and packaging is fixable
without changing behaviour. Moving per-project notes out of the always-loaded set into each project's
own directory was measured at **3,595 tokens a turn**, about 8% of the run.

## Where neither arm helps

Group D is comments and prose, 15 questions, and both arms got 12/15. The layers arm's single wrong
answer in the whole run is D3, where it invented a tick-branch explanation instead of finding the
comment about component defaults not being replicated at BeginPlay on clients.

So the stack does nothing for "why is this like this". Layer 2 is generated from reflection data and
carries doc comments, but it does not carry design intent, and *Docs/Design/* is thin. If we want to
move group D we need to write prose, not generate more artefacts.

## Route match is the mechanism working

Baseline used the intended route on 43 of 160 questions, layers on 129 of 160. The baseline arm's tool
profile says the same thing: 583 Bash calls, 447 Grep, 234 Read, 138 Glob, and **zero**
`find_symbol`. Serena was available to it and it barely touched it. Without a routing table an agent
falls back on shell exploration, which is why group E cost what it did.

## What we had to fix before the numbers meant anything

The first attempt at this run was killed at 118/160 and thrown away. Three separate channels were
letting the layers reach the baseline arm, and only one of them was inside the tree:

1. **A coordination log between sessions** that did not exist when the isolation list was written. A
   day of entries in it describe the artefacts and how to route to them. The leak scan caught this one.
2. **Design notes under a tool directory** that quote answer keys verbatim, and that directory was not
   on the isolation list.
3. The *engine-api* MCP server. `run_bench.py` was invoking `claude -p` with no MCP control, so it
   inherited *~/.claude.json* and the baseline arm had six tools querying a database built from the
   artefacts we had just moved out of the tree. Moving files could never have fixed this, because the
   server runs outside the tree.

Then a fourth, found mid-run: the project's auto-memory. *MEMORY.md* is loaded into every session in
this project and its entries name *BlueprintCallers.md* and *Blueprints.md* and hand over retrieval
routes. Worse, the benchmark agents were writing new memories as they worked, seven of them during the
killed run, so question N+1 inherited question N's findings. That last part breaks question
independence in both arms, so the memory directory is now moved for both.

**Important:** two of these biased the result in opposite directions. The single shared token floor
flattered the layers arm by charging baseline for context it could not see, about 1.6M tokens across
the run. The memory leak flattered baseline by handing it retrieval routes it should have had to
invent. They would have partly cancelled, which would have made the result look more plausible rather
than less.

The leak scan walks the tree, so it cannot see any channel that lives outside it. Three of the four
were found by reading the harness instead.

## What to do next

1. Fix the cheap-lookup routing (groups A, G, H). The artefacts are being opened where a grep is
   cheaper, and the routing table already says not to.
2. Write prose for group D or accept it as a known hole. Generating more artefacts will not move it.
3. Wire `baseline-isolation.ps1 -Mode Check` into *Update-MemoryStack.ps1*'s preflight, so a
   build or a dump regeneration cannot run against a half-isolated tree.
4. Re-measure I5's "about 25 seconds" for the compile database. The full run did three targets and the
   merge in 13.8s, though that is not like-for-like against a cold single-target run.
5. Group E is answered. If we want a harder Blueprint question set, it needs a project with more
   graphs than the sample game used here has.
