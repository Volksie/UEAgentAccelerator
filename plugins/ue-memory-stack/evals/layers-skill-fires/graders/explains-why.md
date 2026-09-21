---
type: llm
focus: last_message
---
PASS if the answer names the per-class artefact under Docs/AgentMemory/classes/ (or the index that points
at it) AND gives the reason: the replication condition is set in GetLifetimeReplicatedProps at runtime and
UnrealHeaderTool rewrites the specifiers, so the header does not carry the answer and a parser cannot see
it.

FAIL if it only names a file without the reason, or if it says the header or the UPROPERTY specifiers are
where to look.
