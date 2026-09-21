using UnrealBuildTool;

public class UEAgentAcceleratorTools : ModuleRules
{
	public UEAgentAcceleratorTools(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// Deliberately no dependency on any game module. This plugin walks the live reflection
		// system and the asset registry, so it works on any project without knowing anything
		// about it. That is what makes it portable to the real repo.
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core", "CoreUObject", "Engine", "UnrealEd"
		});

		// BlueprintGraph gives us UK2Node_CallFunction and UK2Node_Variable, which is how the
		// Blueprint to C++ edges get resolved rather than name matched.
		PrivateDependencyModuleNames.AddRange(new string[] {
			// Json is for ModuleAvailabilityCommandlet, which writes the declared platform matrix
			// resolved by FModuleDescriptor::IsCompiledInConfiguration. The Markdown dump needed no
			// serialiser; this one emits structured data for the engine API database to read.
			"NetCore", "Projects", "BlueprintGraph", "KismetCompiler", "AssetRegistry", "Json",
			// Widget Blueprints: the designer tree and animations, for the BindWidget edges in BlueprintIndex.cpp.
			"UMG", "UMGEditor",
			// Enhanced Input, for the input tier. A mapping context holds key-to-action bindings
			// that live in no registry tag, so this is the one tier that must load its assets -
			// a project has a handful of them against thousands of assets, so it costs nothing.
			"EnhancedInput", "InputCore"
		});
	}
}
