#pragma once

#include "CoreMinimal.h"

/**
 * Blueprint side of the agent memory dump.
 *
 * Tier 1 reads asset registry tags with no asset loading at all, which gives inheritance,
 * interfaces and whether a Blueprint has any graph logic.
 *
 * Tier 3 loads each Blueprint and walks its graphs for UK2Node_CallFunction and variable nodes,
 * resolving each back to the C++ UFunction or FProperty it targets. That produces the reverse
 * index, which is the only artifact in the stack that can answer "which Blueprints break if I
 * change this C++ function".
 */
namespace AgentMemoryBlueprintIndex
{
	/** Writes Blueprints.md and BlueprintCallers.md into OutDir. Returns the number of Blueprints seen. */
	int32 Emit(const FString& OutDir, bool bWalkGraphs);
}
