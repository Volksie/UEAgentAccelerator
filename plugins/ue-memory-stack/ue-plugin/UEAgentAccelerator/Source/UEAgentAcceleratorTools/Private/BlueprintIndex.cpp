#include "BlueprintIndex.h"
#include "AgentMemoryFile.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Interfaces/IPluginManager.h"
#include "Blueprint/BlueprintSupport.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "K2Node_CallFunction.h"
#include "K2Node_Variable.h"
#include "K2Node_DynamicCast.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/CommandLine.h"
#include "Misc/Paths.h"
#include "Animation/WidgetAnimation.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Widget.h"
#include "WidgetBlueprint.h"
#include "WidgetBlueprintEditorUtils.h"
#include "Misc/SecureHash.h"
#include "Engine/SimpleConstructionScript.h"
#include "Engine/SCS_Node.h"
#include "Engine/InheritableComponentHandler.h"
#include "Components/ActorComponent.h"
#include "InputMappingContext.h"
#include "InputAction.h"
#include "EnhancedActionKeyMapping.h"
#include "EdGraphSchema_K2.h"
#include "K2Node_Event.h"
#include "GameFramework/Actor.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_FunctionResult.h"
#include "K2Node_CustomEvent.h"
#include "Engine/TimelineTemplate.h"

namespace
{
	// One use of a C++ symbol from inside a Blueprint graph, or a by-name binding from a widget tree.
	// An edge whose TARGET is another Blueprint. Deliberately a separate type from FBPEdge, which
	// feeds bpcallers/ and means "C++ symbols used by Blueprints". Several benchmark answer keys
	// count rows in that directory, and adding macro graphs to the walk once moved one from 12
	// Blueprints and 30 nodes to 13 and 31 - so a new edge kind that leaked into it would silently
	// invalidate a key rather than fail.
	struct FBPOutEdge
	{
		FString TargetPath;   // package path of the Blueprint being called or cast to
		FString TargetStem;
		FString Member;       // function name, or empty for a cast
		FString Kind;         // call or cast
		FString GraphName;
		int32 Count = 1;

		bool operator<(const FBPOutEdge& O) const
		{
			if (TargetPath != O.TargetPath) { return TargetPath < O.TargetPath; }
			if (Kind != O.Kind)             { return Kind < O.Kind; }
			if (Member != O.Member)         { return Member < O.Member; }
			return GraphName < O.GraphName;
		}
	};

	struct FBPEdge
	{
		FString Symbol;      // Owner::Member, always the C++ side
		FString BlueprintPath;
		FString GraphName;
		FString Kind;        // call, read, write or bind
		int32 Count = 1;     // how many nodes in that graph, so two calls don't read as one

		bool operator<(const FBPEdge& O) const
		{
			if (Symbol != O.Symbol)               { return Symbol < O.Symbol; }
			if (BlueprintPath != O.BlueprintPath) { return BlueprintPath < O.BlueprintPath; }
			if (GraphName != O.GraphName)         { return GraphName < O.GraphName; }
			return Kind < O.Kind;
		}
	};

	// One changed default. The two owner kinds are kept apart on purpose: a value on the class
	// default object and a value on a component's template are different storage, reached by
	// different editor UI, and a query that cannot tell them apart cannot answer "what does this
	// CLASS default to" separately from "what does this COMPONENT default to". the seed project carries one
	// of each by construction - MaxHealth on the CDO, MaxStamina on a component template - so the
	// two paths have a positive control each rather than sharing one.
	struct FBPOverride
	{
		FString OwnerKind;     // class, component, inherited_component
		FString Owner;         // empty for the class, else the component's variable name
		FString OwnerClass;    // the component's class, empty for the class kind
		FString Property;
		FString Value;         // what this Blueprint sets
		FString InheritedValue;// what it would have been
		int32 TruncatedFrom = 0;  // original length when Value was capped, else 0
		int32 WindowAt = 0;       // offset the shown window starts at, 0 when it starts at the front
		bool bRedacted = false;

		bool operator<(const FBPOverride& O) const
		{
			if (OwnerKind != O.OwnerKind) { return OwnerKind < O.OwnerKind; }
			if (Owner != O.Owner)         { return Owner < O.Owner; }
			return Property < O.Property;
		}
	};

	// The per-Blueprint model. Built once, written twice: as JSON here, and as Markdown from the
	// same fields once the renderer lands. build_api_db.py re-parses the formatted Markdown today
	// to get its Blueprint edges, and its own docstring says why that is fragile - a layout change
	// breaks it quietly. Four more Markdown shapes to parse would make that worse, so the data
	// side gets its own file and the document side stops being an interface.
	struct FBPVariable
	{
		FString Name;
		FString Type;        // rendered by the editor's own schema, not reimplemented here
		FString Default;
		FString Category;
		FString Tooltip;
		TArray<FString> Flags;
		FString Replication; // the COND_ when replicated, else empty
		FString RepNotify;
	};

	struct FBPComponent
	{
		FString Name;
		FString Class;
		FString Kind = TEXT("component");   // component or widget
		FString AttachParent;
		FString AttachSocket;
		FString Source;      // empty when this Blueprint declares it, else where it comes from
		bool bInherited = false;
		bool bParentNative = false;

		bool operator<(const FBPComponent& O) const { return Name < O.Name; }
	};

	// Three separate questions that get confused with each other. A class that CAN tick but starts
	// with ticking off is not a performance problem; one that ticks every frame into an empty
	// handler is. Neither is visible from any other layer.
	struct FBPFunction
	{
		FString Name;
		FString Category;
		FString Tooltip;
		FString Access;
		bool bPure = false;
		bool bConst = false;
		TArray<FString> Inputs;
		TArray<FString> Outputs;

		bool operator<(const FBPFunction& O) const { return Name < O.Name; }
	};

	struct FBPEventNode
	{
		FString Name;
		FString Kind;        // override or custom
		TArray<FString> Inputs;
		TArray<FString> NetFlags;
		bool bWired = false;

		bool operator<(const FBPEventNode& O) const
		{
			if (Name != O.Name) { return Name < O.Name; }
			return Kind < O.Kind;
		}
	};

	struct FBPDispatcher
	{
		FString Name;
		TArray<FString> Inputs;
		bool operator<(const FBPDispatcher& O) const { return Name < O.Name; }
	};

	struct FBPTimeline
	{
		FString Name;
		FString Length;
		bool operator<(const FBPTimeline& O) const { return Name < O.Name; }
	};

	struct FBPInterfaceImpl
	{
		FString Name;
		TArray<FString> Functions;
		bool operator<(const FBPInterfaceImpl& O) const { return Name < O.Name; }
	};

	struct FBPTick
	{
		bool bCanEverTick = false;
		bool bStartWithTickEnabled = false;
		bool bEventTickWired = false;
		bool bTickNodeDisabled = false;   // a linked Event Tick that is switched off
		bool bKnown = false;   // false for a Blueprint whose default object is not an Actor
	};

	struct FBPRecord
	{
		FString Path;            // package path, /Game/Characters/BP_Hero
		FString Stem;            // the file-name form of the same, Game.Characters.BP_Hero
		FString Name;
		FString Parent;          // immediate, native or Blueprint
		FString NativeParent;    // ultimate native ancestor
		TArray<FString> Interfaces;
		int32 ReplicatedProps = 0;
		int32 DataOnly = -1;     // 1 yes, 0 no, -1 the registry did not say
		int32 NativeComponents = 0;
		int32 BlueprintComponents = 0;
		TArray<FBPOverride> Overrides;
		TArray<FBPVariable> Variables;
		TArray<FBPComponent> Components;
		FString RootComponent;
		FBPTick Tick;
		TArray<FBPFunction> Functions;
		TArray<FBPEventNode> Events;
		TArray<FBPDispatcher> Dispatchers;
		TArray<FBPTimeline> Timelines;
		TArray<FBPInterfaceImpl> InterfaceImpls;
		TArray<FBPOutEdge> CallsOut;
		TArray<FString> HardDependencies;
		TArray<FString> SoftDependencies;
	};

	// A designer-settable, non-transient property. If a designer cannot set it, it is not a tuning
	// value, and the diff fills with engine bookkeeping that changes for reasons nobody authored.
	bool IsTunableProperty(const FProperty* Prop)
	{
		if (!Prop) { return false; }
		if (!Prop->HasAnyPropertyFlags(CPF_Edit)) { return false; }
		if (Prop->HasAnyPropertyFlags(CPF_Transient | CPF_DuplicateTransient | CPF_EditorOnly)) { return false; }
		return true;
	}

	// Name-matched redaction. These files are committed, and this plugin runs in projects we do not
	// see, so a string variable holding a key would go into someone's git history in plain text.
	// It is a NAME match, so it misses a secret that is not named like one, and it fires on innocent
	// names that merely contain one of the words. The doc says so; so does this comment, because the
	// first person to find a redacted value here will want to know which of the two happened.
	bool IsSecretName(const FString& Name)
	{
		static const TCHAR* Needles[] = { TEXT("key"), TEXT("secret"), TEXT("token"), TEXT("password"), TEXT("credential") };
		for (const TCHAR* Needle : Needles)
		{
			if (Name.Contains(Needle, ESearchCase::IgnoreCase)) { return true; }
		}
		return false;
	}

	// A secret is text somebody typed. The name match on its own fired 9 times on a sample game and was
	// wrong 9 times: InputBrushKeySets, KeyboardStyle, FallbackBindingKey, PressAnyKeyPanelClass
	// and friends - input bindings, every one, and every one a tuning value a reader would want.
	// Requiring the value to BE text costs no protection, because a credential is not stored in an
	// FKey or a TSubclassOf, and it removed all nine. Containers of text count; struct members do
	// NOT, deliberately - FKey holds an FName, so recursing into structs brings the false
	// positives straight back.
	bool HoldsTextValue(const FProperty* Prop)
	{
		auto IsText = [](const FProperty* P)
		{
			return P && (P->IsA<FStrProperty>() || P->IsA<FTextProperty>() || P->IsA<FNameProperty>());
		};

		if (IsText(Prop)) { return true; }
		if (const FArrayProperty* Arr = CastField<FArrayProperty>(Prop)) { return IsText(Arr->Inner); }
		if (const FSetProperty* Set = CastField<FSetProperty>(Prop))     { return IsText(Set->ElementProp); }
		if (const FMapProperty* Map = CastField<FMapProperty>(Prop))     { return IsText(Map->KeyProp) || IsText(Map->ValueProp); }
		return false;
	}

	// An instanced subobject exports as an object path that carries a transient name, so it differs
	// between two runs of the same dump over the same asset. The class is the part a reader wants
	// anyway, and it is stable.
	FString ExportPropertyValue(const FProperty* Prop, const void* Container, int32 Index)
	{
		if (const FObjectProperty* ObjProp = CastField<FObjectProperty>(Prop))
		{
			const UObject* Value = ObjProp->GetObjectPropertyValue(
				ObjProp->ContainerPtrToValuePtr<void>(Container, Index));
			if (Value && Value->IsDefaultSubobject())
			{
				return FString::Printf(TEXT("<%s instance>"), *Value->GetClass()->GetName());
			}
		}
		FString Out;
		// ExportText_InContainer is the wrong call here, and the way it is wrong is silent.
		// ExportText_Direct GATES on Identical(Data, Delta) and writes NOTHING when they match,
		// and a null Delta means "compare against the type's zero" rather than "no delta". So a
		// false bool, a zero float and a null object each exported as an empty string: 676 of
		// 1420 rows on a sample game had a blank side, which reads as "no value" and is indistinguishable
		// from False, 0 and None. ExportTextItem_Direct carries no gate and always writes.
		Prop->ExportTextItem_Direct(Out, Prop->ContainerPtrToValuePtr<void>(Container, Index),
			nullptr, nullptr, PPF_None);

		// An empty container and an empty string both export as nothing, and a blank cell in a
		// committed file reads as "we did not look". Now that the export is unconditional, empty
		// means the value's text form really is empty, and saying so is one token.
		return Out.IsEmpty() ? FString(TEXT("<empty>")) : Out;
	}

	// Arrays and structs run to pages. 200 characters is enough to recognise a value; the real
	// length is kept so a reader can tell "this is the value" from "this is the start of it".
	void CapValue(FString& Value, int32& OutTruncatedFrom)
	{
		const int32 Cap = 200;
		if (Value.Len() > Cap)
		{
			OutTruncatedFrom = Value.Len();
			Value = Value.Left(Cap);
		}
	}

	// Two values that differ somewhere past the cap both truncate to the same text, so the row
	// renders as "no change" while carrying a real one. 37 rows on a sample game did exactly that -
	// BodyInstance at 1,240 characters, Executions at 381 - and the reader's only clue was a
	// truncated_from field. Find where they actually diverge and show a window there instead.
	void CapPairAtDifference(FString& Value, FString& Inherited,
		int32& OutTruncatedFrom, int32& OutWindowAt)
	{
		const int32 Cap = 200;
		const int32 Lead = 40;   // a little context before the divergence, so it reads in situ

		if (Value.Len() <= Cap && Inherited.Len() <= Cap) { return; }

		int32 Diff = 0;
		const int32 Shortest = FMath::Min(Value.Len(), Inherited.Len());
		while (Diff < Shortest && Value[Diff] == Inherited[Diff]) { ++Diff; }

		// Within the cap, the ordinary front-truncation already shows the difference.
		const int32 Start = (Diff >= Cap) ? FMath::Max(0, Diff - Lead) : 0;
		OutWindowAt = Start;

		auto Window = [Cap, Start](FString& Text, int32& OutFrom)
		{
			if (Text.Len() <= Cap && Start == 0) { return; }
			OutFrom = Text.Len();
			Text = (Start < Text.Len()) ? Text.Mid(Start, Cap) : FString(TEXT("<shorter than the window>"));
		};

		int32 InheritedFrom = 0;
		Window(Value, OutTruncatedFrom);
		Window(Inherited, InheritedFrom);
	}

