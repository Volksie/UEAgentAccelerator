# Installing the plugin

This is the C++ plugin alone. `/ue-memory-stack:setup` calls it and then writes the rest of the
project side, so that is the normal route and this page is what it does underneath — worth reading when
the descriptor is unusual, when the project is in Perforce, or when you are choosing between copying and
sharing one checkout.

Two ways in, and which one you want depends on how many projects you're running this on.

## One project: copy it

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Install-UEAgentAccelerator.ps1 -ProjectPath D:\MyGame\MyGame.uproject
```

That copies *${CLAUDE_PLUGIN_ROOT}/ue-plugin/UEAgentAccelerator* into *MyGame\Plugins\UEAgentAccelerator*, adds the plugin to the `Plugins` array in the descriptor with `Enabled` true, and backs the descriptor up to *MyGame.uproject.bak* first.

Only the *.uplugin* and *Source* are copied. *Binaries* and *Intermediate* belong to whatever project built them, so copying those across gives you a DLL built for a different target.

The descriptor is edited as text rather than reserialised, so the diff is the few lines that changed and the file keeps its own indentation, line endings and byte order mark. The new entry is written in the style of the entry above it, so it looks like the editor wrote it:

```json
"Plugins": [
    { "Name": "UEAgentAccelerator", "Enabled": true }
]
```

If the descriptor already enables the plugin the file isn't touched at all, so re-running the installer doesn't dirty your tree, and an existing *.uproject.bak* is never overwritten.

A few descriptor shapes can't be edited in place: no `Plugins` key at all, an empty `Plugins` array, or an entry listed with no `Enabled` key. Those fall back to reserialising the whole file through `ConvertTo-Json`, which reindents with four spaces, can reorder keys and adds a byte order mark. The script warns when it does that. It's fine for Unreal and ugly in a diff, so on a descriptor small enough for it to matter it's easier to add the entry by hand and re-run.

## If your project is in Perforce

The descriptor is checked out before it's written, and there are two separate reasons for that.

The obvious one is that Perforce keeps controlled files read only until they're open for edit, so without a checkout the write just fails. It fails *after* the plugin has been copied into *Plugins* and the backup taken, which leaves the project looking installed and behaving as though it isn't: the plugin is on disk but the descriptor never enabled it, and the dump then reports zero modules.

The one worth knowing about is a descriptor of type `text+w`. The `+w` modifier keeps the file writable whether or not it's open, so the usual signal that a checkout was forgotten never fires. The write succeeds, the file never joins a changelist, and nobody finds out until the change turns out not to be in the submit. So the checkout is decided on whether the file is *controlled*, not on whether it's read only.

If `p4` isn't on `PATH`, or the server is unreachable, or the checkout is refused, the script clears the read only flag and carries on, and warns you so you can put the file in a changelist yourself. A Perforce outage shouldn't stop you installing a plugin. `-NoSourceControl` skips the whole thing deliberately.

**Note:** `p4` is run from the descriptor's own directory. Perforce settings usually come from a `P4CONFIG` file above your workspace and `p4` searches upwards from its working directory to find it, so a `p4` invoked from wherever you cloned this repository would find nothing and report the workspace as unknown. If the script says it cleared the read only flag on a file you know is in Perforce, check that `p4 -d <project folder> info` shows the client you expect.

*Invoke-AgentMemoryDump.ps1* does the same for its output folder, which matters as soon as you've committed a dump, and *New-CompileDatabase.ps1* does it for *compile_commands.json*.

## Several projects in one root: share the source

If you've got a few projects side by side, you probably don't want a copy of the plugin in each one drifting apart from the others. Point at a single copy instead:

```powershell
${CLAUDE_PLUGIN_ROOT}/scripts/Install-UEAgentAccelerator.ps1 -ProjectPath D:\Work\GameA\GameA.uproject -Mode Reference
```

That adds an `AdditionalPluginDirectories` entry to the descriptor pointing at the folder that *contains* the plugin folder, not at the plugin itself. **Give it `-PluginSource`.** Left to itself it references this plugin's own copy, and that path belongs to the plugin manager: it is not on anybody else's machine, and an update can move it, after which the editor has no plugin and says nothing at all. A layout like this works well:

```
D:\Work\
  Shared\
    UEAgentAccelerator\        one copy of the source, referenced by all three
  GameA\GameA.uproject
  GameB\GameB.uproject
  ToolsProject\Tools.uproject
