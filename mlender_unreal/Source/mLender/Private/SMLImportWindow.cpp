// Copyright mena-works. MIT licence, see the repository root.
#include "SMLImportWindow.h"

#if WITH_EDITOR

#include "MLSettings.h"

#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "IPythonScriptPlugin.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Styling/AppStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SSearchBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Views/STableRow.h"

#define LOCTEXT_NAMESPACE "mLender"

namespace
{
	void RunPython(const FString& Command)
	{
		IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
		if (Python == nullptr || !Python->IsPythonAvailable())
		{
			UE_LOG(LogTemp, Warning,
				TEXT("mLender: Python is not available; the Import window "
					 "cannot read a package."));
			return;
		}
		Python->ExecPythonCommand(*Command);
	}

	FString SavedFile(const FString& Name)
	{
		return FPaths::Combine(
			FPaths::ProjectSavedDir(), TEXT("mLender"), Name);
	}
}

void SMLImportWindow::Construct(const FArguments& InArgs)
{
	const UMLSettings* Settings = GetDefault<UMLSettings>();
	if (Settings != nullptr)
	{
		PackageFolder = Settings->LastPackageFolder.Path;
	}

	ChildSlot
	[
		SNew(SVerticalBox)

		// --- the package -------------------------------------------------
		+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 8.0f, 8.0f, 4.0f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(STextBlock).Text(LOCTEXT("Package", "Package"))
				.MinDesiredWidth(60.0f)
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
			[
				SNew(SEditableTextBox)
				.Text_Lambda([this]()
				{
					return FText::FromString(PackageFolder);
				})
				.OnTextCommitted_Lambda(
					[this](const FText& T, ETextCommit::Type)
				{
					PackageFolder = T.ToString();
					ReloadManifest();
				})
			]
			+ SHorizontalBox::Slot().AutoWidth().Padding(4.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("Browse", "Browse..."))
				.OnClicked_Lambda([this]()
				{
					Browse();
					return FReply::Handled();
				})
			]
		]

		// --- the search --------------------------------------------------
		+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 2.0f)
		[
			SNew(SSearchBox)
			.HintText(LOCTEXT("SearchHint", "Filter by name"))
			.OnTextChanged_Lambda([this](const FText& T)
			{
				Search = T.ToString();
				if (Tree.IsValid())
				{
					Tree->RequestTreeRefresh();
				}
			})
		]

		// --- the outliner ------------------------------------------------
		+ SVerticalBox::Slot().FillHeight(1.0f).Padding(8.0f, 4.0f)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::Get().GetBrush("ToolPanel.GroupBorder"))
			[
				SAssignNew(Tree, STreeView<TSharedPtr<FMLNode>>)
				.TreeItemsSource(&Roots)
				.OnGenerateRow(this, &SMLImportWindow::MakeRow)
				.OnGetChildren(this, &SMLImportWindow::GetChildren)
				.SelectionMode(ESelectionMode::None)
			]
		]

		// --- what will happen --------------------------------------------
		+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 2.0f)
		[
			SNew(STextBlock).Text(this, &SMLImportWindow::FooterText)
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(8.0f, 4.0f, 8.0f, 8.0f)
		[
			SNew(SButton)
			.HAlign(HAlign_Center)
			.ContentPadding(FMargin(0.0f, 10.0f))
			.ToolTipText(LOCTEXT("ImportTip",
				"Build the ticked branch. The level is cleared first -- this "
				"is a full import, filtered."))
			.IsEnabled_Lambda([this]() { return CheckedCount() > 0; })
			.OnClicked(this, &SMLImportWindow::Import)
			[
				SNew(STextBlock)
				.Font(FAppStyle::Get().GetFontStyle("NormalFontBold"))
				.Text(LOCTEXT("Import", "Import"))
			]
		]
	];

	ReloadManifest();
}

void SMLImportWindow::Browse()
{
	// The picker and the manifest both live in Python; this asks for both in
	// one line, then reads what was written.
	RunPython(TEXT(
		"import mlender_unreal as m; "
		"f = m.actions.choose_folder(); "
		"m.settings.update(last_package_folder=f) if f else None; "
		"m.actions.build_package_manifest(f) if f else None"));
	const UMLSettings* Settings = GetDefault<UMLSettings>();
	if (Settings != nullptr)
	{
		PackageFolder = Settings->LastPackageFolder.Path;
	}
	ReloadManifest();
}

void SMLImportWindow::ReloadManifest()
{
	const FString Path = SavedFile(TEXT("manifest.json"));
	if (!PackageFolder.IsEmpty())
	{
		// Cheap when the package has not changed: the builder compares the
		// source JSON's size and mtime and returns the existing file.
		RunPython(FString::Printf(
			TEXT("import mlender_unreal as m; "
				 "m.actions.build_package_manifest(r\"%s\")"),
			*PackageFolder));
	}
	LoadManifest(Path);
	if (Tree.IsValid())
	{
		Tree->RequestTreeRefresh();
	}
}

