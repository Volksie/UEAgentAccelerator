# Layers 0 and 1: the compile database and the symbol index

Optional. This is what gives an agent compiler grounded answers to "where is this defined" and "what references this", rather than text matches. It's where the leverage is, and it's also where your toolchain gets a vote, so do it after the rest is working.

Two pieces: a compile database written by UnrealBuildTool, and clangd indexing it, fronted by Serena so an agent can query it.

> **Important: read *../serena/README.md* before you trust any of this.** On a tree with the engine in the workspace, a stock Serena install doesn't work. Every symbolic call walked the whole tree first, about 190s on ours. Epic's `.gitignore` overrode our `ignored_paths`. The stock context removed a tool our routing table depended on. None of that produced an error. We measured two benchmark versions on it before finding out. That folder says where the fixes come from — commits on a fork, installed with `uv`, rather than patches this repository ships — and how to check from outside your agent that they're actually live.

## What you get, and what you don't

**You get:** definitions, references, call hierarchies, types, and hover, all resolved by an actual C++ front end. When it answers, it's right.

**You don't get:** anything the reflection system holds. UnrealHeaderTool parses `UCLASS`, `UFUNCTION` and `UPROPERTY`, not the C preprocessor, so those macros are gone by the time clangd sees the file. It cannot tell you a function is `BlueprintCallable`, it has no idea `.uasset` files exist, and it will never see a replication condition. That's Layer 2's job and the routing table should say so, or an agent will ask clangd a question clangd cannot even know it's failing.

## 1. Generate the compile database

```powershell
.\New-CompileDatabase.ps1 -ProjectPath D:\MyGame\MyGame.uproject -EnginePath C:\UE_5.8
```

Add `-IncludeEngine` if you want symbol queries to reach engine types rather than stopping at your own code. That's a much bigger index and it's usually worth it.

Two bits of folklore that are false on 5.8, read out of *GenerateClangDatabase.cs* rather than off a forum:

- It sets `bForceAddGeneratedCodeIncludePath`, so the long standing complaint that the database omits the generated header directories is fixed.
- It uses a separate intermediate environment and disables unity and PCH, so it shouldn't clobber your normal build.

Still true: it isn't incremental, it rewrites the whole file every run, and every path in it is absolute. That last one matters. **Renaming or moving your tree invalidates the index**, because clangd's shards are keyed by source path. There's no "let it finish first" argument either, since finishing doesn't save it. If a rename is coming, rename first and index after.

Regenerate the database after any *.Build.cs* or module change.

**Several projects sharing one engine go in one invocation, not one each.** Pass them all and give it somewhere to write:

```powershell
.\New-CompileDatabase.ps1 -ProjectPath D:\Work\A\A.uproject,D:\Work\B\B.uproject -EnginePath C:\UE_5.8 -OutputDir D:\Work\.clangd-db
```

That matters more than it looks. UnrealBuildTool accumulates repeatable target arguments and can describe several targets in one database, resolving shared engine files once. Generating a database per project and concatenating them by hand leaves several entries for the same shared engine file, and whichever was merged first wins. It is correct only for as long as your targets happen to agree on the flags for shared code, and the first one that does not is resolved silently in favour of whoever merged first.

Measured on three targets that did agree: the hand merge and the single invocation produced the same 25,887 distinct files with **zero differing compile commands**, so the hand-rolled version had been right by coincidence rather than by construction. The single invocation was also about twice as fast.

**Note:** UBT's own output contains duplicate entries for shared files — 26,003 entries for 25,887 distinct files in that measurement. That is normal and harmless, clangd takes the first match, and a deduplicating merge step is not something you need to add.

## 2. Install Serena

Serena is at <https://github.com/oraios/serena>. Install it with `uv` as its quick start describes, on a Python it manages rather than a system one:

```
uv tool install -p 3.13 serena-agent
```

If you have no `uv` yet, `python -m pip install --user uv` is enough; there is no need for the piped web installer.

Then create the global configuration, which nothing else does for you and which *step 5* edits:

```
serena init
```

