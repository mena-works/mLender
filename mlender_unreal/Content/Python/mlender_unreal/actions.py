# -*- coding: utf-8 -*-
"""What a button or a menu entry does.

One implementation per action, called from both surfaces, so the panel and the
menu can never mean different things by the same word. The panel is Slate and
reaches these through ExecPythonCommand; the menu reaches them through a
string command. Neither carries any logic of its own.

Two of these close gaps that had no filling at all: until now the receiver
could not import a package unless Maya pushed one, and the report it writes
beside every package was never named anywhere a user would look.
"""

import os
import subprocess
import sys

import unreal

import json

from .constants import (
    GENERATED_TAG,
    HIDDEN_LAYER_NAME,
    MANIFEST_FILE_NAME,
    MENU_WARNING_LIMIT,
    SELECTION_FILE_NAME,
)
from . import selection
from . import settings
from .importer import (
    import_scene_package,
    read_package_json,
    validate_schema_version,
)
from . import livelink


# An import may now start from a button as well as from the message pump, and
# the pump's safety was an accident: it takes the message off the queue before
# importing, so a re-entrant tick finds nothing. A button has no such luck, and
# import_scene_package pumps Slate ticks while it runs -- which is how a
# callback without a guard once recursed twenty-one deep and took the editor
# with it.
_importing = False


def log(line):
    unreal.log("mLender: {0}".format(line))


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def run_import(package_folder, package_data=None, include_paths=None):
    """The one door every import goes through."""
    global _importing
    if _importing:
        unreal.log_warning(
            "mLender: an import is already running; this one was refused "
            "rather than started on top of it."
        )
        return None
    folder = str(package_folder or "").strip()
    if not folder:
        unreal.log_warning("mLender: no package folder given.")
        return None
    _importing = True
    try:
        kwargs = livelink.accepted_kwargs(settings.import_kwargs())
        if include_paths is not None:
            # Deliberately never a setting: a selection is for this import,
            # and a stale one persisting would silently prune the next push.
            kwargs["include_paths"] = include_paths
        result = livelink.remember_result(import_scene_package(
            folder,
            package_data=package_data,
            **kwargs
        ))
    except Exception as exc:
        unreal.log_error("mLender: import failed: {0}".format(exc))
        return None
    finally:
        _importing = False
    settings.update(last_package_folder=folder)
    settings.set_summary(summary_line(result))
    log(summary_line(result))
    livelink.report_warnings(result)
    if result.get("report_path") and settings.get("open_report_when_done"):
        open_report()
    return result


def import_package_folder(folder=""):
    """Import a package the user picks, rather than one Maya pushed."""
    folder = str(folder or "").strip() or choose_folder()
    if not folder:
        return None
    return run_import(folder)


def reimport_last():
    folder = settings.get("last_package_folder") or ""
    if not folder:
        unreal.log_warning(
            "mLender: nothing has been imported yet, so there is nothing to "
            "do again."
        )
        return None
    return run_import(folder)


def choose_folder(start=""):
    """A folder picker, through whatever this build actually has.

    Unreal's own dialog is tried first. tkinter is the fallback because the
    embedded interpreter ships it -- an installer in this repo once died at
    startup for assuming the opposite about Blender's, so it is probed here
    rather than trusted.
    """
    start = str(start or settings.get("last_package_folder") or "")
    tools = getattr(unreal, "EditorDialog", None)
    picker = getattr(tools, "open_directory_dialog", None) if tools else None
    if picker is not None:
        try:
            chosen = picker("Choose a package folder", start)
            if chosen:
                return str(chosen[0] if isinstance(chosen, list) else chosen)
        except Exception:
            pass
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        try:
            chosen = filedialog.askdirectory(
                title="Choose a package folder", initialdir=start or None)
        finally:
            # Destroyed, not just withdrawn: a leaked root makes the second
            # call in a session fail rather than the first.
            root.destroy()
        return str(chosen or "")
    except Exception as exc:
        unreal.log_warning(
            "mLender: no folder picker is available here ({0}). Set the "
            "package folder in the panel, or call "
            "mlender_unreal.actions.run_import(r\"...\").".format(exc)
        )
    return ""


def _package_json_source(folder):
    """(name, mtime, size) of the package's JSON, the manifest's cache key."""
    try:
        names = [
            name for name in sorted(os.listdir(folder))
            if name.endswith("_scene.json") or name.endswith("_lookdev.json")
        ]
    except Exception:
        return "", 0.0, 0
    if not names:
        return "", 0.0, 0
    path = os.path.join(folder, names[0])
    try:
        info = os.stat(path)
    except Exception:
        return names[0], 0.0, 0
    return names[0], float(info.st_mtime), int(info.st_size)


