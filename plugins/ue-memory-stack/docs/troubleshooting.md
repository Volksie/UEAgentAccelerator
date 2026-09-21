# Troubleshooting

**Start with `/ue-memory-stack:doctor`.** Most of what is below, it checks mechanically: an uninstalled plugin, an untrusted workspace, a DLL older than its source, a dump that reported success and wrote nothing usable, an empty Blueprint caller index, a compile database pointing at response files that are gone, and a Serena an upgrade has reverted. It also says plainly what it could not check. This page is for reading once it has told you where to look.

Everything here has actually happened, and most of these cost an hour or more the first time. They're grouped by what you see rather than by what's wrong, because what you see is what you have.

## The dump

### It reports 0 modules

The plugin didn't load. A *.uplugin* whose `EngineVersion` is older than the engine you're running compiles fine and is then skipped at startup, and `-unattended` auto answers the incompatibility dialog with No, so you get no dialog and no obvious error.

Look in *<Project>/Saved/Logs/<Project>.log* for:

```
LogPluginManager: Display: Skipping load of 'UEAgentAccelerator'
```

The other cause is simpler: the plugin is on disk but not enabled in the *.uproject*. A plugin that isn't enabled is loaded by nothing.

### It reports 0 Blueprints on a project that has some

They're in plugin content. Plugin content mounts under `/<PluginName>/` rather than `/Game/`, so a scan restricted to `/Game/` misses it. Game Feature plugins are the usual case, and on a big project most of the Blueprints can live outside `/Game/`.

This was a real bug in the scan, fixed on 7 September 2026, so if you're on an older copy that's the first thing to check.

### "Looked like a commandlet, but we could not find the class"

Use the module qualified name:

```
-run=UEAgentAcceleratorTools.AgentMemoryDump
```

The module loads at `PostEngineInit`, which is after commandlet class lookup, so a bare `-run=AgentMemoryDump` can't resolve. Qualifying it fixes this with no rebuild.

### "Could not find the class", but the module qualified name looks right

Check your quoting. In PowerShell, an unquoted `-run=Module.Class` loses the class half, and you get the same "looked like a commandlet, but we could not find the class" as a bare commandlet name.

```powershell
UnrealEditor-Cmd.exe MyGame.uproject "-run=UEAgentAcceleratorTools.AgentMemoryDump" ...
```

The scripts in this repository pass arguments as an array and are not affected. This bites when you type the command at a prompt, which is exactly when you are already debugging something else.

### It hangs forever, doing nothing

You're missing `-Multiprocess`. Without it the editor calls Turnkey, which shells out to *Build.bat* `-Mode=ValidatePlatforms`, which takes a global lock and then sits in a `ping` loop. See *TargetPlatformManagerModule.cpp:390*. The flag skips the SetupPlatforms call entirely.

### "Failed to load 'UnrealEditor-UEAgentAcceleratorTools.dll' (GetLastError=4551)"

Straight after a successful build, followed by "could not find the class", this is transient.

**Run the same command again.** Every import was checked against the exports of all seven dependent modules once, and nothing was missing. Don't go looking with `dumpbin`.

### It won't start at all

Check *ShaderCompileWorker.exe* exists in *Engine\Binaries\Win64*. Building the editor target doesn't guarantee it, and an interrupted build loses it. Rebuild with:

```
UnrealBuildTool.exe ShaderCompileWorker Win64 Development
```

About two minutes.

### It succeeds, but the files look wrong or old

The DLL is stale. This is the nastiest one in the list, because nothing fails: the dump runs, logs its usual "wrote index.md and N class files", exits 0, and writes the old format.

The plugin is shared by source but its binaries are built **per project**, so each project has its own *UnrealEditor-UEAgentAcceleratorTools.dll* and each one needs building. Build one project, dump three, and two of them silently write stale output.

The DLL is in the *plugin's* *Binaries\Win64*, not the project's: after a `-Mode Copy` install that's *<Project>\Plugins\UEAgentAccelerator\Binaries\Win64*.

*Build-UEAgentAccelerator.ps1* checks this for you, and `-CheckOnly` runs the check alone:

```
.\Build-UEAgentAccelerator.ps1 -ProjectPath ... -EnginePath ... -CheckOnly
```

**Important:** checking a small project is not checking the change. If you've modified the commandlet, verify the artefact the change was for. A spot check on a four class project once passed while 442 of 447 files elsewhere were stale.

### It writes everything correctly and then reports `exit=1`

Normal on any project with pre-existing content errors, and not about the dump. *UnrealEditor-Cmd* returns non-zero if anything logged an `Error` at any point in the run, whoever logged it and for whatever reason.

The first real project this was pointed at dumped 96 modules, 967 classes and 611 Blueprints perfectly and exited 1, on 567 log lines about a null `ProxyFactoryClass` in a Blueprint in somebody's developer folder. Those were there before the plugin was installed and would be there without it.

So judge the run on the summary lines and the file count, which is what the script does. It prints the exit code because it's occasionally a clue, and says so when it's non-zero with output written. If you want to know what tripped it, the errors are in *<Project>/Saved/Logs/<Project>.log*:

