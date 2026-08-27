// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#if WITH_EDITOR

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/STreeView.h"

/**
 * One node of the package's Maya hierarchy, as the tree holds it.
 *
 * The manifest arrives as parallel arrays with every parent before its
 * children, so the whole tree is built in one forward pass and each full DAG
 * path is reconstructed by walking Parent -- exact, because the names are raw
 * DAG components with their FBX escapes untouched.
 */
struct FMLNode
{
	FString Name;
	int32 Parent = INDEX_NONE;
	int32 Kind = 0;
	/** Meshes and other records under here, this node included. */
	int32 Count = 0;
	bool bChecked = true;
	TArray<TSharedPtr<FMLNode>> Children;
	TWeakPtr<FMLNode> ParentNode;
};

/**
 * The Import window: pick a package, tick what comes in, build it.
 *
 * The tree never reads the package's own JSON -- 46 MB on a real shot. Python
 * writes a compact manifest (parallel name/parent/kind arrays, ~500 KB for
 * 12,388 nodes, cached against the source file's size and mtime) and this
 * reads that. The ticks go back the same way, as a selection file, because
 * five thousand DAG names have no business in a Python command string.
 */
class SMLImportWindow : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SMLImportWindow) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	TArray<TSharedPtr<FMLNode>> Roots;
	TArray<TSharedPtr<FMLNode>> AllNodes;
	TSharedPtr<STreeView<TSharedPtr<FMLNode>>> Tree;
	TArray<FString> KindNames;
	FString PackageFolder;
	FString Search;
	int32 TotalCount = 0;

	/** Ask Python for a manifest, then read it. */
	void Browse();
	void ReloadManifest();
	bool LoadManifest(const FString& Path);

	TSharedRef<ITableRow> MakeRow(
		TSharedPtr<FMLNode> Node,
		const TSharedRef<STableViewBase>& Owner);
	void GetChildren(TSharedPtr<FMLNode> Node,
		TArray<TSharedPtr<FMLNode>>& OutChildren);

	void SetChecked(TSharedPtr<FMLNode> Node, bool bChecked);
	ECheckBoxState StateOf(TSharedPtr<FMLNode> Node) const;
	int32 CheckedCount() const;
	FString PathOf(const TSharedPtr<FMLNode>& Node) const;

	/** The highest fully-ticked nodes: a checked branch implies its children,
	 *  which is what include_paths means, and it keeps the file small. */
	void CollectSelection(TArray<FString>& OutPaths) const;
	FReply Import();

	FText FooterText() const;
	bool MatchesSearch(const TSharedPtr<FMLNode>& Node) const;
};

#endif // WITH_EDITOR
