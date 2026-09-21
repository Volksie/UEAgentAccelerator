---
description: Install or check the Serena build that makes Layer 1 work on an Unreal tree
argument-hint: "[--check]"
allowed-tools: Bash, Read, Grep
---

Install the Serena build Layer 1 needs, or report whether it is already in.

Arguments passed: `$ARGUMENTS`. `--check` reports and writes nothing.

## Before running anything, know why this is fiddly

On a tree with an engine in the workspace a **stock Serena install mostly does not work, and says nothing**. Every symbolic call walks the whole tree first; the engine's `.gitignore` overrides the project's excluded paths; and the stock context removes `search_for_pattern`, so a routing table naming it points at nothing. `${CLAUDE_PLUGIN_ROOT}/serena/README.md` has all seven items in order of how much they matter.

**These are not patches any more.** They used to be diffs applied to an installed Serena, and every `uv tool upgrade serena-agent` reverted all of them without saying so. They are commits on a fork now, so they arrive with the install. That also keeps this repository MIT: Serena's application is GPL-3.0-or-later from v2, so a diff against it would put a GPL-derived file in here. Nothing in this plugin is derived from Serena — see *NOTICE.md*.

## What to do

**1. Run the installer.** It is idempotent: the install uses `--force`, and the context is left alone if one carrying `search_for_pattern` is already there.

```powershell
${CLAUDE_PLUGIN_ROOT}/serena/Install-SerenaForUE.ps1 -DryRun -TaskName '<your Serena task>'
```

Drop `-DryRun` once the plan looks right. If the tree has a `.claude/agent-memory-stack.json`, the task name is in it under `serena.taskName`. `-Source` installs from somewhere else, which is the flag to reach for if the user would rather not install from a third-party fork.

**2. Expect it to refuse, and do not work around it.** It checks whether this shell's `%APPDATA%` writes are redirected into a packaged app's private storage, and refuses if they are. That is the failure it exists to prevent: an install made from a redirected shell lands in a copy the real server never loads, and every check made from the same shell says it worked. If it refuses, tell the user to run it from a normal PowerShell window — do not look for another route.

**3. Restart the server**, properly. The installer does this itself when it knows the task name; otherwise run `serena\Start-SerenaForUE.ps1 -Stop` and then start the scheduled task. Stopping the task alone is not a restart: it kills only the watchdog, the server lives on, and the restarted launcher finds the port busy and exits with nothing to do. Stopping `serena.exe` alone is not one either, because one generation is three processes and the grandchild holds the listener.

**4. Check from outside the agent.** The proof is the **running server's tool list**, not the files on disk: `find_symbol_indexed` present, and `search_for_pattern` present if the context variant is in use.

## If the version looks wrong

Do not read it from the first `serena_agent-*.dist-info` in `site-packages`. More than one can be there — an in-place upgrade leaves the old one behind, and a packaged app's shell sees a *union* of its redirected copy and the real one, so it can list a build that is serving nothing. `direct_url.json` inside each one says where that copy came from, and the installer prints it.

## Say this afterwards

**A plain `uv tool upgrade serena-agent` replaces the fork with upstream and takes all seven fixes with it.** Re-run this after any upgrade, and re-check the tool list.
