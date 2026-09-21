# How the benchmark works

The rules we arrived at for measuring whether the stack actually helps. Most of them exist because we got something wrong first, so they're worth reading before you change the harness.

## Enumerate, then sample. Never hand pick

If you choose the questions yourself you choose the ones you already understand, and the benchmark flatters the stack. So enumerate every candidate in a stratum mechanically, take a seeded random sample, and write the question from whatever comes up. `sample_candidates.py` stops at "here is a symbol worth asking about" and `make_questions.py` goes the rest of the way.

The seed is part of the result. Change it and you have a different set.

## Never let the tool under test supply its own answer key

Every key comes from the reflection artefacts, never from clangd, because clangd is one of the things being measured. Where the reflection walk is itself under test, the key needs a hand check instead.

Hand check rates we settled on:

| Group | Rate | Why |
|---|---|---|
| Most groups | 10% | Spot check |
| Replication and specifiers | 25% | The reflection walk is the thing being tested here |
| Negative answers | **100%** | An incorrect "no" is the worst error the set can contain |

`check_keys.py` re-derives what it can from source independently and reports PASS, FAIL or SKIP. It is not a substitute for the hand check, it just makes the hand check smaller.

## Take each stratum from wherever it is populated

Don't force one project to answer every group. A stratum needs a population, and no single project has all of them:

- A small project you control is where facts can be *planted*, so it's the only place the answer key is fully known. Keep the hand written blast radius keys here.
- A large project is the only place blast radius is neither zero nor trivial.
- A deep project, with files too big to read, is where token and time cost show up.
- Deprecation questions usually have no population in a project at all, so they come from the engine tree.

That's what the `strata` block per project in *projects.json* is for. A project that is thin in a group should not be asked about that group.

## Isolation has to be proven, not assumed

The baseline arm must be **unable to reach** the layers, not merely told not to use them. Telling a capable agent not to look at a file is not a measurement.

Three things we learned the hard way, and the third one cost a whole run.

1. **A parallel root of junctions does not work.** The compile database holds absolute paths, so the compile database and the symbol index resolve back to the real tree from any working directory, and an agent reads any absolute path regardless of its cwd.
2. **A copy anywhere in the tree defeats all of it.** We were caught twice. Once by a zip at the tree root holding a hundred class files, once by a backup directory whose name did not contain "AgentMemory" at all, noticed only because a baseline answer cited a file inside it *after* that arm had run. So the leak check recognises artefact trees by **shape**, a directory holding `classes/` or an `index.md` beside a `BlueprintCallers.md`, rather than by name.
3. **Moving things aside is a denylist, and a denylist is never finished.** This is the one worth taking seriously before you copy our method. Every file that exists, and every file anybody creates later, is readable by the measured agent until somebody classifies it. We found **fifteen leak channels over three attempts**, and each round found them in places the round before had blessed: a version file whose line 149 was one question's exact answer, a review document dropped at the tree root the previous day, the stack update script's own logs narrating the pipeline stage by stage, forty-three unclassified root build logs, and — the one that should have been obvious — **the isolation run's own marker file**, which named the arm and said which files had been moved. Thirty-seven of 159 answers knew a benchmark was running and five declined to answer until it finished.

**What replaced it: build a room rather than empty one.** A clean root beside the tree, holding only what that arm may see — source, config and content copied or hardlinked in, the engine junctioned from where it already is, and nothing else ever named. A file nobody thought about is then absent by construction rather than present until classified. The argument is about verification cost rather than tightness: proving a denylist complete never ends, and enumerating what to copy is a bounded list of about twenty items.

**Nothing of ours goes in the room, including the room's own bookkeeping.** Our first room wrote its drift manifest into its root and the run wrote its lock file there too. On the next baseline run, 6 of the first 51 questions read the manifest, which names the real tree's path, and several answers reasoned out loud from the lock file that an automated run was recording them. A marker's wording can be made harmless; its presence cannot. The builder here keeps the manifest beside the room instead.

**Neither one is the proof.** An agent with a shell can read an absolute path from any working directory, so no layout makes the tree unreachable. What establishes a clean run is a **per-question record of what each question actually reached for**, checked against the held list, aborting on the first hit. Prove non-access from the run's own record; treat the layout as defence in depth.

