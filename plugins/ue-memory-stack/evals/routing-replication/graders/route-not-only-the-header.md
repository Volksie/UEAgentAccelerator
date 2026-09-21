---
type: llm
focus: last_message
---
The question was where each replication condition came from.

PASS if the answer attributes the conditions to the generated reflection artefact (a file under
Docs/AgentMemory), or to GetLifetimeReplicatedProps in the .cpp - both are places the condition is
actually stated.

FAIL if it says the conditions come from the header or from the UPROPERTY specifiers, because the header
carries no condition at all: `UPROPERTY(Replicated)` is the same text for both properties, and the two
properties replicate under different conditions.

FAIL if it hedges to the point of not naming a source.
