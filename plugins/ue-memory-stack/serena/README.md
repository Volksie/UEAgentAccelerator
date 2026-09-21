# Serena for Unreal trees

Serena and clangd are Layer 1. On an Unreal tree with the engine in the workspace, a **stock Serena install mostly doesn't work, and it doesn't tell you so**. We ran two benchmark versions on it before finding out. The v4 result in *plugins/ue-memory-bench/bench/arm-comparison-v4.md* is the first one measured with Layer 1 doing what it was designed to do, and the seven items below are the difference.

**This route is now the one the current numbers were measured on.** The v5 and v6 results — *plugins/ue-memory-bench/bench/arm-comparison-v5.md* and *arm-comparison-v6.md* beside it — ran on the 2.x fork this installer installs, where earlier releases here shipped patches for 1.7.0 and the published figures described something you could not install. What the run says about the switch itself is narrower than it looks: the layers arm moved 93.2% to 95.6% against a per-pass spread of 0.6 points, which reads as "unchanged, possibly slightly better", and the run changed Layer 3 at the same time, so **nothing in it isolates the Serena version**. Take the fork for the reason given above — the fixes stop being reverted by every upgrade — and not as a measured improvement.

None of this is needed for the reflection dump, the Blueprint index or the routing table. It's only for Layer 1. If you're not using Serena, skip this folder.

**None of this is shipped here as code, and the reason is worth a sentence.** These fixes used to be diffs and loose files in this directory, applied to an installed Serena — and every `uv tool upgrade serena-agent` reverted all of them without saying so. They are now **commits on a fork**, so they arrive with the install and survive it. That also keeps this repository MIT: Serena is licensed per component, `solidlsp` under MIT and the application under **GPL-3.0-or-later from v2 onward**, so a diff against the application would be a GPL-derived file inside an MIT repository. *layer1-state.json* describes what a correct install looks like; *NOTICE.md* has the licensing in full.

## In order of how much they matter

| | What | Where it comes from | Why |
|---|---|---|---|
| 1 | `ignore_all_files_in_gitignore: false` | your `.serena/project.yml` | Epic's `.gitignore` overrides your `ignored_paths` |
| 2 | the freshness skip list | fork commit | Every symbolic call starts by walking the whole tree, about 190s on ours |
| 3 | a context that keeps `search_for_pattern` | derived on your machine | The stock context removes `search_for_pattern` |
| 4 | `find_symbol_indexed` | fork commit | Whole-tree name lookup from clangd's index, 0.1s instead of a timeout |
| 5 | the C# `.csproj` ignore fix | fork commit | The C# server opens every `.csproj` in the engine, ThirdParty included |
| 6 | the accept-loop hardening | fork commit | One transient socket error stops the HTTP server accepting, permanently |
| 7 | the `find_symbol` scope guard | fork commit | An unscoped `find_symbol` keeps walking the engine after the client gives up, and crashed clangd |

The first two decide whether Layer 1 works at all. The last one decides whether one agent's mistake takes the language server down for everybody.

### 1. Epic's `.gitignore` overrides your `ignored_paths`

*../docs/05-serena-clangd.md* already recommends turning `ignore_all_files_in_gitignore` off, because the walk that finds every `.gitignore` can stall startup on an engine tree. There's a second reason, and it's worse because it looks like success.

Serena appends the patterns from every `.gitignore` in the tree **after** your `ignored_paths`, and the last match wins. Epic's `UnrealEngine/.gitignore` ignores everything and then whitelists back in, with lines like `!UnrealEngine/**/*/` and `!UnrealEngine/**/*.csproj`. Those whitelist lines come later, so they override every engine exclusion you wrote. Your ThirdParty and Binaries exclusions are silently ignored.

Measured on our tree, before and after setting it to `false`:

| | before | after |
|---|---|---|
| ignore-spec build at startup | 240s | 0.0s |
| source files Serena tracks | 187,590 | 107,852 |
| engine ThirdParty and Binaries tracked | yes | no |
| language servers start after the server does | about 6 minutes | seconds |

### 2. The per-call file walk

Seven of Serena's symbolic tools, including `find_symbol`, `find_referencing_symbols` and `get_diagnostics_for_file`, start by walking every tracked source file and `stat`-ing it, to catch edits made outside Serena. Nothing in the configuration turns that off. It runs before **every** call.

On our tree that walk took **189s**, measured twice. So under a 45s tool timeout, no symbolic call ever reached clangd. We proved it from the process side: during a call that timed out, clangd's read counter didn't move, and it had not received a single `didOpen` all session. Under a 600s timeout it "worked", but every call paid three minutes before doing anything. That's why we didn't notice for two benchmark versions.

