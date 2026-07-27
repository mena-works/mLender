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

Araç iki Python package'ından oluşur. Package'lar birbirini import etmez; tek
bağları LiveLink protokolü ve paket JSON şemasıdır.

```text
za_lookdev_exporter/        # Maya tarafı
  __init__.py               # public API: show_ui, show, export_lookdev
  constants.py              # protokol sabitleri, attribute alias tabloları
  mayautils.py              # maya.cmds sarmalayıcıları, değer yardımcıları
  textures.py               # shading network'te upstream texture arama
  shaders.py                # shader → Principled kanal çıkarımı
  meshes.py                 # mesh keşfi, material ve face atamaları
  lights.py                 # ışık keşfi ve current-frame ışık kayıtları
  fbx.py                    # MEL FBXExport sarmalayıcısı
  livelink.py               # TCP gönderim istemcisi
  package.py                # paket klasörü, JSON yazımı, atomik temizlik
  ui.py                     # Maya penceresi

za_lookdev_importer/        # Blender tarafı (multi-file add-on)
  __init__.py               # bl_info, register/unregister, reload
  constants.py              # protokol sabitleri, socket adları, kalibrasyon
  utils.py                  # değer dönüşümü, isim normalizasyonu
  images.py                 # texture yükleme, UDIM çözümleme
  materials.py              # Principled ve Surface Shader node ağaçları
  lights.py                 # Blender ışıkları ve Dome World
  scene.py                  # sahne temizleme, mesh eşleştirme, subdivision
  fbx.py                    # FBX import, paket dosyası çözümleme
  importer.py               # import orkestrasyonu, şema doğrulaması
  livelink.py               # socket listener ve ana thread mesaj pompası
  ui.py                     # operator'lar, scene property'leri, panel
```

Bölünmeden önceki tek dosyalık sürümler git geçmişinde `0dcbff4` commit'inde
duruyor; karşılaştırmak için `git show 0dcbff4:za_lookdev_exporter.py`.

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

**Redshift**

- `RedshiftStandardMaterial`
- `RedshiftMaterial` (legacy)

**Arnold** (MtoA 5.4.8 üzerinde doğrulandı)

- `aiStandardSurface`
- `aiOpenPBRSurface`
- `aiLambert`
- `aiFlat`

**Native Maya**

- `lambert`
- `blinn`
- `surfaceShader`

Aktarılan kanallar:

- Base Color
- Reflection Roughness
- Metalness
- Normal/Bump
- Opacity/Transparency
- Emission Color
- Emission Strength
- Transmission (weight, renk, roughness), IOR, Thin Walled

Materialin transmission ağırlığı sıfırdan büyükse Principled yerine **Glass
BSDF** kurulur. Cam bir yüzeyde refraction'ı Principled transmission'la taklit
etmek yerine ayrı bir Glass BSDF kullanmak, hem Redshift hem Arnold tarafındaki
görüntüye belirgin şekilde daha yakın duruyor; roughness ve IOR de iki tarafta
aynı anlama geliyor.

Cutout opacity refraction'dan ayrı tutulur: opacity 1'in altındaysa Glass BSDF
bir Transparent BSDF ile Mix Shader üzerinden karıştırılır, cam rengine
karıştırılmaz.

Kaynak değerler material custom property'lerinde saklanır:
`za_material_mode`, `za_transmission_weight`, `za_thin_walled`,
`za_transmission_affects_alpha`.

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

### Arnold

Attribute isimleri canlı bir MtoA 5.4.8 oturumundan okunmuştur, tahmin
değildir. `aiStandardSurface` ile `aiOpenPBRSurface` üç kanalda ayrışır:

```text
Kanal              aiStandardSurface     aiOpenPBRSurface
Base Color         baseColor             baseColor
Roughness          specularRoughness     specularRoughness
Metallic           metalness             baseMetalness
Opacity            opacity (renk)        geometryOpacity (float)
Normal/Bump        normalCamera          normalCamera
Emission           emissionColor         emissionColor
Emission Strength  emission (0-1)        emissionLuminance (nit)
```

