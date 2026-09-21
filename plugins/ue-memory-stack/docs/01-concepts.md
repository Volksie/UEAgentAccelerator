# What each layer can and can't answer

The layers exist because no single tool answers everything about an Unreal codebase, and the ones that look like they do are the dangerous ones. This is what each layer actually knows, and where it goes quiet.

## Layer 0, the compile database

Answers nothing on its own. It's a list of every translation unit and the exact flags it compiles with, written by UnrealBuildTool, and it exists so Layer 1 can exist.

Worth knowing about it:

- It isn't incremental. Every run rebuilds the whole map and rewrites the file.
- Every entry is written with absolute paths, which is why moving or renaming your tree invalidates the clangd index that sits on top of it.
- It points into `Intermediate/Build`, so deleting those response files breaks clangd with an error that never mentions them.

## Layer 1, the symbol index

clangd, fronted by Serena. Compiler grounded, so when it answers it's right.

**Good at:** where a symbol is defined, what references it, the type of an expression, the members of a class, anything that follows from parsing C++ properly. It handles `TArray`, `TMap`, `GENERATED_BODY()` and the generated headers fine, given a compile database and one prior build.

**Blind to:** every reflection specifier. UnrealHeaderTool parses `UCLASS`, `UFUNCTION` and `UPROPERTY`, not the C preprocessor, so by the time clangd sees the file those macros are gone. It cannot tell you that a function is `BlueprintCallable`, and it has no idea `.uasset` files exist.

**Also worth knowing:** it's the layer most likely to come up looking healthy while bound to the wrong thing. See *05-serena-clangd.md*.

## Layer 2, the reflection dump

The commandlet in this repo, run inside the editor, walking the live reflection system and the Blueprint graphs.

This is the only layer that can answer these:

**Replication conditions.** `UPROPERTY(Replicated)` tells you a property replicates and nothing more. The condition is set in `GetLifetimeReplicatedProps`, which is runtime code, so it exists nowhere a parser can reach. An agent reading the header sees `Replicated`, answers, and has no way to know it saw half the answer.

**What UHT added.** A const `BlueprintCallable` `UFUNCTION` is `BlueprintPure`, and the header never says so. The dump reports what the reflection system holds, which is the truth, and the header is a different thing that merely looks authoritative.

**Blueprint to C++ edges.** A Blueprint graph calling a `BlueprintCallable` function is a real caller. `rg` skips `.uasset` files without a word, so a blast radius search returns C++ callers and looks complete. The edges here come from resolved graph nodes rather than name matching, which is what makes the negative form trustworthy: a class that isn't in the index has no Blueprint users. Absence means absence rather than "we didn't look".

**What one Blueprint actually is.** Parent, interfaces and a replicated count describe a Blueprint from the outside. They cannot say what it *contains*, and for a **data-only** Blueprint — no graph, the asset is its defaults — "data only: true" is the entire content of the asset withheld. `bp/<stem>.md` carries what it changed from its parent, the variables it declares, its components and widget tree, tick, functions, events, dispatchers, timelines, and what loading it drags in.

Changes live in **four** different places — class defaults, component templates, inherited-component overrides, and components built in a C++ constructor — and they are kept apart, because a query that merges them cannot answer "what does this *class* default to" separately from "what does this *component* default to". A Blueprint can also **replace** a native component's class outright; that is diffed against the parent's template rather than the new class's defaults, which is what separates a value the designer retuned from one that is merely serialised.

**Blueprint to Blueprint edges.** A call into another Blueprint's function, or a `Cast To`, is invisible to every compile-time tool for the same reason a call into C++ is. These get their own reverse index and are deliberately kept out of the C++ one, because blast-radius counts depend on that index meaning exactly what its name says.

**What assets exist, without loading them.** A DataTable's row struct, a StateTree's schema — read from registry tags, which is what makes it affordable on a project with thousands of assets. It covers enabled content only, and says which plugins it skipped.

