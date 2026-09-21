#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "AgentMemoryDumpCommandlet.generated.h"

/**
 * Emits one Markdown file per module describing the live reflection surface:
 * class hierarchy, interfaces, UFUNCTION and UPROPERTY specifiers, replication
 * conditions, and the doc comments UHT captured as metadata.
 *
 * The output is deterministic and uses no absolute paths, so it can be committed
 * and shared. It is the only layer that can answer COND_ questions, because those
 * live in GetLifetimeReplicatedProps at runtime and appear in no header.
 *
 * Run with:
 *   UnrealEditor-Cmd.exe <project>.uproject -run=UEAgentAcceleratorTools.AgentMemoryDump [-Modules=A,B] [-Out=Docs/AgentMemory]
 */
UCLASS()
class UEAGENTACCELERATORTOOLS_API UAgentMemoryDumpCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UAgentMemoryDumpCommandlet();

	virtual int32 Main(const FString& Params) override;
};