Üç davranış farkına dikkat:

- **Arnold opacity ters çevrilmez.** Maya'nın `transparency` değeri
  opacity'ye çevrilirken tersi alınır; Arnold'ın `opacity`'si zaten
  opacity'dir (1 = opak) ve olduğu gibi aktarılır.
- **OpenPBR emission bir ağırlık değil, nit cinsinden parlaklıktır.**
  Blender Emission Strength soketine ham geçirilemez; importer'daki
  `OPENPBR_EMISSION_LUMINANCE_SCALE` ile ölçeklenir (varsayılan 100 nit → 1.0).
- **`aiFlat` `color` okur, `outColor` değil.** Maya `surfaceShader`'ında
  `outColor` gerçek bir girdi attribute'udur, ama Arnold shader'larında
  hesaplanmış bir çıktıdır ve render dışında anlamsız bir sabit döner.

`aiStandardSurface.base` ve OpenPBR `baseWeight`/`specularWeight` ağırlıkları
aktarılmaz; Principled'da karşılıkları yok ve base color'a katlamak dışa
aktarılan değeri yanlış raporlamak olurdu.

`aiLambert` base color'ını `KdColor`'dan alır ve Principled Roughness `0.7`,
Metallic `0.0` ile kurulur. `aiFlat`, `surfaceShader` gibi Emission +
Transparent + Mix Shader olarak kurulur.

### Lambert ve Blinn

Lambert ve Blinn'de base color texture bağlıysa texture yolu, değilse renk
değeri aktarılır. Maya transparency değeri Blender opacity değerine çevrilir.

- Lambert → Principled Roughness `0.7`
- Blinn → Principled Roughness `0.1`
- İkisi için de Metallic `0.0`

### Surface Shader

Maya `surfaceShader.outColor` değeri veya bağlı texture Blender'da Emission
shader Color girişine aktarılır. `outTransparency`, Transparent BSDF ile
Emission arasında Mix Shader opacity değerine dönüştürülür. Böylece material
Principled yüzey gibi ışık almak yerine Maya Surface Shader'a yakın, doğrudan
emissive davranır.

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

### UDIM

UDIM tespiti dosya adına bakarak tahmin edilmez, **Maya'ya sorulur**:
`file.uvTilingMode` tiled olup olmadığını, `computedFileTextureNamePattern` ise
Maya'nın kendi çözdüğü deseni verir. Yalnız ikisi de sonuç vermezse dosya
adındaki tile numarası `<UDIM>` ile değiştirilir.

- `<UDIM>`, `<udim>`, `%(UDIM)d`, `$UDIM`, `{UDIM}` biçimleri tek token'a
  normalize edilir.
- Tile numarası sayılmak için 1001 veya üstü olmalı ve dosya adındaki **son**
  dört haneli grup olmalıdır; böylece versiyon numaraları tile sanılmaz.
- Blender tarafında image `TILED` yapılır ve `reload()` edilir — Blender kardeş
  tile'ları yalnız reload sırasında tarar.
- Glob'da `*` yerine `[1-9][0-9][0-9][0-9]` kullanılır; `*` aynı önekle
  başlayan alakasız dosyaları yakalayabiliyordu.

JSON hem `<UDIM>` desenini (`path`, `udim_pattern`) hem de somut tile yolunu
(`original_path`) taşır.

Bir shader emission rengi gönderip emission strength göndermezse Blender'da
strength `1.0` olarak set edilir. Blender 3.x bu soketi varsayılan olarak `1.0`,
4.x ise `0.0` bıraktığı için aksi halde aynı paket 3.6'da emissive, 4.x'te siyah
görünürdü.

## Maya kullanımı

Maya Python sekmesinde:

