<sub>MEASURED 20 SEPTEMBER 2026 &nbsp;·&nbsp; UNREAL ENGINE 5.8.3 &nbsp;·&nbsp; THREE REAL PROJECTS &nbsp;·&nbsp; TWO AGENTS</sub>

# An agent with a memory stack is right more often, and it gets there faster

We gave the same model the same questions about a large Unreal Engine codebase twice. The first time it had only shell and text search. The second time it also had a memory stack: a routing guide, pre-generated knowledge about every class and Blueprint, an engine API database and semantic code search. **With the stack it got more questions right, got none outright wrong, and used a fraction of the time and tokens.**

![On 139 everyday questions: 95% correct with the stack against 68% without it. 0 answers outright wrong against 26. 3 times less total time, 1.2 hours against 3.6. 2.2 times fewer input tokens, 93k per question against 200k.](docs/images/why-figures-light.svg#gh-light-mode-only)
![On 139 everyday questions: 95% correct with the stack against 68% without it. 0 answers outright wrong against 26. 3 times less total time, 1.2 hours against 3.6. 2.2 times fewer input tokens, 93k per question against 200k.](docs/images/why-figures-dark.svg#gh-dark-mode-only)

<sub>Full result and its caveats: [arm-comparison-v6.md](plugins/ue-memory-bench/bench/arm-comparison-v6.md). The questions cover three projects: Epic's Lyra sample game, an open source plugin and the small seed project in this repository.</sub>

<br>

## The difference is largest on the questions that matter most

The bigger and less textual the question, the wider the gap. These are real questions from the run, with each agent's time and whether its answer was right.

![Five questions from the run. Which Blueprint is called into most: 865 seconds and wrong without the stack, 19 seconds and right with it. Which custom events are RPCs: ran out of time at 900 seconds without, 20 seconds and right with. Which Blueprint reads NumBotsToCreate: 828 seconds without, 14 with, both right. Which graphs break if OnlineMode is renamed: 825 seconds without, 40 with, both right. How many plugins lack a Runtime module on a particular console: 116 seconds and wrong without, 20 seconds and right with.](docs/images/why-questions-light.svg#gh-light-mode-only)
![Five questions from the run. Which Blueprint is called into most: 865 seconds and wrong without the stack, 19 seconds and right with it. Which custom events are RPCs: ran out of time at 900 seconds without, 20 seconds and right with. Which Blueprint reads NumBotsToCreate: 828 seconds without, 14 with, both right. Which graphs break if OnlineMode is renamed: 825 seconds without, 40 with, both right. How many plugins lack a Runtime module on a particular console: 116 seconds and wrong without, 20 seconds and right with.](docs/images/why-questions-dark.svg#gh-dark-mode-only)

Even where both agents get there, as on Q014 and Q072, the one without the stack spends about 14 minutes and more than a million tokens rebuilding from raw asset bytes what the stack already holds. That cost comes back on every question like it.

<br>

## It's better in every area we measured

The questions fall into eleven kinds. With the stack the agent scores higher in all eleven, and it reaches 100% in three of them.

![Correct answers by kind of question, with partial credit. Without and with the stack: engine API and platform support 20% and 100%, Blueprint internals 57% and 100%, build and tooling 52% and 95%, what makes things expensive 62% and 94%, inheritance 63% and 92%, comments and docs 70% and 93%, reflection and replication 80% and 98%, what breaks if I change this 82% and 95%, where things are defined 78% and 90%, effective flags 87% and 93%, trick questions 95% and 100%.](docs/images/why-accuracy-by-area-light.svg#gh-light-mode-only)
![Correct answers by kind of question, with partial credit. Without and with the stack: engine API and platform support 20% and 100%, Blueprint internals 57% and 100%, build and tooling 52% and 95%, what makes things expensive 62% and 94%, inheritance 63% and 92%, comments and docs 70% and 93%, reflection and replication 80% and 98%, what breaks if I change this 82% and 95%, where things are defined 78% and 90%, effective flags 87% and 93%, trick questions 95% and 100%.](docs/images/why-accuracy-by-area-dark.svg#gh-dark-mode-only)

<sub>Partial credit: a fully right answer counts 1 and a partly right one 0.5. Each group has between 8 and 30 questions. Blueprint internals, and most of the inheritance and effective-flags groups, come from the harder questions described below.</sub>

The biggest gains are where the answer isn't in any file a text search can read. In those groups an agent without the stack doesn't fail loudly; it makes something up. That's why the wrong answers matter most: **26 against none on the everyday questions, and 11 against none on the harder ones.** An agent that confidently tells you a property replicates to everyone when it's `COND_OwnerOnly` costs more than it ever saved, and a confidently wrong answer is cheap, so it never shows up in the token count.

<br>

## Why a plain search misses what the stack knows

A large Unreal project keeps much of its truth where text search can't reach. The stack reads those places ahead of time and serves the result as a query.

<table>
<tr>
<td width="50%" valign="top">

**Blueprints are binary**

Part of any caller list lives in `.uasset` graphs, which text search skips without warning. The stack walks every Blueprint graph ahead of time, so "who calls this?" includes the Blueprint callers no C++ tool can see. Rename the function and it still compiles.

</td>
<td width="50%" valign="top">

**The header isn't the whole story**

UnrealHeaderTool adds flags that are never written in the source: a `const` `BlueprintCallable` quietly becomes `BlueprintPure`. A property's replication condition lives in `GetLifetimeReplicatedProps`, not beside the property. The stack records the effective flags.

</td>
</tr>
<tr>
<td width="50%" valign="top">

**Some answers need no code at all**

Platform support is resolved from plugin descriptors, using the engine's own rules. That's how the stack answers for a console on a machine with no console SDK installed.

</td>
<td width="50%" valign="top">

**Comments can be wrong**

The stack sends the agent to the function body as well as the comment above it. One benchmark question turns on a header comment that describes behaviour the code doesn't have. Reading both is how that gets caught.

</td>
</tr>
</table>

<br>

## It stays fast when the questions get hard

52 of the questions were written to need exactly what the stack holds, so they're reported separately rather than folded into the headline. Without the stack, time grows with difficulty. With it, time barely moves.

![Median seconds per question. Everyday questions: 44.1 without the stack, 27.6 with it. Harder questions: 160.8 without, 28.6 with.](docs/images/why-time-by-difficulty-light.svg#gh-light-mode-only)
![Median seconds per question. Everyday questions: 44.1 without the stack, 27.6 with it. Harder questions: 160.8 without, 28.6 with.](docs/images/why-time-by-difficulty-dark.svg#gh-dark-mode-only)

| | Without the stack | With the stack | Difference |
|:---|---:|---:|---:|
| **139 everyday questions** | | | |
| Correct, with partial credit | 68.3% | **95.0%** | +26.6 pts |
| Median time per question | 44.1 s | **27.6 s** | 1.6× faster |
| Total time | 3.59 h | **1.21 h** | 3.0× faster |
| Input tokens | 27.8M | **12.9M** | 2.2× fewer |
| Model calls (turns) | 1,841 | **867** | 2.1× fewer |
| Tool calls | 1,702 | **728** | 2.3× fewer |
| Answers outright wrong | 26 | **0** | |
| **52 harder questions** | | | |
| Correct, with partial credit | 66.3% | **96.2%** | +29.8 pts |
| Median time per question | 160.8 s | **28.6 s** | 5.6× faster |
| Total time | 3.38 h | **0.54 h** | 6.3× faster |
| Model calls (turns) | 1,413 | **401** | 3.5× fewer |
| Tool calls | 1,361 | **349** | 3.9× fewer |
| Answers outright wrong | 11 | **0** | |
| Questions that ran out of time | 2 | **0** | |

<sub>The stack carries a larger fixed context per session, 14,861 tokens against 7,615, and it still costs less on every measure, because it needs far fewer calls to reach an answer. All figures include that fixed cost.</sub>

<br>

## What's in the stack

Six layers, each there because the one below it can't answer a particular kind of question. Any one can fail without sinking the rest. The [README](README.md#the-stack) goes through them in detail.

| Layer | What it is | What only it can answer |
|:---:|:---|:---|
| **5** | Design docs | Why a system is built the way it is |
| **4** | Instruction files with a routing table | Which layer to ask, so the agent stops grepping out of habit |
| **3** | Engine API store | What a module declares, and where it's available, for targets you never built |
| **2** | The reflection dump, one file per class and Blueprint | Effective flags, replication conditions, Blueprint callers |
| **1** | Symbol index, clangd fronted by Serena | Definitions and references resolved by a real C++ front end |
| **0** | `compile_commands.json` | Nothing on its own, but clangd can't parse Unreal source without it |

<br>

## Where plain search does as well

Questions about where something is defined get answered quickly either way, because the definition is usually one grep away. The stack is still more accurate there (78% to 90%), but it takes a little longer, so on that kind of question the win is accuracy rather than speed.

"Why is this built this way" still needs someone to write the design docs. The stack scores well on it only because somebody did, which is the point of Layer 5.

---

### How we measured it

Both agents used the same model on the same 191 questions. The one without the stack ran in a clean copy of the tree holding only source, config and content, with five built-in tools and nothing we built: no language server, no MCP server, no rules files. The rule behind that is the one part of this that isn't a judgement call, so it's worth stealing: **the baseline gets nothing we built, and the codebase it's asked about isn't altered.**

Every answer was graded against a key three times, independently, and the majority grade is what's shown. Before publishing, every key that marked the stack down was re-derived from source, and eleven turned out to be wrong. The figures here use the corrected keys, and the corrections raised both agents' scores.

Semantic code search sits on the stack's side of that line, so these numbers answer "is this worth building", not "is it worth adding to a codebase that already has good semantic search". Answering that needs a third arm, and we haven't run it.

The full result, with its caveats and the questions we couldn't explain, is in [arm-comparison-v6.md](plugins/ue-memory-bench/bench/arm-comparison-v6.md). Read that before quoting a number from here. Group figures carry weight; single questions don't.

**Measure your own tree.** The generator in *plugins/ue-memory-bench/bench/tools* builds a question set from your own project's artefacts. There's a much cheaper check as well: the stack plugin carries four [`claude plugin eval` cases](plugins/ue-memory-stack/evals/README.md) that check a session opens the right artefact rather than grepping. That costs cents per commit and tells you routing works. It isn't a result.

<p align="center"><b><a href="README.md#install">Install the stack →</a></b></p>
