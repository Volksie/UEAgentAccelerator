#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "ModuleAvailabilityCommandlet.generated.h"

/**
 * Emits declared platform availability for every plugin module on disk, by calling the engine's own
 * FModuleDescriptor::IsCompiledInConfiguration rather than reimplementing its rules.
 *
 * WHY THIS EXISTS. The descriptor tier of the engine API database originally evaluated the
 * allow/deny semantics in Python, transcribed clause by clause from ModuleDescriptor.cpp. That was
 * accurate and it was the wrong thing to do twice over: it is a derivative of engine source, which
 * cannot be published, and the design had already said not to -
 *
 *     "the allow/deny semantics get evaluated once by the engine's own function rather than
 *      reimplemented by us and got subtly wrong"   - our own design note, written and ignored
 *
 * So the matrix is resolved here, once, by the function that defines it, and the Python reads the
 * result instead of recomputing it. There is now exactly one implementation of these rules in the
 * world and Epic owns it.
 *
 * WHAT IT DOES NOT COST. Declared availability still needs no console SDK and no console build:
 * IsCompiledInConfiguration evaluates the descriptor, not the toolchain, so console answers come
 * out of a Win64 editor. What it does need, which the Python did not, is an editor to run in.
 *
 * Run with:
 *   UnrealEditor-Cmd.exe <project>.uproject -run=UEAgentAcceleratorTools.ModuleAvailability
 *     [-Out=<file>] [-Platforms=Win64,Android,...] [-Roots=<dir>;<dir>]
 *     -unattended -nopause -nosplash -NullRHI -Multiprocess
 */
UCLASS()
class UEAGENTACCELERATORTOOLS_API UModuleAvailabilityCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UModuleAvailabilityCommandlet();

	virtual int32 Main(const FString& Params) override;
};