**The room is in this repository; the gate is not.** `tools/Build-BaselineRoot.ps1` builds and verifies one, and `run_bench.py --isolation room` runs the baseline arm in it. The per-question record that would *prove* a clean run is still ours only, so treat a room-mode run as much better defended than a move-aside one and not as proven.

Two things to know before using either:

- **The answer keys have to move in both arms regardless.** A question file sitting in the tree is greppable, and a run with the keys present measures nothing. Room mode still moves them; it replaces the layer half of isolation, not that half.
- **If you use move-aside, do the two things that caught our last leaks.** Classify every entry at your tree root before you start, not just the ones with obvious names — anything your pipeline writes describes the layers by construction. Then grep the isolated tree for your own artefact vocabulary. The room builder does that second step as a build step you cannot skip, which is the only reason it is worth trusting more.

The answer keys move in **both** arms, because a question file sitting in the tree is greppable and a run with the keys present measures nothing.

Prove it per run rather than trusting the script: `run_bench.py` asks a session to try to read the layer files and records what happened, and that record belongs in the results.

## Scoring

| Mode | Scored how |
|---|---|
| `exact` | String or value match against the key |
| `set` | Recall and precision reported **separately**, never collapsed into one number |
| `empty_set` | A pass needs the empty set **and** evidence the agent checked, rather than a guess |
| `prose` | Judgement |

`empty_set` is the one people get wrong. "No callers" is the right answer to some questions and the lazy answer to all of them, so a pass has to show the check happened.

**Judge every answer more than once, and quote the majority.** A judge disagrees with itself, and on a set of this size the disagreement is the same size as some of the differences being claimed. Three passes over 340 measurements came out 96.2% unanimous, every disagreement between adjacent verdicts and none of them reversing a right answer into a wrong one. The majority verdict is the one to publish and the spread across passes **is** the error bar; `judge_reliability.py` reports both.

One trap in doing that, which cost us a document. If the key you store scores under does not include the pass number, three passes overwrite each other and the table reports whichever ran last while looking exactly like a three-pass result. Ours differed from the majority by one question in each direction.

## One question per session

Run them in sequence and the later ones inherit context, at which point the token numbers stop meaning anything. One question, one fresh session.

Most of the cost of a session is paid before it reads a byte: the system prompt, the tool schemas and the standing context. Measure it rather than estimating it — `measure_floor.py` asks a configuration to reply with one word and reports what that cost — and measure it **per arm**, because two arms with different tool surfaces do not share a floor.

Cutting the tool surface is the one lever that reduces the bill without changing what you measure, and it is much bigger than it sounds: pinning the built-in tools to the five each arm actually needs cut the standing cost of a run by roughly **15x**. It has nothing to do with the memory layers and it dwarfs everything that does.

Two details that are easy to get wrong. `--tools` controls which built-in tools **exist**; `--allowedTools` only controls which ones skip a permission prompt, so the second does not reduce anything. And neither arm should have `Write` or `Edit`: a run that measures a tree must not be able to modify it, and a retrieval question must not be answerable by leaving notes for the next one. In our v2 run both arms had them and the baseline arm used them 33 times.

**Do not subtract a floor from a total.** We recorded "tokens above the floor" for two versions before noticing it cannot be right: a session pays its standing context on **every turn**, not once, so one subtraction understates a long answer and the obvious correction — floor times turns — goes negative on most questions, because the implied per-turn input is not a constant. It ranged from 21,278 to 70,129 on one arm of one run. Report total input tokens and turns, and let the reader divide.

## Reading the numbers

**Group medians carry weight. Single question figures do not.** Run to run variance on the same question under identical conditions was about **40% on tool calls and 20% on seconds**, measured over 140 questions run twice. One question moved from 274.8s to 109.5s between two runs of itself, another from 275.0s to 644.5s. Any claim about an individual question needs repeats before it means anything.

**A judged Correct figure carries about half a point of noise, measured three ways.** On the current set, 340 measurements judged three times were 96.2% unanimous, and the credit each pass produced on its own varied by 0.3 points on one arm and 0.6 on the other. So a gap of a point or two is still nothing; a gap of sixteen is not. Re-measure this on your own set rather than carrying ours across — it is a property of your questions and your judge prompt.

