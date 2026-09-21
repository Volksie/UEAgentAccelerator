// Engine API database, Layer 2b. UHT exporter for the "uht" fidelity tier.
//
// Why this exists rather than the exporter Unreal ships:
//
//   UhtJsonExporter hands System.Text.Json the live UhtModule graph and serialises Epic's internal
//   types directly. That graph is cyclic by construction - types carry an EngineClass back-reference
//   and functions are a Next-linked list - so it throws
//       "A possible object cycle was detected ... maximum allowed depth of 64"
//   on every module and writes nothing. Measured 2026-09-09 on a small editor target. It ships
//   UhtExporterOptions.None, so it is off by default and nothing in CI exercises it.
//
//   This exporter walks the graph and emits a FLAT PROJECTION instead of handing the graph to a
//   serialiser. Cycles cannot arise, because nothing here follows a back-reference: every cross-type
//   link is written as a name, and the merge step resolves names to ids.
//
// Why it lives here rather than in the engine:
//
//   We treat the engine tree as read only. UhtTables.AddPlugins loads exporters
//   from external assemblies, and UEBuildTarget.cs:6050-6090 walks every ENABLED plugin's directory
//   for *.ubtplugin.csproj, compiles it, and registers it with UHT if it carries [UnrealHeaderTool].
//   UEAgentAccelerator is our own plugin, enabled by the projects that use it, so this rides the per-target build
//   UHT already runs - which is the argument for this tier: you cannot build for a console
//   without running UHT over that console's modules.
//
// Enable with -AgentMemoryApi on the UHT command line, or [UnrealHeaderTool] AgentMemoryApi=true.
// Options = None, so it never runs as part of an ordinary build unless asked for.
//
// What this tier CANNOT produce, and must not pretend to: COND_* replication conditions. They live
// in GetLifetimeReplicatedProps at runtime and appear in no header. UHT sees Replicated and
// ReplicatedUsing only. rep_condition stays null here and is written by the runtime commandlet -
// the rule that absence and ignorance must not look the same.

using System;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Text;
using System.Threading.Tasks;
using EpicGames.UHT.Tables;
using EpicGames.UHT.Types;
using EpicGames.UHT.Utils;

namespace UEAgentAcceleratorUhtPlugin
{
	[UnrealHeaderTool]
	internal sealed class UEAgentAcceleratorUhtExporter
	{
		private const string SchemaVersion = "1";

		// ModuleName is MANDATORY for an exporter that lives in a UBT plugin
		// (UhtExporterTable.cs:230, "An exporter in a UBT plugin must specify a ModuleName") and must
		// name a module present in THAT TARGET'S manifest, or UHT skips the exporter with only a log
		// line and still reports Result: Succeeded.
		//
		// It was UEAgentAcceleratorTools, this plugin's own module. That looked right - it tied the
		// exporter to the plugin being enabled - and it silently produced NOTHING for Game targets,
		// because that module is Type: Editor and a Game target's manifest does not contain it.
		// Measured 2026-09-09 on a sample game: its Editor target has 707 modules with this module
		// present; its Client and Server targets have 317 and 312, absent from both. **A console
		// target is a Game target**, so every console target
		// would have exported nothing while reporting success - precisely the case this tier exists
		// for, and it would have looked like the console simply had no API surface.
		//
		// CoreUObject is in every target type's manifest measured here, Program targets included. The
		// plugin-enabled gate is not lost by moving to it: UBT only compiles and registers a
		// *.ubtplugin.csproj found under an ENABLED plugin, so with the plugin off the exporter is
		// never registered at all. ModuleName was a second, redundant gate that happened to be the
		// wrong shape.
		[UhtExporter(Name = "AgentMemoryApi", Description = "Flat API projection for the engine API database (Layer 2b)",
			Options = UhtExporterOptions.None, ModuleName = "CoreUObject")]
		[SuppressMessage("CodeQuality", "IDE0051:Remove unused private members", Justification = "Attribute accessed method")]
		private static void Export(IUhtExportFactory factory)
		{
			// The tasks MUST be awaited. Creating them and returning lets the session tear down
			// first: measured 2026-09-09, that produced "1 requested writes" for 587 modules and no
			// output files, with no error anywhere - the run reported Succeeded. The shipped
			// exporter collects and WaitAll's for this reason.
			List<Task> tasks = new(64);
			foreach (UhtModule module in factory.Session.Modules)
			{
				UhtModule captured = module;
				Task? task = factory.CreateTask(taskFactory =>
				{
					StringBuilder builder = new();
					WriteModule(taskFactory, captured, builder);
					// The TARGET is part of the filename, not just the content. Every target writes
					// into the same directory (MakePath uses the exporter module's output dir), so a
					// plain ".agentapi.json" means the second target silently overwrites the first
					// for every shared module - and Engine is shared by all of them. That would make
					// "observed on a console as well as Win64" unrepresentable, which is the entire point
					// of the console tier. Found 2026-09-09 before any console build existed.
					string target = taskFactory.Session.Manifest?.TargetName ?? "UnknownTarget";
					taskFactory.CommitOutput(
						taskFactory.MakePath(captured, $".{target}.agentapi.json"), builder);
				});
				if (task != null)
				{
					tasks.Add(task);
				}
			}
			Task.WaitAll([.. tasks]);
		}

