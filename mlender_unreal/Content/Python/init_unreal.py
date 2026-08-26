# -*- coding: utf-8 -*-
"""Plugin bootstrap.

Unreal runs any init_unreal.py it finds on a plugin's Python path at editor
startup, and puts that folder on sys.path itself. So this file exists only to
register the menu; the package beside it is what does the work.

Failures are caught and logged. A plugin that raises during startup can leave
the editor without its menus, and an artist has no way to see why.
"""

import unreal


try:
    import mlender_unreal

    # Before the menu, because the menu's labels carry the settings' values:
    # drawing first would state the defaults and then quietly disagree with
    # the file.
    mlender_unreal.settings.load()
    # The strip may have been created from the compiled defaults
    # before this load ran; settle it to the stored choice.
    mlender_unreal.actions.sync_toolbar()

    # Reported from the return value rather than announced: there is no menu
    # to hang anything on in a headless commandlet, and a startup line naming
    # a menu that is not there sends the reader looking for it.
    if mlender_unreal.register():
        unreal.log(
            "mLender {0} loaded. Tools > mLender".format(
                mlender_unreal.BUILD_VERSION
            )
        )
    else:
        unreal.log(
            "mLender {0} loaded without its menu (no editor UI here). Use "
            "mlender_unreal.start_listener() from Python.".format(
                mlender_unreal.BUILD_VERSION
            )
        )
except Exception as exc:  # pragma: no cover - startup guard
    unreal.log_error("mLender failed to load: {0}".format(exc))
