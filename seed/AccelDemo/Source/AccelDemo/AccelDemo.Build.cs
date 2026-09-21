using UnrealBuildTool;

public class AccelDemo : ModuleRules
{
	public AccelDemo(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "AccelDemoCore" });
		PrivateDependencyModuleNames.AddRange(new string[] { "NetCore" });
	}
}