		// ---------------------------------------------------------------------------------------
		// Writing. Hand-rolled rather than System.Text.Json: the values are all strings, ints and
		// bools, the shape is fixed, and it keeps the plugin free of serialiser configuration that
		// could reintroduce the cycle problem this exporter exists to avoid.
		// ---------------------------------------------------------------------------------------

		private static void WriteModule(IUhtExportFactory factory, UhtModule module, StringBuilder sb)
		{
			sb.Append("{\n");
			Field(sb, 1, "schema_version", SchemaVersion, true);
			Field(sb, 1, "source", "uht", true);
			Field(sb, 1, "module", module.ShortName, true);
			Field(sb, 1, "module_type", module.Module.ModuleType.ToString(), true);
			// Target provenance. Without it the merge cannot tell a Win64 observation from a console one,
			// and the merge step's `targets` column has nothing to fill it from.
			Field(sb, 1, "target", factory.Session.Manifest?.TargetName ?? "", true);
			Field(sb, 1, "is_game_target", factory.Session.Manifest?.IsGameTarget == true ? "true" : "false", true);
			Field(sb, 1, "base_directory", module.Module.BaseDirectory, true);

			sb.Append("  \"classes\": [\n");
			bool first = true;
			foreach (UhtPackage package in module.Packages)
			{
				CollectClasses(package, sb, ref first);
			}
			sb.Append("\n  ],\n");

			sb.Append("  \"structs\": [\n");
			first = true;
			foreach (UhtPackage package in module.Packages)
			{
				CollectStructs(package, sb, ref first);
			}
			sb.Append("\n  ],\n");

			sb.Append("  \"enums\": [\n");
			first = true;
			foreach (UhtPackage package in module.Packages)
			{
				CollectEnums(package, sb, ref first);
			}
			sb.Append("\n  ]\n}\n");
		}

		private static void CollectClasses(UhtType type, StringBuilder sb, ref bool first)
		{
			if (type is UhtClass cls)
			{
				if (!first)
				{
					sb.Append(",\n");
				}
				first = false;
				WriteClass(cls, sb);
			}
			foreach (UhtType child in type.Children)
			{
				CollectClasses(child, sb, ref first);
			}
		}

		private static void CollectStructs(UhtType type, StringBuilder sb, ref bool first)
		{
			if (type is UhtScriptStruct st)
			{
				if (!first)
				{
					sb.Append(",\n");
				}
				first = false;
				sb.Append("    {");
				InlineField(sb, "name", st.SourceName, true);
				InlineField(sb, "engine_name", st.EngineName, true);
				InlineField(sb, "header", HeaderPath(st), true);
				InlineField(sb, "doc", ToolTip(st), false);
				sb.Append('}');
			}
			foreach (UhtType child in type.Children)
			{
				CollectStructs(child, sb, ref first);
			}
		}

		private static void CollectEnums(UhtType type, StringBuilder sb, ref bool first)
		{
			if (type is UhtEnum en)
			{
				if (!first)
				{
					sb.Append(",\n");
				}
				first = false;
				sb.Append("    {");
				InlineField(sb, "name", en.SourceName, true);
				InlineField(sb, "header", HeaderPath(en), true);
				InlineField(sb, "doc", ToolTip(en), true);
				sb.Append("\"values\": [");
				bool firstValue = true;
				foreach (UhtEnumValue value in en.EnumValues)
				{
					if (!firstValue)
					{
						sb.Append(", ");
					}
					firstValue = false;
					sb.Append('{');
					InlineField(sb, "name", value.Name, true);
					sb.Append("\"value\": ").Append(value.Value);
					sb.Append('}');
				}
				sb.Append("]}");
			}
			foreach (UhtType child in type.Children)
			{
				CollectEnums(child, sb, ref first);
			}
		}

