#include "ModuleAvailabilityCommandlet.h"
#include "AgentMemoryFile.h"

#include "HAL/FileManager.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/CommandLine.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/DataDrivenPlatformInfoRegistry.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Interfaces/IProjectManager.h"
#include "PluginDescriptor.h"
#include "ProjectDescriptor.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

DEFINE_LOG_CATEGORY_STATIC(LogModuleAvailability, Log, All);

namespace
{
	// The default when nothing is configured: these public platforms, plus the engine's own list of
	// confidential platforms, added at run time so no console is named in source. A console only
	// appears in that list when its platform extension is installed, which is the same thing as the
	// machine being licensed for it. Console entries are DECLARED only - no SDK or console build is
	// needed - which is the whole point: IsCompiledInConfiguration evaluates the descriptor, not the
	// toolchain.
	//
	// A tree that wants an exact list sets it in its Editor ini instead, so the list is data rather
	// than a code difference between copies:
	//
	//   [/Script/UEAgentAcceleratorTools.ModuleAvailabilityCommandlet]
	//   +Platforms=Win64
	//   +Platforms=Android
	//
	// -Platforms=a,b,c on the command line overrides both.
	const TCHAR* DefaultPlatforms[] = {
		TEXT("Win64"), TEXT("Linux"), TEXT("LinuxArm64"), TEXT("Mac"),
		TEXT("IOS"), TEXT("Android")
	};

	struct FTargetKind
	{
		const TCHAR* Name;
		EBuildTargetType Type;
	};

	const FTargetKind TargetKinds[] = {
		{ TEXT("Game"),    EBuildTargetType::Game    },
		{ TEXT("Editor"),  EBuildTargetType::Editor  },
		{ TEXT("Client"),  EBuildTargetType::Client  },
		{ TEXT("Server"),  EBuildTargetType::Server  },
		{ TEXT("Program"), EBuildTargetType::Program },
	};

	FString HostTypeToString(EHostType::Type Type)
	{
		return EHostType::ToString(Type);
	}

	/** Every directory a .uplugin can live in for this tree. Mirrors what the Python scanned. */
	void GatherPluginRoots(TArray<FString>& OutRoots, const FString& ExtraRoots)
	{
		const FString EngineDir = FPaths::EngineDir();
		OutRoots.Add(EngineDir / TEXT("Plugins"));
		OutRoots.Add(EngineDir / TEXT("Platforms"));
		OutRoots.Add(EngineDir / TEXT("Source") / TEXT("Programs"));

		const FString ProjectDir = FPaths::ProjectDir();
		OutRoots.Add(ProjectDir / TEXT("Plugins"));

		// AdditionalPluginDirectories, so a shared plugin outside the project is not missed. This is
		// the same blind spot that hid the UHT exporter from UBT's own discovery.
		if (const FProjectDescriptor* Project = IProjectManager::Get().GetCurrentProject())
		{
			for (const FString& Dir : Project->GetAdditionalPluginDirectories())
			{
				OutRoots.Add(FPaths::ConvertRelativePathToFull(ProjectDir / Dir));
			}
		}

		if (!ExtraRoots.IsEmpty())
		{
			TArray<FString> Extra;
			ExtraRoots.ParseIntoArray(Extra, TEXT(";"), true);
			OutRoots.Append(Extra);
		}
	}
}

UModuleAvailabilityCommandlet::UModuleAvailabilityCommandlet()
{
	IsClient = false;
	IsServer = false;
	IsEditor = true;
	LogToConsole = true;
}