	// Compare one object against the defaults it came from, and record every designer-settable
	// property that differs. Used three times: the generated class against its parent, a component
	// template against its class default, and an inherited component's override against the
	// template it overrides.
	void CollectOverrides(const UStruct* PropertySource, const void* Object, const void* Defaults,
		const FString& OwnerKind, const FString& Owner, const FString& OwnerClass,
		TArray<FBPOverride>& Out, int32& OutRedactedNonString, bool bDescendIntoSubobjects = false)
	{
		if (!PropertySource || !Object || !Defaults) { return; }

		for (TFieldIterator<FProperty> It(PropertySource); It; ++It)
		{
			const FProperty* Prop = *It;
			if (!IsTunableProperty(Prop)) { continue; }

			// A component built in a C++ constructor lives here and nowhere else. The two CDOs
			// hold two different instances of it, so the pointers always differ and the class
			// name always matches - which is why this has to be a descent rather than a row.
			// One level only: the actor's own components, which is what the question asks about.
			if (bDescendIntoSubobjects)
			{
				if (const FObjectProperty* ObjProp = CastField<FObjectProperty>(Prop))
				{
					const UObject* Mine = ObjProp->GetObjectPropertyValue(ObjProp->ContainerPtrToValuePtr<void>(Object, 0));
					const UObject* Theirs = ObjProp->GetObjectPropertyValue(ObjProp->ContainerPtrToValuePtr<void>(Defaults, 0));
					if (Mine && Theirs && Mine->IsDefaultSubobject() && Theirs->IsDefaultSubobject())
					{
						// A Blueprint can REPLACE a native component's class, and requiring the two
						// classes to match here meant such a component was never diffed at all: one
						// row saying the class changed, and not one of its values. A character that
						// swaps its movement component and retunes the speeds on it then answers
						// "what is its walk speed" from the PARENT - confidently, and wrong.
						//
						// The property source has to be a class BOTH objects are. Iterating the new
						// class's properties over the parent template's memory reads past the end of
						// that object; the nearest shared ancestor is both safe and the honest
						// comparison, being the properties the two classes have in common.
						const UClass* Shared = Mine->GetClass();
						while (Shared && !Theirs->IsA(Shared)) { Shared = Shared->GetSuperClass(); }

						if (Shared)
						{
							// Compared against the PARENT'S template, not the new class's CDO. A
							// replaced subobject's archetype is its own class default, so everything
							// the parent's constructor already set is serialised into the asset and
							// reads as a change. Against the parent's template, only what the
							// designer actually retuned survives.
							CollectOverrides(Shared, Mine, Theirs,
								TEXT("native_component"), Prop->GetName(), Mine->GetClass()->GetName(),
								Out, OutRedactedNonString, false);

							// Same class: the two pointers always differ, so falling through would
							// invent a row that cannot show a difference. Different class: the swap
							// IS the change, and its row is the only one naming the new class.
							if (Mine->GetClass() == Theirs->GetClass()) { continue; }
						}
					}
				}
			}

			for (int32 Index = 0; Index < Prop->ArrayDim; ++Index)
			{
				if (Prop->Identical_InContainer(Object, Defaults, Index)) { continue; }

				FBPOverride Rec;
				Rec.OwnerKind = OwnerKind;
				Rec.Owner = Owner;
				Rec.OwnerClass = OwnerClass;
				Rec.Property = Prop->ArrayDim > 1
					? FString::Printf(TEXT("%s[%d]"), *Prop->GetName(), Index)
					: Prop->GetName();

				Rec.Value = ExportPropertyValue(Prop, Object, Index);
				Rec.InheritedValue = ExportPropertyValue(Prop, Defaults, Index);

				// Identical_InContainer compares an object property by POINTER, and every class
				// gets its own default subobject, so each native component read as an override on
				// a Blueprint that had not touched it: four of six rows on the seed project's character,
				// each printing the same value on both sides. A row whose two sides are equal
				// cannot show a difference, so it must not claim one. Compared BEFORE capping,
				// because two different long values can share their first 200 characters.
				if (Rec.Value.Equals(Rec.InheritedValue, ESearchCase::CaseSensitive))
				{
					continue;
				}

				if (IsSecretName(Prop->GetName()) && !HoldsTextValue(Prop))
				{
					// The name matched but the value cannot be text. Counted rather than silently
					// dropped: if this number ever climbs, the word list is picking up a family of
					// properties nobody meant it to, and a count is the only way to notice.
					//
					// KNOWN GAP, and this counter is where you will be standing when you need it:
					// not recursing into structs means a PROJECT struct with a string member named
					// ApiKey is not redacted. The fix is to recurse but match the name of the LEAF
					// member, with a short exclusion list of engine structs whose values come from
					// a closed set (FKey, FInputChord). That keeps the nine false positives at zero
					// by type rather than by luck. Deliberately not built until someone needs it.
					++OutRedactedNonString;
				}
				else if (IsSecretName(Prop->GetName()))
				{
					Rec.bRedacted = true;
					Rec.Value = FString::Printf(TEXT("<redacted, %d characters>"), Rec.Value.Len());
					Rec.InheritedValue = FString::Printf(TEXT("<redacted, %d characters>"), Rec.InheritedValue.Len());
				}
				else
				{
					CapPairAtDifference(Rec.Value, Rec.InheritedValue, Rec.TruncatedFrom, Rec.WindowAt);
				}

				Out.Add(MoveTemp(Rec));
			}
		}
	}

	FString JsonEscape(const FString& In)
	{
		FString Out;
		Out.Reserve(In.Len() + 8);
		for (const TCHAR C : In)
		{
			switch (C)
			{
			case TEXT('"'):  Out += TEXT("\\\""); break;
			case TEXT('\\'): Out += TEXT("\\\\"); break;
			case TEXT('\n'): Out += TEXT("\\n");  break;
			case TEXT('\r'): Out += TEXT("\\r");  break;
			case TEXT('\t'): Out += TEXT("\\t");  break;
			default:
				// Control characters have no literal form in JSON. Everything else, including
				// non-ASCII, goes through as UTF-8 rather than \u escapes: the file is committed
				// and a human reads the diff.
				if (C < 0x20) { Out += FString::Printf(TEXT("\\u%04x"), (int32)C); }
				else          { Out.AppendChar(C); }
				break;
			}
		}
		return Out;
	}

	FString JsonStr(const FString& In)
	{
		return FString::Printf(TEXT("\"%s\""), *JsonEscape(In));
	}

	FString JsonStrArray(const TArray<FString>& In)
	{
		TArray<FString> Parts;
		Parts.Reserve(In.Num());
		for (const FString& S : In) { Parts.Add(JsonStr(S)); }
		return FString::Printf(TEXT("[%s]"), *FString::Join(Parts, TEXT(",")));
	}