bool SMLImportWindow::LoadManifest(const FString& Path)
{
	Roots.Reset();
	AllNodes.Reset();
	KindNames.Reset();
	TotalCount = 0;

	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("mLender: %s could not be read."), *Path);
		return false;
	}

	for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("kind_names")))
	{
		KindNames.Add(Value->AsString());
	}
	const TArray<TSharedPtr<FJsonValue>>& Names =
		Root->GetArrayField(TEXT("names"));
	const TArray<TSharedPtr<FJsonValue>>& Parents =
		Root->GetArrayField(TEXT("parents"));
	const TArray<TSharedPtr<FJsonValue>>& Kinds =
		Root->GetArrayField(TEXT("kinds"));
	if (Names.Num() != Parents.Num() || Names.Num() != Kinds.Num())
	{
		UE_LOG(LogTemp, Warning,
			TEXT("mLender: the manifest's arrays disagree (%d/%d/%d)."),
			Names.Num(), Parents.Num(), Kinds.Num());
		return false;
	}

	AllNodes.Reserve(Names.Num());
	for (int32 Index = 0; Index < Names.Num(); ++Index)
	{
		TSharedPtr<FMLNode> Node = MakeShared<FMLNode>();
		Node->Name = Names[Index]->AsString();
		Node->Parent = static_cast<int32>(Parents[Index]->AsNumber());
		Node->Kind = static_cast<int32>(Kinds[Index]->AsNumber());
		AllNodes.Add(Node);
	}
	// Parents come before children, so one forward pass wires the tree.
	for (int32 Index = 0; Index < AllNodes.Num(); ++Index)
	{
		const TSharedPtr<FMLNode>& Node = AllNodes[Index];
		if (AllNodes.IsValidIndex(Node->Parent))
		{
			AllNodes[Node->Parent]->Children.Add(Node);
			Node->ParentNode = AllNodes[Node->Parent];
		}
		else
		{
			Roots.Add(Node);
		}
	}
	// A leaf counts itself; a group counts what is under it. Backwards, so
	// every child is already counted when its parent is reached.
	for (int32 Index = AllNodes.Num() - 1; Index >= 0; --Index)
	{
		const TSharedPtr<FMLNode>& Node = AllNodes[Index];
		if (Node->Children.Num() == 0)
		{
			Node->Count = Node->Kind == 0 ? 0 : 1;
		}
		if (AllNodes.IsValidIndex(Node->Parent))
		{
			AllNodes[Node->Parent]->Count += Node->Count;
		}
	}
	for (const TSharedPtr<FMLNode>& Node : Roots)
	{
		TotalCount += Node->Count;
	}
	for (const TSharedPtr<FMLNode>& Node : Roots)
	{
		Tree.IsValid() ? Tree->SetItemExpansion(Node, true) : void();
	}
	return true;
}

void SMLImportWindow::GetChildren(
	TSharedPtr<FMLNode> Node, TArray<TSharedPtr<FMLNode>>& OutChildren)
{
	if (!Node.IsValid())
	{
		return;
	}
	for (const TSharedPtr<FMLNode>& Child : Node->Children)
	{
		if (MatchesSearch(Child))
		{
			OutChildren.Add(Child);
		}
	}
}

bool SMLImportWindow::MatchesSearch(const TSharedPtr<FMLNode>& Node) const
{
	if (Search.IsEmpty() || !Node.IsValid())
	{
		return true;
	}
	if (Node->Name.Contains(Search))
	{
		return true;
	}
	// A branch stays visible while anything under it matches, or the match
	// would be unreachable.
	for (const TSharedPtr<FMLNode>& Child : Node->Children)
	{
		if (MatchesSearch(Child))
		{
			return true;
		}
	}
	return false;
}

ECheckBoxState SMLImportWindow::StateOf(TSharedPtr<FMLNode> Node) const
{
	if (!Node.IsValid())
	{
		return ECheckBoxState::Unchecked;
	}
	if (Node->Children.Num() == 0)
	{
		return Node->bChecked
			? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
	}
	bool bAny = false;
	bool bAll = true;
	for (const TSharedPtr<FMLNode>& Child : Node->Children)
	{
		const ECheckBoxState State = StateOf(Child);
		bAny |= State != ECheckBoxState::Unchecked;
		bAll &= State == ECheckBoxState::Checked;
	}
	if (Node->bChecked)
	{
		bAny = true;
	}
	else
	{
		bAll = false;
	}
	if (bAll)
	{
		return ECheckBoxState::Checked;
	}
	return bAny ? ECheckBoxState::Undetermined : ECheckBoxState::Unchecked;
}

void SMLImportWindow::SetChecked(TSharedPtr<FMLNode> Node, bool bChecked)
{
	if (!Node.IsValid())
	{
		return;
	}
	Node->bChecked = bChecked;
	for (const TSharedPtr<FMLNode>& Child : Node->Children)
	{
		SetChecked(Child, bChecked);
	}
}