int32 UModuleAvailabilityCommandlet::Main(const FString& Params)
{
	FString OutPath;
	if (!FParse::Value(*Params, TEXT("Out="), OutPath) || OutPath.IsEmpty())
	{
		OutPath = FPaths::ProjectDir() / TEXT("Docs") / TEXT("AgentMemory") / TEXT("module-availability.json");
	}
	OutPath = FPaths::ConvertRelativePathToFull(OutPath);

	TArray<FString> Platforms;
	FString PlatformList;
	// bShouldStopOnSeparator=false, or FParse stops at the first comma and "-Platforms=a,b,c" silently
	// resolves only "a". It did exactly that until 2026-09-21, which nothing noticed because nothing had
	// passed a list: every run used the built-in default.
	if (FParse::Value(*Params, TEXT("Platforms="), PlatformList, /*bShouldStopOnSeparator=*/false) && !PlatformList.IsEmpty())
	{
		PlatformList.ParseIntoArray(Platforms, TEXT(","), true);
	}
	else if (GConfig && GConfig->GetArray(TEXT("/Script/UEAgentAcceleratorTools.ModuleAvailabilityCommandlet"),
		TEXT("Platforms"), Platforms, GEditorIni) > 0)
	{
		UE_LOG(LogModuleAvailability, Display, TEXT("Platforms from the Editor ini: %s"),
			*FString::Join(Platforms, TEXT(",")));
	}
	else
	{
		Platforms.Reset();
		for (const TCHAR* P : DefaultPlatforms)
		{
			Platforms.Add(P);
		}
		const TMap<FName, FDataDrivenPlatformInfo>& Infos = FDataDrivenPlatformInfoRegistry::GetAllPlatformInfos();
		for (const FName& Confidential : FDataDrivenPlatformInfoRegistry::GetConfidentialPlatforms())
		{
			// A group such as a console family exists for ini chaining, not as a target platform.
			const FDataDrivenPlatformInfo* Info = Infos.Find(Confidential);
			if (Info && !Info->bIsFakePlatform)
			{
				Platforms.AddUnique(Confidential.ToString());
			}
		}
	}

	FString ExtraRoots;
	FParse::Value(*Params, TEXT("Roots="), ExtraRoots);

	TArray<FString> Roots;
	GatherPluginRoots(Roots, ExtraRoots);

	// Find every descriptor under every root, de-duplicated by full path.
	TSet<FString> DescriptorPaths;
	for (const FString& Root : Roots)
	{
		if (!IFileManager::Get().DirectoryExists(*Root))
		{
			continue;
		}
		TArray<FString> Found;
		IFileManager::Get().FindFilesRecursive(Found, *Root, TEXT("*.uplugin"), true, false, false);
		for (const FString& F : Found)
		{
			DescriptorPaths.Add(FPaths::ConvertRelativePathToFull(F));
		}
	}

	UE_LOG(LogModuleAvailability, Display,
		TEXT("Found %d plugin descriptors across %d roots; resolving %d platforms x %d target types"),
		DescriptorPaths.Num(), Roots.Num(), Platforms.Num(), UE_ARRAY_COUNT(TargetKinds));

	TArray<TSharedPtr<FJsonValue>> PluginArray;
	int32 ModuleCount = 0;
	int32 RowCount = 0;
	int32 FailedCount = 0;
	TArray<TSharedPtr<FJsonValue>> Failures;

	TArray<FString> SortedPaths = DescriptorPaths.Array();
	SortedPaths.Sort();

	for (const FString& Path : SortedPaths)
	{
		FPluginDescriptor Descriptor;
		FText FailReason;
		if (!Descriptor.Load(Path, FailReason))
		{
			// Counted, never silently dropped. A strict JSON reader mishandles ~8% of these
			// descriptors, and reporting the remainder as fact is how two answer keys went wrong.
			++FailedCount;
			TSharedPtr<FJsonObject> Fail = MakeShared<FJsonObject>();
			Fail->SetStringField(TEXT("path"), Path);
			Fail->SetStringField(TEXT("error"), FailReason.ToString());
			Failures.Add(MakeShared<FJsonValueObject>(Fail));
			continue;
		}

		TSharedPtr<FJsonObject> PluginObj = MakeShared<FJsonObject>();
		PluginObj->SetStringField(TEXT("name"), FPaths::GetBaseFilename(Path));
		PluginObj->SetStringField(TEXT("descriptor_path"), Path);
		PluginObj->SetStringField(TEXT("category"), Descriptor.Category);
		PluginObj->SetStringField(TEXT("description"), Descriptor.Description);
		PluginObj->SetStringField(TEXT("version_name"), Descriptor.VersionName);
		PluginObj->SetBoolField(TEXT("enabled_by_default"),
			Descriptor.EnabledByDefault == EPluginEnabledByDefault::Enabled);
		PluginObj->SetBoolField(TEXT("explicitly_loaded"), Descriptor.bExplicitlyLoaded);
		PluginObj->SetNumberField(TEXT("module_count"), Descriptor.Modules.Num());

		TArray<TSharedPtr<FJsonValue>> ModuleArray;
		for (int32 Index = 0; Index < Descriptor.Modules.Num(); ++Index)
		{
			const FModuleDescriptor& Module = Descriptor.Modules[Index];
			++ModuleCount;

			TSharedPtr<FJsonObject> ModuleObj = MakeShared<FJsonObject>();
			ModuleObj->SetStringField(TEXT("name"), Module.Name.ToString());
			ModuleObj->SetStringField(TEXT("host_type"), HostTypeToString(Module.Type));
			ModuleObj->SetStringField(TEXT("loading_phase"),
				ELoadingPhase::ToString(Module.LoadingPhase));
			// The ordinal disambiguates the 13 plugins that declare the same module name twice with
			// different Type and different platform lists. Keying on the name alone collapsed those
			// pairs and silently dropped 585 availability rows.
			ModuleObj->SetNumberField(TEXT("ordinal"), Index);

			TArray<TSharedPtr<FJsonValue>> Rows;
			for (const FString& Platform : Platforms)
			{
				for (const FTargetKind& Kind : TargetKinds)
				{
					// THE POINT OF THIS FILE: Epic's function decides, not us.
					const bool bAvailable = Module.IsCompiledInConfiguration(
						Platform,
						EBuildConfiguration::Development,
						FString(),                 // TargetName: empty, so Game/ProgramAllowList
						                           // clauses fall through as they do for a generic
						                           // target rather than a specific one
						Kind.Type,
						/*bBuildDeveloperTools=*/ true,
						/*bBuildRequiresCookedData=*/ false);

					TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
					Row->SetStringField(TEXT("platform"), Platform);
					Row->SetStringField(TEXT("target_type"), Kind.Name);
					Row->SetBoolField(TEXT("available"), bAvailable);
					Rows.Add(MakeShared<FJsonValueObject>(Row));
					++RowCount;
				}
			}
			ModuleObj->SetArrayField(TEXT("availability"), Rows);
			ModuleArray.Add(MakeShared<FJsonValueObject>(ModuleObj));
		}
		PluginObj->SetArrayField(TEXT("modules"), ModuleArray);
		PluginArray.Add(MakeShared<FJsonValueObject>(PluginObj));
	}

	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("schema_version"), TEXT("1"));
	Root->SetStringField(TEXT("source"), TEXT("engine"));
	Root->SetStringField(TEXT("resolver"),
		TEXT("FModuleDescriptor::IsCompiledInConfiguration"));
	Root->SetStringField(TEXT("configuration"), TEXT("Development"));
	Root->SetStringField(TEXT("generated_utc"), FDateTime::UtcNow().ToIso8601());
	Root->SetNumberField(TEXT("plugins"), PluginArray.Num());
	Root->SetNumberField(TEXT("modules"), ModuleCount);
	Root->SetNumberField(TEXT("availability_rows"), RowCount);
	Root->SetNumberField(TEXT("descriptors_failed"), FailedCount);
	Root->SetArrayField(TEXT("failures"), Failures);
	Root->SetArrayField(TEXT("plugin_list"), PluginArray);

	FString Json;
	TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Json);
	FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);

	IFileManager::Get().MakeDirectory(*FPaths::GetPath(OutPath), true);
	// ForceUTF8WithoutBOM, not the default. SaveStringToFile auto-detects and will write UTF-16 the
	// moment the content needs it, and a consumer that assumes UTF-8 then fails on byte 0. This tree
	// has already lost two answer keys to an encoding assumption; the output format is not a place to
	// leave anything to detection.
	if (!AgentMemoryFile::SaveStringToFileCRLF(Json, *OutPath,
			FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		UE_LOG(LogModuleAvailability, Error, TEXT("Failed to write %s"), *OutPath);
		return 1;
	}

	UE_LOG(LogModuleAvailability, Display,
		TEXT("Wrote %s: %d plugins, %d modules, %d availability rows, %d descriptors failed to load"),
		*OutPath, PluginArray.Num(), ModuleCount, RowCount, FailedCount);
	return 0;
}
