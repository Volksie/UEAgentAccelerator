<h1 align="center">UE Agent Accelerator</h1>

<p align="center"><i>Your agent can't read what UnrealHeaderTool wrote.</i></p>

<p align="center">
A layered memory stack for running coding agents on an Unreal Engine codebase.<br> It writes down what your project actually looks like at runtime, in files small enough to read, and tells the agent which one to open.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/licence-MIT-blue.svg" alt="MIT licence">
  <img src="https://img.shields.io/badge/Unreal%20Engine-5.8%2B-black.svg" alt="Unreal Engine 5.8+">
  <img src="https://img.shields.io/badge/version-0.4.2-orange.svg" alt="Version 0.4.2">
  <img src="https://img.shields.io/badge/scripts-Windows-lightgrey.svg" alt="Windows scripts">
</p>

<p align="center">
  <a href="#the-problem">The problem</a> &middot;
  <a href="#why-its-needed">Why it's needed</a> &middot;
  <a href="#the-stack">The stack</a> &middot;
  <a href="#install">Install</a> &middot;
  <a href="#what-you-get">What you get</a> &middot;
  <a href="#routing">Routing</a> &middot;
  <a href="#docs">Docs</a>
</p>

---

## The problem

Coding agents do reasonably well on most codebases and badly on Unreal ones. A lot of what you need to know about a UE class isn't in the source: UnrealHeaderTool adds some of it and the engine assembles the rest at runtime, so an agent reading headers can't see it and has no way of knowing what it missed.

Here's a property from the seed project in this repo. This is the whole declaration:

```cpp
UPROPERTY(Replicated, BlueprintReadOnly, Category="AccelDemo|Stamina")
float Stamina = 100.0f;
```

Ask an agent what condition it replicates under and it'll tell you what the header says, which is nothing. The condition is set in `GetLifetimeReplicatedProps`, which is runtime code. Here's the same property as the dump sees it:

```
| Property  | Type    | Specifiers                | Replication    |
| `Stamina` | `float` | BlueprintReadOnly, Replicated | COND_OwnerOnly |
```

Same for specifiers, in the other direction: a const `BlueprintCallable` `UFUNCTION` is pure and the header never says so, because UHT adds it.

And then there's blast radius, which is the one that actually bites. A Blueprint graph calling a `BlueprintCallable` function is a real caller, and no C++ tool can see it. `rg` skips *.uasset* files without a word, so "who calls this" comes back with the C++ callers and looks complete. Rename the function and it still compiles.

You can get all three, but only by asking the live reflection system, which means running inside the editor. That's what the plugin in here does, and it's one layer of six.

---

## Why it's needed

We gave the same model the same 191 questions about a large Unreal codebase twice. The first time it had shell and text search. The second time it also had this stack. With the stack it got more right, got nothing outright wrong, and took a fraction of the time and tokens to get there.

On the 139 everyday engineering questions:

| | Without the stack | With the stack |
|---|---|---|
| Correct, with partial credit | 68.3% | **95.0%** |
| Answers outright wrong | 26 | **0** |
| Total time | 3.6 hours | **1.2 hours** |
| Model calls (turns) | 1,841 | **867** |

The questions cover three projects on Unreal Engine 5.8.3: Epic's Lyra sample game, an open source plugin and the small seed project in this repo.

### The gap is widest on the questions that cost you most

These are real questions from the run, with each agent's time and whether it got the answer right.

| Question | Without the stack | With the stack |
|---|---|---|
| Which Blueprint is called into by other Blueprints most often, and how many have callers at all? | 865 s, 110 turns, 4.4M tokens. Wrong | 19 s, 7 turns. Right |
| Which custom events in Lyra's Blueprints are RPCs, and which of those are reliable? | Ran out of time at 900 s, no answer | 20 s, 7 turns. Right |
| Which Blueprint reads `NumBotsToCreate`, and how many nodes in it do so? | 828 s, 53 turns, 1.0M tokens. Right | 14 s, 3 turns. Right |
| If I rename `OnlineMode`, which Blueprint graphs break? C++ and Blueprint, the full list | 825 s, 62 turns, 2.9M tokens. Right | 40 s, 9 turns. Right |
| How many plugins in this engine have a Runtime module that isn't available on a particular console? | Wrong | Right, on a machine with no console SDK installed |