**Neither install puts anything on `PATH`.** `uv` lands in your Python user scripts directory and Serena's commands in `%USERPROFILE%\.local\bin`, and both installers say so in a line that is easy to scroll past. Until you add them, every command on this page fails as "not recognised" and the natural reading is that the install failed. Add both:

```powershell
$add = '%APPDATA%\Python\Python313\Scripts', '%USERPROFILE%\.local\bin'
$key = Get-Item 'HKCU:\Environment'
$raw = $key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
New-ItemProperty HKCU:\Environment Path -PropertyType ExpandString -Force `
  -Value ((@($raw -split ';' | Where-Object { $_ }) + $add) -join ';') | Out-Null
```

Read the existing value with `DoNotExpandEnvironmentNames` as above and write it back as `ExpandString`. Reading it the ordinary way expands the `%VARS%` already in there and writing that back freezes them to one machine's paths, which is a mess to unpick later and easy to do by accident.

**Note:** if your agent runs inside a sandbox or an app container, install a second copy outside it for any background service to use. A tool installed inside a container has its recorded paths pointing into that container, and a service started outside cannot resolve them. Both copies share `~/.serena`, so trust settings and downloaded language servers are common to them.

What that looks like when you hit it:

```
error: uv trampoline failed to canonicalize script path
```

`uv` installs its commands as trampolines, tiny launchers that record an absolute path to the environment they run. `~/.local/bin` is not redirected, so the launcher is genuinely on disk outside the container while the environment it points into is not, and it fails as above. A scheduled task running the same command gives you nothing but exit code 1.

**Installing again from outside is not enough on its own.** `uv` will not overwrite an executable it has no record of installing, and outside the container it has no record — its registry is redirected too, so the second install is working from an empty one. It reports success and leaves the broken launcher exactly where it was. Pass `--force`:

```powershell
uv tool install --force -p 3.13 serena-agent
```

Then confirm from outside, not from the agent: `serena --version`. Checking from inside the container tells you nothing, because in there the original install still resolves perfectly.

## 2b. Verify the installed file, not the installer's exit code

`uv tool install --force` can report success and leave the **old** file in site-packages. It happened
twice in one day here, to two different people, because the fork's version string does not move
between builds and uv reuses a cached one. Nothing in the output says so.

So after any install or upgrade, check the installed copy for something the change introduced:

```powershell
# the installer does this for every registered fix - run it yourself if you are not using the installer
Select-String -Path "$env:APPDATA\uv\tools\serena-agent\Lib\site-packages\solidlsp\ls_process.py" `
              -Pattern 'LANGUAGE SERVER DIED: ls_id='
```

If a fix reports missing straight after a successful install, suspect the install before the fix:

```powershell
uv cache clean serena-agent
uv tool install --force --reinstall git+https://github.com/Volksie/serena@codemem
```

`/ue-memory-stack:serena-setup` checks every registered fix this way and names the ones it cannot
find. That check is the proof the install landed; the installer's exit code is not.

## 2c. Optional: one long-lived server, warmed up at logon

Registered as a `stdio` server, Serena is started **once per client session**, so several chats mean
several Serena processes and several language servers over one clangd index. One long-lived HTTP
server means one of each.

It also fixes a first-call problem that reads as a broken install. **Project activation is lazy**:
the language servers do not start until the first symbolic tool call arrives. On a large Unreal tree
that has been measured at around **190 seconds against a 45 second tool timeout**, so whoever calls
first burns two or three failed calls and reasonably concludes Serena does not work. With the
launcher the cost is paid at logon instead — on that tree, warm-up finished in 154s and a genuinely
cold client afterwards got a 0.1s handshake and a 0.1s `find_symbol`.

Those are one tree's numbers, not a promise. `Start-SerenaForUE.ps1` ships beside the installer, and
**the installer offers it rather than registering it** — something that runs at logon is a different
kind of ask from a tool you invoke, and a process you did not know about is one you cannot debug.

```powershell
schtasks /create /tn "Serena MCP" /sc onlogon /rl highest /f /tr `
  "powershell -NoProfile -ExecutionPolicy Bypass -File <plugin>\serena\Start-SerenaForUE.ps1 -Project <your project root>"