```python
import sys

tool_path = r"D:\GitHub_Repository\mayatools\ZA_Exporter"
if tool_path not in sys.path:
    sys.path.append(tool_path)

import za_lookdev_exporter as za
za.show_ui()
```

`tool_path`, package klasörünün **içi değil, üstündeki** klasördür; yani
`za_lookdev_exporter` klasörünü içeren dizin.

### Kalıcı kurulum

Her seferinde yolu yazmamak için iki yol var, ikisi de mevcut ayarlarına
dokunmadan eklenebilir.

**userSetup.py** — `Documents/maya/scripts/userSetup.py` dosyasının sonuna
ekle. Dosya zaten varsa üzerine yazma, altına ekle:

```python
ZA_EXPORTER_ROOT = r"...\MayaToBlender_Exporter-main"


def _register_za_exporter():
    import os
    import sys
    try:
        if not os.path.isdir(os.path.join(ZA_EXPORTER_ROOT,
                                          "za_lookdev_exporter")):
            return
        if ZA_EXPORTER_ROOT not in sys.path:
            sys.path.append(ZA_EXPORTER_ROOT)
    except Exception as exc:
        print("Z-A Exporter could not be registered: %s" % exc)


maya.utils.executeDeferred(_register_za_exporter)
```

`import maya.utils` dosyanın başında olmalı. Blok baştan sona try ile
sarılıdır; klasör taşınmış olsa bile Maya'nın açılışını bozmaz.

**Shelf** — `Documents/maya/<sürüm>/prefs/shelves/` altına ayrı bir
`shelf_ZA_Exporter.mel` koy. Yeni bir dosya olduğu için mevcut shelf'lerin
etkilenmez; Maya açılışta yükler. İki buton önerilir: biri `za.show_ui()`,
diğeri `za.reload_package()` ile yeniden yükleyip UI'yi açan geliştirme
butonu.

1. `Export Location` seç.
2. Blender host/port değerlerini kontrol et. Varsayılan `127.0.0.1:50505`.
3. `Send To Blender` butonuna bas.

### Maya'da yeniden yükleme

Kodda değişiklik yaptıktan sonra `importlib.reload(za)` yetmez; package'da bu
yalnızca `__init__.py`'yi tazeler, submodule'ler eski kalır. Bunun yerine:

```python
za = za.reload_package()
za.show_ui()
```

`reload_package()` submodule'leri bağımlılık sırasına göre yeniler ve tazelenmiş
package'ı döndürür. Dönen değeri `za`'ya geri atamayı unutma.

## Blender kullanımı

`za_lookdev_importer` standart bir Blender multi-file add-on'udur. Üç kurulum
yolu var:

**1. Klasörü doğrudan kopyala** (geliştirme için en pratik)

`za_lookdev_importer` klasörünü Blender'ın add-on dizinine kopyala:

```text
%APPDATA%\Blender Foundation\Blender\<sürüm>\scripts\addons\za_lookdev_importer\
```

**2. Zip olarak kur**

`za_lookdev_importer` klasörünü zip'le, `Edit > Preferences > Add-ons > Install`
ile seç.

**3. Script dizini olarak tanıt**

`Preferences > File Paths > Scripts` altına package'ın **üstündeki** klasörü
ekle ve Blender'ı yeniden başlat.

Kurulumdan sonra `Edit > Preferences > Add-ons` içinde
`Z-A Exporter - Lookdev` kaydını etkinleştir.

`View3D > N Panel > Z-A Exporter` içinde:

1. Panelde yazan `Build` numarasının beklediğin sürüm olduğunu doğrula.
2. FBX Scale değerini kontrol et.
3. Host/Port değerlerini kontrol et.
4. `Start LiveLink` butonuna bas.

### Blender'da yeniden yükleme

Add-on olarak kurulduğunda `F3 > Reload Scripts` yeterlidir; `__init__.py`
submodule'leri bağımlılık sırasına göre kendisi yeniler ve `unregister()`
listener socket'ini ve timer'ını kapatır.

