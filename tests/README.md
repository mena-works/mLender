# Testler

Beş kademe var. Yukarıdan aşağıya doğru daha yavaş ama daha gerçek.

## 1. Sözleşme kontrolleri (host gerekmez, saniyeler)

```bash
python tests/check_contracts.py
```

`bpy`, `mathutils` ve `maya.cmds` yerine sahte modül koyup her iki package'ı
gerçekten import eder. Yakaladıkları:

- `from .x import y` içindeki var olmayan isimler
- döngüsel import
- iki package arasında protokol sabiti kayması
- exporter'ın ürettiği bir kanalın importer'da karşılığı olmaması
- `bl_info["version"]` ile `BUILD_VERSION` uyumsuzluğu
- `resolve_area_shape` ve `light_energy` sayısal davranışı
- şema doğrulamasının uyumsuz paketi reddetmesi

Sözdizimi için ayrıca:

```bash
python -m py_compile za_lookdev_exporter/*.py za_lookdev_importer/*.py
```

## 2. Maya export testi (gerçek Maya + Arnold, ~2 dk)

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/host/maya_export_test.py
```

Headless Maya'da desteklenen her Arnold shader ve ışığından bir tane içeren
sahne kurar, gerçek exporter'ı çalıştırır, ürettiği JSON'a assert eder.
Paketi `<temp>/za_lookdev_test` altına yazar.

Doğruladıkları arasında: `specularRoughness`/`baseMetalness`/`geometryOpacity`
gibi attribute isimleri, Arnold opacity'sinin ters çevrilmemesi, `aiTranslator`
string'inden şekil çözümlemesi, `aiExposure` yazım farkı, `aiFlat`'ın
`outColor` yerine `color` okuması, `aiLightPortal`'ın dışlanması.

## 3. Blender add-on testi (gerçek Blender, ~15 sn)

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/host/blender_addon_test.py
```

Add-on'un kayıt olduğunu, operator'ların **çağrılabildiğini** ve arka arkaya
`register()` çağrılarının çalışan bir add-on bıraktığını doğrular. Sonuncusu
Blender'ın "Reload Scripts" davranışıdır ve bozuk bir register'ın butonları
çalışmayan bir panel bırakarak saklandığı yerdir.

Kurulum gerektirmez, package'ı doğrudan depodan import eder.

## 4. Blender import testi (gerçek Blender, ~30 sn)

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/host/blender_import_test.py
```

2. adımın yazdığı paketi gerçek Blender'a import eder ve oluşan node
ağaçlarına, ışık data'sına assert eder. Önce 2. adımı çalıştır.

Birden fazla Blender sürümünde çalıştırmak sürüm uyum kodunu sınar; bu araç
3.6'dan 5.2'ye kadar iddia ediyor.

## 5. Render eşleşmesi (gerçek Arnold + gerçek Cycles, ~2 dk)

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/calibration/render_match_maya.py
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/calibration/render_match_blender.py
```

Tek soruyu uçtan uca yanıtlar: Arnold'da belli bir şekilde görünen ışık,
aktarımdan sonra Blender'da aynı görünüyor mu? Kamera da aktarıldığı için iki
render aynı yerden aynı lensle bakar; ikisi de lineer EXR yazdığı için view
transform devrede değildir ve sayılar doğrudan karşılaştırılabilir.

Bu karşılaştırma üç gerçek hata buldu: enerjide birim ölçeğinin yok sayılması
(~10000×), Arnold quad'ının transform scale'in iki katı olması, ve speküler
ağırlığının hiç aktarılmaması. Ayrıntı `light_calibration.md`.

`.ass` export ederken `lightLinks=0, shadowLinks=0` şart; yoksa export boş bir
ışık grubuna karşı `use_light_group on` yazar ve render simsiyah çıkar.

Prosedürel bake de 2. ve 4. adımda sınanır: gerçek bir checker ve ramp
ağı kurulur, bake edilir, Blender'da Non-Color yüklendiği doğrulanır, ve
export'un sahneye `file` node bırakmadığı kontrol edilir.

## Performans ölçümü (gerçek Maya + gerçek Blender, ~1 dk)

```bash
"C:\Program Files\Autodesk\Maya2023in\mayapy.exe" ^
    tests/calibration/benchmark_export.py 1600 60
"C:\Program Files\Blender Foundation\Blender 5.2lender.exe" ^
    --background --factory-startup --python tests/calibration/benchmark_import.py
```

Test değil, **ölçüm rig'i**: sentetik büyük bir sahne kurar, export ve import'u
cProfile altında çalıştırır ve en pahalı fonksiyonları yazdırır.

İlk çalıştırması iki gerçek darboğaz buldu, ikisi de karesel:

```text
export  face_assignment her mesh için shading engine'in bütün üyelerinde
        cmds.ls çağırıyordu.  800 mesh / 2 materyal: 7.1s -> 5.8s
        (200/400/800 eğrisi 1.0/2.4/7.1 idi, artık doğrusal)

import  find_mesh_record her obje için bütün kayıtları tarıyor ve isim
        anahtarlarını her seferinde regex'le yeniden üretiyordu.
        1600 mesh: 60.8s -> 2.0s
```

Ayrıca aynı materyal her mesh için baştan okunuyordu; artık shader başına bir
kez okunuyor (400 mesh / 60 materyal: `shader_channels` 400 → 60 çağrı).

## Ne doğrulanmıyor

Bu üç test **render etmiyor**; sabitlerin tutarlı uygulandığını doğrularlar,
değerlerin doğru olduğunu değil.

Düzeltme node'larının matematiği ayrıca ölçüldü, `correction_nodes.md`
içinde: Arnold `aiColorCorrect`/`aiRange` bir `aiFlat` üzerinden render
edilerek, Blender node'ları da world background'a bağlanıp render edilerek.
Üç sonuç sezginin tersi çıktı (gamma ters üs, hueShift tur cinsinden, contrast
pivotlu) ve soket **isimleri** 4.1→5.2'de değişip indeksleri sabit kaldı.

Işık değerleri de ölçüldü, `light_calibration.md` içinde:

- Blender'ın light Power'ının toplam akı olduğu ve `normalize` kapalıyken
  alanla ölçeklendiği **render ile ölçüldü** (4.1 ve 5.2).
- Arnold ve native Maya için yoğunluk→watt dönüşümü **ölçüldü ve π çıktı**;
  beş varyantta yayılım %0.00006.
- Redshift girdisi ölçülemedi (plugin kurulu değil) ve devralınmış tahmin
  olarak duruyor.
- `OPENPBR_EMISSION_LUMINANCE_SCALE` hâlâ seçilmiş bir değerdir; OpenPBR
  emission'ı nit cinsindendir ve "doğru" karşılığı sahneye bağlıdır.

`kick -licensecheck` bu makinede lisans bulamıyor ama bu yanıltıcı: eski RLM
yolunu kontrol ediyor. Arnold, Maya'nın Autodesk lisansıyla çalışıyor ve `kick`
`.ass` dosyalarını sorunsuz render ediyor.
