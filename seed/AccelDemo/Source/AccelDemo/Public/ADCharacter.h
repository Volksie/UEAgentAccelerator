#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "ADInteractable.h"
#include "ADCharacter.generated.h"

class UADStaminaComponent;

UCLASS(Blueprintable, BlueprintType)
class ACCELDEMO_API AADCharacter : public ACharacter, public IADInteractable
{
	GENERATED_BODY()

public:
	AADCharacter();

	virtual void BeginPlay() override;
	virtual void OnInteracted(AActor* Interactor) override;
	virtual FText GetInteractionPrompt_Implementation() const override;

	/**
	 * Applies damage to this character. Server only.
	 * Always call this rather than setting Health directly: Health is replicated
	 * with a condition, and writing to it outside this function skips the
	 * replication bookkeeping, so clients will keep the stale value until some
	 * unrelated property forces a resend.
	 */
	UFUNCTION(BlueprintCallable, Category="AccelDemo|Combat")
	void ApplyDamage(float Amount);

	UFUNCTION(BlueprintPure, Category="AccelDemo|Combat")
	bool IsAlive() const { return Health > 0.0f; }

	UFUNCTION(Server, Reliable, Category="AccelDemo|Combat")
	void ServerRequestRespawn();

	UFUNCTION(NetMulticast, Unreliable, Category="AccelDemo|Combat")
	void MulticastPlayHitReaction(float Amount);

	UFUNCTION(Client, Reliable, Category="AccelDemo|Combat")
	void ClientNotifyDeath();

protected:
	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="AccelDemo")
	TObjectPtr<UADStaminaComponent> Stamina;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="AccelDemo|Combat")
	float MaxHealth = 100.0f;

	UPROPERTY(ReplicatedUsing=OnRep_Health, BlueprintReadOnly, Category="AccelDemo|Combat")
	float Health = 100.0f;

	UPROPERTY(Replicated, BlueprintReadOnly, Category="AccelDemo|Combat")
	int32 DeathCount = 0;

	UPROPERTY(EditDefaultsOnly, Category="AccelDemo|Combat")
	float RespawnDelaySeconds = 3.0f;

	UFUNCTION()
	void OnRep_Health();
};