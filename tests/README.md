# Testler

Üç kademe var. Yukarıdan aşağıya doğru daha yavaş ama daha gerçek.

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
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/maya_export_test.py
```

Headless Maya'da desteklenen her Arnold shader ve ışığından bir tane içeren
sahne kurar, gerçek exporter'ı çalıştırır, ürettiği JSON'a assert eder.
Paketi `<temp>/za_lookdev_test` altına yazar.

Doğruladıkları arasında: `specularRoughness`/`baseMetalness`/`geometryOpacity`
gibi attribute isimleri, Arnold opacity'sinin ters çevrilmemesi, `aiTranslator`
string'inden şekil çözümlemesi, `aiExposure` yazım farkı, `aiFlat`'ın
`outColor` yerine `color` okuması, `aiLightPortal`'ın dışlanması.

## 3. Blender import testi (gerçek Blender, ~30 sn)

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/blender_import_test.py
```

2. adımın yazdığı paketi gerçek Blender'a import eder ve oluşan node
ağaçlarına, ışık data'sına assert eder. Önce 2. adımı çalıştır.

Birden fazla Blender sürümünde çalıştırmak sürüm uyum kodunu sınar; bu araç
3.6'dan 5.2'ye kadar iddia ediyor.

## Ne doğrulanmıyor

Bu üç test **render etmiyor**; sabitlerin tutarlı uygulandığını doğrularlar,
değerlerin doğru olduğunu değil.

Değerlerin kendisi ayrıca ölçüldü, `light_calibration.md` içinde:

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
