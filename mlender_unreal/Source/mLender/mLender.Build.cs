// The compiled half of the mLender receiver. See Public/MLMotionPlayer.h for
// why a plugin that is otherwise pure Python carries a C++ module at all.
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
	}
}
