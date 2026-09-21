---
system: Module layout
modules: [AccelDemoCore, AccelDemo, AccelDemoTools]
classes: [UADStaminaComponent, AADCharacter, UMakeBenchBlueprintsCommandlet]
status: current
source: reconstructed 2026-09-12 from the .uproject, the .Build.cs files and the code
---

# Module layout

AccelDemo is three modules. The split is about which way dependencies point.

| Module | Type | Loading phase | Depends on | Holds |
|---|---|---|---|---|
| *AccelDemoCore* | Runtime | PreDefault | engine only | reusable gameplay components: stamina |
| *AccelDemo* | Runtime | Default | *AccelDemoCore* | the game: the character and what it can interact with |
| *AccelDemoTools* | Editor | PostEngineInit | both of the above, plus editor modules | the commandlet that generates the seed Blueprints |

## Why Core knows nothing about the game

*AccelDemoCore* has no dependency on *AccelDemo*, and that is the point of it. The stamina component can be put on any pawn without pulling the character in. It also explains an API shape that looks odd in isolation: the component exposes *NotifyDamaged* and waits to be told about damage, rather than watching the character's health, because it cannot see the character at all. The game module calls down into Core; Core never calls up.

The loading phases follow the same direction: *PreDefault* puts Core ahead of the game module at *Default*.

## Why the tools are a module and not assets

The benchmark needs Blueprints that genuinely call C++ functions and read C++ properties, because those are the callers no C++ tool can see. Blueprints are binary assets and cannot be written by hand, so *AccelDemoTools* generates them with a commandlet that places real call and property-read nodes in their graphs. The module is editor-only and loads after the engine is up, because it drives editor functionality; it never ships in a game build.

## Plugins

The project enables *UEAgentAccelerator* from this repository's `plugin/` directory, through `AdditionalPluginDirectories`, and the *UEAgentAcceleratorUht* entry for its UnrealHeaderTool exporter. It is editor-only and commandlet driven: it emits the project's reflection surface and its Blueprint-to-C++ edges, which the memory layers are built from. It is tooling, not gameplay, and none of the three modules above depends on it.
