// Copyright mena-works. MIT licence, see the repository root.
#include "MLMotionPlayer.h"

#include "Components/SceneComponent.h"
#include "Engine/World.h"
#include "MLMotionData.h"

AMLMotionPlayer::AMLMotionPlayer()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = true;
	// A paused PIE session still scrubs, and so does the Movie Render Queue.
	PrimaryActorTick.bTickEvenWhenPaused = true;
	SetCanBeDamaged(false);

	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Static);
	RootComponent = Root;
}

void AMLMotionPlayer::SetFrame(float NewFrame)
{
	Frame = NewFrame;
	ApplyFrame(Frame);
}

int32 AMLMotionPlayer::BindActors(const TArray<FString>& ObjectIds, const TArray<AActor*>& Actors)
{
	Bindings.Reset();
	if (Motion == nullptr || ObjectIds.Num() != Actors.Num())
	{
		return 0;
	}

	Bindings.Reserve(ObjectIds.Num());
	for (int32 Item = 0; Item < ObjectIds.Num(); ++Item)
	{
		AActor* Actor = Actors[Item];
		const int32 TrackIndex = Motion->FindTrack(ObjectIds[Item]);
		if (Actor == nullptr || TrackIndex < 0)
		{
			continue;
		}
		FMLMotionBinding Binding;
		Binding.ObjectId = ObjectIds[Item];
		Binding.Actor = Actor;
		Binding.TrackIndex = TrackIndex;
		for (const AActor* Parent = Actor->GetAttachParentActor(); Parent != nullptr;
			Parent = Parent->GetAttachParentActor())
		{
			++Binding.Depth;
		}
		Bindings.Add(MoveTemp(Binding));
	}

	// A sample is a world transform, and setting a parent's moves its
	// children with it -- so a child set before its parent ends up somewhere
	// else. Parents first, and the order holds for every frame after.
	Bindings.StableSort([](const FMLMotionBinding& A, const FMLMotionBinding& B)
	{
		return A.Depth < B.Depth;
	});

	AppliedFrame = TNumericLimits<float>::Lowest();
	return Bindings.Num();
}

int32 AMLMotionPlayer::GetBoundCount() const
{
	int32 Count = 0;
	for (const FMLMotionBinding& Binding : Bindings)
	{
		if (Binding.Actor != nullptr && Binding.TrackIndex >= 0)
		{
			++Count;
		}
	}
	return Count;
}

void AMLMotionPlayer::ApplyFrame(float AtFrame)
{
	AppliedFrame = AtFrame;
	if (Motion == nullptr)
	{
		return;
	}

	const UWorld* World = GetWorld();
	const bool bEditorWorld = World != nullptr && World->WorldType == EWorldType::Editor;

	FTransform Transform;
	for (FMLMotionBinding& Binding : Bindings)
	{
		AActor* Actor = Binding.Actor;
		if (!IsValid(Actor) || Binding.TrackIndex < 0)
		{
			continue;
		}
		if (Motion->Evaluate(Binding.TrackIndex, AtFrame, bInterpolate, Transform))
		{
			Actor->SetActorTransform(Transform, false, nullptr, ETeleportType::TeleportPhysics);
		}
		const int8 Visible = Motion->IsVisible(Binding.TrackIndex, AtFrame) ? 1 : 0;
		if (Visible != Binding.LastVisible)
		{
			Actor->SetActorHiddenInGame(Visible == 0);
#if WITH_EDITOR
			// The game flag does nothing in an editor viewport; this one does.
			if (bEditorWorld)
			{
				Actor->SetIsTemporarilyHiddenInEditor(Visible == 0);
			}
#endif
			Binding.LastVisible = Visible;
		}
	}
}

bool AMLMotionPlayer::EvaluateObject(const FString& ObjectId, float AtFrame, FTransform& OutTransform, bool& bOutVisible) const
{
	bOutVisible = true;
	if (Motion == nullptr)
	{
		return false;
	}
	const int32 TrackIndex = Motion->FindTrack(ObjectId);
	if (TrackIndex < 0)
	{
		return false;
	}
	bOutVisible = Motion->IsVisible(TrackIndex, AtFrame);
	return Motion->Evaluate(TrackIndex, AtFrame, bInterpolate, OutTransform);
}

AActor* AMLMotionPlayer::FindBoundActor(const FString& ObjectId) const
{
	for (const FMLMotionBinding& Binding : Bindings)
	{
		if (Binding.ObjectId == ObjectId)
		{
			return Binding.Actor;
		}
	}
	return nullptr;
}

void AMLMotionPlayer::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	// The setter covers Sequencer; this covers everything that writes the
	// property directly -- a Blueprint, a details panel undo, a level load.
	if (!FMath::IsNearlyEqual(Frame, AppliedFrame))
	{
		ApplyFrame(Frame);
	}
}

void AMLMotionPlayer::PostLoad()
{
	Super::PostLoad();
	// Nothing has been applied in this session, whatever the saved frame says.
	AppliedFrame = TNumericLimits<float>::Lowest();
	for (FMLMotionBinding& Binding : Bindings)
	{
		Binding.LastVisible = -1;
	}
}

#if WITH_EDITOR
void AMLMotionPlayer::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	Super::PostEditChangeProperty(PropertyChangedEvent);
	const FName Name = PropertyChangedEvent.GetPropertyName();
	if (Name == GET_MEMBER_NAME_CHECKED(AMLMotionPlayer, Frame)
		|| Name == GET_MEMBER_NAME_CHECKED(AMLMotionPlayer, Motion)
		|| Name == GET_MEMBER_NAME_CHECKED(AMLMotionPlayer, bInterpolate))
	{
		for (FMLMotionBinding& Binding : Bindings)
		{
			Binding.LastVisible = -1;
		}
		ApplyFrame(Frame);
	}
}
#endif
