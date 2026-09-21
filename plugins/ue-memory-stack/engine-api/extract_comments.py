"""Index every comment block in the projects' C++, not just doc comments on reflected declarations.

WHY THIS EXISTS. Layer 2 walks `UClass` data, so it carries the doc comment attached to a reflected
declaration and nothing else. A comment inside a function body is in no artefact at all - grep a
generated `classes/<Class>.md` for one and you get nothing, because it was never there to find.

That is not academic. It was found by a benchmark question whose whole answer was a `// HACK:` comment
three lines into a `.cpp`: the artefacts could not carry it, the symbol index does not index prose, and
the arm with every layer available invented an explanation rather than finding the comment. An index of
comment blocks, with a file and line beside each, is the only layer that can answer that shape of
question.

WHAT THIS IS NOT. This is the *index*, not the matcher. It puts the corpus somewhere searchable with a
citation attached; whether we later match against it lexically (FTS5, which is what happens today) or
semantically (embeddings) is a separate decision, and an embedding index over comments would be built
over exactly these rows. Extracting is the prerequisite either way.

SCOPE. Your projects' own `Source/` trees, including the ones inside their plugins. Not the engine,
which is around 93,000 files and a different decision: the engine's comments are worth indexing, but
the cost and the staleness rules are not the same, so that is deliberately left out here.

WHICH PROJECTS. Every directory under `--root` that holds a `.uproject`, unless `--projects` names them
explicitly. It used to be a hardcoded list of the three projects this was written against, which would
have indexed nothing at all in anyone else's tree while reporting success.
"""
from __future__ import annotations

import pathlib
import re

def discover_projects(root: "pathlib.Path") -> "list[str]":
    """Every directory under root holding a .uproject, sorted. The store is per tree, not per project,
    so this is the same rule the merge job uses when it globs for artefact directories."""
    return sorted(p.parent.name for p in root.glob("*/*.uproject"))
SUFFIXES = {".h", ".cpp", ".hpp", ".inl"}
SKIP_DIRS = {"Intermediate", "Binaries", "Saved", "DerivedDataCache", "DerivedDataBackendGraph"}

# A line that plausibly declares the thing a following comment belongs to. Deliberately loose: the
# symbol is metadata to help a reader place the hit, not something we assert as ground truth.
DECL = re.compile(
    r"^\s*(?:(?:UE_API|FORCEINLINE|static|virtual|inline|explicit|constexpr)\s+)*"
    r"(?:[\w:<>,\*&\s]+?\s+)?"
    r"(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)?)\s*\("
)
TYPE_DECL = re.compile(r"^\s*(?:class|struct|enum(?:\s+class)?)\s+(?:\w+_API\s+)?(?P<name>[A-Za-z_]\w*)")
MARKER = re.compile(r"\b(HACK|TODO|FIXME|NOTE|XXX|WORKAROUND|WARNING|IMPORTANT)\b")

# `if (`, `for (`, `return Foo(` and friends all match the call-shaped DECL pattern. Attributing a
# comment to "if" is worse than attributing it to nothing, because the metadata reads as fact.
KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "sizeof", "do", "else",
            "case", "new", "delete", "throw", "static_cast", "const_cast", "reinterpret_cast",
            "dynamic_cast", "check", "checkf", "ensure", "ensureMsgf", "verify"}

# Lines a declaration can hide behind. A header doc comment is usually separated from the thing it
# documents by a reflection macro, so forward attribution has to look past these.
SKIP_AHEAD = re.compile(r"^\s*(?:$|//|/\*|\*|U(?:PROPERTY|FUNCTION|CLASS|STRUCT|ENUM|INTERFACE|META)\s*\(|"
                        r"GENERATED_\w+|UE_API\b|template\s*<|friend\b|\}|\{|public:|protected:|private:)")

# Boilerplate that would otherwise dominate the index. Epic's copyright header is on every file.
NOISE = re.compile(r"^(copyright|all rights reserved|fill out your copyright)", re.I)


def _split_identifier(name: str) -> str:
    """`GetReachDistance` -> `Get Reach Distance`, so a search for one word in a name matches it.

    Costs nothing and closes the most common half of "I only half remember what it is called".
    It does not help with a *synonym* of the name, which is the case embeddings would be for.
    """
    if not name:
        return ""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return s.replace("_", " ").replace("::", " ")


def _decl_name(line: str) -> str:
    """The symbol this line declares, or "" if it declares nothing worth recording."""
    m = TYPE_DECL.match(line) or DECL.match(line)
    if not m:
        return ""
    cand = m.group("name")
    if cand in KEYWORDS:
        return ""
    if cand.isupper() and len(cand) > 2:       # UPROPERTY, GENERATED_BODY and friends
        return ""
    return cand


def _lookahead_decl(lines: list[str], idx: int, window: int = 5) -> str:
    """The first real declaration at or after `idx`, looking past macros and blank lines.

    A doc comment belongs to what follows it, but what follows it is usually `UPROPERTY(...)` or
    `UFUNCTION(...)` rather than the declaration itself. Without this, every documented reflected
    member is attributed to whatever happened to be declared above it, which is both wrong and
    confidently stated.
    """
    for j in range(idx, min(idx + window, len(lines))):
        line = lines[j].strip()
        if SKIP_AHEAD.match(line):
            continue
        name = _decl_name(line)
        return name or ""
    return ""


