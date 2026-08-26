// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "MLSettings.generated.h"

/**
 * The receiver's settings, as an object a details view can draw.
 *
 * The values live in Python -- settings.py owns them, writes them to
 * <project>/Saved/mLender/settings.json and answers for them whether this
 * module is compiled or not. This object is a *surface*, not a store: Python
 * mirrors into it after every change and reads back out of it before every
 * import. The reading direction is pull, so a panel edit reaches the next
 * import without this class knowing anything happened.
 *
 * Every property name here is a contract with settings.py, checked by nothing
 * at compile time: Unreal's Python maps ImportScale to "import_scale" and
 * bImportLights to "import_lights", so a rename on either side silently stops
 * mirroring. check_contracts.py reads this header against SETTING_SPECS.
 */
UCLASS(BlueprintType)
class MLENDER_API UMLSettings : public UObject
{
	GENERATED_BODY()

public:
	/** Multiplies the whole send: the meshes through Interchange and the
	 *  motion, cameras and locators through the JSON. Measured at 10 on a
	 *  200 m shot: geometry and motion both scaled once, not twice. */
	UPROPERTY(EditAnywhere, Category = "Import", meta = (ClampMin = "0.0001"))
	float ImportScale = 1.0f;

	/** An artistic multiplier over the measured light conversion. The
	 *  conversion is exact, so 1.0 matches the Maya render. */
	UPROPERTY(EditAnywhere, Category = "Import", meta = (ClampMin = "0.0"))
	float PowerScale = 1.0f;

	/** Leave the lighting this level already has in place. Lights a previous
	 *  send made are still replaced. */
	UPROPERTY(EditAnywhere, Category = "Import")
	bool bKeepExistingLights = false;

	UPROPERTY(EditAnywhere, Category = "Import")
	bool bImportLights = true;

	UPROPERTY(EditAnywhere, Category = "Import")
	bool bImportCameras = true;

	UPROPERTY(EditAnywhere, Category = "Import")
	bool bImportAnimation = true;

	/** Maya's selection sets and display layers, rebuilt as Unreal Layers. */
	UPROPERTY(EditAnywhere, Category = "Import")
	bool bImportSets = true;

	/** Off keeps the ML_ materials this project already has -- your tuned
	 *  instances survive the next send untouched. New shaders are still
	 *  built either way. */
	UPROPERTY(EditAnywhere, Category = "Import")
	bool bUpdateMaterials = true;

	/** Which camera to make the shot's own. Blank takes the renderable one,
	 *  which is what the package itself says. */
	UPROPERTY(EditAnywhere, Category = "Import")
	FString ActiveCamera;

	/** Objects Maya had hidden go into a layer, because that is the only
	 *  hiding the editor keeps. This decides whether that layer starts on. */
	UPROPERTY(EditAnywhere, Category = "Import")
	bool bRevealHiddenLayer = false;

	UPROPERTY(EditAnywhere, Category = "Import")
	bool bOpenReportWhenDone = false;

	/** none, groups, sets or layers -- the categories the package itself
	 *  carries. The receiver never invents one the sender did not send. */
	UPROPERTY(EditAnywhere, Category = "Filter")
	FString FilterKind = TEXT("none");

	UPROPERTY(EditAnywhere, Category = "Filter")
	TArray<FString> FilterNames;

	/** Build everything except what is named, rather than only what is. */
	UPROPERTY(EditAnywhere, Category = "Filter")
	bool bFilterInvert = false;

	UPROPERTY(EditAnywhere, Category = "Package")
	FDirectoryPath LastPackageFolder;

	UPROPERTY(EditAnywhere, Category = "LiveLink")
	FString LivelinkHost = TEXT("127.0.0.1");

	UPROPERTY(EditAnywhere, Category = "LiveLink", meta = (ClampMin = "1", ClampMax = "65535"))
	int32 LivelinkPort = 50505;

	/** What the last import did. Written by Python, read by the panel, and
	 *  deliberately not saved -- a summary from a previous session describes
	 *  a level that may no longer be open.
	 *
	 *  EditAnywhere rather than VisibleAnywhere because VisibleAnywhere is
	 *  read-only to Python: set_editor_property throws, and the first version
	 *  of this swallowed that and drew an empty panel. */
	UPROPERTY(EditAnywhere, Transient, Category = "Last Import")
	FString LastSummary;
};
