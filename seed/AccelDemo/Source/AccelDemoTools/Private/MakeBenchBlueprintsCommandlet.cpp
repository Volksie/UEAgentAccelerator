#include "MakeBenchBlueprintsCommandlet.h"

#include "ADCharacter.h"
#include "ADInteractable.h"
#include "ADStaminaComponent.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "EdGraph/EdGraph.h"
#include "EdGraphSchema_K2.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "GameFramework/Actor.h"
#include "K2Node_CallFunction.h"
#include "K2Node_VariableGet.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Misc/PackageName.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"

namespace
{
	const TCHAR* AssetRoot = TEXT("/Game/Bench");

	UBlueprint* MakeBlueprint(UClass* ParentClass, const FString& AssetName)
	{
		const FString PackageName = FString::Printf(TEXT("%s/%s"), AssetRoot, *AssetName);

		UPackage* Package = CreatePackage(*PackageName);
		if (!Package)
		{
			UE_LOG(LogTemp, Error, TEXT("MakeBenchBlueprints: could not create package %s"), *PackageName);
			return nullptr;
		}
		Package->FullyLoad();

		UBlueprint* BP = FKismetEditorUtilities::CreateBlueprint(
			ParentClass, Package, FName(*AssetName), BPTYPE_Normal,
			UBlueprint::StaticClass(), UBlueprintGeneratedClass::StaticClass());

		if (!BP)
		{
			UE_LOG(LogTemp, Error, TEXT("MakeBenchBlueprints: CreateBlueprint failed for %s"), *AssetName);
		}
		return BP;
	}

	// Drops a call node into the Blueprint's event graph. The node is what makes this Blueprint a
	// real caller of the C++ function: UK2Node_CallFunction holds an FMemberReference that resolves
	// back to the UFunction, which is the edge the Phase 4 tier 3 walk is meant to find.
	bool AddCallNode(UBlueprint* BP, UClass* OwnerClass, const FName FunctionName, int32 PosX, int32 PosY)
	{
		if (!BP || BP->UbergraphPages.Num() == 0)
		{
			return false;
		}

		UFunction* Function = OwnerClass ? OwnerClass->FindFunctionByName(FunctionName) : nullptr;
		if (!Function)
		{
			UE_LOG(LogTemp, Error, TEXT("MakeBenchBlueprints: no UFunction %s on %s"),
				*FunctionName.ToString(), OwnerClass ? *OwnerClass->GetName() : TEXT("null"));
			return false;
		}

		UEdGraph* Graph = BP->UbergraphPages[0];

		UK2Node_CallFunction* Node = NewObject<UK2Node_CallFunction>(Graph);
		Node->SetFromFunction(Function);
		Node->CreateNewGuid();
		Node->PostPlacedNewNode();
		Node->AllocateDefaultPins();
		Node->NodePosX = PosX;
		Node->NodePosY = PosY;
		Graph->AddNode(Node, false, false);

		return true;
	}

	// A read of a C++ property from a graph. Same class of edge as a call, and the same blind spot:
	// change MaxHealth's type and this node is what breaks, with nothing on the C++ side to warn you.
	bool AddPropertyReadNode(UBlueprint* BP, UClass* OwnerClass, const FName PropertyName, int32 PosX, int32 PosY)
	{
		if (!BP || BP->UbergraphPages.Num() == 0)
		{
			return false;
		}

		UEdGraph* Graph = BP->UbergraphPages[0];

		UK2Node_VariableGet* Node = NewObject<UK2Node_VariableGet>(Graph);
		Node->VariableReference.SetExternalMember(PropertyName, OwnerClass);
		Node->CreateNewGuid();
		Node->PostPlacedNewNode();
		Node->AllocateDefaultPins();
		Node->NodePosX = PosX;
		Node->NodePosY = PosY;
		Graph->AddNode(Node, false, false);
		return true;
	}