**Route match is not an arm-versus-arm number.** We published one as though it were, and it does not survive contact with the method: most expected routes name a layer artefact, and the baseline arm runs somewhere those have never existed, so it scores near zero by construction however good its answer. Split the set by whether a route was reachable at all — `route_split.py` does it — and on the reachable half the two arms come out level. Route is a diagnostic *within* an arm: it is how you find out your own routing table is being ignored.

**Say "inferred" when a number is inferred, or go and measure it.** Once a figure is in prose it reads exactly like a measured one, and ours travelled through three documents before anybody checked it: 4,781 tokens a turn attributed to a set of MCP tool schemas, derived by subtracting one version's floor from another's, and **measured at 102**. It was wrong by a factor of 47, and the difference it had been credited with was instruction files growing. `measure_floor.py` exists because of that.

**A measured number belongs to a version of the stack.** Change a layer and the only way to move a result across that boundary is to re-run it. Nothing else is comparable, and no argument makes it so.

## An arm is defined by what it can call, so check it can call it

Three ways a run measures a different stack from the one you defined, with no error anywhere:

- **A missing MCP server is not an error to the CLI.** It just removes the tools. Isolation held the directory our engine-API server's script lived in, the server never started, and 26 questions ran with none of its tools. The standing floor dropped by 747 tokens, which is the size of the missing schemas, and that was visible and not acted on. Start every server the arm has after isolation and require a tool list before question 1.
- **A tool not on the non-interactive allowlist is refused per call.** In one discarded run, 19 of 159 questions hit a permission refusal on the language server while the arm used it successfully everywhere else. An explicit per-arm allowlist is the fix we adopted.
- **A tool your routing table names can be absent from the server's live tool list.** Ours named `search_for_pattern` for two versions; Serena's stock context removes it, and the arm called it zero times in 170 questions. Check the live list, not the documentation.

Record each arm's surface, and its probe results, in the run's meta file. A later reader can't reconstruct it from which tools happen to appear in the answers.

## Other sessions can reach a measured one

On a machine running more than one agent session, a question being measured shows up in the other sessions' peer list, and any of them can send it a message. No isolation method and no leak gate sees that channel. We found it by noticing a peer named after the room directory. Mitigating it is not done; don't run other sessions that might message peers while you're measuring.

## Re-derive the key's answer, not facts about it

Two of our answer keys were wrong in a published result, and the checker had passed both. It asserted facts *about* each key's answer: that a function had a certain call count, that a count came from a certain table. It never recomputed the answer to the *question*. One key named the most-called Blueprint function without anyone computing the ranking. The other counted every module where the question said *engine* modules.

The rule the checker lacked: **a superlative means compute the whole ranking; a scope word (engine, project, declared) means apply that filter independently rather than copying the key's own query.** Then feed the checker the old wrong keys and confirm it catches them. In both cases it was the stack arm that had answered correctly and been scored wrong. Before re-scoring after a key fix, check whether the correction can only move one arm, and say so, because a key changed after scoring in one arm's favour has to earn it.

## Standing context can change under you between runs

v3's two arms didn't share a standing context. Most of the baseline arm ran before a change that added 971 tokens to both arms at once, on the same CLI build, when the model flag changed spelling. Both spellings resolve to the same model, and today both give the larger floor, so the change can't be inspected or reproduced. Measure each arm's floor at the start of every run, and record it next to the results.

## The generated comparison quotes our numbers in its own caveats

`compare_arms.py` writes a "read this before quoting any number below" block at the top of its output. Most of it now comes from a notes file you write per run and pass with `--notes`: judge agreement, timeouts, defects. Without one, the block says no notes were supplied rather than printing someone else's.

One paragraph is still ours: run-to-run variance, measured by running 140 of our questions twice. Re-measure it on your own set if you're going to quote it.

## Record the defects rather than fixing them mid flight

If you find a broken question after the run, note it and leave it. Fixing it invalidates the result it sits in. Ours had one question that referred to another question by id, which no session can resolve; it stayed in, and *QUESTION-DEFECTS.md* records it along with what excluding it would have changed. That is more honest than a set that quietly improved between two arms.
