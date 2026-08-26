// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#if WITH_EDITOR

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"

class UMLSettings;

/** The settings tab's id, defined in mLenderModule.cpp. The strip invokes
 *  it, and check_contracts.py reads the name so a rename is noticed. */
extern const FName MLPanelTabName;

/**
 * The receiver's panel, laid out by hand.
 *
 * The first version drew a generic property grid (IDetailsView) under the
 * buttons, and it read as what it was: the engine's face, not the tool's.
 * This one is built the way Dash's panel is -- measured, not guessed: that
 * plugin ships no widget uasset, no Qt and no HTML, and its DLL links
 * SDockTab and SCompoundWidget, so a panel of that shape is hand-arranged
 * Slate. One big action, the few settings a shot actually touches, and
 * everything else folded away.
 *
 * Every button runs one Python call and nothing else. The implementations
 * live in actions.py so the panel and the Tools menu cannot mean different
 * things by the same word, and a build with no compiled module keeps all of
 * it from the menu.
 *
 * Widgets read the UMLSettings default object through attributes, so they are
 * always current without any notification; edits write the object and then
 * one Python line pulls it into the dict and the settings file. Pull, never
 * push -- two writers on one value is the bug this repo keeps finding.
 */
class SMLPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SMLPanel) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	static UMLSettings* Settings();

	/** Slate button handler that runs one line of Python. */
	FReply RunPython(FString Command);

	/** Pull the panel's edits into Python and the settings file. */
	void Persist();

	FText SummaryText() const;

	TSharedRef<class SWidget> MakeButton(
		const FText& Label, const FText& Tooltip, const FString& Command,
		bool bPrimary = false);
	TSharedRef<class SWidget> MakeCheck(
		const FText& Label, const FText& Tooltip, bool UMLSettings::*Field);
	TSharedRef<class SWidget> Labelled(
		const FText& Label, TSharedRef<class SWidget> Widget);
	TSharedRef<class SWidget> SectionTitle(const FText& Label);
};

#endif // WITH_EDITOR
