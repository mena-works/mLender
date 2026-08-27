// Copyright mena-works. MIT licence, see the repository root.
#include "SMLToolbar.h"

#if WITH_EDITOR

#include "MLSettings.h"
#include "SMLImportWindow.h"
#include "SMLPanel.h"

#include "Framework/Application/SlateApplication.h"
#include "Framework/Docking/TabManager.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Interfaces/IPluginManager.h"
#include "IPythonScriptPlugin.h"
#include "Styling/AppStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SComboButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "mLender"

namespace
{
	TWeakPtr<SWindow> GToolbarWindow;

	void RunPython(const FString& Command)
	{
		IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
		if (Python == nullptr || !Python->IsPythonAvailable())
		{
			UE_LOG(LogTemp, Warning,
				TEXT("mLender: Python is not available, the strip cannot act."));
			return;
		}
		Python->ExecPythonCommand(*Command);
	}

	FString PluginVersion()
	{
		const TSharedPtr<IPlugin> Plugin =
			IPluginManager::Get().FindPlugin(TEXT("mLender"));
		return Plugin.IsValid()
			? Plugin->GetDescriptor().VersionName : FString();
	}

	TSharedRef<SWidget> StripButton(
		const FText& Label, const FText& Tooltip, const FString& Command)
	{
		return SNew(SButton)
			.ButtonStyle(FAppStyle::Get(), "SimpleButton")
			.ToolTipText(Tooltip)
			.ContentPadding(FMargin(8.0f, 4.0f))
			.OnClicked_Lambda([Command]()
			{
				RunPython(Command);
				return FReply::Handled();
			})
			[
				SNew(STextBlock)
				.Text(Label)
				.Font(FAppStyle::Get().GetFontStyle("NormalFont"))
			];
	}

	void AddPythonEntry(FMenuBuilder& Menu, const FText& Label,
		const FText& Tooltip, const FString& Command)
	{
		Menu.AddMenuEntry(Label, Tooltip, FSlateIcon(),
			FUIAction(FExecuteAction::CreateLambda([Command]()
			{
				RunPython(Command);
			})));
	}

	/** Remember where the strip sits, and whether it is up. */
	void PersistState(bool bVisible)
	{
		UMLSettings* Settings = GetMutableDefault<UMLSettings>();
		const TSharedPtr<SWindow> Window = GToolbarWindow.Pin();
		if (Settings != nullptr && Window.IsValid())
		{
			const FVector2D Position = Window->GetPositionInScreen();
			Settings->ToolbarX = static_cast<float>(Position.X);
			Settings->ToolbarY = static_cast<float>(Position.Y);
			Settings->bToolbarVisible = bVisible;
			RunPython(FString::Printf(
				TEXT("import mlender_unreal; mlender_unreal.settings.update("
					 "toolbar_visible=%s, toolbar_x=%f, toolbar_y=%f)"),
				bVisible ? TEXT("True") : TEXT("False"),
				Position.X, Position.Y));
		}
	}

	TSharedRef<SWidget> KebabMenu()
	{
		FMenuBuilder Menu(/*bInShouldCloseWindowAfterMenuSelection=*/true,
			nullptr);
		AddPythonEntry(Menu,
			LOCTEXT("KebabReport", "Open the report"),
			LOCTEXT("KebabReportTip",
				"Written beside every package; it holds every warning."),
			TEXT("import mlender_unreal; mlender_unreal.actions.open_report()"));
		AddPythonEntry(Menu,
			LOCTEXT("KebabSummary", "Summary to the log"),
			LOCTEXT("KebabSummaryTip",
				"Counts, phase timings and the first warnings."),
			TEXT("import mlender_unreal; "
				 "mlender_unreal.actions.show_last_summary()"));
		AddPythonEntry(Menu,
			LOCTEXT("KebabSelect", "Select what mLender made"),
			LOCTEXT("KebabSelectTip", "Everything tagged by this tool."),
			TEXT("import mlender_unreal; "
				 "mlender_unreal.actions.select_generated_actors()"));
		AddPythonEntry(Menu,
			LOCTEXT("KebabHidden", "Show / hide the hidden objects"),
			LOCTEXT("KebabHiddenTip",
				"The layer holding what Maya had hidden."),
			TEXT("import mlender_unreal; "
				 "mlender_unreal.actions.toggle_hidden_layer()"));
		return Menu.MakeWidget();
	}

	TSharedRef<SWidget> LiveLinkMenu()
	{
		FMenuBuilder Menu(true, nullptr);
		AddPythonEntry(Menu,
			LOCTEXT("LinkStart", "Start listening"), FText::GetEmpty(),
			TEXT("import mlender_unreal; mlender_unreal.start_listener()"));
		AddPythonEntry(Menu,
			LOCTEXT("LinkStop", "Stop listening"), FText::GetEmpty(),
			TEXT("import mlender_unreal; mlender_unreal.stop_listener()"));
		AddPythonEntry(Menu,
			LOCTEXT("LinkStatus", "Status to the log"), FText::GetEmpty(),
			TEXT("import mlender_unreal; mlender_unreal.print_status()"));
		return Menu.MakeWidget();
	}

	TSharedRef<SWidget> StripContent()
	{
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);

