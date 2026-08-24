// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MLMotionPlayer.generated.h"

class UMLMotionData;

/** One mover: the actor in the level and the track that drives it. */
USTRUCT()
struct MLENDER_API FMLMotionBinding
{
	GENERATED_BODY()

	UPROPERTY()
	FString ObjectId;

	UPROPERTY()
	TObjectPtr<AActor> Actor = nullptr;

	UPROPERTY()
	int32 TrackIndex = -1;

	/** How many attach parents the actor has; parents are moved before children. */
	UPROPERTY()
	int32 Depth = 0;

	/** -1 unknown, else the last visibility written, so a frame only touches what changed. */
	int8 LastVisible = -1;
};

/**
 * Plays a package's sampled motion onto the level's mesh actors.
 *
 * Why this exists, and why it is C++ in a plugin that is otherwise Python:
 *
 * A Level Sequence keys one binding per actor, and a binding is a row in the
 * Sequencer outliner. A shot of 7562 rigid movers made a 349 MB sequence the
 * editor would not open at all, and splitting it into sub-sequences only moved
 * the rows somewhere the user still had to avoid opening. So the movers are
 * taken out of the sequence entirely: the sequence keys **one** float, Frame,
 * on this actor, and the actor sets every mover's world transform itself.
 *
 * That needs two things Blueprint cannot do. The actor must update while the
 * user scrubs in the editor, where Blueprint Tick does not run --
 * ShouldTickIfViewportsOnly and PostEditChangeProperty are C++. And Sequencer
 * calls a property's setter by name when one exists, so SetFrame applies the
 * frame the moment the ruler moves rather than a tick later.
 *
 * The transforms are world space and already in Unreal's frame; the Python
 * side does the Maya conversion and the anchoring to where Interchange placed
 * each actor, exactly as it did when the keys went onto the sequence.
 */
UCLASS(BlueprintType, HideCategories = (Rendering, Replication, Collision, Input, HLOD, Physics, Networking, LOD, Cooking, DataLayers, WorldPartition, LevelInstance))
class MLENDER_API AMLMotionPlayer : public AActor
{
	GENERATED_BODY()

public:
	AMLMotionPlayer();

	/** The frame being shown. Keyed by the Level Sequence; may be fractional. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category = "mLender", meta = (DisplayPriority = 1))
	float Frame = 0.0f;

	/** The motion this actor plays. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "mLender")
	TObjectPtr<UMLMotionData> Motion;

	/** Interpolate between kept samples, which is what motion blur and sub-frame rendering need. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "mLender")
	bool bInterpolate = true;

	UPROPERTY(VisibleAnywhere, Category = "mLender")
	TArray<FMLMotionBinding> Bindings;

	/**
	 * Set Frame and place the movers for it. Python's entry point.
	 *
	 * NOT named SetFrame, and the name is the whole point. Sequencer resolves
	 * a property to one of two paths, and FPropertyRegistry::ResolveFastProperty
	 * refuses the fast one when the class has a function called
	 * "Set" + PropertyName -- so a setter named SetFrame put Frame on the slow
	 * FTrackInstancePropertyBindings path. Measured on a real shot: on that
	 * path, dragging the playhead called the setter every time and playing
	 * called it exactly once, at the first frame, while the ruler ran to 519.
	 * The level played in PIE, where the actor ticks, and stood still in the
	 * editor. With no such function the engine writes Frame directly and Tick
	 * picks it up: measured again, Frame follows the ruler through playback
	 * and dragging both.
	 */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	void JumpToFrame(float NewFrame);

	/**
	 * Pair each object id with its actor, in the order given, keeping only
	 * the ones the motion asset has a track for. Returns how many were bound.
	 */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	int32 BindActors(const TArray<FString>& ObjectIds, const TArray<AActor*>& Actors);

	UFUNCTION(BlueprintCallable, Category = "mLender")
	int32 GetBoundCount() const;

	/** Move every bound actor to where it is at a frame. */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	void ApplyFrame(float AtFrame);

	/** What a bound object's transform and visibility are at a frame, without moving anything. */
	UFUNCTION(BlueprintCallable, Category = "mLender")
	bool EvaluateObject(const FString& ObjectId, float AtFrame, FTransform& OutTransform, bool& bOutVisible) const;

	UFUNCTION(BlueprintCallable, Category = "mLender")
	AActor* FindBoundActor(const FString& ObjectId) const;

	virtual void Tick(float DeltaSeconds) override;
	virtual bool ShouldTickIfViewportsOnly() const override { return true; }
	virtual void PostLoad() override;

#if WITH_EDITOR
	virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif

private:
	/** The frame the actors were last moved to, so a tick with nothing new costs nothing. */
	float AppliedFrame = TNumericLimits<float>::Lowest();
};