	bool AddReplicatedInt(UBlueprint* BP, const FName VarName)
	{
		FEdGraphPinType IntType;
		IntType.PinCategory = UEdGraphSchema_K2::PC_Int;

		if (!FBlueprintEditorUtils::AddMemberVariable(BP, VarName, IntType))
		{
			return false;
		}

		// There is no helper for the replication flag, so set it the way the editor's own
		// variable details panel does: straight onto the description's PropertyFlags.
		const int32 Index = FBlueprintEditorUtils::FindNewVariableIndex(BP, VarName);
		if (Index == INDEX_NONE)
		{
			return false;
		}
		BP->NewVariables[Index].PropertyFlags |= CPF_Net;
		return true;
	}

	bool SaveBlueprint(UBlueprint* BP)
	{
		if (!BP)
		{
			return false;
		}

		FKismetEditorUtilities::CompileBlueprint(BP);

		UPackage* Package = BP->GetOutermost();
		Package->MarkPackageDirty();
		FAssetRegistryModule::AssetCreated(BP);

		const FString Filename = FPackageName::LongPackageNameToFilename(
			Package->GetName(), FPackageName::GetAssetPackageExtension());

		FSavePackageArgs Args;
		Args.TopLevelFlags = RF_Public | RF_Standalone;
		Args.Error = GError;

		const bool bSaved = UPackage::SavePackage(Package, BP, *Filename, Args);
		UE_LOG(LogTemp, Display, TEXT("MakeBenchBlueprints: %s %s"),
			bSaved ? TEXT("wrote") : TEXT("FAILED to write"), *Filename);
		return bSaved;
	}
}

UMakeBenchBlueprintsCommandlet::UMakeBenchBlueprintsCommandlet()
{
	IsClient = false;
	IsServer = false;
	IsEditor = true;
	LogToConsole = true;
}

int32 UMakeBenchBlueprintsCommandlet::Main(const FString& Params)
{
	int32 Made = 0;

	// 1. A character Blueprint that calls ApplyDamage and adds its own replicated variable.
	//    This is the one that makes "what calls ApplyDamage" answerable only from the graph.
	if (UBlueprint* BP = MakeBlueprint(AADCharacter::StaticClass(), TEXT("BP_AccelDemoCharacter")))
	{
		AddCallNode(BP, AADCharacter::StaticClass(), TEXT("ApplyDamage"), 0, 0);
		AddCallNode(BP, AADCharacter::StaticClass(), TEXT("IsAlive"), 0, 200);
		AddPropertyReadNode(BP, AADCharacter::StaticClass(), TEXT("MaxHealth"), 0, 400);
		AddReplicatedInt(BP, TEXT("ComboCounter"));
		if (SaveBlueprint(BP)) { ++Made; }
	}

	// 2. A data only Blueprint. No graph logic, no variables, just a subclass. Tier 1 should see
	//    it and mark it IsDataOnly, and tier 3 should correctly find nothing in it.
	if (UBlueprint* BP = MakeBlueprint(AADCharacter::StaticClass(), TEXT("BP_TrainingDummy")))
	{
		if (SaveBlueprint(BP)) { ++Made; }
	}

	// 3. An actor implementing the C++ interface, calling into a component function in a different
	//    module. Cross module, cross language, and the interface is implemented in Blueprint rather
	//    than C++, which nothing on the C++ side can see.
	if (UBlueprint* BP = MakeBlueprint(AActor::StaticClass(), TEXT("BP_StaminaPickup")))
	{
		FBlueprintEditorUtils::ImplementNewInterface(BP, UADInteractable::StaticClass()->GetClassPathName());
		AddCallNode(BP, UADStaminaComponent::StaticClass(), TEXT("ApplyStamina"), 0, 0);
		if (SaveBlueprint(BP)) { ++Made; }
	}

	UE_LOG(LogTemp, Display, TEXT("MakeBenchBlueprints: done, %d Blueprints written to %s"), Made, AssetRoot);
	return Made == 3 ? 0 : 1;
}
