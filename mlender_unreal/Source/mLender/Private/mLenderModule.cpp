// Copyright mena-works. MIT licence, see the repository root.
#include "Modules/ModuleManager.h"

#if WITH_EDITOR
#include "SMLPanel.h"
#include "Framework/Docking/TabManager.h"
#include "Misc/CoreDelegates.h"
#include "Styling/AppStyle.h"
#include "Textures/SlateIcon.h"
#include "Widgets/Docking/SDockTab.h"
#include "WorkspaceMenuStructure.h"
#include "WorkspaceMenuStructureModule.h"
#endif

#define LOCTEXT_NAMESPACE "mLender"

/** The panel's tab id. A name Python does not need, but the header list in
 *  check_contracts.py reads it so a rename is noticed on both sides. */
const FName MLPanelTabName(TEXT("mLenderPanel"));

/**
 * The module exists to carry the UCLASSes the receiver needs and, in the
 * editor, the panel. Everything the panel does is one Python call: the logic
 * lives in actions.py, so an install with no compiled module still has all of
 * it from the Tools menu.
 */
class FMLenderModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
#if WITH_EDITOR
		// Not in StartupModule itself: this module loads at the Default
		// phase, before the editor's tab manager exists. Registering there
		// reports no error and produces no tab, which is the same failure
		// mode as a menu registered against a path that is not there.
		FCoreDelegates::OnPostEngineInit.AddRaw(
			this, &FMLenderModule::RegisterPanelTab);
#endif
	}

	virtual void ShutdownModule() override
	{
#if WITH_EDITOR
		FCoreDelegates::OnPostEngineInit.RemoveAll(this);
		if (FSlateApplication::IsInitialized())
		{
			FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(MLPanelTabName);
		}
#endif
	}

#if WITH_EDITOR
private:
	void RegisterPanelTab()
	{
		if (!FSlateApplication::IsInitialized())
		{
			// A commandlet. There is nowhere to hang a tab and saying so once
			// beats a stack of warnings from every headless run.
			return;
		}
		FGlobalTabmanager::Get()
			->RegisterNomadTabSpawner(
				MLPanelTabName,
				FOnSpawnTab::CreateRaw(this, &FMLenderModule::SpawnPanelTab))
			.SetDisplayName(LOCTEXT("PanelTitle", "mLender"))
			.SetTooltipText(LOCTEXT("PanelTooltip",
				"Import settings, what comes in, and what the last import did"))
			.SetGroup(WorkspaceMenu::GetMenuStructure().GetLevelEditorCategory())
			.SetIcon(FSlateIcon(FAppStyle::GetAppStyleSetName(),
				"LevelEditor.Tabs.Details"));
	}

	TSharedRef<SDockTab> SpawnPanelTab(const FSpawnTabArgs& Args)
	{
		return SNew(SDockTab)
			.TabRole(ETabRole::NomadTab)
			[
				SNew(SMLPanel)
			];
	}
#endif
};

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FMLenderModule, mLender);
