# -*- coding: utf-8 -*-
import json
import os
import sys
import glob
import shutil
import zipfile
import threading
import tkinter
import customtkinter as ctk

# Configure CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def find_zips():
    dist_dir = get_resource_path("dist")
    maya_zip = glob.glob(os.path.join(dist_dir, "mLender-*-maya-module.zip"))
    blender_zip = glob.glob(os.path.join(dist_dir, "mLender-*-blender-addon.zip"))
    unreal_zip = glob.glob(os.path.join(dist_dir, "mLender-*-unreal-plugin.zip"))
    return (maya_zip[0] if maya_zip else None,
            blender_zip[0] if blender_zip else None,
            unreal_zip[0] if unreal_zip else None)

def bundled_version(path):
    """The version out of a bundled archive's name, so the window says what
    it is about to install rather than leaving the user to guess."""
    name = os.path.basename(path or "")
    parts = name.split("-")
    return parts[1] if len(parts) > 2 else "?"

def replace_folder(path):
    """Delete a previous install before writing the new one.

    Extracting over the old folder overwrites what both versions have and
    leaves behind what only the old one had. A module the new version
    dropped would keep being imported, and the user would be running a
    mixture of two builds without a way to tell.
    """
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)

class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("mLender Setup")
        self.geometry("500x550")
        self.resizable(False, False)
        
        # Internal state
        self.maya_z, self.blender_z, self.unreal_z = find_zips()
        if not self.maya_z or not self.blender_z:
            print(f"dist directory: {get_resource_path('dist')}")
            # We don't crash, but we might show an error later
        
        self.maya_versions = self.detect_maya()
        self.blender_versions = self.detect_blender()
        self.unreal_projects = self.detect_unreal_projects()
        self.unreal_engines = self.detect_unreal_engines()
        
        self.maya_vars = {}
        self.blender_vars = {}
        self.unreal_vars = {}
        self.unreal_engine_vars = {}
        
        self.build_ui()
        
    def detect_maya(self):
        import winreg
        installed_versions = set()
        
        # 1. Check Program Files
        pf = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        ad_pf = os.path.join(pf, "Autodesk")
        if os.path.exists(ad_pf):
            for item in os.listdir(ad_pf):
                if item.startswith("Maya") and item.replace("Maya", "").isdigit():
                    installed_versions.add(item.replace("Maya", ""))
                    
        # 2. Check Registry
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\Autodesk\\Maya", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        if subkey_name.isdigit() and len(subkey_name) == 4:
                            installed_versions.add(subkey_name)
                    except OSError:
                        continue
        except OSError:
            pass
            
        # 3. Intersect with Documents\\maya so we don't install to empty profiles
        docs = os.path.join(os.path.expanduser("~"), "Documents", "maya")
        doc_versions = set()
        if os.path.exists(docs):
            for item in os.listdir(docs):
                path = os.path.join(docs, item)
                if os.path.isdir(path) and item.isdigit() and len(item) == 4:
                    doc_versions.add(item)
                    
        if installed_versions:
            final_versions = installed_versions.intersection(doc_versions)
            if not final_versions:
                final_versions = installed_versions
        else:
            final_versions = doc_versions
            
        return sorted(list(final_versions), reverse=True)
        
    def detect_blender(self):
        import winreg
        versions = set()
        
        # 1. Check standard Program Files installation
        pf = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        bf_pf = os.path.join(pf, "Blender Foundation")
        if os.path.exists(bf_pf):
            for item in os.listdir(bf_pf):
                if item.startswith("Blender "):
                    v = item.replace("Blender ", "").strip()
                    if v.replace(".", "").isdigit():
                        versions.add(v)
                        
        # 2. Check Windows Registry (Add/Remove Programs) for Steam or custom installs
        def check_registry(hive, flag):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall", 0, winreg.KEY_READ | flag) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                if "Blender" in str(display_name):
                                    display_version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                                    parts = str(display_version).split(".")
                                    if len(parts) >= 2:
                                        versions.add(f"{parts[0]}.{parts[1]}")
                        except OSError:
                            continue
            except OSError:
                pass

        check_registry(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY)
        check_registry(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)
        check_registry(winreg.HKEY_CURRENT_USER, 0)
        
        # 3. Fallback: check AppData, but only include it if a 'config' folder exists 
        # (meaning the user actively used this version recently, e.g. portable version)
        appdata = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
        bf = os.path.join(appdata, "Blender Foundation", "Blender")
        if os.path.exists(bf):
            for item in os.listdir(bf):
                path = os.path.join(bf, item)
                if os.path.isdir(path) and item.replace(".", "").isdigit():
                    if os.path.exists(os.path.join(path, "config")) or not versions:
                        versions.add(item)
                        
        return sorted(list(versions), reverse=True)
        
    def detect_unreal_projects(self):
        """Unreal projects the plugin can be installed into.

        Projects rather than the engine, for two reasons the install notes
        already give: the engine folder is under Program Files and needs
        administrator rights, and an engine update wipes what is in it.

        A .uproject is what makes a folder a project, so that is what is
        looked for -- a folder named after one proves nothing.
        """
        found = {}
        roots = [
            os.path.join(os.path.expanduser("~"), "Documents",
                         "Unreal Projects"),
            os.path.join(os.path.expanduser("~"), "Unreal Projects"),
        ]
        for root in roots:
            if not os.path.isdir(root):
                continue
            for entry in sorted(os.listdir(root)):
                folder = os.path.join(root, entry)
                if not os.path.isdir(folder):
                    continue
                projects = glob.glob(os.path.join(folder, "*.uproject"))
                if projects:
                    found[entry] = projects[0]
        return found

    def detect_unreal_engines(self):
        """Engine installs, which is where a plugin stops being per project.

        A plugin under <Engine>/Engine/Plugins is available to every project
        on that engine, and mLender enables itself, so nothing has to be done
        per project at all. The cost is in the notes and it is real: the
        folder is under Program Files, so writing there needs administrator
        rights, and an engine update removes what is in it.

        Read from the registry first, because an engine can be installed
        anywhere, and fall back to the standard folder for the case where the
        launcher wrote no key.
        """
        found = {}
        try:
            import winreg

            for hive, flag in ((winreg.HKEY_LOCAL_MACHINE, 0),
                               (winreg.HKEY_CURRENT_USER, 0)):
                try:
                    key = winreg.OpenKey(
                        hive, r"SOFTWARE\EpicGames\Unreal Engine")
                except OSError:
                    continue
                index = 0
                while True:
                    try:
                        version = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        sub = winreg.OpenKey(key, version)
                        path, _ = winreg.QueryValueEx(sub, "InstalledDirectory")
                    except OSError:
                        continue
                    if path and os.path.isdir(os.path.join(path, "Engine")):
                        found[version] = path
        except Exception:
            pass

        for path in sorted(glob.glob(r"C:\Program Files\Epic Games\UE_*")):
            if not os.path.isdir(os.path.join(path, "Engine")):
                continue
            version = os.path.basename(path).replace("UE_", "")
            found.setdefault(version, path)
        return found

    def build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))
        
        title = ctk.CTkLabel(header, text="mLender", font=ctk.CTkFont(size=32, weight="bold"))
        title.pack(anchor="w")
        subtitle = ctk.CTkLabel(
            header,
            text="Maya to Blender and Unreal  -  installing build {0}".format(
                bundled_version(self.blender_z)),
            font=ctk.CTkFont(size=14),
            text_color="gray",
        )
        subtitle.pack(anchor="w")
        
        # Main Frame
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Maya Section
        maya_lbl = ctk.CTkLabel(main_frame, text="Maya Installations", font=ctk.CTkFont(size=16, weight="bold"))
        maya_lbl.pack(anchor="w", pady=(10, 5))
        
        if not self.maya_versions:
            ctk.CTkLabel(main_frame, text="No Maya installations detected.", text_color="gray").pack(anchor="w", padx=10)
        else:
            var = ctk.BooleanVar(value=True)
            chk = ctk.CTkSwitch(main_frame, text="All Maya Versions (Global)", variable=var)
            chk.pack(anchor="w", padx=10, pady=5)
            self.maya_vars["Global"] = var
            
            for v in self.maya_versions:
                var = ctk.BooleanVar(value=False)
                chk = ctk.CTkSwitch(main_frame, text=f"Maya {v}", variable=var)
                chk.pack(anchor="w", padx=10, pady=5)
                self.maya_vars[v] = var
                
        # Blender Section
        blender_lbl = ctk.CTkLabel(main_frame, text="Blender Installations", font=ctk.CTkFont(size=16, weight="bold"))
        blender_lbl.pack(anchor="w", pady=(20, 5))
        
        if not self.blender_versions:
            ctk.CTkLabel(main_frame, text="No Blender installations detected.", text_color="gray").pack(anchor="w", padx=10)
        else:
            for v in self.blender_versions:
                var = ctk.BooleanVar(value=True)
                chk = ctk.CTkSwitch(main_frame, text=f"Blender {v}", variable=var)
                chk.pack(anchor="w", padx=10, pady=5)
                self.blender_vars[v] = var
                
        # Unreal Section
        unreal_lbl = ctk.CTkLabel(main_frame, text="Unreal Projects", font=ctk.CTkFont(size=16, weight="bold"))
        unreal_lbl.pack(anchor="w", pady=(20, 5))

        if not self.unreal_z:
            ctk.CTkLabel(main_frame, text="No Unreal plugin in this installer.", text_color="gray").pack(anchor="w", padx=10)
        else:
            for version, root in sorted(self.unreal_engines.items()):
                var = ctk.BooleanVar(value=False)
                chk = ctk.CTkSwitch(
                    main_frame,
                    text="Unreal Engine {0}  -  every project".format(version),
                    variable=var,
                )
                chk.pack(anchor="w", padx=10, pady=5)
                self.unreal_engine_vars[version] = var
            if self.unreal_engines:
                ctk.CTkLabel(
                    main_frame,
                    text="Installing into the engine needs administrator rights, and an engine update removes it. Per project below survives updates.",
                    text_color="gray", font=ctk.CTkFont(size=11),
                    wraplength=520, justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 5))

        if self.unreal_z and not self.unreal_projects:
            # Projects, not engines: the engine folder is under Program Files
            # and an engine update wipes what is in it.
            ctk.CTkLabel(main_frame, text="No Unreal projects found under Documents\\Unreal Projects.", text_color="gray").pack(anchor="w", padx=10)
        elif self.unreal_z:
            for name in sorted(self.unreal_projects):
                var = ctk.BooleanVar(value=False)
                chk = ctk.CTkSwitch(main_frame, text=name, variable=var)
                chk.pack(anchor="w", padx=10, pady=5)
                self.unreal_vars[name] = var

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=20)
        
        self.status_lbl = ctk.CTkLabel(footer, text="", text_color="gray")
        self.status_lbl.pack(side="left")
        
        self.install_btn = ctk.CTkButton(footer, text="Install Now", command=self.start_install, height=40, font=ctk.CTkFont(weight="bold"))
        self.install_btn.pack(side="right")
        
    def start_install(self):
        if not self.maya_z or not self.blender_z:
            self.status_lbl.configure(text="Error: Installation files missing!", text_color="red")
            return
            
        self.install_btn.configure(state="disabled", text="Installing...")
        threading.Thread(target=self.install_worker, daemon=True).start()
        
    def install_worker(self):
        try:
            self.install_maya()
            self.install_blender()
            self.install_unreal()
            self.after(0, self.finish_install)
        except Exception as e:
            self.after(0, lambda: self.status_lbl.configure(text=f"Error: {str(e)}", text_color="red"))
            self.after(0, lambda: self.install_btn.configure(state="normal", text="Install Now"))
            
    def finish_install(self):
        self.status_lbl.configure(text="Installation Completed Successfully!", text_color="green")
        self.install_btn.configure(text="Close", state="normal", command=self.destroy)
        
    def install_maya(self):
        docs = os.path.join(os.path.expanduser("~"), "Documents", "maya")
        selected_maya = [k for k, v in self.maya_vars.items() if v.get()]
        
        if not selected_maya:
            return
            
        for sel in selected_maya:
            if sel == "Global":
                modules_dir = os.path.join(docs, "modules")
            else:
                modules_dir = os.path.join(docs, sel, "modules")
                
            os.makedirs(modules_dir, exist_ok=True)
            self.after(0, lambda d=modules_dir: self.status_lbl.configure(text=f"Installing to {d}..."))
            
            # Extract zip
            mlender_dir = os.path.join(modules_dir, "mLender")
            scripts_dir = os.path.join(mlender_dir, "scripts")
            exporter_dir = os.path.join(scripts_dir, "mlender_exporter")
            replace_folder(exporter_dir)
            os.makedirs(exporter_dir, exist_ok=True)

            with zipfile.ZipFile(self.maya_z, 'r') as zf:
                # The maya zip has structure:
                # mLender.mod
                # mLender/scripts/mlender_exporter/...
                zf.extractall(modules_dir)
                
            # Create userSetup.py
            user_setup_path = os.path.join(scripts_dir, "userSetup.py")
            with open(user_setup_path, "w", encoding="utf-8") as f:
                f.write("import maya.cmds as cmds\n")
                f.write("import maya.utils\n")
                f.write("def _init_mlender_shelf():\n")
                f.write("    try:\n")
                f.write("        import mlender_exporter.shelf\n")
                f.write("        mlender_exporter.shelf.create_shelf()\n")
                f.write("    except Exception as e:\n")
                f.write("        print('Failed to load mLender shelf: {}'.format(e))\n")
                f.write("maya.utils.executeDeferred(_init_mlender_shelf)\n")

    def install_blender(self):
        appdata = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
        bf = os.path.join(appdata, "Blender Foundation", "Blender")
        selected_blender = [k for k, v in self.blender_vars.items() if v.get()]
        
        for sel in selected_blender:
            addons_dir = os.path.join(bf, sel, "scripts", "addons")
            os.makedirs(addons_dir, exist_ok=True)
            self.after(0, lambda d=addons_dir: self.status_lbl.configure(text=f"Installing to {d}..."))

            # The folder name is the add-on's module name, so this is the
            # one Blender will import; a previous build goes first.
            replace_folder(os.path.join(addons_dir, "mlender_importer"))
            with zipfile.ZipFile(self.blender_z, 'r') as zf:
                zf.extractall(addons_dir)

    def install_unreal(self):
        if not self.unreal_z:
            return

        for version, var in self.unreal_engine_vars.items():
            if not var.get():
                continue
            root = self.unreal_engines.get(version)
            if not root:
                continue
            plugins_dir = os.path.join(root, "Engine", "Plugins")
            self.after(0, lambda d=plugins_dir: self.status_lbl.configure(
                text="Installing to {0}...".format(d)))
            try:
                replace_folder(os.path.join(plugins_dir, "mLender"))
                with zipfile.ZipFile(self.unreal_z, "r") as archive:
                    archive.extractall(plugins_dir)
            except PermissionError:
                # Program Files. Said plainly, because "it did not work" sends
                # the user looking in the wrong place.
                self.after(0, lambda v=version: self.status_lbl.configure(
                    text="Unreal {0} needs administrator rights - run this "
                         "installer as administrator, or install per "
                         "project.".format(v),
                    text_color="orange"))

        selected = [k for k, v in self.unreal_vars.items() if v.get()]
        for name in selected:
            uproject = self.unreal_projects.get(name)
            if not uproject:
                continue
            plugins_dir = os.path.join(os.path.dirname(uproject), "Plugins")
            os.makedirs(plugins_dir, exist_ok=True)
            self.after(0, lambda d=plugins_dir: self.status_lbl.configure(
                text="Installing to {0}...".format(d)))

            # The folder inside the archive is mLender, which is the name
            # Unreal reads from the .uplugin -- not the one the repository
            # uses. A previous build goes first, for the same reason it does
            # everywhere else.
            # The project file is left alone. mLender enables itself, so
            # there is nothing to add to it -- and a project file carries
            # settings nobody wants an installer rewriting.
            replace_folder(os.path.join(plugins_dir, "mLender"))
            with zipfile.ZipFile(self.unreal_z, "r") as archive:
                archive.extractall(plugins_dir)


