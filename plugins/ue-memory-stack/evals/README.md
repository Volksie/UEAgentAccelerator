# The eval suite

Four cases that ask one question: **does this plugin send a session to the right artefact instead of grepping?** That is the only thing Layer 4 does, and it is the layer whose value is hardest to argue about, so it is the one worth a test that runs per commit.

```bash
claude plugin eval . --scaffold --trust-plugin --max-cost-usd 5 --no-publish
```

`--scaffold` is not optional: each case builds its own fixture with a shell script, because a run is sandboxed and there is no project in it otherwise. Read those scripts before passing it — the scaffold runs as **you**, outside the sandbox, and the CLI says so for a reason. `--trust-plugin` asserts you trust this suite, which a non-interactive run needs.

**Do not pass `--allow-tools Bash`.** The cases do not need a shell inside the sandbox, and granting one fails outright on at least one Windows setup: *a PATH directory could not be examined for keychain credential helpers (EPERM), so the Bash sandbox cannot exclude them*. The scaffold still runs, because it is not sandboxed.

By default a plugin target runs **two arms** — with the plugin and without it — and reports the delta, so a four-case suite at three runs each is 24 runs. `--ablation none` halves that and scores a single arm. The delta is the more interesting number: it is the plugin's contribution, rather than the model's general competence at reading files.

Requires **CLI 2.1.269 or later**. Earlier builds print "`plugin eval` is currently in early access" and exit 1.

## Why this is not the benchmark

| | `claude plugin eval` | `ue-memory-bench` |
|---|---|---|
| Asks | do the instructions route correctly | do the layers change how well real questions get answered |
| Against | a fixture of a few files, built per run | a real tree, hundreds of classes, real artefacts |
| Costs | cents, minutes | hours, and a real bill |
| Run | per commit | per version, deliberately |

A passing eval suite is not a result, and the benchmark's numbers are not a regression test. **Neither substitutes for the other**, and the mistake available here is quoting the cheap one as though it were the expensive one.

## What each case pins down

| Case | The failure it would catch |
|---|---|
| `routing-replication` | Answering a replication question from the header, which says nothing, instead of from `classes/<Class>.md`, which says `COND_OwnerOnly`. |
| `routing-blueprint-callers` | Answering "what breaks if I rename this" from C++ callers alone. A Blueprint graph calling it is a real caller that no C++ tool and no `rg` can see. |
| `comment-versus-body` | Trusting a doc comment over the code. The fixture's comment says metres over a body returning centimetres, which is the seed project's deliberate fixture. |
| `layers-skill-fires` | The `ue-memory-layers` skill never firing. Under `--ablation with-without` this grader is a plugin-fired indicator rather than part of the score, which is exactly what it should be. |

Each case pairs an **answer** grader with a **route** grader, and the pairing is the point: a right answer by the wrong route is a coincidence that will not repeat on the next question. The suite would rather fail a run that guessed correctly than pass it.

## The first run, and what it showed

Run 2026-09-18, CLI 2.1.276, four cases, three runs each, both arms — 24 runs, 864 seconds, **$4.25**.

| Case | With | Without | Δ |
|---|---|---|---|
| `layers-skill-fires` | 1.00 | 0.00 | **+1.00** |
| `routing-replication` | 1.00 | 1.00 | 0.00 |
| `routing-blueprint-callers` | 1.00 | 1.00 | 0.00 |
| `comment-versus-body` | 1.00 | 1.00 | 0.00 |

The last row is after fixing two graders; the first run scored it 0.44 against 0.33, and **the graders were wrong, not the model** — see below.

**So the suite runs, scores, and proves very little about the plugin.** Three of four cases pass identically with and without it, which means they are measuring the model's competence at reading a small directory, not this plugin's contribution. On a four-file fixture there is no wrong route to take: whatever the instructions say, a glob and a grep find the artefact. Only `layers-skill-fires` separates the arms, and it does so trivially, because the skill does not exist in the baseline.

**That is a fixture problem, and it is the work this suite needs next.** A case discriminates only when the wrong route costs something: decoy files that a text search hits first, a header that contradicts the artefact, a `.uasset` that a grep would "answer" from and be wrong, or a turn budget tight enough that the efficient route is the only one that finishes. Until then, read a green suite as "nothing regressed", not as "the layers help".

**Two graders were the weak part, twice, and both failures looked like the plugin failing.**

- `tool_used: Read` with an `input_match` reported *Read called 0x* on a run whose trace plainly shows `Read` on that exact path — and separately, a session that reached the file with `Grep` instead was marked as not having routed at all. Both route graders are now a `regex` over `target: trace`, which asks whether the session opened the artefact rather than which verb it used.
- A `not_contains` grader failed an answer for *naming* the wrong figure while rejecting it. The model said "200 cm … the doc comment is stale", then mentioned 20,000 to explain what the comment would imply — and was marked wrong for showing its working. That is a bad answer key, the same failure the benchmark's own method notes warn about, and it is now an `llm` grader that judges the claim.

**And one thing the suite did prove, which no amount of reading would have:** in the units case the session fired `ue-memory-layers`, opened the `.cpp`, and answered correctly. The instruction "comments are not answers about units, read the body too" is being followed. That is worth knowing precisely because it was the case most likely to fail.

## What the runner corrected, and what is still unproven

The cases were first written to the published documentation, which describes a flatter file shape than the runner accepts. The loader put that right, for free, because it reports bad keys before it spends anything:

- **`scaffold_script` is not a `prompt.md` frontmatter key.** That file accepts `schema_version, name, description, tags, plugins, runs, expected_outcome, model, max_turns, timeout_seconds, allowed_tools, artifact_publish, growthbook_overrides, append_system_prompt, env` and nothing else.
- **A `case.yaml` is nested**: `schema_version` (a *string*, `"1.0"`), `name`, and an `execution:` block holding `prompt`, `max_turns`, `timeout_seconds`, `allowed_tools` and `scaffold_script`. These cases are `case.yaml` for that reason.

`tools/check_evals.py` in the repository now encodes that, so the next mistake of this kind is caught in a second rather than at the front of a paid run.

**Two more things the runner taught, both of which cost a paid run each.** `scaffold_script` belongs under a `context:` block and nowhere else: under `execution:` or at the top level the loader accepts it and silently never runs it, so the agent meets an empty working directory and says so. And the scaffold shells out to `bash`, which must be on `PATH` — on Windows that means Git's `bin` directory, and without it the run fails with *Executable not found in $PATH: "bash"*.

**A broken case does not score zero.** The empty-workspace runs scored 0.33, because a negative grader is satisfied by an answer containing nothing. `tools/check_evals.py` now refuses a case whose graders are all negative, and the lesson generalises: read the per-grader verdicts, not the number.

**Authentication:** an eval run spawns `claude -p` children, which need the CLI's own credentials. If they have expired — they can, while the desktop app keeps working — every run fails with *Not logged in* and the suite stops. `claude` then `/login` in a terminal fixes it.
