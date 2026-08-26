// Copyright mena-works. MIT licence, see the repository root.
#pragma once

#if WITH_EDITOR

#include "CoreMinimal.h"

/**
 * The floating strip's lifetime, owned by nobody's layout.
 *
 * A borderless SWindow parented to the editor's root so it rides above the
 * viewport, draggable from anywhere on its body, hidden -- not destroyed --
 * by its own close button so its position survives the session. Python
 * persists visibility and position through the settings object.
 */
namespace FMLToolbar
{
	void Show();
	void Hide();
	bool IsVisible();
	/** Called by the module on shutdown; destroys the window for real. */
	void Shutdown();
}

#endif // WITH_EDITOR
