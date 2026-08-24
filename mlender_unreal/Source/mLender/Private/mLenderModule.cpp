// Copyright mena-works. MIT licence, see the repository root.
#include "Modules/ModuleManager.h"

// Nothing to start or stop: the module exists to carry two UCLASSes, and
// the reflection system registers those on load.
IMPLEMENT_MODULE(FDefaultModuleImpl, mLender);