```

Then point your client at `http://127.0.0.1:24290/mcp` instead of a stdio command.

**To restart it, run `Start-SerenaForUE.ps1 -Stop` and then start the task again.** Stopping the
task kills only the launcher, which is the watchdog; the server and its language servers survive,
the next start finds the port busy and exits with nothing to do, and the old server runs on
unwatched with none of the change. `-Stop` kills the watchdog, the whole tree and any orphans.

**The warm-up opens one file per language, not one file.** A single call activates the manager and
therefore starts every server, but each server still does lazy per-file work on its first document.
clangd in particular loads no compilation database until a file is opened, and a workspace symbol
query answers **instantly with nothing** until then — an empty result that reads exactly like "no
such symbol". The script discovers one real file per language under your project; if it picks badly,
edit `Get-WarmUpTargets`.

### If you adapt this, do not read the response body

This is the part worth reading even if you write your own launcher, because the obvious
implementation is the broken one.

The first version of the warm-up called the MCP endpoint with `Invoke-WebRequest` on the launcher's
own thread. **`-TimeoutSec` bounds only the response headers, not the body read**, and MCP
streamable HTTP answers with `text/event-stream`. It sat on an open stream for **eleven minutes**, so
the launcher never reached the next line and **the watchdog never armed** — a convenience feature had
disabled the thing that restarts a dead server.

The shipped version has two defences, either of which alone would have been enough:

1. the response body is never read (`HttpClient` with `ResponseHeadersRead`, disposed immediately) —
   the tool call does its work server-side whether or not anyone reads the reply;
2. the whole warm-up runs in a **background job**, so no bug in it can delay the watchdog again.

### One ordering rule that is not a preference

Serena's `--tool-timeout` must stay **below** your client's idle timeout. The wrong way round: the
client gives up and disconnects, Serena keeps working to its own longer timeout, and the reply to a
vanished client raises a disconnect error on the **listening** socket. On Windows the asyncio
proactor loop then stops accepting — the process survives, the dashboard survives, the MCP endpoint
does not. The server looks alive and answers nothing.

## 3. Point it at a clangd, explicitly

Serena bundles a clangd and will fall back to it silently. That fallback is the single most common reason this layer looks installed and answers nothing, so name the one you want.

On Windows the one to use ships with the Visual Studio LLVM component, at something like:

```
C:\Program Files\Microsoft Visual Studio\18\Professional\VC\Tools\Llvm\x64\bin\clangd.exe
```

**On version:** clangd does not have to match your compiler exactly, and a newer one is generally fine — we index with 22.x against a toolchain whose preferred version is 20.x and it works. What matters far more is that it is *a real toolchain clangd rather than the bundled fallback*, because the fallback is started without your compile database and therefore knows nothing about your project. If UnrealBuildTool starts complaining about your compiler version, that is a separate question about the compiler and not about the indexer.

## 4. Write the project configuration

This is the part that decides whether symbol queries reach across your projects and into the engine, and it is where a default install falls short. Create `.serena/project.yml` at the root of the tree that *contains* your projects, not inside one of them:

```yaml
project_name: "MyTree"

# Only what your routing table names. Each one is another process that can fail to start, and one
# that does takes all the others down with it. See the table below.
language_servers:
  - cpp
  - csharp   # for the .Build.cs and UBT row in the template routing table; drop both together

encoding: "utf-8"

# FALSE, and not only for speed. Serena appends every .gitignore's patterns AFTER ignored_paths and the
# last match wins, so Epic's ignore-everything-then-whitelist UnrealEngine/.gitignore overrides every
# engine exclusion below. With it on, ThirdParty and Binaries were tracked however we wrote them.
ignore_all_files_in_gitignore: false

# The projects AND the engine. Without the engine here, a query that walks into engine code stops
# at the boundary and reports nothing, which reads exactly like "no such symbol".
ls_workspace_folders:
  - "GameA"
  - "GameB"
  - "UnrealEngine/Engine"

# Everything here is either build output or content that costs a great deal to walk and answers
# nothing. Leaving them in is the difference between an index that finishes and one that does not.
ignored_paths:
  - "**/Binaries/**"
  - "**/Intermediate/**"
  - "**/Saved/**"
  - "**/DerivedDataCache/**"
  - "UnrealEngine/Engine/Source/ThirdParty/**"
  # The line above misses the other ThirdParty trees. Platform extensions and engine plugins carry
  # their own, and clangd died twice on an LLVM source file under Engine/Platforms/<console>/Source/ThirdParty
  # while Serena walked the engine. Checked against Serena's own is_ignored_path on real files: these
  # three are ignored, and plugin source outside ThirdParty is not. The walk that crashed is now refused
  # outright by the scope guard in serena/, so we haven't re-run it to test these lines on their own.
  - "UnrealEngine/Engine/Platforms/*/Source/ThirdParty/**"
  - "UnrealEngine/Engine/Plugins/**/Source/ThirdParty/**"
  - "UnrealEngine/Engine/Extras/ThirdPartyNotUE/**"
  - "UnrealEngine/Engine/Content/**"
  - "**/compile_commands*.json"
  - "**/.vs/**"

ls_specific_settings:
  cpp:
    ls_path: "C:/Program Files/Microsoft Visual Studio/18/Professional/VC/Tools/Llvm/x64/bin/clangd.exe"
    ls_extra_args:
      - "--compile-commands-dir=C:/Work/.clangd-db"
      - "--header-insertion=never"
      - "--background-index"
      - "-j"
      - "4"
      - "--pch-storage=disk"
```

**Three things here are also facts about your tree**, and they belong in *.claude/agent-memory-stack.json* rather than being typed into this file and the refresh script separately: the project folders in `ls_workspace_folders`, the compile database directory, and the Serena project and scheduled-task names. *00-getting-started.md* step 8 covers it. A project listed here and missing from the refresh, or the reverse, is the failure this stack is worst at noticing: everything runs, and the symbol index silently describes a tree that no longer matches.

`--compile-commands-dir` points at the **directory holding** `compile_commands.json`, not at the file. If you generated one database covering several projects, as *step 1* describes, that is the directory you gave `-OutputDir`.

### Which language servers to enable

Enable the ones your routing table actually names, and no more. Each is a separate process with its own runtime, and **Serena refuses to start its language server manager at all when any one of them fails to start** — so a server whose runtime is missing takes C++ down with it, and the error only surfaces on a call that reaches the manager. Every extra entry is another way for the whole layer to fail.

Serena fetches the servers itself, on demand. Most land under `~/.serena/language_servers/`, but what each one needs from you is decided by how it is *launched*, not by what is in that folder:

| Server | What it buys you | Runtime you must provide |
|---|---|---|
| `cpp` | Everything Layer 1 is for. The only one that is not optional | Your own clangd. Serena downloads one as a fallback and you should override it, see below |
| `csharp` | `.Build.cs`, `.Target.cs`, and queries into UnrealBuildTool itself | **`dotnet`** on PATH. It is Roslyn, run as a DLL by `dotnet.exe` |
| `hlsl` | Diagnostics on shader files. This is `shader-language-server`, shipping the DirectX shader compiler with it. It has no document symbols, so `get_symbols_overview` refuses a `.usf`, and it does not know Unreal's virtual include paths, so every `/Engine/...` include is reported as not found: read past those | None, a native binary |
| `markdown` | Structure in your docs. Rarely worth it | None, `marksman.exe` is native |
| `powershell` | Your build scripts, if you query them as code | **`pwsh`** on PATH. Windows PowerShell does not satisfy it |
| `json`, `yaml` | Structure in config files. Rarely worth it | **`node`**. Both run out of `node_modules/.bin` |
| `python` | Editor scripting and Python tooling in your tree | **`uv`**. Serena runs Pyright with `uvx --from pyright ...` rather than downloading it |

**If you want to check any of this on your own machine, read the launch command rather than the folder.** Serena logs one line per server as it starts it, in `~/.serena/logs/*.err.log`:

