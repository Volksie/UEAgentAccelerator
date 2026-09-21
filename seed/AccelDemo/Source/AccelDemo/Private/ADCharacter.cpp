#include "ADCharacter.h"
#include "ADStaminaComponent.h"
#include "Net/UnrealNetwork.h"
#include "TimerManager.h"
#include "Engine/World.h"

AADCharacter::AADCharacter()
{
	PrimaryActorTick.bCanEverTick = false;
	bReplicates = true;

	Stamina = CreateDefaultSubobject<UADStaminaComponent>(TEXT("Stamina"));
}

void AADCharacter::BeginPlay()
{
	Super::BeginPlay();

	// HACK: we defer the first stamina top-up by one frame because on clients the
	// component has not finished replicating its default values at BeginPlay, so
	// topping up here writes into a pool that is about to be overwritten. Remove
	// this once UE-1234567 is fixed and initial replication is ordered before
	// BeginPlay on the owning client.
	if (UWorld* World = GetWorld())
	{
		FTimerHandle Handle;
		World->GetTimerManager().SetTimerForNextTick([this]()
		{
			if (Stamina)
			{
				Stamina->ApplyStamina(0.0f);
			}
		});
	}
}

void AADCharacter::ApplyDamage(float Amount)
{
	if (!HasAuthority())
	{
		return;
	}

	Health = FMath::Clamp(Health - Amount, 0.0f, MaxHealth);

	// Damage pauses stamina regen, see Docs/Design/StaminaSystem.md.
	if (Stamina)
	{
		Stamina->NotifyDamaged();
	}

	MulticastPlayHitReaction(Amount);

	if (Health <= 0.0f)
	{
		++DeathCount;
		ClientNotifyDeath();
	}
}

void AADCharacter::OnInteracted(AActor* Interactor)
{
	if (Stamina)
	{
		Stamina->ApplyStamina(-5.0f);
	}
}

FText AADCharacter::GetInteractionPrompt_Implementation() const
{
	return NSLOCTEXT("AccelDemo", "InteractPrompt", "Talk");
}

void AADCharacter::OnRep_Health()
{
}

void AADCharacter::ServerRequestRespawn_Implementation()
{
	Health = MaxHealth;
}

void AADCharacter::MulticastPlayHitReaction_Implementation(float Amount)
{
}

void AADCharacter::ClientNotifyDeath_Implementation()
{
}

void AADCharacter::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);

	DOREPLIFETIME_CONDITION(AADCharacter, Health, COND_OwnerOnly);
	DOREPLIFETIME_CONDITION(AADCharacter, DeathCount, COND_SkipOwner);
}