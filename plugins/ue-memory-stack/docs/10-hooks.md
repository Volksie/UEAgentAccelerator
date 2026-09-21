# The hooks, and what they cost

Two hooks ship enabled, one ships off. The reasoning is entirely about cost, and the numbers below were measured rather than estimated.

## What each one does

| Hook | Fires | What it does |
|---|---|---|
| `SessionStart` → *Warn-StackStale.ps1* | Once, when a session starts | Says one line if this project enables a plugin nobody installed, or if a plugin DLL is older than its source. Silent otherwise. |
| `PreToolUse` on `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` → *Deny-ArtefactWrite.ps1* | Every edit, and every shell command | Refuses changes to *Docs/AgentMemory/\*\** and to *.claude/.uea-install.json*, with a reason naming what to do instead. |
| `PostToolUse` on `Bash` → *Note-BuildRanDump.ps1* | **Off by default** | After a command that looked like a build, notes that the artefacts now describe the code as it was before it. |

## Why the guard watches the shell, and what that costs

The first version of the guard matched `Write|Edit`. The first person to test it walked straight through it: their session was configured to make file changes with `sed` and heredocs, so a `sed -i` on a generated artefact was never offered to the hook at all, and nothing said a word. The file was edited, the guard reported nothing, and the only reason anybody knew was that the tester said so.

That is worth stating plainly because it is the failure mode this whole plugin argues against. **A guard that covers only the paths nobody takes produces confidence rather than protection**, and confidence is the expensive kind of wrong. Shell writes are the normal path in plenty of sessions, so `Bash` is in the matcher.

| | Measured |
|---|---|
| `SessionStart`, on a real three-project tree | ~250 ms, once |
| `PreToolUse`, per edit **and per shell command** | ~220 ms |

All of that is PowerShell process startup rather than anything the scripts do. So the honest summary is: the guard costs about a fifth of a second on most tool calls an agent makes. That is the price of it holding. If your sessions never write through the shell and you want the milliseconds back, take `|Bash` out of the matcher in *hooks/hooks.json* — and know what you have chosen.

Hooks add **no always-on tokens**: `claude plugin details` reports them as harness-only, and the plugin's projected always-on cost is identical with them and without. Whatever a `SessionStart` hook *prints*, though, is real context in every session for ever, which is why it prints nothing when the stack is healthy. A cheerful "all good" banner is a permanent charge for information nobody asked for.

## How the shell arm decides

A shell command is denied only when the hook can see **both** a protected path and something that writes to it. Every writing pattern is tied to the path rather than matched anywhere in the command, so these all pass:

```bash
cat  MyGame/Docs/AgentMemory/classes/UMyThing.md
grep -rn COND MyGame/Docs/AgentMemory/ > /tmp/hits.txt     # redirected somewhere else
cp   MyGame/Docs/AgentMemory/classes/UMyThing.md /tmp/     # copied out, not over
sed -i 's/a/b/' MyGame/Source/Thing.cpp                    # an ordinary source file
```

and these are refused:

```bash
sed -i 's/COND_OwnerOnly/COND_None/' MyGame/Docs/AgentMemory/classes/UMyThing.md
echo x >  MyGame/Docs/AgentMemory/index.md
cat <<'EOF' > MyGame/Docs/AgentMemory/index.md
echo x | tee MyGame/Docs/AgentMemory/index.md
Set-Content -Path MyGame/Docs/AgentMemory/index.md -Value x
rm MyGame/Docs/AgentMemory/classes/UMyThing.md
cp /tmp/forged.md MyGame/Docs/AgentMemory/classes/UMyThing.md
perl -pi -e 's/a/b/' MyGame/Docs/AgentMemory/classes/UMyThing.md
```

Twenty-four cases, positives and negatives, are checked whenever this changes. The negatives matter as much as the positives: a guard that blocks reading an artefact is one somebody deletes by Friday.

**It fails open in every direction.** Unreadable payload, unfamiliar tool, a command it cannot parse: it exits silently and allows the call. There will be shapes it misses — a script that writes an artefact from inside Python, for instance, or an editor invoked by a name it does not know. It is a guard against the ordinary accident, not a permission system, and it does not pretend otherwise.

## Turning the build note on

```json
"PostToolUse": [
  {
    "matcher": "Bash",
    "hooks": [
      {
        "type": "command",
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"${CLAUDE_PLUGIN_ROOT}/hooks/Note-BuildRanDump.ps1\""
      }
    ]
  }
]
```

It ships off because it would be a *second* process spawn on every shell command, to say something that applies after a build and not otherwise — and the same fact is in the refresh skill and in `/ue-memory-stack:doctor`. Worth it on a tree where people build from the agent and forget to regenerate.

## Things worth knowing before you debug a hook

**Editing a hook changes nothing until the plugin is reinstalled.** Hooks are read from the cached copy of the plugin, keyed by version, so an edited *hooks.json* in a marketplace directory is ignored by every session — and `claude plugin update` will say you are already up to date. Bump the version, or uninstall and install. This cost two rounds of testing to notice, because a hook that is not loaded behaves exactly like one whose matcher is wrong.

**Hooks load at session start.** Even after a reinstall, the session you are in keeps the hooks it started with. Open a new one before concluding anything.

**Project-scope plugin hooks need the workspace trusted.** Claude Code documents it: hooks load only after the trust dialog is accepted. Dismiss it and the hooks are absent, along with the plugin's commands, with no error.

**`SessionStart` output is context, not screen output.** It reaches the model, not the user, so "I saw nothing at startup" is not evidence either way. Ask the session what arrived in its context.

**A `PreToolUse` deny is not an error.** The hook returns a decision and a reason; the reason reaches the model, which should then do what the reason suggests. If a deny reads as a failure rather than as guidance, the reason text is at fault and should name a command.

**These are Windows scripts**, like the rest of the tooling here. On another platform the hooks do nothing, and every check they perform is available from `/ue-memory-stack:doctor` — which is also PowerShell, so a non-Windows tree loses neither more nor less than it already had.
