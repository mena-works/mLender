// Copyright mena-works. MIT licence, see the repository root.
#include "SMLPanel.h"

#if WITH_EDITOR

#include "MLSettings.h"

#include "IPythonScriptPlugin.h"
#include "Styling/AppStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SSpinBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SExpandableArea.h"
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

UMLSettings* SMLPanel::Settings()
{
	return GetMutableDefault<UMLSettings>();
}

FReply SMLPanel::RunPython(FString Command)
{
	Run(Command);
	return FReply::Handled();
}

void SMLPanel::Persist()
{
	// The one Python line that pulls the object's values into the dict and
	// the settings file. Called on commit rather than on every keystroke.
	Run(TEXT("import mlender_unreal; mlender_unreal.settings.update("
			 "**mlender_unreal.settings.values())"));
}

FText SMLPanel::SummaryText() const
{
	const UMLSettings* Current = GetDefault<UMLSettings>();
	if (Current == nullptr || Current->LastSummary.IsEmpty())
	{
		return LOCTEXT("NoImport", "No import yet this session.");
	}
	return FText::FromString(Current->LastSummary);
}

TSharedRef<SWidget> SMLPanel::MakeButton(
	const FText& Label, const FText& Tooltip, const FString& Command,
	bool bPrimary)
{
	return SNew(SButton)
		.ToolTipText(Tooltip)
		.HAlign(HAlign_Center)
		.ContentPadding(bPrimary ? FMargin(0.0f, 10.0f) : FMargin(8.0f, 4.0f))
		.OnClicked(FOnClicked::CreateSP(this, &SMLPanel::RunPython, Command))
		[
			SNew(STextBlock)
			.Text(Label)
			.Font(bPrimary
				? FAppStyle::Get().GetFontStyle("NormalFontBold")
				: FAppStyle::Get().GetFontStyle("NormalFont"))
		];
}

TSharedRef<SWidget> SMLPanel::MakeCheck(
	const FText& Label, const FText& Tooltip, bool UMLSettings::*Field)
{
	return SNew(SCheckBox)
		.ToolTipText(Tooltip)
		.IsChecked_Lambda([Field]()
		{
			return (Settings()->*Field)
				? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
		})
		.OnCheckStateChanged_Lambda([this, Field](ECheckBoxState State)
		{
			(Settings()->*Field) = (State == ECheckBoxState::Checked);
			Persist();
		})
		[
			SNew(STextBlock).Text(Label).Margin(FMargin(4.0f, 0.0f, 10.0f, 0.0f))
		];
}

TSharedRef<SWidget> SMLPanel::Labelled(
	const FText& Label, TSharedRef<SWidget> Widget)
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(STextBlock).Text(Label).MinDesiredWidth(110.0f)
		]
		+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
		[
			Widget
		];
}

TSharedRef<SWidget> SMLPanel::SectionTitle(const FText& Label)
{
	return SNew(STextBlock)
		.Text(Label)
		.Font(FAppStyle::Get().GetFontStyle("NormalFontBold"))
		.Margin(FMargin(0.0f, 10.0f, 0.0f, 2.0f));
}