	// Blueprint names are not unique across mount points: A sample game has Phase_Playing, Phase_PostGame
	// and Phase_Warmup under more than one plugin each, so the asset name alone cannot name a file.
	// The package path can, with the slashes turned into dots.
	FString StemForPackage(const FString& PackagePath)
	{
		FString Stem = PackagePath;
		Stem.RemoveFromStart(TEXT("/"));
		Stem.ReplaceInline(TEXT("/"), TEXT("."));

		// Windows still enforces 260 characters in places, and this sits under a project path we
		// do not control. Keeping the tail keeps the asset name, which is the readable part; the
		// hash of the WHOLE path keeps it unique, which the tail on its own would not.
		const int32 MaxStem = 120;
		if (Stem.Len() > MaxStem)
		{
			const FString Digest = FMD5::HashAnsiString(*PackagePath).Left(8);
			const FString Tail = Stem.Right(100);
			UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: stem for %s is %d chars, shortening to %s-%s"),
				*PackagePath, Stem.Len(), *Digest, *Tail);
			Stem = Digest + TEXT("-") + Tail;
		}
		return Stem;
	}

	FString MetaValue(const FBPVariableDescription& Var, const FName Key)
	{
		for (const FBPVariableMetaDataEntry& Entry : Var.MetaDataArray)
		{
			if (Entry.DataKey == Key) { return Entry.DataValue; }
		}
		return FString();
	}

	void CollectVariables(const UBlueprint* BP, UClass* GenClass, TArray<FBPVariable>& Out)
	{
		if (!BP) { return; }
		const UObject* CDO = GenClass ? GenClass->GetDefaultObject() : nullptr;

		for (const FBPVariableDescription& Var : BP->NewVariables)
		{
			FBPVariable V;
			V.Name = Var.VarName.ToString();

			// The editor's own renderer, rather than a second implementation of it that would
			// drift. This is the string a designer sees next to the variable.
			V.Type = UEdGraphSchema_K2::TypeToText(Var.VarType).ToString();

			// Var.DefaultValue is blank whenever the default is the type's zero, which is the same
			// ambiguity step 3 spent a rebuild removing. The generated class's CDO holds the real
			// value, so read it through the exporter that already handles zero, empty and
			// instanced subobjects.
			V.Default = TEXT("<unresolved>");
			if (CDO)
			{
				if (const FProperty* Prop = GenClass->FindPropertyByName(Var.VarName))
				{
					V.Default = ExportPropertyValue(Prop, CDO, 0);
				}
			}

			V.Category = Var.Category.ToString();
			V.Tooltip = MetaValue(Var, TEXT("tooltip"));

			if (Var.PropertyFlags & CPF_Edit)
			{
				V.Flags.Add((Var.PropertyFlags & CPF_DisableEditOnInstance) ? TEXT("editable on default only") : TEXT("instance editable"));
			}
			if (Var.PropertyFlags & CPF_ExposeOnSpawn)      { V.Flags.Add(TEXT("expose on spawn")); }
			if (Var.PropertyFlags & CPF_BlueprintReadOnly)  { V.Flags.Add(TEXT("blueprint read only")); }
			if (Var.PropertyFlags & CPF_Transient)          { V.Flags.Add(TEXT("transient")); }
			if (Var.PropertyFlags & CPF_SaveGame)           { V.Flags.Add(TEXT("save game")); }
			if (!MetaValue(Var, TEXT("BlueprintPrivate")).IsEmpty()) { V.Flags.Add(TEXT("private")); }

			if (Var.PropertyFlags & CPF_Net)
			{
				V.Flags.Add(TEXT("replicated"));
				if (const UEnum* Cond = StaticEnum<ELifetimeCondition>())
				{
					V.Replication = Cond->GetNameStringByValue((int64)Var.ReplicationCondition);
				}
				V.RepNotify = Var.RepNotifyFunc.IsNone() ? FString() : Var.RepNotifyFunc.ToString();
			}

			Out.Add(MoveTemp(V));
		}
	}

	void AddWidgetTree(const UWidgetBlueprint* WBP, bool bInherited, const FString& Source,
		TArray<FBPComponent>& Out)
	{
		if (!WBP || !WBP->WidgetTree) { return; }
		TArray<UWidget*> Widgets;
		WBP->WidgetTree->GetAllWidgets(Widgets);
		for (const UWidget* W : Widgets)
		{
			if (!W) { continue; }
			const FString Name = W->GetFName().ToString();
			// A declared widget wins over the inherited one of the same name, and the declared
			// pass runs first.
			if (Out.ContainsByPredicate([&Name](const FBPComponent& E) { return E.Name == Name; })) { continue; }

			FBPComponent C;
			C.Kind = TEXT("widget");
			C.Name = Name;
			C.Class = W->GetClass()->GetName();
			C.AttachParent = W->GetParent() ? W->GetParent()->GetFName().ToString() : FString();
			C.bInherited = bInherited;
			C.Source = Source;
			Out.Add(MoveTemp(C));
		}
	}

	void AddSCSNodes(const USimpleConstructionScript* SCS, bool bInherited, const FString& Source,
		TArray<FBPComponent>& Out)
	{
		if (!SCS) { return; }
		for (const USCS_Node* Node : SCS->GetAllNodes())
		{
			if (!Node) { continue; }
			FBPComponent C;
			C.Name = Node->GetVariableName().ToString();
			C.Class = Node->ComponentClass ? Node->ComponentClass->GetName() : FString(TEXT("unknown"));
			C.AttachParent = Node->ParentComponentOrVariableName.IsNone() ? FString() : Node->ParentComponentOrVariableName.ToString();
			C.AttachSocket = Node->AttachToName.IsNone() ? FString() : Node->AttachToName.ToString();
			C.bParentNative = Node->bIsParentComponentNative;
			C.bInherited = bInherited;
			C.Source = Source;
			Out.Add(MoveTemp(C));
		}
	}

	// "Does this pawn have a camera" does not care who declared it. A component reached through two
	// Blueprints and a C++ constructor is still a component this Blueprint has, so inherited ones
	// are listed with where they came from rather than left out.
	void CollectComponents(const UBlueprint* BP, UClass* ParentClass, UClass* GenClass, TArray<FBPComponent>& Out, FString& OutRoot)
	{
		if (!BP) { return; }
		AddSCSNodes(BP->SimpleConstructionScript, false, FString(), Out);

		for (UClass* Class = ParentClass; Class; Class = Class->GetSuperClass())
		{
			if (const UBlueprintGeneratedClass* BPGC = Cast<UBlueprintGeneratedClass>(Class))
			{
				AddSCSNodes(BPGC->SimpleConstructionScript, true, Class->GetName(), Out);
			}
		}

		// Components made in a C++ constructor appear in no construction script at all - the same
		// blind spot step 3's fourth owner kind was about, arriving from the other side.
		if (GenClass)
		{
			if (const UObject* CDO = GenClass->GetDefaultObject())
			{
				// The root first, so the property that names it wins the dedupe over
				// AActor::RootComponent regardless of field order.
				TSet<const UObject*> Seen;
				if (const AActor* ActorCDO = Cast<AActor>(CDO))
				{
					if (const UActorComponent* Root = ActorCDO->GetRootComponent())
					{
						OutRoot = Root->GetFName().ToString();
					}
				}

				// An Actor whose root comes from the construction script has no root on its CDO -
				// the root is attached when the script runs - so BP_StaminaPickup reported an empty
				// root while plainly having a DefaultSceneRoot. The construction script knows.
				if (OutRoot.IsEmpty() && BP->SimpleConstructionScript)
				{
					const TArray<USCS_Node*>& Roots = BP->SimpleConstructionScript->GetRootNodes();
					if (Roots.Num() > 0 && Roots[0])
					{
						OutRoot = Roots[0]->GetVariableName().ToString();
					}
				}

				for (TFieldIterator<FObjectProperty> It(GenClass); It; ++It)
				{
					const FObjectProperty* Prop = *It;
					if (!Prop->PropertyClass || !Prop->PropertyClass->IsChildOf(UActorComponent::StaticClass())) { continue; }
					const UObject* Value = Prop->GetObjectPropertyValue(Prop->ContainerPtrToValuePtr<void>(CDO, 0));
					if (!Value || !Value->IsDefaultSubobject()) { continue; }

					// AActor::RootComponent points at a component another property already
					// names - on a Character, the same object as CapsuleComponent - so taking one
					// entry per POINTER counted seven components where there are six. Dedupe on
					// the object, not the property name. The root is a role, and it is reported
					// as one below rather than as a component in its own right.
					if (Seen.Contains(Value)) { continue; }
					Seen.Add(Value);

					FBPComponent C;
					C.Name = Prop->GetName();
					C.Class = Value->GetClass()->GetName();
					C.bInherited = true;
					C.bParentNative = true;
					C.Source = Prop->GetOwnerClass() ? Prop->GetOwnerClass()->GetName() : FString();
					Out.Add(MoveTemp(C));
				}
			}
		}
		// A Widget Blueprint has no SimpleConstructionScript at all: its children live in the
		// WidgetTree, and every one of them was missing. Caught by a pre-registered check that
		// cross-referenced bpcallers/ - which already listed four bind edges into
		// one widget Blueprint's widget tree while this walk reported zero components for it. Two
		// walks disagreeing is the only reason this was visible.
		if (const UWidgetBlueprint* WBP = Cast<UWidgetBlueprint>(BP))
		{
			AddWidgetTree(WBP, false, FString(), Out);

			// A Widget Blueprint's WidgetTree holds only what IT declares. a derived widget Blueprint
			// declares nothing and inherits four widgets from its parent widget Blueprint, and
			// reported zero - the same declared-versus-inherited split already handled for
			// construction-script components, missed on the widget side because the first fix only
			// had to satisfy one widget Blueprint, which declares its own.
			for (UClass* Class = ParentClass; Class; Class = Class->GetSuperClass())
			{
				if (const UWidgetBlueprint* ParentWBP = Cast<UWidgetBlueprint>(Class->ClassGeneratedBy))
				{
					AddWidgetTree(ParentWBP, true, Class->GetName(), Out);
				}
			}
		}

		Out.Sort();
	}

	// "Name : Type", with the editor's own type rendering, because a signature without types tells
	// a caller nothing about whether their call will compile.
	FString PinToText(const UEdGraphPin* Pin)
	{
		return FString::Printf(TEXT("%s : %s"),
			*Pin->PinName.ToString(), *UEdGraphSchema_K2::TypeToText(Pin->PinType).ToString());
	}

	bool IsSignaturePin(const UEdGraphPin* Pin, EEdGraphPinDirection Direction)
	{
		return Pin
			&& Pin->Direction == Direction
			&& Pin->PinType.PinCategory != UEdGraphSchema_K2::PC_Exec
			&& Pin->PinType.PinCategory != UEdGraphSchema_K2::PC_Delegate
			&& Pin->PinName != UEdGraphSchema_K2::PN_Self;
	}

	void CollectFunctions(const UBlueprint* BP, TArray<FBPFunction>& Out)
	{
		if (!BP) { return; }
		for (const UEdGraph* Graph : BP->FunctionGraphs)
		{
			if (!Graph) { continue; }

			FBPFunction Fn;
			Fn.Name = Graph->GetName();

			for (const UEdGraphNode* Node : Graph->Nodes)
			{
				if (const UK2Node_FunctionEntry* Entry = Cast<UK2Node_FunctionEntry>(Node))
				{
					const int32 Flags = Entry->GetFunctionFlags();
					Fn.bPure = (Flags & FUNC_BlueprintPure) != 0;
					Fn.bConst = (Flags & FUNC_Const) != 0;
					Fn.Access = (Flags & FUNC_Private) ? TEXT("private")
						: ((Flags & FUNC_Protected) ? TEXT("protected") : TEXT("public"));
					Fn.Category = Entry->MetaData.Category.ToString();
					Fn.Tooltip = Entry->MetaData.ToolTip.ToString();

					for (const UEdGraphPin* Pin : Entry->Pins)
					{
						if (IsSignaturePin(Pin, EGPD_Output)) { Fn.Inputs.Add(PinToText(Pin)); }
					}
				}
				else if (const UK2Node_FunctionResult* Result = Cast<UK2Node_FunctionResult>(Node))
				{
					for (const UEdGraphPin* Pin : Result->Pins)
					{
						if (IsSignaturePin(Pin, EGPD_Input)) { Fn.Outputs.AddUnique(PinToText(Pin)); }
					}
				}
			}
			Out.Add(MoveTemp(Fn));
		}
		Out.Sort();
	}

	void CollectEvents(const UBlueprint* BP, TArray<FBPEventNode>& Out)
	{
		if (!BP) { return; }
		for (const UEdGraph* Graph : BP->UbergraphPages)
		{
			if (!Graph) { continue; }
			for (const UEdGraphNode* Node : Graph->Nodes)
			{
				const UK2Node_Event* Event = Cast<UK2Node_Event>(Node);
				if (!Event) { continue; }

				FBPEventNode E;
				if (Event->bOverrideFunction)
				{
					E.Kind = TEXT("override");
					E.Name = Event->EventReference.GetMemberName().ToString();
				}
				else
				{
					E.Kind = TEXT("custom");
					E.Name = Event->CustomFunctionName.ToString();
				}

				// The net flags are the whole reason a custom event is interesting to someone
				// changing replication, and they live nowhere else a text tool can reach.
				const uint32 Flags = Event->FunctionFlags;
				if (Flags & FUNC_NetMulticast) { E.NetFlags.Add(TEXT("multicast")); }
				if (Flags & FUNC_NetServer)    { E.NetFlags.Add(TEXT("server")); }
				if (Flags & FUNC_NetClient)    { E.NetFlags.Add(TEXT("client")); }
				if (Flags & FUNC_NetReliable)  { E.NetFlags.Add(TEXT("reliable")); }
				else if (Flags & FUNC_Net)     { E.NetFlags.Add(TEXT("unreliable")); }

				for (const UEdGraphPin* Pin : Event->Pins)
				{
					if (IsSignaturePin(Pin, EGPD_Output)) { E.Inputs.Add(PinToText(Pin)); }
					// Same rule as the tick section: a disabled node is linked and never compiled.
					if (Pin && Pin->Direction == EGPD_Output
						&& Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Exec
						&& Pin->LinkedTo.Num() > 0
						&& Event->IsNodeEnabled())
					{
						E.bWired = true;
					}
				}
				Out.Add(MoveTemp(E));
			}
		}
		Out.Sort();
	}

	void CollectDispatchers(const UBlueprint* BP, TArray<FBPDispatcher>& Out)
	{
		if (!BP) { return; }
		for (const UEdGraph* Graph : BP->DelegateSignatureGraphs)
		{
			if (!Graph) { continue; }
			FBPDispatcher D;
			D.Name = Graph->GetName();
			for (const UEdGraphNode* Node : Graph->Nodes)
			{
				if (const UK2Node_FunctionEntry* Entry = Cast<UK2Node_FunctionEntry>(Node))
				{
					for (const UEdGraphPin* Pin : Entry->Pins)
					{
						if (IsSignaturePin(Pin, EGPD_Output)) { D.Inputs.Add(PinToText(Pin)); }
					}
				}
			}
			Out.Add(MoveTemp(D));
		}
		Out.Sort();
	}

	void CollectTimelines(const UBlueprint* BP, TArray<FBPTimeline>& Out)
	{
		if (!BP) { return; }
		for (const UTimelineTemplate* Timeline : BP->Timelines)
		{
			if (!Timeline) { continue; }
			FBPTimeline T;
			T.Name = Timeline->GetVariableName().ToString();
			// One formatter for every float in this file, so 5.0 does not become 5.000000 on one
			// machine and 5 on another.
			T.Length = FString::Printf(TEXT("%f"), Timeline->TimelineLength);
			Out.Add(MoveTemp(T));
		}
		Out.Sort();
	}

	void CollectInterfaces(const UBlueprint* BP, TArray<FBPInterfaceImpl>& Out)
	{
		if (!BP) { return; }
		for (const FBPInterfaceDescription& Desc : BP->ImplementedInterfaces)
		{
			if (!Desc.Interface) { continue; }
			FBPInterfaceImpl Impl;
			Impl.Name = Desc.Interface->GetName();
			for (const UEdGraph* Graph : Desc.Graphs)
			{
				if (Graph) { Impl.Functions.Add(Graph->GetName()); }
			}
			Impl.Functions.Sort();
			Out.Add(MoveTemp(Impl));
		}

		Out.Sort();
	}

	FBPTick CollectTick(const UBlueprint* BP, UClass* GenClass)
	{
		FBPTick T;
		if (!GenClass) { return T; }

		if (const AActor* CDO = Cast<AActor>(GenClass->GetDefaultObject()))
		{
			T.bKnown = true;
			T.bCanEverTick = CDO->PrimaryActorTick.bCanEverTick;
			T.bStartWithTickEnabled = CDO->PrimaryActorTick.bStartWithTickEnabled;
		}

		// Wired means the exec pin actually goes somewhere. A ReceiveTick node sitting unconnected
		// in a graph is the thing people think they deleted.
		if (BP)
		{
			for (const UEdGraph* Graph : BP->UbergraphPages)
			{
				if (!Graph) { continue; }
				for (const UEdGraphNode* Node : Graph->Nodes)
				{
					const UK2Node_Event* Event = Cast<UK2Node_Event>(Node);
					if (!Event || Event->EventReference.GetMemberName() != TEXT("ReceiveTick")) { continue; }
					// A DISABLED node is linked and never compiled, so a link alone does not mean the
					// tick does anything. Eleven of a sample game's twenty linked ReceiveTick nodes are
					// disabled, and reporting those as wired produced seven Blueprints that claimed
					// a live tick on a class the Kismet compiler says cannot tick - the compiler
					// sets bCanEverTick from a non-empty ReceiveTick, so the two could never
					// disagree unless this was wrong. It was.
					const bool bEnabled = Event->IsNodeEnabled();
					for (const UEdGraphPin* Pin : Event->Pins)
					{
						if (Pin && Pin->Direction == EGPD_Output
							&& Pin->PinType.PinCategory == UEdGraphSchema_K2::PC_Exec
							&& Pin->LinkedTo.Num() > 0)
						{
							if (bEnabled) { T.bEventTickWired = true; }
							else          { T.bTickNodeDisabled = true; }
						}
					}
				}
			}
		}
		return T;
	}

	// One line of blueprints.jsonl. Key order is fixed here rather than left to a map, because the
	// file is committed and two dumps of an unchanged project have to be byte-identical; an
	// FJsonObject would serialise in TMap order and give a different file on a different machine.
	//
	// `sections` is the part to read before trusting an absence. It names the sections this build
	// actually populates, so a consumer can tell "this Blueprint has no variables" from "this
	// build does not yet report variables". Same rule bpcallers/ follows: an absence is only
	// evidence if the file says what was looked for.
	FString RecordToJsonLine(const FBPRecord& R)
	{
		TArray<FString> F;
		F.Add(FString::Printf(TEXT("\"path\":%s"), *JsonStr(R.Path)));
		F.Add(FString::Printf(TEXT("\"stem\":%s"), *JsonStr(R.Stem)));
		F.Add(FString::Printf(TEXT("\"name\":%s"), *JsonStr(R.Name)));
		F.Add(FString::Printf(TEXT("\"parent\":%s"), *JsonStr(R.Parent)));
		F.Add(FString::Printf(TEXT("\"native_parent\":%s"), *JsonStr(R.NativeParent)));
		F.Add(FString::Printf(TEXT("\"interfaces\":%s"), *JsonStrArray(R.Interfaces)));
		F.Add(FString::Printf(TEXT("\"replicated_props\":%d"), R.ReplicatedProps));
		F.Add(FString::Printf(TEXT("\"data_only\":%s"),
			R.DataOnly < 0 ? TEXT("null") : (R.DataOnly > 0 ? TEXT("true") : TEXT("false"))));
		F.Add(FString::Printf(TEXT("\"native_components\":%d"), R.NativeComponents));
		F.Add(FString::Printf(TEXT("\"blueprint_components\":%d"), R.BlueprintComponents));
		{
			TArray<FString> Ovr;
			Ovr.Reserve(R.Overrides.Num());
			for (const FBPOverride& O : R.Overrides)
			{
				TArray<FString> G;
				G.Add(FString::Printf(TEXT("\"owner_kind\":%s"), *JsonStr(O.OwnerKind)));
				G.Add(FString::Printf(TEXT("\"owner\":%s"), *JsonStr(O.Owner)));
				G.Add(FString::Printf(TEXT("\"owner_class\":%s"), *JsonStr(O.OwnerClass)));
				G.Add(FString::Printf(TEXT("\"property\":%s"), *JsonStr(O.Property)));
				G.Add(FString::Printf(TEXT("\"value\":%s"), *JsonStr(O.Value)));
				G.Add(FString::Printf(TEXT("\"inherited\":%s"), *JsonStr(O.InheritedValue)));
				G.Add(FString::Printf(TEXT("\"truncated_from\":%d"), O.TruncatedFrom));
				G.Add(FString::Printf(TEXT("\"window_at\":%d"), O.WindowAt));
				G.Add(FString::Printf(TEXT("\"redacted\":%s"), O.bRedacted ? TEXT("true") : TEXT("false")));
				Ovr.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
			}
			F.Add(FString::Printf(TEXT("\"overrides\":[%s]"), *FString::Join(Ovr, TEXT(","))));
		}
		{
			TArray<FString> Vars;
			for (const FBPVariable& V : R.Variables)
			{
				TArray<FString> G;
				G.Add(FString::Printf(TEXT("\"name\":%s"), *JsonStr(V.Name)));
				G.Add(FString::Printf(TEXT("\"type\":%s"), *JsonStr(V.Type)));
				G.Add(FString::Printf(TEXT("\"default\":%s"), *JsonStr(V.Default)));
				G.Add(FString::Printf(TEXT("\"category\":%s"), *JsonStr(V.Category)));
				G.Add(FString::Printf(TEXT("\"tooltip\":%s"), *JsonStr(V.Tooltip)));
				G.Add(FString::Printf(TEXT("\"flags\":%s"), *JsonStrArray(V.Flags)));
				G.Add(FString::Printf(TEXT("\"replication\":%s"), *JsonStr(V.Replication)));
				G.Add(FString::Printf(TEXT("\"rep_notify\":%s"), *JsonStr(V.RepNotify)));
				Vars.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
			}
			F.Add(FString::Printf(TEXT("\"variables\":[%s]"), *FString::Join(Vars, TEXT(","))));
		}
		{
			TArray<FString> Comps;
			for (const FBPComponent& C : R.Components)
			{
				TArray<FString> G;
				G.Add(FString::Printf(TEXT("\"name\":%s"), *JsonStr(C.Name)));
				G.Add(FString::Printf(TEXT("\"class\":%s"), *JsonStr(C.Class)));
				G.Add(FString::Printf(TEXT("\"kind\":%s"), *JsonStr(C.Kind)));
				G.Add(FString::Printf(TEXT("\"attach_parent\":%s"), *JsonStr(C.AttachParent)));
				G.Add(FString::Printf(TEXT("\"attach_socket\":%s"), *JsonStr(C.AttachSocket)));
				G.Add(FString::Printf(TEXT("\"inherited\":%s"), C.bInherited ? TEXT("true") : TEXT("false")));
				G.Add(FString::Printf(TEXT("\"source\":%s"), *JsonStr(C.Source)));
				G.Add(FString::Printf(TEXT("\"parent_is_native\":%s"), C.bParentNative ? TEXT("true") : TEXT("false")));
				Comps.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
			}
			F.Add(FString::Printf(TEXT("\"components\":[%s]"), *FString::Join(Comps, TEXT(","))));
		}
		{
			// null rather than false when the default object is not an Actor: a widget does not
			// tick in the way this question means, and saying "false" would answer a question that
			// was not asked.
			TArray<FString> G;
			G.Add(FString::Printf(TEXT("\"can_ever_tick\":%s"),
				R.Tick.bKnown ? (R.Tick.bCanEverTick ? TEXT("true") : TEXT("false")) : TEXT("null")));
			G.Add(FString::Printf(TEXT("\"start_with_tick_enabled\":%s"),
				R.Tick.bKnown ? (R.Tick.bStartWithTickEnabled ? TEXT("true") : TEXT("false")) : TEXT("null")));
			G.Add(FString::Printf(TEXT("\"event_tick_wired\":%s"), R.Tick.bEventTickWired ? TEXT("true") : TEXT("false")));
			G.Add(FString::Printf(TEXT("\"tick_node_disabled\":%s"), R.Tick.bTickNodeDisabled ? TEXT("true") : TEXT("false")));
			F.Add(FString::Printf(TEXT("\"tick\":{%s}"), *FString::Join(G, TEXT(","))));
		}
		F.Add(FString::Printf(TEXT("\"root_component\":%s"), *JsonStr(R.RootComponent)));
		{
			TArray<FString> Fns;
			for (const FBPFunction& Fn : R.Functions)
			{
				TArray<FString> G;
				G.Add(FString::Printf(TEXT("\"name\":%s"), *JsonStr(Fn.Name)));
				G.Add(FString::Printf(TEXT("\"inputs\":%s"), *JsonStrArray(Fn.Inputs)));
				G.Add(FString::Printf(TEXT("\"outputs\":%s"), *JsonStrArray(Fn.Outputs)));
				G.Add(FString::Printf(TEXT("\"pure\":%s"), Fn.bPure ? TEXT("true") : TEXT("false")));
				G.Add(FString::Printf(TEXT("\"const\":%s"), Fn.bConst ? TEXT("true") : TEXT("false")));
				G.Add(FString::Printf(TEXT("\"access\":%s"), *JsonStr(Fn.Access)));
				G.Add(FString::Printf(TEXT("\"category\":%s"), *JsonStr(Fn.Category)));
				G.Add(FString::Printf(TEXT("\"tooltip\":%s"), *JsonStr(Fn.Tooltip)));
				Fns.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
			}
			F.Add(FString::Printf(TEXT("\"functions\":[%s]"), *FString::Join(Fns, TEXT(","))));
		}
		{
			TArray<FString> Evs;
			for (const FBPEventNode& E : R.Events)
			{
				TArray<FString> G;
				G.Add(FString::Printf(TEXT("\"name\":%s"), *JsonStr(E.Name)));
				G.Add(FString::Printf(TEXT("\"kind\":%s"), *JsonStr(E.Kind)));
				G.Add(FString::Printf(TEXT("\"inputs\":%s"), *JsonStrArray(E.Inputs)));
				G.Add(FString::Printf(TEXT("\"net\":%s"), *JsonStrArray(E.NetFlags)));
				G.Add(FString::Printf(TEXT("\"wired\":%s"), E.bWired ? TEXT("true") : TEXT("false")));
				Evs.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
			}
			F.Add(FString::Printf(TEXT("\"events\":[%s]"), *FString::Join(Evs, TEXT(","))));
		}
		{
			TArray<FString> Ds;
			for (const FBPDispatcher& D : R.Dispatchers)
			{
				Ds.Add(FString::Printf(TEXT("{\"name\":%s,\"inputs\":%s}"),
					*JsonStr(D.Name), *JsonStrArray(D.Inputs)));
			}
			F.Add(FString::Printf(TEXT("\"dispatchers\":[%s]"), *FString::Join(Ds, TEXT(","))));
		}
		{
			TArray<FString> Ts;
			for (const FBPTimeline& T : R.Timelines)
			{
				Ts.Add(FString::Printf(TEXT("{\"name\":%s,\"length\":%s}"),
					*JsonStr(T.Name), *JsonStr(T.Length)));
			}
			F.Add(FString::Printf(TEXT("\"timelines\":[%s]"), *FString::Join(Ts, TEXT(","))));
		}
		{
			TArray<FString> Is;
			for (const FBPInterfaceImpl& Impl : R.InterfaceImpls)
			{
				Is.Add(FString::Printf(TEXT("{\"name\":%s,\"functions\":%s}"),
					*JsonStr(Impl.Name), *JsonStrArray(Impl.Functions)));
			}
			F.Add(FString::Printf(TEXT("\"interfaces\":[%s]"), *FString::Join(Is, TEXT(","))));
		}
		{
			TArray<FString> Es;
			for (const FBPOutEdge& E : R.CallsOut)
			{
				TArray<FString> G;
				G.Add(FString::Printf(TEXT("\"target\":%s"), *JsonStr(E.TargetPath)));
				G.Add(FString::Printf(TEXT("\"target_stem\":%s"), *JsonStr(E.TargetStem)));
				G.Add(FString::Printf(TEXT("\"member\":%s"), *JsonStr(E.Member)));
				G.Add(FString::Printf(TEXT("\"kind\":%s"), *JsonStr(E.Kind)));
				G.Add(FString::Printf(TEXT("\"graph\":%s"), *JsonStr(E.GraphName)));
				G.Add(FString::Printf(TEXT("\"count\":%d"), E.Count));
				Es.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
			}
			F.Add(FString::Printf(TEXT("\"calls_out\":[%s]"), *FString::Join(Es, TEXT(","))));
		}
		F.Add(FString::Printf(TEXT("\"hard_dependencies\":%s"), *JsonStrArray(R.HardDependencies)));
		F.Add(FString::Printf(TEXT("\"soft_dependencies\":%s"), *JsonStrArray(R.SoftDependencies)));
		F.Add(FString::Printf(TEXT("\"sections\":%s"),
			*JsonStrArray(TArray<FString>({ TEXT("identity"), TEXT("overrides"),
				TEXT("variables"), TEXT("components"), TEXT("tick"), TEXT("functions"),
				TEXT("events"), TEXT("dispatchers"), TEXT("timelines"), TEXT("interfaces"),
				TEXT("calls_out"), TEXT("dependencies") }))));
		return FString::Printf(TEXT("{%s}"), *FString::Join(F, TEXT(",")));
	}

	FString Tag(const FAssetData& Data, const FName Key, const TCHAR* Fallback = TEXT(""))
	{
		FString Value;
		if (Data.GetTagValue(Key, Value) && !Value.IsEmpty())
		{
			return Value;
		}
		return Fallback;
	}

	// Registry tags store class paths in export form, Class'/Script/Module.Name'. The quoted form
	// is noise in a document meant to be read, so reduce it to the plain path.
	FString TidyClassPath(const FString& In)
	{
		if (In.IsEmpty() || In == TEXT("None"))
		{
			return TEXT("");
		}
		FString Out = In;
		int32 Quote = INDEX_NONE;
		if (Out.FindChar(TEXT('\''), Quote))
		{
			Out = Out.RightChop(Quote + 1);
			Out.RemoveFromEnd(TEXT("'"));
		}
		return Out;
	}

	// UClass::IsA is private on purpose, because "is this UClass object an instance of X" is a
	// different question from "does this class derive from X" and people confuse them. What we
	// actually want is simpler: was this class declared in C++.
	// The ImplementedInterfaces tag is the exported form of an FBPInterfaceDescription array, which
	// carries the graph list too and is unreadable in a table. Pull out just the class names.
	TArray<FString> TidyInterfaceList(const FString& In)
	{
		TArray<FString> Names;
		const FString Key = TEXT("Interface=\"");
		int32 At = 0;
		while (true)
		{
			const int32 Start = In.Find(Key, ESearchCase::CaseSensitive, ESearchDir::FromStart, At);
			if (Start == INDEX_NONE) { break; }
			const int32 ValueStart = Start + Key.Len();
			const int32 End = In.Find(TEXT("\""), ESearchCase::CaseSensitive, ESearchDir::FromStart, ValueStart);
			if (End == INDEX_NONE) { break; }
			FString Path = TidyClassPath(In.Mid(ValueStart, End - ValueStart));
			// Reduce /Script/Module.ClassName to ClassName, which is how it gets asked about.
			int32 Dot = INDEX_NONE;
			if (Path.FindLastChar(TEXT('.'), Dot)) { Path = Path.RightChop(Dot + 1); }
			if (!Path.IsEmpty()) { Names.AddUnique(Path); }
			At = End + 1;
		}
		Names.Sort();
		return Names;
	}

	FString TidyInterfaces(const FString& In)
	{
		return FString::Join(TidyInterfaceList(In), TEXT(", "));
	}

	bool IsNativeClass(const UClass* Class)
	{
		return Class && Class->IsNative();
	}

	// The package path of the Blueprint that generated a class, or empty when the class is native.
	FString BlueprintPackageOf(const UClass* Class)
	{
		if (!Class || Class->IsNative()) { return FString(); }
		const UPackage* Package = Class->GetOutermost();
		return Package ? Package->GetName() : FString();
	}

	void WalkGraph(const UEdGraph* Graph, const FString& BlueprintPath, TArray<FBPEdge>& Out,
		TArray<FBPOutEdge>* OutBP = nullptr)
	{
		if (!Graph)
		{
			return;
		}

		for (const UEdGraphNode* Node : Graph->Nodes)
		{
			if (const UK2Node_CallFunction* Call = Cast<UK2Node_CallFunction>(Node))
			{
				const UFunction* Fn = Call->GetTargetFunction();
				// Only record calls into native C++. Blueprint to Blueprint calls are a different
				// question and would drown out the one this index exists to answer.
				if (Fn && IsNativeClass(Fn->GetOwnerClass()))
				{
					Out.Add({ FString::Printf(TEXT("%s::%s"), *Fn->GetOwnerClass()->GetName(), *Fn->GetName()),
						BlueprintPath, Graph->GetName(), TEXT("call") });
				}
				else if (Fn && OutBP)
				{
					// The call this walk has always dropped. Its target is a Blueprint, so no C++
					// tool sees it and renaming the function still compiles - the same argument
					// that justifies bpcallers/, one level up.
					const FString Target = BlueprintPackageOf(Fn->GetOwnerClass());
					if (!Target.IsEmpty() && Target != BlueprintPath)
					{
						FBPOutEdge E;
						E.TargetPath = Target;
						E.Member = Fn->GetName();
						E.Kind = TEXT("call");
						E.GraphName = Graph->GetName();
						OutBP->Add(MoveTemp(E));
					}
				}
			}
			else if (const UK2Node_DynamicCast* CastNode = Cast<UK2Node_DynamicCast>(Node))
			{
				// A cast is a HARD reference: it is the usual reason loading one Blueprint loads
				// twenty, and it is invisible to every text tool for the same reason a call is.
				const FString Target = BlueprintPackageOf(CastNode->TargetType);
				if (OutBP && !Target.IsEmpty() && Target != BlueprintPath)
				{
					FBPOutEdge E;
					E.TargetPath = Target;
					E.Kind = TEXT("cast");
					E.GraphName = Graph->GetName();
					OutBP->Add(MoveTemp(E));
				}
			}
			else if (const UK2Node_Variable* Var = Cast<UK2Node_Variable>(Node))
			{
				const FProperty* Prop = Var->GetPropertyForVariable();
				if (Prop && IsNativeClass(Prop->GetOwnerClass()))
				{
					const bool bWrite = Node->GetClass()->GetName().Contains(TEXT("VariableSet"));
					Out.Add({ FString::Printf(TEXT("%s::%s"), *Prop->GetOwnerClass()->GetName(), *Prop->GetName()),
						BlueprintPath, Graph->GetName(), bWrite ? TEXT("write") : TEXT("read") });
				}
			}
		}
	}

	// A C++ widget class can reach into a Widget Blueprint without a single graph node: a
	// UPROPERTY(meta=(BindWidget)) is bound BY NAME to the widget of that name in the Blueprint's
	// designer tree, and BindWidgetAnim likewise to an animation. The widget compiler enforces the
	// binding, so renaming the C++ property breaks the Blueprint exactly as renaming a called
	// function would - and the graph walk above sees none of it. On a sample game, 11 of the 88 Blueprints
	// that produced no graph edge turned out to be widgets whose only C++ contact is this binding
	// (one widget Blueprint on a sample gameSafeZoneEditor's four BindWidget properties, the two confirmation
	// dialogs, both on-screen joysticks, the settings list entries). Without this walk, bpcallers/
	// said "no Blueprint users" for every one of those classes, which is the false negative the
	// file exists to prevent.
	//
	// The symbol is attributed to the class that DECLARES the property, walking the native chain,
	// so it lands in the same bpcallers/<Class>.md as a call to one of that class's functions would.
	void WalkWidgetBindings(const UBlueprint* BP, UClass* ParentClass, const FString& BlueprintPath, TArray<FBPEdge>& Out)
	{
		const UWidgetBlueprint* WBP = Cast<UWidgetBlueprint>(BP);
		if (!WBP || !ParentClass)
		{
			return;
		}

		TSet<FName> WidgetNames;
		if (WBP->WidgetTree)
		{
			TArray<UWidget*> Widgets;
			WBP->WidgetTree->GetAllWidgets(Widgets);
			for (const UWidget* W : Widgets)
			{
				if (W) { WidgetNames.Add(W->GetFName()); }
			}
		}
		TSet<FName> AnimNames;
		for (const UWidgetAnimation* Anim : WBP->Animations)
		{
			if (Anim)
			{
				AnimNames.Add(Anim->GetFName());
				AnimNames.Add(FName(*Anim->GetDisplayLabel()));
			}
		}
		if (WidgetNames.Num() == 0 && AnimNames.Num() == 0)
		{
			return;
		}

		for (UClass* Class = ParentClass; Class; Class = Class->GetSuperClass())
		{
			if (!Class->IsNative())
			{
				continue;
			}
			for (TFieldIterator<FProperty> It(Class, EFieldIteratorFlags::ExcludeSuper); It; ++It)
			{
				const FProperty* Prop = *It;
				bool bOptional = false;
				if (FWidgetBlueprintEditorUtils::IsBindWidgetProperty(Prop, bOptional))
				{
					if (WidgetNames.Contains(Prop->GetFName()))
					{
						Out.Add({ FString::Printf(TEXT("%s::%s"), *Class->GetName(), *Prop->GetName()),
							BlueprintPath, TEXT("WidgetTree"), TEXT("bind") });
					}
				}
				else if (FWidgetBlueprintEditorUtils::IsBindWidgetAnimProperty(Prop, bOptional))
				{
					if (AnimNames.Contains(Prop->GetFName()))
					{
						Out.Add({ FString::Printf(TEXT("%s::%s"), *Class->GetName(), *Prop->GetName()),
							BlueprintPath, TEXT("Animations"), TEXT("bind") });
					}
				}
			}
		}
	}
}

