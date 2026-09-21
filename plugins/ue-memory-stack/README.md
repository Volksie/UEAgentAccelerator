# ue-memory-stack

The layered memory stack for Unreal codebases, as a Claude Code plugin. It writes down what your project actually looks like at runtime — reflection specifiers, replication conditions, Blueprint-to-C++ edges — in files small enough to read, and tells an agent which one answers which question.

```bash
claude plugin marketplace add Volksie/UEAgentAccelerator
claude plugin install ue-memory-stack@ue-agent-accelerator --scope project
```

## What you get

| | |
|---|---|
| `/ue-memory-stack:setup` | Write the project side of the stack into a tree, or report what is missing |
| `/ue-memory-stack:update` | Regenerate the layers: build, compile database, dump, verify |
| `/ue-memory-stack:status` | What exists, and whether it still describes the code |
| `/ue-memory-stack:doctor` | Checks every layer that fails quietly, and says what is broken, what fixes it, and what could not be checked |
| `/ue-memory-stack:serena-setup` | Install or check the Serena build Layer 1 needs on an engine tree |
| `ue-memory-layers` (skill) | Answers replication, specifier, blast-radius and inheritance questions from the artefacts instead of from a grep |
| `ue-memory-refresh` (skill) | When artefacts are stale, how to tell without trusting timestamps, and how to regenerate |
| `ue-memory-setup` (skill) | Installing the stack, and repairing a layer that answers but answers nothing |

## What is inside

| Path | What it is |
|---|---|
| `scripts/` | Install, build, dump, compile database, and a one-command refresh of every layer |
| `ue-plugin/UEAgentAccelerator/` | The C++ plugin: an editor-only commandlet that walks the live reflection system and the Blueprint graphs |
| `serena/` | The patches that make Layer 1 work on an engine tree, with their licence notices |
| `engine-api/` | Layer 3: the store builders and a six-tool MCP server over what UnrealHeaderTool and the descriptors declare. Opt-in, Python, no dependencies |
| `templates/` | What gets written into a project: the routing table, per-module rules, a design doc, the stack config |
| `docs/` | The guides, from getting started to troubleshooting, including the depot route for teams with no GitHub |
| `hooks/` | Two hooks that ship on and one that ships off, with the measured cost of each in `docs/10-hooks.md` |

Address any of it as `${CLAUDE_PLUGIN_ROOT}/...`. There is nothing to clone.

## The two steps nobody else can do for you

`/ue-memory-stack:setup` places both of these; finishing them is yours.

**Write the routing table.** It lands at your tree root as `CLAUDE.md`, with placeholders. Rewriting it for your tree is an hour, and it is the part that does most of the work: nothing makes an agent open the right artefact rather than grepping out of habit except this file.

**Finish the tree's facts.** `.claude/agent-memory-stack.json` is filled in from what setup could see and carries `<ANGLE BRACKET>` placeholders where it could not. Grep it for `<`. Complete, it means setup and refresh cannot disagree about which projects exist.

## Versioning

The version in *plugin.json* is the packaging's, and it moves when the tools or instructions change. It is **not** the benchmark result version: those belong to measured runs, and `plugins/ue-memory-bench/bench/arm-comparison-v6.md` in the repository is the current one. A plugin release does not make a benchmark number newer — and this release is a case in point, because the generator in it writes its artefacts with different line endings from the ones the run read, so the next measured result will be v7.

## Licence

MIT, beside this file. `serena/` contains modified Serena (MIT, Oraios AI) and a modified CPython method (PSF); both carry their notices, and the repository's *NOTICE.md* has the full attributions.