void SMLPanel::Construct(const FArguments& InArgs)
{
	const FMargin Row(8.0f, 3.0f);

	// --- what comes in: the settings a shot actually touches --------------
	TSharedRef<SWrapBox> Kinds = SNew(SWrapBox).UseAllottedSize(true);
	Kinds->AddSlot().Padding(0.0f, 2.0f)[MakeCheck(
		LOCTEXT("Lights", "Lights"),
		LOCTEXT("LightsTip", "Build the package's lights."),
		&UMLSettings::bImportLights)];
	Kinds->AddSlot().Padding(0.0f, 2.0f)[MakeCheck(
		LOCTEXT("Cameras", "Cameras"),
		LOCTEXT("CamerasTip", "Build the package's cameras."),
		&UMLSettings::bImportCameras)];
	Kinds->AddSlot().Padding(0.0f, 2.0f)[MakeCheck(
		LOCTEXT("Animation", "Animation"),
		LOCTEXT("AnimationTip",
			"Key the sampled motion and build the Level Sequence."),
		&UMLSettings::bImportAnimation)];
	Kinds->AddSlot().Padding(0.0f, 2.0f)[MakeCheck(
		LOCTEXT("Materials", "Update materials"),
		LOCTEXT("MaterialsTip",
			"Off keeps the ML_ materials this project already has, so your "
			"tuned instances survive the next send. New shaders are still "
			"built."),
		&UMLSettings::bUpdateMaterials)];
	Kinds->AddSlot().Padding(0.0f, 2.0f)[MakeCheck(
		LOCTEXT("Sets", "Sets and layers"),
		LOCTEXT("SetsTip",
			"Rebuild Maya's selection sets and display layers as Unreal "
			"Layers."),
		&UMLSettings::bImportSets)];

	// --- the folded-away rest ---------------------------------------------
	TSharedRef<SVerticalBox> More = SNew(SVerticalBox);
	More->AddSlot().AutoHeight().Padding(Row)
	[
		Labelled(LOCTEXT("Power", "Light power"),
			SNew(SSpinBox<float>)
			.ToolTipText(LOCTEXT("PowerTip",
				"An artistic multiplier over the measured light conversion. "
				"The conversion is exact, so 1.0 matches the Maya render."))
			.MinValue(0.0f).MaxSliderValue(4.0f).MaxValue(1000.0f)
			.Value_Lambda([]() { return Settings()->PowerScale; })
			.OnValueChanged_Lambda([](float V) { Settings()->PowerScale = V; })
			.OnValueCommitted_Lambda([this](float V, ETextCommit::Type)
			{
				Settings()->PowerScale = V;
				Persist();
			}))
	];
	More->AddSlot().AutoHeight().Padding(Row)
	[
		Labelled(LOCTEXT("ActiveCam", "Active camera"),
			SNew(SEditableTextBox)
			.ToolTipText(LOCTEXT("ActiveCamTip",
				"Which camera becomes the shot's own. Blank takes the one "
				"Maya marks renderable."))
			.HintText(LOCTEXT("ActiveCamHint", "the renderable one"))
			.Text_Lambda([]()
			{
				return FText::FromString(Settings()->ActiveCamera);
			})
			.OnTextCommitted_Lambda([this](const FText& T, ETextCommit::Type)
			{
				Settings()->ActiveCamera = T.ToString();
				Persist();
			}))
	];
	More->AddSlot().AutoHeight().Padding(Row)
	[
		Labelled(LOCTEXT("Folder", "Package folder"),
			SNew(SEditableTextBox)
			.ToolTipText(LOCTEXT("FolderTip",
				"The package the import buttons read. The picker fills this "
				"in; it can also be pasted."))
			.Text_Lambda([]()
			{
				return FText::FromString(Settings()->LastPackageFolder.Path);
			})
			.OnTextCommitted_Lambda([this](const FText& T, ETextCommit::Type)
			{
				Settings()->LastPackageFolder.Path = T.ToString();
				Persist();
			}))
	];
	More->AddSlot().AutoHeight().Padding(Row)
	[
		Labelled(LOCTEXT("Host", "LiveLink host"),
			SNew(SEditableTextBox)
			.Text_Lambda([]()
			{
				return FText::FromString(Settings()->LivelinkHost);
			})
			.OnTextCommitted_Lambda([this](const FText& T, ETextCommit::Type)
			{
				Settings()->LivelinkHost = T.ToString();
				Persist();
			}))
	];
	More->AddSlot().AutoHeight().Padding(Row)
	[
		Labelled(LOCTEXT("Port", "LiveLink port"),
			SNew(SSpinBox<int32>)
			.MinValue(1).MaxValue(65535)
			.Value_Lambda([]() { return Settings()->LivelinkPort; })
			.OnValueChanged_Lambda([](int32 V) { Settings()->LivelinkPort = V; })
			.OnValueCommitted_Lambda([this](int32 V, ETextCommit::Type)
			{
				Settings()->LivelinkPort = V;
				Persist();
			}))
	];
	More->AddSlot().AutoHeight().Padding(Row)
	[
		MakeCheck(
			LOCTEXT("AutoReport", "Open the report after each import"),
			LOCTEXT("AutoReportTip",
				"The file written beside every package. It holds every "
				"warning; the log shows the first few."),
			&UMLSettings::bOpenReportWhenDone)
	];
	{
		TSharedRef<SWrapBox> MoreButtons = SNew(SWrapBox).UseAllottedSize(true);
		MoreButtons->AddSlot().Padding(2.0f)[MakeButton(
			LOCTEXT("SelectMade", "Select what mLender made"),
			LOCTEXT("SelectMadeTip",
				"Everything tagged by this tool, in the level."),
			TEXT("import mlender_unreal; "
				 "mlender_unreal.actions.select_generated_actors()"))];
		MoreButtons->AddSlot().Padding(2.0f)[MakeButton(
			LOCTEXT("LogSummary", "Summary to the log"),
			LOCTEXT("LogSummaryTip",
				"The counts, the phase timings and the first warnings."),
			TEXT("import mlender_unreal; "
				 "mlender_unreal.actions.show_last_summary()"))];
		MoreButtons->AddSlot().Padding(2.0f)[MakeButton(
			LOCTEXT("OpenFolder", "Open the package folder"),
			LOCTEXT("OpenFolderTip", "The folder the last import read."),
			TEXT("import mlender_unreal; "
				 "mlender_unreal.actions.open_package_folder()"))];
		More->AddSlot().AutoHeight().Padding(Row)[MoreButtons];
	}

	// --- the face ----------------------------------------------------------
	ChildSlot
	[
		SNew(SScrollBox)
		+ SScrollBox::Slot()
		[
			SNew(SVerticalBox)

			// LiveLink line: where it listens, and the two verbs.
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 8.0f, 8.0f, 4.0f)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
				[
					SNew(STextBlock)
					.Font(FAppStyle::Get().GetFontStyle("NormalFontBold"))
					.Text_Lambda([]()
					{
						return FText::FromString(FString::Printf(
							TEXT("LiveLink  %s:%d"),
							*Settings()->LivelinkHost,
							Settings()->LivelinkPort));
					})
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(2.0f, 0.0f)
				[
					MakeButton(LOCTEXT("Start", "Start"),
						LOCTEXT("StartTip",
							"Listen for a package sent from Maya."),
						TEXT("import mlender_unreal; "
							 "mlender_unreal.start_listener()"))
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(2.0f, 0.0f)
				[
					MakeButton(LOCTEXT("Stop", "Stop"),
						LOCTEXT("StopTip", "Stop listening and free the port."),
						TEXT("import mlender_unreal; "
							 "mlender_unreal.stop_listener()"))
				]
			]

			// The one big action, and its echo.
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 6.0f)
			[
				MakeButton(
					LOCTEXT("Import", "Import a Package..."),
					LOCTEXT("ImportTip",
						"Pick a package written by Maya and build it here."),
					TEXT("import mlender_unreal; "
						 "mlender_unreal.actions.import_package_folder()"),
					/*bPrimary=*/true)
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 0.0f)
			[
				MakeButton(
					LOCTEXT("Reimport", "Import the last one again"),
					LOCTEXT("ReimportTip",
						"Build the last package again with the settings as "
						"they are now."),
					TEXT("import mlender_unreal; "
						 "mlender_unreal.actions.reimport_last()"))
			]

			// The settings a shot actually touches.
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 0.0f)
			[
				SectionTitle(LOCTEXT("WhatComesIn", "What comes in"))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(Row)
			[
				Labelled(LOCTEXT("Scale", "Scale"),
					SNew(SSpinBox<float>)
					.ToolTipText(LOCTEXT("ScaleTip",
						"Multiplies everything: the meshes through "
						"Interchange and the motion, cameras and locators "
						"through the JSON. Measured at 10 on a 200 m shot: "
						"both halves scaled once, not twice."))
					.MinValue(0.0001f).MaxSliderValue(100.0f)
					.MaxValue(100000.0f)
					.Value_Lambda([]() { return Settings()->ImportScale; })
					.OnValueChanged_Lambda([](float V)
					{
						Settings()->ImportScale = V;
					})
					.OnValueCommitted_Lambda([this](float V, ETextCommit::Type)
					{
						Settings()->ImportScale = V;
						Persist();
					}))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(Row)[Kinds]
			+ SVerticalBox::Slot().AutoHeight().Padding(Row)
			[
				MakeCheck(
					LOCTEXT("KeepLights", "Keep the lighting this level already has"),
					LOCTEXT("KeepLightsTip",
						"Lights a previous send made are still replaced."),
					&UMLSettings::bKeepExistingLights)
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(Row)
			[
				// Special: flipping this also flips the layer, now, through
				// the same action the menu uses.
				SNew(SCheckBox)
				.ToolTipText(LOCTEXT("HiddenTip",
					"Objects Maya had hidden live in a layer, because a "
					"layer is the only hiding the editor keeps across "
					"reopening the level."))
				.IsChecked_Lambda([]()
				{
					return Settings()->bRevealHiddenLayer
						? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
				})
				.OnCheckStateChanged_Lambda([this](ECheckBoxState State)
				{
					RunPython(FString::Printf(
						TEXT("import mlender_unreal; mlender_unreal.actions."
							 "set_hidden_layer_visible(%s)"),
						State == ECheckBoxState::Checked
							? TEXT("True") : TEXT("False")));
				})
				[
					SNew(STextBlock)
					.Text(LOCTEXT("Hidden", "Show the objects Maya hid"))
					.Margin(FMargin(4.0f, 0.0f))
				]
			]

			// What the last import did.
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 0.0f)
			[
				SectionTitle(LOCTEXT("LastImport", "Last import"))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 2.0f)
			[
				SNew(SBorder)
				.BorderImage(FAppStyle::Get().GetBrush("ToolPanel.GroupBorder"))
				.Padding(8.0f)
				[
					SNew(STextBlock)
					.AutoWrapText(true)
					.Text(this, &SMLPanel::SummaryText)
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 2.0f)
			[
				MakeButton(LOCTEXT("Report", "Open the report"),
					LOCTEXT("ReportTip",
						"Written beside every package; it holds every "
						"warning."),
					TEXT("import mlender_unreal; "
						 "mlender_unreal.actions.open_report()"))
			]

			// Everything else, folded.
			+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 8.0f)
			[
				SNew(SExpandableArea)
				.AreaTitle(LOCTEXT("MoreTitle", "More"))
				.InitiallyCollapsed(true)
				.BodyContent()[More]
			]
		]
	];
}

#undef LOCTEXT_NAMESPACE

#endif // WITH_EDITOR
