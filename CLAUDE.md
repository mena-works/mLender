# CLAUDE.md — Z-A Exporter (Lookdev)

> Bu dosya bu repo için geçerlidir ve üst klasördeki (`Downloads/CLAUDE.md`)
> Unreal Engine kurallarının **yerine geçer**. Buradaki hiçbir şey Unreal,
> Blueprint veya it-is-unreal MCP ile ilgili değildir.

---

## Proje Bilgisi

- **Ne yapar:** Maya sahnesini FBX + JSON paketi olarak Blender'a canlı gönderir;
  Blender tarafında materialleri Principled BSDF olarak, ışıkları native Blender
  light olarak yeniden kurar.
- **Hedef sürümler:** Maya 2022+ (Redshift), Blender 3.6+ (4.x dahil)
- **Dil:** Promptlar ve açıklamalar Türkçe; kod, değişken, fonksiyon ve
  yorumlar İngilizce. README Türkçe.
- **Test/build yok.** Doğrulama elle yapılır (aşağıda "Doğrulama").

---

## 1. Dosya Yapısı

İki bağımsız Python package. Bağımlılık yönü tek yönlüdür ve döngü yoktur;
bir modül yalnızca kendinden önce listelenenleri import edebilir.

```text
za_lookdev_exporter/     # Maya (import sırası = bağımlılık sırası)
  constants.py           # sabitler, attribute alias tabloları
  mayautils.py           # maya.cmds sarmalayıcıları
  textures.py            # upstream texture arama
  bake.py                # prosedürel ağları UV'ye bake etme
  shaders.py             # shader → kanal çıkarımı
  meshes.py              # mesh keşfi, material/face atamaları
  lights.py              # ışık keşfi ve kayıtları
  cameras.py             # kamera keşfi ve lens kayıtları
  fbx.py                 # MEL FBXExport
  livelink.py            # TCP istemci
  package.py             # paket klasörü, JSON, atomik temizlik
  ui.py                  # Maya penceresi
  __init__.py            # public API + reload_package()

za_lookdev_importer/     # Blender multi-file add-on
  constants.py
  utils.py               # değer/isim normalizasyonu
  images.py              # texture yükleme, UDIM
  materials.py           # node ağaçları
  lights.py              # Blender ışıkları, Dome World
  cameras.py             # Blender kameraları
  transforms.py          # Maya→Blender matris (ışık+kamera ortak)
  scene.py               # sahne temizleme, mesh eşleştirme, subdivision
  fbx.py                 # FBX import, paket dosyası çözümleme
  importer.py            # orkestrasyon + şema doğrulaması
  livelink.py            # socket listener + ana thread pompası
  ui.py                  # operator, property, panel
  __init__.py            # bl_info, register/unregister, reload bloğu

README.md                # Kullanıcı dokümantasyonu (Türkçe)
```

İki package birbirini **import etmez**. Aralarındaki tek bağ, aşağıdaki
protokol ve JSON sözleşmesidir. Ortak yardımcı modül ekleme — Maya ve Blender
farklı Python runtime'larında çalışır, paylaşılan dosya deploy'u kırar.

Bölünme öncesi tek dosyalık sürümler git geçmişinde `0dcbff4` commit'indedir.
Oradan "mevcut davranış" çıkarma; tek doğru kaynak package'lardır.

### Yeni modül eklerken

1. Modülü bağımlılık sırasında doğru yere koy.
2. Exporter'da `__init__.py` içindeki `SUBMODULES` tuple'ına ekle.
3. Importer'da `__init__.py` içindeki reload bloğunun **iki listesine** de ekle.

Bu listeler reload sırasını belirler. Eksik bırakılan modül, geliştirme
sırasında sessizce eski kodla çalışmaya devam eder.

---

## 2. Çalışma Ortamı Kısıtları

### Exporter (`za_lookdev_exporter/`)

- Maya'nın gömülü Python'unda çalışır. `maya.cmds` ve `maya.mel` dışında
  **üçüncü parti bağımlılık yok**, standart kütüphane yeterli.
- Dosya `from __future__ import print_function` ile başlar ve baştan sona
  `.format()` kullanır. **f-string, walrus, type hint ekleme** — eski Maya
  sürümleriyle uyum bilinçli bir karar.
- Blender'a özgü hiçbir şey import edilemez (`bpy`, `mathutils`).

### Importer (`za_lookdev_importer/`)

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
| `LIVELINK_PROTOCOL`  | `za_lookdev_livelink`  |
| `LIVELINK_VERSION`   | `1`                    |

Kurallar:

- Mesaj formatı: tek satır UTF-8 JSON + `\n`. Importer `\n`'e kadar okur.
- Mesaj boyutu üst sınırı importer'da `MAX_MESSAGE_BYTES` (32 MB).
- `_validate_message()` protocol, protocol_version, event ve `package_json`
  varlığını kontrol eder. Yeni alan eklemek geriye uyumludur; **alan silmek
  veya yeniden adlandırmak breaking'dir.**
- Breaking bir değişiklik yapıyorsan `LIVELINK_VERSION`'ı **her iki dosyada
  birlikte** artır. Tek taraflı artırma sessiz değil, açık hata verir — bu iyi;
  ama iki tarafı da güncellemeden commit etme.
- `EXPORT_SCHEMA_VERSION` (exporter, şu an `8`) JSON'a yazılır ve importer
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

