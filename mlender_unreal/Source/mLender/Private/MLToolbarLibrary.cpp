// Copyright mena-works. MIT licence, see the repository root.
#include "MLToolbarLibrary.h"

#if WITH_EDITOR
#include "SMLToolbar.h"
#endif

void UMLToolbarLibrary::ShowToolbar()
{
#if WITH_EDITOR
	FMLToolbar::Show();
#endif
}

void UMLToolbarLibrary::HideToolbar()
{
#if WITH_EDITOR
	FMLToolbar::Hide();
#endif
}

bool UMLToolbarLibrary::IsToolbarVisible()
{
#if WITH_EDITOR
	return FMLToolbar::IsVisible();
#else
	return false;
#endif
}
