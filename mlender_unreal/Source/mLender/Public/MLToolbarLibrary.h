// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MLToolbarLibrary.generated.h"

/**
 * Python's handle on the floating strip.
 *
 * The strip is Slate and lives in the compiled module; Python probes
 * getattr(unreal, "MLToolbarLibrary", None) and treats absence as a valid
 * installation, the same rule every other compiled name follows. Outside the
 * editor these are no-ops rather than missing symbols, because the module is
 * Runtime and the class has to link everywhere the module does.
 */
UCLASS()
class MLENDER_API UMLToolbarLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "mLender")
	static void ShowToolbar();

	UFUNCTION(BlueprintCallable, Category = "mLender")
	static void HideToolbar();

	UFUNCTION(BlueprintCallable, Category = "mLender")
	static bool IsToolbarVisible();
};
