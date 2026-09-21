#include "AgentMemoryDumpCommandlet.h"
#include "AgentMemoryFile.h"
#include "BlueprintIndex.h"

#include "Interfaces/IPluginManager.h"
#include "Interfaces/IProjectManager.h"
#include "ProjectDescriptor.h"

#include "Containers/SortedMap.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Misc/App.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Net/UnrealNetwork.h"
#include "UObject/UnrealType.h"
#include "UObject/UObjectIterator.h"

namespace
{
	/**
	 * The shape of what this commandlet writes. Bump it when a change would make an older artefact set
	 * wrong rather than merely smaller: a column that moves, a file that stops being written, a
	 * meaning that changes. Do not bump it for a new file or a new row, which an older reader ignores.
	 *
	 * It is stamped into MANIFEST.md, and the plugin's health check compares it against the number in
	 * `artefact-format.json`. Those two have to move together, and a repository check fails when they
	 * do not - because a stamp nobody compares is decoration.
	 */
	constexpr int32 kArtefactFormatVersion = 1;

	/** The version of the UEAgentAccelerator plugin that wrote these files, from its own descriptor. */
	FString PluginVersionName()
	{
		const TSharedPtr<IPlugin> Self = IPluginManager::Get().FindPlugin(TEXT("UEAgentAccelerator"));
		return Self.IsValid() ? Self->GetDescriptor().VersionName : TEXT("unknown");
	}

	/**
	 * the full signature, so a caller does not have to open the header to learn the shape.
	 *
	 * Built from the UFunction's own parameter properties rather than any text source. CPF_ReturnParm
	 * marks the return value and is not a parameter; CPF_OutParm without CPF_ReferenceParm is an
	 * out-by-value, which reads as `&` at the call site and is worth showing. Order comes from the
	 * field iterator, which is declaration order, so the output is deterministic.
	 */
	FString FunctionSignature(UFunction* Fn)
	{
		FString Ret = TEXT("void");
		TArray<FString> Params;
		for (TFieldIterator<FProperty> It(Fn); It && (It->PropertyFlags & CPF_Parm); ++It)
		{
			FString Type = It->GetCPPType();
			if (It->PropertyFlags & CPF_ReturnParm)
			{
				Ret = Type;
				continue;
			}
			if (It->PropertyFlags & CPF_ConstParm) { Type = TEXT("const ") + Type; }
			if (It->PropertyFlags & (CPF_OutParm | CPF_ReferenceParm)) { Type += TEXT("&"); }
			Params.Add(FString::Printf(TEXT("%s %s"), *Type, *It->GetName()));
		}
		return FString::Printf(TEXT("%s %s(%s)"), *Ret, *Fn->GetName(), *FString::Join(Params, TEXT(", ")));
	}

	/**
	 * which header declares this class.
	 *
	 * UHT records two keys and they answer different questions. `ModuleRelativePath` is the one worth
	 * printing - it is relative to the module root, so it survives the tree moving. `IncludePath` is
	 * what you would write in an #include. Neither carries a LINE number: no line metadata exists
	 * anywhere in the reflection data, so A6's "every member a line number" cannot come from here.
	 * See the note in the class file header for where it can come from instead.
	 */
	FString GetHeaderPath(const UField* Field)
	{
#if WITH_EDITORONLY_DATA
		if (const FString* Rel = Field->FindMetaData(TEXT("ModuleRelativePath"))) { return *Rel; }
		if (const FString* Inc = Field->FindMetaData(TEXT("IncludePath"))) { return *Inc; }
#endif
		return FString();
	}

	// UHT stores the C++ comment above a reflected member as metadata. ToolTip is the
	// cleaned form, Comment the raw one. Both are editor-only, which is fine here.
	FString GetDoc(const UField* Field)
	{
#if WITH_EDITORONLY_DATA
		if (Field)
		{
			if (const FString* Tip = Field->FindMetaData(TEXT("ToolTip")))
			{
				return Tip->TrimStartAndEnd().Replace(TEXT("\n"), TEXT(" ")).Replace(TEXT("|"), TEXT("/"));
			}
		}
#endif
		return FString();
	}

	FString GetPropDoc(const FProperty* Prop)
	{
#if WITH_EDITORONLY_DATA
		if (Prop)
		{
			if (const FString* Tip = Prop->FindMetaData(TEXT("ToolTip")))
			{
				return Tip->TrimStartAndEnd().Replace(TEXT("\n"), TEXT(" ")).Replace(TEXT("|"), TEXT("/"));
			}
		}
#endif
		return FString();
	}

	FString ModuleOf(const UClass* Class)
	{
		// Package names for native classes are /Script/<ModuleName>
		const FString Pkg = Class->GetPackage()->GetName();
		FString Left, Right;
		if (Pkg.Split(TEXT("/Script/"), &Left, &Right))
		{
			return Right;
		}
		return FString();
	}