		private static void WriteClass(UhtClass cls, StringBuilder sb)
		{
			sb.Append("    {\n");
			Field(sb, 3, "name", cls.SourceName, true);
			Field(sb, 3, "engine_name", cls.EngineName, true);
			// Super is written as a NAME, never as a nested object. This is the whole reason the
			// shipped exporter fails: following the reference is what creates the cycle.
			Field(sb, 3, "super", cls.SuperClass?.SourceName ?? "", true);
			Field(sb, 3, "class_type", cls.ClassType.ToString(), true);
			Field(sb, 3, "header", HeaderPath(cls), true);
			sb.Append("      \"class_flags\": ").Append((ulong)cls.ClassFlags).Append(",\n");
			sb.Append("      \"is_deprecated\": ").Append(cls.Deprecated ? "true" : "false").Append(",\n");
			Field(sb, 3, "deprecation_message", DeprecationMessage(cls), true);
			// Decoded flag names alongside the raw integer, storing both. NOTE these
			// are FLAG names, not the specifiers the header author typed. UHT resolves some
			// specifiers into flag combinations - BlueprintReadWrite is CPF_BlueprintVisible with
			// CPF_BlueprintReadOnly absent - so a property reads "BlueprintVisible" here and never
			// "BlueprintReadWrite". For author-written specifiers the Layer 2 reflection artefacts
			// remain the authority; this is the machine truth sitting beside them, not a replacement.
			Field(sb, 3, "class_flag_names", cls.ClassFlags.ToString(), true);
			Field(sb, 3, "doc", ToolTip(cls), true);

			sb.Append("      \"interfaces\": [");
			bool firstIface = true;
			foreach (UhtStruct baseType in cls.Bases)
			{
				// Both UhtClassType.Interface (the UINTERFACE, e.g. UMBInteractable) and
				// UhtClassType.NativeInterface (the I-prefixed companion actually listed in the base
				// list, e.g. IMBInteractable) count. Filtering on Interface alone reported an empty
				// interface list for every implementing class - caught 2026-09-09 on AMBCharacter,
				// which implements IMBInteractable.
				if (baseType is UhtClass baseClass &&
					(baseClass.ClassType == UhtClassType.Interface ||
					 baseClass.ClassType == UhtClassType.NativeInterface))
				{
					if (!firstIface)
					{
						sb.Append(", ");
					}
					firstIface = false;
					sb.Append('"').Append(Escape(baseClass.SourceName)).Append('"');
				}
			}
			sb.Append("],\n");

			sb.Append("      \"functions\": [\n");
			bool firstFn = true;
			foreach (UhtType child in cls.Children)
			{
				if (child is UhtFunction fn)
				{
					if (!firstFn)
					{
						sb.Append(",\n");
					}
					firstFn = false;
					WriteFunction(fn, sb);
				}
			}
			sb.Append("\n      ],\n");

			sb.Append("      \"properties\": [\n");
			bool firstProp = true;
			foreach (UhtType child in cls.Children)
			{
				if (child is UhtProperty prop)
				{
					if (!firstProp)
					{
						sb.Append(",\n");
					}
					firstProp = false;
					WriteProperty(prop, sb);
				}
			}
			sb.Append("\n      ]\n    }");
		}