The patch skips the top-level `UnrealEngine` directory in that walk. Nobody edits the engine, so there are no outside edits there to catch. Your projects are still polled. Each fix helps on its own and we measured them separately: setting 1 alone took the stock walk from 190s to 59s, and this patch alone took it to 6.3s. We didn't time the two together. `SERENA_FRESHNESS_SKIP` changes which directories are skipped; set it to an empty string to get stock behaviour back.

**Don't lower `--tool-timeout` until this is in.** On an unpatched install a short timeout doesn't make Layer 1 faster. It makes every symbolic call fail, quietly.

### 3. `search_for_pattern` is missing from the stock context

Serena's bundled `claude-code` context excludes every tool that duplicates one the host agent already has: `read_file` (Read), `execute_shell_command` (Bash), `find_file` and `list_dir` (Glob), and `search_for_pattern` (Grep). That's deliberate and reasonable in general.

It breaks a routing table that names `search_for_pattern`, though, and ours did in five rows. Under the stock context every one of those rows pointed at a tool that didn't exist. We measured an arm calling it zero times across 170 questions and read that as the agent preferring Grep. It had no choice.

The variant here is the bundled file with that one exclusion removed. It's worth having because `search_for_pattern` honours `ignored_paths`, while a Grep from the tree root walks the whole engine. Install it as described below and select it with `--context`. The other option is to keep the stock context and route those rows to Grep, which is honest and slower on an engine tree.

### 4. `find_symbol_indexed`

Serena's `find_symbol` never uses clangd's index. Unscoped, it walks every file in every workspace folder and asks for a symbol tree per file, which is why the routing template has always said "never call it without `relative_path`". Serena already has a correct `workspace/symbol` request, which clangd answers from its index. Nothing in Serena calls it. This tool calls it.

Measured on our tree once clangd had loaded its index: **0.01–0.12s a query**, where unscoped `find_symbol` times out. Against a reflection-derived list of the same tree, a seeded random sample found **552 of 560**; the eight misses were two struct aliases clangd reports at their alias declaration, five `UENUM`s it resolves to their `.generated.h`, and one editor-private function.

It adds no capability the language server did not have. `SolidLanguageServer.request_workspace_symbol()` already existed in `solidlsp/ls.py` and nothing in Serena called it; the tool is the missing caller.

**Four things to know before routing to it:**

- Matching is fuzzy. `AActor` returns up to 50 results, so pick the exact name; `Class::Func` narrows.
- An out-of-line method resolves to its `.cpp` definition, not the header declaration.
- A `UENUM` can resolve to its `.generated.h` under `Intermediate/`.
- **It returns `[]` in about a tenth of a second until clangd has opened at least one file.** A fast empty answer straight after a restart is not "no such symbol". Warm it with one file-scoped call first — the benchmark harness blocks on exactly this, because every question after an unwarmed start would have scored a confident nothing.

### 5. C# projects under ignored paths

The C# language server opens every `.csproj` under the tree root and never checks `ignored_paths`. On an engine tree that included the ThirdParty projects Roslyn can't build. They produce thousands of NuGet advisory lines on every restart, and they're a large part of an 8–9 minute re-warm. With the patch (and setting 1, without which the paths still aren't ignored) it skipped 58 and opened 187.

### 6. The listener that dies with the process still running

Windows only, and only if you run Serena as a long-lived HTTP server, which *../docs/05* recommends. It's a CPython bug, not a Serena one. In the Proactor event loop, one transient `accept()` error closes the **listening** socket and never re-arms. The process, the event loop and the dashboard all keep running, and the MCP endpoint stops answering. We logged it 15 times, each one an 8–9 minute outage while a watchdog restarted everything, and every one fell inside a benchmark run, where a fresh client per question means constant connect and disconnect.

The fix re-arms the loop on a transient error, which is what the Unix event loop already does, and gives up after 200 consecutive failures so a hot loop still ends. On the fork it is `serena/util/accept_hardening.py`, called from `serena/cli.py` before the event loop serves — it used to be a `sitecustomize.py` shim dropped into the environment, which every reinstall removed.

### 7. Unscoped find_symbol keeps running after the client gives up

`--tool-timeout` bounds how long the server takes to *reply*. It doesn't stop the work. An unscoped `find_symbol` on our tree timed out at 45s on the client, then carried on walking the engine on the server for **four hours**, sending a symbol request for every file. It ended by crashing clangd twice, both times on the same third-party LLVM source file under `Engine/Platforms`. The next run found clangd gone, and nothing pointed back at a probe made hours earlier. A walk that has started can't be cancelled, so the only bound that holds is refusing the call before it starts.