Port 50505 takılı kalırsa önce panelden `Stop LiveLink`, sonra `Reload Scripts`
yap. Add-on'u tamamen kaldırırken Blender'ın `unregister()` çağrısı socket'i
serbest bırakır; eski tek dosyalık sürümdeki elle socket avlama adımına artık
gerek yok.

## Işık aktarımı

Işıklar FBX içine yazılmaz. Maya sahnesindeki geçerli frame değerleri JSON
üzerinden gönderilir ve Blender'da `Z-A Lookdev Import > Z-A Lights` altında
yeniden oluşturulur.

Desteklenen eşlemeler:

- Redshift Physical Area → Blender Area
- Redshift Physical Point → Blender Point
- Redshift Physical Spot → Blender Spot
- Redshift Physical Directional → Blender Sun
- Redshift Dome → Blender World Environment
- Redshift IES → Blender Spot + IES texture node
- Arnold `aiAreaLight` → Blender Area (`aiTranslator`: quad/disk/cylinder)
- Arnold `aiSkyDomeLight` → Blender World Environment
- Arnold `aiPhotometricLight` → Blender Spot + IES texture node (`aiFilename`)
- Arnold `aiMeshLight` → Blender Area (yaklaşık)
- Native Maya Area/Point/Spot/Directional → karşılık gelen Blender light

Arnold `aiLightPortal` aktarılmaz: hiç color veya intensity attribute'u yok,
aktarılırsa Blender'da siyah bir alan ışığı olurdu.

Arnold ışıklarında exposure attribute'unun yazımı düzensizdir —
`aiAreaLight` ve `aiPhotometricLight` `exposure`, `aiSkyDomeLight`,
`aiMeshLight` ve Arnold'lu native Maya ışıkları ise yalnızca `aiExposure`
taşır. Alias tablosu ikisini de dener.

Aktarılan temel değerler:

- World konum ve rotasyon
- Transform scale üzerinden area boyutu
- Color ve color temperature
- Intensity, exposure ve fiziksel unit
- Area shape, normalize, spread ve bidirectional metadata
- Spot cone/falloff
- Shadow, softness ve contribution değerleri
- Dome HDR ve IES dosya yolları

Exposure değeri `intensity * 2^exposure` olarak değerlendirilir. Orijinal
değerler Blender light custom property'lerinde `za_source_*` alanlarıyla
korunur.

### Enerji modeli

Blender'ın light Power değeri **toplam ışıl akıdır**. Bu, dokümandan değil
render ölçümüyle doğrulandı: Blender 4.1 ve 5.2'de normalize açıkken bir
ışığın boyutu 4× olduğunda parlaklığı değişmiyor (oran 0.998), kapalıyken 16×
oluyor (=4²). `normalize` property'si olmayan eski Blender sürümleri de akı
modunda davranıyor.

Bu, Arnold'ın belgelediği sözleşmenin aynısı: normalize açıkken toplam
çıktı `O = C`, kapalıyken `O = C × A`. Redshift de aynı kavramı kullanıyor.

Importer bu yüzden **her ışığı toplam akıya çevirir** ve Blender'ın
`normalize`'ını açık bırakır. Alan çarpımını hem burada yapıp hem Blender'a
bırakmak alanı iki kez uygulardı.

Fiziksel birim bildiren ışıklar tam olarak çevrilir:

```text
Lumens     -> flux = intensity / 683
Candela    -> flux = intensity * 4pi / 683
Watts      -> dogrudan
Radiance   -> flux = intensity * alan * pi / 683
Sun        -> irradiance, alan ve normalize uygulanmaz
```

### Yoğunluktan watt'a dönüşüm

Arnold'ın `intensity`'si ve Redshift'in "Image" unit'i boyutsuzdur, Blender'ın
Power'ı ise watt cinsinden toplam akıdır. Bu dönüşüm **tahmin edilmedi,
ölçüldü**: Arnold ve Cycles'ta birebir aynı sahne render edilip oran çözüldü.