		private static void WriteFunction(UhtFunction fn, StringBuilder sb)
		{
			sb.Append("        {");
			InlineField(sb, "name", fn.SourceName, true);
			InlineField(sb, "function_type", fn.FunctionType.ToString(), true);
			sb.Append("\"function_flags\": ").Append((ulong)fn.FunctionFlags).Append(", ");
			InlineField(sb, "specifiers", fn.FunctionFlags.ToString(), true);
			sb.Append("\"is_deprecated\": ").Append(fn.Deprecated ? "true" : "false").Append(", ");
			InlineField(sb, "deprecation_message", DeprecationMessage(fn), true);
			InlineField(sb, "doc", ToolTip(fn), true);
			// Signatures: parameters in order, return last.
			sb.Append("\"params\": [");
			bool firstParam = true;
			int ordinal = 0;
			foreach (UhtType param in fn.ParameterProperties.Span)
			{
				if (param is not UhtProperty p)
				{
					continue;
				}
				if (!firstParam)
				{
					sb.Append(", ");
				}
				firstParam = false;
				sb.Append('{');
				sb.Append("\"ordinal\": ").Append(ordinal++).Append(", ");
				InlineField(sb, "name", p.SourceName, true);
				InlineField(sb, "cpp_type", p.GetUserFacingDecl(), true);
				sb.Append("\"property_flags\": ").Append((ulong)p.PropertyFlags).Append(", ");
				sb.Append("\"is_return\": false}");
			}
			if (fn.ReturnProperty is UhtProperty ret)
			{
				if (!firstParam)
				{
					sb.Append(", ");
				}
				sb.Append('{');
				sb.Append("\"ordinal\": ").Append(ordinal).Append(", ");
				InlineField(sb, "name", ret.SourceName, true);
				InlineField(sb, "cpp_type", ret.GetUserFacingDecl(), true);
				sb.Append("\"property_flags\": ").Append((ulong)ret.PropertyFlags).Append(", ");
				sb.Append("\"is_return\": true}");
			}
			sb.Append("]}");
		}

		private static void WriteProperty(UhtProperty prop, StringBuilder sb)
		{
			sb.Append("        {");
			InlineField(sb, "name", prop.SourceName, true);
			InlineField(sb, "cpp_type", prop.GetUserFacingDecl(), true);
			sb.Append("\"property_flags\": ").Append((ulong)prop.PropertyFlags).Append(", ");
			InlineField(sb, "specifiers", prop.PropertyFlags.ToString(), true);
			sb.Append("\"is_deprecated\": ").Append(prop.Deprecated ? "true" : "false").Append(", ");
			InlineField(sb, "deprecation_message", DeprecationMessage(prop), true);
			InlineField(sb, "rep_notify", prop.RepNotifyName ?? "", true);
			// rep_condition is DELIBERATELY ABSENT. COND_* is assigned in GetLifetimeReplicatedProps
			// at runtime and is unknowable from a header. Emitting it as null here would let a
			// consumer read "no condition" where the truth is "this tier cannot see it".
			InlineField(sb, "category", prop.MetaData.GetValueOrDefault("Category"), true);
			InlineField(sb, "doc", ToolTip(prop), false);
			sb.Append('}');
		}

		// ---------------------------------------------------------------------------------------

		private static string HeaderPath(UhtType type)
		{
			try
			{
				return type.HeaderFile.FilePath;
			}
			catch (Exception)
			{
				// UhtType.HeaderFile throws UhtIceException for types with no associated header.
				return String.Empty;
			}
		}

		private static string DeprecationMessage(UhtType type)
		{
			// "DeprecationMessage" is a plain metadata key and is not in UhtNames, so it is spelled
			// out. Empty is common and meaningful in itself: something marked deprecated with no
			// statement of what to use instead. Worth being able to query for rather than hiding.
			return type.MetaData.GetValueOrDefault("DeprecationMessage");
		}

		private static string ToolTip(UhtType type)
		{
			return type.MetaData.GetValueOrDefault("ToolTip");
		}

		private static void Field(StringBuilder sb, int indent, string name, string value, bool comma)
		{
			sb.Append(' ', indent * 2).Append('"').Append(name).Append("\": \"").Append(Escape(value)).Append('"');
			sb.Append(comma ? ",\n" : "\n");
		}

		private static void InlineField(StringBuilder sb, string name, string value, bool comma)
		{
			sb.Append('"').Append(name).Append("\": \"").Append(Escape(value)).Append('"');
			if (comma)
			{
				sb.Append(", ");
			}
		}

		private static string Escape(string value)
		{
			if (String.IsNullOrEmpty(value))
			{
				return String.Empty;
			}
			StringBuilder sb = new(value.Length + 8);
			foreach (char c in value)
			{
				switch (c)
				{
					case '"': sb.Append("\\\""); break;
					case '\\': sb.Append("\\\\"); break;
					case '\n': sb.Append("\\n"); break;
					case '\r': sb.Append("\\r"); break;
					case '\t': sb.Append("\\t"); break;
					default:
						if (c < 0x20)
						{
							sb.Append("\\u").Append(((int)c).ToString("x4"));
						}
						else
						{
							sb.Append(c);
						}
						break;
				}
			}
			return sb.ToString();
		}
	}
}