		// Close first, like the bar this is modelled on.
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(2.0f, 0.0f)
		[
			SNew(SButton)
			.ButtonStyle(FAppStyle::Get(), "SimpleButton")
			.ToolTipText(LOCTEXT("CloseTip",
				"Hide the strip. Tools > mLender brings it back."))
			.OnClicked_Lambda([]()
			{
				FMLToolbar::Hide();
				return FReply::Handled();
			})
			[
				SNew(STextBlock).Text(FText::FromString(TEXT("✕")))
			]
		];
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SComboButton)
			.HasDownArrow(false)
			.ToolTipText(LOCTEXT("KebabTip", "Report, summary, selection"))
			.OnGetMenuContent_Static(&KebabMenu)
			.ButtonContent()
			[
				SNew(STextBlock).Text(FText::FromString(TEXT("⋮")))
			]
		];

		Row->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SButton)
			.ButtonStyle(FAppStyle::Get(), "SimpleButton")
			.ToolTipText(LOCTEXT("ImportTip",
				"Pick a package written by Maya, tick what comes in, and "
				"build it."))
			.ContentPadding(FMargin(8.0f, 4.0f))
			.OnClicked_Lambda([]()
			{
				FGlobalTabmanager::Get()->TryInvokeTab(MLImportTabName);
				return FReply::Handled();
			})
			[
				SNew(STextBlock).Text(LOCTEXT("Import", "Import"))
			]
		];
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SButton)
			.ButtonStyle(FAppStyle::Get(), "SimpleButton")
			.ToolTipText(LOCTEXT("SettingsTip", "The mLender settings panel."))
			.ContentPadding(FMargin(8.0f, 4.0f))
			.OnClicked_Lambda([]()
			{
				FGlobalTabmanager::Get()->TryInvokeTab(MLPanelTabName);
				return FReply::Handled();
			})
			[
				SNew(STextBlock).Text(LOCTEXT("Settings", "Settings"))
			]
		];
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SComboButton)
			.ToolTipText(LOCTEXT("LinkTip", "Listen for a package from Maya"))
			.OnGetMenuContent_Static(&LiveLinkMenu)
			.ButtonContent()
			[
				SNew(STextBlock).Text(LOCTEXT("Link", "LiveLink"))
			]
		];
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			StripButton(LOCTEXT("Snapshot", "Snapshot"),
				LOCTEXT("SnapshotTip",
					"Save the open level and copy its file, timestamped, "
					"under Saved/mLender/Snapshots."),
				TEXT("import mlender_unreal; "
					 "mlender_unreal.actions.snapshot_level()"))
		];

		Row->AddSlot().AutoWidth().VAlign(VAlign_Center)
			.Padding(10.0f, 0.0f, 6.0f, 0.0f)
		[
			SNew(STextBlock)
			.Text(FText::FromString(
				FString::Printf(TEXT("mLender %s"), *PluginVersion())))
			.Font(FAppStyle::Get().GetFontStyle("SmallFont"))
			.ColorAndOpacity(FSlateColor::UseSubduedForeground())
		];

		return SNew(SBorder)
			.BorderImage(FAppStyle::Get().GetBrush("Brushes.Panel"))
			.Padding(FMargin(4.0f, 3.0f))
			[
				Row
			];
	}
}

void FMLToolbar::Show()
{
	if (!FSlateApplication::IsInitialized())
	{
		// A commandlet: nowhere to hang a window.
		return;
	}
	TSharedPtr<SWindow> Existing = GToolbarWindow.Pin();
	if (Existing.IsValid())
	{
		Existing->ShowWindow();
		Existing->BringToFront();
		PersistState(/*bVisible=*/true);
		return;
	}

	const UMLSettings* Settings = GetDefault<UMLSettings>();
	FVector2D Position(80.0f, 80.0f);
	if (Settings != nullptr
		&& Settings->ToolbarX >= 0.0f && Settings->ToolbarY >= 0.0f)
	{
		Position.Set(Settings->ToolbarX, Settings->ToolbarY);
	}

	TSharedRef<SWindow> Window =
		SNew(SWindow)
		.Type(EWindowType::Normal)
		.CreateTitleBar(false)
		.SizingRule(ESizingRule::Autosized)
		.SupportsMaximize(false)
		.SupportsMinimize(false)
		.FocusWhenFirstShown(false)
		.bDragAnywhere(true)
		.ScreenPosition(Position)
		[
			StripContent()
		];

	// A native child of the editor's root rides above the viewport without
	// being globally topmost -- the standing a tool palette has.
	const TSharedPtr<SWindow> Root = FGlobalTabmanager::Get()->GetRootWindow();
	if (Root.IsValid())
	{
		FSlateApplication::Get().AddWindowAsNativeChild(
			Window, Root.ToSharedRef());
	}
	else
	{
		FSlateApplication::Get().AddWindow(Window);
	}
	GToolbarWindow = Window;
}

void FMLToolbar::Hide()
{
	const TSharedPtr<SWindow> Window = GToolbarWindow.Pin();
	if (Window.IsValid())
	{
		PersistState(/*bVisible=*/false);
		Window->HideWindow();
	}
}

bool FMLToolbar::IsVisible()
{
	const TSharedPtr<SWindow> Window = GToolbarWindow.Pin();
	return Window.IsValid() && Window->IsVisible();
}

void FMLToolbar::Shutdown()
{
	const TSharedPtr<SWindow> Window = GToolbarWindow.Pin();
	if (Window.IsValid())
	{
		Window->RequestDestroyWindow();
	}
	GToolbarWindow.Reset();
}

#undef LOCTEXT_NAMESPACE

#endif // WITH_EDITOR
