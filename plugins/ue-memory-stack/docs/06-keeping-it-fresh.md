# Keeping it fresh

Committed artefacts have one failure mode that matters, and it isn't being wrong. It's being **quietly old**. A stale artefact reads exactly like a current one, an agent believes it exactly as much, and nothing in the output says which you're looking at.

So the question isn't "how often should I regenerate", it's "how would I find out if I hadn't".

## One command

```powershell
.\Update-MemoryStack.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

Build, then the compile database, then the dump, then a check that the artefacts are internally consistent. `-Preset Artefacts` regenerates the dump without rebuilding, `-Preset Layer1` does the compile database alone, and `-DryRun` prints every command it would run without running any of it.

Pass more than one `-ProjectPath` and it does each in turn. That is not a convenience: the plugin's binaries are built per project, so building one and dumping three writes stale output for two of them and reports success.

**What it does that running the scripts by hand does not.** Every stage checks the *artefacts* afterwards rather than trusting the exit code. A stage whose tool exits 0 without leaving anything newer than the moment the stage started is treated as a failure, because that is what almost every silent failure in this stack looks like: a tool that ran, reported success, and wrote nothing.

Artefact directories are moved aside and put back if a stage fails, never wiped in place. A run that dies after deleting the old output leaves an index saying nothing has any Blueprint callers, which reads exactly like the truth.

It also refuses to start if an editor is running, because the editor holds the plugin DLLs open and UBT will not run a second instance. The failure without that check is about file permissions and never mentions the editor.

## After getting latest

Regenerating after your own change is the obvious case, and it is covered below. This is the other one: somebody else changed it. It catches people out because nothing about a sync tells you whether the artefacts you just pulled describe the code you just pulled.

Four things can have moved, and they need different amounts of work:

| What changed in the sync | What you need to do |
|---|---|
| Reflected code, and they regenerated | Nothing. The artefacts came down with it |
| Reflected code, and they did not | Regenerate. Until you do, the artefacts are wrong and confident |
| The plugin itself, to a new version | Rebuild before dumping, or the dump writes the old format |
| A `.Build.cs`, or a new module | Regenerate the compile database as well |

If you are not sure which of those happened, the answer is one command:

```powershell
.\Update-MemoryStack.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

On a tree whose facts are in *.claude/agent-memory-stack.json* (*00-getting-started.md*, step 8), pass that instead of the paths and every project in it is refreshed:

```powershell
.\scripts\Update-MemoryStack.ps1 -StackConfig D:\Tree\.claude\agent-memory-stack.json
```

It rebuilds first, so a plugin that moved is picked up, and it refuses to dump against a stale DLL rather than quietly writing the old format.

**Why you cannot just check the timestamps.** The obvious idea is to compare the newest source file against the newest artefact and regenerate if source wins. That works for catching your own forgetfulness, and it does **not** work after a sync: both git and Perforce stamp everything they write with the time they wrote it, so a changed header and a regenerated artefact that arrived in the same sync both look like they were modified just now, and their order tells you nothing. A check like that reports "fresh" for exactly the case you wanted it to catch.

**What does work is comparing revisions**, because a revision is a fact on the server and a sync cannot forge it. Ask which change last touched the source, ask which change last touched the artefacts, and compare those rather than the files:

```powershell
# Perforce, at the revisions you actually have
p4 changes -m1 "MyGame/Source/...#have"          # the code
p4 changes -m1 "MyGame/Docs/AgentMemory/...#have" # what describes it
```

Artefacts at an older change than the code means regenerate, and it means it whether you synced a minute ago or a month ago. The git form is the same question: `git log -1 --format=%H --` over each path, then ask which commit is an ancestor of the other.

Two things that comparison cannot see, so check them separately:

- **Your own uncommitted edits.** `p4 opened` or `git status` over the source paths. A `UPROPERTY` you changed and have not submitted is invisible to a revision comparison, and it is the most likely thing to be stale.
- **Artefacts that are not in source control yet**, on a tree being set up. There is nothing to compare against, so fall back to file times and *say* that is what you did. It is a weaker answer and should read like one.

The compile database is the happy exception: it is normally ignored by source control, so it is never synced, its timestamp really is the moment it was built on this machine, and comparing it against a synced `.Build.cs` is sound.

Failing all that, there are two blunter options. Regenerate after any sync that touched reflected code, which is cheap on a small project and a few minutes on a large one. Or put the CI check below in place, so the artefacts on your default branch are known to match the code and a sync from it needs nothing.

**On Perforce, artefacts come down read only.** The next dump then meets a folder it cannot write, and the commandlet does not stop at the first failure: it carries on and reports its usual summary. *Invoke-AgentMemoryDump.ps1* opens the folder for edit first, which is why. See *02-install-plugin.md*.

**If the engine version changed**, regenerate everything and expect the compile database and the clangd index to need rebuilding too. Every path in the database is absolute and the index is keyed by source path.

## When to regenerate

| Change | Regenerate |
|---|---|
| `UCLASS`, `UFUNCTION`, `UPROPERTY`, or anything in `GetLifetimeReplicatedProps` | The dump |
| A Blueprint that calls C++, added, removed or rewired | The dump |
| A `.Build.cs` or a new module | The dump, and the compile database |
| A design decision changing | The design doc, by hand |
| Renaming or moving code | Everything, and check the routing table still points at real paths |