```text
Arnold        x pi     (olculdu)
Native Maya   x pi     (olculdu, MtoA ayni quad_light'a cevirir)
Redshift      x10      (olculemedi, orijinal aractan devralindi)
```

π tesadüf değil: Arnold'ın normalize edilmiş `intensity`'si ışığın normali
yönündeki ışıl şiddettir (`I₀`), Lambert yayıcı için toplam akı `Φ = π·I₀`, ve
Blender'ın Power'ı toplam akıdır. Yani:

```text
Blender Power = pi * intensity * 2^exposure
```

Mesafe, yoğunluk ve exposure değiştirilen beş varyantta çapa her seferinde
3.1412 çıktı (yayılım %0.00006). Yöntem ve ham sayılar için
`tests/light_calibration.md`.

> Bu, 1.7.0'dan önceki sürümlerde Arnold ve Maya ışıklarının **318× fazla
> parlak** geldiği anlamına gelir. Eski paketleri yeniden gönderirsen
> aydınlatma belirgin şekilde değişecek; doğrusu yenisidir.

`View3D > N Panel > Z-A Exporter > Light Power Scale` sanatsal bir çarpandır,
varsayılanı `1.0`. Bütün ışıkları eşit ölçekler, ışıklar arası oranları bozmaz.

Redshift kullanıyorsan devralınan tahmini tamamen atlamanın yolu var: ışığın
`unitsType` değerini Lumens, Candela veya Watts gibi fiziksel bir birime çevir.
O dallar tam çevrilir.

Blender'ın birebir karşılığı olmayan Cylinder/Mesh area light şekilleri
Rectangle Area olarak yaklaştırılır. Birden fazla Dome varsa Blender'ın tek
World ortamı için ilk aktif Dome kullanılır; diğer Dome kayıtları metadata
empty olarak korunur.

## Blender import davranışı

Yeni paket geldiğinde:

1. LiveLink protokolü ve paket şema sürümü doğrulanır. Uyumsuz bir paket
   **sahneye dokunulmadan** reddedilir.
2. Paketin FBX dosyası bulunur.
3. Açık Blender dosyası kayıtlıysa önce kaydedilir.
4. Sahnedeki bütün objeler ve collection'lar silinir.
5. Kullanılmayan mesh, material, image, texture, action ve diğer data-block'lar
   purge edilir.
6. Yeni FBX import edilir.
7. FBX'in oluşturduğu geçici material slotları temizlenir.
8. JSON'daki mesh → material ve yüz atamaları uygulanır.
9. Materialler Principled BSDF olarak yeniden kurulur.
10. Textureler Maya'daki orijinal dosya konumlarından bağlanır.
11. JSON ışıkları ve Dome World ortamı yeniden oluşturulur.
12. Bütün meshlerde Z-A Subdivision modifier ayarları kurulur.
13. Import sonunda tekrar recursive orphan purge yapılır.

Import yıkıcı olduğu için doğrulama adımları bilinçli olarak en başta yapılır:
Blender add-on'u Maya exporter'ından eskiyse paket reddedilir ve mevcut sahne
korunur. Desteklenen şema sürümleri `za_lookdev_importer/constants.py` içindeki
`SUPPORTED_SCHEMA_VERSIONS` ile tanımlıdır.

Tek bir material, texture veya ışık hatası import'u durdurmaz; uyarı olarak
toplanır ve Blender System Console'a `Z-A Lookdev warning:` önekiyle yazılır.

Bir mesh birden fazla material kullanıyorsa Maya shadingEngine face membership
bilgisi JSON'a yazılır ve Blender polygon material indexleri yeniden kurulur.

## Git

Bu klasör bağımsız Git deposudur:

```text
D:\GitHub_Repository\mayatools\ZA_Exporter\.git
```