```powershell
Select-String -Path $env:USERPROFILE\.serena\logs\*.err.log -Pattern 'via command'
```

That is the authority. Looking at the folder instead is how you conclude that the C# server is a self contained binary, when in fact the `.exe` sitting next to the DLL is a build host helper and the server itself is started by `dotnet`.

**`PyrightServer/` being empty is normal**, and not a sign that anything failed. Python is the one server Serena does not download into that tree: it fetches and runs Pyright through `uvx`, so the directory exists and stays empty while the server works fine.

**The clangd it downloads is `clangd_19.1.2`, and that is a useful thing to know**, because it gives you a one glance diagnostic. If the process line in *step 6* shows a path containing `clangd_19.1.2`, you are running Serena's fallback rather than your own, whatever your configuration says. That is the untrusted-project failure, and no error is reported at any point.

The template routing table names a C# server for `.Build.cs` and UBT questions, so if you keep that row, enable `csharp`. If you delete the row, do not enable it. Keeping the two in step is the point: a routing table that names a tool you are not running sends an agent to something that returns nothing, and it falls back to grep having spent a call.

**Two of these bit us specifically.** `powershell` wants `pwsh`, and Windows PowerShell does not satisfy it. `json` and `yaml` want `node`. Neither runtime was installed, and the result was not "those servers are unavailable" but every Serena call hanging until it timed out, C++ included.

### Reaching source outside your tree

`ls_workspace_folders` holds paths under your project root. For source that lives elsewhere — UnrealBuildTool and AutomationTool are the usual case, if you want the C# row in your routing table to work — there is a sibling key that takes them:

```yaml
ls_additional_workspace_folders:
  - "C:/UE_5.8/Engine/Source/Programs/UnrealBuildTool"
  - "C:/UE_5.8/Engine/Source/Programs/AutomationTool"
```

**Registering a folder is not the same as indexing it.** A folder listed here is searched; whether it is *indexed* depends on the language server being enabled and started. We ran for a while with these registered and no `csharp` server, and `find_symbol` on a UBT class returned nothing at all — which reads as "that class does not exist" rather than "nothing is indexing C#".

### The rest of the keys

`project.yml` has about twenty more, and for this stack the defaults are right. Two are worth knowing about: `excluded_tools` trims Serena's tool surface, which matters if you are paying for tool schemas on every session and have measured that they cost you; and `read_only` stops Serena editing files, which is worth setting if you only ever want it answering questions.

## 5. Trust the project, or the configuration above is ignored

Serena applies `ls_specific_settings` only to a project it trusts. Untrusted, it silently ignores them and starts its bundled clangd with no compile database — which is the failure in *step 6* below, and it reports no error at any point.

Trust lives in `~/.serena/serena_config.yml`, and it needs **two** entries, not one:

```yaml
trusted_project_path_patterns:
  - C:\Work\MyTree
  - C:\Work\MyTree\**
```

The glob `...\**` does **not** match the bare root, so a single pattern ending in `\**` leaves the root itself untrusted. This one costs an afternoon, because everything looks configured and nothing takes effect.

## 6. Check what actually started, not what you configured

This is the part worth the doc. Layer 1 fails **silently and while looking healthy**, so verify the process rather than the config files:

```powershell
Get-CimInstance Win32_Process -Filter "Name='clangd.exe'" | Select-Object ProcessId,CommandLine
```

**No clangd at all is the normal state of a server nobody has queried yet.** Serena starts its language servers lazily, on the first call that needs one, not when the server starts. So a freshly started Serena has no `clangd.exe` and that is not a fault. Start looking for a cause only after you have made a query and it still is not there.

To make that query when your agent is not connected yet, drive the server over HTTP. Three calls: initialize, the initialized notification, then any scoped symbol lookup.

