#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "ADStaminaComponent.generated.h"

// Tracks a pawn's stamina pool and its regeneration.
// See Docs/Design/StaminaSystem.md for why regeneration pauses after damage.
UCLASS(ClassGroup=(AccelDemo), meta=(BlueprintSpawnableComponent))
class ACCELDEMOCORE_API UADStaminaComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UADStaminaComponent();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType,
		FActorComponentTickFunction* ThisTickFunction) override;

	// Call this whenever the owner takes damage. It restarts the regeneration pause,
	// which is why damage has to tell the component rather than the component
	// watching health.
	UFUNCTION(BlueprintCallable, Category="AccelDemo|Stamina")
	void NotifyDamaged();

	// Adds Amount to the current stamina pool. Amount is in stamina points, not a
	// percentage, so passing 50 adds half the default pool rather than half of what
	// remains. Values that would take the pool outside 0..100 are clamped, and no
	// warning is issued for out of range input.
	UFUNCTION(BlueprintCallable, Category="AccelDemo|Stamina")
	void ApplyStamina(float Amount);

	// Returns how far this pawn can reach to interact with something, in metres.
	UFUNCTION(BlueprintPure, Category="AccelDemo|Interaction")
	float GetReachDistance() const;

	UFUNCTION(BlueprintPure, Category="AccelDemo|Stamina")
	float GetStamina() const { return Stamina; }

protected:
	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="AccelDemo|Stamina")
	float MaxStamina = 100.0f;

	// Stamina restored per second once regeneration resumes. Tuned against the
	// 2 second post-damage pause, so changing one without the other breaks the
	// recovery curve the design doc describes.
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="AccelDemo|Stamina")
	float RegenPerSecond = 12.0f;

	// How long regeneration stays paused after damage. See
	// Docs/Design/StaminaSystem.md for where the 2 came from; it is a playtest
	// result rather than a technical constraint.
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="AccelDemo|Stamina")
	float RegenPauseSeconds = 2.0f;

	/** Current stamina, 0..MaxStamina. Replicated to the owning client only; other
	 *  clients never see this value and must not branch on it. */
	UPROPERTY(Replicated, BlueprintReadOnly, Category="AccelDemo|Stamina")
	float Stamina = 100.0f;

	UPROPERTY(ReplicatedUsing=OnRep_Exhausted, BlueprintReadOnly, Category="AccelDemo|Stamina")
	bool bExhausted = false;

	UFUNCTION()
	void OnRep_Exhausted();

private:
	// Seconds left on the post-damage pause. Server side only, and deliberately not
	// replicated: clients see the result through Stamina, not the timer.
	float RegenPauseRemaining = 0.0f;
};