```powershell
Select-String -Path <Project>\Saved\Logs\<Project>.log -Pattern ': Error: ' | Select-Object -First 5
```

### "The game module 'X' could not be found", where X is one of yours

Two projects sharing one source engine, and the other one was built more recently.

Each project keeps its own *<Project>\Binaries\Win64\UnrealEditor.modules*, so they don't overwrite each other and it's easy to conclude they're independent. They're not. Those manifests are matched to the engine's own *<Engine>\Engine\Binaries\Win64\UnrealEditor.modules* by `BuildId`, and a build that regenerates the engine manifest gives it a new one. Every other project's manifest is then stale, and its modules stop resolving.

What you see is a dialog naming a module that exists, is compiled, and is listed in the manifest sitting next to it. Under `-unattended` the dialog is answered for you and the process is gone in about a second, so from the script it looks like the dump refused to start for no reason.

*Invoke-AgentMemoryDump.ps1* compares the two `BuildId`s before launching and stops with the command to fix it. The fix is to build the project you're about to dump.

**The order that avoids it entirely:** build and dump one project, then build and dump the next. Building both and then dumping both leaves the first one broken. Note the trigger is a build that rewrites the engine manifest, typically a first or otherwise substantial build of the other target; an incremental one doesn't disturb it, which is why this can appear to come and go.

### The dump reports a large file count for a run that wrote nothing

Fixed, but worth knowing what you were looking at if you've seen it. The output folder is meant to be committed, so on a re-dump it's already full, and a count of what's in it comes back reassuringly large whether or not this run wrote any of it. A dump that died in a second once reported `files=1383` and `Wrote 1383 files`.

The count is now of files touched since the process started, and the summary shows both:

```
exit=1  wall=104.6s  written=1383  in folder=1383
```

If `in folder` exceeds `written`, the extra files are left over from a previous run: a class deleted from the code leaves its file behind, and nothing regenerates or removes it. Delete the folder and dump again if you want it to match the tree exactly.

### The second dump leaves output that's part old and part new

Perforce, and only on a project that committed its first dump. The artefacts come back read only, the commandlet's writes fail, and it doesn't stop on a failed write: it carries on, logs its usual summary and exits 0, so the folder ends up half updated with nothing anywhere saying so.

*Invoke-AgentMemoryDump.ps1* opens the output folder for edit before it runs, which is the fix. If you're driving the commandlet directly, check the folder out yourself first:

```
p4 edit <Project>/Docs/AgentMemory/...
```

## Builds

### UBT can't find the target, or builds one that isn't yours

`<ProjectName>Editor` is a convention, not a rule. A descriptor named one thing can perfectly well build a target named another, because the target name comes from the *Target.cs* file and nothing makes it match the descriptor. A project that was renamed at some point is the usual way the two drift apart.

The scripts read the *Target.cs* files under *<Project>\Source* and use the one declaring `TargetType.Editor`. If there's more than one they say which and stop, and you pick with `-Target`. If you're building by hand, look at the filenames rather than assuming.

### UBT says "Result: Failed (OtherCompilationError)" but nothing is wrong

You're wrapping UBT in PowerShell with `2>&1`. On PowerShell 5.1, redirecting a native executable's stderr wraps each line in an ErrorRecord and corrupts `$?`, so a build that succeeded is reported as failed. Measured on 8 September 2026: one target failed three consecutive scripted attempts and succeeded every time it was run directly, and half an hour went into retrying a build that was never broken.

Run UBT from a plain shell, or redirect the two streams to separate files. The scripts here do the latter.

### A build sits there and never starts

*Build.bat* takes a batch level lock that survives a cancelled build and blocks the next one. Call UnrealBuildTool directly instead, which is what these scripts do. If one is already stuck, find the *cmd.exe* whose command line mentions *Build.bat* and kill it.

### The build serialises onto one process and takes forever

On some machines UBA needs a large fixed page file, and without one it quietly gives up on parallelism rather than telling you. If a 24 core machine is building like a 1 core machine, check the page file before anything else.

## Layer 1, clangd and Serena

Layer 1 is the part that comes up looking healthy while being bound to the wrong thing, so check the process rather than the config files.

```powershell
Get-CimInstance Win32_Process -Filter "Name='clangd.exe'" | Select-Object ProcessId,CommandLine
```

Connected looks like the toolchain's own clangd with your merged database:

```
.../VC/Tools/Llvm/x64/bin/clangd.exe --compile-commands-dir=<your db> --header-insertion=never
  --background-index -j 4 --pch-storage=disk --background-index-priority=low
```

Two ways it goes wrong, both silent:

1. **A bundled fallback clangd with a bare `--background-index`.** That's what you get when the project isn't trusted, which makes the per language server settings a no op. Trust patterns are exact about trailing separators: a pattern ending `\**` does not match the bare root, so the root needs its own entry.
2. **The right binary with the wrong flags**, usually no `--compile-commands-dir`. Serena is bound to a different project. Registration can live in more than one config file, one per client, and fixing one does nothing for the other.