def selftest(report_path):
    """Everything the installer does except open a window, written to a file.

    A windowed build has no stdout, so "does it run" cannot be read from a
    shell -- which is how a build with no tkinter in it reached a release.
    This runs the same imports and the same detection and writes what it
    found, so a check has something to read and an exit code to trust.
    """
    maya_zip, blender_zip, unreal_zip = find_zips()
    report = {
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "tk": tkinter.TkVersion,
        "customtkinter": getattr(ctk, "__version__", "?"),
        "maya_zip": os.path.basename(maya_zip or ""),
        "blender_zip": os.path.basename(blender_zip or ""),
        "unreal_zip": os.path.basename(unreal_zip or ""),
        "version": bundled_version(blender_zip),
        "maya_versions": InstallerApp.detect_maya(None),
        "blender_versions": InstallerApp.detect_blender(None),
        "unreal_projects": sorted(
            InstallerApp.detect_unreal_projects(None)
        ),
        "unreal_engines": sorted(
            InstallerApp.detect_unreal_engines(None)
        ),
    }
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        index = sys.argv.index("--selftest")
        target = (sys.argv[index + 1] if len(sys.argv) > index + 1
                  else "mlender_setup_selftest.json")
        sys.exit(selftest(target))
    app = InstallerApp()
    app.mainloop()