```

with each descriptor carrying:

```json
"AdditionalPluginDirectories": [ "../Shared" ]
```

Relative entries are resolved against the project folder, so a relative path like that survives the whole tree being moved or renamed. Absolute ones don't, and they also can't be committed, so prefer relative.

**Important:** sharing the source does not share the binaries. Every project builds its own *UnrealEditor-UEAgentAcceleratorTools.dll*, so **every project needs its own build**. Build one and dump another and you get old format files, a success message and exit code 0. *Build-UEAgentAccelerator.ps1* checks for this and `-CheckOnly` runs the check on its own.

The DLL lands in the *plugin's* own *Binaries\Win64*, not the project's, so after a `-Mode Copy` install it's at *MyGame\Plugins\UEAgentAccelerator\Binaries\Win64\UnrealEditor-UEAgentAcceleratorTools.dll*. The build script checks the plugin folder, the shared source folder and the project's own *Binaries* and takes whichever is newest, so it finds it either way round.

## The exception: UHT exporters can't be shared this way

This one costs an afternoon to work out, so it's worth writing down.

If you extend this with a UnrealHeaderTool exporter, the shared-source trick stops working, because UBT's `EnumerateUbtPlugins` scans only the engine's and the project's own *Build*, *Source*, *Plugins* and *Mods* directories looking for `*.ubtplugin.csproj`. **It never consults `AdditionalPluginDirectories`**, and the csproj it finds must also sit under an enabled plugin's directory. So a UHT exporter parked in your shared folder is never discovered, never compiled and never registered, and nothing tells you why.

The pattern that works keeps one copy of the source and adds a thin shim per project:

```
D:\Work\
  Shared\UEAgentAccelerator\Source\UEAgentAcceleratorUht\Exporter.cs    the only copy
  GameA\Plugins\MyUhtPlugin\
    MyUhtPlugin.uplugin                    "Modules": [], it hosts no module
    Source\MyUhtPlugin.ubtplugin.csproj    compiles the shared .cs from ../../../../Shared/...
  GameB\Plugins\MyUhtPlugin\               same two files again
```

The *.uplugin* carries an empty `Modules` array, because the plugin exists only to be a directory UBT will look inside. The csproj pulls the source in from the shared location:

```xml
<ItemGroup>
  <Compile Include="..\..\..\..\Shared\UEAgentAccelerator\Source\UEAgentAcceleratorUht\*.cs" />
</ItemGroup>
```

So a project that needs the exporter gets another thin csproj, never another copy of the *.cs*. It's one more file per project and it keeps the thing you actually maintain in one place.

**Note:** those relative `Compile Include` paths are the one part of this that breaks if you move the shared folder, and it breaks at build time with a message about no source files rather than about a missing path. If you rename the shared directory, grep the csproj files.

## Not on Windows

Nothing in the plugin is Windows specific, only the scripts are. Copy *../ue-plugin* into your project's *Plugins* folder, add the two descriptor entries by hand, and build your editor target however you normally do. *03-running-the-dump.md* gives the commandlet invocation in full.

## Checking it actually loaded

The dump reporting zero modules almost always means the plugin didn't load rather than that your project has no modules. Look in *<Project>/Saved/Logs/<Project>.log* for:

```
LogPluginManager: Display: Skipping load of 'UEAgentAccelerator'
```

A *.uplugin* whose `EngineVersion` is older than the engine you're running compiles fine and is then skipped at startup, and `-unattended` answers the incompatibility dialog with No, so you get no dialog and no obvious error. The other cause is simpler: the plugin is on disk but was never enabled in the descriptor.
