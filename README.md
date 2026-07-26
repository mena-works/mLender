# Z-A Exporter — Lookdev

Maya sahnesindeki bütün meshleri FBX olarak Blender'a canlı gönderen ve
materialleri Maya shader bilgilerine göre Blender Principled BSDF olarak yeniden
kuran Lookdev aktarım aracıdır.

Bu sürümde:

- Alembic yoktur.
- UV bake yoktur.
- Texture kopyalama yoktur.
- Kamera exportu yoktur.
- Lookdev `.blend` seçimi yoktur.
- Shape key, parent veya constraint kurulumu yoktur.
- Yeni paket geldiğinde Blender sahnesi tamamen temizlenir ve unused data purge
  edilir.

## Dosyalar

- `za_lookdev_exporter.py`: Maya UI, FBX export, shader/texture analizi ve
  LiveLink gönderimi
- `za_lookdev_importer.py`: Blender add-on/LiveLink listener, sahne yenileme ve
  Principled material kurulumu

## Paket sistemi

Maya UI'da seçilen ana klasörde her gönderim için yeni paket oluşturulur:

```text
MTB_Z_A_01/
  MTB_Z_A_01.fbx
  MTB_Z_A_01_lookdev.json

MTB_Z_A_02/
  MTB_Z_A_02.fbx
  MTB_Z_A_02_lookdev.json
```

Texture dosyaları paket içine kopyalanmaz. JSON yalnız Maya'daki orijinal
texture konumunu taşır; Blender image node aynı dosyayı doğrudan açar.

## Desteklenen Maya shaderları

- `RedshiftStandardMaterial`
- `RedshiftMaterial` (legacy)
- `lambert`
- `blinn`

Aktarılan kanallar:

- Base Color
- Reflection Roughness
- Metalness
- Normal/Bump
- Opacity/Transparency
- Emission Color
- Emission Strength

### Redshift roughness kuralı

Principled BSDF Roughness için Redshift **Reflection Roughness** kullanılır.
Redshift Diffuse Roughness, Oren–Nayar diffuse davranışını kontrol ettiği için
Principled yüzey roughness'ına aktarılmaz.

Materialda roughness inputunun glossiness olarak yorumlandığını belirten
Redshift bayrağı açıksa değer veya texture Blender roughness'ına bağlanmadan
önce ters çevrilir (`roughness = 1 - glossiness`).

Redshift Standard Material için temel Maya attribute adayları:

```text
Base Color           → base_color
Reflection Roughness → refl_roughness
Metalness            → metalness
Opacity              → opacity_color
Normal/Bump          → bump_input
Emission             → emission_color
Emission Strength    → emission_weight
```

Legacy Redshift Material için:

```text
Base Color           → diffuse_color
Reflection Roughness → refl_roughness
Metalness            → refl_metalness
Opacity              → opacity_color
Normal/Bump          → bump_input
Emission             → emission_color
Emission Strength    → emission_weight
```

Shader sürümleri arasındaki attribute isim farkları için alternatif isimler de
kontrol edilir. JSON her kanal için gerçekten bulunan `maya_attr` ve
`maya_plug` bilgisini yazar.

### Lambert ve Blinn

Lambert ve Blinn'de base color texture bağlıysa texture yolu, değilse renk
değeri aktarılır. Maya transparency değeri Blender opacity değerine çevrilir.

- Lambert → Principled Roughness `0.7`
- Blinn → Principled Roughness `0.1`
- İkisi için de Metallic `0.0`

## Texture ağları

Bir material inputuna doğrudan file node bağlı olmak zorunda değildir. Exporter
upstream history tarar ve şu dosya alanlarını kontrol eder:

- Maya `file.fileTextureName`
- Redshift `tex0`
- `filename`
- `file`

Color correction, bump veya benzeri ara node'ların arkasındaki ilk bulunabilir
texture yolu JSON'a yazılır. Çok katmanlı/prosedürel ağların matematiksel sonucu
bake edilmez; bulunan kaynak texture ve material değeriyle mümkün olan en yakın
Principled kurulum yapılır.

Base Color ve Emission textureleri renkli; Roughness, Metalness, Opacity ve
Normal textureleri Blender'da Non-Color olarak açılır. Normal texture,
`Normal Map` node üzerinden Principled Normal inputuna bağlanır.

## Maya kullanımı

Maya Python sekmesinde:

