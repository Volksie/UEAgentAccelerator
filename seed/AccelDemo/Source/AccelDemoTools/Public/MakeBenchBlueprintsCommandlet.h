#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "MakeBenchBlueprintsCommandlet.generated.h"

/**
 * Creates the seed Blueprints the benchmark needs, so the Blueprint questions in group E and F
 * have something real to run against. Blueprints are binary assets and cannot be hand written,
 * so they are generated here rather than committed by hand.
 *
 * The important part is that the graphs contain real UK2Node_CallFunction nodes pointing at C++
 * UFunctions. That is what makes BP_AccelDemoCharacter a genuine caller of ApplyDamage, invisible
 * to clangd and to ripgrep, which is the whole point of the exercise.
 *
 * Run with:
 *   UnrealEditor-Cmd.exe <project>.uproject -run=AccelDemoTools.MakeBenchBlueprints
 *     -unattended -nopause -nosplash -NullRHI -Multiprocess
 */
UCLASS()
class ACCELDEMOTOOLS_API UMakeBenchBlueprintsCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UMakeBenchBlueprintsCommandlet();
	virtual int32 Main(const FString& Params) override;
};