`find_symbol` returning `[]` for an engine symbol doesn't mean the symbol is missing. It usually means one of the above. A quick functional check once the process line looks right: `find_symbol("FARFilter", relative_path=...)` should return the engine's own declaration.

### `find_symbol` never returns

You called it without `relative_path`. **It is also still running**, on the server, after your client gave up. An unscoped call that timed out in 45s on our tree carried on walking the engine for four hours and killed clangd at the end of it. Restart Serena rather than waiting, and apply the scope guard in *../serena/* so the call gets refused next time instead of starting. Serena's symbol search does not use clangd's index; it walks every file in every workspace folder asking for a document symbol tree, which is tens of thousands of files with the engine in the workspace. Unscoped, it times out. Use `find_symbol_indexed` from *../serena/* to get the file, or Grep, then scope the call.

**If scoped calls time out too**, it's not the lookup. Every symbolic call starts with a walk of the whole tree to catch outside edits, about 190s on ours, and nothing in the configuration turns it off. See *../serena/README.md*, "The per-call file walk".

### `search_for_pattern` doesn't exist

Serena's stock `claude-code` context removes it, because it duplicates the host agent's Grep. Nothing errors: a routing table that names it just points at nothing, and the agent falls back to Grep. Use the variant in *../serena/contexts/*, or route those rows to Grep.

### clangd has quietly gone, and nobody restarted anything

Look for an unscoped `find_symbol` somewhere earlier: yours, another session's, or a probe script's. Serena keeps walking the tree on the server long after the client times out, and on our tree that walk ended by crashing clangd on a third-party LLVM file under `Engine/Platforms/*/Source/ThirdParty`, twice. *05-serena-clangd.md* adds that path to `ignored_paths`. Serena's log shows the walk as thousands of `textDocument/documentSymbol` requests with no client attached.

### `find_symbol_indexed` returns `[]` for something that definitely exists

clangd hasn't loaded its index yet. Straight after a restart it returns nothing in about 0.1s until at least one file has been opened, then takes a couple of minutes to load. Make one file-based call first, such as a scoped `get_diagnostics_for_file`, and try again.

### Serena is running, the dashboard responds, and no tool call ever returns

If you run it as a long lived HTTP server, check `--tool-timeout` against the client's timeout. The server's must be the **lower** of the two, so it always answers before the client gives up.

With them the wrong way round the client disconnects while Serena is still working, and the reply then goes to a socket that no longer exists. That raises a disconnect error on the *listening* socket and it stops accepting new connections. The process stays up, the dashboard keeps answering, and the MCP endpoint is dead — so every check you would think to run says the server is fine.

**If the timeouts are right and it still happens**, it's the same failure with a different trigger. On Windows one transient `accept()` error closes CPython's listening socket permanently, and a client connecting and disconnecting often, as a benchmark does, eventually causes one. Look for `Accept failed on a socket` with `WinError 64` in the log. The accept-loop hardening on the fork fixes it — `/ue-memory-stack:serena-setup` installs that build — and a watchdog should check the port rather than the process.

Restart the server. Then set the timeouts so the server's is comfortably below the client's.

### Every tool call hangs until it times out

Probably not clangd. Serena refuses to initialise the language server manager at all when *any* configured server fails to start, so one missing runtime takes the whole project down. The error naming the failed servers only appears once you make a call that reaches the manager, so a scoped query surfaces it while an unscoped one just hangs.

### Queries time out on first run against a prebuilt index

clangd tops the index up rather than trusting it wholesale, a few hundred new shards at around 27 a minute. Queries issued while that's happening can exceed even a very long tool timeout. Check whether shards are still being written before concluding anything is broken:

```bash
find <index dir> -name '*.idx' -newermt '-4 minutes' | wc -l
```

### clangd breaks in a way that looks like clangd being broken

Did you delete *<Project>/Intermediate/Build*? The compile database is a set of pointers into those response files, so deleting them breaks clangd with an error that never mentions the missing files. Regenerate the database after any *.Build.cs* or module change, and leave the intermediates alone otherwise.

## Getting a straight answer out of the artefacts

### A class file is enormous

Most aren't. The median is around 1,200 bytes on a plugin sized project and 560 on a big game, but the distribution has a tail: one class in several hundred goes past 20 KB, and the biggest we've seen is 32 KB.

Grep the file for the row you want, or read just the Properties or Functions table. Measured on 8 September 2026: on a one row replication question, reading the 32 KB file whole cost about 33,000 bytes of retrieval against 8,132 for a grep. Both answered correctly and one paid four times for it.

### The comment and the code disagree

Believe the code. For anything about units, ranges, bounds or contracts, the comment alone isn't an answer, and hover is worse than useless here because it returns the comment with nothing to contradict it. The seed project has a deliberate example: `GetReachDistance` says metres and returns centimetres. Measured both ways, hover answered "metres" and plain file reading answered centimetres and flagged the disagreement.
