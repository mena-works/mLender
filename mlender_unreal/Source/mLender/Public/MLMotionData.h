// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "MLMotionData.generated.h"

/**
 * One object's sampled motion: a world transform per kept frame, and the
 * frames at which its visibility switches.
 *
 * Sparse on purpose. The exporter samples every frame, but a piece of debris
 * sits still until it is hit and again once it lands, and the Python side
 * drops every sample that lies on the line between its neighbours before it
 * hands the track over. The evaluation interpolates, so nothing is lost.
 *
 * Single precision on purpose too: a shot is thousands of these, and a world
 * position in centimetres keeps a thousandth of a unit in a float.
 */
USTRUCT()
struct MLENDER_API FMLMotionTrack
{
	GENERATED_BODY()

	/** The Maya DAG path the exporter keyed the object by. */
	UPROPERTY()
	FString ObjectId;

	/** Frame numbers of the kept samples, ascending. */
	UPROPERTY()
	TArray<int32> Frames;

	UPROPERTY()
	TArray<FVector3f> Locations;

	UPROPERTY()
	TArray<FQuat4f> Rotations;

	UPROPERTY()
	TArray<FVector3f> Scales;

	/** Frames at which the visibility changes; the value applies from there on. */
	UPROPERTY()
	TArray<int32> VisibilityFrames;

	UPROPERTY()
	TArray<bool> VisibilityValues;
};

/**
 * The motion of every rigid mover in a package, as one asset.
 *
 * Kept as an asset rather than inside the player actor so the level stays a
 * level: a shot of seven thousand movers over five hundred frames is tens of
 * megabytes of keys, and a map that heavy is slow to open, save and diff.
 */
UCLASS(BlueprintType)
class MLENDER_API UMLMotionData : public UDataAsset
{
	GENERATED_BODY()

public:
	/** The first frame any track holds a sample at. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "mLender")
	int32 FirstFrame = 0;

	/** The last frame any track holds a sample at. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "mLender")
	int32 LastFrame = 0;

	UPROPERTY()
	TArray<FMLMotionTrack> Tracks;

	/**
	 * Append one object's track. Values holds ten floats per frame: location
	 * xyz, quaternion xyzw, scale xyz, all in Unreal world space. Returns the
	 * new track's index, or -1 when the arrays do not agree.
	 */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	int32 AddTrack(const FString& ObjectId, const TArray<int32>& Frames,
		const TArray<float>& Values, const TArray<int32>& VisibilityFrames,
		const TArray<bool>& VisibilityValues);

	UFUNCTION(BlueprintCallable, Category = "mLender")
	int32 GetTrackCount() const { return Tracks.Num(); }

	/** Transform samples across every track, which is what the asset costs. */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	int32 GetKeyCount() const;

	UFUNCTION(BlueprintCallable, Category = "mLender")
	TArray<FString> GetObjectIds() const;

	/** The track index for an object id, or -1. */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	int32 FindTrack(const FString& ObjectId) const;

	/**
	 * A new, empty asset at PackagePath/AssetName, registered so the Content
	 * Browser lists it. Editor only; returns null in a cooked build.
	 */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	static UMLMotionData* CreateMotionAsset(const FString& PackagePath, const FString& AssetName);

	/** The world transform of a track at a frame, interpolated between kept samples. */
	bool Evaluate(int32 TrackIndex, float AtFrame, bool bInterpolate, FTransform& OutTransform) const;

	/** Whether a track is visible at a frame. A track with no visibility keys always is. */
	bool IsVisible(int32 TrackIndex, float AtFrame) const;

	virtual void PostLoad() override;

private:
	void RebuildIndex();

	/** Object id to track index. Rebuilt on load; not saved. */
	TMap<FString, int32> Index;
};