	FString FunctionSpecifiers(const UFunction* Fn)
	{
		TArray<FString> S;
		const EFunctionFlags F = Fn->FunctionFlags;
		if (F & FUNC_BlueprintCallable)   { S.Add(TEXT("BlueprintCallable")); }
		if (F & FUNC_BlueprintPure)       { S.Add(TEXT("BlueprintPure")); }
		if (F & FUNC_BlueprintEvent)      { S.Add(TEXT("BlueprintEvent")); }
		if (F & FUNC_Native)              { S.Add(TEXT("Native")); }
		if (F & FUNC_Static)              { S.Add(TEXT("Static")); }
		if (F & FUNC_Net)                 { S.Add(TEXT("Net")); }
		if (F & FUNC_NetServer)           { S.Add(TEXT("Server")); }
		if (F & FUNC_NetClient)           { S.Add(TEXT("Client")); }
		if (F & FUNC_NetMulticast)        { S.Add(TEXT("NetMulticast")); }
		if (F & FUNC_NetReliable)         { S.Add(TEXT("Reliable")); }
		if (F & FUNC_Exec)                { S.Add(TEXT("Exec")); }
		return FString::Join(S, TEXT(", "));
	}

	FString PropertySpecifiers(const FProperty* P)
	{
		TArray<FString> S;
		const EPropertyFlags F = P->PropertyFlags;
		if (F & CPF_Edit)                 { S.Add(TEXT("EditAnywhere")); }
		if (F & CPF_EditConst)            { S.Add(TEXT("EditConst")); }
		if (F & CPF_DisableEditOnInstance){ S.Add(TEXT("EditDefaultsOnly")); }
		if (F & CPF_DisableEditOnTemplate){ S.Add(TEXT("EditInstanceOnly")); }
		// Report the specifier as written in the header rather than the raw flags:
		// BlueprintReadWrite is CPF_BlueprintVisible with CPF_BlueprintReadOnly absent,
		// and an agent reading "BlueprintVisible" alone would not infer that.
		if (F & CPF_BlueprintVisible)
		{
			S.Add((F & CPF_BlueprintReadOnly) ? TEXT("BlueprintReadOnly") : TEXT("BlueprintReadWrite"));
		}
		if (F & CPF_Net)                  { S.Add(TEXT("Replicated")); }
		if (F & CPF_RepNotify)            { S.Add(TEXT("ReplicatedUsing")); }
		if (F & CPF_Transient)            { S.Add(TEXT("Transient")); }
		if (F & CPF_Config)               { S.Add(TEXT("Config")); }
		return FString::Join(S, TEXT(", "));
	}

	const TCHAR* CondName(ELifetimeCondition C)
	{
		switch (C)
		{
		case COND_None:                 return TEXT("COND_None");
		case COND_InitialOnly:          return TEXT("COND_InitialOnly");
		case COND_OwnerOnly:            return TEXT("COND_OwnerOnly");
		case COND_SkipOwner:            return TEXT("COND_SkipOwner");
		case COND_SimulatedOnly:        return TEXT("COND_SimulatedOnly");
		case COND_AutonomousOnly:       return TEXT("COND_AutonomousOnly");
		case COND_SimulatedOrPhysics:   return TEXT("COND_SimulatedOrPhysics");
		case COND_InitialOrOwner:       return TEXT("COND_InitialOrOwner");
		case COND_Custom:               return TEXT("COND_Custom");
		case COND_ReplayOrOwner:        return TEXT("COND_ReplayOrOwner");
		case COND_ReplayOnly:           return TEXT("COND_ReplayOnly");
		case COND_SimulatedOnlyNoReplay:return TEXT("COND_SimulatedOnlyNoReplay");
		case COND_SimulatedOrPhysicsNoReplay: return TEXT("COND_SimulatedOrPhysicsNoReplay");
		case COND_SkipReplay:           return TEXT("COND_SkipReplay");
		case COND_Never:                return TEXT("COND_Never");
		default:                        return TEXT("COND_Unknown");
		}
	}
}
UAgentMemoryDumpCommandlet::UAgentMemoryDumpCommandlet()
{
	IsClient = false;
	IsServer = false;
	IsEditor = true;
	LogToConsole = true;
}