In practice: hang it off whatever already runs after a build. It's a few seconds on a small project and a few minutes on a large one, and the graph walk is nearly all of that.

## A fourth way, and the one you cannot see

The three below are about artefacts that describe older *code*. There is a fourth: artefacts written by an older *dump*, where the shape of the files themselves has moved. Reading them tells you nothing is wrong, because every file is well formed — it is the meaning that has changed.

So *MANIFEST.md* carries two rows:

```
| Artefact format | 1 |
| Written by plugin | 0.2.0 |
```

The format is a number the commandlet owns, bumped when a change would make an older set wrong rather than merely smaller — a column that moves, a file that stops being written, a meaning that changes. `/ue-memory-stack:doctor` compares it against what the installed plugin expects and fails when they differ.

**A set with no format row at all was written before the stamp existed**, and that is the answer rather than a missing one. Regenerate once and the question has an answer for ever after.

## The three ways it goes stale

**The DLL is older than the plugin source.** The dump runs against whatever module is built, so if you changed the commandlet and didn't rebuild, you get the old format with a success message and exit code 0. `Build-UEAgentAccelerator.ps1 -CheckOnly` is the guard, and it's the only check that has ever caught this before the output was committed.

**You built one project and dumped another.** The plugin's binaries are per project. Build A, dump A, B and C, and two of them write stale output and report success. If you run this on several projects, build all of them or check each before dumping.

**Checking a small project isn't checking the change.** A spot check on a four class project passed once while 442 of 447 files elsewhere were stale. Verify the artefact the change was *for*.

## Do the artefacts have to be committed?

Short answer: something has to put them where an agent will find them, and committing them is much the simplest way. The reason it matters more than it sounds is that **an agent that finds no artefacts does not fail.** It falls back to grepping headers and answers anyway, with the confident wrong answers this whole stack exists to prevent. A missing artefact is invisible in a way a missing header never is.

So the choice is really about who generates them, not whether they exist.

**Committed, generated by whoever changes the code.** The default the rest of these docs assume. The artefacts land in the same commit as the change that caused them, so a reviewer sees a replication condition change in the diff, and anyone syncing gets code and description together. The cost is remembering to run it, which is what the CI check below is for.

**Committed, generated by CI.** Developers never run the dump; a job regenerates after a merge and commits the result back. Better if your team will not reliably run it. What has to be checked in is unchanged — the code, the plugin or a reference to it, and the CI configuration — the difference is only who produces the artefact commit.

**Not committed at all**, published as a build artifact that developers fetch. This is the one to think hardest about. Nothing artefact-shaped is in source control, so there are no generated files in review and no merge conflicts in them. In exchange every developer needs a fetch step before the artefacts do anything, review loses the diff, and anyone who skips the fetch gets the silent grep fallback above. We have not run it this way.

## Catching it in CI

Two jobs, and they are not the same thing.

**Checking** regenerates and fails if the tree is dirty afterwards. This is the cheap one and it needs the artefacts committed, because the check is precisely "do the committed artefacts still describe this code":

```powershell
.\Update-MemoryStack.ps1 -ProjectPath $proj -EnginePath $engine
git diff --exit-code -- Docs/AgentMemory
```

That works because the output is deterministic and carries no absolute paths, so a clean tree means they match and a dirty one means somebody changed a `UPROPERTY` and did not re-run it.

**Refreshing** does the same and commits the result instead of failing. Three things to get right, none of them about this tool:

The job needs write access to the repository, and a way not to trigger itself. A commit from CI that starts another CI run that makes another commit is the usual first attempt.

On Perforce it needs a workspace and has to open the artefacts for edit before writing, exactly as the dump script does locally.

Two branches that both touch reflected code produce conflicting artefacts, and **the resolution is to regenerate after the merge, never to merge them by hand.** They are generated files; a hand-merged index is a description of a codebase that never existed.

**Both need a built editor on the CI machine**, which is the expensive part and the reason to think about this at all. If that is not worth it per commit, run the check on a schedule. Weekly still catches drift long before anyone has been badly misled.

## Keeping the routing table honest

The artefacts go stale in ways a script can catch. *CLAUDE.md* goes stale in ways it can't, and it's the file every session reads.

Two things worth re-checking whenever you touch it:

1. **Every path it names still exists.** A row pointing at a file that moved is worse than no row: the agent tries it, gets nothing, and falls back to grep having spent a call and learned nothing.
2. **Every claim in it is still true.** Ours carried a line telling people to invoke the commandlet under its old module name for weeks after that name changed, sitting directly above a paragraph that gave the new one. Both were confidently worded and one was wrong.

The second is the reason to keep the file short. Everything in it is loaded on every question and paid for whether it's used or not, so a long file isn't just expensive, it's more surface to rot.

## Two trees

If you develop in one tree and publish from another, they will drift, and the drift is invisible until something behaves differently in one place. *Sync-Shared.ps1* compares the shared paths by hash and reports what differs:

```powershell
.\Sync-Shared.ps1 -TreePath C:\Work\MyTree            # compare, write nothing
.\Sync-Shared.ps1 -TreePath C:\Work\MyTree -Mode Pull # take the working tree's copy
```

It refuses to overwrite when the destination holds changes the source doesn't, unless you pass `-Force`. Curated files like *CLAUDE.md* are reported but never copied, because a lesson learned about one project doesn't belong in another project's file verbatim.