The patch makes `find_symbol` return an error, with a pointer to `find_symbol_indexed`, when `relative_path` is empty or names a directory holding more than 1,000 source files. Counting skips build output and stops at the limit, so the check itself is cheap. On the live server an unscoped call was refused in 0.10s, the engine directory in 0.31s and the crashing ThirdParty directory in 0.20s. The UnrealBuildTool directory (301 files) still answered in 3.0s, and a single header in 0.11s. The largest project directories on our tree held 494 to 590 source files, so the default leaves them usable. `SERENA_FIND_SYMBOL_MAX_SCOPE_FILES` changes the limit, and `0` restores stock behaviour.

One thing to expect: a call made while the server is still starting times out instead of being refused, because it queues behind language-server startup. That's harmless. The guard runs before any language-server work, and the log shows no walk.

## Installing

One command, from an **ordinary terminal** rather than from inside your agent:

```powershell
<plugin>\serena\Install-SerenaForUE.ps1 -TaskName '<your scheduled task>'
```

It installs the fork with `uv`, checks each fix in the installed files by a sentinel string, derives the context variant from **your** installed stock context, and restarts the scheduled task. `-DryRun` reports what it would do and writes nothing. `-Source` points it somewhere else — your own fork, if you would rather not install from ours.

It **refuses to run from a shell whose `%APPDATA%` writes are redirected**, for the reason in the next section, and it detects that by writing a file and looking for it at the physical path a container redirects to. Do not test that by reading `%APPDATA%`: inside the container the variable still reads as the ordinary path, because only writes are redirected, so a string test passes happily and the install goes to the private copy anyway.

### By hand

```powershell
uv tool install --force git+https://github.com/Volksie/serena@codemem
```

Then put `ignore_all_files_in_gitignore: false` in your `.serena/project.yml`, and make the context: copy the `claude-code.yml` your install provides — under `serena/resources/config/contexts/` in its site-packages — into `%USERPROFILE%\.serena\contexts\claude-code-ue.yml`, delete the `- search_for_pattern` line from `excluded_tools`, and start the server with `--context claude-code-ue`. That's the form we ran; we haven't tested passing a file path to `--context`.

Then restart the server properly, which is **not** stopping and starting the scheduled task. When the task runs `Start-SerenaForUE.ps1`, stopping it kills only the watchdog; `serena.exe` and its language servers live on, the restarted launcher finds the port busy and exits with nothing to do, and the old build keeps serving. Run `Start-SerenaForUE.ps1 -Stop` first, which kills the watchdog, the whole tree and any orphans from earlier generations, and then start the task. Killing `serena.exe` on its own is not enough either: one generation is three processes, and the grandchild holds the listener.

### Which build is actually serving

**Ask the port, not the files, and not `uv tool list`.** More than one `serena_agent-*.dist-info` can sit in one `site-packages` — an in-place upgrade leaves the old one behind, and a packaged app's shell sees a *union* of its redirected copy and the real one, so it can list a version that is serving nothing. `direct_url.json` inside each `dist-info` says where that one came from. The installer prints it.

## Check it from outside your agent

**This is the step that matters, and we got it wrong for a day.** If your agent runs inside a packaged desktop app on Windows, its shell may see a redirected `%APPDATA%`. The path looks the same, but a file written there lands in the app's private copy, and the real server never loads it. We wrote every patch from inside the app, checked every patch from inside the app, and declared them live. None of them had run. A check from a normal PowerShell window said so, and we dismissed it as a false alarm.

So check from a normal terminal, against the running server rather than the files on disk. The server's own tool list is the proof:

- `find_symbol_indexed` is in it.
- `search_for_pattern` is in it, if you used the context variant.
- A scoped `get_diagnostics_for_file` on a project file comes back in seconds, not at the timeout.
- With the accept-loop hardening in, the server log shows `transient accept() error, listener kept` instead of `Accept failed on a socket`, the first time it happens.

## Licences

**Nothing in this directory is derived from Serena.** The two files here — *Install-SerenaForUE.ps1* and *layer1-state.json* — describe it and install it. What you install is Serena, Copyright (c) 2025 Oraios AI, licensed per component: `solidlsp` under MIT, the application under **GPL-3.0-or-later** from v2 onward, from them under their terms. v1.7.0, tagged `mit-final`, is the last MIT release.

The context variant is **derived on your machine** from the file your own install provides, so what you end up with is your file with one line removed and nothing was distributed to you.

An earlier release shipped three diffs, a new tool module, a `sitecustomize.py` carrying a CPython method under the PSF licence, and a modified copy of one of Serena's contexts. All of it is gone: the code fixes live on the fork, and the shim became `serena/util/accept_hardening.py` there. *NOTICE.md* at the repository root has the full statement.