def _source_roots(root: pathlib.Path, projects=None):
    """Every `Source` tree belonging to each project, **including plugin modules**.

    Scanning only `<Project>/Source` misses most of the code on any project of size: a sample game can
    keep fourteen of its sixteen modules in Game Feature plugins under `Plugins/`, and a plugin project
    keeps all of its own code there. Same mistake as assuming a project's content is all under `/Game/`
    when more Content roots sit under `Plugins/`.
    """
    for project in (projects or discover_projects(root)):
        base = root / project
        if not base.is_dir():
            continue
        top = base / "Source"
        if top.is_dir():
            yield top
        plugins = base / "Plugins"
        if plugins.is_dir():
            for candidate in plugins.rglob("Source"):
                if candidate.is_dir() and not SKIP_DIRS.intersection(candidate.parts):
                    yield candidate


def iter_comment_blocks(root: pathlib.Path, projects=None):
    """Yield (rel_path, line_no, enclosing_symbol, text) for each contiguous comment block."""
    for src in _source_roots(root, projects):
        for path in src.rglob("*"):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.parts):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue

            rel = path.relative_to(root).as_posix()
            last_decl = ""
            block: list[str] = []
            block_start = 0
            in_c_comment = False

            for i, raw in enumerate(lines, start=1):
                line = raw.strip()
                is_comment = False

                if in_c_comment:
                    is_comment = True
                    body = line[:line.index("*/")] if "*/" in line else line
                    block.append(body.lstrip("*").strip())
                    if "*/" in line:
                        in_c_comment = False
                elif line.startswith("//"):
                    is_comment = True
                    if not block:
                        block_start = i
                    block.append(line.lstrip("/").strip())
                elif line.startswith("/*"):
                    is_comment = True
                    if not block:
                        block_start = i
                    body = line[2:]
                    if "*/" in body:
                        block.append(body[:body.index("*/")].strip())
                    else:
                        in_c_comment = True
                        block.append(body.strip())

                if is_comment:
                    if len(block) == 1:
                        block_start = i
                    continue

                # Not a comment line.
                decl_here = "" if line.startswith("#") else _decl_name(line)

                if block:
                    text = " ".join(x for x in block if x).strip()
                    if text and not NOISE.match(text):
                        # Attribute FORWARD where we can, looking past reflection macros.
                        # `// Returns how far this pawn can reach` sits above GetReachDistance and
                        # below ApplyStamina, separated from it by a UFUNCTION line; taking the
                        # preceding declaration labelled it ApplyStamina, which is worse than useless
                        # because it reads as fact. Fall back to the enclosing symbol only when
                        # nothing is declared ahead, which is the inside-a-function-body case.
                        ahead = _lookahead_decl(lines, i - 1)
                        yield rel, block_start, (ahead or last_decl), text
                    block = []

                if decl_here:
                    last_decl = decl_here

            if block:
                text = " ".join(x for x in block if x).strip()
                if text and not NOISE.match(text):
                    yield rel, block_start, last_decl, text


def index_comments(con, root: pathlib.Path) -> tuple[int, int]:
    """Insert comment rows into the existing `search` FTS5 table. Returns (rows, files).

    No schema change: the table is fts5(kind, name, owner, doc) and the four columns carry
      kind  = 'comment'
      name  = enclosing symbol, plus its camelCase split so partial-name searches hit
      owner = '<relative path>:<line>', which is what makes a result a citation and not just a hit
      doc   = the comment text, with any HACK/TODO/NOTE marker kept so `kind:comment TODO` works
    """
    rows = 0
    files = set()
    for rel, line, symbol, text in iter_comment_blocks(root):
        name = symbol
        split = _split_identifier(symbol)
        if split and split.lower() != symbol.lower():
            name = f"{symbol} {split}"
        con.execute("INSERT INTO search (kind, name, owner, doc) VALUES ('comment', ?, ?, ?)",
                    (name, f"{rel}:{line}", text))
        rows += 1
        files.add(rel)
    return rows, len(files)


if __name__ == "__main__":
    import argparse
    import collections

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parents[2])
    ap.add_argument("--grep", help="show blocks whose text matches this (case-insensitive)")
    ap.add_argument("--projects", help="comma-separated project directory names; default is every "
                                       "directory under --root holding a .uproject")
    args = ap.parse_args()

    n = 0
    marked = collections.Counter()
    per_file = collections.Counter()
    projects = [p.strip() for p in args.projects.split(",")] if args.projects else None
    for rel, line, sym, text in iter_comment_blocks(args.root, projects):
        n += 1
        per_file[rel] += 1
        m = MARKER.search(text)
        if m:
            marked[m.group(1)] += 1
        if args.grep and args.grep.lower() in text.lower():
            print(f"  {rel}:{line}  [{sym}]  {text[:160]}")
    print(f"\n{n:,} comment blocks across {len(per_file):,} files")
    print("markers:", dict(marked.most_common()))