Even where both get there, the agent without the stack spends about 14 minutes and more than a million tokens rebuilding from raw asset bytes what the stack already holds. You pay that again on every question like it.

### It's better in every area we measured

The questions fall into eleven groups. With the stack the agent scores higher in all eleven.

| Kind of question | Without | With |
|---|---|---|
| Engine API and platform support | 20% | **100%** |
| Blueprint internals | 57% | **100%** |
| Build, tooling and procedure | 52% | **95%** |
| What makes things expensive | 63% | **94%** |
| Inheritance and ancestry | 63% | **92%** |
| What comments and docs say | 70% | **93%** |
| Reflection and replication | 80% | **98%** |
| What breaks if I change this | 82% | **96%** |
| Where things are defined | 78% | **90%** |
| Effective flags and writers | 87% | **93%** |
| Trick questions | 95% | **100%** |

Scores use partial credit, so a fully right answer counts 1 and a partly right one counts 0.5. Each group has between 8 and 30 questions.

The biggest gains are where the answer isn't in any file a text search can read. In those groups an agent without the stack doesn't fail loudly. It makes something up. That's why I'd look hardest at the wrong answers, 26 against none on the everyday questions and 11 against none on the harder ones: an agent that confidently tells you a property replicates to everyone when it's `COND_OwnerOnly` costs more than it ever saved, and a confidently wrong answer is cheap, so it never shows up in the token count.

### It stays fast when the questions get hard

52 of the questions were written to need exactly what the stack holds, so we report them separately rather than fold them into the headline. Without the stack, time goes up with difficulty. With it, time barely moves.

| | Without the stack | With the stack |
|---|---|---|
| **139 everyday questions** | | |
| Correct, with partial credit | 68.3% | **95.0%** |
| Answers outright wrong | 26 | **0** |
| Median time a question | 44.1 s | **27.6 s** |
| Input tokens | 27.8M | **12.9M** |
| **52 harder questions** | | |
| Correct, with partial credit | 66.3% | **96.2%** |
| Answers outright wrong | 11 | **0** |
| Median time a question | 160.8 s | **28.6 s** |
| Ran out of time | 2 | **0** |

The stack costs more context up front, 14,861 tokens a session against 7,615, and it still comes out cheaper on every measure because it needs far fewer calls to reach an answer. All the figures above include that fixed cost.

### Where plain search does as well

Questions about where something is defined get answered quickly either way, because the definition is usually one grep away. The stack is still more accurate there (78% to 90%), but it takes a little longer, so on that kind of question the win is accuracy rather than speed.

"Why is this built this way" still needs someone to write the design docs. The stack scores well on it only because somebody did, which is the point of Layer 5.

### How we measured it

Both agents used the same model on the same questions. The one without the stack ran in a clean copy of the tree holding only source, config and content, with five built-in tools and nothing we built: no language server, no MCP server, no rules files. The rule behind that is the one part of this that isn't a judgement call, so it's worth stealing: **the baseline gets nothing we built, and the codebase it's asked about isn't altered.**

Every answer was graded against a key three times, independently, and the majority grade is what's shown. Before publishing, every key that marked the stack down was re-derived from source, and eleven turned out to be wrong. The figures here use the corrected keys, and the corrections raised both agents' scores.

**Note:** semantic code search sits on the stack's side of that line, so these numbers answer "is this worth building", not "is it worth adding to a codebase that already has good semantic search". Answering that needs a third arm, and we haven't run it.

The full result, with its caveats and the questions we couldn't explain, is in *[plugins/ue-memory-bench/bench/arm-comparison-v6.md](plugins/ue-memory-bench/bench/arm-comparison-v6.md)*. Read that before quoting a number from here. Group figures carry weight, single questions don't.

If you'd rather not take our word for it, the generator in *plugins/ue-memory-bench/bench/tools* builds a question set from your own project's artefacts, so you can measure your own tree. There's a much cheaper check as well: the stack plugin carries four [`claude plugin eval` cases](plugins/ue-memory-stack/evals/README.md) that check a session opens the right artefact rather than grepping. That costs cents per commit and tells you routing works. It isn't a result.

---