```powershell
$u = 'http://127.0.0.1:24290/mcp'
$h = @{ 'Content-Type'='application/json'; 'Accept'='application/json, text/event-stream' }
$init = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
$r = Invoke-WebRequest $u -Method Post -Headers $h -Body $init -UseBasicParsing
$h['mcp-session-id'] = $r.Headers['mcp-session-id']
Invoke-WebRequest $u -Method Post -Headers $h -Body '{"jsonrpc":"2.0","method":"notifications/initialized"}' -UseBasicParsing | Out-Null

$call = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"find_symbol","arguments":{"name_path":"<AClass>","relative_path":"<the file declaring it>"}}}'
(Invoke-WebRequest $u -Method Post -Headers $h -Body $call -UseBasicParsing -TimeoutSec 900).Content
```

Give it a long timeout: the first call pays the language server start, which on a tree with an engine in it is minutes rather than seconds. A result with line numbers in it means the whole chain works, and `clangd.exe` will now be in the process list to check.

Connected looks like your toolchain's clangd, pointed at your database. A path containing `clangd_19.1.2` is Serena's downloaded fallback and means your settings are being ignored:

```
.../VC/Tools/Llvm/x64/bin/clangd.exe --compile-commands-dir=<your db dir> --header-insertion=never
  --background-index -j 4 --pch-storage=disk --background-index-priority=low
```

Two ways it goes wrong, neither of which reports an error:

**A bundled fallback clangd with a bare `--background-index`.** Your `ls_specific_settings` are being ignored, and the usual cause is the project not being trusted, which makes them a no-op without saying so. Go back to *step 5* and check you have both trust patterns.

**The right binary with the wrong flags**, usually missing `--compile-commands-dir`. Serena is bound to a different project than the one whose `project.yml` you edited, or that setting names a file rather than the directory holding it. Registration can also live in more than one config file, one per client, and fixing one does nothing for the other.

A functional check once the process line looks right: ask for a symbol you know is in the engine, **scoped to the file that declares it**. If `find_symbol("FARFilter", relative_path=...)` returns the engine's own declaration, you're connected. `[]` does not mean the symbol is missing, it almost always means one of the two above.

**Important: never call `find_symbol` without `relative_path`.** Serena's symbol search doesn't use clangd's index. It walks every file in every workspace folder and asks for a document symbol tree per file, which with the engine in the workspace is tens of thousands of files. Re-measured with the per-call file walk patched out: scoped to a header, **0.01–12s** (12s is the first time a large header is opened, then about 0.1s). Unscoped, **it still times out**.

Our earlier figures, "scoped and cold 227s, unscoped 300s", were measured with Serena's per-call file walk still in place, so most of each number was the walk rather than the lookup. They're withdrawn.

**An unscoped call doesn't stop when your client gives up.** The client times out, and Serena carries on walking the engine on the server, sending a symbol request for every file. One of ours ran for **4 hours** after the client had disconnected. It ended by killing clangd twice, both times on the same third-party LLVM source file under a console platform directory. The next session found clangd gone, and nothing pointed back at a probe run hours earlier. Stock Serena refuses nothing, so without a patch the rule in your routing table is the only thing standing between one agent's mistake and everyone else's language server. The scope guard on the fork refuses the call before it starts, and refuses any directory holding more than 1,000 source files. Upstream closed the issue as not planned, so that one stays local; *../serena/README.md* has the install.

