// Copyright mena-works. MIT licence, see the repository root.
#include "MLAssetUtility.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "UObject/Package.h"

int32 UMLAssetUtility::DiscardUnsavedAssets(const TArray<UObject*>& Assets)
{
	int32 Discarded = 0;
	UPackage* Transient = GetTransientPackage();
	for (UObject* Asset : Assets)
	{
		if (!IsValid(Asset) || Asset->GetOutermost() == Transient)
		{
			continue;
		}
		UPackage* Package = Asset->GetOutermost();

		// The registry first, while the asset still has the path it was
		// registered under; afterwards there is nothing to match.
		FAssetRegistryModule::AssetDeleted(Asset);

		// No redirector, no transaction, no loader reset: the asset was made
		// this session and never saved, so there is nothing on disk to point
		// at it and nothing to undo into.
		const bool bMoved = Asset->Rename(
			nullptr, Transient,
			REN_DontCreateRedirectors | REN_NonTransactional | REN_ForceNoResetLoaders);
		if (!bMoved)
		{
			continue;
		}
		Asset->ClearFlags(RF_Standalone | RF_Public);
		Asset->MarkAsGarbage();

		// The package it came from is now empty and dirty, and a dirty
		// package is what the editor asks about on exit.
		if (Package != nullptr && Package != Transient)
		{
			Package->SetDirtyFlag(false);
			Package->ClearFlags(RF_Standalone);
			Package->MarkAsGarbage();
		}
		++Discarded;
	}
	return Discarded;
}