## The stack

| Layer | What it is | Where it comes from |
|---|---|---|
| **5** | Design docs, with front matter naming the modules they govern | You write them |
| **4** | Curated instruction files, *CLAUDE.md* and *.claude/rules/\*.md* | Templates in here, you adapt them |
| **3** | Engine API store: what is declared, for targets you never built | In here, opt-in |
| **2** | The reflection dump, one Markdown file per class | The plugin in here |
| **1** | Symbol index, clangd fronted by Serena | Installed separately |
| **0** | `compile_commands.json` | UnrealBuildTool, script in here |

Each one exists because the layer below it cannot answer a particular kind of question. Taking them from the bottom:

**Layer 0** is `compile_commands.json`, written by UnrealBuildTool. It answers nothing on its own and it is not optional either: it records the exact flags every translation unit compiles with, and without it clangd cannot parse Unreal source at all. Generated code, module include paths and the macro soup mean a C++ parser given a UE file and no flags produces nonsense.

**Layer 1** is the symbol index: clangd, fronted by Serena. Definitions, references, call hierarchies and types, all resolved by a real C++ front end, so when it answers it is right. You need it because text search is wrong often enough to matter on a codebase this inheritance-heavy: `rg` cannot tell a definition from a mention, an override from the virtual it overrides, or your `Tick` from the two hundred others. What it cannot see is anything the reflection system holds, because UnrealHeaderTool parses the macros and by the time clangd sees the file they are gone.

**Layer 2** is the reflection dump, and it is the one this repository exists to provide. It runs a commandlet inside the editor, walks the live reflection system and the Blueprint graphs, and writes one small Markdown file per class. It is the only layer that can answer the three questions above, because all three are decided at runtime or by UHT and none of them survive into anything a parser reads. Without it they do not go unanswered, which would be fine: they get answered confidently and wrongly.

**Layer 3** is the engine API store. UnrealHeaderTool emits what every module declares, on-disk descriptors say what exists and where it is available, and the two merge into one queryable store with a small MCP server over it. It answers "is this module available on that platform" for platforms you have never built for, because declared availability is resolved by the engine's own function rather than by your toolchain — and it is the only layer that indexes comment *bodies*, so a `// HACK:` inside a function is findable. Layer 2 can do neither: it sees only what the editor you are running actually loaded, and only the doc comment attached to a reflected declaration.

**Layer 4** is the curated instruction files: *CLAUDE.md* and the per-module rules. It holds the routing table that says which layer answers which kind of question. This is the layer people underrate and it is the one that decides whether any of the others get used: the artefacts are just files in a folder, and what makes an agent open the right one instead of grepping out of habit is being told to.

**Layer 5** is the design documents. Why a system is built the way it is, what was tried and rejected, and which numbers came from playtesting rather than a constraint. Nothing else in the stack can answer that because it is not in the code: the seed project's regeneration pause is two seconds because of a playtest, and the code can tell you it is two and nothing more.

They are deliberately independent, so any one can fail without sinking the rest. Layers 2, 4 and 5 are cheap and entirely under your control. Layers 0 and 1 are where the leverage is and also where your toolchain gets a vote, so build 4 and 2 first and treat the rest as an upgrade. Done in that order, even a total Layer 1 failure leaves you better off than you were, which is what makes it safe to start.

*plugins/ue-memory-stack/docs/01-concepts.md* goes through what each layer can and cannot answer in more detail, including where each one goes quiet.

---

## Install

You need Unreal Engine 5.8 or later, a C++ project that builds, and PowerShell.

It ships as a Claude Code plugin, and this repository is its marketplace:

```bash
claude plugin marketplace add Volksie/UEAgentAccelerator
claude plugin install ue-memory-stack@ue-agent-accelerator --scope project
```

`--scope project` records it in your project's *.claude/settings.json*, so the tree carries which plugin it wants and at which marketplace. It does **not** install it for the next person: Claude Code documents that a plugin only a project's settings enables doesn't load until that person installs it, so everybody runs those two commands once. **And a project-scope plugin loads only after the workspace trust prompt is accepted** — dismiss that and you get a session with no plugin and no error.

Then, in a session in your project, two commands:

