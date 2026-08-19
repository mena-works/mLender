# CLAUDE.md — mLender (Lookdev)

> Bu dosya bu repo için geçerlidir ve üst klasördeki (`Downloads/CLAUDE.md`)
> Unreal Engine kurallarının **yerine geçer**. Bu repoda Unreal **alıcı bir
> hedef**tir (`mlender_unreal`, editör Python'u); Blueprint, C++ modülü veya
> it-is-unreal MCP ile ilgili hiçbir şey yoktur.

---

## Proje Bilgisi

- **Ne yapar:** Maya sahnesini FBX + JSON paketi olarak Blender'a **ve Unreal'a**
  canlı gönderir; Blender tarafında materialleri Principled BSDF olarak,
  ışıkları native Blender light olarak, Unreal tarafında materialleri Material
  Instance olarak, ışıkları Unreal light actor olarak yeniden kurar.
- **Hedef sürümler:** Maya 2022+ (Redshift), Blender 3.6+ (4.x dahil),
  Unreal 5.8 (5.8.1'de doğrulandı)
- **Dil:** Promptlar ve açıklamalar Türkçe; kod, değişken, fonksiyon,
  yorumlar, commit mesajları **ve README** İngilizce. Depo `mena-works`
  altında public olduğu için README dış dokümantasyondur.
  `tests/docs/` altındaki ölçüm kayıtları Türkçe kalır — onlar iç notlardır.
- **Test/build yok.** Doğrulama elle yapılır (aşağıda "Doğrulama").

---

## 1. Dosya Yapısı

**Üç** bağımsız Python package. Bağımlılık yönü tek yönlüdür ve döngü yoktur;
bir modül yalnızca kendinden önce listelenenleri import edebilir.

```text
mlender_exporter/     # Maya (import sırası = bağımlılık sırası)
  constants.py           # sabitler, attribute alias tabloları
  mayautils.py           # maya.cmds sarmalayıcıları
  collect.py             # texture'ları pakete kopyalama (opsiyonel)
  animation.py           # frame aralığı ve zaman çizgisi örnekleme
  textures.py            # upstream texture arama
  bake.py                # prosedürel ağları UV'ye bake etme
  tessellate.py          # NURBS/subdiv yüzeyleri geçici polygon olarak
  shaders.py             # shader → kanal çıkarımı
  meshes.py              # mesh keşfi, material/face atamaları
  transforms.py          # locator ve boş null'lar
  curves.py              # NURBS/bezier eğriler
  volumes.py             # aiVolume (VDB yolu)
  standins.py            # aiStandIn ve gpuCache (dosya referansı)
  particles.py           # parçacık noktaları, kare kare bake
  instancers.py          # particle instancer (nokta üzerine geometri)
  render.py              # çözünürlük, aspect, motion blur
  sets.py                # selection set ve display layer
  lights.py              # ışık keşfi ve kayıtları
  cameras.py             # kamera keşfi ve lens kayıtları
  coverage.py            # taşınmayanı sayan tarama (sessiz kaybı bitirir)
  fbx.py                 # MEL FBXExport
  alembic.py             # deforme mesh + emitter particle için AbcExport
  livelink.py            # TCP istemci
  posebridge.py          # canlı poz köprüsü (Maya değerlendirir, iskelet akar)
  asrig.py               # Advanced Skeleton manifesti (DeformSet, FKIK zincirleri)
  presets.py             # export ayarları (UI ve batch aynı sözleşme)
  batch.py               # UI'siz export girisi (farm, gece publish)
  report.py              # pakete yazılan export raporu
  package.py             # paket klasörü, JSON, atomik temizlik
  ui.py                  # Maya penceresi
  __init__.py            # public API + reload_package()

mlender_importer/     # Blender multi-file add-on
  constants.py
  utils.py               # değer/isim normalizasyonu
  images.py              # texture yükleme, UDIM
  corrections.py         # Maya düzeltme node'larını yeniden kurma
  materials.py           # node ağaçları
  lights.py              # Blender ışıkları, Dome World
  cameras.py             # Blender kameraları
  transforms.py          # Maya→Blender matris (ışık+kamera ortak)
  colormanagement.py     # Maya OCIO ayarı → Blender view transform
  animation.py           # örneklenen animasyonu keyframe olarak kurma
  scene.py               # sahne temizleme, mesh eşleştirme, subdivision
  attributes.py          # custom property'ler
  empties.py             # locator → Empty
  curves.py              # Blender eğrileri
  volumes.py             # Blender volume objesi
  standins.py            # standin çapası ve içeriği
  particles.py           # vertex-only mesh + konum keyframe'leri
  instancers.py          # vertex instancing (dupli-verts, ölçüldü)
  render.py              # sahne render ayarları
  sets.py                # collection olarak set ve layer
  merge.py               # Replace / Merge / Add
  fbx.py                 # FBX import, paket dosyası çözümleme
  alembic.py             # paket cache'ini okuma (eksen/ölçek ölçüldü)
  importer.py            # orkestrasyon + şema doğrulaması
  posebridge.py          # gelen pozu armature'lara uygulama
  asrig.py               # AS kontrol katmanı: custom shape + IK + FKIK property
  livelink.py            # socket listener + ana thread pompası
  ui.py                  # operator, property, panel
  __init__.py            # bl_info, register/unregister, reload bloğu

mlender_unreal/       # Unreal plugin (klasörün kendisi plugin'dir)
  mLender.uplugin        # plugin manifesti; VersionName BUILD_VERSION ile eş
  Content/Python/        # Unreal bir plugin'in Python'unu YALNIZ burada sys.path'e koyar
    init_unreal.py       # editör açılışında kendiliğinden çalışır
    mlender_unreal/      # asıl package (import sırası = bağımlılık sırası)
      constants.py         # protokol sabitleri, ölçülmüş dönüşümler, kanal tabloları
      utils.py             # değer/yol/isim normalizasyonu (unreal import etmez)
      transforms.py        # Maya→Unreal matris; ışık/kamera ve obje AYRI dönüşüm
      objects.py           # JSON'dan kurulan her şey için ortak yerleştirme
      images.py            # texture import, sRGB/compression
      materials.py         # master material üretimi + Material Instance
      graphs.py            # blend shader'lar için materyal başına graph
      lights.py            # Unreal light actor'leri, lümen/lüks
      cameras.py           # CineCameraActor, filmback ve focus
      meshes.py            # Interchange FBX scene import, materyal slot eşleşmesi
      empties.py           # locator ve boş null → Actor, parent zinciriyle
      curves.py            # NURBS/bezier → Blueprint üstünde SplineComponent
      volumes.py           # VDB → Sparse Volume Texture + Heterogeneous Volume
      standins.py          # .abc → Geometry Cache; okunamayan → çapa
      particles.py         # parçacık çapası + instancer'ın nokta kaynagı
      instancers.py        # nokta başına StaticMeshActor, mesh paylaşımlı
      animation.py         # ışık/kamera/görünürlük/materyal anahtarları (Level Sequence)
      aovs.py              # AOV'lar → Movie Render Queue config
      sets.py              # selection set / display layer → Unreal Layer
      scene.py             # level temizleme ve doğrulama
      importer.py          # orkestrasyon + şema doğrulaması
      livelink.py          # socket listener + game thread pompası
      ui.py                # Tools menüsü
      __init__.py          # public API + reload_package()

packaging/               # kurulabilir çıktılar
  build_release.py       # Blender add-on .zip + Maya modülü + Unreal plugin .zip
  verify_release.py      # üçünü de gerçek host'lara kurup dener

tests/                   # amaca göre ayrılmış, ayrıntı tests/README.md
  check_contracts.py     # host gerekmez, saniyeler — en sık çalıştırılan
  host/                  # gerçek Maya ve gerçek Blender testleri
  calibration/           # render eşleşmesi, ölçek probları, performans rig'i
  docs/                  # ölçüm kayıtları (ışık, materyal, düzeltme node'ları)

README.md                # Kullanıcı dokümantasyonu (Türkçe)
```

`tests/` üç gruba ayrılmıştır çünkü üçü farklı şeyler yapar: sözleşme
kontrolleri saniyede çalışır ve her değişiklikten sonra çalıştırılır, `host/`
gerçek DCC ister, `calibration/` ise test değil **ölçüm rig'idir** — sabitleri
doğrulamaz, onları üretir. Yeni bir dosya eklerken hangisine ait olduğuna karar
ver; ölçüm rig'lerini `host/` içine koyma.

Üç package birbirini **import etmez**. Aralarındaki tek bağ, aşağıdaki
protokol ve JSON sözleşmesidir. Ortak yardımcı modül ekleme — Maya, Blender ve
Unreal farklı Python runtime'larında çalışır, paylaşılan dosya deploy'u kırar.
Bu yüzden protokol sabitleri ve şema listesi üç yerde **kopyalanmıştır**;
onları tek dosyaya toplama, `check_contracts.py` eşitliği zorluyor.

`mlender_unreal`'ın iç içe yapısı tercih değil zorunluluk: Unreal bir plugin'in
Python'unu yalnız `<Plugin>/Content/Python` altından `sys.path`'e koyar ve
`init_unreal.py`'ı yalnız orada çalıştırır. Klasörün kendisi plugin olduğu için
geliştirme kurulumu tek junction'dır.

Bölünme öncesi tek dosyalık sürümler git geçmişinde `0dcbff4` commit'indedir.
Oradan "mevcut davranış" çıkarma; tek doğru kaynak package'lardır.

### Yeni modül eklerken

1. Modülü bağımlılık sırasında doğru yere koy.
2. Exporter'da `__init__.py` içindeki `SUBMODULES` tuple'ına ekle.
3. Importer'da `__init__.py` içindeki reload bloğunun **iki listesine** de ekle.
4. Unreal alıcısında `__init__.py` içindeki `SUBMODULES` tuple'ına **ve** import
   bloğuna ekle.

Bu listeler reload sırasını belirler. Eksik bırakılan modül, geliştirme
sırasında sessizce eski kodla çalışmaya devam eder — ve bu, düzenlemenin
işlememesi gibi görünür.

Artık `check_contracts.py` üçünü de zorluyor: her `.py` her listede olmak
zorunda, ve exporter listesi var olmayan bir modül adı taşıyamaz. İki importer
listesi ayrı ayrı okunuyor; tek desenle bakmak ikisinin birleşimini eşleştirir
ve birinden eksik bir modül testten geçer.

---

## 2. Çalışma Ortamı Kısıtları

### Exporter (`mlender_exporter/`)

- Maya'nın gömülü Python'unda çalışır. `maya.cmds` ve `maya.mel` dışında
  **üçüncü parti bağımlılık yok**, standart kütüphane yeterli.
- Dosya `from __future__ import print_function` ile başlar ve baştan sona
  `.format()` kullanır. **f-string, walrus, type hint ekleme** — eski Maya
  sürümleriyle uyum bilinçli bir karar.
- Blender'a özgü hiçbir şey import edilemez (`bpy`, `mathutils`).

### Unreal alıcısı (`mlender_unreal/`)

- Unreal'in gömülü Python'unda çalışır (5.8.1'de **3.11.8**). `unreal` dışında
  bağımlılık yok.
- Maya'ya veya Blender'a özgü hiçbir şey import edilemez (`maya.cmds`, `bpy`,
  `mathutils`). Vektör matematiği `math` ile elle yazılır.
- `utils.py` bilinçli olarak `unreal` **import etmez**; sözleşme testinin host
  olmadan çalıştırdığı fonksiyonlar oradadır.
- `mLender.uplugin` bir Unreal manifestidir; `VersionName` `BUILD_VERSION` ile
  eş olmak zorunda (`check_contracts.py` ve `build_release.py` ikisi de bakar).
  Bu, Blender'daki `bl_info["version"]`'ın karşılığıdır.
- Klasör adı plugin adı **değildir**: Unreal plugin'i `.uplugin` dosyasının
  adından tanır. Depoda klasör `mlender_unreal`, dağıtımda `mLender`.
- `unreal` modülü thread-safe **değildir** (bkz. bölüm 6).

### Importer (`mlender_importer/`)

- Blender'ın Python'unda çalışır. `bpy` + `mathutils` dışında bağımlılık yok.
- Maya'ya özgü hiçbir şey import edilemez (`maya.cmds`).
- `bl_info` bir Blender add-on manifestidir ve `__init__.py`'nin en üstünde,
  reload bloğundan **önce** durmalıdır; Blender bu sözlüğü dosyayı çalıştırmadan
  parse eder. Bozulursa add-on listede görünmez.
- Klasör adı add-on'un modül adıdır. Değiştirirsen kullanıcının kurulu
  add-on'u kopyalanır, güncellenmez.

---

## 3. LiveLink Protokolü — Değiştirilmesi Riskli Sözleşme

Aşağıdaki sabitler **iki dosyada da** aynı olmak zorunda:

| Sabit                | Değer                  |
|----------------------|------------------------|
| `LIVELINK_HOST`      | `127.0.0.1`            |
| `LIVELINK_PORT`      | `50505`                |
| `LIVELINK_PROTOCOL`  | `mlender_livelink`  |
| `LIVELINK_VERSION`   | `1`                    |

Kurallar:

- Mesaj formatı: tek satır UTF-8 JSON + `\n`. Importer `\n`'e kadar okur.
- Mesaj boyutu üst sınırı importer'da `MAX_MESSAGE_BYTES` (32 MB).
- `_validate_message()` protocol, protocol_version, event ve `package_json`
  varlığını kontrol eder. İki event vardır: `scene_package_ready` ve
  `pose_update`; bilinmeyen event **açık hatayla** reddedilir, bu yüzden yeni
  event eklemek sürüm artırmadan geriye uyumludur. Yeni alan eklemek geriye uyumludur; **alan silmek
  veya yeniden adlandırmak breaking'dir.**
- Breaking bir değişiklik yapıyorsan `LIVELINK_VERSION`'ı **her iki dosyada
  birlikte** artır. Tek taraflı artırma sessiz değil, açık hata verir — bu iyi;
  ama iki tarafı da güncellemeden commit etme.
- `EXPORT_SCHEMA_VERSION` (exporter, şu an `41`) JSON'a yazılır ve importer
  `SUPPORTED_SCHEMA_VERSIONS` ile doğrular. Şema kırıcı bir değişiklik
  yaparsan exporter'da sürümü artır **ve** importer'ın desteklenen sürüm
  listesini güncelle.
- Şema doğrulaması sahne silinmeden **önce** yapılır (`importer.py` içindeki
  `validate_schema_version`). Bu sıralamayı bozma; import yıkıcıdır ve
  uyumsuz bir paket kullanıcıya sahnesine mal olmamalıdır.

---

## 4. Kanal Sözleşmesi (Material)

Exporter'ın ürettiği kanal anahtarları, importer'ın `_principled_input()`
eşlemesiyle birebir uyuşmalıdır:

```text
base_color  roughness  specular  metallic  opacity  normal  emission
emission_strength  transmission  transmission_color  transmission_roughness
ior  thin_walled  transmission_affects_alpha
```

Üç build yolu var ve kanalın hangisine gittiği `constants.py`'de açıktır:

- `PRINCIPLED_INPUTS` — Principled BSDF soketleri
- `GLASS_INPUTS` — transmission sıfırdan büyükse kurulan Glass BSDF soketleri
- `METADATA_CHANNELS` — soketi olmayan, yolu seçen veya custom property olarak
  saklanan kanallar

Yeni kanal eklerken bu üç sözlükten **birine** girmeli; sözleşme testi
kapsanmayan kanalı yakalar.

Her kanal kaydı şu alanları taşıyabilir:

```json
{
  "maya_attr": "refl_roughness",
  "maya_plug": "shader.refl_roughness",
  "value": 0.4,
  "texture": { "path": "...", "node": "...", "color_space": "..." },
  "invert": true,
  "semantic": "maya_transparency_to_opacity"
}
```

- Yeni kanal eklerken **üç yeri birden** güncelle: exporter kanal tablosu,
  importer'daki ilgili soket sözlüğü, ve gerekiyorsa `apply_record_to_socket()`
  özel davranışı.
- Şema kırıcı kanal eklediysen `EXPORT_SCHEMA_VERSION`'ı artır ve importer'ın
  `SUPPORTED_SCHEMA_VERSIONS` listesine ekle. Liste eski sürümleri de tutar,
  böylece başka bir daldan gelen paket reddedilmez.
- `invert` bayrağını exporter koyar, importer uygular. Exporter değeri kendisi
  ters çevirdiyse `invert`'i `False`'a çeker — çift inversiyon hatasına dikkat
  (`_maya_basic_channels`, `_surface_shader_channels`).
- Roughness için Redshift **Reflection Roughness** kullanılır. Diffuse
  Roughness (Oren–Nayar) Principled roughness'ına **bağlanmaz**.

---

## 5. Attribute Alias Deseni — Bozma

Maya/Redshift sürümleri arasında attribute isimleri değişir. Kod bunu tek bir
desenle çözer: her semantik kanal için **aday isim tuple'ı** tutulur, ilk var
olan kullanılır.

- Işıklar: `LIGHT_ATTR_ALIASES`
- Shader: `REDSHIFT_STANDARD_CHANNELS`, `REDSHIFT_LEGACY_CHANNELS`

Yeni bir sürüm desteği eklerken **kodu değil tuple'ı** genişlet. Aday isim
tuple'larının sırası önceliktir; en yaygın/en doğru isim başa yazılır.

Sıra gerçekten önemli: `aiAreaLight` hem `exposure` hem `aiExposure` taşır ve
Arnold'un kullandığı `exposure`'dır, ama `aiSkyDomeLight` yalnızca `aiExposure`
taşır. Tuple `("exposure", "exposure0", "aiExposure")` ikisini de doğru
çözer — sırayı değiştirirsen dome ışıkları yanlış değeri okur.

Renderer başına ayrı kanal tablosu tutulur, çünkü semantik farkları var:
Maya'nın `transparency`'si ters çevrilir, Arnold'un `opacity`'si çevrilmez.
Aynı tabloya iki renderer'ın ismini koymak bu farkı gizler.

Aynı savunmacı yaklaşım node keşfinde de var: `_scene_light_shapes()` bilinen
tip listesi + `nodeType` içinde "light" geçen shape taraması ile çalışır.
Bilinmeyen Redshift ışık tiplerini yakalamak için bu heuristik tarama
kaldırılmamalı.

---

## 6. Blender Tarafı Kritik Kurallar

### Thread güvenliği (ihlali Blender'ı çökertir)

- `bpy` **thread-safe değildir.** Listener thread'i (`_listener_loop`) yalnızca
  socket okur ve `_messages` queue'suna koyar.
- Tüm `bpy` erişimi `_process_messages()` içinde, `bpy.app.timers` üzerinden
  ana thread'de yapılır.
- Listener thread'ine asla `bpy` çağrısı ekleme.

### Sürüm uyumu

Blender 3.6 ile 4.x arasında API farkları var. Kod bunları şöyle karşılar,
aynı deseni sürdür:

- Socket/property varlığı: `hasattr(data, "spread")`, `hasattr(data, "normalize")`
- İsim değişikliği: `_principled_input()` içinde `("Emission Color", "Emission")`
  gibi fallback tuple'ları
- Riskli setter'lar: `try/except` ile sarılı (`_enable_alpha`)
- Operator imza değişikliği: `_import_fbx()` içinde `TypeError` yakalanıp
  argüman düşürülerek tekrar denenir

Yeni bir Blender API'si kullanırken **doğrudan çağırma** — bu üç desenden
uygun olanıyla koru.

### Sürüm numarası

Importer'da davranış değiştiren her düzenlemede **ikisini birlikte** artır:

- `bl_info["version"]` tuple'ı
- `BUILD_VERSION` string'i

Bu iki değer N-panel'de gösterilir ve kullanıcının doğru dosyayı yüklediğini
doğrulamasının tek yoludur. Uyumsuz bırakma.

### Namespace kuralı

- Üretilen material adları: `ML_` öneki
- Üretilen node adları: `ML_` öneki
- Custom property'ler: `ml_` öneki (`ml_generated`, `ml_source_*`)
- Blender Scene property'leri: `ml_` öneki
- Collection'lar: `ROOT_COLLECTION_NAME`, `LIGHT_COLLECTION_NAME` sabitleri

`ml_generated` bayrağı, aracın ürettiği datablock'ları FBX'in ürettiği geçici
olanlardan ayırmak için kullanılır. Yeni datablock üretiyorsan bu bayrağı koy.

Maya grup hiyerarşisi iç içe collection olarak kurulur (`place_in_group`).
Yalnız **shape'i olmayan** transform'lar klasör sayılır; geometri taşıyan bir
transform objedir. Aynı gruba düşen meshler tek collection paylaşsın diye
`group_cache` import boyunca taşınır — onu her mesh için sıfırlama.

---

## 6b. Unreal Tarafı Kritik Kurallar

### Thread güvenliği

`unreal` de `bpy` gibi thread-safe değildir. `livelink.py`'ın listener
thread'i yalnız socket okur ve queue'ya koyar; her `unreal` çağrısı
`process_messages()` içinde, `register_slate_post_tick_callback` üzerinden
**game thread'de** yapılır. Blender'da hook `bpy.app.timers`, kural aynı.

### Eksen dönüşümü Blender'ınkiyle aynı DEĞİL

Maya→Unreal `(x, y, z) → (x, z, y)`: düz Y/Z takası, **işaret çevirmesi yok**.
Blender'ınki `(x, -z, y)`. El değişimi takasın kendisi tarafından yutuluyor.
İkisi de ölçüldü (`tests/docs/unreal_calibration.md`); birini diğerine
benzetmeye çalışma.

Mesh transform'ları **Interchange** taşıyor ve doğru taşıyor — `meshes.py`
içinde bilinçli olarak hiç transform matematiği yok. Doğru olanın üstüne bir
kez daha uygulamak, ışık enerjisinde bir kez yapılmış hatanın aynısıdır.

### Işık/kamera ile obje dönüşümü AYRI

`transforms.py` iki dönüşüm taşıyor ve karıştırılmamalı:

- **Işık/kamera:** Maya local −Z'ye bakar, Unreal +X'e. Bakış yönü Unreal'in
  forward'ına taşınır (`unreal_rotation`).
- **Obje** (locator, volume, standin, curve, instancer): bakış yönü yok, kendi
  eksenleri adını korur → `Unreal +X = S·maya_x`, `+Y = S·maya_z`,
  `+Z = S·maya_y` (`unreal_object_rotation`). Her ekseni aynı adlı Unreal
  eksenine eşlemek **sol el çerçevesi** üretir, yani sessizce ayna.

Objede scale de taşınır (boyutunu başka hiçbir şey taşımıyor) ve Y/Z bileşenleri
eksenlerle birlikte takas edilir.

### İki ayrı ölçek

`unreal_scale` santimetre (konumlar), `metre_scale` metre (enerji). Enerji
çapası metreye karşı ölçüldü; ikisini karıştırmak 100× veya 10⁴× hata.

### Işık enerjisi Unreal'de mutlak olarak doğrulandı

`light_absolute_*` rig'i Unreal'i **analitik fiziğe** karşı ölçüyor (Arnold'a
değil — onun pikselleri keyfi ölçekte, o yüzden mutlak olamaz):

```text
candelas = lümen/(4π) → lux = candelas·cosθ/d² → nit = lux·albedo/π
```

Nokta kaynak yaklaşımının geçerli olduğu varyantlarda oran **0.9529, yayılım
%0.034**. Ters kare, doğrusallık ve `2^exposure` ayrı ayrı doğrulandı. Kalan
%4.7 modelin nokta-kaynak varsayımının; oran boyut/mesafe ile hareket ediyor.

Sonuç: `SCS_SCENE_COLOR_HDR` **nit** cinsinden (1.0 ≈ 1 cd/m²) ve zincir
mutlak doğru. `ml_light_power_scale`'i 1.0'da bırak.

### Motor kendi biriminin otoritesi

Işık yoğunluğu lümen olarak yazılıyor; kendi çevrim sabitini yazma, motor
çevirsin. `apply_intensity` birimi geri okuyup gerekirse motorun
`get_units_conversion_factor`'ı ile çeviriyor — bu bir **koruma**, gözlenmiş
bir hatanın çözümü değil (5.8.1'de point/rect/spot üçü de `LUMENS`'i
koruyor).

### Property yazımı setter ile — fırlatır, yutulursa sessiz kalır

Light component'inin `intensity` ve `intensity_units`'ı Python'a
**read-only**; düz atama `is read-only and cannot be set` fırlatıyor.
`set_<name>()` önce, property yedek, ikisi de olmazsa **uyarı**.

Çıplak `try/except` ile atama yapıp geçmek bu oturumda bütün ışıkları
**8.0 candela**'da bıraktı (spawn edilmiş component'in varsayılanı; CDO
5000 UNITLESS der, o başka bir sayı) ve test "pozitif mi" diye sorduğu için
**geçti**.

### Coat ve sheen için Unreal girdisi yok

`unreal.MaterialProperty` probe edildi: coat ve sheen **yok**. Bu kanallar
`UNREAL_METADATA_CHANNELS` içinde ve uyarı yazılıyor. Base color'a katmak
ölçülmemiş bir şeyi ölçülmüş gibi göstermek olurdu.

### Blend mode Material'e ait, instance'a değil

Bu yüzden yüzey sınıfı başına bir master material var (Opaque, Masked,
Translucent, Unlit). Tek master ile cam + cutout + unlit içeren bir sahne
karşılanamaz — instance blend mode'u override edemez.

## 7. Yıkıcı Davranış — Bilinçli Tasarım

`import_scene_package()` her pakette **sahnenin tamamını siler**. Bu bir hata
değil, aracın tasarımıdır (README "Blender import davranışı" bölümü).

- Silmeden önce dosya kayıtlıysa `bpy.ops.wm.save_mainfile()` çağrılır.
- `_clear_scene_and_purge()` üç aşamalıdır (operator → datablock remove →
  `batch_remove`) ve tam temizlenmezse **hata fırlatır**. Bu kontrolü sessize
  alma; yarım temizlenmiş sahneye import etmek daha kötüdür.
- Kullanıcı verisini koruyacak bir "merge" modu istenirse bu ayrı bir özelliktir,
  mevcut akışı sessizce değiştirerek yapılmaz.

---

## 8. Koordinat ve Birim Dönüşümü

- Maya Y-up → Blender Z-up: `(x, y, z)` → `(x, -z, y)`
  (`_maya_vector_to_blender`). Bu dönüşümü elle tekrar yazma, bu fonksiyonu
  kullan.
- World matrix'in üç ekseni tek tek dönüştürülür (`_maya_light_matrix`);
  sıfır uzunluklu eksenler için fallback vektör kullanılır.
- Ölçek: `meters_per_maya_unit` (Maya linear unit'ten) × kullanıcının FBX Scale
  değeri = `position_scale`.
- Işık boyutu transform scale'den gelir; obje scale'i Blender'da `1,1,1`'e
  sabitlenir, boyut `data.size`/`data.size_y` üzerinden verilir.

### Işık enerjisi: her şey akıya çevrilir

Blender'ın light Power'ı **toplam ışıl akıdır** (render ile ölçüldü, 4.1 ve
5.2). `light_energy()` bu yüzden her dalda akı döndürür ve `create_light_object`
Blender'ın `normalize`'ını **her zaman `True`** bırakır.

Bu kuralı bozma: alan çarpımını hem `light_energy()` içinde yapıp hem de
Blender'a normalize=False vermek alanı **iki kez** uygular. Kaynak ışığın
normalize bayrağı `light_energy()` içinde tüketilir, Blender'a geçirilmez;
bilgi `ml_source_normalized` custom property'sinde saklanır.

Fiziksel birim bildiren dallar (lumen/candela/watt/radiance) tam çevrimdir,
dokunma.

### Yoğunluktan watt'a dönüşüm ölçüldü

Dönüşüm `WATTS_PER_INTENSITY × position_scale²`'dir. Sahne biriminin karesi
**zorunlu**: Arnold birimden bağımsızdır, aydınlatma ham sayılara göre `1/d²`
düşer. Bu terimi düşürmek santimetre sahnelerde 10⁴ kat hata verir.

`WATTS_PER_INTENSITY` tahmin değil, ölçüm sonucudur. Arnold ve native Maya
için değer **π**'dir; Arnold'ın normalize `intensity`'si normal yöndeki ışıl
şiddettir ve Lambert yayıcının toplam akısı onun π katıdır.

Bu sayıyı "kalibrasyon" diye değiştirme. Değiştirmen isteniyorsa önce
`tests/docs/light_calibration.md` içindeki ölçümü tekrarla; rig'in doğruluğunu
Blender'ın `piksel = P/(π²d²)` özdeşliğini tutturmasıyla sınayabilirsin.

Redshift girdisi (`10.0`) hâlâ devralınmış bir tahmindir çünkü plugin bu
makinede kurulu değil. Bunu düzeltmek isteyen olursa yöntem belgede yazılı.

Kullanıcı çarpanı `ml_light_power_scale`'dir, varsayılanı `1.0` ve dönüşümün
üstünde çarpan olarak durur. Dönüşüm ölçülmüş olduğu için varsayılanı
değiştirme.

Orijinal Maya değerleri `ml_source_*` custom property'lerinde saklanır —
tartışma çıktığında referans budur, silme.

### Light node ağacı birim çarpandır

Bir Blender light'ının node ağacı, `data.energy`'nin **üzerine** uygulanır.
IES veya decay için Emission Strength'e bağlanan node zincirinde Strength
girişleri `NODE_TREE_UNIT_STRENGTH` (1.0) kalmalıdır. Oraya `data.energy`
yazmak enerjiyi iki kez uygular ve ışık karesel olarak parlar.

### Blender sürüm varsayılanlarına güvenme

Principled Emission Strength varsayılanı 3.x'te `1.0`, 4.x'te `0.0`. Bir soketin
varsayılanına bel bağlayan her yol, sürümler arasında sessizce farklı görüntü
üretir. Değeri açıkça set et (`DEFAULT_EMISSION_STRENGTH` bunun örneğidir).

---

## 9. İş Akışı

### Değişiklik yapmadan önce

1. Değişikliğin hangi tarafı etkilediğini belirle: sadece Maya, sadece Blender,
   veya **ikisi birden** (protokol/kanal sözleşmesi).
2. İki tarafı etkiliyorsa iki package'ı da aynı commit'te güncelle. Tek taraflı
   protokol değişikliği bırakma.
3. **Attribute ismi tahmin etme.** Maya ve Blender bu makinede kurulu ve
   headless çalıştırılabiliyor (aşağıya bak). Yeni bir renderer, shader veya
   ışık tipi eklerken önce bir probe scripti yaz, gerçek isimleri oku, sonra
   tabloyu doldur. Bu projede tahmin edilen isimlerin çoğu yanlış çıktı:
   `aiLambert.KdColor`, `aiOpenPBRSurface.baseMetalness`,
   `aiAreaLight.aiTranslator`, `aiSkyDomeLight.aiExposure`.

### Doğrulama

Maya ve Blender bu makinede kurulu ve headless çalıştırılabiliyor, yani
gerçekten test edebilirsin. Ayrıntılar `tests/README.md`.

```bash
# 1. Sozdizimi
python -m py_compile mlender_exporter/*.py mlender_importer/*.py

# 2. Sozlesme kontrolleri (host gerekmez, saniyeler)
python tests/check_contracts.py

# 3. Gercek Maya + Arnold (~2 dk)
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/host/maya_export_test.py

# 4. Gercek Blender, 3'un yazdigi paketi okur (~30 sn)
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/host/blender_import_test.py

# 4b. Gercek Unreal, ayni paketi okur (~2 dk, ilk acilis daha uzun)
"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" ^
    <bir .uproject> -run=pythonscript ^
    -script="tests/host/unreal_import_test.py" -unattended -nosplash -nullrhi

# 5. Dagitilabilir ciktilar (yalniz surum cikarirken)
python packaging/build_release.py
python packaging/verify_release.py
```

Unreal testi bir `.uproject` ister; yoksa `PythonScriptPlugin` etkin minimal
bir tanesi elle yazılabilir. **Python çıktısı stdout'a değil
`<proje>/Saved/Logs/<proje>.log` içine düşer** — sonucu oradan `MLPASS` /
`MLFAIL` ile ara. Bu, headless Unreal'da ilk saati yiyen ayrıntıdır.

`verify_release.py` formalite değildir: **üç** artefaktı da gerçek host'a
kurar — modülü repoya erişilemeyen bir çalışma dizininden mayapy'ye, add-on'u
tek kullanımlık bir Blender home'una, plugin'i burada yaratılıp silinen bir
Unreal projesinin `Plugins/`'ine. Üçü de bir kez yanlıştı ve yalnız kurunca
ortaya çıktı. Bir kez de **testin kendisi** yalan söyledi: mayapy çalışma
dizinini `sys.path`'e koyduğu için repo kopyası import ediliyor, modül hiç
denenmiyor ve "ok" yazıyordu — Unreal ayağı da bu yüzden import'un **kurulu
kopyadan** geldiğini ayrıca kontrol ediyor.

Unreal ayağının iki ayrıntısı: plugin `EnabledByDefault: false` taşıyor, yani
`Plugins/`'e koymak yetmez, `.uproject`'te etkinleştirilmesi gerekir (INSTALL.md
zaten böyle söylüyor; kontrolün ilk sürümü bu adımı atlayıp paketi bozuk
sanmıştı — bozuk olan kontroldü). Ve `Tools > mLender` menüsü commandlet'te
**doğrulanamaz**: headless editörde menü asılacak yer yok, plugin bunu zaten
açıkça bildiriyor. Kontrol menüyü değil, `register()`'ın cevap verdiğini ve
açılış satırının log'a düştüğünü sınıyor.

Kurulu tek Blender sürümü **5.2** (2026-08-18'de kontrol edildi; 4.1/4.3/4.5
bir zamanlar kuruluydu, artık değil). Kullanıcının hedefi de 5.2.
Sürüm uyumu iddia eden bir değişiklik yaptıysan 4. adımı birden fazla sürümde
çalıştır — bu araç 3.6'dan 5.2'ye kadar iddia ediyor ve aradaki farklar gerçek
(`shadow_method` 4.5'te kalktı, `use_temperature` 4.2'de geldi).

Yeni davranış eklediğinde **ilgili teste assertion ekle**. Testler bu projede
gerçek hata yakaladı: `aiFlat`'ın `outColor` yerine `color` okuması gerektiği
ancak gerçek Maya'da çalıştırılınca ortaya çıktı.

Testler render etmez. Kalibrasyon sabitlerinin *uygulandığını* doğrularlar,
*doğru olduklarını* değil. Bir sabiti değiştirdiysen bunu kullanıcıya söyle ve
göz karşılaştırması iste.

Kullanıcının elle doğrulaması gereken adımlar:

1. Maya'da `za.show_ui()` → Export Location seç → `Send To Blender`
2. Blender N-panel'de `Build` numarasının beklenen sürüm olduğunu kontrol et
3. Import sonrası panel status satırını oku (mesh/material/subdiv/ışık sayıları)
4. Blender System Console'da `mLender warning:` satırlarını kontrol et

### Hata yönetimi deseni

- **Exporter**: paket üretimi atomiktir. Hata olursa FBX, JSON ve klasör
  temizlenir (`export_scene` içindeki `try/except`). Yeni dosya üretiyorsan
  bu temizliğe ekle.
- **Importer**: tek bir material/ışık/texture hatası import'u durdurmaz;
  `warnings` listesine yazılır ve akış devam eder. Bu deseni sürdür — kısmi
  sonuç, hiç sonuç yoktan iyidir. Yalnızca akışın devam etmesinin anlamsız
  olduğu durumlarda (sahne temizlenemedi, FBX bulunamadı, mesh üretilmedi)
  exception fırlat.

---

## 10. Kod Stili

- Paket dışına açık API `__init__.py` içindeki `__all__` ile tanımlıdır:
  exporter'da `show_ui`, `show`, `export_scene`, `reload_package`;
  importer'da `import_scene_package`, `register`, `unregister` ve listener
  fonksiyonları.
- Modüller arası paylaşılan fonksiyonlar `_` **almaz** — başka modülden
  `_foo` import etmek anlamsızdır. `_` öneki yalnızca aynı modül içinde
  kalan yardımcılar içindir (`_build_principled`, `_insert_value_invert`).
- Modül içi import'lar hep relative: `from .mayautils import attr_exists`.
  Absolute import (`from mlender_exporter.mayautils import ...`) yazma;
  Blender add-on klasör adı değiştiğinde kırılır.
- Modül seviyesi sabitler UPPER_SNAKE ve `constants.py` içinde toplanır.
  Yeni bir sihirli sayı veya string'i doğrudan mantığa gömme.
- Yorumlar **İngilizce** ve seyrek — sadece "neden" açıklar, "ne" değil.
  Mevcut yorumlar bunun örneği (ör. Redshift Image unit kalibrasyon notu).
  Bu yoğunluğu koru, satır satır yorum ekleme.
- Maya/Blender API çağrıları savunmacı sarılır; `_attr_exists`, `_scalar`,
  `_color4`, `_number` gibi mevcut yardımcıları kullan, yenisini yazma.
- Fonksiyonlar tek sorumluluk taşır ve kısadır. 100 satırı geçen bir fonksiyon
  yazıyorsan böl.

---

## 11. Yasak Listesi

- ❌ Listener thread'inden `bpy` **veya `unreal`** çağırma
- ❌ Exporter'a f-string / type hint / Python 3'e özgü sözdizimi ekleme
- ❌ Üç package arasında ortak modül import etme
- ❌ Protokol sabitlerini tek tarafta değiştirme (artık **üç** taraf var)
- ❌ Kanal anahtarını tek tarafta yeniden adlandırma
- ❌ `BUILD_VERSION` ile `bl_info["version"]`'ı **veya `.uplugin`'in
  `VersionName`'ini** ayrı bırakma
- ❌ Maya→Unreal dönüşümünü Blender'ınki sanma; Unreal `(x, z, y)`, Blender
  `(x, -z, y)`, ikisi de ölçüldü
- ❌ Unreal'de mesh transform'una dokunma; Interchange zaten doğru yapıyor,
  ikinci kez uygulamak çift-uygulamadır
- ❌ Unreal'de konum ölçeğiyle enerji ölçeğini karıştırma; biri santimetre
  biri metre, karıştırmak 10⁴ hata
- ❌ Unreal light component property'sini düz atamayla yazma; `intensity` ve
  `intensity_units` read-only, atama **fırlatır**. Setter kullan ve
  başarısızlığı yutma — yutulan bir yazma ışığı 8 candela'da bırakır
- ❌ Bir Unreal varsayılanını CDO'dan okuyup "sahnedeki varsayılan" sanma;
  spawn edilmiş ışık 8 CANDELAS, CDO 5000 UNITLESS diyor
- ❌ Unreal'de render'ı commandlet'te ölçmeye çalışma; render komutları
  işletilmiyor ve temizlenmiş bir target `(1,0,0)` okuyor. Ölçmeden önce
  bilinen renkli **kontrol** koy
- ❌ Blender'ın piksel dizisiyle Unreal'in render target'ını aynı yönlü sanma;
  biri alttan yukarı, öteki yukarıdan aşağı — aynı formül kareyi aynalar
- ❌ `SceneCapture2D`'yi kontrol edilebilir bir ölçüm aracı sanma; GI'ı
  kapatmanın üç yolu (cvar, `show_flag_settings`, proje ini) sonucu **bit-bit
  değiştirmiyor** ve 8 kare %0.000 aynı. Ayarı değiştiremediğin bir render'da
  hiçbir hipotezi eleyemezsin
- ❌ Bir asimetriyi ölçmeden "gürültü" diye açıklama; 8 kare alıp yayılıma
  bakmak bu hipotezi bir turda çürüttü
- ❌ Rapor yazımının export'u veya import'u düşürmesine izin verme; paket
  klasörü salt okunur olabilir, rapor yazılamıyorsa yazılmaz, iş devam eder
- ❌ Exporter'ın `BUILD_VERSION`'ını `__init__.py`'de arama; `constants.py`'a
  taşındı (package.py kökü import edemez, döngü olurdu) ve
  `build_release.py` oradan okuyor
- ❌ Preset'e `export_scene`'in almadığı bir anahtar koyma; keyword argüman
  olarak gidip export'u düşürür. Bilinmeyen anahtar **düşürülür**
- ❌ Komut satırında adı geçmeyen ayarı varsayılana döndürme; `None` "söylenmedi"
  demektir ve preset'in değeri kalır
- ❌ Bir compound plug'ın anahtarlı olup olmadığını yalnız kendisine sorma;
  Maya renkleri **çocuklarından** anahtarlıyor (`baseColorR`), compound
  "bağlantı yok" der ve keyli base colour sessizce donar
- ❌ animCurve'ü shading network sanma; bake yolu anahtarlanmış bir skaleri
  tek kare halinde texture'a basıyordu — upstream yürüyüşü animCurve'de durur
- ❌ Bake edilmiş örnekleri Bezier bırakma; örnekler zaten değerlendirilmiş
  eğri, LINEAR olmalı (iki kez ease etmesin)
- ❌ String attribute'u `plug_value` ile okuma; o sayısal ve string'i **düşürüyor**
  (`None` dönüyor). `raw_attr_value` kullan
- ❌ Renk seti için "current olan" varsayımı yapma; shader başka bir seti okuyor
  olabilir ve yanlışı okumak makul görünür
- ❌ Exporter'ın yazdığı bir bayrağı okuyan var mı diye bakmadan bırakma; `unsupported_network`
  başından beri yazılıyordu ve **kimse okumuyordu** — kanal sessizce siyaha çöküyordu
- ❌ Uyarıyı pakete yazıp işin bittiğini sanma; `export_warnings`'i **hiçbir
  alıcı okumuyordu**, yani kapsam/tessellation/donmuş kanal uyarılarının
  hiçbiri Blender veya Unreal'de görünmüyordu. Uyarı okunmuyorsa yok demektir
- ❌ Animasyon kapalıyken sessiz kalma; `export_animation` varsayılanı **False**
  ve tek kare export uçan kamerayı da blink'i de düşürüyor. Ne düştüğünü
  kind kind say ve hangi kutunun tıklanacağını söyle
- ❌ Blender host testinde çıkış kodunu geçti sanma; traceback verip **exit 0**
  döndüğü ölçüldü. Özet satırını ara
- ❌ AOV'u substring ile eşleştirme; `"z" in name` OpenPBR'ın **fuzz**'ını
  derinlik pass'i yapıyordu. Tam eşleşme kullan
- ❌ Blender'da eşleşmeyen AOV'u sessizce custom slot yapma; shader yazmadıkça
  **siyah render eder**, yani "geldi ama boş" olur — uyarı yaz
- ❌ Arnold AOV `type`'ını tahmin etme; ölçüldü: 4=FLOAT, 5=RGB, 6=RGBA,
  7=VECTOR (kodda "5=RGBA usually" yazıyordu, yanlıştı)
- ❌ Unreal'de mesh actor'ünü yalnız `StaticMeshActor` sanma; Interchange skinli
  meshi kendiliğinden `SkeletalMeshActor` getiriyor ve filtreleyen kod onları
  level'da placeholder materyalle sahipsiz bırakıyor
- ❌ `override_pipelines`'a bir şey verip çalıştığını sanma; soft path **kabul
  ediliyor**, `import_scene` True dönüyor ve **sıfır asset** üretiyor. Sonucu
  say
- ❌ Unreal'de obje rotasyonunu ışık/kamera dönüşümüyle kurma; ikisi ayrı,
  obje için her ekseni aynı adlı eksene eşlemek sol el çerçevesi (ayna) verir
- ❌ Unreal'de bir level actor'üne component eklemeye çalışma; bu build'de
  `add_component_by_class` **yok**. Ya bileşeni zaten taşıyan bir actor sınıfı
  spawn et (`GeometryCacheActor`, `HeterogeneousVolume`), ya da
  `SubobjectDataSubsystem` ile Blueprint üret
- ❌ Yeni yapılmış bir Blueprint'ten actor spawn edip çalıştığını sanma;
  derlenmeden `generated_class` kullanılamaz ve spawn **None** döner, sebebini
  söylemeden. Derle, sonra `generated_class()` ile spawn et
- ❌ Parçacık `positions`'ını üçlü liste sanma; exporter **düz** float listesi
  yazıyor ve doğrudan iterasyon `'float' object is not iterable` verir
- ❌ Referans verilen dosya diskte yokken testin yüklemeyi şart koşması;
  fixture'ın `smoke.vdb`'si yok ve çapa doğru davranıştır — koşulsuz assertion
  çalışan importer'ı düşürdü
- ❌ Mutlak parlaklığı Arnold'a karşı ölçmeye çalışma; Arnold'ın pikselleri
  keyfi ölçekte, referans **analitik fizik** olmalı
- ❌ Tick callback'i re-entrancy guard'sız yazma; `import_scene_package` Slate
  tick'lerini pompalıyor, callback kendini çağırıyor ve `RecursionError` ile
  editörü götürüyor (21 import derinliği ölçüldü)
- ❌ Material Instance parametresini Python'dan set edip render'a ulaştığını
  sanma; değer saklanıyor, geri okuma doğruyu diyor, **render değişmiyor**
- ❌ Ölçüm yamasını küçük tutma; 10 px yama blotchy indirekt ışıkta simetrik
  sahneyi %13 asimetrik gösterdi, 40 px yama + dik kamera %0.29'a indirdi
- ❌ Mesh'i olmayan bir mesh actor'ünde materyal atamasını sessizce atlama;
  daha önce gönderi barındıran content root'a yeniden import bunu üretiyor ve
  "2 mesh, 0 materyal, 0 uyarı" diye görünüyordu
- ❌ Unreal'e n-gon taşıyan bir Alembic gönderme; okuyucu dört köşeden
  fazlasını reddediyor ("expecting triangles (3) or quads (4)") ve **bütün
  dosyayı** düşürüyor. Gerçek bir çekimde tek bir yüz 574 objeyi götürdü ve
  import yalnız "cache okunamadı" dedi. Yalnız gerekeni üçgenleştir, history
  olarak yap ve geri al
- ❌ N-gon'u üçgen/yüz oranıyla arama; bir üçgen + bir beşgen, dörtgen
  meshiyle aynı oranı veriyor. Yüzleri gez
- ❌ Alembic'i face set yazmadan gönderip materyalin geleceğini sanma;
  ölçüldü, `-writeFaceSets` yoksa Unreal'de **her slot** `NoFaceSetName`
  ve hiçbir slot hangi shader'a ait olduğunu söylemiyor. Varken slot adı
  shading group; tek materyalli mesh yine isimsiz tek slot verir, çok
  materyalli olan SG başına bir tane
- ❌ GeometryCache'i importer varsayılanıyla alma; `flatten_tracks` varsayılan
  **True** ve altı objeyi tek track + **tek materyal slotu**na indiriyor.
  Obje başına track istiyorsan açıkça `False` yaz
- ❌ Cache slotlarını konumdan bağımsız sanma; isimsiz slotlar yalnız track
  sırasıyla çözülür. Ölçüldü: track sırası alfabetik (`alphaShape_0`,
  `mikeShape_0`…) ve slotlar o sırayı izliyor; ortadaki çok materyalli obje
  ardışık iki isimli slot üretiyor
- ❌ "Animasyonlu mu" sorusunu bağlantı yürüyerek cevaplama; Bullet, expression
  ve constraint hiçbir animCurve bırakmaz. Zaman çizgisini adımlayıp **dünya
  matrisini** oku — ve dünya, çünkü hareketsiz bir prop hareketli bir grubun
  içinde seyahat eder
- ❌ Alembic root'unu hareketli hiyerarşinin içine koyma; AbcExport root'un
  kendi matrisini yazar, üstündekini yazmaz. İçerideki propu root yapmak onu
  yanlış yerde ve hareketsiz teslim eder
- ❌ Unreal'de coat/sheen'i bir girdiye zorlama; `MaterialProperty`'de yok
- ❌ Tek master material ile bütün yüzey sınıflarını karşılamaya çalışma;
  blend mode instance'a ait değil
- ❌ Blender API'sini `hasattr`/`try` koruması olmadan doğrudan çağırma
- ❌ Işık kalibrasyon sabitlerini gerekçesiz değiştirme
- ❌ Sahne temizleme doğrulamasını sessize alma
- ❌ Şema doğrulamasını sahne silindikten sonraya taşıma
- ❌ Çalıştırıp doğrulamadan "test edildi / çalışıyor" deme
- ❌ Alias tuple'larını kod mantığıyla değiştirme
- ❌ Yeni modülü reload listelerine eklemeyi unutma
- ❌ Absolute import kullanma (relative import zorunlu)
- ❌ Package'lar arasında döngüsel bağımlılık oluşturma
- ❌ DCC attribute ismini probe etmeden tabloya yazma
- ❌ Arnold `opacity`'sini Maya `transparency` gibi ters çevirme
- ❌ Bir kaydın `value` taşımasına bakıp "düz değer" sanma; `first_channel_record`
  bağlantı olsa da `value` doldurur. Texture'ı `texture.path` ile ayır, yoksa
  texture'lı transparency ters çevrilmeden geçer
- ❌ Arnold shader'ında `outColor` okuma (hesaplanmış çıktı, girdi değil)
- ❌ Bir kanalı yalnız Glass yoluna bağlayıp bırakma; yaygın olan Principled
  yoludur, `GLASS_ONLY_CHANNELS` dışındaki her kanal oraya da ulaşmalı
- ❌ Testleri yalnız "normal" aralıkta yazma; sınırın ötesinde de bir değer
  olsun, yoksa aralığı daraltan hata görünmez
- ❌ Emission ve ışık rengini 0–1'e kırpma; ikisi de meşru şekilde 1'i aşar,
  albedo ve tint'ler kırpılır
- ❌ Materyal chart'ına tek hücre ekleme; **çift** ekle, yoksa iki tarafta da
  sıfır olan bir kanal "eşleşti" görünür
- ❌ Ölçüm rig'inin geometrisine dokunup kontrol satırlarına bakmadan sonuç
  okuma; aynı materyali iki konuma koyan kontroller rig'in üç ayrı kusurunu
  yakaladı ve üçü de tabloyu makul göstermeye devam ediyordu
- ❌ Yeni davranışı teste assertion eklemeden bırakma
- ❌ Kaynak sahnenin istemediği bir şeyi bütün meshlere uygulama
- ❌ Işık enerjisinden `position_scale²` terimini düşürme
- ❌ Displacement'a birim ölçeği ekleme; FBX birim dönüşümünü obje scale'ine
  koyar, vertex'ler Maya biriminde kalır, object space displacement zaten doğru
- ❌ Displacement'ı shader'da arama; Maya onu shadingEngine'de tutar
- ❌ `nurbsToPoly`/`subdToPoly` çağırıp seçimi geri koymamak; ikisi de
  çıktısını seçili bırakır, ve seçili-export o yüzden kullanıcının
  seçmediği bir yüzeyi taşıdı. Seçimi sakla, geri koy; seçili olan bir
  yüzeyi stand-in'iyle temsil et, yoksa seçtiği NURBS hiç gitmez
- ❌ Curve-on-surface'ı sahne eğrisi sanma; her trim bölgesi başına bir
  tane bırakır ve trimli bir model alıcıya gömülü gelir. DAG yolundaki
  `->` tek işarettir — node tipi düz `nurbsCurve`, parent'ı normal bir
  transform. Hem export hem kapsam taraması aynı kuralı uygulamalı
- ❌ Nanite mesh'inde `get_num_triangles()` okuyup kaynak geometri sanma;
  o **fallback** mesh'tir ve bütçeye göre kurulur. Ölçüldü: 896 üçgenlik
  panel de 3968 üçgenlik küre de 256 okundu, yani sayı mesh'i değil
  bütçeyi anlatıyor. `get_num_nanite_triangles()` kaynağı verir.
  Nanite'ı bu araç açmıyor — motorun import varsayılanı
- ❌ Sequencer'da display frame ile tick'i karıştırma; `add_key`,
  `set_range` ve oynatma konumu **tick**. Ölçüldü: 24 karede 100→900
  anahtarlanan sekans tick 12000'de 500, "kare 12"de 100.40 okuyor.
  Display rate yalnız cetveli adlandırır
- ❌ …ama `set_playback_start/end` bu ailenin **istisnası**: o **kare**
  alıyor. Ölçüldü: `set_playback_end(33000)` → `get_playback_end_seconds()`
  = 1375 s, `set_playback_end(33)` → 1.375 s. Tick verince 0-33'lük bir
  çekim 0-33000 açılıyor, bütün anahtarlar ilk otuz üç karede kalıyor ve
  cetveli sürükleyen "animasyon yok" görüyor — kullanıcı böyle bildirdi
- ❌ Mesh animasyonunun FBX'ten doğru geldiğini varsayma; Interchange onu
  kendi Level Sequence'ına, her anahtarı **kare numarasını tick olarak**
  yazarak koyuyor. Ölçüldü: 520 karelik hareket tick 1..519'da, yani ilk
  karenin ellide birinde bitiyor ve "hiç hareket yok" gibi görünüyor.
  Anahtarları geri okuyup doğru zaman tabanıyla yaz, ve sıkışmayı **tespit et**
  — varsayarsan düzelmiş bir motorda animasyonu bin katına gerersin
- ❌ Geri okunan kanalları **konuma göre** eşleme; okuma yalnız anahtarı olan
  kanalları döndürüyor, yani Z'de düşen bir obje tek kanal olarak gelir ve
  ilk sıraya (X'e) yazılır. Obje animasyonlu görünür, yanlara gider.
  İsimle eşle, ve fixture'da **dikey** hareket eden bir şey bulundur
- ❌ Simülasyonu anahtar arayarak tespit etmeye çalışma; Bullet solver
  transform'u animCurve'suz ve `.translate`'e bağlantısız sürüyor. Hareket
  FBX bake'ine düşüyor (ölçüldü), ama sim Maya'da bir kez oynatılmış olmalı
- ❌ Bir kanalı ağırlığına bakmadan "kayboldu" diye bildirme; `coat_ior`
  varsayılanı 1.5 olduğu için coat kapalıyken bile uyarı çıkıyordu ve 31
  materyalin 28'i sahte uyarıydı, üç gerçeği gömüyordu
- ❌ Unreal'de bir shading model girdisini `connect_material_property` ile
  arama; ClearCoat `CustomData0/1`'de ve enum'da yok. Yol
  `MakeMaterialAttributes`. Dönüş değerine güvenmeden önce uydurma bir pin
  adıyla kontrol et — sahte ad `False` dönüyorsa `True` bir şey anlatır
- ❌ Coat'u yalnız opak yüzeye verme; Unreal'de blend mode ile shading model
  bağımsızdır, masked bir yüzey de coat giyer
- ❌ Sequencer'ın materyal parametre API'sine diğer kanallarla aynı zamanı
  verme; ölçüldü, `add_scalar_parameter_key` verdiğin sayıyı
  ticks-per-frame'e **bölüyor** (1000 verince 1 saklıyor), transform kanalı
  bölmüyor. Tick'i geri çarp; yoksa bütün anahtarlar sekansın ilk birkaç
  tick'ine yığılır ve "animasyon yok" gibi görünür
- ❌ Fixture'da bir alanın **dolu** olduğunu varsayma; bu depoda iki kez
  çıktı (dört ışığın da örnekleri aynıydı, dome'un texture'ı hiç yoktu) ve
  ikisinde de üç alıcının yolu düşmesi imkânsız assertion'larla kaplıydı
- ❌ Component property'sini actor binding'ine anahtarlama; intensity ve
  LightColor `light_component`, focal/aperture `camera_component`
  binding'ine gider
- ❌ Görünürlük anahtarını motorun `hidden` bayrağıyla aynı sanma;
  Sequencer kanalında **True = görünür**, ters yazmak her blink'i çevirir
- ❌ Sekansı son karesinde okuyup "anahtar yok" deme; bitişe inmek
  sekansı bitirir ve animasyon öncesi değerleri geri koyar
- ❌ Animasyon örneğini kaydın üstüne yazarken eski türevi bırakma;
  `effective_intensity` statik kayıttan gelir ve dönüşüm onu tercih eder,
  yani yalnız `intensity`'yi yazmak ilk kareyi 25 kez anahtarlar. Beklenen
  değeri de aynı yoldan hesaplarsan test uyar ve hiçbir şey yakalamaz
- ❌ Mesh başına bütün kayıtları tarama veya materyali her mesh için yeniden
  okuma; ikisi de karesel, `benchmark_*.py` ile ölçüldü
- ❌ Mesh eşleştirmesini yalnız isme dayandırma; aynı kısa isim farklı
  gruplarda tekrar eder ve meshler yer değiştirir, grup izi tie-breaker'dır
- ❌ `blendColors`'ı Blender'ın Mix'iyle aynı sanma; faktör ters
- ❌ `remapValue`'yu doğrusal sanma; rampası asıl işidir
- ❌ Boş bir `lightlink` cevabını "hiçbir şeyi aydınlatmıyor" sanma;
  `defaultLightSet` dışındaki ışık böyle cevap verir ve kısıtlama yazmak onu
  Blender'da karartır
- ❌ Blender'da ACES view transform olduğunu varsayma; stok OCIO config'de
  yok, sadece özel config yüklüyse var
- ❌ Görünürlük bayraklarını varsayılanlarıyla birlikte yazma; yalnız
  varsayılandan farklı olanı yaz, yoksa sahnenin istemediği bir şeyi
  bütün meshlere uygularsın
- ❌ Her frame'in matrisini bağımsız Euler'e çözme; tam turda sıçrar,
  `make_compatible` ile bir öncekine uyumlu hale getir
- ❌ Bake edilmiş anahtarları Bezier bırakma; `LINEAR` olmalı
- ❌ `Action.fcurves` kullanma; 5.0'da kalktı, `action_fcurves()` kullan
- ❌ Zaman çizgisini örnekleyip kullanıcının frame'ini geri koymamak
- ❌ Blender soket varsayılanını kaynaktan gelen değer sanma (speküler 0.5)
- ❌ Baked map'i sRGB sanma; Maya lineer yazar
- ❌ Soket bileşen sayısını varsayma; Subsurface Radius 3, renk soketleri 4
- ❌ Düzeltme node'u soketlerine isimle erişme; isimler 4.1→5.2'de değişti
  (`Fac`→`Factor`, `Bright`→`Brightness`), indeksler değişmedi
- ❌ Gamma'yı iki tarafta aynı sanma; Maya `in^(1/g)`, Blender `in^g`
- ❌ Sahneyi export sırasında kalıcı olarak değiştirme (convertSolidTx'in file node'unu temizle)
- ❌ Bilinmeyen bir shader tipini native okuyucuya düşürme; `attr_exists` bir
  multi compound'un çocuğu için de "var" der ama `shader.color` adreslenebilir
  bir plug değildir. Sahnedeki tek `layeredShader` **bütün export'u** öldürdü
- ❌ Bir DCC çağrısının argümanı kabul etmesini uyguladığı sanma;
  `wm.usd_import(scale=...)` hata vermeden **hiçbir şey yapmıyor**, ve
  mesh'in kendi `dimensions`'ına bakmak da yetmez — parent'a uygulanmış
  olabilir, dünya uzayında ölç
- ❌ Ölçüm rig'inin bütün satırları aynı çıkınca "rig ölü" deme; sorulmayan
  sorunun cevabı olabilir. `layeredTexture`'da otuz dört satırın aynı çıkması
  ölü rig değil, **indeks 0'ın üst katman olduğu** anlamına geliyordu
- ❌ Ayırt etmeyen değerlerle ölçme; 0.8 üstünde 0.4'te `Difference`, `Darken`
  ve "hiçbir şey yapmadı" aynı sayıyı verir. Sonucun her adaydan farklı
  olduğu bir çift seç
- ❌ Yeni fixture'a ad verirken mevcutlara bakmama; bu depoda iki kez çakıştı
  (`uvSetCube`, `layerCube`) ve ikisinde de test yanlış materyali ölçtü
- ❌ Yeni bir dosya referansı taşıyan kayıt tipi ekleyip `collect.py`'a
  eklememek; "toplanmış" paket sessizce eksik olur (VDB ve standin böyle
  dışarıda kalmıştı)
- ❌ Testi repo kökünden çalıştırıp dağıtım artefaktını doğruladığını sanma;
  host çalışma dizinini `sys.path`'e koyar ve repo kopyası import edilir
- ❌ Unreal host testinin repo'yu sınadığını varsayma; projede kurulu bir
  mLender varsa `init_unreal.py` açılışta onu `sys.modules`'a koyar ve
  `sys.path.insert` hiçbir şey yapmaz. Dakikalar önce yazılan fonksiyon
  "modülde yok" dedi. Gölgeleyeni düşür, yeniden import et, ve hangi kopyayı
  sınadığını **assert et**
- ❌ Geliştirme kurulumunu **kopya** yapma; `<proje>/Plugins/mLender` repo'ya
  bir junction olmalı. Kopya olduğunda editör bugünün kodunu değil kopyalandığı
  günün kodunu yüklüyor ve bu iki kez gerçek hataya yol açtı. PowerShell:
  `New-Item -ItemType Junction -Path <proje>\Plugins\mLender -Target <repo>\mlender_unreal`
  (Git Bash üzerinden `cmd //c mklink` kaçış yüzünden çalışmıyor)
- ❌ Unreal kamerasına Maya'nın ham film back'ini yazma; Unreal'de film fit
  yok, çerçeveyi filmback oranından kurar. Fit'i render aspect'ine karşı
  çözüp pişir (`tests/docs/film_fit.md`). Maya'nın FOV sorgusu bu soruya
  cevap vermez — fit'i de çözünürlüğü de yok sayıyor
- ❌ Bir artefaktı **içeriğine bakarak** doğrulama; üç arşivi de içinde
  bulup "tamam" denen installer açılışta `no module named tkinter` ile öldü
  ve o haliyle release'e çıktı. PyInstaller **derleyen** yorumlayıcının
  runtime'ını donduruyor; Blender'ın Python'unda tkinter yok, mayapy ve
  Unreal'inkinde var. Çalıştığını sına — windowed bir exe'nin stdout'u
  yoktur, `--selftest` gibi dosyaya yazan bir yol aç
- ❌ Gizli bir mesh'te deformasyon ölçme; Blender gizli objeyi depsgraph'tan
  çıkarır, modifier hiç çalışmaz ve sağlam rig "0 vertex kıpırdadı" gösterir
- ❌ Animasyonu yalnız değer farkıyla assert etme; span kontrolü bir karelik
  kaymayı bir sürüm boyunca geçirdi. Anahtarların **hangi karede** durduğuna
  da assert et (FBX importer `anim_offset` varsayılanı 1.0'dır, 0 geçilmeli)

---

## 12. Git

Depo `mena-works/mLender` altında **public**'tir:

```text
origin     https://github.com/mena-works/mLender      (metin_dev)
upstream   https://github.com/hasancivili/MayaToBlender_Exporter
```

Çalışma dalı `metin_dev`. Ortam her commit'ten sonra `origin`'e **otomatik
push** ediyor (VS Code sync), yani commit etmek yayınlamaktır — public bir
depoda bunu akılda tut.

Commit mesajı formatı (İngilizce):

```text
feat: add IES profile support to light import
fix: prevent double inversion on lambert transparency
docs: document light energy calibration constants
```

Davranış değiştiren her değişiklikte **README.md'yi de güncelle** — README bu
projede kullanıcı dokümantasyonudur ve şu an kodla senkron.