def build_package_manifest(folder="", output_path=""):
    """Write the Import window's tree food for a package.

    The scene JSON is 42 MB on a real shot and the window must never parse
    it; this reads it once, writes a compact manifest, and on the next call
    for the same unchanged package returns the existing file without parsing
    anything. Returns the manifest path, or "" when there is nothing to
    write -- the window treats "" as "no tree".
    """
    folder = str(folder or settings.get("last_package_folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        unreal.log_warning(
            "mLender: no package folder to build a manifest for "
            "({0!r}).".format(folder)
        )
        return ""
    out = str(output_path or "").strip() or settings.saved_file_path(
        MANIFEST_FILE_NAME)
    if not out:
        unreal.log_warning(
            "mLender: no project to write the manifest under."
        )
        return ""

    name, mtime, size = _package_json_source(folder)
    if os.path.isfile(out):
        try:
            with open(out, "r") as handle:
                existing = json.load(handle)
            if (existing.get("package_folder") == folder
                    and existing.get("source_json") == name
                    and existing.get("source_mtime") == mtime
                    and existing.get("source_size") == size
                    and existing.get("manifest_version")
                    == selection.MANIFEST_VERSION):
                return out
        except Exception:
            pass

    try:
        package_data = read_package_json(folder)
        # Validated before the tree exists: the window must never offer a
        # tree for a package the import would refuse.
        validate_schema_version(package_data)
        payload = selection.manifest_payload(
            package_data, folder, source_name=name,
            source_mtime=mtime, source_size=size,
        )
    except Exception as exc:
        unreal.log_warning(
            "mLender: {0} could not be read for the manifest: {1}".format(
                folder, exc
            )
        )
        return ""
    try:
        parent = os.path.dirname(out)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(out, "w") as handle:
            json.dump(payload, handle, separators=(",", ":"))
    except Exception as exc:
        unreal.log_warning(
            "mLender: the manifest could not be written to {0}: {1}".format(
                out, exc
            )
        )
        return ""
    log("manifest: {0} node(s) -> {1}".format(payload["node_count"], out))
    return out


def import_selected(selection_path=""):
    """Import the package the selection file names, filtered to its ticks.

    The Import window writes the file and calls this; the file is how 5,000
    DAG paths reach Python without riding a command string. An empty
    selection is refused here, before run_import, so the level is never
    cleared for nothing.
    """
    path = str(selection_path or "").strip() or settings.saved_file_path(
        SELECTION_FILE_NAME)
    try:
        folder, include_paths = selection.read_selection_file(path)
    except Exception as exc:
        unreal.log_warning("mLender: {0}".format(exc))
        return None
    return run_import(folder, include_paths=include_paths)


def summary_line(result=None):
    result = result if result is not None else livelink.last_result()
    if not result:
        return "No import yet this session."
    seconds = result.get("total_seconds") or 0.0
    filtered = ""
    if result.get("filtered_out_count"):
        filtered = ", {0} filtered out".format(result["filtered_out_count"])
    return (
        "{0} mesh(es) on {1} asset(s), {2} material(s), {3} mover(s), "
        "{4} hidden, {5} warning(s), {6}{7}".format(
            result.get("mesh_count", 0),
            result.get("mesh_asset_count", 0),
            result.get("material_count", 0),
            result.get("motion_object_count", 0),
            result.get("hidden_count", 0),
            len(result.get("warnings") or []),
            _duration(seconds),
            filtered,
        )
    )


def _duration(seconds):
    seconds = float(seconds or 0.0)
    if seconds < 60.0:
        return "{0:.1f} s".format(seconds)
    return "{0:d} min {1:02d} s".format(
        int(seconds // 60), int(round(seconds % 60))
    )


def show_last_summary():
    """The counts, the timings and the first warnings, in the log."""
    result = livelink.last_result()
    if not result:
        log("No import yet this session.")
        return ""
    log(summary_line(result))
    for label, taken in (result.get("timings") or []):
        unreal.log("    {0:<52} {1}".format(label[:52], _duration(taken)))
    warnings = list(result.get("warnings") or [])
    for warning in warnings[:MENU_WARNING_LIMIT]:
        unreal.log_warning("    {0}".format(warning))
    if len(warnings) > MENU_WARNING_LIMIT:
        unreal.log_warning(
            "    ... and {0} more.".format(len(warnings) - MENU_WARNING_LIMIT)
        )
    report = result.get("report_path") or ""
    if report:
        log("report: {0}".format(report))
    return summary_line(result)


def _open_on_disk(path):
    path = str(path or "")
    if not path or not os.path.exists(path):
        unreal.log_warning(
            "mLender: nothing to open at {0!r}.".format(path)
        )
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 - the editor's own shell open
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        unreal.log_warning(
            "mLender: {0} could not be opened: {1}".format(path, exc)
        )
        return False
    return True


def open_report():
    """The report the importer writes beside every package.

    It has always been written and its path has never been shown, so nobody
    has read it. It holds every warning; the log shows the first few.
    """
    result = livelink.last_result() or {}
    report = result.get("report_path") or ""
    if not report:
        folder = settings.get("last_package_folder") or ""
        if folder and os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith("_import_unreal.txt"):
                    report = os.path.join(folder, name)
                    break
    if not report:
        unreal.log_warning(
            "mLender: no import report yet. One is written beside the "
            "package every time a package is imported."
        )
        return False
    return _open_on_disk(report)


def open_package_folder():
    return _open_on_disk(settings.get("last_package_folder") or "")


def set_hidden_layer_visible(state=True):
    """Show or hide the objects Maya had hidden.

    They live in a layer because that is the only hiding the editor keeps: the
    actor flag Python can set is "temporarily" hidden and does not survive
    reopening the level.
    """
    try:
        layers = unreal.get_editor_subsystem(unreal.LayersSubsystem)
        layers.set_layers_visibility(
            [unreal.Name(HIDDEN_LAYER_NAME)], bool(state))
    except Exception as exc:
        unreal.log_warning(
            "mLender: the {0} layer could not be switched: {1}".format(
                HIDDEN_LAYER_NAME, exc
            )
        )
        return False
    settings.update(reveal_hidden_layer=bool(state))
    log("{0} is now {1}.".format(
        HIDDEN_LAYER_NAME, "visible" if state else "hidden"))
    return True


def toggle_hidden_layer():
    return set_hidden_layer_visible(not settings.get("reveal_hidden_layer"))


def level_cameras():
    """The cameras in the level, by label, for a menu or a drop-down."""
    labels = []
    for actor in (_actor_subsystem().get_all_level_actors() or []):
        try:
            if actor.get_class().get_name().endswith("CameraActor"):
                labels.append(str(actor.get_actor_label()))
        except Exception:
            continue
    return sorted(labels)


def pilot_camera(label=""):
    """Look through a camera, or stop looking through one when given none."""
    subsystem = getattr(unreal, "LevelEditorSubsystem", None)
    if subsystem is None:
        unreal.log_warning("mLender: this build has no LevelEditorSubsystem.")
        return False
    editor = unreal.get_editor_subsystem(subsystem)
    label = str(label or "").strip()
    if not label:
        try:
            editor.eject_pilot_level_actor()
            return True
        except Exception as exc:
            unreal.log_warning("mLender: could not eject: {0}".format(exc))
            return False
    for actor in (_actor_subsystem().get_all_level_actors() or []):
        try:
            if str(actor.get_actor_label()) != label:
                continue
        except Exception:
            continue
        try:
            editor.pilot_level_actor(actor)
            log("looking through {0}.".format(label))
            return True
        except Exception as exc:
            unreal.log_warning(
                "mLender: could not look through {0}: {1}".format(label, exc)
            )
            return False
    unreal.log_warning(
        "mLender: no actor in this level is labelled {0!r}.".format(label)
    )
    return False


def select_generated_actors():
    """Select everything this tool made, and say how many that is."""
    subsystem = _actor_subsystem()
    made = []
    for actor in (subsystem.get_all_level_actors() or []):
        try:
            if GENERATED_TAG in [str(tag) for tag in (actor.tags or [])]:
                made.append(actor)
        except Exception:
            continue
    try:
        subsystem.set_selected_level_actors(made)
    except Exception as exc:
        unreal.log_warning("mLender: could not select: {0}".format(exc))
        return 0
    log("selected {0} actor(s) this tool made.".format(len(made)))
    return len(made)


def package_options(kind=""):
    """The group, set or layer names the last package carries.

    Read from the package rather than from the level, so the list is what can
    be asked for on the next import rather than what happened to survive the
    last one.
    """
    kind = str(kind or settings.get("filter_kind") or "none")
    folder = settings.get("last_package_folder") or ""
    if kind == "none" or not folder:
        return []
    try:
        package_data = read_package_json(folder)
    except Exception as exc:
        unreal.log_warning(
            "mLender: {0} could not be read: {1}".format(folder, exc)
        )
        return []
    names = set()
    if kind == "groups":
        for record in (package_data.get("meshes") or []):
            for group in (record.get("groups") or []):
                names.add(str(group))
    elif kind == "sets":
        for key in ("selection_sets", "object_sets"):
            for record in (package_data.get(key) or []):
                name = record.get("name") if isinstance(record, dict) else record
                if name:
                    names.add(str(name))
    elif kind == "layers":
        for record in (package_data.get("display_layers") or []):
            name = record.get("name") if isinstance(record, dict) else record
            if name:
                names.add(str(name))
    return sorted(names)