```
/ue-memory-stack:setup     the C++ plugin, the descriptor entry, the stack config, the templates
/ue-memory-stack:update    build the editor target, generate the artefacts, verify them
```

Setup writes each thing only when it is absent, so running it again on a finished tree changes nothing and says so. `-Check` reports instead of writing, which is also how a tree finds out it is still carrying the C++ plugin from before the last update. After that, `/ue-memory-stack:status` tells you whether the artefacts still describe the code, and `/ue-memory-stack:doctor` checks the layers that fail without saying anything — an uninstalled plugin, a stale DLL, a Serena an upgrade has quietly unpatched.

Two things it cannot do for you, and they are the two that matter:

**Write the routing table.** Setup puts the template at your tree root as *CLAUDE.md*. Rewriting it for your tree is an hour, it is prose about your own codebase so nobody else can write it, and nothing makes an agent open the right artefact instead of grepping out of habit except this file.

**Finish the tree's facts.** Setup fills in *.claude/agent-memory-stack.json* from what it can see and leaves `<ANGLE BRACKET>` placeholders where it can't — your engine path, your Serena project. Grep it for `<`. Once it is complete, `-StackConfig` replaces every path argument, and setup and refresh cannot disagree about which projects exist — a disagreement that shows up as artefacts nobody regenerates and no symbol query can see.

<details>
<summary>Other ways in</summary>

**No GitHub on your machines?** That is the normal case on a Perforce team, and it works without anybody cloning anything. One person runs `tools/Export-ToDepot.ps1`, which copies the marketplace into the depot along with an *Install-FromDepot.ps1*, and writes the project's *.claude/settings.json*. Everybody else syncs and runs that one script, once. **A committed settings file cannot install a plugin** — Claude Code documents that a plugin only a project's settings enables does not load until the person installs it, and it fails by simply not being there. [Installing from a depot](plugins/ue-memory-stack/docs/09-installing-from-a-depot.md) has the whole route and the traps.

**Sharing one copy of the C++ plugin between projects.** `-Mode Reference -PluginSource <shared path>`, on the setup script or the install script under it. That writes an `AdditionalPluginDirectories` entry pointing at the folder holding the shared copy, instead of copying anything. **Give it a path your whole team has** — a depot or a share. Without `-PluginSource` the entry points inside the plugin's own folder, which is the plugin manager's to move and is on nobody else's machine; the editor then has no plugin and says nothing. It warns when it is about to do that.

**The binaries are per project either way.** Sharing the source does not share the DLL, so every project needs its own build. Building one project and dumping another writes old format files, reports success and exits 0.

**Not on Windows.** Nothing in the C++ plugin is Windows specific, the scripts just are. Copy the plugin into *Plugins*, enable it, build, and run the commandlet yourself:

```
UnrealEditor-Cmd <project>.uproject -run=UEAgentAcceleratorTools.AgentMemoryDump \
  -unattended -nopause -nosplash -NullRHI -Multiprocess
```

Three of those arguments are load bearing and *plugins/ue-memory-stack/docs/03-running-the-dump.md* explains which and why.

