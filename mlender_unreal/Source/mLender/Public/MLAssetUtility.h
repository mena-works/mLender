// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MLAssetUtility.generated.h"

/**
 * What the Python side cannot do through reflection.
 *
 * Getting rid of an unsaved asset nothing references should cost nothing,
 * and through the editor's delete it costs a reference walk per asset:
 * measured, 7960 duplicate meshes took nine minutes of a fourteen minute
 * import. A rename into the transient package is instant, but Python cannot
 * tell the asset registry about it, and the browser then lists a ghost the
 * save walks into. This does both, and marks the object for the next
 * garbage collection.
 */
UCLASS()
class MLENDER_API UMLAssetUtility : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Move unsaved assets nothing points at out of their packages, off the
	 * asset registry and onto the garbage list. Returns how many went. Only
	 * for assets that have never been saved: a package on disk is not
	 * touched by this, and would still be there afterwards.
	 */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	static int32 DiscardUnsavedAssets(const TArray<UObject*>& Assets);
};