int32 AgentMemoryBlueprintIndex::Emit(const FString& OutDir, bool bWalkGraphs)
{
	FAssetRegistryModule& Module = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	IAssetRegistry& Registry = Module.Get();
	Registry.SearchAllAssets(true);

	TArray<FAssetData> Assets;
	Registry.GetAssetsByClass(UBlueprint::StaticClass()->GetClassPathName(), Assets, true);

	// Our content only. That is /Game plus the mount point of every non-engine plugin: plugin
	// content mounts under /<PluginName>/, not under /Game, so filtering on /Game alone silently
	// finds nothing in a project whose Blueprints all live in a plugin. Engine content would
	// swamp the file and is not ours to describe.
	TArray<FString> AllowedRoots;
	AllowedRoots.Add(TEXT("/Game/"));
	for (const TSharedRef<IPlugin>& Plugin : IPluginManager::Get().GetEnabledPlugins())
	{
		const EPluginType Type = Plugin->GetType();
		if (Type == EPluginType::Engine || Type == EPluginType::Enterprise)
		{
			continue;
		}
		if (Plugin->GetName() == TEXT("AgentMemory"))
		{
			continue;
		}
		AllowedRoots.AddUnique(FString::Printf(TEXT("/%s/"), *Plugin->GetName()));
	}

	Assets.RemoveAll([&AllowedRoots](const FAssetData& D)
	{
		const FString Package = D.PackageName.ToString();
		for (const FString& Root : AllowedRoots)
		{
			if (Package.StartsWith(Root))
			{
				return false;
			}
		}
		return true;
	});
	Assets.Sort([](const FAssetData& A, const FAssetData& B) { return A.PackageName.LexicalLess(B.PackageName); });

	// Both of these files used to be one table each, and both grew past the point where an agent
	// could read them: 376 KB and 87 KB on a 506-Blueprint project, about 94,000 and 22,000 tokens. That is the same
	// failure the per-module reflection dump had, arriving from a different direction, so they get
	// the same fix: an index plus one small file per owner.
	auto ParentFileName = [](const FString& NativePath)
	{
		FString S = NativePath;
		S.RemoveFromStart(TEXT("/Script/"));
		S.ReplaceInline(TEXT("/"), TEXT("-"));
		S.ReplaceInline(TEXT("."), TEXT("-"));
		return S.IsEmpty() ? FString(TEXT("unknown")) : S;
	};
	auto OwnerOf = [](const FString& Symbol)
	{
		FString Left, Right;
		return Symbol.Split(TEXT("::"), &Left, &Right) ? Left : Symbol;
	};

	// Native parent -> the full rows for the Blueprints under it.
	TMap<FString, TArray<FString>> ByParent;

	// The model, one entry per Blueprint, in the same order as Assets - which is sorted by package
	// path above, so the sidecar is sorted without a second sort.
	TArray<FBPRecord> Records;
	Records.Reserve(Assets.Num());

	TArray<FString> Lines;
	Lines.Add(TEXT("# Blueprint index"));
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("Inheritance, interfaces and replication come from asset registry tags, which need no"));
	Lines.Add(TEXT("asset loading. clangd and ripgrep can see none of this: it lives in binary .uasset files."));
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("**This file is an index.** One row per native parent class, with the Blueprints"));
	Lines.Add(TEXT("under it in `blueprints/<Parent>.md`. Grep this table for the parent you care about"));
	Lines.Add(TEXT("and read that one file, rather than reading the whole set."));
	Lines.Add(TEXT(""));
	Lines.Add(TEXT("| Native parent | Blueprints | Detail |"));
	Lines.Add(TEXT("|---|---|---|"));

	TArray<FBPEdge> Edges;

	// Walk coverage, counted rather than assumed, so the absence claim in bpcallers/ can state
	// exactly what it rests on. A data-only Blueprint has no graphs by construction and cannot
	// produce an edge; it is not a gap in the walk, and counting it as one made the coverage
	// figure read as "54% of Blueprints walked" when every Blueprint that could be walked was.
	int32 NumBlueprints = 0;
	int32 NumDataOnly = 0;
	int32 NumWalked = 0;

	// Counted across the whole project rather than per Blueprint: the redaction rule is a name
	// match and over-fires by design, and a rule nobody measured is a rule nobody can argue with.
	int32 RedactedNonString = 0;

	for (const FAssetData& Data : Assets)
	{
		const FString Path = Data.PackageName.ToString();
		TArray<FBPOverride> PendingOverrides;
		TArray<FBPVariable> PendingVariables;
		TArray<FBPComponent> PendingComponents;
		FBPTick PendingTick;
		FString PendingRoot;
		TArray<FBPFunction> PendingFunctions;
		TArray<FBPEventNode> PendingEvents;
		TArray<FBPDispatcher> PendingDispatchers;
		TArray<FBPTimeline> PendingTimelines;
		TArray<FBPInterfaceImpl> PendingInterfaces;
		TArray<FBPOutEdge> PendingCallsOut;
		FString Native = TidyClassPath(Tag(Data, FBlueprintTags::NativeParentClassPath));
		FString Parent = TidyClassPath(Tag(Data, FBlueprintTags::ParentClassPath));
		const FString Interfaces = TidyInterfaces(Tag(Data, FBlueprintTags::ImplementedInterfaces, TEXT("")));
		const FString RepCount = Tag(Data, FBlueprintTags::NumReplicatedProperties, TEXT("0"));
		const FString DataOnly = Tag(Data, FBlueprintTags::IsDataOnly, TEXT("?"));
		const FString NativeComps = Tag(Data, FBlueprintTags::NumNativeComponents, TEXT("0"));
		const FString BPComps = Tag(Data, FBlueprintTags::NumBlueprintComponents, TEXT("0"));

		++NumBlueprints;
		if (DataOnly == TEXT("True"))
		{
			++NumDataOnly;
		}

		if (bWalkGraphs)
		{
			if (UBlueprint* BP = Cast<UBlueprint>(Data.GetAsset()))
			{
				++NumWalked;

				// Not every Blueprint carries usable parent tags in the registry, and an empty
				// cell in this table is worse than a slow one: a reader cannot tell "no parent"
				// from "we failed to look". If we have already paid to load the asset, read the
				// parent off the object instead.
				// ParentClass is not always set on a loaded Blueprint, but the generated class
				// knows its own super, so try that second. Seen on 4 of 8 Blueprints in one plugin.
				UClass* ParentClass = BP->ParentClass;
				if (!ParentClass && BP->GeneratedClass)
				{
					ParentClass = BP->GeneratedClass->GetSuperClass();
				}

				for (const UEdGraph* Graph : BP->UbergraphPages) { WalkGraph(Graph, Path, Edges, &PendingCallsOut); }
				for (const UEdGraph* Graph : BP->FunctionGraphs) { WalkGraph(Graph, Path, Edges, &PendingCallsOut); }
				// Macro libraries keep their calls in MacroGraphs and nowhere else: a macro is
				// expanded into its callers at compile time, so the source graphs of a caller hold
				// only the instance node. Three a sample game macro libraries produced no edge because of this.
				for (const UEdGraph* Graph : BP->MacroGraphs) { WalkGraph(Graph, Path, Edges, &PendingCallsOut); }
				WalkWidgetBindings(BP, ParentClass, Path, Edges);

				// Overrides need the loaded asset, so they live here rather than in the registry
				// tier above. Three sources, kept as three owner kinds.
				if (UClass* GenClass = BP->GeneratedClass)
				{
					CollectVariables(BP, GenClass, PendingVariables);
					CollectComponents(BP, ParentClass, GenClass, PendingComponents, PendingRoot);
					PendingTick = CollectTick(BP, GenClass);
					CollectFunctions(BP, PendingFunctions);
					CollectEvents(BP, PendingEvents);
					CollectDispatchers(BP, PendingDispatchers);
					CollectTimelines(BP, PendingTimelines);
					CollectInterfaces(BP, PendingInterfaces);

					if (ParentClass && GenClass->GetDefaultObject() && ParentClass->GetDefaultObject())
					{
						// The parent class supplies the property list, so a variable this Blueprint
						// DECLARES is not reported here - it has no inherited value to differ from,
						// and it belongs to the variables section instead.
						CollectOverrides(ParentClass, GenClass->GetDefaultObject(), ParentClass->GetDefaultObject(),
							TEXT("class"), FString(), FString(), PendingOverrides, RedactedNonString,
							/*bDescendIntoSubobjects*/ true);
					}

					if (BP->SimpleConstructionScript)
					{
						for (const USCS_Node* Node : BP->SimpleConstructionScript->GetAllNodes())
						{
							const UActorComponent* Template = Node ? Node->ComponentTemplate : nullptr;
							if (!Template) { continue; }
							CollectOverrides(Template->GetClass(), Template, Template->GetClass()->GetDefaultObject(),
								TEXT("component"), Node->GetVariableName().ToString(),
								Template->GetClass()->GetName(), PendingOverrides, RedactedNonString);
						}
					}

					// A component inherited from a parent Blueprint can be retuned without being
					// redeclared, and that override lives in a third place again. Compared against
					// the template it actually overrides - NOT against the component class default,
					// which would re-report the parent's changes as this Blueprint's.
					if (UInheritableComponentHandler* ICH = BP->InheritableComponentHandler)
					{
						TArray<UActorComponent*> Overridden;
						ICH->GetAllTemplates(Overridden);
						for (UActorComponent* Template : Overridden)
						{
							if (!Template) { continue; }
							const FComponentKey Key = ICH->FindKey(Template);
							const UActorComponent* Original = Key.IsValid() ? Key.GetOriginalTemplate() : nullptr;
							if (!Original) { continue; }
							CollectOverrides(Template->GetClass(), Template, Original,
								TEXT("inherited_component"), Key.GetSCSVariableName().ToString(),
								Template->GetClass()->GetName(), PendingOverrides, RedactedNonString);
						}
					}
				}

				if (Parent.IsEmpty() && ParentClass)
				{
					Parent = ParentClass->GetPathName();
				}
				if (Native.IsEmpty())
				{
					for (UClass* Super = ParentClass; Super; Super = Super->GetSuperClass())
					{
						if (Super->IsNative()) { Native = Super->GetPathName(); break; }
					}
				}

				if (Parent.IsEmpty())
				{
					// Say so in the log rather than leaving a silent 'unknown' in the table.
					UE_LOG(LogTemp, Warning,
						TEXT("AgentMemoryDump: %s has no resolvable parent (ParentClass=%s, GeneratedClass=%s)"),
						*Path,
						BP->ParentClass ? *BP->ParentClass->GetName() : TEXT("null"),
						BP->GeneratedClass ? *BP->GeneratedClass->GetName() : TEXT("null"));
				}
			}
		}

		// Emitted after the walk, so the fallbacks above are already applied.
		const FString NativeKey = Native.IsEmpty() ? FString(TEXT("unknown")) : Native;

		{
			FBPRecord Rec;
			Rec.Path = Path;
			Rec.Stem = StemForPackage(Path);
			Rec.Name = Data.AssetName.ToString();
			Rec.Parent = Parent;
			Rec.NativeParent = Native;
			Rec.Interfaces = TidyInterfaceList(Tag(Data, FBlueprintTags::ImplementedInterfaces, TEXT("")));
			Rec.ReplicatedProps = FCString::Atoi(*RepCount);
			Rec.DataOnly = (DataOnly == TEXT("True")) ? 1 : ((DataOnly == TEXT("False")) ? 0 : -1);
			Rec.NativeComponents = FCString::Atoi(*NativeComps);

			// "What does loading this drag in", answered without loading anything. A hard
			// dependency is pulled in at load; a soft one is a path that resolves later.
			{
				TArray<FAssetDependency> Deps;
				Registry.GetDependencies(FAssetIdentifier(Data.PackageName), Deps,
					UE::AssetRegistry::EDependencyCategory::Package);
				for (const FAssetDependency& Dep : Deps)
				{
					const FString Name = Dep.AssetId.PackageName.ToString();
					// Our content only, on the same rule the Blueprint scan uses: an engine
					// package in every row would drown the ones a reader can act on.
					bool bOurs = false;
					for (const FString& Root : AllowedRoots)
					{
						if (Name.StartsWith(Root)) { bOurs = true; break; }
					}
					if (!bOurs) { continue; }

					if (EnumHasAnyFlags(Dep.Properties, UE::AssetRegistry::EDependencyProperty::Hard))
					{
						Rec.HardDependencies.AddUnique(Name);
					}
					else
					{
						Rec.SoftDependencies.AddUnique(Name);
					}
				}
				Rec.HardDependencies.Sort();
				Rec.SoftDependencies.Sort();
			}
			Rec.BlueprintComponents = FCString::Atoi(*BPComps);
			PendingOverrides.Sort();
			Rec.Overrides = MoveTemp(PendingOverrides);
			Rec.Variables = MoveTemp(PendingVariables);
			Rec.Components = MoveTemp(PendingComponents);
			Rec.Tick = PendingTick;
			Rec.RootComponent = MoveTemp(PendingRoot);
			Rec.Functions = MoveTemp(PendingFunctions);
			Rec.Events = MoveTemp(PendingEvents);
			Rec.Dispatchers = MoveTemp(PendingDispatchers);
			Rec.Timelines = MoveTemp(PendingTimelines);
			Rec.InterfaceImpls = MoveTemp(PendingInterfaces);

			// Two call nodes to the same function in the same graph are two uses, not one, which
			// is the same rule bpcallers/ already follows for its own counts.
			{
				PendingCallsOut.Sort();
				TArray<FBPOutEdge> Folded;
				for (FBPOutEdge& E : PendingCallsOut)
				{
					E.TargetStem = StemForPackage(E.TargetPath);
					if (Folded.Num() > 0
						&& Folded.Last().TargetPath == E.TargetPath
						&& Folded.Last().Kind == E.Kind
						&& Folded.Last().Member == E.Member
						&& Folded.Last().GraphName == E.GraphName)
					{
						++Folded.Last().Count;
					}
					else
					{
						Folded.Add(E);
					}
				}
				Rec.CallsOut = MoveTemp(Folded);
			}
			Records.Add(MoveTemp(Rec));
		}
		ByParent.FindOrAdd(NativeKey).Add(FString::Printf(TEXT("| `%s` | `%s` | %s | %s | %s | %s + %s | [detail](../bp/%s.md) |"),
			*Path,
			Parent.IsEmpty() ? TEXT("unknown") : *Parent,
			Interfaces.IsEmpty() ? TEXT("none") : *Interfaces,
			*RepCount, *DataOnly, *NativeComps, *BPComps,
			*StemForPackage(Path)));
	}

	{
		TArray<FString> Parents;
		ByParent.GetKeys(Parents);
		Parents.Sort();

		const FString ParentDir = FPaths::Combine(OutDir, TEXT("blueprints"));
		IFileManager::Get().MakeDirectory(*ParentDir, true);

		for (const FString& NativeKey : Parents)
		{
			const TArray<FString>& Rows = ByParent[NativeKey];
			const FString Stem = ParentFileName(NativeKey);

			TArray<FString> Doc;
			Doc.Add(FString::Printf(TEXT("# Blueprints deriving from `%s`"), *NativeKey));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
			Doc.Add(TEXT(""));
			// say what this file IS, not just what is in it. A benchmark question
			// asked for every Blueprint whose ultimate native parent is X, found the exact six, and
			// then offered a fourteen-item alternative with equal weight rather than committing.
			// The data was right; the file never stated its own grouping rule, so the answer hedged.
			Doc.Add(FString::Printf(TEXT("**This file is the complete set for `%s` as an ULTIMATE native parent.**"), *NativeKey));
			Doc.Add(FString::Printf(TEXT("%d Blueprint(s), including ones that reach `%s` through another Blueprint."), Rows.Num(), *NativeKey));
			Doc.Add(TEXT("The immediate parent is in the second column, so a Blueprint whose immediate parent is a"));
			Doc.Add(TEXT("*different* native class appears in that class's file as well as this one. If you were asked"));
			Doc.Add(TEXT("for the ultimate native parent, this list is the answer and needs no widening."));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("| Blueprint | Immediate parent | Interfaces | Replicated props | Data only | Components (native + BP) | Detail |"));
			Doc.Add(TEXT("|---|---|---|---|---|---|---|"));
			Doc.Append(Rows);
			Doc.Add(TEXT(""));

			AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")),
				*FPaths::Combine(ParentDir, Stem + TEXT(".md")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

			Lines.Add(FString::Printf(TEXT("| `%s` | %d | [%s](blueprints/%s.md) |"),
				*NativeKey, Rows.Num(), *Stem, *Stem));
		}
	}

	{
		// ---- The input tier: what each key is actually bound to. ----
		//
		// The registry tier above answers "which mapping contexts exist" and stops there, because it
		// reads tags and never loads. That is right for 8,687 assets and wrong for these: a binding
		// lives in no tag, so without loading, the layers cannot say what is on any key. There are
		// FOUR mapping contexts here, so the load costs nothing and buys the only questions anyone
		// actually asks - what does this key do, does a key drive two actions, does a context
		// re-bind a key another context already bound.
		TArray<FAssetData> ContextAssets;
		Registry.GetAssetsByClass(UInputMappingContext::StaticClass()->GetClassPathName(), ContextAssets, true);
		ContextAssets.RemoveAll([&AllowedRoots](const FAssetData& D)
		{
			const FString Package = D.PackageName.ToString();
			for (const FString& Root : AllowedRoots) { if (Package.StartsWith(Root)) { return false; } }
			return true;
		});
		ContextAssets.Sort([](const FAssetData& A, const FAssetData& B)
		{
			if (A.PackageName != B.PackageName) { return A.PackageName.LexicalLess(B.PackageName); }
			return A.AssetName.LexicalLess(B.AssetName);
		});

		struct FBinding
		{
			FString ContextPath, ContextName, ActionPath, ActionName, Key, ValueType;
			TArray<FString> Triggers, Modifiers;
		};
		TArray<FBinding> Bindings;

		for (const FAssetData& Data : ContextAssets)
		{
			const UInputMappingContext* Context = Cast<UInputMappingContext>(Data.GetAsset());
			if (!Context) { continue; }

			for (const FEnhancedActionKeyMapping& Map : Context->GetMappings())
			{
				FBinding B;
				B.ContextPath = Data.PackageName.ToString();
				B.ContextName = Data.AssetName.ToString();
				// GetFName, not ToString: the FName is the stable identifier the asset stores and
				// an editor-free package parse recovers, while ToString is a display form. Keying
				// the reverse index on a display string would also make it locale-shaped.
				B.Key = Map.Key.GetFName().ToString();
				if (const UInputAction* Action = Map.Action)
				{
					B.ActionPath = Action->GetPackage() ? Action->GetPackage()->GetName() : FString();
					B.ActionName = Action->GetName();
					if (const UEnum* VT = StaticEnum<EInputActionValueType>())
					{
						B.ValueType = VT->GetNameStringByValue((int64)Action->ValueType);
					}
				}
				// Class names only: an instanced trigger or modifier exports as an object path with
				// a transient name, which would differ between two runs of the same dump.
				for (const UInputTrigger* T : Map.Triggers)  { if (T) { B.Triggers.AddUnique(T->GetClass()->GetName()); } }
				for (const UInputModifier* M : Map.Modifiers) { if (M) { B.Modifiers.AddUnique(M->GetClass()->GetName()); } }
				B.Triggers.Sort();
				B.Modifiers.Sort();
				Bindings.Add(MoveTemp(B));
			}
		}

		// A TOTAL order, and the trailing fields are not decoration. (context, key) is not unique -
		// one key can drive two actions - and (context, action) is not either, since one action
		// takes several keys. (context, key, action) is the minimum identity, and even that repeats
		// when a context binds the same pair twice with different triggers, so the trigger and
		// modifier lists are the tiebreak. An unstable sort on a non-unique key is what made
		// assets.jsonl non-deterministic earlier today; this is that lesson applied before it bites.
		Bindings.Sort([](const FBinding& A, const FBinding& B)
		{
			if (A.ContextPath != B.ContextPath) { return A.ContextPath < B.ContextPath; }
			if (A.Key != B.Key)                 { return A.Key < B.Key; }
			if (A.ActionPath != B.ActionPath)   { return A.ActionPath < B.ActionPath; }
			const FString AT = FString::Join(A.Triggers, TEXT(",")) + TEXT("|") + FString::Join(A.Modifiers, TEXT(","));
			const FString BT = FString::Join(B.Triggers, TEXT(",")) + TEXT("|") + FString::Join(B.Modifiers, TEXT(","));
			return AT < BT;
		});

		// Report a repeated (context, key, action) rather than letting it pass as a duplicate row.
		// If this is ever non-zero the triple is not an identity and a consumer keying on it will
		// silently collapse rows, which is the exact failure the registry tier already hit once.
		{
			int32 RepeatedTriples = 0;
			for (int32 i = 1; i < Bindings.Num(); ++i)
			{
				if (Bindings[i].ContextPath == Bindings[i - 1].ContextPath
					&& Bindings[i].Key == Bindings[i - 1].Key
					&& Bindings[i].ActionPath == Bindings[i - 1].ActionPath)
				{
					++RepeatedTriples;
				}
			}
			if (RepeatedTriples > 0)
			{
				UE_LOG(LogTemp, Display,
					TEXT("AgentMemoryDump: input tier - %d binding(s) repeat a (context, key, action) triple; "
						 "that triple is NOT a unique identity here"), RepeatedTriples);
			}
		}

		{
			// Emitted even when there is nothing to say, for the same reason bpusers/ is created
			// empty: an ABSENT file means "this build does not report input", an EMPTY one means
			// "this build looked and the project has none", and a reader grepping a project for
			// input cannot tell those apart from a missing file. the seed project and When-If-Then have no
			// mapping contexts at all, so before this they had no input artefacts whatsoever -
			// indistinguishable from a set written before the tier existed. This is the same defect
			// as the empty bpusers/ directory, in the second place I failed to carry the fix to.
			// --- the sidecar ---
			{
				TArray<FString> Rows;
				for (const FBinding& B : Bindings)
				{
					TArray<FString> G;
					G.Add(FString::Printf(TEXT("\"context\":%s"), *JsonStr(B.ContextPath)));
					G.Add(FString::Printf(TEXT("\"context_name\":%s"), *JsonStr(B.ContextName)));
					G.Add(FString::Printf(TEXT("\"key\":%s"), *JsonStr(B.Key)));
					G.Add(FString::Printf(TEXT("\"action\":%s"), *JsonStr(B.ActionPath)));
					G.Add(FString::Printf(TEXT("\"action_name\":%s"), *JsonStr(B.ActionName)));
					G.Add(FString::Printf(TEXT("\"value_type\":%s"), *JsonStr(B.ValueType)));
					G.Add(FString::Printf(TEXT("\"triggers\":%s"), *JsonStrArray(B.Triggers)));
					G.Add(FString::Printf(TEXT("\"modifiers\":%s"), *JsonStrArray(B.Modifiers)));
					Rows.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
				}
				FString Payload = FString::Join(Rows, TEXT("\n"));
				if (Rows.Num() > 0) { Payload += TEXT("\n"); }
				AgentMemoryFile::SaveStringToFileCRLF(Payload,
					*FPaths::Combine(OutDir, TEXT("input.jsonl")),
					FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
			}

			auto KeyStem = [](const FString& Key)
			{
				FString S = Key;
				S.ReplaceInline(TEXT("/"), TEXT("-"));
				S.ReplaceInline(TEXT("\\"), TEXT("-"));
				S.ReplaceInline(TEXT(":"), TEXT("-"));
				S.ReplaceInline(TEXT("*"), TEXT("-"));
				S.ReplaceInline(TEXT("?"), TEXT("-"));
				S.ReplaceInline(TEXT("\""), TEXT("-"));
				S.ReplaceInline(TEXT("<"), TEXT("-"));
				S.ReplaceInline(TEXT(">"), TEXT("-"));
				S.ReplaceInline(TEXT("|"), TEXT("-"));
				return S.IsEmpty() ? FString(TEXT("unknown")) : S;
			};

			// The two label facts, stated in every file that could mislead a reader who does not
			// know them. EConsoleForGamepadLabels does not name every console, so a newer one uses
			// its predecessor's set and a row labelled for it would be inventing one; and one label is genuinely
			// ambiguous across the two sets, for two keys that are bound to DIFFERENT actions.
			// The two bullets are GENERIC here, and naming a console is left to configuration: a tree
			// that needs the specific wording (its benchmark asks about a particular pad) points
			// InputLabelNoteFile in the [/Script/UEAgentAcceleratorTools.AgentMemoryDumpCommandlet]
			// section of its Editor ini at a text file, or passes -InputLabelNote=<file>. The file
			// REPLACES the bullets line for line. A configured file that cannot be read is an Error,
			// not a fallback: silently writing the generic note would change what a reader is told
			// without anything saying so.
			TArray<FString> LabelBullets = {
				TEXT("- **Not every console has a label set.** `EConsoleForGamepadLabels` names only some,"),
				TEXT("  and a newer console uses its predecessor's. A row claiming its own set would be invented."),
				TEXT("- **\"Gamepad X\" is ambiguous.** It is `Gamepad_FaceButton_Bottom` under one console's"),
				TEXT("  labels and `Gamepad_FaceButton_Left` under another's - two different keys, bound here to"),
				TEXT("  **different actions**. Resolve the label set before resolving the label."),
			};
			{
				FString NoteFile;
				if (!FParse::Value(FCommandLine::Get(), TEXT("InputLabelNote="), NoteFile) && GConfig)
				{
					GConfig->GetString(TEXT("/Script/UEAgentAcceleratorTools.AgentMemoryDumpCommandlet"),
						TEXT("InputLabelNoteFile"), NoteFile, GEditorIni);
				}
				if (!NoteFile.IsEmpty())
				{
					if (FPaths::IsRelative(NoteFile))
					{
						NoteFile = FPaths::Combine(FPaths::ProjectDir(), NoteFile);
					}
					TArray<FString> Custom;
					if (FFileHelper::LoadFileToStringArray(Custom, *NoteFile) && Custom.Num() > 0)
					{
						LabelBullets = MoveTemp(Custom);
					}
					else
					{
						UE_LOG(LogTemp, Error, TEXT("AgentMemoryDump: input label note %s is missing or empty"), *NoteFile);
					}
				}
			}
			auto LabelCaveat = [&LabelBullets](TArray<FString>& D)
			{
				D.Add(TEXT("**A controller label is not a key.** A person says \"the cross button\" and the"));
				D.Add(TEXT("asset says `Gamepad_FaceButton_Bottom`. That translation lives in the engine, in"));
				D.Add(TEXT("`EKeys::GetGamepadDisplayName`, and it is **per label set**. Two things follow that"));
				D.Add(TEXT("a reader will otherwise get wrong:"));
				D.Add(TEXT(""));
				D.Append(LabelBullets);
				D.Add(TEXT(""));
			};

			// --- one file per context ---
			const FString CtxDir = FPaths::Combine(OutDir, TEXT("input"));
			IFileManager::Get().MakeDirectory(*CtxDir, true);

			TArray<FString> Index;
			Index.Add(TEXT("# Input mapping contexts"));
			Index.Add(TEXT(""));
			Index.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
			Index.Add(TEXT(""));
			Index.Add(TEXT("Key-to-action bindings, read from the loaded assets. **This is the only tier that"));
			Index.Add(TEXT("loads**: a binding lives in no asset registry tag, so nothing else in this stack can"));
			Index.Add(TEXT("say what any key does. There are few enough contexts that the load is free."));
			Index.Add(TEXT(""));
			LabelCaveat(Index);
			Index.Add(FString::Printf(TEXT("**%d context(s), %d binding(s).**"), ContextAssets.Num(), Bindings.Num()));
			Index.Add(TEXT(""));
			Index.Add(TEXT("| Context | Bindings | Detail |"));
			Index.Add(TEXT("|---|---|---|"));

			for (const FAssetData& Data : ContextAssets)
			{
				const FString Path = Data.PackageName.ToString();
				const FString Name = Data.AssetName.ToString();
				TArray<FString> Rows;
				for (const FBinding& B : Bindings)
				{
					if (B.ContextPath != Path) { continue; }
					Rows.Add(FString::Printf(TEXT("| `%s` | `%s` | %s | %s | %s |"),
						*B.Key,
						B.ActionName.IsEmpty() ? TEXT("(none)") : *B.ActionName,
						B.ValueType.IsEmpty() ? TEXT("-") : *B.ValueType,
						B.Triggers.Num()  ? *FString::Join(B.Triggers,  TEXT(", ")) : TEXT("-"),
						B.Modifiers.Num() ? *FString::Join(B.Modifiers, TEXT(", ")) : TEXT("-")));
				}

				TArray<FString> Doc;
				Doc.Add(FString::Printf(TEXT("# `%s`"), *Path));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
				Doc.Add(TEXT(""));
				Doc.Add(FString::Printf(TEXT("**%d binding(s) in this context.** Complete: this is every mapping the"), Rows.Num()));
				Doc.Add(TEXT("asset declares, read from the loaded object rather than matched by name."));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("A context is one **layer**. Another context can bind the same key to something else,"));
				Doc.Add(TEXT("and which one wins depends on what is pushed at runtime, so a key here is not"));
				Doc.Add(TEXT("necessarily what the player gets. `inputkeys/<Key>.md` lists every context binding a"));
				Doc.Add(TEXT("given key, which is the question to ask before concluding anything about one."));
				Doc.Add(TEXT(""));
				LabelCaveat(Doc);
				Doc.Add(TEXT("| Key | Action | Value type | Triggers | Modifiers |"));
				Doc.Add(TEXT("|---|---|---|---|---|"));
				Doc.Append(Rows);
				Doc.Add(TEXT(""));

				const FString Stem = StemForPackage(Path);
				AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")),
					*FPaths::Combine(CtxDir, Stem + TEXT(".md")),
					FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

				Index.Add(FString::Printf(TEXT("| `%s` | %d | [%s](input/%s.md) |"), *Path, Rows.Num(), *Name, *Stem));
			}

			// --- the reverse index, keyed on the KEY ---
			// Same shape as bpusers/: the question "what is on this button" is one read rather than
			// a scan of every context.
			const FString KeyDir = FPaths::Combine(OutDir, TEXT("inputkeys"));
			IFileManager::Get().MakeDirectory(*KeyDir, true);

			TArray<FString> SeenKeys;
			for (const FBinding& B : Bindings) { SeenKeys.AddUnique(B.Key); }
			SeenKeys.Sort();

			for (const FString& Key : SeenKeys)
			{
				TArray<FString> Rows;
				TArray<FString> Actions;
				for (const FBinding& B : Bindings)
				{
					if (B.Key != Key) { continue; }
					Actions.AddUnique(B.ActionPath);
					Rows.Add(FString::Printf(TEXT("| `%s` | `%s` | %s | %s |"),
						*B.ContextPath,
						B.ActionPath.IsEmpty() ? TEXT("(none)") : *B.ActionPath,
						B.ValueType.IsEmpty() ? TEXT("-") : *B.ValueType,
						B.Triggers.Num() ? *FString::Join(B.Triggers, TEXT(", ")) : TEXT("-")));
				}

				TArray<FString> Doc;
				Doc.Add(FString::Printf(TEXT("# What `%s` is bound to"), *Key));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
				Doc.Add(TEXT(""));
				Doc.Add(FString::Printf(TEXT("**%d binding(s) across %d action(s).**"), Rows.Num(), Actions.Num()));
				if (Actions.Num() > 1)
				{
					Doc.Add(TEXT(""));
					Doc.Add(TEXT("**This key drives more than one action.** That is legitimate when the triggers"));
					Doc.Add(TEXT("differ or the contexts are layered, and a bug when it is neither - so the"));
					Doc.Add(TEXT("triggers are in the table rather than left to be looked up."));
				}
				Doc.Add(TEXT(""));
				LabelCaveat(Doc);
				Doc.Add(TEXT("| Context | Action | Value type | Triggers |"));
				Doc.Add(TEXT("|---|---|---|---|"));
				Doc.Append(Rows);
				Doc.Add(TEXT(""));

				AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")),
					*FPaths::Combine(KeyDir, KeyStem(Key) + TEXT(".md")),
					FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
			}

			Index.Add(TEXT(""));
			AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Index, TEXT("\n")),
				*FPaths::Combine(OutDir, TEXT("Input.md")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

			UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: input tier - %d context(s), %d binding(s), %d key file(s)"),
				ContextAssets.Num(), Bindings.Num(), SeenKeys.Num());
		}
	}

	{
		// ---- bp/<stem>.md, rendered from the SAME model the sidecar is written from. ----
		//
		// One model, two outputs. The alternative - a renderer that re-derives its values - is how
		// a document and its database drift apart while both look right, and build_api_db.py's own
		// docstring already says what re-parsing a document for data costs.
		const FString BpDir = FPaths::Combine(OutDir, TEXT("bp"));
		IFileManager::Get().MakeDirectory(*BpDir, true);

		auto Row = [](const TArray<FString>& Cells)
		{
			return FString::Printf(TEXT("| %s |"), *FString::Join(Cells, TEXT(" | ")));
		};
		auto Cell = [](const FString& In)
		{
			// A pipe inside a value would split the row and silently move every column after it.
			FString Out = In;
			Out.ReplaceInline(TEXT("|"), TEXT("\\|"));
			Out.ReplaceInline(TEXT("\n"), TEXT(" "));

			// Leading or trailing whitespace is invisible in a rendered table, so a name
			// carrying it reads as a name that does not exist. one control-rig Blueprint genuinely
			// declares "L Leg IK Mode " with a trailing space; printed plainly, this file
			// would hand a reader a string that matches nothing. Delimit it and say so.
			if (!In.IsEmpty() && In != In.TrimStartAndEnd())
			{
				return FString::Printf(TEXT("`%s` *(surrounding whitespace)*"), *Out);
			}
			return Out.IsEmpty() ? FString(TEXT("-")) : Out;
		};

		for (const FBPRecord& R : Records)
		{
			TArray<FString> D;
			D.Add(FString::Printf(TEXT("# `%s`"), *R.Path));
			D.Add(TEXT(""));
			D.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
			D.Add(TEXT(""));
			D.Add(FString::Printf(TEXT("Parent `%s`, ultimate native parent `%s`."),
				R.Parent.IsEmpty() ? TEXT("unknown") : *R.Parent,
				R.NativeParent.IsEmpty() ? TEXT("unknown") : *R.NativeParent));
			D.Add(TEXT(""));
			D.Add(TEXT("**Every value in this file is also a field in `blueprints.jsonl`**, which is the"));
			D.Add(TEXT("same data as one line of JSON. Query that rather than parsing this."));
			D.Add(TEXT(""));

			if (R.Overrides.Num() > 0)
			{
				D.Add(TEXT("## Changed from the defaults"));
				D.Add(TEXT(""));
				D.Add(TEXT("What this Blueprint sets that its parent did not. This is where a tuning value"));
				D.Add(TEXT("lives, and for a data-only Blueprint it is the entire content."));
				D.Add(TEXT(""));
				D.Add(TEXT("| Owner | Kind | Property | Value | Was |"));
				D.Add(TEXT("|---|---|---|---|---|"));
				for (const FBPOverride& O : R.Overrides)
				{
					FString Value = O.Value;
					FString Was = O.InheritedValue;
					if (O.TruncatedFrom > 0)
					{
						// Say WHERE the shown text sits in the real value, or a window that starts
						// mid-string reads as a corrupt value.
						const FString Note = O.WindowAt > 0
							? FString::Printf(TEXT(" *(chars %d+ of %d)*"), O.WindowAt, O.TruncatedFrom)
							: FString::Printf(TEXT(" *(first 200 of %d)*"), O.TruncatedFrom);
						Value += Note;
					}
					D.Add(Row({ Cell(O.Owner.IsEmpty() ? TEXT("(class)") : O.Owner), Cell(O.OwnerKind),
						Cell(O.Property), Cell(Value), Cell(Was) }));
				}
				D.Add(TEXT(""));
			}

			if (R.Variables.Num() > 0)
			{
				D.Add(TEXT("## Variables it declares"));
				D.Add(TEXT(""));
				D.Add(TEXT("| Name | Type | Default | Category | Flags | Replication |"));
				D.Add(TEXT("|---|---|---|---|---|---|"));
				for (const FBPVariable& V : R.Variables)
				{
					FString Rep = V.Replication;
					if (!V.RepNotify.IsEmpty()) { Rep += FString::Printf(TEXT(", notify `%s`"), *V.RepNotify); }
					D.Add(Row({ Cell(V.Name), Cell(V.Type), Cell(V.Default), Cell(V.Category),
						Cell(FString::Join(V.Flags, TEXT(", "))), Cell(Rep) }));
				}
				D.Add(TEXT(""));
			}

			if (R.Components.Num() > 0)
			{
				D.Add(TEXT("## Components and widgets"));
				D.Add(TEXT(""));
				D.Add(FString::Printf(TEXT("Root: `%s`. Inherited ones are listed too, with where they come from -"),
					R.RootComponent.IsEmpty() ? TEXT("none") : *R.RootComponent));
				D.Add(TEXT("\"does this have a camera\" does not care who declared it."));
				D.Add(TEXT(""));
				D.Add(TEXT("| Name | Class | Kind | Attached to | From |"));
				D.Add(TEXT("|---|---|---|---|---|"));
				for (const FBPComponent& C : R.Components)
				{
					// An SCS node with a socket but no named parent attaches to the actor's root.
					// Rendered naively that produced a cell beginning " at `head`", which reads as
					// a truncated value rather than as a root attachment.
					FString Attach = C.AttachParent.IsEmpty() ? FString(TEXT("(root)")) : C.AttachParent;
					if (!C.AttachSocket.IsEmpty()) { Attach += FString::Printf(TEXT(" at `%s`"), *C.AttachSocket); }
					else if (C.AttachParent.IsEmpty()) { Attach.Empty(); }
					D.Add(Row({ Cell(C.Name), Cell(C.Class), Cell(C.Kind), Cell(Attach),
						Cell(C.bInherited ? (C.Source.IsEmpty() ? TEXT("inherited") : C.Source) : TEXT("declared here")) }));
				}
				D.Add(TEXT(""));
			}

			{
				D.Add(TEXT("## Tick"));
				D.Add(TEXT(""));
				if (!R.Tick.bKnown)
				{
					D.Add(TEXT("Not an Actor, so the Actor tick settings do not apply."));
				}
				else
				{
					D.Add(FString::Printf(TEXT("- Can ever tick: **%s**"), R.Tick.bCanEverTick ? TEXT("yes") : TEXT("no")));
					D.Add(FString::Printf(TEXT("- Starts with tick enabled: **%s**"), R.Tick.bStartWithTickEnabled ? TEXT("yes") : TEXT("no")));
					D.Add(FString::Printf(TEXT("- Event Tick has anything connected: **%s**"), R.Tick.bEventTickWired ? TEXT("yes") : TEXT("no")));
					if (R.Tick.bTickNodeDisabled)
					{
						D.Add(TEXT("- An `Event Tick` node exists and is **disabled**, so it is linked but never"));
						D.Add(TEXT("  compiled. That is why the line above says no."));
					}
				}
				D.Add(TEXT(""));
			}

			if (R.Functions.Num() > 0)
			{
				D.Add(TEXT("## Functions"));
				D.Add(TEXT(""));
				D.Add(TEXT("| Name | Inputs | Outputs | Pure | Const | Access |"));
				D.Add(TEXT("|---|---|---|---|---|---|"));
				for (const FBPFunction& F : R.Functions)
				{
					D.Add(Row({ Cell(F.Name), Cell(FString::Join(F.Inputs, TEXT(", "))),
						Cell(FString::Join(F.Outputs, TEXT(", "))),
						Cell(F.bPure ? TEXT("yes") : TEXT("no")), Cell(F.bConst ? TEXT("yes") : TEXT("no")),
						Cell(F.Access) }));
				}
				D.Add(TEXT(""));
			}

			if (R.Events.Num() > 0)
			{
				D.Add(TEXT("## Events"));
				D.Add(TEXT(""));
				// The engine drops unconnected BeginPlay, Tick and ActorBeginOverlap nodes into every
				// new Blueprint. Listing them under a heading called Events, with no further word,
				// reads as "this Blueprint handles Tick" - so the wiring is a column, and the ones
				// that do nothing are called out in prose above the table rather than left to it.
				D.Add(TEXT("**Connected** says whether the event's exec pin actually goes anywhere. The editor"));
				D.Add(TEXT("adds empty `ReceiveBeginPlay`, `ReceiveTick` and `ReceiveActorBeginOverlap` nodes to"));
				D.Add(TEXT("a new Blueprint, so an event listed here with **no** is a node that exists and does"));
				D.Add(TEXT("nothing - not an implementation."));
				D.Add(TEXT(""));
				D.Add(TEXT("| Name | Kind | Connected | Replication | Inputs |"));
				D.Add(TEXT("|---|---|---|---|---|"));
				for (const FBPEventNode& E : R.Events)
				{
					D.Add(Row({ Cell(E.Name), Cell(E.Kind), Cell(E.bWired ? TEXT("yes") : TEXT("no")),
						Cell(FString::Join(E.NetFlags, TEXT(", "))),
						Cell(FString::Join(E.Inputs, TEXT(", "))) }));
				}
				D.Add(TEXT(""));
			}

			if (R.Dispatchers.Num() > 0)
			{
				D.Add(TEXT("## Event dispatchers"));
				D.Add(TEXT(""));
				D.Add(TEXT("| Name | Signature |"));
				D.Add(TEXT("|---|---|"));
				for (const FBPDispatcher& Disp : R.Dispatchers)
				{
					D.Add(Row({ Cell(Disp.Name), Cell(FString::Join(Disp.Inputs, TEXT(", "))) }));
				}
				D.Add(TEXT(""));
			}

			if (R.Timelines.Num() > 0)
			{
				D.Add(TEXT("## Timelines"));
				D.Add(TEXT(""));
				D.Add(TEXT("These tick while they are playing."));
				D.Add(TEXT(""));
				D.Add(TEXT("| Name | Length |"));
				D.Add(TEXT("|---|---|"));
				for (const FBPTimeline& T : R.Timelines) { D.Add(Row({ Cell(T.Name), Cell(T.Length) })); }
				D.Add(TEXT(""));
			}

			if (R.InterfaceImpls.Num() > 0)
			{
				D.Add(TEXT("## Interfaces"));
				D.Add(TEXT(""));
				D.Add(TEXT("| Interface | Functions implemented here |"));
				D.Add(TEXT("|---|---|"));
				for (const FBPInterfaceImpl& Impl : R.InterfaceImpls)
				{
					D.Add(Row({ Cell(Impl.Name), Cell(FString::Join(Impl.Functions, TEXT(", "))) }));
				}
				D.Add(TEXT(""));
			}

			if (R.CallsOut.Num() > 0)
			{
				D.Add(TEXT("## Calls into other Blueprints"));
				D.Add(TEXT(""));
				D.Add(TEXT("No C++ tool sees these: the target is a Blueprint, so renaming the function still"));
				D.Add(TEXT("compiles and ripgrep skips `.uasset`. A `cast` is a HARD reference and is the usual"));
				D.Add(TEXT("reason loading one Blueprint loads twenty. The reverse index is `bpusers/`."));
				D.Add(TEXT(""));
				D.Add(TEXT("| Target | Member | Kind | Graph | Nodes |"));
				D.Add(TEXT("|---|---|---|---|---|"));
				for (const FBPOutEdge& E : R.CallsOut)
				{
					D.Add(Row({ Cell(FString::Printf(TEXT("`%s`"), *E.TargetPath)), Cell(E.Member),
						Cell(E.Kind), Cell(E.GraphName), Cell(FString::FromInt(E.Count)) }));
				}
				D.Add(TEXT(""));
			}

			if (R.HardDependencies.Num() > 0 || R.SoftDependencies.Num() > 0)
			{
				D.Add(TEXT("## What loading this drags in"));
				D.Add(TEXT(""));
				D.Add(FString::Printf(TEXT("**%d hard, %d soft**, from the asset registry, this project's content only."),
					R.HardDependencies.Num(), R.SoftDependencies.Num()));
				D.Add(TEXT(""));
				for (const FString& Dep : R.HardDependencies) { D.Add(FString::Printf(TEXT("- hard `%s`"), *Dep)); }
				for (const FString& Dep : R.SoftDependencies) { D.Add(FString::Printf(TEXT("- soft `%s`"), *Dep)); }
				D.Add(TEXT(""));
			}

			AgentMemoryFile::SaveStringToFileCRLF(FString::Join(D, TEXT("\n")),
				*FPaths::Combine(BpDir, R.Stem + TEXT(".md")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
		}

		UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: %d per-Blueprint detail files in bp/"), Records.Num());
	}

	{
		// ---- The registry tier. Every asset in our content, from TAGS alone, no loading. ----
		//
		// The Blueprint passes above load each asset, which is why they are slow and why they can
		// answer questions about graphs. This one answers a different question - what IS there -
		// and pays nothing for it. A DataTable's row struct, a StateTree's schema and a data
		// asset's searchable tags are all in the registry already.
		TArray<FAssetData> AllAssets;
		Registry.GetAllAssets(AllAssets);

		AllAssets.RemoveAll([&AllowedRoots](const FAssetData& D)
		{
			const FString Package = D.PackageName.ToString();
			for (const FString& Root : AllowedRoots)
			{
				if (Package.StartsWith(Root)) { return false; }
			}
			return true;
		});
		// Sort on (package, asset name), not package alone. UE's Sort is introsort and NOT stable,
		// so equal keys come out in an unspecified order - and a package CAN hold several assets:
		// one StateTree task asset holds the Blueprint, its generated class and the CDO. Package-only
		// was not a total order, those three permuted between runs, and assets.jsonl stopped being
		// byte-identical. Same package that collapsed three database rows into one an hour earlier;
		// "one asset per package" is wrong in every direction it is assumed.
		AllAssets.Sort([](const FAssetData& A, const FAssetData& B)
		{
			if (A.PackageName != B.PackageName) { return A.PackageName.LexicalLess(B.PackageName); }
			return A.AssetName.LexicalLess(B.AssetName);
		});

		// Class -> rows, and the same data as JSON lines.
		TMap<FString, TArray<FString>> AssetsByClass;
		TArray<FString> AssetJson;
		AssetJson.Reserve(AllAssets.Num());

		for (const FAssetData& Data : AllAssets)
		{
			const FString ClassName = Data.AssetClassPath.GetAssetName().ToString();
			const FString Package = Data.PackageName.ToString();

			// The tags worth naming per kind. RowStructure is what makes a DataTable answerable
			// without opening it; Schema does the same for a StateTree.
			FString Detail;
			const FString RowStruct = Tag(Data, FName(TEXT("RowStructure")));
			const FString Schema = Tag(Data, FName(TEXT("Schema")));
			if (!RowStruct.IsEmpty()) { Detail = FString::Printf(TEXT("row struct `%s`"), *TidyClassPath(RowStruct)); }
			else if (!Schema.IsEmpty()) { Detail = FString::Printf(TEXT("schema `%s`"), *TidyClassPath(Schema)); }

			AssetsByClass.FindOrAdd(ClassName).Add(FString::Printf(TEXT("| `%s` | %s |"),
				*Package, Detail.IsEmpty() ? TEXT("-") : *Detail));

			TArray<FString> G;
			G.Add(FString::Printf(TEXT("\"path\":%s"), *JsonStr(Package)));
			G.Add(FString::Printf(TEXT("\"name\":%s"), *JsonStr(Data.AssetName.ToString())));
			G.Add(FString::Printf(TEXT("\"class\":%s"), *JsonStr(ClassName)));
			G.Add(FString::Printf(TEXT("\"row_struct\":%s"), *JsonStr(TidyClassPath(RowStruct))));
			G.Add(FString::Printf(TEXT("\"schema\":%s"), *JsonStr(TidyClassPath(Schema))));
			AssetJson.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
		}

		{
			FString Payload = FString::Join(AssetJson, TEXT("\n"));
			if (AssetJson.Num() > 0) { Payload += TEXT("\n"); }
			AgentMemoryFile::SaveStringToFileCRLF(Payload,
				*FPaths::Combine(OutDir, TEXT("assets.jsonl")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
		}

		TArray<FString> Classes;
		AssetsByClass.GetKeys(Classes);
		Classes.Sort();

		const FString AssetDir = FPaths::Combine(OutDir, TEXT("assets"));
		IFileManager::Get().MakeDirectory(*AssetDir, true);

		TArray<FString> Index;
		Index.Add(TEXT("# Asset index"));
		Index.Add(TEXT(""));
		Index.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
		Index.Add(TEXT(""));
		Index.Add(TEXT("Every asset in this project's **enabled** content, from asset registry tags alone -"));
		Index.Add(TEXT("**nothing here required loading an asset**. Engine content is excluded; it is not"));
		Index.Add(TEXT("ours to describe and would swamp the table."));
		Index.Add(TEXT(""));
		{
			// A disabled plugin's content is never mounted, so the registry holds nothing for it and
			// this file cannot see it. On a sample game that is GreenRoom and RedRoom, and the gap is exactly
			// as large as the count is short against the files on disk. Saying so costs two lines;
			// not saying so makes an absence read as completeness, which is the failure this whole
			// stack is built to avoid.
			TArray<FString> Disabled;
			for (const TSharedRef<IPlugin>& Plugin : IPluginManager::Get().GetDiscoveredPlugins())
			{
				const EPluginType Type = Plugin->GetType();
				if (Type == EPluginType::Engine || Type == EPluginType::Enterprise) { continue; }
				if (!Plugin->IsEnabled()) { Disabled.AddUnique(Plugin->GetName()); }
			}
			Disabled.Sort();
			if (Disabled.Num() > 0)
			{
				Index.Add(FString::Printf(
					TEXT("**Not covered: %d disabled plugin(s)** - %s. Their content is never mounted, so"),
					Disabled.Num(), *FString::Join(Disabled, TEXT(", "))));
				Index.Add(TEXT("the asset registry holds nothing for them and neither does this file. Absence"));
				Index.Add(TEXT("here means \"not in enabled content\", not \"does not exist on disk\"."));
				Index.Add(TEXT(""));
			}
		}
		Index.Add(TEXT("**This file is an index.** One row per asset class, with the assets under it in"));
		Index.Add(TEXT("`assets/<Class>.md`. Grep this table for the class you want and read that one file."));
		Index.Add(TEXT(""));
		Index.Add(FString::Printf(TEXT("**%d assets in %d classes.**"), AllAssets.Num(), Classes.Num()));
		Index.Add(TEXT(""));
		Index.Add(TEXT("| Asset class | Count | Detail |"));
		Index.Add(TEXT("|---|---|---|"));

		for (const FString& ClassName : Classes)
		{
			const TArray<FString>& Rows = AssetsByClass[ClassName];
			FString Stem = ClassName;
			Stem.ReplaceInline(TEXT("/"), TEXT("-"));

			TArray<FString> Doc;
			Doc.Add(FString::Printf(TEXT("# `%s` assets"), *ClassName));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
			Doc.Add(TEXT(""));
			Doc.Add(FString::Printf(TEXT("**Complete for `%s` in this project's own content.** %d asset(s),"), *ClassName, Rows.Num()));
			Doc.Add(TEXT("from registry tags with no asset loading. An empty *Detail* means the registry"));
			Doc.Add(TEXT("carries no row struct or schema tag for this class, not that the asset has none."));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("| Asset | Detail |"));
			Doc.Add(TEXT("|---|---|"));
			Doc.Append(Rows);
			Doc.Add(TEXT(""));

			AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")),
				*FPaths::Combine(AssetDir, Stem + TEXT(".md")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

			Index.Add(FString::Printf(TEXT("| `%s` | %d | [%s](assets/%s.md) |"),
				*ClassName, Rows.Num(), *Stem, *Stem));
		}

		Index.Add(TEXT(""));
		AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Index, TEXT("\n")),
			*FPaths::Combine(OutDir, TEXT("Assets.md")),
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

		UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: registry tier - %d assets in %d classes"),
			AllAssets.Num(), Classes.Num());
	}

	{
		// bpusers/ - the reverse index for Blueprint-to-Blueprint edges. A sibling of bpcallers/
		// and deliberately NOT part of it: that directory answers "which Blueprints use this C++
		// symbol" and answer keys can count its rows. This one answers "which Blueprints break
		// if I change this BLUEPRINT's function", which nothing in the stack could answer before.
		TMap<FString, TArray<FBPOutEdge>> ByTarget;
		TMap<FString, FString> CallerOf;   // a row's identity is (caller, edge), so carry the caller
		TMap<FString, FString> StemOfTarget;
		for (const FBPRecord& Rec : Records)
		{
			for (const FBPOutEdge& E : Rec.CallsOut)
			{
				FBPOutEdge Row = E;
				// Reuse GraphName's slot pairing by keeping the caller beside it in a parallel key.
				ByTarget.FindOrAdd(E.TargetPath).Add(Row);
				CallerOf.FindOrAdd(E.TargetPath + TEXT("|") + Rec.Path) = Rec.Path;
				StemOfTarget.FindOrAdd(E.TargetPath) = E.TargetStem;
			}
		}

		{
			// Created even when empty, and that is load-bearing rather than tidy. An EMPTY
			// directory means "this build covers this tier and found nothing"; an ABSENT one means
			// "this set predates the tier". A reader needs those separated, and a missing directory
			// and an empty one are indistinguishable to a file count - one sample project has genuinely
			// zero Blueprint-to-Blueprint edges and was reporting the same "0" that a set written
			// before this walk existed would have reported.
			const FString UsersDir = FPaths::Combine(OutDir, TEXT("bpusers"));
			IFileManager::Get().MakeDirectory(*UsersDir, true);

			TArray<FString> Targets;
			ByTarget.GetKeys(Targets);
			Targets.Sort();

			for (const FString& Target : Targets)
			{
				TArray<FString> Rows;
				for (const FBPRecord& Rec : Records)
				{
					for (const FBPOutEdge& E : Rec.CallsOut)
					{
						if (E.TargetPath != Target) { continue; }
						Rows.Add(FString::Printf(TEXT("| `%s` | `%s` | %s | %s | %d |"),
							*Rec.Path,
							E.Member.IsEmpty() ? TEXT("-") : *E.Member,
							*E.Kind, *E.GraphName, E.Count));
					}
				}
				Rows.Sort();

				TArray<FString> Doc;
				Doc.Add(FString::Printf(TEXT("# Blueprints that use `%s`"), *Target));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("**Blueprint-to-Blueprint only.** A call from one Blueprint graph into another"));
				Doc.Add(TEXT("Blueprint's function, or a `Cast To` that makes this asset a HARD dependency of"));
				Doc.Add(TEXT("the caller. No C++ tool sees either: renaming the function still compiles, and"));
				Doc.Add(TEXT("ripgrep skips `.uasset` silently."));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("**This is not `bpcallers/`.** That directory answers the other question - which"));
				Doc.Add(TEXT("Blueprints use a C++ symbol - and contains no row from this walk."));
				Doc.Add(TEXT(""));
				Doc.Add(TEXT("| Caller | Member | Kind | Graph | Nodes |"));
				Doc.Add(TEXT("|---|---|---|---|---|"));
				Doc.Append(Rows);
				Doc.Add(TEXT(""));

				const FString Stem = StemOfTarget.FindRef(Target);
				AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")),
					*FPaths::Combine(UsersDir, Stem + TEXT(".md")),
					FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
			}

			UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: %d Blueprint-to-Blueprint targets in bpusers/"),
				ByTarget.Num());
		}
	}

	{
		// The sidecar. One Blueprint per line, no trailing newline difference between platforms:
		// joined with \n and saved without a BOM, because CRLF once made 163 of 169 committed
		// files look changed when nothing had.
		TArray<FString> JsonLines;
		JsonLines.Reserve(Records.Num());
		for (const FBPRecord& Rec : Records) { JsonLines.Add(RecordToJsonLine(Rec)); }
		FString Payload = FString::Join(JsonLines, TEXT("\n"));
		if (JsonLines.Num() > 0) { Payload += TEXT("\n"); }
		AgentMemoryFile::SaveStringToFileCRLF(Payload,
			*FPaths::Combine(OutDir, TEXT("blueprints.jsonl")),
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}

	Lines.Add(TEXT(""));
	AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Lines, TEXT("\n")),
		*FPaths::Combine(OutDir, TEXT("Blueprints.md")),
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

	// The reverse index. Keyed by the C++ symbol, because the question is always asked from that
	// direction: I am about to change this function, what breaks.
	Edges.Sort();

	TArray<FString> Rev;
	Rev.Add(TEXT("# C++ symbols used from Blueprint graphs"));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("**This is the blast radius index.** Every row is a use of a C++ function or property from"));
	Rev.Add(TEXT("inside a Blueprint graph, resolved through the node's member reference rather than matched"));
	Rev.Add(TEXT("by name. No C++ tool can produce these: clangd cannot see .uasset files, ripgrep skips them"));
	Rev.Add(TEXT("silently, and renaming a symbol listed here still compiles."));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("**Covers:** function calls (`call`), property reads (`read`) and property writes (`write`)"));
	Rev.Add(TEXT("from every event graph, function graph and macro graph of every Blueprint under /Game and"));
	Rev.Add(TEXT("the project's plugins, plus `bind`: a C++ `BindWidget` or `BindWidgetAnim` property bound by"));
	Rev.Add(TEXT("name to a widget or animation in a Widget Blueprint's designer tree, which the widget compiler"));
	Rev.Add(TEXT("enforces and no graph node records. Stated explicitly because an index with no rows of a"));
	Rev.Add(TEXT("given kind is otherwise indistinguishable from an index that does not cover that kind, and a"));
	Rev.Add(TEXT("reader who assumes the latter will go and grep binaries."));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("**Does not cover:** component templates and variable or pin *types* that name a C++ class,"));
	Rev.Add(TEXT("default values, and anything outside a Blueprint asset (materials, Niagara, data tables)."));
	Rev.Add(TEXT("Those are uses of a class, not of a member, and `blueprints/<Parent>.md` is where a class's"));
	Rev.Add(TEXT("Blueprint children and component counts live."));
	Rev.Add(TEXT(""));
	{
		TSet<FString> WithEdges;
		for (const FBPEdge& E : Edges) { WithEdges.Add(E.BlueprintPath); }
		// One line, fixed wording: engine-api/build_api_db.py parses it into bp_walk, so the
		// absence note the MCP server attaches to an empty blast-radius result is this fact and not a
		// hardcoded total.
		// The same four numbers as data. The Markdown line stays exactly as it is - it is the
		// committed answer and a benchmark key reads it - and this is a second output of the same
		// counters, not a second derivation of them.
		{
			const FString WalkJson = FString::Printf(
				TEXT("{\"total\":%d,\"data_only\":%d,\"walked\":%d,\"with_edges\":%d}\n"),
				NumBlueprints, NumDataOnly, NumWalked, WithEdges.Num());
			AgentMemoryFile::SaveStringToFileCRLF(WalkJson,
				*FPaths::Combine(OutDir, TEXT("bpwalk.json")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
		}

		Rev.Add(FString::Printf(TEXT("**Walk coverage:** %d Blueprints, %d data-only, %d walked, %d with edges."),
			NumBlueprints, NumDataOnly, NumWalked, WithEdges.Num()));
		Rev.Add(TEXT("Data-only Blueprints have no graphs by construction and cannot produce an edge; they are not"));
		Rev.Add(TEXT("a gap in the walk. Every Blueprint that could be loaded was walked, so within what this file"));
		Rev.Add(TEXT("covers, absence is exact."));
		Rev.Add(TEXT(""));
	}
	Rev.Add(TEXT("A symbol absent from this table has no Blueprint users of the kinds covered above. That is a"));
	Rev.Add(TEXT("real answer to the negation form of the question, not an absence of evidence, and it is just"));
	Rev.Add(TEXT("as useful as a hit."));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("**This file is an index.** One row per owning C++ class, with its uses in"));
	Rev.Add(TEXT("`bpcallers/<Class>.md`. Grep this table for the class you are about to change and read"));
	Rev.Add(TEXT("that one file. A class absent from this table has no Blueprint users at all."));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("**Rows are classes, not members.** Grepping here for a function or property name finds"));
	Rev.Add(TEXT("nothing even when that member has Blueprint users. Go by the owning class, or straight to"));
	Rev.Add(TEXT("`bpcallers/<Class>.md`, which lists every member of that class with its users."));
	Rev.Add(TEXT(""));
	Rev.Add(TEXT("| Owning C++ class | Uses | Detail |"));
	Rev.Add(TEXT("|---|---|---|"));

	// Owning C++ class -> its rows. Grouped rather than listed flat, because the question is
	// always "I am about to change this class", never "show me every edge in the project".
	TMap<FString, TArray<FString>> ByOwner;
	TArray<FString> EdgeJson;

	// Collapse identical rows. Two call nodes to the same function in the same graph are two
	// uses, not two facts, and printing the row twice reads as a duplicate rather than a count.
	for (int32 i = 0; i < Edges.Num(); )
	{
		int32 j = i + 1;
		while (j < Edges.Num()
			&& Edges[j].Symbol == Edges[i].Symbol
			&& Edges[j].BlueprintPath == Edges[i].BlueprintPath
			&& Edges[j].GraphName == Edges[i].GraphName
			&& Edges[j].Kind == Edges[i].Kind)
		{
			++j;
		}
		const int32 Count = j - i;
		ByOwner.FindOrAdd(OwnerOf(Edges[i].Symbol)).Add(
			FString::Printf(TEXT("| `%s` | `%s` | %s | %s%s |"),
				*Edges[i].Symbol, *Edges[i].BlueprintPath, *Edges[i].GraphName, *Edges[i].Kind,
				Count > 1 ? *FString::Printf(TEXT(" x%d"), Count) : TEXT("")));

		// The same folded row as data. Written from this loop rather than from a second pass, so
		// the document and the sidecar cannot disagree about what a row IS: one fold, two outputs.
		// The database reads this instead of re-parsing the Markdown, which its own loader
		// docstring calls a second parse of a formatted document that breaks silently.
		{
			FString SymClass = Edges[i].Symbol;
			FString SymName;
			int32 Sep = INDEX_NONE;
			if (SymClass.FindLastChar(TEXT(':'), Sep) && Sep >= 1)
			{
				SymName = SymClass.RightChop(Sep + 1);
				SymClass = SymClass.Left(Sep - 1);
			}
			TArray<FString> G;
			G.Add(FString::Printf(TEXT("\"symbol_class\":%s"), *JsonStr(SymClass)));
			G.Add(FString::Printf(TEXT("\"symbol_name\":%s"), *JsonStr(SymName)));
			G.Add(FString::Printf(TEXT("\"kind\":%s"), *JsonStr(Edges[i].Kind)));
			G.Add(FString::Printf(TEXT("\"blueprint_path\":%s"), *JsonStr(Edges[i].BlueprintPath)));
			G.Add(FString::Printf(TEXT("\"graph\":%s"), *JsonStr(Edges[i].GraphName)));
			G.Add(FString::Printf(TEXT("\"uses\":%d"), Count));
			EdgeJson.Add(FString::Printf(TEXT("{%s}"), *FString::Join(G, TEXT(","))));
		}
		i = j;
	}

	{
		FString Payload = FString::Join(EdgeJson, TEXT("\n"));
		if (EdgeJson.Num() > 0) { Payload += TEXT("\n"); }
		AgentMemoryFile::SaveStringToFileCRLF(Payload,
			*FPaths::Combine(OutDir, TEXT("bpcallers.jsonl")),
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}

	{
		TArray<FString> Owners;
		ByOwner.GetKeys(Owners);
		Owners.Sort();

		const FString CallerDir = FPaths::Combine(OutDir, TEXT("bpcallers"));
		IFileManager::Get().MakeDirectory(*CallerDir, true);

		for (const FString& Owner : Owners)
		{
			const TArray<FString>& Rows = ByOwner[Owner];

			TArray<FString> Doc;
			Doc.Add(FString::Printf(TEXT("# Blueprint users of `%s`"), *Owner));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
			Doc.Add(TEXT(""));
			Doc.Add(FString::Printf(TEXT("%d use(s) from Blueprint graphs, resolved through the node's member"), Rows.Num()));
			Doc.Add(TEXT("reference rather than matched by name. Renaming or changing the signature of any"));
			Doc.Add(TEXT("symbol listed here still compiles clean, and breaks these graphs."));
			Doc.Add(TEXT(""));
			// absence has to be as trustworthy as presence, and say so. The walk
			// resolves member references on compiled graph nodes, so a symbol that is not listed
			// genuinely has no Blueprint users - it is not a search that might have missed one.
			// Without this an agent hedges on a negative, or goes off grepping .uasset binaries,
			// which is the very expensive failure mode this file exists to prevent.
			Doc.Add(TEXT("**A negative here is real.** This is a resolved graph walk, not a text search, so a"));
			Doc.Add(TEXT("symbol absent from this table has no Blueprint users of the kinds the walk covers: graph"));
			Doc.Add(TEXT("nodes (`call`, `read`, `write`) in event, function and macro graphs, and `bind`, a"));
			Doc.Add(TEXT("`BindWidget`/`BindWidgetAnim` property bound by name in a widget's designer tree. Data-only"));
			Doc.Add(TEXT("Blueprints have no graphs and cannot appear here; that is not a gap. Not covered: uses of a"));
			Doc.Add(TEXT("*class* rather than a member, such as component templates and variable types. Do not fall"));
			Doc.Add(TEXT("back to ripgrep or `strings` on a `.uasset` to double-check: neither can see these"));
			Doc.Add(TEXT("references, and both will report nothing whether or not a caller exists."));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("| C++ symbol | Used by | Graph | How |"));
			Doc.Add(TEXT("|---|---|---|---|"));
			Doc.Append(Rows);
			Doc.Add(TEXT(""));

			AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")),
				*FPaths::Combine(CallerDir, Owner + TEXT(".md")),
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

			Rev.Add(FString::Printf(TEXT("| `%s` | %d | [%s](bpcallers/%s.md) |"),
				*Owner, Rows.Num(), *Owner, *Owner));
		}
	}

	if (Edges.Num() == 0)
	{
		Rev.Add(TEXT("| *none found* | | |"));
	}
	Rev.Add(TEXT(""));

	AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Rev, TEXT("\n")),
		*FPaths::Combine(OutDir, TEXT("BlueprintCallers.md")),
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);

	if (RedactedNonString > 0)
	{
		UE_LOG(LogTemp, Display,
			TEXT("AgentMemoryDump: redaction name-matched %d propert(ies) whose value is not text, left visible"),
			RedactedNonString);
	}

	UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: %d Blueprints, %d C++ edges from graphs"),
		Assets.Num(), Edges.Num());

	return Assets.Num();
}
