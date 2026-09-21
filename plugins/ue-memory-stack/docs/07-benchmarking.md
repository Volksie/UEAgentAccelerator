# Benchmarking your own tree

Our numbers are ours. They were measured on our projects, with our routing table, on our hardware, and the honest thing to do with someone else's benchmark is to re-run it rather than believe it. The harness in *bench/* generates a question set from **your** project's artefacts so you can.

*plugins/ue-memory-bench/bench/METHOD.md* covers why the harness works the way it does. This covers running it.

## What you need

- The dump already run on the project you want to measure, because the questions are generated from the artefacts.
- Python 3. Standard library only, nothing to install.
- The `claude` CLI, signed in, if you want to run the arms rather than just generate the set.

## 1. Say which projects to draw from

*plugins/ue-memory-bench/bench/projects.json* names them. The default lists one, the seed project, so it runs out of the box:

```json
{
  "projects": [
    {
      "key": "mygame",
      "dir": "D:/Work/MyGame",
      "areas": { "default": "Project code", "rules": [ { "module_contains": "Editor", "area": "Editor tooling" } ] },
      "strata": { "A": 14, "B": 14, "C": 20, "E": 13, "F": 10 }
    }
  ]
}
```

`strata` is where the questions come from, by group:

| Group | Asks about |
|---|---|
| A | Where something is defined, its type, what a function does |
| B | Inheritance chains and where a member is declared |
| C | Replication conditions, specifiers, RPC kinds |
| E | Subclasses, Blueprint subclasses, blast radius |
| F | Negative answers: what does **not** replicate, what has **no** Blueprint callers |
| H | Deprecation. Comes from the engine tree, not from a project |

`n` is a target rather than a promise. A group with no population in your project comes up short and the generator says so rather than inventing questions. That's a signal about your project, not a failure: if only two classes replicate anything, group C isn't a fair question for it.

Add more projects when one can't populate everything. The shape is multi-project for that reason, and *plugins/ue-memory-bench/bench/projects.example.json* shows a three project set.

## 2. Generate the set

```bash
python plugins/ue-memory-bench/bench/tools/make_questions.py --root . --seed 1 --config plugins/ue-memory-bench/bench/projects.json --out plugins/ue-memory-bench/bench/questions.md
```

That writes the Markdown for people and the JSON for the harness. Both carry the seed, because the seed is part of the result.

## 3. Check the keys

```bash
python plugins/ue-memory-bench/bench/tools/check_keys.py --root . --questions plugins/ue-memory-bench/bench/questions.json
```

This re-derives what it can from source, independently of the artefacts that produced the key, and reports PASS, FAIL or SKIP. SKIP is normal and means the question isn't mechanically checkable.

**It does not replace reading them.** Hand check a sample, and hand check **every** negative answer, because a question whose key wrongly says "nothing" is the worst thing the set can contain. The rates we use are in *METHOD.md*.

## 4. Build the runset

The generated question set is not what the runner consumes. It wants a *runset*, which merges the generated questions with any hand written ones and fixes the order:

```bash
python plugins/ue-memory-bench/bench/tools/make_runset.py
```

That writes `plugins/ue-memory-bench/bench/runset-full.json`, which is what `run_bench.py` loads by default.

Two optional inputs. `--handwritten` merges markdown tables of questions that cannot be derived mechanically, which is where groups like "why is this built this way" live if you write them. `--smoke` takes a file listing the ids for a twenty question smoke tier, and produces `runset-smoke.json` alongside; without it you get the full runset only, because which twenty questions represent a set is a judgement rather than a sample.

## 5. Install the benchmark agent

The harness runs each question in its own session, and which agent it runs matters to the result. Copy the one that ships here:

```
copy templates\agents\bench.md D:\MyGame\.claude\agents\bench.md
```

It declares four tools and nothing else, and the reason is cost rather than tidiness. A general purpose sub-agent given the prompt "reply with OK", doing no work at all, cost us **52,884 tokens**. A real benchmark question cost 58,000 to 67,000. So roughly 89% of every question was paid before it read a single byte, and none of that is retrieval: it is the agent's system prompt, its tool schemas and its skill listing. Across a few hundred questions and two arms that floor is most of the bill.

**Keep its tool list in step with what your routing table names.** If your *CLAUDE.md* sends an agent to a symbol server and this agent cannot reach one, you are measuring the fallback rather than the route, and the number you get is not the number you wanted.

## 6. Say what each arm may call

*plugins/ue-memory-bench/bench/arms.json* lists each arm's MCP servers and the MCP tools it may call. The runner passes that list with `--strict-mcp-config`, so an arm gets exactly those servers and **nothing from your own `~/.claude.json`**. Before that flag, the runner inherited every server you had registered, including the language server the baseline arm is meant to be without, and nothing recorded that it had happened.

