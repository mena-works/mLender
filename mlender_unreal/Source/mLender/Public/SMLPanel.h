// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#if WITH_EDITOR

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"

class IDetailsView;

/**
 * The receiver's panel: a details view of UMLSettings over a row of actions.
 *
 * Every button runs one Python call and nothing else. The implementations
 * live in actions.py so that the panel and the Tools menu cannot mean
 * different things by the same word, and so that a build with no compiled
 * module still has all of them from the menu.
 */
class SMLPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SMLPanel) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	TSharedPtr<IDetailsView> DetailsView;

	/** Slate button handler that runs one line of Python. */
	FReply RunPython(FString Command);

	/** The last import's summary, straight off the settings object so the
	 *  panel needs no notification to stay current. */
	FText SummaryText() const;
	FText StatusText() const;

	TSharedRef<class SWidget> MakeButton(
		const FText& Label, const FText& Tooltip, const FString& Command);
};

#endif // WITH_EDITOR