int32 UAgentMemoryDumpCommandlet::Main(const FString& Params)
{
	TArray<FString> Tokens, Switches;
	TMap<FString, FString> ParamsMap;
	ParseCommandLine(*Params, Tokens, Switches, ParamsMap);

	TArray<FString> WantedModules;

	const FString ModulesArg = ParamsMap.FindRef(TEXT("Modules"));
	if (!ModulesArg.IsEmpty())
	{
		ModulesArg.ParseIntoArray(WantedModules, TEXT(","), true);
		for (FString& M : WantedModules) { M.TrimStartAndEndInline(); }
	}
	else
	{
		// No hardcoded list: this plugin has to work on a project it knows nothing about.
		// Take the project's own modules plus the modules of every project plugin, and leave
		// engine modules out. Anyone who wants engine modules can name them with -Modules=.
		if (const FProjectDescriptor* Project = IProjectManager::Get().GetCurrentProject())
		{
			for (const FModuleDescriptor& Module : Project->Modules)
			{
				WantedModules.AddUnique(Module.Name.ToString());
			}
		}

		for (const TSharedRef<IPlugin>& Plugin : IPluginManager::Get().GetEnabledPlugins())
		{
			UE_LOG(LogTemp, Verbose, TEXT("AgentMemoryDump: plugin %s type=%d modules=%d"),
				*Plugin->GetName(), (int32)Plugin->GetType(), Plugin->GetDescriptor().Modules.Num());
			// Everything except engine plugins. Checking for EPluginType::Project alone is not
			// enough: a plugin reached through AdditionalPluginDirectories comes back as
			// External, and that is exactly how a shared plugin gets into a project.
			const EPluginType Type = Plugin->GetType();
			if (Type == EPluginType::Engine || Type == EPluginType::Enterprise)
			{
				continue;
			}
			if (Plugin->GetName() == TEXT("AgentMemory"))
			{
				continue; // don't describe ourselves
			}
			for (const FModuleDescriptor& Module : Plugin->GetDescriptor().Modules)
			{
				WantedModules.AddUnique(Module.Name.ToString());
			}
		}

		WantedModules.Sort();
	}

	if (WantedModules.Num() == 0)
	{
		UE_LOG(LogTemp, Warning, TEXT("AgentMemoryDump: no project modules found, nothing to do"));
	}

	FString OutRel = ParamsMap.FindRef(TEXT("Out"));
	if (OutRel.IsEmpty()) { OutRel = TEXT("Docs/AgentMemory"); }
	// The absolute test is not optional. FPaths::Combine concatenates and does not notice that its
	// second argument is already rooted, so an absolute -Out lands the whole dump in a folder named
	// after the drive letter underneath the project. That writes successfully, logs the usual summary
	// and exits the same way, so the only symptom is the artefacts not being where they were asked
	// for. The default and every relative path still resolve against the project.
	const FString OutDir = FPaths::IsRelative(OutRel)
		? FPaths::Combine(FPaths::ProjectDir(), OutRel)
		: OutRel;

	UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: modules=%s out=%s"), *FString::Join(WantedModules, TEXT(",")), *OutDir);

	// Collect classes per module, sorted, so the output is deterministic.
	//
	// TSortedMap rather than TMap, and that is the whole of the determinism. Classes within a module
	// were already sorted, but a TMap iterates in hash bucket order, which follows insertion order,
	// which follows TObjectIterator, which follows whatever order the packages happened to load in
	// this run. So index.md came out with the module blocks shuffled: same rows, same length, same
	// bytes, different order.
	//
	// That is worth a container change because the artefacts are meant to be committed. A file that
	// rewrites itself into a different order on every dump puts a 900-line diff in front of a reviewer
	// whenever anyone regenerates, and a real addition is invisible inside it. It also makes
	// MANIFEST.md's "every other file here is byte-identical when regenerated" claim true, which it
	// was not while this was a TMap.
	TSortedMap<FString, TArray<UClass*>> ByModule;
	for (TObjectIterator<UClass> It; It; ++It)
	{
		UClass* Class = *It;
		const FString Mod = ModuleOf(Class);
		if (Mod.IsEmpty() || !WantedModules.Contains(Mod)) { continue; }
		ByModule.FindOrAdd(Mod).Add(Class);
	}

	int32 TotalClasses = 0;

	// One file per class, plus a small index. Per module was the wrong granularity: measured on
	// a 101-class plugin, 2026-09-07: one module came to 188 KB and about 47,000 tokens, which is most of a
	// whole question budget, so an agent that loads it pays more than reading the source it
	// replaces. Per class the median is a few hundred tokens and the index tells you which one to
	// open. Smaller files also diff and merge in Perforce, which one large file per module does not.
	const FString ClassDir = FPaths::Combine(OutDir, TEXT("classes"));

	TArray<FString> Index;
	Index.Add(TEXT("# Reflection index"));
	Index.Add(TEXT(""));
	Index.Add(TEXT("Generated by the AgentMemoryDump commandlet from the live reflection system."));
	Index.Add(TEXT("Do not hand edit."));
	Index.Add(TEXT(""));
	Index.Add(TEXT("One row per reflected class. The detail is in `classes/<Class>.md`, one file each,"));
	Index.Add(TEXT("so a question about one class costs one row plus one small file rather than the whole"));
	Index.Add(TEXT("module. This index is the authority for specifiers and replication conditions: clangd"));
	Index.Add(TEXT("sees none of it, because UHT macros are stripped before it parses."));
	Index.Add(TEXT(""));
	Index.Add(TEXT("**A class absent from this table is not reflected**, which is an answer rather than a gap."));
	Index.Add(TEXT(""));
	Index.Add(TEXT("| Class | Module | Inherits | Fns | Props | Replicated | Detail |"));
	Index.Add(TEXT("|---|---|---|---|---|---|---|"));

	for (TPair<FString, TArray<UClass*>>& Pair : ByModule)
	{
		TArray<UClass*>& Classes = Pair.Value;
		Classes.Sort([](const UClass& A, const UClass& B) { return A.GetName() < B.GetName(); });

		for (UClass* Class : Classes)
		{
			++TotalClasses;

			TArray<FString> Doc;
			Doc.Add(FString::Printf(TEXT("# %s"), *Class->GetName()));
			Doc.Add(TEXT(""));
			Doc.Add(FString::Printf(TEXT("Module `%s`. Generated by the AgentMemoryDump commandlet, do not hand edit."), *Pair.Key));
			Doc.Add(TEXT(""));
			// name the header, so "where is this declared" needs no search at all.
			{
				const FString Header = GetHeaderPath(Class);
				if (!Header.IsEmpty())
				{
					Doc.Add(FString::Printf(TEXT("Declared in `%s`."), *Header));
					// Honest about what is NOT here. The reflection system records no line numbers
					// for any field, so this file can name the header and not the line. Grep the
					// header for the member name, or use engine_api_search with kind='comment',
					// which does carry <path>:<line> for every documented declaration.
					Doc.Add(TEXT("Line numbers are not available from reflection; grep that header for a member name."));
					Doc.Add(TEXT(""));
				}
			}

		// hierarchy, including engine parents
		TArray<FString> Chain;
		for (UClass* S = Class->GetSuperClass(); S; S = S->GetSuperClass())
		{
			Chain.Add(S->GetName());
		}
		if (Chain.Num() > 0)
		{
			Doc.Add(FString::Printf(TEXT("- Inherits: %s"), *FString::Join(Chain, TEXT(" -> "))));
		}

		// interfaces
		TArray<FString> Ifaces;
		for (const FImplementedInterface& I : Class->Interfaces)
		{
			if (I.Class) { Ifaces.Add(I.Class->GetName()); }
		}
		Ifaces.Sort();
		if (Ifaces.Num() > 0)
		{
			Doc.Add(FString::Printf(TEXT("- Implements: %s"), *FString::Join(Ifaces, TEXT(", "))));
		}

		// replication conditions come from the CDO at runtime, not from any header
		TMap<uint16, ELifetimeCondition> RepConds;
		// FProperty::RepIndex is only assigned once the class's replication layout
		// has been built. In a commandlet nothing triggers that, so every replicated
		// property would report RepIndex 0 and DOREPLIFETIME would assert on the
		// second registration. Build it explicitly first.
		Class->SetUpRuntimeReplicationData();
		if (UObject* CDO = Class->GetDefaultObject(false))
		{
			TArray<FLifetimeProperty> Lifetimes;
			CDO->GetLifetimeReplicatedProps(Lifetimes);
			for (const FLifetimeProperty& LP : Lifetimes)
			{
				RepConds.Add(LP.RepIndex, (ELifetimeCondition)LP.Condition);
			}
		}

		// Summary block, before the long prose. The class doc comment and the Doc columns of the
		// two tables below are what make a file large, and they sit above the facts most questions
		// actually want. Measured 2026-09-08: one class file came to 32 KB against a 1,193 byte
		// median, and two of three sessions read it whole rather than grepping, correctly, because
		// the routing rule said "read classes/<Class>.md" with no qualification. This header is
		// bounded by the number of replicated properties rather than by the size of the class, so
		// reading the first part of any artefact now answers shape and replication.
		int32 SumFns = 0, SumProps = 0;
		for (TFieldIterator<UFunction> FIt(Class, EFieldIteratorFlags::ExcludeSuper); FIt; ++FIt) { ++SumFns; }
		TArray<FProperty*> RepProps;
		for (TFieldIterator<FProperty> PIt(Class, EFieldIteratorFlags::ExcludeSuper); PIt; ++PIt)
		{
			++SumProps;
			if (PIt->PropertyFlags & CPF_Net) { RepProps.Add(*PIt); }
		}
		RepProps.Sort([](const FProperty& A, const FProperty& B) { return A.GetName() < B.GetName(); });

		// Blank line before the heading: without it the bullets above and this heading are one
		// list to a strict Markdown parser, and these files are read by people as well as agents.
		Doc.Add(TEXT(""));
		Doc.Add(TEXT("## Summary"));
		Doc.Add(TEXT(""));
		Doc.Add(FString::Printf(TEXT("%d function%s, %d propert%s, %d replicated."),
			SumFns, SumFns == 1 ? TEXT("") : TEXT("s"),
			SumProps, SumProps == 1 ? TEXT("y") : TEXT("ies"),
			RepProps.Num()));
		Doc.Add(TEXT(""));
		if (RepProps.Num() > 0)
		{
			Doc.Add(TEXT("| Replicated property | Type | Condition | OnRep |"));
			Doc.Add(TEXT("|---|---|---|---|"));
			for (FProperty* Prop : RepProps)
			{
				const ELifetimeCondition* C = RepConds.Find(Prop->RepIndex);
				FString ExtendedType;
				const FString CppType = Prop->GetCPPType(&ExtendedType);
				ExtendedType.ReplaceInline(TEXT(" ,"), TEXT(","));
				ExtendedType.ReplaceInline(TEXT(" >"), TEXT(">"));
				Doc.Add(FString::Printf(TEXT("| `%s` | `%s%s` | %s | %s |"),
					*Prop->GetName(), *CppType, *ExtendedType,
					C ? CondName(*C) : TEXT("replicated, condition not found"),
					Prop->RepNotifyFunc != NAME_None ? *Prop->RepNotifyFunc.ToString() : TEXT("-")));
			}
		}
		else
		{
			// Stated rather than omitted: "no table" and "not looked" read identically to an agent,
			// and group F of the benchmark is entirely questions whose answer is "none".
			Doc.Add(TEXT("No property declared on this class replicates."));
		}
		Doc.Add(TEXT(""));

		// The class doc comment goes below the summary. It is unbounded prose and on the largest
		// classes it is most of the file.
		const FString ClassDoc = GetDoc(Class);
		if (!ClassDoc.IsEmpty())
		{
			Doc.Add(FString::Printf(TEXT("- Doc: %s"), *ClassDoc));
			Doc.Add(TEXT(""));
		}

		// functions declared on this class only
		TArray<UFunction*> Fns;
		for (TFieldIterator<UFunction> FIt(Class, EFieldIteratorFlags::ExcludeSuper); FIt; ++FIt)
		{
			Fns.Add(*FIt);
		}
		Fns.Sort([](const UFunction& A, const UFunction& B) { return A.GetName() < B.GetName(); });
		if (Fns.Num() > 0)
		{
			Doc.Add(TEXT("### Functions"));
			Doc.Add(TEXT(""));
			// name the provenance of these specifiers. They are the EFFECTIVE flags
			// as UHT computed them, read off the live UFunction, and they legitimately differ from
			// what the header author typed - UHT adds BlueprintPure to a const BlueprintCallable
			// with a return value, and the header never says so. A benchmark question decoded
			// these correctly and then declared our documentation a bug, because nothing told it
			// which of the two sources wins.
			Doc.Add(TEXT("**Effective specifiers**, as UnrealHeaderTool computed them, read from the live"));
			Doc.Add(TEXT("`UFunction`. These can differ from the specifier list written in the header and the"));
			Doc.Add(TEXT("table is right when they do: a const `BlueprintCallable` with a return value is"));
			Doc.Add(TEXT("`BlueprintPure` here and is not marked so in the header. **This table wins over the"));
			Doc.Add(TEXT("header. A disagreement is not a defect in either.**"));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("| Function | Signature | Specifiers | Doc |"));
			Doc.Add(TEXT("|---|---|---|---|"));
			for (UFunction* Fn : Fns)
			{
				Doc.Add(FString::Printf(TEXT("| `%s` | `%s` | %s | %s |"),
					*Fn->GetName(), *FunctionSignature(Fn), *FunctionSpecifiers(Fn), *GetDoc(Fn)));
			}
			Doc.Add(TEXT(""));
		}

		// properties declared on this class only
		TArray<FProperty*> Props;
		for (TFieldIterator<FProperty> PIt(Class, EFieldIteratorFlags::ExcludeSuper); PIt; ++PIt)
		{
			Props.Add(*PIt);
		}
		Props.Sort([](const FProperty& A, const FProperty& B) { return A.GetName() < B.GetName(); });
		if (Props.Num() > 0)
		{
			Doc.Add(TEXT("### Properties"));
			Doc.Add(TEXT(""));
			Doc.Add(TEXT("| Property | Type | Specifiers | Replication | Doc |"));
			Doc.Add(TEXT("|---|---|---|---|---|"));
			for (FProperty* Prop : Props)
			{
				FString Rep;
				if (Prop->PropertyFlags & CPF_Net)
				{
					const ELifetimeCondition* C = RepConds.Find(Prop->RepIndex);
					Rep = C ? CondName(*C) : TEXT("replicated, condition not found");
					if (Prop->RepNotifyFunc != NAME_None)
					{
						Rep += FString::Printf(TEXT(", OnRep=%s"), *Prop->RepNotifyFunc.ToString());
					}
				}
				// GetCPPType() on its own returns just "TArray" / "TMap" / "TSet" and drops the
				// element types into ExtendedTypeText, so without this a container property
				// reads as "TArray" and you can't tell what it holds. Found by check_keys.py
				// comparing 128 container properties from a sample game against the headers.
				FString ExtendedType;
				const FString CppType = Prop->GetCPPType(&ExtendedType);
				// GetCPPType spaces nested templates the old way, "TMap<TObjectPtr<AActor> ,int32>".
				// Tidy it so the artefact reads the way the header does.
				ExtendedType.ReplaceInline(TEXT(" ,"), TEXT(","));
				ExtendedType.ReplaceInline(TEXT(" >"), TEXT(">"));
				Doc.Add(FString::Printf(TEXT("| `%s` | `%s%s` | %s | %s | %s |"),
					*Prop->GetName(), *CppType, *ExtendedType, *PropertySpecifiers(Prop),
					*Rep, *GetPropDoc(Prop)));
			}
			Doc.Add(TEXT(""));
		}

			const FString ClassFile = FPaths::Combine(ClassDir, Class->GetName() + TEXT(".md"));
			if (!AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Doc, TEXT("\n")) + TEXT("\n"), *ClassFile,
				FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
			{
				UE_LOG(LogTemp, Error, TEXT("AgentMemoryDump: FAILED to write %s"), *ClassFile);
				return 1;
			}

			// Index row. Counts rather than detail, so the index stays cheap to hold.
			int32 NumFns = 0, NumProps = 0, NumRep = 0;
			for (TFieldIterator<UFunction> FIt(Class, EFieldIteratorFlags::ExcludeSuper); FIt; ++FIt) { ++NumFns; }
			for (TFieldIterator<FProperty> PIt(Class, EFieldIteratorFlags::ExcludeSuper); PIt; ++PIt)
			{
				++NumProps;
				if (PIt->PropertyFlags & CPF_Net) { ++NumRep; }
			}
			const UClass* Super = Class->GetSuperClass();
			Index.Add(FString::Printf(TEXT("| `%s` | %s | `%s` | %d | %d | %d | [%s](classes/%s.md) |"),
				*Class->GetName(), *Pair.Key, Super ? *Super->GetName() : TEXT("-"),
				NumFns, NumProps, NumRep, *Class->GetName(), *Class->GetName()));
		}
	}

	Index.Add(TEXT(""));
	if (!AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Index, TEXT("\n")) + TEXT("\n"),
		*FPaths::Combine(OutDir, TEXT("index.md")),
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		UE_LOG(LogTemp, Error, TEXT("AgentMemoryDump: FAILED to write index.md"));
		return 1;
	}
	UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: wrote index.md and %d class files"), TotalClasses);

	// ---------------------------------------------------------------------------------------
	// MANIFEST.md, so staleness is visible to a reader rather than only to the Verify stage.
	//
	// One file rather than a stamp in every artefact: stamping each would make every regeneration a
	// 457-file diff, and these are committed, so the diff has to mean something.
	// Declared outside the block on purpose: the coverage table at the bottom can only be filled
	// once the Blueprint pass has run, so the rows are built here and the file is written after it.
	TArray<FString> Man;
	{
		Man.Add(TEXT("# Artefact manifest"));
		Man.Add(TEXT(""));
		Man.Add(TEXT("Generated by the AgentMemoryDump commandlet. Do not hand edit."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**What this is for.** Everything in this directory is generated, and a generated"));
		Man.Add(TEXT("file that has gone stale looks exactly like one that has not. Check this before"));
		Man.Add(TEXT("trusting an answer that turns on a recent change."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**This is the one artefact that changes on every run, deliberately.** Every other"));
		Man.Add(TEXT("file here is byte-identical when regenerated from unchanged source, which is what"));
		Man.Add(TEXT("makes them committable: a diff means the code moved. This file carries a timestamp"));
		Man.Add(TEXT("because recording *when* is its entire job, so it is excluded from that rule and"));
		Man.Add(TEXT("from the determinism check. Do not commit it expecting a clean diff."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("| Field | Value |"));
		Man.Add(TEXT("|---|---|"));
		// First two rows on purpose: they decide whether anything below them can be trusted.
		Man.Add(FString::Printf(TEXT("| Artefact format | %d |"), kArtefactFormatVersion));
		Man.Add(FString::Printf(TEXT("| Written by plugin | %s |"), *PluginVersionName()));
		Man.Add(FString::Printf(TEXT("| Engine version | %s |"), *FEngineVersion::Current().ToString()));
		Man.Add(FString::Printf(TEXT("| Engine branch | %s |"), *FEngineVersion::Current().GetBranch()));
		// This used to print `Current().GetChangelist()` alone, and on a source build
		// that is always 0 - `Build.version` here has `"Changelist": 0` beside
		// `"CompatibleChangelist": 55116800`. It read as authoritative and discriminated nothing: a
		// changelist of 0 looks identical on 5.8.3 and on whatever we upgrade to next, which is the
		// exact event either side of which these artefacts are valid or not.
		//
		// Both are printed, and the unstamped one says so. Same rule as `bpcallers/`'s absence-is-real
		// header with the sign flipped - a reader must be able to tell "changelist 0" from "no
		// changelist recorded".
		//
		// SECOND ATTEMPT. The obvious fix was FEngineVersion::CompatibleWith(), and it
		// **also returns 0 here** - ran it and looked rather than assuming. The compiled-in value
		// comes from UBT:
		//
		//     BuildVersion.cs:77
		//     EffectiveCompatibleChangelist =>
		//         (Changelist != 0 && CompatibleChangelist != 0) ? CompatibleChangelist : Changelist;
		//
		// With Changelist == 0 on a source build, that falls back to Changelist, so COMPATIBLE_CHANGELIST
		// is compiled in as 0 whatever Build.version says. The 55116800 exists **only in the JSON on
		// disk**, and no engine API path reaches it. So read the file.
		const uint32 CurrentCL = FEngineVersion::Current().GetChangelist();
		Man.Add(CurrentCL != 0
			? FString::Printf(TEXT("| Engine changelist | %u |"), CurrentCL)
			: TEXT("| Engine changelist | not stamped (source build) |"));

		FString CompatibleCLText = TEXT("unavailable");
		{
			const FString VersionFile = FPaths::Combine(FPaths::EngineDir(), TEXT("Build"), TEXT("Build.version"));
			FString VersionJson;
			if (FFileHelper::LoadFileToString(VersionJson, *VersionFile))
			{
				TSharedPtr<FJsonObject> Root;
				const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(VersionJson);
				int32 CompatibleCL = 0;
				if (FJsonSerializer::Deserialize(Reader, Root) && Root.IsValid()
					&& Root->TryGetNumberField(TEXT("CompatibleChangelist"), CompatibleCL) && CompatibleCL != 0)
				{
					CompatibleCLText = FString::Printf(TEXT("%d"), CompatibleCL);
				}
			}
		}
		Man.Add(FString::Printf(TEXT("| Engine compatible changelist | %s |"), *CompatibleCLText));
		Man.Add(FString::Printf(TEXT("| Project | %s |"), FApp::GetProjectName()));
		Man.Add(FString::Printf(TEXT("| Generated (UTC) | %s |"), *FDateTime::UtcNow().ToIso8601()));
		Man.Add(FString::Printf(TEXT("| Modules | %d |"), ByModule.Num()));
		Man.Add(FString::Printf(TEXT("| Reflected classes | %d |"), TotalClasses));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**Artefact format is the one to check after a plugin update.** It is the shape of"));
		Man.Add(TEXT("these files, not their content: when it moves, an artefact set written before the"));
		Man.Add(TEXT("move is wrong in ways that reading it will not show. `/ue-memory-stack:doctor`"));
		Man.Add(TEXT("compares it against the plugin installed here and says so. A set written before"));
		Man.Add(TEXT("this row existed carries no format at all, which is itself the answer."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**Compare engines on the compatible changelist, not the changelist.** A source"));
		Man.Add(TEXT("build never stamps the latter, so it reads 0 on every engine and tells you"));
		Man.Add(TEXT("nothing about which one produced these files."));
		Man.Add(TEXT(""));
		// A project revision was asked for and is deliberately absent. A project that is not under
		// version control has no revision to record, and a field claiming one would be inventing it.
		// The Verify stage compares artefact mtimes against source mtimes instead, which needs no
		// VCS and catches the same problem.
		Man.Add(TEXT("**No project revision.** A project that is not under version control has no"));
		Man.Add(TEXT("revision to record, and a field claiming one would be invented. Staleness is"));
		Man.Add(TEXT("checked by comparing these files' timestamps against the newest reflected source"));
		Man.Add(TEXT("file, which `scripts/Update-MemoryStack.ps1 -Stages Verify`"));
		Man.Add(TEXT("does automatically and fails on."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**No line numbers anywhere in these artefacts.** The reflection system records"));
		Man.Add(TEXT("none, for any field. `classes/<Class>.md` names the declaring header; for a line,"));
		Man.Add(TEXT("grep that header, or use `engine_api_search` with `kind='comment'`, which carries"));
		Man.Add(TEXT("`<path>:<line>` for every documented declaration."));
		Man.Add(TEXT(""));

	}

	// Blueprint pass. Reflection alone stops at C++, and the questions that hurt most are about
	// what Blueprints do with it. -NoBlueprints skips the graph walk, which is the expensive half.
	const bool bWalkGraphs = !FParse::Param(*Params, TEXT("NoBlueprintGraphs"));
	const int32 NumBlueprints = AgentMemoryBlueprintIndex::Emit(OutDir, bWalkGraphs);

	{
		// WHAT THIS SET CONTAINS, written after the Blueprint pass because that is the only moment
		// it is knowable. Read off the disk rather than off the code's intentions: if a stage failed
		// and wrote nothing, this table says so instead of describing a set that was not produced.
		//
		// This is a COVERAGE table, not a format one. The artefact format stays at 1 because
		// everything the detail dump added is a new file - nothing moved, nothing stopped being
		// written, and an older set is smaller rather than wrong. But smaller still has to be
		// legible: without these rows a reader cannot tell "this project has no Blueprint-to-
		// Blueprint edges" from "this set predates that walk", and those need different actions.
		// -1 when the DIRECTORY is absent, 0 when it exists and is empty. FindFiles cannot tell
		// those apart on its own - both come back as an empty array - and they mean opposite
		// things: an empty directory is this build saying "I cover this and found nothing", a
		// missing one is a set written before the tier existed. Reporting both as 0 is the exact
		// ambiguity this table was added to remove, and it did so until this check caught it.
		auto CountFiles = [&OutDir](const TCHAR* Dir)
		{
			const FString Path = FPaths::Combine(OutDir, Dir);
			if (!IFileManager::Get().DirectoryExists(*Path)) { return -1; }
			TArray<FString> Found;
			IFileManager::Get().FindFiles(Found, *(Path / TEXT("*.md")), true, false);
			return Found.Num();
		};
		auto Lines = [&OutDir](const TCHAR* File)
		{
			FString Text;
			if (!FFileHelper::LoadFileToString(Text, *FPaths::Combine(OutDir, File))) { return -1; }
			int32 N = 0;
			for (const TCHAR C : Text) { if (C == TEXT('\n')) { ++N; } }
			return N;
		};
		auto Row = [](const TCHAR* Name, int32 N, const TCHAR* Unit)
		{
			return N < 0
				? FString::Printf(TEXT("| %s | **not in this set** |"), Name)
				: FString::Printf(TEXT("| %s | %d %s |"), Name, N, Unit);
		};

		Man.Add(TEXT("## What this set contains"));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**\"not in this set\" means this dump did not write it, not that the project has none.**"));
		Man.Add(TEXT("An older set predating a tier reads the same as a project that genuinely has nothing"));
		Man.Add(TEXT("of that kind, and they need different actions - so the two are separated here. A count"));
		Man.Add(TEXT("of 0 is a real answer; an absent row is not."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("| Tier | Coverage |"));
		Man.Add(TEXT("|---|---|"));
		Man.Add(FString::Printf(TEXT("| Reflected classes | %d in %d module(s) |"), TotalClasses, ByModule.Num()));
		Man.Add(FString::Printf(TEXT("| Blueprints | %d |"), NumBlueprints));
		Man.Add(Row(TEXT("Blueprint detail (`bp/`)"), CountFiles(TEXT("bp")), TEXT("file(s)")));
		Man.Add(Row(TEXT("Blueprint users (`bpusers/`)"), CountFiles(TEXT("bpusers")), TEXT("file(s)")));
		Man.Add(Row(TEXT("C++ callers (`bpcallers/`)"), CountFiles(TEXT("bpcallers")), TEXT("file(s)")));
		Man.Add(Row(TEXT("Registry tier (`assets/`)"), CountFiles(TEXT("assets")), TEXT("class file(s)")));
		Man.Add(Row(TEXT("Blueprint data (`blueprints.jsonl`)"), Lines(TEXT("blueprints.jsonl")), TEXT("row(s)")));
		Man.Add(Row(TEXT("Asset data (`assets.jsonl`)"), Lines(TEXT("assets.jsonl")), TEXT("row(s)")));
		Man.Add(Row(TEXT("C++ edge data (`bpcallers.jsonl`)"), Lines(TEXT("bpcallers.jsonl")), TEXT("row(s)")));
		Man.Add(Row(TEXT("Input contexts (`input/`)"), CountFiles(TEXT("input")), TEXT("context file(s)")));
		Man.Add(Row(TEXT("Input keys (`inputkeys/`)"), CountFiles(TEXT("inputkeys")), TEXT("key file(s)")));
		Man.Add(Row(TEXT("Input data (`input.jsonl`)"), Lines(TEXT("input.jsonl")), TEXT("binding(s)")));
		Man.Add(TEXT(""));
		Man.Add(TEXT("The `.jsonl` files are the same data as the Markdown beside them, written from one"));
		Man.Add(TEXT("in-memory model rather than parsed back out of the documents. Query those; read the"));
		Man.Add(TEXT("Markdown. Each line of `blueprints.jsonl` carries a `sections` list naming what that"));
		Man.Add(TEXT("build populates, so an empty list is distinguishable from an unreported one."));
		Man.Add(TEXT(""));
		Man.Add(TEXT("**Registry coverage is ENABLED content only.** A disabled plugin never mounts, so the"));
		Man.Add(TEXT("asset registry holds nothing for it and neither does this set. `Assets.md` names any"));
		Man.Add(TEXT("that were skipped."));
		Man.Add(TEXT(""));

		if (!AgentMemoryFile::SaveStringToFileCRLF(FString::Join(Man, TEXT("\n")) + TEXT("\n"),
			*FPaths::Combine(OutDir, TEXT("MANIFEST.md")),
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
		{
			UE_LOG(LogTemp, Error, TEXT("AgentMemoryDump: FAILED to write MANIFEST.md"));
			return 1;
		}
	}

	UE_LOG(LogTemp, Display, TEXT("AgentMemoryDump: done, %d modules, %d classes, %d blueprints"),
		ByModule.Num(), TotalClasses, NumBlueprints);
	return 0;
}