**For "where is X defined", use `find_symbol_indexed`** from *../serena/*, which asks clangd's index directly and answers in about 0.1s. Without that patch, find the file first and scope the call. `search_for_pattern` finds the file only if your context exposes it, and the stock `claude-code` context doesn't. Grep works either way.

## 7. Expect the first run to be slow

On a prebuilt index clangd tops it up rather than trusting it, a few hundred new shards at roughly 27 a minute, at around 4 GB resident. Queries issued during that can exceed even a very long timeout. Before concluding anything is broken, check whether shards are still being written:

```bash
find <index dir> -name '*.idx' -newermt '-4 minutes' | wc -l
```

For scale: on our tree the full engine plus projects database held 25,946 translation units, and indexing reached about 92% and 814 MB after roughly twelve hours. That's the cost of `-IncludeEngine`. It's a one off, and it's the reason this layer comes last.

## If every tool call hangs until it times out

Probably not clangd. Serena refuses to initialise its language server manager at all when **any** configured server fails to start, so one missing runtime takes the whole project down. The error naming the failed servers only appears once you make a call that reaches the manager, so a scoped query surfaces it while an unscoped one just hangs.

Check what language servers you have enabled and whether their runtimes are installed. We lost time to two of them needing runtimes that simply weren't on the machine.

### The other cause, which looks identical: `ignore_all_files_in_gitignore`

That setting defaults to `true`, and honouring it means walking the whole tree to find every `.gitignore` in it. On a tree with an engine in it that walk does not finish in any useful time, and it happens during startup, before any language server is launched. Nothing is reported. Every call hangs, exactly as above, and the natural conclusion is that you have a language server problem.

**Turn it off on a tree that is not in git.** A Perforce workspace does not have meaningful `.gitignore` files, only whatever the engine and vendored plugins happen to ship, so the setting buys nothing and costs everything:

```yaml
ignore_all_files_in_gitignore: false
```

Telling the two apart takes one look at the log, because they stop in different places. This one stops here and goes no further:

```
serena.project:_gather_ignorespec - Using 10 ignored paths from the project configuration.
serena.util.file_system:start - Loading of .gitignore files starting ...
serena.util.file_system:_load_gitignore_files - Processing .gitignore file: <tree>\.gitignore
```

A missing runtime gets past that and stops later, on the language server manager. We spent a while suspecting a newly added `csharp` server here, because it had just been enabled and the symptom appeared at the same time. It was innocent: with the gitignore walk turned off, `cpp` and `csharp` both start in under a minute.

## Run it as one long lived server, not one per session

This is the single change that made Layer 1 usable daily, and it is worth doing before you decide the whole layer is too slow.

**The default registration is `stdio`, which spawns a Serena per session.** Three chats open means three Serena processes and three clangd processes, all indexing the same tree and all reading and writing the same shard directory. The work is duplicated, the index peak is several GB *each*, and the language server warm up is paid again every time you start a session. On a tree with the engine in it that warm up is around ten minutes.

Registered over HTTP instead, there is one server, one clangd, one index, and the warm up is paid once.

Start it with:

```
serena start-mcp-server --transport streamable-http --host 127.0.0.1 --port 24290 ^
  --context claude-code-ue --project <your tree> ^
  --tool-timeout 600 --log-level WARNING
```

and register that instead of a command:

```json
{ "type": "http", "url": "http://127.0.0.1:24290/mcp", "timeout": 900000 }
```

Then start it at logon, with a scheduled task on Windows or whatever your platform's equivalent is, and it is simply always there.

**Start it from outside your agent, not from inside it.** The natural move, when you are already in a session, is to run the command there. Do that and the server is a child of the session: it dies with it, you are back to one Serena per session, and you have done the setup without getting any of the benefit.

```powershell
$exe  = "$env:USERPROFILE\.local\bin\serena.exe"
$args = 'start-mcp-server --transport streamable-http --host 127.0.0.1 --port 24290 ' +
        '--context claude-code-ue --project "D:\Work\Tree" --tool-timeout 600 --log-level WARNING'
Register-ScheduledTask -TaskName 'Serena MCP' -Force `
  -Action    (New-ScheduledTaskAction -Execute $exe -Argument $args) `
  -Trigger   (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME") `
  -Principal (New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited) `
  -Settings  (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1))
```

`Start-ScheduledTask -TaskName 'Serena MCP'` runs it now without waiting for a logon.

**`-ExecutionTimeLimit ([TimeSpan]::Zero)` is not optional.** The default limit is three days, after which Task Scheduler stops the task. For a server meant to be always there, that is a failure arriving long after anybody would connect the two.

Check it took, with `Get-ScheduledTaskInfo -TaskName 'Serena MCP'`. Two of the results are worth recognising, because the healthy one looks like an error:

| `LastTaskResult` | Means |
|---|---|
| `267009` | `0x41301`, **the task is running**. This is the healthy answer while the server is up |
| `1` | The executable could not run at all. On Windows this is almost always the trampoline problem in *step 2* |
| `0` | It ran and the process exited. For a server meant to stay up, that is a failure |

Then confirm it is genuinely detached, which is the entire point, by checking its parent:

```powershell
Get-CimInstance Win32_Process -Filter "Name='serena.exe'" | ForEach-Object {
  "$($_.ProcessId) parent=$((Get-CimInstance Win32_Process -Filter "ProcessId=$($_.ParentProcessId)").Name)"
}
```

`svchost.exe` means Task Scheduler owns it and it outlives every client. `powershell.exe`, `cmd.exe` or your agent means you started it from a session after all.

**About that 600.** It's deliberately generous, because on an unpatched install every symbolic call spends minutes in the file walk before doing anything, and a shorter timeout just makes every call fail. With the patches in *../serena/* applied we run **45s on the server and 60s on the client**, and nothing legitimate comes near it. Don't lower it until the file-walk patch is in, and confirm the patch is live from outside your agent first.

**`--context claude-code-ue` is the variant in *../serena/contexts/***. The stock `claude-code` context removes `search_for_pattern`. Use the stock one if your routing table doesn't name that tool.

**Important: `--tool-timeout` must stay below the client's timeout, and getting that backwards takes the server down in a way that looks like it is still up.** With the client at 900s and the server at 600s, the server always answers first. Reverse them and the client gives up and disconnects while Serena is still working; the reply then goes to a socket that is gone, which raises a disconnect error on the *listening* socket and stops it accepting. The process stays alive, the dashboard still responds, and the MCP endpoint answers nothing. We lost a session to that before finding it.

Getting the timeouts right isn't enough on Windows. The underlying fault is in CPython's event loop, and a correct configuration still triggers it under connection churn: one transient `accept()` error closes the listening socket for good. We logged it 15 times during benchmark runs, each an 8–9 minute outage. The accept-loop hardening on the fork fixes it, by re-arming the loop the way the Unix event loop already does.

**Note:** use `--log-level WARNING`. At INFO Serena echoes clangd's entire stderr into the log, which reached 37 MB in two hours.

### Watch the port, not the process, and log the drops

The failure above is the one that *setup* causes, and it has a twin that happens on its own under sustained load: the listener stops answering while the process stays alive, resident and apparently healthy. A watchdog that checks the process finds it running and does nothing. **Check the port.**

Even with a watchdog on the port, a restart is not free for whoever is mid-call. We measured this properly because it distorted a whole benchmark run: the seven slowest questions in a 170-question run were **exactly** the seven that logged a transport error, at a median of 886s against 44.7s for the rest. One of them re-ran in 120s once the server stayed up, against 1,162s when it had dropped twice — same question, same tools. The session pays twice, once while the call dies and again while the next one waits for the warm-up.

Two things make that findable instead of mysterious:

- **Record the transport errors alongside whatever else you record.** Without them the slow questions look like slow *code paths*, and we published two wrong explanations before the error log matched the times exactly.
- **Count the language-server processes now and again.** Each restart spawned a fresh set and left the previous set resident: thirteen orphaned groups on one machine, about 500 MB between them, with the live server at 3.1 GB and 4.4 GB of 31.4 GB free. Not proven as the cause of the drops, and the arrow plausibly points both ways, but a count that only ever goes up is worth knowing about.

Three consequences of a long lived server, all of which will confuse you once:

Restarting your editor or your agent does not restart Serena. That is the point of the arrangement, and it also means **a configuration change needs the server restarted, not the session** — editing the project config and starting a new chat does nothing at all.

A path check from inside a sandboxed session proves nothing about what a background service sees. On Windows in particular, an app that runs in a container has `%APPDATA%` redirected, so a launcher started by Task Scheduler resolves paths differently from anything the app spawns. Probe from outside rather than reasoning about it.

**Do not run `serena setup claude-code` afterwards.** It rewrites the client configuration with a `stdio` registration and quietly undoes all of this. The tool suggests it, and it is the right advice for the default setup and the wrong advice for this one.

## Deleting the wrong thing

Don't delete `<Project>/Intermediate/Build`. The compile database is a set of pointers into those response files, so removing them breaks clangd with an error that never mentions the missing files and looks exactly like clangd being broken.