**What a key is bound to.** A binding lives in no registry tag, so this tier loads — and it also carries the translation between the `FKey` an asset stores and the name a person says out loud.

**What it can't do:** anything about code that isn't reflected. A plain C++ virtual with no `UFUNCTION` is invisible to it, deliberately. That's a real gap and Layer 1 covers it.

## Layer 3, the engine API surface

A UHT exporter. It rides the UnrealHeaderTool run that every build already does, so it can describe modules for platforms you have never built for.

It **cannot** produce replication conditions, and mustn't pretend to. UHT sees `Replicated` and `ReplicatedUsing` and stops, because the condition doesn't exist until runtime. Absence and ignorance have to look different, so the field stays null here and is written by Layer 2 instead.

## Layer 4, the curated instruction files

*CLAUDE.md* and *.claude/rules/*. Free, always loaded, and the layer that decides whether any of the others get used.

This is the one people underrate. The artefacts are just files in a folder; what makes an agent open the right one instead of grepping out of habit is a routing table telling it which layer answers which question.

The clearest evidence came from a row that was wrong. Our routing table sent five kinds of question to `search_for_pattern`, and Serena's stock context removes that tool, so the row pointed at nothing. Across 170 benchmark questions the stack arm called it zero times, and we spent a version reading that as the agent preferring Grep. It never had the choice. The routing table decides which tools get used, so it can also quietly stop them being used.

*(An earlier version of this page cited a group of aggregate questions answered by grep instead of the database as the evidence. That diagnosis didn't survive a closer look at the questions and is withdrawn: most of them were about a single class, where not querying the database was correct.)*

It's also the layer that rots silently. Everything in it is loaded on every question and believed, so a line that stops being true is worse than a line that was never there. Ours told people to invoke the commandlet under a module name that had changed weeks earlier, sitting directly above a paragraph that gave the right one.

And it is read by sessions you were not thinking about. We added a line asking sessions to log what they change before finishing, which is right for interactive work. Benchmark agents have no write tool, so they hit that instruction mid-answer and spent turns trying to comply: 34 of 170 answers mention it, including three of the four questions that ran past the time ceiling. **Before adding a line here, ask what it does to a session that cannot act on it.**

## Layer 5, the design documents

Why a system is built the way it is: what was tried, what went wrong with it, and which numbers came from playtesting rather than from a constraint.

Nothing else in the stack can answer this, because it isn't in the code. The 2 second regen pause in the seed project is a playtest result; the code can tell you it's 2 and nothing else.

Front matter naming the modules and classes a document governs is what makes it findable from a class name rather than by guessing filenames.

## Comments are not answers

For anything about units, ranges, bounds or contracts, read the body as well as the comment.

The seed project has `GetReachDistance` with a comment saying the value is in metres over a body returning centimetres, deliberately. Measured both ways: hover answered "metres", because hover returns the comment and there is nothing in it to disagree with. Plain file reading answered centimetres and flagged the disagreement.

So on that class of question the cheap route is also the accurate one, which is not the usual shape of this trade.

## Escalate cheapest first

The layers only pay off if a query starts at the cheapest one that can answer it:

> *CLAUDE.md* is free. Then the reflection dump, then a symbol query, then hover, then whole files.

Two size rules that matter in practice:

- Grep the indexes rather than reading them. `index.md` is one row per class and gets large; on a big project it is around 12,600 tokens.
- Check a class file's size before reading it whole. The median is around 1 KB but the distribution has a tail, and the biggest we have seen is 32 KB. On one replication question, reading that file whole cost about 33,000 bytes against 8,132 for a grep. Both answered correctly and one paid four times over.

## Any layer can fail without sinking the rest

That's the point of building them separately. Layers 2, 4 and 5 are cheap, portable and entirely under your control. Layers 0 and 1 are where the leverage is and where your toolchain gets a vote.

Build 4 and 2 first. Done that way, a total Layer 1 failure still leaves you better off than you were, which is what makes the whole thing safe to start.
