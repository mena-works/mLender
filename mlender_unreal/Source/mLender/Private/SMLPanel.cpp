// Copyright mena-works. MIT licence, see the repository root.
#include "SMLPanel.h"

#if WITH_EDITOR

#include "MLSettings.h"

#include "IPythonScriptPlugin.h"
#include "Modules/ModuleManager.h"
#include "PropertyEditorModule.h"
#include "IDetailsView.h"
#include "Styling/AppStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SWrapBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/SBoxPanel.h"

#define LOCTEXT_NAMESPACE "mLender"

namespace
{
	/** One line of Python, or a warning if the plugin is not there.
	 *
	 * PythonScriptPlugin is a dependency of this plugin, so it being absent
	 * means a broken install rather than an unsupported one -- but a button
	 * that silently does nothing is the worst way to find that out.
	 */
	void Run(const FString& Command)
	{
		IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
		if (Python == nullptr || !Python->IsPythonAvailable())
		{
			UE_LOG(LogTemp, Warning,
				TEXT("mLender: Python is not available in this editor, so the "
					 "panel cannot do anything."));
			return;
		}
		Python->ExecPythonCommand(*Command);
	}
}

FReply SMLPanel::RunPython(FString Command)
{
	Run(Command);
	return FReply::Handled();
}

FText SMLPanel::SummaryText() const
{
	const UMLSettings* Settings = GetDefault<UMLSettings>();
	if (Settings == nullptr || Settings->LastSummary.IsEmpty())
	{
		return LOCTEXT("NoImport", "No import yet this session.");
	}
	return FText::FromString(Settings->LastSummary);
}

FText SMLPanel::StatusText() const
{
	const UMLSettings* Settings = GetDefault<UMLSettings>();
	if (Settings == nullptr)
	{
		return FText::GetEmpty();
	}
	return FText::FromString(FString::Printf(
		TEXT("LiveLink %s:%d"), *Settings->LivelinkHost, Settings->LivelinkPort));
}

TSharedRef<SWidget> SMLPanel::MakeButton(
	const FText& Label, const FText& Tooltip, const FString& Command)
{
	return SNew(SButton)
		.Text(Label)
		.ToolTipText(Tooltip)
		.OnClicked(FOnClicked::CreateSP(
			const_cast<SMLPanel*>(this), &SMLPanel::RunPython, Command));
}

void SMLPanel::Construct(const FArguments& InArgs)
{
	FPropertyEditorModule& PropertyEditor =
		FModuleManager::LoadModuleChecked<FPropertyEditorModule>("PropertyEditor");

	FDetailsViewArgs Args;
	Args.bAllowSearch = true;
	Args.bHideSelectionTip = true;
	Args.bShowOptions = false;
	Args.NameAreaSettings = FDetailsViewArgs::HideNameArea;
	DetailsView = PropertyEditor.CreateDetailView(Args);
	// The CDO, because that is the object Python reads and writes: a fresh
	// instance would draw values nothing else can see.
	DetailsView->SetObject(GetMutableDefault<UMLSettings>());

	const FMargin Pad(4.0f, 2.0f);

	TSharedRef<SWrapBox> ImportRow = SNew(SWrapBox).UseAllottedSize(true);
	ImportRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("ImportFolder", "Import a Package Folder..."),
		LOCTEXT("ImportFolderTip",
			"Pick a package written by Maya and build it here. Until now a "
			"package could only arrive over LiveLink."),
		TEXT("import mlender_unreal; mlender_unreal.actions.import_package_folder()"))];
	ImportRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Reimport", "Import the Last One Again"),
		LOCTEXT("ReimportTip", "Build the last package again with the settings as they are now."),
		TEXT("import mlender_unreal; mlender_unreal.actions.reimport_last()"))];

	TSharedRef<SWrapBox> AfterRow = SNew(SWrapBox).UseAllottedSize(true);
	AfterRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Summary", "Summary to the Log"),
		LOCTEXT("SummaryTip", "The counts, the phase timings and the first warnings."),
		TEXT("import mlender_unreal; mlender_unreal.actions.show_last_summary()"))];
	AfterRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("OpenReport", "Open the Report"),
		LOCTEXT("OpenReportTip",
			"The file written beside every package. It holds every warning; "
			"the log shows the first few."),
		TEXT("import mlender_unreal; mlender_unreal.actions.open_report()"))];
	AfterRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("OpenFolder", "Open the Package Folder"),
		LOCTEXT("OpenFolderTip", "The folder the last import read."),
		TEXT("import mlender_unreal; mlender_unreal.actions.open_package_folder()"))];
	AfterRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Hidden", "Show / Hide the Hidden Objects"),
		LOCTEXT("HiddenTip",
			"Objects Maya had hidden live in a layer, because a layer is the "
			"only hiding the editor keeps across reopening the level."),
		TEXT("import mlender_unreal; mlender_unreal.actions.toggle_hidden_layer()"))];
	AfterRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("SelectMade", "Select What mLender Made"),
		LOCTEXT("SelectMadeTip", "Everything tagged by this tool, in the level."),
		TEXT("import mlender_unreal; mlender_unreal.actions.select_generated_actors()"))];

	TSharedRef<SWrapBox> LinkRow = SNew(SWrapBox).UseAllottedSize(true);
	LinkRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Start", "Start LiveLink"),
		LOCTEXT("StartTip", "Listen for a package sent from Maya."),
		TEXT("import mlender_unreal; mlender_unreal.start_listener()"))];
	LinkRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Stop", "Stop LiveLink"),
		LOCTEXT("StopTip", "Stop listening and free the port."),
		TEXT("import mlender_unreal; mlender_unreal.stop_listener()"))];
	LinkRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Status", "Status to the Log"),
		LOCTEXT("StatusTip", "Every setting and the listener's state."),
		TEXT("import mlender_unreal; mlender_unreal.print_status()"))];
	LinkRow->AddSlot().Padding(Pad)[MakeButton(
		LOCTEXT("Apply", "Re-read the Panel"),
		LOCTEXT("ApplyTip",
			"Pull the values edited here back into Python and save them. The "
			"next import reads them anyway; this writes the file now."),
		TEXT("import mlender_unreal; mlender_unreal.settings.update("
			 "**mlender_unreal.settings.values())"))];

	ChildSlot
	[
		SNew(SVerticalBox)

		+ SVerticalBox::Slot().AutoHeight().Padding(6.0f, 6.0f, 6.0f, 2.0f)
		[
			SNew(STextBlock)
			.Font(FAppStyle::Get().GetFontStyle("NormalFontBold"))
			.Text(this, &SMLPanel::StatusText)
		]

		+ SVerticalBox::Slot().AutoHeight().Padding(6.0f, 0.0f, 6.0f, 4.0f)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::Get().GetBrush("ToolPanel.GroupBorder"))
			.Padding(6.0f)
			[
				SNew(STextBlock)
				.AutoWrapText(true)
				.Text(this, &SMLPanel::SummaryText)
			]
		]

		+ SVerticalBox::Slot().AutoHeight().Padding(4.0f)[ImportRow]
		+ SVerticalBox::Slot().AutoHeight().Padding(4.0f)[AfterRow]
		+ SVerticalBox::Slot().AutoHeight().Padding(4.0f)[LinkRow]

		+ SVerticalBox::Slot().FillHeight(1.0f).Padding(2.0f)
		[
			SNew(SScrollBox)
			+ SScrollBox::Slot()[DetailsView.ToSharedRef()]
		]
	];
}

#undef LOCTEXT_NAMESPACE

#endif // WITH_EDITOR
