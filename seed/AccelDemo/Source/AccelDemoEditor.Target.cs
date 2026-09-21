using UnrealBuildTool;

public class AccelDemoEditorTarget : TargetRules
{
	public AccelDemoEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.AddRange(new string[] { "AccelDemoCore", "AccelDemo", "AccelDemoTools" });
	}
}