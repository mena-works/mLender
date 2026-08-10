# -*- coding: utf-8 -*-
import os
import sys
import glob
import shutil
import zipfile
import threading
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
    return (maya_zip[0] if maya_zip else None, 
            blender_zip[0] if blender_zip else None)

class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("mLender Setup")
        self.geometry("500x550")
        self.resizable(False, False)
        
        # Internal state
        self.maya_z, self.blender_z = find_zips()
        if not self.maya_z or not self.blender_z:
            print(f"dist directory: {get_resource_path('dist')}")
            # We don't crash, but we might show an error later
        
        self.maya_versions = self.detect_maya()
        self.blender_versions = self.detect_blender()
        
        self.maya_vars = {}
        self.blender_vars = {}
        
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
        
    def build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))
        
        title = ctk.CTkLabel(header, text="mLender", font=ctk.CTkFont(size=32, weight="bold"))
        title.pack(anchor="w")
        subtitle = ctk.CTkLabel(header, text="Maya to Blender Exporter Installation", font=ctk.CTkFont(size=14), text_color="gray")
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
            
            with zipfile.ZipFile(self.blender_z, 'r') as zf:
                zf.extractall(addons_dir)

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
