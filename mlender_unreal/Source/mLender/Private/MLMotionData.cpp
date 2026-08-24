// Copyright mena-works. MIT licence, see the repository root.
#include "MLMotionData.h"

#include "UObject/Package.h"

#if WITH_EDITOR
#include "AssetRegistry/AssetRegistryModule.h"
#endif

namespace
{
	// Ten floats per sample, in the order the Python side writes them.
	constexpr int32 FloatsPerSample = 10;

	// The index of the last frame at or before AtFrame, or -1 before the first.
	int32 LastAtOrBefore(const TArray<int32>& Frames, float AtFrame)
	{
		int32 Low = 0;
		int32 High = Frames.Num();
		while (Low < High)
		{
			const int32 Mid = (Low + High) / 2;
			if (static_cast<float>(Frames[Mid]) <= AtFrame + KINDA_SMALL_NUMBER)
			{
				Low = Mid + 1;
			}
			else
			{
				High = Mid;
			}
		}
		return Low - 1;
	}
}

int32 UMLMotionData::AddTrack(const FString& ObjectId, const TArray<int32>& Frames,
	const TArray<float>& Values, const TArray<int32>& VisibilityFrames,
	const TArray<bool>& VisibilityValues)
{
	const int32 Count = Frames.Num();
	if (Count == 0 || Values.Num() != Count * FloatsPerSample
		|| VisibilityFrames.Num() != VisibilityValues.Num())
	{
		return -1;
	}

	FMLMotionTrack Track;
	Track.ObjectId = ObjectId;
	Track.Frames = Frames;
	Track.Locations.Reserve(Count);
	Track.Rotations.Reserve(Count);
	Track.Scales.Reserve(Count);

	FQuat4f Previous = FQuat4f::Identity;
	for (int32 Sample = 0; Sample < Count; ++Sample)
	{
		const float* V = &Values[Sample * FloatsPerSample];
		Track.Locations.Add(FVector3f(V[0], V[1], V[2]));
		FQuat4f Rotation(V[3], V[4], V[5], V[6]);
		Rotation.Normalize();
		// q and -q are one rotation, but a slerp between them goes the long
		// way round. Keeping each sample on the same side as the last makes
		// the interpolation take the short arc a tumbling piece actually took.
		if (Sample > 0 && (Rotation | Previous) < 0.0f)
		{
			Rotation = -Rotation;
		}
		Previous = Rotation;
		Track.Rotations.Add(Rotation);
		Track.Scales.Add(FVector3f(V[7], V[8], V[9]));
	}
	Track.VisibilityFrames = VisibilityFrames;
	Track.VisibilityValues = VisibilityValues;

	if (Tracks.Num() == 0)
	{
		FirstFrame = Frames[0];
		LastFrame = Frames.Last();
	}
	else
	{
		FirstFrame = FMath::Min(FirstFrame, Frames[0]);
		LastFrame = FMath::Max(LastFrame, Frames.Last());
	}

	const int32 TrackIndex = Tracks.Add(MoveTemp(Track));
	Index.Add(ObjectId, TrackIndex);
	MarkPackageDirty();
	return TrackIndex;
}

int32 UMLMotionData::GetKeyCount() const
{
	int32 Total = 0;
	for (const FMLMotionTrack& Track : Tracks)
	{
		Total += Track.Frames.Num();
	}
	return Total;
}

TArray<FString> UMLMotionData::GetObjectIds() const
{
	TArray<FString> Ids;
	Ids.Reserve(Tracks.Num());
	for (const FMLMotionTrack& Track : Tracks)
	{
		Ids.Add(Track.ObjectId);
	}
	return Ids;
}

int32 UMLMotionData::FindTrack(const FString& ObjectId) const
{
	if (Index.Num() != Tracks.Num())
	{
		const_cast<UMLMotionData*>(this)->RebuildIndex();
	}
	const int32* Found = Index.Find(ObjectId);
	return Found ? *Found : -1;
}

UMLMotionData* UMLMotionData::CreateMotionAsset(const FString& PackagePath, const FString& AssetName)
{
#if WITH_EDITOR
	if (PackagePath.IsEmpty() || AssetName.IsEmpty())
	{
		return nullptr;
	}
	const FString PackageName = PackagePath / AssetName;
	UPackage* Package = CreatePackage(*PackageName);
	if (Package == nullptr)
	{
		return nullptr;
	}
	Package->FullyLoad();
	UMLMotionData* Asset = NewObject<UMLMotionData>(
		Package, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
	if (Asset == nullptr)
	{
		return nullptr;
	}
	FAssetRegistryModule::AssetCreated(Asset);
	Package->MarkPackageDirty();
	return Asset;
#else
	return nullptr;
#endif
}

bool UMLMotionData::Evaluate(int32 TrackIndex, float AtFrame, bool bInterpolate, FTransform& OutTransform) const
{
	if (!Tracks.IsValidIndex(TrackIndex))
	{
		return false;
	}
	const FMLMotionTrack& Track = Tracks[TrackIndex];
	const int32 Count = Track.Frames.Num();
	if (Count == 0 || Track.Locations.Num() != Count
		|| Track.Rotations.Num() != Count || Track.Scales.Num() != Count)
	{
		return false;
	}

	int32 At = LastAtOrBefore(Track.Frames, AtFrame);
	float Alpha = 0.0f;
	if (At < 0)
	{
		At = 0;
	}
	else if (At < Count - 1 && bInterpolate)
	{
		const float Span = static_cast<float>(Track.Frames[At + 1] - Track.Frames[At]);
		if (Span > 0.0f)
		{
			Alpha = FMath::Clamp((AtFrame - static_cast<float>(Track.Frames[At])) / Span, 0.0f, 1.0f);
		}
	}

	if (Alpha <= 0.0f)
	{
		OutTransform = FTransform(
			FQuat(Track.Rotations[At]), FVector(Track.Locations[At]), FVector(Track.Scales[At]));
		return true;
	}

	const int32 Next = At + 1;
	OutTransform = FTransform(
		FQuat::Slerp(FQuat(Track.Rotations[At]), FQuat(Track.Rotations[Next]), Alpha),
		FMath::Lerp(FVector(Track.Locations[At]), FVector(Track.Locations[Next]), Alpha),
		FMath::Lerp(FVector(Track.Scales[At]), FVector(Track.Scales[Next]), Alpha));
	return true;
}

bool UMLMotionData::IsVisible(int32 TrackIndex, float AtFrame) const
{
	if (!Tracks.IsValidIndex(TrackIndex))
	{
		return true;
	}
	const FMLMotionTrack& Track = Tracks[TrackIndex];
	if (Track.VisibilityFrames.Num() == 0
		|| Track.VisibilityValues.Num() != Track.VisibilityFrames.Num())
	{
		return true;
	}
	const int32 At = LastAtOrBefore(Track.VisibilityFrames, AtFrame);
	// Before the first visibility key the object is as it was exported: the
	// first key states what it was at that frame, so it is the answer here too.
	return Track.VisibilityValues[FMath::Max(At, 0)];
}

void UMLMotionData::PostLoad()
{
	Super::PostLoad();
	RebuildIndex();
}

void UMLMotionData::RebuildIndex()
{
	Index.Reset();
	for (int32 TrackIndex = 0; TrackIndex < Tracks.Num(); ++TrackIndex)
	{
		Index.Add(Tracks[TrackIndex].ObjectId, TrackIndex);
	}
}
