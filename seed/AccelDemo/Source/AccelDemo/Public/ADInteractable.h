#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "ADInteractable.generated.h"

UINTERFACE(MinimalAPI, BlueprintType)
class UADInteractable : public UInterface
{
	GENERATED_BODY()
};

// Implemented by anything the player can walk up to and use.
class ACCELDEMO_API IADInteractable
{
	GENERATED_BODY()

public:
	// Returns the text shown on the interaction prompt. Blueprints may override
	// this; the C++ default lives in each implementing class.
	UFUNCTION(BlueprintNativeEvent, BlueprintCallable, Category="AccelDemo|Interaction")
	FText GetInteractionPrompt() const;

	// Called on the server when the interaction is confirmed. Deliberately plain
	// C++ rather than a UFUNCTION, so it stays invisible to Blueprints and to the
	// reflection dump. That asymmetry is intentional: it gives the benchmark a
	// function that clangd can see and the reflection layer cannot.
	virtual void OnInteracted(class AActor* Interactor) = 0;
};