# Third party notices

This repository is MIT licensed, see *LICENSE*. It doesn't vendor or redistribute any third party software. Everything listed here is something you install yourself, and its own licence applies to your copy of it rather than to anything in this repo.

We've only written down licence terms we've actually read. Where an entry just describes the relationship and links out, that's deliberate.

## Unreal Engine

Epic Games. Required to build and run anything here.

No Unreal Engine source is included in this repository, and none should ever be added to it. The plugin includes engine headers and links against engine modules when you build it, which is ordinary plugin work, but the engine itself stays on your machine under your own agreement with Epic. You need your own Unreal Engine licence, and your use of the engine is governed by Epic's terms rather than by ours.

**Important for contributors:** don't paste engine source into this repo, and don't transcribe an engine function into another language either. If you need engine behaviour, call the engine's own function from the plugin. A clause by clause reimplementation is still derived from engine code, and it's the kind of thing that gets a repository taken down rather than argued about. If you catch one, say so in the pull request.

## Serena

Copyright (c) 2025 Oraios AI. <https://github.com/oraios/serena>

Optional. Serena is what we use for Layer 1, the symbol queries that sit behind `find_symbol` and `find_referencing_symbols` in the routing table template. Nothing in this repo requires it, and the reflection dump works fine without it, so treat it as an upgrade rather than a dependency.

**This repository contains no Serena code, and that is deliberate.** Serena is licensed per component: `solidlsp` under MIT, and the Serena application under **GPL-3.0-or-later from v2 onward** (v1.7.0, tagged `mit-final`, is the last MIT release). This repository is MIT, so a patch against the Serena application — a diff carries the lines it changes — would put a GPL-derived file inside it, and every redistributor would inherit an obligation they were not told about.

So Layer 1's fixes are not shipped here. They are commits on a fork, and *plugins/ue-memory-stack/serena/Install-SerenaForUE.ps1* installs that fork with `uv`; *layer1-state.json* describes what a correct install looks like so the installer and the health check cannot disagree. Both files are ours and contain no Serena source. The one thing that used to be a modified copy of a Serena file — the context variant that stops `search_for_pattern` being excluded — is now **derived on your machine from the context your own install provides**, so what you end up with is your file with one line removed, and nothing was distributed to you.

The fork is at <https://github.com/Volksie/serena> (branch `codemem`); every patch on it is meant to go upstream, and one already has. What you install from there is GPL-3.0-or-later, from them, under their terms.

## CPython

Nothing in this repository contains CPython source.

An earlier release shipped a `sitecustomize.py` under the stack plugin's *serena/* directory, a modified copy of `BaseProactorEventLoop._start_serving` from CPython's `Lib/asyncio/proactor_events.py`, under the Python Software Foundation License. That shim is gone: the same fix now lives in the Serena fork as `serena/util/accept_hardening.py`, so it arrives with the install rather than from here. The entry is kept so anyone reading an older tag knows what it was.

## clangd and LLVM

Apache License v2.0 with LLVM Exceptions. <https://github.com/llvm/llvm-project>

Optional, and only relevant if you're running Layer 1. clangd builds the C++ index Serena queries. On Windows it usually comes with the Visual Studio LLVM component, so most people already have it and don't install anything.

## uv

MIT or Apache-2.0, Astral. <https://github.com/astral-sh/uv>

The Serena installer, *plugins/ue-memory-stack/serena/Install-SerenaForUE.ps1*, runs `uv tool install` to put Serena in its own environment. You install uv yourself; nothing of it is in this repository.

## IBM Plex

SIL Open Font License 1.1, IBM. <https://github.com/IBM/plex>

The project page in *docs/index.html* loads IBM Plex Sans, Serif and Mono from Google Fonts when you open it. The fonts aren't stored in this repository.

## Python 3

Used by the benchmark harness in *plugins/ue-memory-bench/bench/tools*. Install it yourself from <https://www.python.org>. The harness uses the standard library only, so there are no packages to install and nothing further to attribute.

## code-review-graph

MIT, Tirth Patel — <https://github.com/tirth8205/code-review-graph>.

Three ideas in `plugins/ue-memory-stack/engine-api/` are theirs, and are credited in the files that use
them: marking a result whose emptiness is ambiguous rather than returning a bare "no rows"
(`uncertainty.py`), costing response rows by measuring them and spending a budget by rank
(`budget.py`), and a `PostToolUse` matcher that includes `Bash`, because a `sed` edits a file just as
thoroughly as the Edit tool (`stamp-edit.py`).

**No code was copied.** The data model here is a SQLite store over UnrealHeaderTool output and on-disk
descriptors, which shares nothing with a tree-sitter graph, and every constant was measured against this
store rather than carried across. The ideas are what travelled, and the attribution is for those.

## Claude Code

Anthropic. The benchmark harness shells out to the `claude` CLI to run each question, so you need it installed and signed in if you want to run the benchmark. Everything else in this repo works without it. See <https://claude.com/claude-code>.

## Tools named in the docs but not used here

The routing table template mentions a few other things by name, because they answer question types the rest of the stack can't. We don't ship, wrap or require any of them, and they're listed so you know what the rows are talking about:

| Tool | What it covers in the template |
|---|---|
| shader-language-server | HLSL definitions under `Engine/Shaders` |
| unreal-api-mcp | Prebuilt engine API database |

## Trademarks

Unreal, Unreal Engine and the Unreal Engine logo are trademarks or registered trademarks of Epic Games, Inc. in the United States and elsewhere. This project is not affiliated with, endorsed by or sponsored by Epic Games. The name is descriptive: it's a tool for use with Unreal Engine, not an Epic product.
