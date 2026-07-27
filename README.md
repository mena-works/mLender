# Z-A Exporter — Lookdev

Maya sahnesindeki bütün meshleri FBX olarak Blender'a canlı gönderen ve
materialleri Maya shader bilgilerine göre Blender Principled BSDF olarak yeniden
kuran Lookdev aktarım aracıdır.

Bu sürümde:

- Alembic yoktur.
- Texture kopyalama yoktur; yalnız bake edilen prosedüreller pakete yazılır.
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
  cameras.py                # kamera keşfi ve lens kayıtları
  livelink.py               # TCP gönderim istemcisi
  package.py                # paket klasörü, JSON yazımı, atomik temizlik
  ui.py                     # Maya penceresi

za_lookdev_importer/        # Blender tarafı (multi-file add-on)
  __init__.py               # bl_info, register/unregister, reload
  constants.py              # protokol sabitleri, socket adları, kalibrasyon
  utils.py                  # değer dönüşümü, isim normalizasyonu
  images.py                 # texture yükleme, UDIM çözümleme
  corrections.py            # Maya düzeltme node'larını Blender node'u olarak kurma
  materials.py              # Principled ve Surface Shader node ağaçları
  lights.py                 # Blender ışıkları ve Dome World
  cameras.py                # Blender kameraları
  transforms.py             # Maya→Blender matris dönüşümü (ışık+kamera ortak)
  scene.py                  # sahne temizleme, mesh eşleştirme, subdivision
  fbx.py                    # FBX import, paket dosyası çözümleme
  importer.py               # import orkestrasyonu, şema doğrulaması
  livelink.py               # socket listener ve ana thread mesaj pompası
  ui.py                     # operator'lar, scene property'leri, panel

tests/
  check_contracts.py        # host gerekmez, saniyeler
  host/                     # gerçek Maya ve gerçek Blender testleri
  calibration/              # render eşleşmesi, ölçek probları
  docs/                     # ölçüm kayıtları
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
- Specular (ağırlık)
- Transmission (weight, renk, roughness), IOR, Thin Walled

Arnold ve Redshift speküleri 0–1 ağırlık olarak verir; Blender'ın
`Specular IOR Level`'ında 0.5 sıradan bir dielektrik, 0 ise speküler yok
demektir. Bu yüzden ağırlık 1 Blender'ın varsayılanına eşlenir, 1'e değil.
Principled enerji koruduğu için bu önemlidir: Maya'da speküleri sıfır olan bir
yüzeye 0.5 bırakmak hem olmayan bir parlama ekler hem o enerjiyi diffuse'dan
çalar.

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
texture yolu JSON'a yazılır. Ara node'lar artık **atlanmıyor**: tanınanlar
Blender'da node olarak yeniden kuruluyor, tanınmayanlar uyarı olarak
bildiriliyor (aşağıda "Renk düzeltme"). Çok katmanlı/prosedürel ağların
matematiksel sonucu bu yolla ifade edilemiyorsa bake devreye girer.

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

**3. Junction / symlink** (geliştirme için en iyisi)

Kopyalamak yerine add-on klasörünü depoya bağla; `git pull` sonrası kopyalama
derdi kalmaz:

```bat
mklink /J "%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\za_lookdev_importer" ^
          "<depo>\za_lookdev_importer"
```

Windows'ta dizin junction'i yönetici hakkı istemez. Linux/macOS'ta
`ln -s` aynı işi görür.

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
Blender'ın Power'ı toplam akıdır.

Buna sahne biriminin karesi de girer, çünkü Arnold birimden bağımsızdır:
santimetre sahnede 150 birimlik mesafe Blender'da 1.5 m olur ve aydınlatma
`1/d²` ile 10⁴ kat şaşar.

```text
Blender Power = pi * meters_per_maya_unit^2 * intensity * 2^exposure
```

Mesafe, yoğunluk ve exposure değiştirilen beş varyantta çapa her seferinde
3.1412 çıktı (yayılım %0.00006). Yöntem ve ham sayılar için
`tests/docs/light_calibration.md`.

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
12. JSON kameraları kurulur ve renderable olan aktif kamera yapılır.
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

