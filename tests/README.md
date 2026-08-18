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
python -m py_compile mlender_exporter/*.py mlender_importer/*.py
```

## 2. Maya export testi (gerçek Maya + Arnold, ~2 dk)

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/host/maya_export_test.py
```

Headless Maya'da desteklenen her Arnold shader ve ışığından bir tane içeren
sahne kurar, gerçek exporter'ı çalıştırır, ürettiği JSON'a assert eder.
Paketi `<temp>/mlender_test` altına yazar.

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

## 4b. Unreal import testi (gerçek Unreal, ~2 dk)

```bash
"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
    <bir .uproject> -run=pythonscript ^
    -script="tests/host/unreal_import_test.py" -unattended -nosplash -nullrhi
```

2. adımın yazdığı **aynı** paketi gerçek Unreal'a import eder. Önce 2. adımı
çalıştır.

Bir `.uproject` gerekir; `PythonScriptPlugin` etkin minimal bir tanesi yeter.
Test package'ı depodan import eder, kurulum gerektirmez.

**Çıktı stdout'ta değil** `<proje>/Saved/Logs/<proje>.log` içindedir; sonucu
`MLPASS` / `MLFAIL` ile ara. Headless Unreal'da bu ayrıntı ilk saati yer.

Doğruladıkları: eksen takasının iki yönü, santimetre/metre ölçek ayrımı, enerji
zincirinin lümen çıktısı ve kare birim teriminin varlığı, sun'ın lüks olduğu,
uçtan uca import (mesh eşleşmesi, materyal sayısı, actor tipleri), meshlerin
**bizim** materyallerimizi taşıdığı, rect ışığın akısının Unreal'in birim
çevriminden **sağ çıktığı**, ve kameranın Maya focal length'i ile sensor
genişliğini koruduğu.

Son üçü bilerek böyle yazıldı: "ışık var mı" ve "yoğunluk pozitif mi" soran
kontroller, bütün ışıkları Unreal'in varsayılanında bırakan bir hatayı
**geçirdi**.

## Render eşleşmesi, Unreal (gerçek Arnold + gerçek Unreal, ~5 dk)

Dört adım, sırayla. Blender yarısıyla **aynı** `arnold.exr`'i kullanır.

```bash
# 1. Arnold referansi (Blender yarisiyla ayni rig)
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" ^
    tests/calibration/render_match_maya.py

# 2. Paketi import et ve level'i kaydet
"...\UnrealEditor-Cmd.exe" <proje>.uproject -run=pythonscript ^
    -script="tests/calibration/render_match_unreal_import.py" ^
    -unattended -nosplash -nullrhi

# 3. render_match_unreal_capture.py'yi <proje>/Content/Python/init_unreal.py
#    olarak kopyala, editoru o level'de ac. Kendisi capture edip cikiyor.
#    SONRA DOSYAYI SIL, yoksa her editor acilisi capture etmeye calisir.

# 4. Karsilastir
"...\blender.exe" --background --factory-startup ^
    --python tests/calibration/render_match_unreal_compare.py
```

3. adım neden ayrı ve neden editörde: **commandlet render etmiyor** (ölçüldü,
temizlenen render target `(1,0,0)` okuyor) ve `-ExecutePythonScript` script
döner dönmez editörü kapatıyor. Çalışan tek yol startup script + tick.

Simetri kontrolü **assertion**: sahne sol-sağ simetrik, Arnold bunu %0.0025'te
üretiyor. Unreal %2'yi aşarsa karşılaştırma hüküm vermeyi reddedip **exit 2**
veriyor. Bugün %13.42 ile düşüyor, yani bu adım şu an ışığın **dağılımını**
doğruluyor, mutlak parlaklığını doğrulamıyor.

**Önemli iki koşul:**

- Bu rig'i host testiyle **aynı projede** koşma. Host testi import ederken
  `/Game/mLender`'ı siliyor ve kaydedilmiş MatchLevel'in mesh referansları
  null'a düşüyor; import "2 mesh, 0 materyal" veriyor (artık uyarı yazıyor).
  2. adımdan önce projenin `Content/mLender` ve `Content/RenderMatch`
  klasörlerini sil.
- Capture'ın render ayarlarına cevap vermediği ölçüldü (cvar, show flag ve
  proje ini üçü de bit-bit aynı sonuç). "GI kapalı" bir iddia değil; ayrıntı
  `docs/unreal_calibration.md` bölüm 7.4.2.

## LiveLink uçtan uca, Unreal (gerçek Maya + gerçek Unreal, ~3 dk)

**Kullanıcının gerçekten yaptığı yol.** Diğer bütün testler
`import_scene_package()`'i doğrudan çağırıyor; bu ise Maya'da Send'e basmayı
sınıyor: listener thread'i, game-thread pompası ve mesaj doğrulayıcı ancak
burada çalışıyor. Commandlet olmaz — pompa bir Slate tick callback'i.

```bash
# 1. unreal_livelink_test.py'yi <proje>/Content/Python/init_unreal.py olarak
#    kopyala ve editoru ac. Soketi baglar ve bekler.
# 2. Maya'dan gonder:
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" ^
    tests/host/maya_livelink_send.py
# 3. Sonra init_unreal.py kopyasini SIL.
```

Sıra önemli değil: Maya, listener'ın soketi bağladığını bildirmesini bekliyor,
yani test yarış koşuluyla geçmiyor veya düşmüyor. Doğrulanan çıktı:

```text
MLE2E status = Imported 1 mesh(es), 1 material(s), 1 light(s), 1 camera(s).
MLE2E level  = {StaticMeshActor: 1, RectLight: 1, CineCameraActor: 1}
MLE2E meshes carrying our materials = 1
```

## Mutlak parlaklık (gerçek Maya + gerçek Unreal, ~3 dk)

Işık enerjisi zincirini **analitik fiziğe** karşı doğrular. Arnold render'ı
kullanmaz — Arnold'ın pikselleri keyfi ölçekte olduğu için ona karşı bir oran
mutlak olamaz, render eşleşmesinin çözemediği şey buydu.

```bash
# 1. Kapali formda cevabi olan sahneyi export et
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" ^
    tests/calibration/light_absolute_maya.py

# 2. light_absolute_unreal.py'yi <proje>/Content/Python/init_unreal.py olarak
#    kopyala ve editoru ac. Import eder, olcer, hukum yazar, cikar.
#    SONRA DOSYAYI SIL.
```

Öncesinde projenin `Content/mLender` klasörünü sil (yeniden import hatası,
yukarıdaki nota bak).

Beş varyant her biri dönüşümün tek bir terimini oynatır. Beklenen çıktı:

```text
ratio over the variants where a point source is a fair approximation
    = 0.9529, spread 0.034%
VERDICT = ABSOLUTE BRIGHTNESS VERIFIED
```

Simetri kontrolü %5'i aşarsa rig güvenilmez sayılır ve hüküm verilmez. Kalan
%4.7 modelin nokta-kaynak varsayımıdır, transferin değil; `size/distance`
kolonu bunu görünür kılar. Ayrıntı `docs/unreal_calibration.md` bölüm 8.

## Referanslı sahne (gerçek Maya + gerçek Blender, ~1 dk)

```bash
"C:\Program Files\Autodesk\Maya2023in\mayapy.exe" tests/host/maya_reference_test.py
"C:\Program Files\Blender Foundation\Blender 5.2lender.exe" ^
    --background --factory-startup --python tests/host/blender_reference_test.py
```

Referans, referanslanabilmek için önce diskte bir dosya olmak zorunda; bu
yüzden ayrı bir test. Bir asset kurar, kaydeder, aynı dosyayı iki namespace
ile referanslar. Diğer testlerin ulaşamadığı durum bu: iki mesh de `body`, iki
grup da `assetGrp`, iki materyal de `assetShader`. Ayıran tek şey namespace.

## Import modları (gerçek Blender, ~40 sn)

```bash
"C:\Program Files\Blender Foundation\Blender 5.2lender.exe" ^
    --background --factory-startup --python tests/host/blender_modes_test.py
```

Replace / Merge / Add üçünü de sınar. Merge yalnız **ikinci** import'ta
tanımlı olduğu için paketi birden fazla kez import eder: kullanıcının kendi
objesi ile import edilmiş bir objeye eklediği modifier, ikinci import'tan
sonra hâlâ orada mı diye bakar. Bayat obje sayılıyor ama silinmiyor; silme
ayrı bir adım ve o da sınanıyor.

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

## Materyal render eşleşmesi (gerçek Arnold + gerçek Cycles, ~1 dk)

```bash
"C:\Program Files\Autodesk\Maya2023in\mayapy.exe" ^
    tests/calibration/material_match_maya.py
"C:\Program Files\Blender Foundation\Blender 5.2lender.exe" ^
    --background --factory-startup --python ^
    tests/calibration/material_match_blender.py
```

Işık rig'inin materyal karşılığı: sabit nötr ışık, değişen materyal. Düz
quad'lar, sabit bir dome altında. Sıyırma açısı istendiğinde **kamera** eğilir,
quad'lar değil.

İki BRDF farklı olduğu için birebir eşleşme beklenmiyor; aranan **aktarım
hatası**. Kritik tasarım kararı: eşleşmek yeterli değil, çünkü iki tarafta da
sessizce sıfır olan bir kanal da eşleşir. Bu yüzden her şüpheli kanal için
**tek o kanalda farklılaşan bir çift** hücre var.

Chart'ın sonundaki iki **kontrol** hücresi ortadaki bir hücrenin kopyasıdır ve
aynı okumak zorundadır; ayrışırlarsa rig materyali değil kendi geometrisini
ölçüyordur ve Blender tarafı hata koduyla çıkar. Rig'in geometrisine
dokunduğunda önce o satırlara bak.

Sonuçlar ve kapsamadıkları `docs/material_match.md` içinde.

## Coat darkening node zinciri (yalnız Blender, ~10 sn)

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python ^
    tests/calibration/coat_darkening_nodes.py
```

OpenPBR'ın coat karartması base color'a uygulanır: düz renkte Python'da,
texture'lı base color'da sekiz Vector Math node'uyla. Bu rig sabit renkli bir
görüntüyü node yolundan, aynı rengi düz yoldan geçirip ikisini render eder ve
eşleşmelerini şart koşar. Chart yalnız düz renk kullandığı için node yolunu
başka hiçbir şey sınamıyor.

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

Instance, locator, curve, set ve render kayıtları eklendikten sonra 2.6.1'de
yeniden ölçüldü; **regresyon yok** ve yeni keşif fonksiyonları profilin ilk
yirmisinde bile görünmüyor:

```text
                    800 mesh   1600 mesh   olcek
maya.mel FBX export    0.98s      4.52s     4.6x   <- bizim degil
mesh_records           1.18s      2.83s     2.4x
write_json             1.02s      2.19s     2.1x
import (toplam)          -        2.0s       -
```

Doğrusal olmayan tek adım **Maya'nın kendi FBX yazıcısı**. Bizim tarafta en
pahalı şey `attributeQuery` (1600 mesh'te 2.2s, alias tuple deseninin bedeli).
Node **tipine** göre önbelleklemek denendi ve **geri alındı**: aynı tipteki iki
node'un attribute kümesi `addAttr` yüzünden farklı olabilir, yani önbellek
sessizce yanlış cevap verebilirdi. Baskın maliyet zaten FBX yazıcısında.

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

Materyaller de ölçüldü, `material_match.md` içinde: on altı hücrelik bir
chart iki renderer'da render edilip karşılaştırıldı, hepsi %0.7 içinde ve
altı kanal çiftinin altısı da iki tarafta hareket ediyor. Aktarım hatası
bulunamadı. Kapsamadıkları belgede yazılı.

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