Three things in it are worth getting right before a run:

- **The baseline has no MCP servers.** Anything you add there stops being part of the difference you're measuring.
- **Every MCP tool the layers arm should use has to be in `allowed_mcp_tools`.** `claude -p` can't ask for permission, so an unlisted tool is refused on every call, silently. In one discarded run, 19 of 159 questions hit a permission refusal on the language server while the rest used it, and nothing in the record said which was which.
- **`serena_gate` names a class in your tree.** Before the layers arm starts, the runner makes Serena answer a scoped lookup, then waits until clangd's index resolves that class to its header. Without that second wait, straight after a server restart, `find_symbol_indexed` answers `[]` in a tenth of a second, and every question gets scored on "no such symbol". The defaults point at the seed project. `--no-serena-gate` skips both checks, and the run records that it did.

During the run it also checks that clangd is the same process after each question as before. A replacement clangd answers `find_symbol_indexed` with an empty list for minutes. So a change is recorded on the question it happened during, the runner waits for the index again before the next question, and the run stops if the index doesn't come back. The runner also starts every stdio MCP server the arm has, **after** isolation, and requires a non-empty tool list before question 1. A missing MCP server isn't an error to the CLI; it just removes the tools. We lost a whole arm's first attempt to that: isolation held the directory the server lived in, and 26 questions ran without it before anybody noticed.

## 7. Run the arms

The baseline arm has to be **unable** to reach the layers, not just told not to use them. The runner applies isolation itself, proves it, runs the questions and restores the tree, so there's nothing to apply by hand first:

```powershell
python plugins\ue-memory-bench\bench\tools\run_bench.py --arm baseline --artefact-dir "MyGame/Docs/AgentMemory"
python plugins\ue-memory-bench\bench\tools\run_bench.py --arm layers
```

It refuses to start if isolation is already applied from an earlier run. `baseline-isolation.ps1 -Mode Status` says whether anything is moved aside, and `-Mode Restore` is idempotent, so run it after a crash without worrying.

**A question that times out gets one re-run, and a second timeout stands** as no answer. Decide that before the run rather than after you've seen which arm it helps. The record of a timed-out question keeps the calls it made before the ceiling, so you can tell a session that hung from one that was still working.

**Important:** while isolation is applied the tree is modified. Don't build, don't regenerate dumps, and don't run another agent session in that tree.

**Important:** if you keep copies of artefacts anywhere unusual, a zip, a backup directory, an export, pass them in `-ExtraLayerPaths`. A copy defeats the whole measurement, and we were caught by exactly that twice. The leak check looks for artefact trees by shape as well as by name, but it can only check the tree it knows about.

**There is a better way to do this, and it is the one we use.** Moving files aside is a *denylist*, and we abandoned it after it leaked fifteen times over three attempts — a version file, a review document left at the tree root, the pipeline's own logs, forty-three unclassified build logs, and the isolation run's marker file, which told the agent a benchmark was running. Each round found them somewhere the round before had approved.

Build a room instead. It contains only what you put in it, so a file nobody thought about is absent by construction:

```powershell
.\bench\tools\Build-BaselineRoot.ps1 -Mode Build -TreeRoot D:\Tree
python plugins\ue-memory-bench\bench\tools\run_bench.py --arm baseline --isolation room
.\bench\tools\Build-BaselineRoot.ps1 -Mode Verify -TreeRoot D:\Tree
```

Build copies each project's *Source*, *Config* and *Plugins*, hardlinks *Content* so 2 GB of assets cost nothing, junctions the engine from wherever it already is, and then **greps the finished room for your artefact vocabulary and refuses to finish if it finds any**. That last step is a build step rather than a habit, which is the only reason it is worth trusting: it is the method that caught our final three leaks, and on the first run against this repository it caught a stale comment in the seed project.

Two things to know:

- **Edit `$LayerVocabulary` before your first build.** It lists the terms *our* leaks used. Whatever you named your artefact directories, your MCP tools and your rules files belongs in it, or the proof step passes by not knowing what to look for.
- **`-Mode Verify` before every run.** A room that has drifted from the tree measures a codebase that no longer exists, which is this design's own failure mode and the price of not having leaks. The runner calls Verify for you in room mode and refuses to start on a stale one.

**What is still missing, said plainly:** neither method *proves* a clean run. An agent with a shell can read an absolute path from any working directory, so what establishes cleanliness is a per-question record of what each question reached for, checked against the held list. That is not in this repository. A room-mode run is much better defended than a move-aside one; it is not proven.

## 8. Score and compare