## Texture yerleşimi

Maya tiling'i ayrı bir `place2dTexture` node'unda tutar. Upstream taraması
dosyayı bulup bu node'un yanından geçtiği için değerler eskiden **sessizce
düşüyordu**: Maya'da 4×3 tekrarlanan bir texture Blender'a 1×1 geliyordu.

Artık bir **Mapping** node kurulur:

```text
repeatU / repeatV   -> Mapping Scale X / Y
offset              -> Mapping Location X / Y
rotateUV            -> Mapping Rotation Z   (derece -> radyan)
wrapU / wrapV       -> Image extension REPEAT, kapaliysa EXTEND
mirrorU / mirrorV   -> Image extension MIRROR
```

`rotateUV` bir `doubleAngle` attribute'udur ve `getAttr` onu geçerli açı
biriminde (varsayılan derece) döndürür; JSON'a `rotate_uv_degrees` adıyla
derece olarak yazılır ve importer radyana çevirir.

Yerleşim varsayılan değerlerdeyse Mapping node kurulmaz, node ağacı gereksiz
kalabalıklaşmaz.

## Bump şiddeti

`bump2d.bumpDepth` artık taşınıyor ve Blender'ın Normal Map node'unun
`Strength` girişine gidiyor. Eskiden düşüyordu, yani her normal map varsayılan
1.0 şiddetle geliyordu.

`bumpInterp` de okunuyor: `Tangent Space Normals` → Normal Map node,
`Object Space Normals` → Normal Map node `space = OBJECT`, düz `Bump` →
Blender'ın **Bump** node'u (yükseklik alanı olarak).

## Coat, Sheen, Subsurface

`aiStandardSurface` ve `aiOpenPBRSurface`'in ek lobları da aktarılıyor:

```text
coat / coatWeight        -> Coat Weight
coatRoughness            -> Coat Roughness
coatColor                -> Coat Tint
coatIOR                  -> Coat IOR
sheen / fuzzWeight       -> Sheen Weight
sheenRoughness           -> Sheen Roughness
sheenColor / fuzzColor   -> Sheen Tint
subsurface / weight      -> Subsurface Weight
subsurfaceRadius         -> Subsurface Radius
subsurfaceScale          -> Subsurface Scale
specularAnisotropy       -> Anisotropic
```

İki not:

- **Principled'da ayrı bir Subsurface Color soketi yok** (4.1 ve 5.2'de
  ölçüldü); base color'dan renklenir. Maya'nın `subsurfaceColor` değeri bu
  yüzden metadata olarak saklanır, sessizce atılmaz.
