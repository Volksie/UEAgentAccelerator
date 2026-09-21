using UnrealBuildTool;

public class AccelDemoTarget : TargetRules
{
	public AccelDemoTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.AddRange(new string[] { "AccelDemoCore", "AccelDemo" });
	}
}