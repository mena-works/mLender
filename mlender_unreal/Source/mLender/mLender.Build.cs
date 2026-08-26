// The compiled half of the mLender receiver. See Public/MLMotionPlayer.h for
// why a plugin that is otherwise pure Python carries a C++ module at all, and
// Public/SMLPanel.h for the panel.
using UnrealBuildTool;

public class mLender : ModuleRules
{
	public mLender(ReadOnlyTargetRules Target) : base(Target)
	{
		// An installed engine compiles plugin modules against its shared
		// precompiled headers; a private PCH is refused there.
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			// CreateMotionAsset registers the asset it makes, so the Content
			// Browser sees it without a restart.
			"AssetRegistry",
		});

		// The module stays Runtime because the motion player lives in PIE and
		// in the Movie Render Queue, so the panel's dependencies are added
		// only where there is an editor to hang it in, and every line of it
		// is behind WITH_EDITOR.
		if (Target.bBuildEditor)
		{
			PrivateDependencyModuleNames.AddRange(new string[]
			{
				"Slate",
				"SlateCore",
				"WorkspaceMenuStructure",
				// The buttons run one line of Python each; the actions
				// themselves are in actions.py so the menu can call the
				// same ones.
				"PythonScriptPlugin",
			});
		}
	}
}