- **`Subsurface Scale` varsayılanı sürümler arası farklı** (4.1'de 0.05,
  5.2'de 0.005). Bu yüzden değer açıkça set edilir; varsayılana güvenmek aynı
  paketi iki sürümde farklı gösterirdi.

## Renk yönetimi

Aktarım doğru olduğu halde görüntünün "bir tuhaf" görünmesinin en sık sebebi
budur: geometri, material ve ışıklar tutar, ama iki uygulama farklı tone
mapping yapar.

Maya'nın renk yönetimi ayarı artık pakete yazılıyor ve Blender'da kurulmaya
çalışılıyor:

```text
renderingSpaceName    ACEScg
viewTransformName     ACES 1.0 SDR-video (sRGB)
displayName           sRGB
configFilePath        ...\OCIO-configs\Maya2022-default\config.ocio
```

**Önemli sınır, ölçüldü:** Blender'ın kendi OCIO config'inde **hiçbir sürümde
ACES view transform yok** (4.1, 4.5 ve 5.2'de tek tek denendi; sadece
Standard, Raw, Filmic, Filmic Log, False Color, AgX ve 4.5'ten itibaren
Khronos PBR Neutral var).

Bu yüzden davranış şu:

- Blender'da Maya'nın istediği transform **varsa** aynen kurulur. ACES config
  yüklü bir Blender'da bu birebir eşleşir.
- **Yoksa** en yakın karşılığı kurulur ve **uyarı yazılır** — hangi
  transform'un istendiğini ve hangi OCIO config'e işaret edilmesi gerektiğini
  söyleyerek:

```text
Maya was using the "ACES 1.0 SDR-video (sRGB)" view transform, which this
Blender's colour config does not have; "Standard" was used instead. To match
exactly, point Blender at the same OCIO config through the OCIO environment
variable: C:/Program Files/Autodesk/Maya2023/resources/OCIO-configs/...
```

AgX'i olduğu gibi bırakıp "eşleşti" demek tek gerçekten yanıltıcı sonuç
olurdu; onun yerine tanımlı bir transform kurulur.

Maya'da renk yönetimi kapalıysa sahne ham lineer kabul edilir ve `Standard`
kurulur.

## Görünürlük ve render bayrakları

Maya'da kameraya gizlenmiş ama gölge bırakan bir obje eskiden Blender'a
**tamamen görünür** geliyordu; lookdev'in en sık kurulumlarından biri sessizce
kayboluyordu. Artık ışın bazlı görünürlük aktarılıyor:

```text
primaryVisibility                 -> visible_camera
castsShadows                      -> visible_shadow
aiVisibleInDiffuseReflection      -> visible_diffuse
aiVisibleInSpecularReflection     -> visible_glossy
aiVisibleInSpecularTransmission   -> visible_transmission
aiVisibleInVolume                 -> visible_volume_scatter
aiMatte / holdOut                 -> is_holdout
visibility (transform)            -> hide_render + hide_viewport
lodVisibility                     -> hide_viewport
```

Arnold ışın görünürlüğünü Maya'dan daha ince ayırır ve kendi `ai*`
attribute'larını okur; Maya'nın `visibleInReflections`/`visibleInRefractions`
değerleri diğer renderer'lar içindir. İkisi de aday listesinde, önce Arnold'unki.

**Yalnız varsayılandan farklı olan bayraklar yazılır.** Sıradan bir mesh hiç
bayrak üretmez ve Blender'ın kendi varsayılanlarına dokunulmaz — böylece
aktarım, sahnenin istemediği bir şeyi bütün meshlere uygulamaz.

Gizli bir Maya mesh'i Blender'da hem viewport'ta hem **render'da** gizlenir;
yalnız viewport'u gizlemek render'da yine görünmesine yol açardı.

Bu bayraklar **Cycles** özellikleridir; EEVEE ışın görünürlüğünü yok sayar.

## Animasyon (turntable)

Varsayılan olarak **kapalı** — araç tek frame gönderir. Maya penceresindeki
`Export Animation` kutusu işaretlenirse frame aralığı aktarılır.

Aracın turntable üreten bir modu **yok**: sahnede ne animasyonluysa o gelir.
Kamera dönüyorsa kamera döner, obje dönüyorsa obje döner.

```text
Frame Range   bos     -> Maya'nin playback range'i (minTime - maxTime)
              1-120   -> acikca aralik
              1-120x2 -> iki frame'de bir ornekle
```

İki farklı yol kullanılır ve bu bilinçlidir:

- **Meshler FBX'in içinde gelir.** FBX zaten animasyon taşır ve deformer'ları
  doğru aktaran tek yol odur; `FBXExportBakeComplexAnimation` aralıkla birlikte
  açılır.
- **Kamera ve ışıklar JSON'da örneklenir**, çünkü onlar Blender'da sıfırdan
  kuruluyor. Her frame için world matrix, kamera lensi, ışık şiddeti ve rengi
  yazılır.

Işık enerjisi frame başına **yeniden hesaplanır**, interpolate edilmez —
böylece her frame ölçülmüş dönüşümden geçer.

FPS Maya'dan okunur (`currentTimeUnitToFPS`) ve NTSC kesirleri Blender'ın
`fps` / `fps_base` çiftiyle tam olarak kurulur (23.976 → 24 / 1.001).

### İki tuzak, ikisi de turntable'ı bozardı

- **Euler sıçraması.** Her frame'in matrisi bağımsız çözülürse açılar iki
  frame arasında tam tur atlayabilir; 360° dönen bir kamera ansızın geri
  dönüyormuş gibi görünür. Her frame bir öncekiyle uyumlu hale getirilir
  (`make_compatible`). Test bunu tam tur üzerinde sınıyor.
- **Interpolasyon.** Bake edilmiş örnekler doğrusaldır. Blender'ın varsayılan
  Bezier'i her iki anahtar arasında yavaşlatıp hızlandırır ve sabit bir dönüşü
  kesik kesik gösterir. Anahtarlar `LINEAR` yapılır.

Frame sayısı üst sınırı **2000**; aşılırsa aralık kırpılır ve pakete "kırpıldı"
yazılır, sessizce eksik gönderilmez.

## Displacement

Maya displacement'ı **shader'da değil, shadingEngine'de** durur —
`aiStandardSurface`'in displacement attribute'u yoktur. Bu yüzden mesh ile
shading engine birlikte okunur: harita engine'den, yükseklik ve sıfır değeri
mesh'ten gelir.

İki kablolama da tanınır, ikisi de gerçek sahnelerde görülüyor:

```text
file -> displacementShader -> SG.displacementShader     (yaygın olan)
file --------------------->  SG.displacementShader      (Arnold bunu da render eder)
```

Blender'da bir **Displacement** node kurulur ve material output'un
`Displacement` girişine bağlanır. Eşleme birebir, çünkü iki taraf da aynı
formülü hesaplıyor — `(harita - midlevel) * scale`:

```text
aiDispHeight * displacementShader.scale  ->  Scale
aiDispZeroValue                          ->  Midlevel
harita                                   ->  Height
aiDispAutobump                           ->  displacement_method = BOTH
                                             (kapalıysa DISPLACEMENT)
```

**Birim ölçeği bilerek eklenmiyor.** Ölçtüm: FBX import'unda birim dönüşümü
obje scale'ine biniyor, vertex koordinatları Maya biriminde kalıyor. Yani
object space'te 1 birimlik displacement zaten 1 Maya birimidir. Bu, ışık
enerjisi kuralının **tersidir** (orada `position_scale²` zorunlu); buraya da
eklemek santimetre sahnelerde 100 kat fazla displacement verirdi.

İki sınır:

- **Vector displacement kurulmuyor**, uyarı yazılıyor. Yalnız skaler yükseklik
  aktarılıyor.
- Mesh subdivision istemiyorsa uyarı yazılıyor: displacement'ın kıpırdatacak
  geometrisi olmaz. (Arnold'da da aynı şey geçerli.)

Displacement bir **Cycles** özelliğidir; EEVEE onu yok sayar.

`Scale` soketinin varsayılanı sürümler arası farklı (4.1'de 1.0, 5.2'de 0.01),
bu yüzden değer her zaman açıkça set edilir.

## Grup hiyerarşisi → Collection

Maya'daki grup yapısı Blender'da **iç içe collection** olarak yeniden kurulur.
Eskiden bütün meshler tek bir kök collection'a düz olarak giriyordu; kalabalık
bir sahnede outliner kullanılamaz hale geliyordu.

```text
Maya                              Blender
|setDressing|props|chair    ->    Z-A Lookdev Import
                                    setDressing
                                      props
                                        chair
```

Kurallar:

- **Yalnız gerçek gruplar klasör olur.** Kendi shape'i olan bir transform obje
  sayılır, klasör değil; yoksa geometri taşıyan bir transform olmayan bir
  nesting seviyesi uydururdu.
- Grubu olmayan mesh kök collection'da kalır.
- Aynı Maya grubundaki iki mesh **aynı** collection'a girer, isim benzeri iki
  ayrı collection oluşmaz.
- Üretilen collection'lar `za_generated` ve `za_maya_group` custom
  property'lerini taşır.

Işıklar ve kameralar bu hiyerarşiye girmez; `Z-A Lights` ve `Z-A Cameras`
altında toplu kalırlar, çünkü lookdev sırasında hepsine birden erişmek
istenir.

## Renk düzeltme

Texture ile shader arasındaki düzeltme node'ları eskiden **sessizce
atlanıyordu**: upstream taraması dosyayı bulmak için üzerlerinden geçiyor,
gamma'sı ve doygunluğu değiştirilmiş bir texture Blender'a ham geliyordu.

Artık tanınan node'lar Blender node'u olarak yeniden kuruluyor — bake'den
hızlı ve sonradan elle düzenlenebilir:

| Maya / Arnold    | Blender                                          |
|------------------|--------------------------------------------------|
| `aiColorCorrect` | Gamma + Hue/Saturation + Bright/Contrast + Mix   |
| `gammaCorrect`   | Gamma                                            |
| `aiRange`        | Mix (scale) + Mix (offset) + Bright/Contrast     |
| `aiMultiply`     | Mix (Multiply)                                   |
| `aiAdd`          | Mix (Add)                                        |
| `reverse`        | Invert                                           |

Node'lar `ZA_CC_` / `ZA_` önekiyle adlandırılır. Bir ayar nötr değerindeyse o
node hiç kurulmaz, yani dokunulmamış bir düzeltme node'u ağacı kalabalıklaştırmaz.

Üç dönüşüm ölçüldü ve sezginin tersi çıktı (ayrıntı: `tests/docs/correction_nodes.md`):

- **`gamma` ters üstür.** Maya `in^(1/g)` uygular, Blender'ın Gamma node'u
  `in^g`. Değer bu yüzden tersine çevrilerek yazılır.
- **`hueShift` tur cinsindendir**, derece değil. Blender'ın Hue'su ise 0.5'i
  nötr alan bir ofsettir.
- **`contrast` pivotludur.** Arnold `c*(in-pivot)+pivot`, Blender ise
  `(1+C)*in + (B-C/2)`. İkisini eşitleyen çift ölçümle doğrulandı: aynı girdi
  her iki tarafta da `0.820000` veriyor.

`exposure` ayrı bir node kurmaz; multiply ile aynı node'a katlanır.

**Kurulamayanlar bildirilir.** `remapValue`, `blendColors`, `aiComposite` gibi
karşılığı olmayan node'lar için import sonrası uyarı yazılır (Blender System
Console veya panel status satırı):

```text
Correction node "remapCoat" (remapValue) has no Blender equivalent,
so the texture is used without it.
```

`aiRange`'in `smoothstep`, `bias` ve `gain` ayarları da kurulmaz ve ayrıca
uyarılır; doğrusal remap ve contrast kurulur.

## Prosedürel bake

Bir kanal dosyası olmayan bir ağla sürülüyorsa (checker, ramp, katmanlı noise)
referans verilecek bir şey yoktur. Exporter bu durumda ağı mesh'in UV'lerine
**bake eder** ve paketin içine yazar.

```text
MTB_Z_A_01/
  MTB_Z_A_01.fbx
  MTB_Z_A_01_lookdev.json
  textures/
    procCube_shd_base_color.png
    procCube_shd_roughness.png
```

Bake yalnızca gerçekten gerektiğinde çalışır: upstream taraması bir dosya
bulursa o dosya referans verilir, bake edilmez.

Maya UI'da iki kontrol var: `Bake Procedurals` ve `Bake Resolution`
(varsayılan 1024).

İki ölçülmüş kısıt tasarımı belirledi:

- **Maya lineer yazar.** `convertSolidTx`, renk yönetimi açık da olsa kapalı da
  olsa lineer değer yazıyor (0.5 girdi → 0.498 saklanan; sRGB olsaydı 0.735).
  Bu yüzden baked map'ler Blender'da **renk kanalı bile olsa Non-Color** yüklenir.
  sRGB sanmak her bake'i koyulturdu.
- **EXR yazamaz.** File node yolu gösteriyor ama diske bir şey düşmüyor. Format
  bu yüzden PNG.

Renk kanalları için 8-bit lineer PNG karanlıklarda bant verebilir; bu bilinçli
bir takas, alternatifi hiç aktarmamak.

Bake edilen kayıt nereden geldiğini de taşır (`baked_from`), yani Blender'da
bir map'in hangi Maya node'undan çıktığı JSON'dan izlenebilir.

Bake mesh'in UV'lerini kullanır. UV'si olmayan veya bozuk olan bir mesh'te
sonuç boş çıkar; bu durumda export uyarı listesine yazılır ve akış durmaz.

## Kamera aktarımı

Maya'nın startup kameraları (`persp`, `top`, `front`, `side`) viewport
mobilyasıdır, aktarılmaz. Kullanıcının oluşturduğu kameralar
`Z-A Lookdev Import > Z-A Cameras` altında yeniden kurulur.

Maya ile Blender kameraları aynı yöne bakar (yerel -Z ileri, +Y yukarı), yani
ışıklarla aynı matris dönüşümü geçerli. Fark lenste ve birimlerde:

```text
focalLength              -> lens (mm, dogrudan)
horizontalFilmAperture   -> sensor_width   (inc x 25.4)
verticalFilmAperture     -> sensor_height  (inc x 25.4)
filmFit                  -> sensor_fit     (Fill/Overscan -> AUTO)
horizontalFilmOffset     -> shift_x        (apertura bolunur, oran olur)
nearClipPlane/farClip    -> clip_start/end (sahne birimi -> metre)
orthographicWidth        -> ortho_scale    (sahne birimi -> metre)
depthOfField/fStop       -> dof.use_dof / dof.aperture_fstop
focusDistance            -> dof.focus_distance (sahne birimi -> metre)
```

Maya'da `renderable` işaretli kamera Blender'ın aktif sahne kamerası yapılır.
Birden fazla renderable kamera varsa ilki seçilir ve uyarı verilir.

Orijinal değerler camera data'sında `za_source_*` alanlarında saklanır.

## Subdivision

Subdivision **her mesh'e uygulanmaz**; yalnızca Maya'daki mesh gerçekten
istiyorsa uygulanır. Kaynak şu sırayla aranır, çünkü renderer ayarı gerçekten
render edilen şeydir ve Maya'nın smooth preview'ı niyetin yedeğidir:

```text
1. Arnold    aiSubdivType != none   -> aiSubdivIterations
2. Redshift  rsEnableSubdivision    -> rsMaxTessellationSubdivs
3. Maya      displaySmoothMesh != 0 -> smoothLevel / renderSmoothLevel
```

Hiçbiri istemiyorsa mesh'e modifier eklenmez. Arnold'un `aiSubdivType`
varsayılanı **none** olduğu için, modellenmemiş bir küpü Catmull-Clark ile
yuvarlamak yerine olduğu gibi bırakır.

Şema eşlemeleri:

- `catclark` → Blender `CATMULL_CLARK`
- `linear` → Blender `SIMPLE`
- `aiSubdivUvSmoothing`: `pin_corners` → `PRESERVE_CORNERS`,
  `pin_borders` → `PRESERVE_BOUNDARIES`, `smooth` → `SMOOTH_ALL`

Maya'da `useSmoothPreviewForRender` kapalıysa viewport seviyesi `smoothLevel`,
render seviyesi `renderSmoothLevel` olarak ayrı ayrı aktarılır. Kaynağın
hangisi olduğu mesh data'sında `za_subdivision_source` ile saklanır.

> Şema 6'dan eski paketlerde subdivision kaydı yoktur ve o meshler
> **subdivide edilmez**. 1.9.0 öncesinde her mesh subdivide ediliyordu; eski
> bir paketi yeniden göndermen yeterli.

## Git

Bu klasör bağımsız Git deposudur:

```text
D:\GitHub_Repository\mayatools\ZA_Exporter\.git
```
