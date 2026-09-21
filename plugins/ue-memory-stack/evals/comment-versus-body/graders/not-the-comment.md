---
type: llm
focus: last_message
---
The fixture has a doc comment saying the reach distance is "in metres" over a body returning 200.0f,
and Unreal world units are centimetres. The correct answer to "what does it return, in centimetres" is
**200**.

PASS if the answer states 200 cm as the value, including when it also mentions 20,000 in order to
reject it, explain the stale comment, or flag the ambiguity. Showing the working is not a failure.

FAIL if the answer states 20,000 cm as the value, or leaves the two readings as equally likely without
committing to 200.
