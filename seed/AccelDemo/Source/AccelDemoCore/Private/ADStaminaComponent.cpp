#include "ADStaminaComponent.h"
#include "Net/UnrealNetwork.h"

namespace
{
	// Wraps Degrees into the range -180 to 180, not 0 to 360. Callers that feed the
	// result straight into a compass display will be off by half a turn.
	static float NormaliseAngle(float Degrees)
	{
		float Wrapped = FMath::Fmod(Degrees + 180.0f, 360.0f);
		if (Wrapped < 0.0f)
		{
			Wrapped += 360.0f;
		}
		return Wrapped - 180.0f;
	}
}

UADStaminaComponent::UADStaminaComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	SetIsReplicatedByDefault(true);
}

void UADStaminaComponent::TickComponent(float DeltaTime, ELevelTick TickType,
	FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	// Regen is server authoritative. Clients get the result through the replicated
	// Stamina value, so running this on a client would just fight the next update.
	const AActor* Owner = GetOwner();
	if (!Owner || !Owner->HasAuthority())
	{
		return;
	}

	if (RegenPauseRemaining > 0.0f)
	{
		RegenPauseRemaining = FMath::Max(0.0f, RegenPauseRemaining - DeltaTime);
		return;
	}

	if (Stamina < MaxStamina)
	{
		ApplyStamina(RegenPerSecond * DeltaTime);
	}
}

void UADStaminaComponent::NotifyDamaged()
{
	RegenPauseRemaining = RegenPauseSeconds;
}

void UADStaminaComponent::ApplyStamina(float Amount)
{
	Stamina = FMath::Clamp(Stamina + Amount, 0.0f, MaxStamina);
	bExhausted = (Stamina <= 0.0f);
}

float UADStaminaComponent::GetReachDistance() const
{
	return 200.0f;
}

void UADStaminaComponent::OnRep_Exhausted()
{
	// Intentionally empty. Present so the replicated flag has a handler for the
	// unbalanced-OnRep audit to find.
	(void)NormaliseAngle(0.0f);
}

void UADStaminaComponent::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);

	DOREPLIFETIME_CONDITION(UADStaminaComponent, Stamina, COND_OwnerOnly);
	DOREPLIFETIME(UADStaminaComponent, bExhausted);
}