int32 SMLImportWindow::CheckedCount() const
{
	int32 Count = 0;
	for (const TSharedPtr<FMLNode>& Node : AllNodes)
	{
		if (Node->bChecked && Node->Children.Num() == 0 && Node->Kind != 0)
		{
			++Count;
		}
	}
	return Count;
}

FString SMLImportWindow::PathOf(const TSharedPtr<FMLNode>& Node) const
{
	TArray<FString> Parts;
	TSharedPtr<FMLNode> Walk = Node;
	while (Walk.IsValid())
	{
		Parts.Insert(Walk->Name, 0);
		Walk = Walk->ParentNode.Pin();
	}
	return TEXT("|") + FString::Join(Parts, TEXT("|"));
}

void SMLImportWindow::CollectSelection(TArray<FString>& OutPaths) const
{
	// Only the highest fully-ticked nodes: include_paths already means "this
	// and everything under it", so listing the descendants would say the
	// same thing in a much larger file.
	TFunction<void(const TSharedPtr<FMLNode>&)> Walk =
		[&](const TSharedPtr<FMLNode>& Node)
	{
		if (!Node.IsValid())
		{
			return;
		}
		const ECheckBoxState State = StateOf(Node);
		if (State == ECheckBoxState::Checked)
		{
			OutPaths.Add(PathOf(Node));
			return;
		}
		if (State == ECheckBoxState::Unchecked)
		{
			return;
		}
		for (const TSharedPtr<FMLNode>& Child : Node->Children)
		{
			Walk(Child);
		}
	};
	for (const TSharedPtr<FMLNode>& Node : Roots)
	{
		Walk(Node);
	}
}

FReply SMLImportWindow::Import()
{
	TArray<FString> Paths;
	CollectSelection(Paths);
	const bool bAll = Paths.Num() == Roots.Num() && CheckedCount() == TotalCount;

	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetNumberField(TEXT("selection_version"), 1);
	Root->SetStringField(TEXT("package_folder"), PackageFolder);
	Root->SetBoolField(TEXT("include_all"), bAll);
	TArray<TSharedPtr<FJsonValue>> Values;
	for (const FString& Path : Paths)
	{
		Values.Add(MakeShared<FJsonValueString>(Path));
	}
	Root->SetArrayField(TEXT("include_paths"), Values);

	FString Text;
	const TSharedRef<TJsonWriter<>> Writer =
		TJsonWriterFactory<>::Create(&Text);
	FJsonSerializer::Serialize(Root, Writer);

	// Written whole and then moved into place, so Python can never read a
	// half-written selection.
	const FString Final = SavedFile(TEXT("selection.json"));
	const FString Temp = Final + TEXT(".tmp");
	if (!FFileHelper::SaveStringToFile(Text, *Temp))
	{
		UE_LOG(LogTemp, Warning,
			TEXT("mLender: the selection could not be written to %s"), *Temp);
		return FReply::Handled();
	}
	IFileManager::Get().Move(*Final, *Temp, /*bReplace=*/true);

	RunPython(TEXT("import mlender_unreal; "
				   "mlender_unreal.actions.import_selected()"));
	return FReply::Handled();
}

FText SMLImportWindow::FooterText() const
{
	if (AllNodes.Num() == 0)
	{
		return LOCTEXT("NoPackage",
			"No package loaded. Browse to a folder Maya wrote.");
	}
	return FText::FromString(FString::Printf(
		TEXT("%d of %d object(s) ticked, in %d node(s)"),
		CheckedCount(), TotalCount, AllNodes.Num()));
}

TSharedRef<ITableRow> SMLImportWindow::MakeRow(
	TSharedPtr<FMLNode> Node, const TSharedRef<STableViewBase>& Owner)
{
	const FString Kind = KindNames.IsValidIndex(Node->Kind)
		? KindNames[Node->Kind] : FString();
	FString Label = Node->Name;
	if (Node->Count > 1)
	{
		Label += FString::Printf(TEXT("   (%d)"), Node->Count);
	}

	return SNew(STableRow<TSharedPtr<FMLNode>>, Owner)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(SCheckBox)
				.IsChecked_Lambda([this, Node]() { return StateOf(Node); })
				.OnCheckStateChanged_Lambda(
					[this, Node](ECheckBoxState State)
				{
					SetChecked(Node, State == ECheckBoxState::Checked);
				})
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
				.Padding(4.0f, 0.0f)
			[
				SNew(STextBlock).Text(FText::FromString(Label))
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(STextBlock)
				.Text(FText::FromString(Kind))
				.Font(FAppStyle::Get().GetFontStyle("SmallFont"))
				.ColorAndOpacity(FSlateColor::UseSubduedForeground())
			]
		];
}

#undef LOCTEXT_NAMESPACE

#endif // WITH_EDITOR
