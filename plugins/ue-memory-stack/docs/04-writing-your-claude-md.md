# Writing your CLAUDE.md

This is the step people skip and the one that does most of the work. Generating the artefacts takes a few minutes; writing this takes an hour and is worth more.

The reason is simple. The artefacts are files in a folder. Nothing makes an agent open the right one rather than reaching for ripgrep out of habit except a file telling it which layer answers which kind of question. In our v4 run the arm with the whole stack took the route its routing table named on 142 of 170 questions — a *within-arm* diagnostic, not a comparison, and the v5 run retired the pooled figure for that reason: most expected routes name a layer artefact, and the baseline room has never held one, so it cannot match whatever it answers. `plugins/ue-memory-bench/bench/tools/route_split.py` reports the split that means something. When a row was wrong, the arm followed that too: a row naming a tool the server didn't expose got called zero times in 170 questions, and nothing reported it.

Start from *../templates/CLAUDE.md.template*.

## Keep it short

Everything in here is loaded into every session and paid for **on every turn**, not once per question, used or not. That distinction is the whole of this section and we got it wrong ourselves for a while: a multi-turn answer pays for your routing table once per turn of the conversation, so a file that looks like a fixed cost is really a cost multiplied by how long the agent thinks.

Measured on our own tree in the v3 run, across 170 questions and both arms: 17,039 input tokens a turn against 8,387 for an agent carrying none of it. Turn counts were within 5% of each other, so that whole gap is standing context rather than extra work — the stack arm was not doing more, it was paying more for each thing it did. It still won by 17.3 points, but the margin was carrying a passenger.

Ours sits between 100 and 200 lines. Two consequences:

- Cut anything an agent can work out for itself. A summary of what your classes do is expensive and it's already in the artefacts.
- A long file is more surface to rot, and a stale line here is believed.

### Put per-project notes in the project, not in the root

The useful corollary, and it is a mechanism rather than advice. A `CLAUDE.md` inside a project directory is loaded **on demand**, when work is actually in that project, rather than on every turn. A rules file in the root set is loaded always.

So on a tree holding several projects, notes about one of them do not belong in the always-loaded set: every question about project A is otherwise paying for project B's and C's notes as well. Moving them was measured at **3,595 tokens a turn**, roughly 8% of a whole benchmark run, and changed no behaviour at all.

```
Tree/
  CLAUDE.md                 always loaded - keep it short
  .claude/rules/*.md        always loaded - only what is true tree-wide
  GameA/CLAUDE.md           loaded when working in GameA
  GameB/CLAUDE.md           loaded when working in GameB
```

**Note:** if a project already has its own `CLAUDE.md` that you do not own — a vendored plugin whose author wrote one — do not merge yours into it. Put your notes in a differently named file beside it and have the root `CLAUDE.md` point at it, or you will lose their content on their next update and answer questions about their file with your text.

### Ask what each line does to a session that cannot act on it

The one that cost us most was not stale and not long. It asked sessions to log what they change before finishing, which is correct for interactive work and useless to anything answering a single question read-only. Benchmark agents have no write tool, so they discovered that mid-answer: **34 of 170 answers mention trying to comply**, three of the four questions that ran past the time ceiling are among them, and on one question the arm with the stack got it wrong after 43 tool calls where the bare agent got it right in 13.

It had been checked against the byte budget and against the routing it was meant to improve. Nobody asked what else reads it. Everything in this file is read by every session in the tree, including the ones with a different job and a smaller toolset, so scope an instruction to the sessions that can follow it.

## The sections that earn their place

**What this tree is.** Two or three lines. Which directories are yours, which are read only, which are generated. The generated one matters most: an agent that hand edits *Docs/AgentMemory* has destroyed the thing it was reading.

**Build commands.** The exact invocations, because otherwise they get guessed. Include the ones with non-obvious flags and say why the flags are there, or someone will tidy them away.

**Module map.** One line per module: what it holds, what it depends on, and any rule about the direction. If your lower level module must never depend on the higher one, say so here. This is the section an agent reads before deciding where a change belongs.

**The routing table.** Below.

**Hard boundaries.** Things that look reasonable and are not. "Never modify the engine", "never commit `Binaries/`", "don't delete `Intermediate/Build` because the compile database points into it".

**Conventions that get got wrong unaided.** The UE specific ones an agent will otherwise get subtly wrong: `GENERATED_BODY()` placement, the `.generated.h` include going last, a `UPROPERTY(Replicated)` needing an entry in `GetLifetimeReplicatedProps`, a `UFUNCTION` on an interface needing redeclaring in every implementing class.

## The routing table, row by row

Two columns, first stop and fallback, one row per kind of question. Delete rows that don't apply to you: a row pointing at a tool you don't have is worse than no row, because the agent tries it, gets nothing, and falls back to grep having spent a call.