**Try it on the seed first.** *seed/AccelDemo* is three modules and three gameplay classes, with the plugin already wired up through a relative path, so it needs no setup step. Build it, dump it, compare against *examples/*. Ten minutes, and it means you know what right looks like before your own project goes wrong.

</details>

---

## What you get

One run writes this into *Docs/AgentMemory*:

| File | Answers |
|---|---|
| `index.md` | One row per class: module, parent, counts, link. Grep it, don't read it |
| `classes/<Class>.md` | Specifiers, `COND_*` replication and doc comments for one class |
| `Blueprints.md`, `blueprints/<Parent>.md` | Which Blueprints derive from what, implement which interfaces, replicate, or hold no logic |
| `BlueprintCallers.md`, `bpcallers/<Class>.md` | Which Blueprint graphs call a C++ function or touch a C++ property, and which widgets bind one by name |
| `bp/<Blueprint>.md` | What one Blueprint actually is: what it changed from its parent, its variables, components, functions, events, tick, and what loading it drags in |
| `bpusers/<Blueprint>.md` | Which Blueprints call into this Blueprint or cast to it. The opposite question to `bpcallers/`, and no C++ tool sees either |
| `Assets.md`, `assets/<Class>.md` | What assets exist of a class, from registry tags, without loading anything |
| `Input.md`, `inputkeys/<Key>.md` | What a key is bound to, in every input context it appears in |

Real output, from the seed project:

```markdown
# ADStaminaComponent

Module `AccelDemoCore`. Generated by the AgentMemoryDump commandlet, do not hand edit.

- Inherits: ActorComponent -> Object

## Summary

5 functions, 5 properties, 2 replicated.

| Replicated property | Type    | Condition      | OnRep            |
|---|---|---|---|
| `bExhausted`        | `bool`  | COND_None      | OnRep_Exhausted  |
| `Stamina`           | `float` | COND_OwnerOnly | -                |
```

The summary block comes first on purpose, so reading the top of any file answers shape and replication without loading the prose underneath it.

It's deterministic and contains no absolute paths, so commit it next to the code it describes and it diffs sensibly.

The Blueprint edges come from resolved graph nodes rather than name matching, so a class that isn't in the index has no Blueprint users. Absence means absence rather than "we didn't look", which is what makes it safe to answer a blast radius question with "nothing".

That claim is only worth as much as what the walk covers, so the walk says: event, function **and macro** graphs — a macro is expanded into its callers at compile time, so the real call lives in the macro's own graph — plus `bind`, a C++ `BindWidget` or `BindWidgetAnim` property bound *by name* to a widget or animation in a Widget Blueprint's designer tree. That last kind has no graph node at all, the widget compiler enforces it, and renaming the C++ property breaks the Blueprint while compiling clean. Not covered: uses of a *class* rather than a member, such as component templates and variable types. `BlueprintCallers.md` states its own coverage in one line — how many Blueprints exist, how many are data-only and so have no graphs by construction, how many were walked — so a reader can tell a complete walk from a partial one instead of trusting the word "complete".

---

---

## Routing

None of this pays off unless a query starts at the cheapest layer that can answer it, and that ordering lives in the *CLAUDE.md* you write from the template:

> This file is free. Then the reflection dump, then a symbol query, then hover, then whole files. That last one is where we all started before any of this existed.

A few rows from the template, to give you the idea:

| Question | First stop | Fallback |
|---|---|---|
| Where is X defined | `find_symbol_indexed`, clangd's whole-tree index | Grep for the file, then `find_symbol` scoped to it |
| What does X derive from, the whole chain | `classes/<Class>.md`, the `Inherits:` line | the index gives the immediate parent only |
| Is X replicated, under which `COND_` | `classes/<Class>.md` | nothing else can answer this |
| Who calls X | `find_referencing_symbols` **and** `bpcallers/<Class>.md`, both, always | ripgrep, C++ only, and it'll be wrong |
| Units, ranges, bounds | the artefact **and** the body | the comment alone isn't an answer |
| Why is this built this way | *Docs/Design/\*.md* | source history |

That last row but one is there because of a real case. The seed project has a function whose comment says metres over a body returning centimetres, deliberately, and hover answers "metres" every time because it returns the comment with nothing to contradict it.

---

## Docs

| | |
|---|---|
| [Getting started](plugins/ue-memory-stack/docs/00-getting-started.md) | Nothing to a working stack on your own project |
| [Concepts](plugins/ue-memory-stack/docs/01-concepts.md) | What each layer can and can't answer |
| [Installing the plugin](plugins/ue-memory-stack/docs/02-install-plugin.md) | Copy or reference, and the per project binaries trap |
| [Running the dump](plugins/ue-memory-stack/docs/03-running-the-dump.md) | The invocation, and the three flags that aren't optional |
| [Writing your CLAUDE.md](plugins/ue-memory-stack/docs/04-writing-your-claude-md.md) | The routing table, row by row |
| [Serena and clangd](plugins/ue-memory-stack/docs/05-serena-clangd.md) | Layers 0 and 1, and how they fail quietly |
| [Serena for Unreal trees](plugins/ue-memory-stack/serena/README.md) | What a stock Serena gets wrong on an engine tree, where the fixes come from, and how to check they're live |
| [The plugin itself](plugins/ue-memory-stack/README.md) | Its commands and skills, and what it installs into a project |
| [Keeping it fresh](plugins/ue-memory-stack/docs/06-keeping-it-fresh.md) | When to regenerate, and how to catch a stale artefact |
| [Benchmarking](plugins/ue-memory-stack/docs/07-benchmarking.md) | Measuring your own tree |
| [The eval suite](plugins/ue-memory-stack/evals/README.md) | The per-commit routing check, and why it is not the benchmark |
| [Layer 3, the engine API](plugins/ue-memory-stack/docs/08-layer3-engine-api.md) | The exporter, the store and its server |
| [Installing from a depot](plugins/ue-memory-stack/docs/09-installing-from-a-depot.md) | Perforce teams: one person installs it, everybody else syncs |
| [The hooks](plugins/ue-memory-stack/docs/10-hooks.md) | What they do, what they cost in milliseconds, and why one ships off |
| [Migrating](plugins/ue-memory-stack/docs/11-migrating.md) | From a clone-era install onto the plugin, and what rollback actually means |
| [Troubleshooting](plugins/ue-memory-stack/docs/troubleshooting.md) | 0 modules, 0 Blueprints, stale DLLs, and clangd |

And the benchmark's own documents, which are worth reading before quoting any number above:

| | |
|---|---|
| [The result](plugins/ue-memory-bench/bench/arm-comparison-v6.md) | The measured comparison in full, and the caveats that go with it |
| [Method](plugins/ue-memory-bench/bench/METHOD.md) | How the questions are chosen, how isolation is proven, and what each figure is allowed to mean |
| [The baseline arm](plugins/ue-memory-bench/bench/BASELINE-ARM-SPEC.md) | What the arm it is measured against is, and the argument for drawing the line there |
| [Question defects](plugins/ue-memory-bench/bench/QUESTION-DEFECTS.md) | The broken questions, left in the set on purpose, with what excluding them would change |

---

## What's in the repo

| Path | What it is |
|---|---|
| `plugins/ue-memory-stack/` | Everything that ships: scripts, the Serena installer, the guides, the commands and skills, and the templates written into a project |
| `plugins/ue-memory-stack/ue-plugin/UEAgentAccelerator` | The C++ plugin. Editor only, no dependency on any game module, works on any project |
| `plugins/ue-memory-bench/` | The benchmark, as a separate plugin: two commands, one skill, ~183 always-on tokens, and nobody pays them unless they install it |
| `tools/` | Maintainer scripts for this repository: the two-tree sync, and the depot export a Perforce team's first developer runs |
| `seed/AccelDemo` | A tiny known good project with the plugin already wired up |
| `plugins/ue-memory-bench/bench/` | Question generator, key checker, clean-room builder, runner, judge, and the method behind them |
| `plugins/ue-memory-stack/evals/` | Four `claude plugin eval` cases asking whether the instructions route a session to the right artefact |
| `examples/` | The seed project's real generated output, so you can see what you get |

Serena and clangd aren't in here because we don't ship them. *plugins/ue-memory-stack/docs/05-serena-clangd.md* covers installing them, and more usefully the two ways Layer 1 comes up looking healthy while bound to the wrong thing.

---

## Status

Layers 2, 3, 4 and 5 are what we use daily and what the benchmark measures. Layers 0 and 1 work, and they're the parts most likely to argue with your toolchain.

Layer 3 has three parts: the UHT exporter under *ue-plugin/UEAgentAccelerator/Source/UEAgentAcceleratorUht*, a store that merges what it emits with on-disk descriptors and the Layer 2 artefacts, and a six-tool MCP server over the result — both of the latter in *plugins/ue-memory-stack/engine-api/*, Python, no dependencies. It answers what the other layers structurally cannot: whether a module is available on a console you have never built, and what a comment three lines into a `.cpp` says. The exporter runs only when asked (`-AgentMemoryApi`), and the database is yours to build and is not in this repository. See *plugins/ue-memory-stack/docs/08-layer3-engine-api.md*.

## Licence

MIT, see [LICENSE](LICENSE). You need Unreal Engine, which you licence from Epic yourself, and Layer 1 needs tools we don't ship. [NOTICE.md](NOTICE.md) has the details.

Unreal and Unreal Engine are trademarks of Epic Games, Inc. This project isn't affiliated with or endorsed by Epic Games.
