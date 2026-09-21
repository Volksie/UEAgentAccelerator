---
name: ue-memory-layers
description: Answer questions about an Unreal C++ codebase from the generated memory layers rather than by grepping - replication conditions and COND_, reflection specifiers like BlueprintCallable, what Blueprints call a C++ function, inheritance chains, where a symbol is defined, and what each layer cannot answer. Triggers on "is this replicated", "under which COND_", "what calls this", "blast radius", "which Blueprints derive from", "where is X defined", "is it BlueprintCallable", and on any question about a UCLASS, UFUNCTION or UPROPERTY.
---

# Answering from the layers

A lot of what you need to know about an Unreal class is not in the source. UnrealHeaderTool adds some of it and the engine assembles the rest at runtime, so reading the header gives you an answer that looks complete and is not. These artefacts are that missing half, written down.

**Route to the cheapest layer that can answer, and check the project's own `CLAUDE.md` first** — its routing table names the paths for this tree, and it wins over anything here.

## What answers what

| Question | Go to | Never |
|---|---|---|
| Is X replicated, under which `COND_` | `<Project>/Docs/AgentMemory/classes/<Class>.md` | clangd, the header |
| Is X `BlueprintCallable`, `BlueprintPure`, any specifier | the same file | the header |
| What Blueprints call X, blast radius | `bpcallers/<OwningClass>.md` **and** the C++ side, both | ripgrep alone |
| Which Blueprints derive from X | `Blueprints.md`, then `blueprints/<Parent>.md` | |
| What one Blueprint IS — variables, components, tick, functions, what it changed from its parent | `bp/<stem>.md`, linked from the *Detail* column of `blueprints/<Parent>.md` | opening the asset |
| A tuning value a designer set, and what it would have been | `v_bp_tuning` in the store, or the *Changed from the defaults* table in that Blueprint's `bp/` file | guessing from the parent class |
| What calls into **this Blueprint**, or hard-references it with a cast | `bpusers/<stem>.md` | `bpcallers/`, which answers the C++ question and holds none of these |
| Does it tick, and does the tick do anything | the *Tick* section of its `bp/` file, or `v_bp_tick_cost` | one flag on its own |
| What assets exist of a class, a DataTable's row struct | `Assets.md`, then `assets/<Class>.md` | loading the asset |
| What a key is bound to, or which keys reach an action | `inputkeys/<Key>.md`, or `v_input_key` | grepping the `.uasset` |
| The full inheritance chain | the `Inherits:` line in `classes/<Class>.md` | `index.md`, which gives the immediate parent only |
| Where is X defined | `find_symbol_indexed` if Serena is set up, else Grep | unscoped `find_symbol` |
| Why is it built this way | `Docs/Design/*.md` | the code |

**Five traps worth knowing before you answer:**

- **A `UPROPERTY(Replicated)` tells you nothing about the condition.** The `COND_` lives in `GetLifetimeReplicatedProps`, which is runtime code. An agent that reads the header and answers has seen half the truth and cannot tell.
- **A Blueprint caller is invisible to every C++ tool.** `rg` skips `.uasset` silently and renaming the function still compiles. The Blueprint index is built from resolved graph nodes, so **a class absent from it genuinely has no Blueprint users** — absence is an answer, not a gap.
- **Comments are not answers about units, ranges or bounds.** Read the body too. The seed project has `GetReachDistance` commented "in metres" over a body returning centimetres, deliberately, and hover answers "metres" every time.
- **`bpcallers/` and `bpusers/` are one letter apart and answer opposite questions.** The first is *which Blueprints use this C++ symbol*; the second is *which Blueprints use this Blueprint*. Nothing from the Blueprint-to-Blueprint walk is ever written into the first, because answer keys and blast-radius counts depend on what a row there means. Reach for the wrong one and you get a confident, complete, wrong answer.
- **A missing file and an empty one mean different things.** Check the *What this set contains* table in `MANIFEST.md` before concluding a tier is empty: a count of **0** means the walk ran and found none, while **not in this set** means these artefacts predate that tier. Every tier is emitted even when empty precisely so that distinction survives.

## Before you trust an answer

Check the artefacts describe the code as it is now. `/ue-memory-stack:status` says; `${CLAUDE_PLUGIN_ROOT}/docs/06-keeping-it-fresh.md` explains why a timestamp cannot.

**Never hand-edit anything under `Docs/AgentMemory/`.** It is generated, and editing it destroys the thing you are reading from. Regenerate instead.

## Going deeper

- `${CLAUDE_PLUGIN_ROOT}/docs/01-concepts.md` — what each layer can and cannot answer, and where each one goes quiet.
- `${CLAUDE_PLUGIN_ROOT}/docs/04-writing-your-claude-md.md` — writing the routing table this all depends on.
- `${CLAUDE_PLUGIN_ROOT}/docs/troubleshooting.md` — an answer that is confidently wrong usually has a cause in here.
