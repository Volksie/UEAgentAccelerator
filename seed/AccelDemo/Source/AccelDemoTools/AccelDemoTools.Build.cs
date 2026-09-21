using UnrealBuildTool;

public class AccelDemoTools : ModuleRules
{
	public AccelDemoTools(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core", "CoreUObject", "Engine", "UnrealEd",
			"AccelDemo", "AccelDemoCore"
		});
		// BlueprintGraph gives us UK2Node_CallFunction and UK2Node_VariableGet, which is how the
		// seed Blueprints get real call and property nodes rather than empty graphs.
		// AssetRegistry is for AssetCreated. The reflection dump itself lives in the
		// UEAgentAccelerator plugin; this module is now only the seed generator.
		PrivateDependencyModuleNames.AddRange(new string[] {
			"NetCore", "Projects", "BlueprintGraph", "AssetRegistry"
		});
	}
}