```bash
python plugins/ue-memory-bench/bench/tools/score_answers.py --pass 1
python plugins/ue-memory-bench/bench/tools/score_answers.py --pass 2 --resume
python plugins/ue-memory-bench/bench/tools/score_answers.py --pass 3 --resume
python plugins/ue-memory-bench/bench/tools/judge_reliability.py
python plugins/ue-memory-bench/bench/tools/compare_arms.py --baseline plugins/ue-memory-bench/bench/runs/results-baseline-full.jsonl --layers plugins/ue-memory-bench/bench/runs/results-layers-full.jsonl --scores plugins/ue-memory-bench/bench/runs/scores.jsonl --notes my-run.notes.md --out plugins/ue-memory-bench/bench/arm-comparison.md
```

The runner copies each arm's results into the run directory as `results-<arm>-<tag>.jsonl`, and the scorer reads the same names. The tag is `full` unless you ran a named runset; pass `--tag` to both if you did. `--resume` skips answers already judged in that pass, so an interrupted pass picks up where it stopped.

`compare_arms.py` writes the comparison table. Pass `--scores` to put Correct beside the speedups, and `--page` if you publish the result somewhere else as well, so the link lives in the generator rather than in a file that says "regenerate rather than hand edit".

**Write a notes file for the run and pass it with `--notes`.** It's the caveat block at the top of the document: judge agreement, questions that timed out or were re-run, defects found in the set, and anything else that happened. Without it the block says no notes were supplied. It used to be hardcoded with our figures, so every later comparison printed one run's judge agreement as if it described another. *plugins/ue-memory-bench/bench/arm-comparison-v5.notes.md* is ours, as an example, and it is longer than the result it belongs to — which is the right proportion when a run has a rescored key, an arm that drifted and a question that timed out in it.

**Score every answer more than once.** A judge disagrees with itself by about as much as some of the differences you will want to claim, so run the scorer two or three times over the same results and let `judge_reliability.py` report the agreement, the per-pass spread and the majority verdict. `compare_arms.py` votes the majority when it finds more than one pass.

Read *METHOD.md* on how much weight the numbers carry before quoting any of them: group medians mean something, single-question figures mostly don't, half a point of Correct is judge noise, and route match is not a number to compare between arms — run `route_split.py` for the half of the set that is comparable.

## The rest of what is in plugins/ue-memory-bench/bench/tools

The files the steps above do not use directly, so you know what they are rather than wondering:

| File | What it is |
|---|---|
| `judge_reliability.py` | Agreement across judging passes, the credit each pass produced on its own, and the majority verdict per measurement. The spread **is** your error bar |
| `route_split.py` | Route match split by whether the route was reachable in both arms. The half that is comparable is usually the smaller half |
| `measure_floor.py` | What a configuration costs per turn before it is asked anything. Edit the `CONFIGS` list to describe your own surface, then price each piece |
| `measure_schema_cost.py` | What an MCP server's schemas would cost resident against what deferral costs in discovery turns. Points at any stdio server |
| `assess_new_questions.py` | Whether questions you have just added actually discriminate, or are trivial, unanswerable or saturated |
| `_tree_root.py` | Not a tool. Every script here asks it where the tree is, by searching upwards for `plugins/ue-memory-bench/bench/projects.json` rather than counting directories up from itself. Move the tools and the counted answer is silently one level off, and what you see is an empty results file rather than the cause |
| `Build-BaselineRoot.ps1` | Builds, verifies and reports on the baseline arm's clean room. Used by step 7 above rather than directly. It refuses a room whose root holds anything but the projects and the engine |
| `make_smoke.py` | Picks a twenty question smoke tier from a set, if you would rather choose one mechanically than by hand |
| `summarise_run.py` | Turns a run's JSONL into the per group table, medians rather than means, representative and coverage sets never pooled |
| `bench-system.txt` | The system prompt each question is asked under. Change it and your numbers stop being comparable to your earlier ones |
| `judge-system.txt` | The system prompt the scoring judge runs under. Same warning, more so |
| `measure_clangd_index.py` | Not a benchmark tool. It measures what a clangd background index costs per compile database scope, which belongs to *05-serena-clangd.md* and lives here only because it shares the harness |

**The two prompt files are part of the measurement, not configuration.** They are the conditions the questions were asked and marked under, so editing either is a version boundary in the sense *METHOD.md* describes: a number produced afterwards is not comparable to one produced before, and no argument makes it so.

## What to expect on a small project

The seed project here generates 18 questions, not 160, because it has six reflected classes and three Blueprints and there is very little to sample. Ask it for more than it has and the generator reports a shortfall rather than inventing questions. Use it to check the pipeline runs end to end, then point the config at something real.