- Üretilen material adları: `ZA_` öneki
- Üretilen node adları: `ZA_` öneki
- Custom property'ler: `za_` öneki (`za_generated`, `za_source_*`)
- Blender Scene property'leri: `za_` öneki
- Collection'lar: `ROOT_COLLECTION_NAME`, `LIGHT_COLLECTION_NAME` sabitleri

`za_generated` bayrağı, aracın ürettiği datablock'ları FBX'in ürettiği geçici
olanlardan ayırmak için kullanılır. Yeni datablock üretiyorsan bu bayrağı koy.

---

## 7. Yıkıcı Davranış — Bilinçli Tasarım

`import_lookdev_package()` her pakette **sahnenin tamamını siler**. Bu bir hata
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
bilgi `za_source_normalized` custom property'sinde saklanır.

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
`tests/light_calibration.md` içindeki ölçümü tekrarla; rig'in doğruluğunu
Blender'ın `piksel = P/(π²d²)` özdeşliğini tutturmasıyla sınayabilirsin.

Redshift girdisi (`10.0`) hâlâ devralınmış bir tahmindir çünkü plugin bu
makinede kurulu değil. Bunu düzeltmek isteyen olursa yöntem belgede yazılı.

Kullanıcı çarpanı `za_light_power_scale`'dir, varsayılanı `1.0` ve dönüşümün
üstünde çarpan olarak durur. Dönüşüm ölçülmüş olduğu için varsayılanı
değiştirme.

Orijinal Maya değerleri `za_source_*` custom property'lerinde saklanır —
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
python -m py_compile za_lookdev_exporter/*.py za_lookdev_importer/*.py

# 2. Sozlesme kontrolleri (host gerekmez, saniyeler)
python tests/check_contracts.py

# 3. Gercek Maya + Arnold (~2 dk)
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" tests/maya_export_test.py

# 4. Gercek Blender, 3'un yazdigi paketi okur (~30 sn)
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python tests/blender_import_test.py
```

Kurulu Blender sürümleri: 4.1, 4.3, 4.5, 5.2. Kullanıcının hedefi **5.2**.
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
4. Blender System Console'da `Z-A Lookdev warning:` satırlarını kontrol et

### Hata yönetimi deseni

- **Exporter**: paket üretimi atomiktir. Hata olursa FBX, JSON ve klasör
  temizlenir (`export_lookdev` içindeki `try/except`). Yeni dosya üretiyorsan
  bu temizliğe ekle.
- **Importer**: tek bir material/ışık/texture hatası import'u durdurmaz;
  `warnings` listesine yazılır ve akış devam eder. Bu deseni sürdür — kısmi
  sonuç, hiç sonuç yoktan iyidir. Yalnızca akışın devam etmesinin anlamsız
  olduğu durumlarda (sahne temizlenemedi, FBX bulunamadı, mesh üretilmedi)
  exception fırlat.

---

## 10. Kod Stili

- Paket dışına açık API `__init__.py` içindeki `__all__` ile tanımlıdır:
  exporter'da `show_ui`, `show`, `export_lookdev`, `reload_package`;
  importer'da `import_lookdev_package`, `register`, `unregister` ve listener
  fonksiyonları.
- Modüller arası paylaşılan fonksiyonlar `_` **almaz** — başka modülden
  `_foo` import etmek anlamsızdır. `_` öneki yalnızca aynı modül içinde
  kalan yardımcılar içindir (`_build_principled`, `_insert_value_invert`).
- Modül içi import'lar hep relative: `from .mayautils import attr_exists`.
  Absolute import (`from za_lookdev_exporter.mayautils import ...`) yazma;
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

- ❌ Listener thread'inden `bpy` çağırma
- ❌ Exporter'a f-string / type hint / Python 3'e özgü sözdizimi ekleme
- ❌ İki package arasında ortak modül import etme
- ❌ Protokol sabitlerini tek tarafta değiştirme
- ❌ Kanal anahtarını tek tarafta yeniden adlandırma
- ❌ `BUILD_VERSION` ile `bl_info["version"]`'ı ayrı bırakma
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
- ❌ Arnold shader'ında `outColor` okuma (hesaplanmış çıktı, girdi değil)
- ❌ Yeni davranışı teste assertion eklemeden bırakma
- ❌ Kaynak sahnenin istemediği bir şeyi bütün meshlere uygulama
- ❌ Işık enerjisinden `position_scale²` terimini düşürme
- ❌ Blender soket varsayılanını kaynaktan gelen değer sanma (speküler 0.5)
- ❌ Baked map'i sRGB sanma; Maya lineer yazar
- ❌ Soket bileşen sayısını varsayma; Subsurface Radius 3, renk soketleri 4
- ❌ Sahneyi export sırasında kalıcı olarak değiştirme (convertSolidTx'in file node'unu temizle)

---

## 12. Git

Bu klasör şu an bir Git deposu **değil** (README'de bahsedilen depo
`D:\GitHub_Repository\mayatools\ZA_Exporter` yolunda). Commit isteniyorsa önce
`git init` gerektiğini kullanıcıya söyle.

Commit mesajı formatı (İngilizce):

```text
feat: add IES profile support to light import
fix: prevent double inversion on lambert transparency
docs: document light energy calibration constants
```

Davranış değiştiren her değişiklikte **README.md'yi de güncelle** — README bu
projede kullanıcı dokümantasyonudur ve şu an kodla senkron.