```python
import sys
import importlib

tool_path = r"D:\GitHub_Repository\mayatools\ZA_Exporter"
if tool_path not in sys.path:
    sys.path.append(tool_path)

import za_lookdev_exporter as za
importlib.reload(za)
za.show_ui()
```

1. `Export Location` seç.
2. Blender host/port değerlerini kontrol et. Varsayılan `127.0.0.1:50505`.
3. `Send To Blender` butonuna bas.

## Blender kullanımı

Add-on olarak `za_lookdev_importer.py` dosyasını kurabilir veya Scripting
workspace/console üzerinden çalıştırabilirsin:

```python
import gc
import socket
import sys
import types

import bpy

importer_path = r"D:\GitHub_Repository\mayatools\ZA_Exporter\za_lookdev_importer.py"
module_name = "za_lookdev_importer"
protocol_name = "za_lookdev_livelink"

# Stop every reachable previous Z-A runtime.
old_runtimes = [
    sys.modules.pop(module_name, None),
    globals().pop("_ZA_LOOKDEV_RUNTIME", None),
]
for old_runtime in old_runtimes:
    if old_runtime is None:
        continue
    try:
        unregister = (
            old_runtime.get("unregister")
            if isinstance(old_runtime, dict)
            else getattr(old_runtime, "unregister", None)
        )
        if unregister:
            unregister()
    except Exception:
        pass

# Remove timer callbacks left by older importlib.reload sessions.
for item in list(gc.get_objects()):
    try:
        if (
            isinstance(item, types.FunctionType)
            and item.__name__ == "_process_messages"
            and item.__globals__.get("LIVELINK_PROTOCOL") == protocol_name
            and bpy.app.timers.is_registered(item)
        ):
            bpy.app.timers.unregister(item)
    except Exception:
        pass

# Close an orphaned Z-A listener still holding the default port.
for item in list(gc.get_objects()):
    try:
        if isinstance(item, socket.socket):
            address = item.getsockname()
            if isinstance(address, tuple) and len(address) > 1 and address[1] == 50505:
                item.close()
    except Exception:
        pass

# Remove stale Blender registrations.
for class_name in (
    "ZA_OT_start_listener",
    "ZA_OT_stop_listener",
    "ZA_PT_lookdev",
):
    old_class = getattr(bpy.types, class_name, None)
    if old_class:
        try:
            bpy.utils.unregister_class(old_class)
        except Exception:
            pass

for property_name in (
    "za_import_scale",
    "za_livelink_host",
    "za_livelink_port",
):
    if hasattr(bpy.types.Scene, property_name):
        delattr(bpy.types.Scene, property_name)

# Read and execute the exact source file without importlib/bytecode cache.
with open(importer_path, "r", encoding="utf-8") as source_file:
    source = source_file.read()

runtime = types.ModuleType(module_name)
runtime.__file__ = importer_path
runtime.__package__ = ""
sys.modules[module_name] = runtime

exec(compile(source, importer_path, "exec"), runtime.__dict__)
runtime.register()
globals()["_ZA_LOOKDEV_RUNTIME"] = runtime

print("Z-A Lookdev Importer Build", runtime.BUILD_VERSION)
```

`View3D > N Panel > Z-A Exporter` içinde:

1. FBX Scale değerini kontrol et.
2. Host/Port değerlerini kontrol et.
3. `Start LiveLink` butonuna bas.

## Blender import davranışı

Yeni paket geldiğinde:

1. Açık Blender dosyası kayıtlıysa önce kaydedilir.
2. Sahnedeki bütün objeler ve collection'lar silinir.
3. Kullanılmayan mesh, material, image, texture, action ve diğer data-block'lar
   purge edilir.
4. Yeni FBX import edilir.
5. FBX'in oluşturduğu geçici material slotları temizlenir.
6. JSON'daki mesh → material ve yüz atamaları uygulanır.
7. Materialler Principled BSDF olarak yeniden kurulur.
8. Textureler Maya'daki orijinal dosya konumlarından bağlanır.
9. Import sonunda tekrar recursive orphan purge yapılır.

Bir mesh birden fazla material kullanıyorsa Maya shadingEngine face membership
bilgisi JSON'a yazılır ve Blender polygon material indexleri yeniden kurulur.

## Git

Bu klasör bağımsız Git deposudur:

```text
D:\GitHub_Repository\mayatools\ZA_Exporter\.git
```