**Where is X defined.** `find_symbol_indexed`, which asks clangd's index directly and answers in about 0.1s. It's a patch, in *../serena/*, so without it: find the file with Grep, then call `find_symbol` **with `relative_path`**.

The scoping isn't a nicety. Serena's own symbol search doesn't use clangd's index. It walks every file in every workspace folder, and with the engine in the workspace an unscoped call times out. Scoped to a header, it takes 0.01–12s.

**Our first version of this row pointed at a tool that didn't exist**, which is the failure the paragraph above warns about. It said "`search_for_pattern` first". Serena's stock `claude-code` context removes `search_for_pattern`, because it duplicates Grep. So for two benchmark versions, every question that followed the row reached for nothing and fell back to Grep, and we read the zero calls as the agent's preference. Check each tool your table names against the server's live tool list, not its documentation.

That row has also aged twice, which is worth knowing because yours will too. It was right when the workspace was one small project, and stopped being right when the engine was added. Then our timings turned out to be mostly Serena's per-call file walk rather than the lookup itself.

**What does X derive from, the full chain.** Point at `classes/<Class>.md` and say **the `Inherits:` line carries the whole chain**. Say explicitly that the index gives the immediate parent only, otherwise chasing a chain through the index costs one grep per level and looks like the right route while being the slow one.

**Is X replicated, under which `COND_`.** Point at `classes/<Class>.md` and say **nothing else can answer this**. Without that, an agent will read the header, see `Replicated`, and answer confidently with half the truth. This is the row that stops the most wrong answers.

**Who calls X, blast radius.** The most important row in the table, and the one that needs the firmest wording. It must say **both, always**: the C++ tool *and* `bpcallers/<OwningClass>.md`. Not "also consider", not "if relevant". A Blueprint caller is invisible to every C++ tool, `rg` skips `.uasset` silently, and renaming the function still compiles, so a C++ only answer is wrong rather than merely partial.

Two details worth spelling out in the row itself. The index is one row per owning class, so grepping it for a member name finds nothing even when that member has Blueprint users; go by the class, or straight to the file. And a class absent from the index has no Blueprint users at all, which is a real answer to the negative form of the question and as useful as a hit.

**Units, ranges, bounds, contracts.** Say the comment alone is not an answer and the body has to be read too. Hover is actively misleading here, because it returns the comment with nothing to contradict it.

**Why is this built this way.** Point at your design docs. If you don't have any, delete the row and write one first.

**TODO, HACK, inline notes.** Text search is the only route. Say so, so nobody hunts for a cleverer one.

**Anything you have no tool for.** Worth a row saying so. Ours says nothing reads `.uasset` contents, the asset registry gives you the backing class and no more, and the honest fallback is to ask a person. A row that says "there is no route" saves more time than a row that suggests a bad one.

## Say how big things are

Two qualifications that changed behaviour more than we expected. Grep the index rather than reading it whole, because it is one row per class and it gets large. And check a class file's size before reading it: most are around a kilobyte, but one class in several hundred goes past 20 KB, and without that qualification a rule saying "read `classes/<Class>.md`" gets followed literally on the 32 KB one. We measured a session paying four times over for the same correct answer.

## Per module rules, which is where the detail goes

*CLAUDE.md* is loaded on every question, so it has to stay short. Anything that only matters once you already know which module you are in belongs in a per module file instead, under *.claude/rules/*, which is read when it is relevant rather than always.

Start from *../templates/rules/Module.md.template*, one per module:

```
copy templates\rules\Module.md.template D:\MyGame\.claude\rules\MyGameCore.md
```

What earns a place in one: which classes live there and what owns what, the replication conditions and where they are set, the module's dependency direction if it has a rule about it, and the design docs that govern it. What does not: anything the artefacts already say, which is most of what you might be tempted to write.

*../templates/rules/Building.md.template* is the same idea for build commands. It exists so the invocations get copied rather than guessed, and so the non-obvious flags survive somebody tidying them away.

## Design documents, the layer nothing else can answer

Layer 5 is the one people skip because it is the only one with no tool behind it. It is also the only place that can say *why*: what was tried and rejected, and which numbers came from playtesting rather than from a constraint. The code can tell you a pause is two seconds; only a design doc can tell you that two came out of a playtest and that changing it needs another one.

Start from *../templates/design-doc.md.template* and put them in *Docs/Design/*.

The front matter is the point of that template rather than decoration:

```yaml
---
system: Stamina
modules: [GameCore, Game]
classes: [UStaminaComponent, AGameCharacter]
status: current
---
```

Naming the modules and classes is what makes the document findable from a class name, which is how anyone arrives at it: an agent asking "why is this like this" about `UStaminaComponent` has a class, not a filename. Without the front matter it has to guess what the file might be called.

**`status` matters more than it looks.** A superseded document that still says `current` is worse than no document, because it will be believed. Mark it `superseded` and it stops doing harm without anyone having to delete it.

## Test it, don't just write it

Ask three questions you already know the answer to, one per layer, and watch the route rather than the answer:

1. A replication or specifier question. It should read the class artefact, not a header.
2. A blast radius question. It should read the C++ callers **and** the Blueprint index. If it only does the first, the wording isn't firm enough yet.
3. A "why is this like this" question. It should reach for a design doc.

A right answer by the wrong route means the next question gets a wrong one.

## It rots, and quietly

Three things to recheck whenever you touch it: that every path it names still exists, that every claim in it is still true, and that every file it tells a session to read is still *readable*. Ours carried an invocation under a module name that had changed weeks before, sitting immediately above a paragraph that gave the correct one. Both were confidently worded.

**A pointer can rot by the file growing.** Ours told every session to read a coordination log before starting. That was good advice in June and the file is now 339 KB, past what the read tool will return: 138 of 170 sessions tried it, **103 of those reads failed on size**, and each one then fell back to grepping for what it needed. Nothing about the instruction became untrue — the file it names simply outgrew the tool, monotonically, and the failure appears at no point as an error anybody reads. If a line here names a file that grows, bound what it asks for: a section, a tail, the last entry, not the document.

If you keep per module rules files as well, the same applies to those, and they're easier to forget because they're read less often.

## Machine specific things go elsewhere

Local paths, engine locations, personal overrides: put them in *CLAUDE.local.md* and don't commit it. Anything in the committed file has to be true for everyone on the team.
