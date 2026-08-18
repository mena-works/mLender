# Yol haritası

İç çalışma notu, Türkçe. `tests/docs/` ölçüm kayıtlarına ayrılmıştır; burası
ne yapılacağına dair karar defteri.

Sıralama "ne kadar değerli" değil, **hata ne kadar kötü × gerçek sahnede ne
kadar sık** ile yapılmıştır. Gerekçesi şu: bu araçta bulunan ciddi hataların
tamamı eksik özellik değil **sessiz kayıp** oldu — instance, locator, curve,
volume, particle, instancer, projeksiyon. Kullanıcı gönderdiğini aldığını
sandı.

**Ölçülen ile ölçülmeyen ayrımı korunmalıdır.** Aşağıda "ölçüldü" yazan her
satırın arkasında çalıştırılmış bir probe vardır; "kontrol edilmedi" yazan
satırlar iddia değil şüphedir.

---

## 1. Sessizce kaybolanlar

En yüksek öncelik. Kullanıcıya tek satır uyarı gitmiyor.

| iş | durum | not |
|---|---|---|
| NURBS yüzeyler | **bitti (2.48.0)** | Export sırasında tessellate ediliyor; stand-in orijinalin parent'ını ve **adını** alıyor, o yüzden grubu, materyali ve set'leri korunuyor. Sahne `finally` içinde geri konuyor. Trim taşınıyor: ölçüldü, panel trimsiz 1024 yüz, trimli 448; FBX 448 poly/896 üçgen, Blender 448 poly, Unreal 896 üçgen. |
| Maya subdiv yüzeyleri | **bitti (2.48.0)** | Aynı yoldan, `subdToPoly` ile. |
| Animasyonlu materyal parametreleri | **bitti (2.47.0)** | Keyli kanallar örnekleniyor ve Blender soketleri LINEAR key'liyor. İki hata çıktı: base colour compound olduğu için çocuk plug'lardan anahtarlı (ilk sürüm bulamadı), ve animCurve shading network sanılıp bake ediliyordu. Animasyon kapalıyken donma artık uyarılı. |
| Desteklenmeyen texture ağı uyarısı | **bitti (2.45.0)** | `unsupported_network` artık iki alıcıda da adıyla bildiriliyor. Başından beri yazılıyordu ve kimse okumuyordu — kanal sessizce düz değere (renkte siyaha) çöküyordu. |

Ölçüm için:

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" -c "..."   # geom probe
```

NURBS için üç yol vardı ve üçü de ölçüldü:

1. **FBX'e tessellate ettirmek** — ölçüldü, **yanlış çıktı**: FBX NURBS'ü
   taşıyor ama `nurbsSurface` olarak geri geliyor, hiçbir alıcı geometri
   görmüyor. Maya subdiv yüzeyi round-trip'ten hiç sağ çıkmıyor. FBX'te
   NURBS dönüştürme seçeneği de yok.
2. **Blender'da yerel NURBS kurmak** — düzenlenebilir kalır ama trim'li
   yüzeyleri temsil edemez. Yarım çözüm, reddedildi.
3. **`nurbsToPoly` ile geçici mesh** — **seçilen yol** (`tessellate.py`).
   Sahneyi değiştirir ama geri koyar; yasak olan iz bırakmak, ve bake yolu
   zaten aynı şekilde node üretip siliyordu.

Yol 3'ten iki tuzak çıktı, ikisi de artık yasak listesinde: `nurbsToPoly` ve
`subdToPoly` çıktılarını **seçili bırakıyor** (seçili-export kullanıcının
seçmediği yüzeyi taşıdı), ve trim her bölge başına bir **curve-on-surface**
bırakıyor (trimli model alıcıya gömülü gelirdi).

---

## 2. Envanter turu — yapıldı

Probe çalıştırıldı. Sonuçlar:

**Sessizce kayboluyordu** (artık uyarılıyor, aşağıya bak):
`fluidShape`, ışık filtreleri (`aiGobo`), `hairSystem`. NURBS ve Maya subdiv
yüzeyleri de bu listedeydi; 2.48.0'da uyarılmakla kalmayıp taşınıyorlar.

**Temize çıktı, listeden düştü:**

- **Image plane** — kamera kaydında geliyor, kayıp değil.
- **Constraint sonucu** — FBX bake'ine düşüyor. Ölçüldü: Maya'da 8 cm
  sürülen bir küp Blender'da 0.0794 m hareket ediyor.
- nCloth ve hair'in kaynak mesh'leri mesh oldukları için zaten geliyor.

**Kapatılmadı, hâlâ kontrol edilmedi:** VDB **dizileri** (kare başına dosya),
kamera overscan/film offset, XGen.

### Sonuç: sınıf kapatıldı

Altı tipi tek tek taşımak yedincisini sessiz bırakırdı. Bunun yerine
`coverage.py` eklendi: sahnedeki her renderlanabilir shape, paketin
taşıdığıyla karşılaştırılıyor ve artakalan tip tip, sayı ve örnekle
bildiriliyor.

Yani **1. kategorinin ilk üç satırı artık sessiz değil** — hâlâ taşınmıyorlar
ama kullanıcı ne kaybettiğini okuyor. Taşıma işi duruyor, aciliyeti düştü.

---

## Kendi borcum — ölçüldü, temiz

Bu oturumda çok yüzey eklendi (şema 30→36). İki şey ölçülmemişti:

**Hız.** 400 mesh / 60 materyal → **1.7 s** (mesh başına 4.3 ms). Eklenenler
şişirmemiş; `coverage.py` profilin ilk yirmisine bile girmiyor. En pahalı
Python tarafı `visibility_info` (%21) ve o bu oturumdan önce de oradaydı.
Rig: `tests/calibration/benchmark_export.py`.

**Etkileşim.** Her yol tek başına test edilmişti, birbirleriyle hiç
denenmemişti. Dört kesişim ölçüldü, dördü de doğru:

- Blend shader katmanının içinde projeksiyon
- Rampa texture'ı transparency'de (Maya inversiyonunun yaşadığı kanal)
- Glass materyalinin transmission renginde projeksiyon
- Instance'lı mesh'te animasyonlu görünürlük

İlk ikisi kalıcı teste alındı, hem bake açık hem kapalı yoluyla — çünkü
ikisinde farklı davranıyorlar ve ikisi de doğru olmalı.

---

## UV set bağlantısı — kapatıldı, ölçüldü

Sessiz kayıp sınıfının bir üyesi daha. UV set'lerin **kendisi** zaten geliyordu
(`uvSetCube` fixture'ı onu sabitliyor); gelmeyen, **hangi texture'ın hangi
set'i okuduğuydu**. İkinci set'e serilmiş bir texture Blender'da birinci
set'ten okunuyordu: yanlış veri, ama "biraz kaymış texture" gibi görünüyor.

Probe sonuçları (`mayapy` + Blender 4.1/5.2, ikisi de aynı):

- `uvLink(query=True, texture=...)` **her zaman** bir plug döndürür; bağlanmamış
  bir texture için bile `uvSet[0]`. Yani plug'ın varlığı "özel set" demek
  değildir — karşılaştırma şart.
- FBX set isimlerini birebir ve Maya sırasıyla taşıyor: `map1`, `secondUV`.
  İndeks 0 `active` ve `active_render` geliyor.
- Blender'ın UV Map node'u **var olmayan ismi sessizce kabul ediyor** ve
  varsayılan katmanı render ediyor. Bu yüzden import sonrası doğrulama var.

Kararlar:

- Yalnız **farklı olan** kaydedilir. Kural isim (`map1`) değil **indeks**:
  ilk set'i yeniden adlandırılmış bir mesh hâlâ varsayılan sayılır.
- Bir materyal tek UV kaynağı taşır. Aynı texture farklı meshlerde farklı
  set'e bağlıysa ilk varsayılan-olmayan seçilir ve **uyarı yazılır**.
- Kayıt: `texture.uv_set = {"name": ..., "conflict": [...]}`, şema 37.

**Bake yolu — açık sanıldı, ölçüldü, temiz çıktı.** Önce "`convertSolidTx`
current set'e yazıyor, ikinci set'e bağlı prosedürel yanlış düşer" diye not
edilmişti. Yanlıştı; ölçüm ikisini de çürüttü:

- Bake, ağı **kendi `uvLink`'i üzerinden değerlendiriyor**. Rampa ters
  çevrilmiş ikinci set'e taşındığında görüntü ters bake oldu.
- Bake, **varsayılan set'e yazıyor, current'ı yok sayıyor**. Current'ı ikinci
  set yapmak hiçbir şeyi değiştirmedi; yalnız `uvSetName` bayrağı değiştirdi.
  Varsayılan set indeks 0, Blender'ın aktif ettiği katman da o.

Yani bake, UV set'i çözüp Blender'ın okuduğu düzene düzleştiriyor; kayıt
`uv_set` taşımıyor çünkü ihtiyacı yok.

Rig dersi, tekrar aynı ders: ilk probe rampayla kuruldu ve **okunamazdı** —
rampa UV okuduğu için okuma ile yazma birbirini götürüyor, dört bake de aynı
çıkıyordu. Cevabı ancak UV'ye hiç bağlı olmayan bir kaynak (obje uzayı
gradyanı, `samplerInfo.pointObjZ`) verdi. "Dördü de aynı çıktı, demek ki sorun
yok" denseydi doğru sonuca yanlış gerekçeyle varılmış olurdu.

**Yan bulgu, ayrı iş:** `BAKE_BACKGROUND_MODE = "black"` geçersiz. Maya
"Wrong argument to -backgroundMode, using 'shader' mode" yazıp yok sayıyor;
kabul edilen değerler `shader` ve `color`. Sabit yalan söylüyor, davranış
'shader'. Zararlı değil (seam bleed için 'shader' muhtemelen daha iyi) ama
düzeltilmeli.

Testler: sözleşmede varsayılan/özel/çakışma/yeniden-adlandırılmış-ilk-set
dalları, host tarafında `uvLinkCube` — biri varsayılan, biri ikinci set'te iki
texture. **Çift** kondu bilerek: tek texture'lı bir fixture, her texture'ın
önüne node koyan bir hatayı da geçirirdi.

---

## layeredShader — kapatıldı, ve altından bir çökme çıktı

**Önce çökme.** Sahnede bir `layeredShader` varsa export **komple ölüyordu**:
`ValueError: No object matches name: LS.color`. Bilinmeyen her shader tipi
`maya_basic_channels`'a düşüyor, o `.color` okuyor, `attr_exists` de "var"
diyor çünkü `inputs` compound'unun `color` adlı bir çocuğu var — ama
`LS.color` adreslenebilir bir plug değil. Eksik özellik değil, paketi
kaybettiren sert hata. İki yerden kapatıldı:

- `texture_from_plug` artık `listConnections`'ı sarmalıyor; adreslenemeyen bir
  plug bir kanala mal olur, export'a değil.
- Blend shader'lar kendi kanallarını okumaya çalışmıyor (`{}` dönüyor) —
  zaten yüzey tarif etmiyorlar.

**Sonra özellik.** İki compositing modu da bake edilerek ölçüldü (unlit yeşil
üstünde unlit kırmızı, beş transparency):

| mod | T=0 | T=0.5 | T=1 | anlamı |
|---|---|---|---|---|
| Layer Shaders (varsayılan) | yeşil | (0.5, **1.0**, 0) | (1,1,0) | `üst + T × alt` |
| Layer Texture | yeşil | (0.5, 0.5, 0) | kırmızı | `lerp(üst, alt, T)` |

Yeşilin 1.0'da kalması farkın tamamı: ilk mod **topluyor**, üst katmanı
söndürmüyor. Blender'da Add Shader + Transparent'a karşı ölçeklenmiş alt
katman; ikincisi düz Mix Shader. Sayı hiçbir yerde ters çevrilmiyor, kablolama
değişiyor.

`layeredShader` diğer ikisinin tersi iki noktada: indeks 0 **üst**, ve ağırlık
mix değil **transparency**. Renkli transparency ortalanıyor ve uyarı yazılıyor.

**Kesişim test edildi:** `layeredShader`'ın bir katmanının kanalını süren bir
`layeredTexture`. İkisi ayrı yazılmıştı, hiç karşılaşmamışlardı; hem bake
açık (bake'e düşüyor) hem kapalı (iki yığın da kuruluyor) yoluyla doğrulandı.

---

## aiStandIn ve gpuCache — kapatıldı, ölçüldü

İkisi de aynı problemin iki adı: geometri taşımayan, diskteki bir dosyayı
gösteren yer tutucu. `coverage.py` ikisini de sayıyordu; artık taşınıyorlar.

**Dosya referans ediliyor, kopyalanmıyor** — kullanıcı kararı. Standin rutin
olarak GB'larca, ve paket zaten texture'ları aynı sebeple referans ediyor.

Attribute isimleri canlı Maya 2023'ten okundu: yol `aiStandIn.dso` ve
`gpuCache.cacheFileName` — tek fikir, iki isim, o yüzden tablo.

**Birim sorusunun üç formatta üç ayrı cevabı var, üçü de ölçüldü (4.1 ve 5.2):**

| format | birim metadatası | ne yapılır |
|---|---|---|
| `.abc` | yok | ölçek verilmeli, mevcut ölçülü çağrı kullanılır |
| `.obj` | yok | `global_scale` çalışıyor: 4 birimlik küp 0.01'de 0.04 geliyor |
| `.usd` | **kendi taşıyor** | operatörün `scale`'i kabul edilip **yok sayılıyor** — dünya uzayında ölçüldü, ne verilirse verilsin küp 4 birim geldi. O yüzden hiçbir şey verilmiyor. |

Son satır tam olarak "Blender API'sini doğrudan çağırma" kuralının neden
olduğunun örneği: `scale=0.01` hata vermiyor, sessizce hiçbir şey yapmıyor.
Mesh'in kendi `dimensions`'ına bakmak da yetmezdi (parent'a uygulanmış
olabilirdi); dünya uzayında ölçmek gerekti.

`.ass` Blender'ın hiç okuyamadığı format. Okunamayan veya bulunamayan dosya
**anchor'ı Maya'nın çizdiği kutu boyutunda yalnız bırakıyor**, yolu üstünde ve
uyarısı yazılı. Referans verildiği için başka makinede açılan paket buraya
tasarım gereği düşer.

**Sınır kutusu Maya'nın çizdiği, dosyanın gerçek boyutu değil.** Ölçüldü:
`Min/MaxBoundingBox`'ı viewport dolduruyor, başsız export varsayılan ±1 okuyor
ve `exactWorldBoundingBox` sıfır dönüyor. Blender'da birim kutu görünmesi
Maya'nın o durumda gösterdiğinin aynısı.

---

## Paketleme — iki anlamda da yapıldı

Soru iki şey olabiliyordu, ikisi de eksikti, ikisi de yapıldı.

**1. Aracın kendisi kurulabilir paket.** Bugüne kadar kurulum elle klasör
kopyalamak ve `userSetup.py` düzenlemekti — paylaşılan bir dosya, kullanıcının
kendi tercihlerinde, bir hatası bütün pipeline'ı bozar. `packaging/` eklendi:

- `build_release.py` → Blender add-on `.zip` (klasör adı korunur, çünkü o ad
  add-on'un **modül adı**; değişirse Blender güncellemez, yanına kopyalar) ve
  Maya **modülü** (`.mod` + `scripts/`), `MAYA_MODULE_PATH`'e atılıp geçilir.
  Sürümler tutmuyorsa build etmeyi reddediyor.
- `verify_release.py` → ikisini de **gerçekten kurup** deniyor: modülü repoya
  erişilemeyen bir çalışma dizininden mayapy'ye, add-on'u tek kullanımlık bir
  Blender home'a. Kullanıcının gerçek profiline dokunmuyor.

Formalite değil: **ilk `.mod` yolu yanlıştı** ve test yakaladı; ikinci turda da
test kendi hatasını gösterdi (mayapy cwd'yi sys.path'e koyduğu için repo kopyası
import ediliyordu, modül hiç denenmemiş oluyordu ve **geçti gibi görünüyordu**).

**2. Export çıktısı taşınabilir paket.** İki ölçülmüş kusur çıktı:

- "Collect Textures" adı doğruydu ama vaadi yarımdı: ölçüldü, toplama açıkken
  paket texture'ını taşıyıp **VDB'yi ve Alembic standin'i dışarıda bıraktı**.
  Artık `files_collected/` ile ikisi de giriyor; seçenek `Collect Files` oldu.
- Toplanan yol yine **mutlak** yazılıyordu, yani "taşınabilir" paket taşınınca
  kırılıyordu. `resolve_package_paths()` import'ta bir kez çalışıp yerinde
  bulunamayan her yolu paketin içinde arıyor (kök, sonra iki toplama klasörü) —
  FBX ve Alembic'in kendileri için zaten yaptığı şey, artık texture, UDIM tile
  seti, projeksiyon arkasındaki görüntü, layered stack katmanları, volume ve
  standin için de. Yerinde çözülen yol **hiç dokunulmadan** bırakılıyor.

Ölçüldü: toplanmış paket başka bir klasöre kopyalanıp adı değiştirildi ve
kaynak dosyalar silindi → **3 yol yeniden işaretlendi, 0 eksik dosya uyarısı**,
texture yüklendi, volume kuruldu, standin'in cache'i altına geldi.

**Arşiv:** `Archive Package` paketin yanına tek `.zip` yazıyor, arşivin tek üst
düzeyi paket klasörü (açınca importer'ın istediği şey çıkıyor). Klasörün
*yerine* değil *yanına*, çünkü LiveLink ve importer klasörü okuyor.

Açık kalan: importer `.zip`'i doğrudan okumuyor, alan taraf açıyor.

---

## USD turunun a1'i — kapatıldı

USD turunun bulduğu iki canlı hatanın ilki, ve **bir önceki oturumda benim
soktuğum** koddu: `standins.py`'ın USD dalı operatörü argümansız çağırıyordu,
üç satır yukarıdaki Alembic kardeşi ise `set_frame_range=False` geçiriyordu.

Kendi `import_standins()`'imiz üzerinden birebir üretildi (4.1 ve 5.2 aynı):

- Sahne 1..24 iken asset'in `startTimeCode/endTimeCode`'u kazanıyor → **40..90**
- Asset'in `SphereLight`'ı sahneye POINT olarak giriyor: 4.1'de **9869.605**,
  5.2'de **3141.593** — aynı dosya, 3.14× fark, `light_energy()`'ye hiç
  uğramadan. Kamera da geliyor (lens 350000).
- `warnings` **boş**. Sessiz, ve başka bir şeye benziyor: kayan aralık "export
  yanlış aralık gönderdi", kaçak ışık "ışık kalibrasyonu bozuk" gibi okunur.

Üç argüman da (`set_frame_range`, `import_lights`, `import_cameras`) 4.1/4.3/
4.5/5.2'nin hepsinde var ve hepsinde varsayılanı `True`.

Kararlar:

- Argümanlar **TypeError merdiveni yerine** operatörün kendi RNA'sına sorularak
  filtreleniyor. USD importer'ının property'leri sürümler arası oynuyor
  (`import_subdiv`→`import_subdivision`, `attr_import_mode` yalnız 4.3/4.5'te);
  "hangilerine sahipsin" diye sormak, "bir şey reddedildi" bilgisinden daha
  fazlasını söyler.
- `import_lights=False` prim'i **silmiyor, EMPTY bırakıyor** — test tipe assert
  ediyor, yokluğa değil. Asset'in yapısı bozulmuyor.
- Düşürülen ışık/kamera **uyarıya yazılıyor**. Bir sessiz kaybı başkasıyla
  takas etmek düzeltme değildir. Sayım `pxr` ile yapılıyor: Blender'ın dördü de
  bundle ediyor (ölçüldü: 4.1→USD 23.11, 5.2→26.3) ama yine de `try/except`
  ile korunuyor — kütüphane yoksa import doğru kalır, yalnız cümle eksilir.

Fixture olarak Maya testine elle yazılmış bir `.usda` eklendi (Maya tarafında
USD kütüphanesi gerekmiyor, exporter yalnız yolu kaydediyor).

---

## Gerçek rig turu — SpiderSilk (assets/rig/, git dışı)

Roadmap'in "gerçek sahne" maddesi ilk kez gerçek bir prodüksiyon karakteriyle
çalıştırıldı: 50 MB `.ma`, 54 mesh, 1014 joint, 31 skinCluster, 13 blendShape,
3010 constraint, 597 kontrol eğrisi, cm birim. Export 4-5 sn, import 4-6 sn,
çökme yok. Coverage yeni bir tip yakaladı: `poseInterpolator` (15) — hiçbir
listede yoktu, gerçek sahne akla gelmeyeni buldu.

**Rig durumu, ölçüldü:**

- Skinning **çalışıyor**: 18 mesh vertex group + armature modifier ile geliyor,
  6 mesh shape key taşıyor, kemik döndürünce 6199/6199 vertex deforme oluyor.
- "0 hareket" iki kez yanlış alarmdı: (1) kaş kemiğiyle göz mesh'i ölçülmüştü,
  (2) mesh Maya'da gizli geldiği için Blender depsgraph'tan çıkarıyor —
  **gizli mesh'te modifier hiç değerlendirilmez**, ölçmeden önce aç.
- `scene_joints` düzeltildi: sahnedeki bütün joint'ler değil, yalnız export
  edilen meshlerin skinCluster influence'ları + joint ataları. Ölçüm:
  **132 armature → 2** (`joints_grp` 372 kemik, `rivet_ws_grp` 242).
- Kontrol katmanı (515 ctrl → constraint/IK/motionPath → bind joint) **gelmiyor
  ve gelmeyecek** — Maya'nın DG değerlendirmesini taşımak demek. Ters durum
  not edildi: Maya'da bind joint'ler constraint'li olduğundan elle
  döndürülemez; Blender'da serbest FK olarak döndürülebilir.
- Maya'daki sürülmüş hareket **bake ile birebir geliyor**: `main_ctrl`
  anahtarlanınca armature'a 2930 f-curve düştü, `spineChest_env` iki uçta da
  Maya'yla altı hane aynı (1.270495 / 1.520495 m).

**Bulunan genel hata — bir karelik kayma, kapatıldı:** Blender FBX
importer'ının `anim_offset` varsayılanı 1.0 (dördünde de ölçüldü). Maya kare
N'i N/fps saniyeye yazar → her baked anahtar N+1'e düşüyordu. Mesh hareketi,
JSON'dan Maya kare numarasıyla anahtarlanan ışık/kamera/görünürlükten **bir
kare geride** oynuyordu ve aralığın son karesi sondan bir önceki pozu
gösteriyordu. `anim_offset=0.0` geçiliyor; test artık span'e değil anahtarların
**nerede durduğuna** da assert ediyor — span kontrolü kaymayı bir sürüm boyunca
geçirmişti.

**Açık kalanlar:** rig iskelesi gürültüsü (4615 empty: 3582 tamamen boş grup,
770 locator, 263 yalnız-joint grubu; 586 eğrinin hepsi `|rig` altında —
"rig internals" anahtarı mı dar kural mı, kullanıcı kararı), Gemini'nin ölü
constraint kodu (3010 constraint'ten 0'ı kaydediliyor: `listConnections`'a
geçersiz `fullPath` bayrağı + `mesh_path`/`transform_path` anahtar uyumsuzluğu),
`setup_gui.py`'ın bildirilmemiş `customtkinter` bağımlılığı.

---

## Canlı poz köprüsü — yapıldı, ölçüldü

Araştırma turunun kararı uygulandı: DG taklit edilmiyor, **Maya'ya
değerlendirtiliyor** (UE Live Link deseni). Yeni event `pose_update`;
bilinmeyen event açık hatayla reddedildiği için protokol sürümü artmadı.
`posebridge.py` iki tarafta da var; Maya UI'da "Send Pose" + "Sync Timeline
Pose" (timeChanged scriptJob).

Blender tarafındaki matematik: hedef dünya matrisinden `matrix_basis`,
ebeveynler önce ve ebeveynin **hedefine** karşı çözülüyor — sahne güncellemesi
gerekmeden tek geçişte. FBX'in kemik eksen konvansiyonu türetmeden düşüyor;
bunun sınayıcısı **bind pozu no-op testi**.

O test ilk koşuda gerçek bir hatayı yakaladı: birim ölçeği yalnız
translation'a uygulamıştım, FBX ise cm dönüşümünü **kemik çerçevelerinin
kendisinde** taşıyor (her rest-chain world matrisi 0.01 ölçekli) — kökün
basis'i 100 ölçek geldi ve skin bind'de −0.54 m kaydı. Ölçek artık tüm
matrise uygulanıyor. Bir itiraf da kayda: ilk "altı hane tuttu" ölçümüm
**döngüseldi** (kendi yazdığım pb.matrix'i geri okuyordum); gerçek hakem
skin'dir ve testler ona göre yazıldı.

SpiderSilk'te uçtan uca: bind uygulaması mesh'i **+0.000000** oynatıyor (596
kemik, en kötü basis sapması 0.0004 cm), 25 cm'lik kontrol hareketi mesh'e
**+0.249999 m** olarak geliyor, kemik dünyaları ~10⁻⁷ m. Gerçek soket duman
testi: mayapy → listener thread → pompa → 5 hanede birebir uç.

Yol üstünde iki iş daha kapandı:

- **Cache kapısı düzeltildi:** deformerleri yalnız skinCluster/blendShape olan
  mesh artık Alembic'e değil FBX'e gidiyor — cache pozlanabilirliği donduruyordu.
  Karışık deformer (skin + cluster) cache'te kalıyor ve uyarısı bunu söylüyor.
  Bunu mevcut bir alembic assertion'ı yakaladı; fixture'daki skinli silindir
  cache'e düşünce sayı 2 oldu.
- **Fixture'a skinli üç eklemli zincir + bağsız decoy joint** girdi: rig
  taşıma ilk kez kalıcı süitte (armature + vertex group + poz parity +
  decoy'un taşınmadığı).

**Advanced Skeleton notu (kullanıcı kararı):** hedef daraldı — "çoğunlukla AS
kullanıyoruz, AS rig'leri exchangeable olsun yeter." Köprü rig'den bağımsız
zaten çalışıyor; AS'ye özel katman (Blender'da FK/IK kontrol rig'i üretimi,
AS'nin düzenli adlandırması sayesinde yapılabilir) **ölçülmeden yazılmayacak**:
SpiderSilk stok AS değil. Bir AS karakteri `assets/rig/` altına gelince
envanteri çıkarılıp tasarlanacak.

---

## Advanced Skeleton — beş rig ölçüldü, köprü kutudan çıktığı gibi çalışıyor

Kullanıcı beş AS karakteri verdi (Chubs, Cubby, Gizmo, Joey, Sam; assets/rig/,
git dışı). Envanter beşinde de aynı deseni verdi:

- `DeformSet` = gövde bind iskeleti (34-36 eklem) — AS asıl iskeleti kendisi
  beyan ediyor. `ControlSet` beşinde de tam 121 kontrol; `FaceControlSet` ayrı.
- FK kontrol ↔ eklem **birebir isim**: `FKElbow_L` ↔ `Elbow_L`.
- `FKIK{Arm,Leg}_{L,R}.FKIKBlend` (0=FK, 10=IK) ve switcher üstünde
  `startJoint/middleJoint/endJoint` — IK zinciri attribute olarak yazılı,
  probe gerekmiyor.
- Hepsi cm, 13'er blendShape, yüzde ~144 ek eklem (DeformSet dışında ama
  skinCluster influence'ı, yani keşfimiz hepsini alıyor: 178 ⊇ 34).

Chubs uçtan uca: export 1.5 sn, import 48 mesh / 18 skinli / gövde 53k vertex,
armature **tek ve temiz** (`DeformationSystem`, 179 kemik). Rig'in kendi
kontrolüyle poz (`FKIKBlend`→FK, `FKElbow_L` −50°) köprüden geçti: bind ve
sürülen pozda bilek Maya'yla **10⁻⁷ m** içinde, 178/178 eklem, sıfır uyarı.

Karar (kullanıcı): "exchangeable"in üçüncü katmanı yapılacak — Blender'da
yerli AS kontrol katmanı: FK kemiklerine kontrol eğrisi siluetleri (custom
shape), kol/bacak için gerçek Blender IK + pole + FKIKBlend karşılığı limb
başına özellik. Yüz v1'de dışarıda. Yaklaşıklık yalnız IK çözücünün kendi
matematiğinde; FK ve köprü birebir kalır.

---

## AS kontrol katmanı — yapıldı, ölçüldü, ve iki tuzak dersi

Manifest'ten yerli Blender kontrol katmanı: FK kemiklerine AS eğrileri custom
shape, beyan edilen zincirlere gerçek Blender IK'sı (IK/Pole eğrileri canlı
hedefe terfi), limb başına `FKIK_<Limb>_<Side>` property'si. Şema 42.

**Ölçülen iki gerçek kodu şekillendirdi:**

1. FBX kemikleri **kopuk çubuk** getiriyor — kuyruklar bir sonraki eklemde
   değil. Ölçüldü: hiçbir kısıt düzeni duruşu tutturamadı, en iyisi tam bir
   kemik boyu (0.041) saptı. Çözüm zincirleri **yeniden kuyruklamak**; poz
   rest'teyken yapıldığı için skin'e maliyeti sıfır.
2. `pole_angle` **tarama ile kalibre** ediliyor: rest'te ucu kıpırdatmayan
   açı ölçülerek bulunuyor. "IK rest'te no-op" böylece kurgu gereği doğru.

**İki yanılgı da kayda** — ikisi de geçersiz ölçümdü, çözücü suçsuz çıktı:

- "Kilitli sahip / ölü çözücü" turlarının tamamı **erişilemez yönde** çekilmişti:
  T-pose'da kol +X'e dümdüz uzanıyor, hedef +X'e çekilince zaten tam
  uzanmış zincir haklı olarak yerinde durdu. Eleme sonuçları çöpe gitti.
- Sonra "yarım takip" (−0.026/−0.05): **Chubs 3 cm'lik karakter**, 5 cm'lik
  çekiş kolu erişimin dışına çağırıyordu; −0.0263 tam katlanma sınırıydı.
  Rig ölçeğinde (−8 mm) çekince takip **birebir**: −0.00800.

**Köprü ile IK aynı kemikleri sürüyor** — kavga yerine sıra: akan Maya pozu
FK diktesidir, `apply_pose` limbleri FK'ya park eder ve **uyarıyla söyler**
(ölçüldü: canlı IK ebeveynleri yeniden yönlendirip basılı pozu bir kemik boyu
sarkıtıyordu). Python'dan property değiştiren `update_tag()` çağırmalı —
ölçüldü, sürücü ancak ondan sonra okuyor.

Chubs'ta uçtan uca: 4 zincir + 32 FK silueti, rest 0.000000, −8 mm çekiş →
bilek tam −0.00800 + skin bükülüyor, FK dönüşü 0.000000. Kalıcı süitte
mini-AS fixture'ı (iki set + switcher + 4 eğri + skinli kol) her mekanizmayı
assert ediyor. Kapsam dışı (bilinçli): yüz, spine hybrid IK, Blender→Maya
geri poz.

**AS Rig paneli (2.33.0):** picker'ın işlevsel karşılığı N-panel'de — limb
başına FK/IK slider'ı + tek tıkla limb seçimi (3 kemik + IK + pole) ve
"Select FK Controls". `build_as_rig` manifesti `ml_as_rig` ID property'si
olarak armature'e yazıyor; panel ve seçim yardımcıları isim türetmek yerine
onu okuyor, yani kaydedilip yeniden açılan .blend'de de çalışıyor. Slider
aralığı `id_properties_ui` ile 0..1'e sabitlendi. Ölçülen sürüm farkı: kemik
seçim bayrağı 4.x'te `Bone.select`, 5.x'te `PoseBone.select` — probe ile
doğrulandı, `set_bone_selected()` ikisini de karşılıyor. Host testinde
manifest, aralık, iki seçim yolu (fonksiyon + gerçek operatör), kayıt ve
panel poll'u assert'li; 4.1/4.3/4.5/5.2 dördü de yeşil.

**Referanslı ve çoklu rig (2.34.0, şema 43):** kullanıcının "birden fazla AS
rigi varsa?" sorusu probe'la ölçüldü ve asıl bulgu daha genişti — **tek**
referanslı rig bile algılanmıyordu: setler `Chubs:DeformSet`'te yaşıyor,
çıplak `objExists("DeformSet")` ve `ls("FKIK*")` ikisi de boş dönüyor.
Düzeltme üç ölçüme dayandı:

1. FBX namespace'i Blender'a **aynen** taşıyor, iki nokta dahil
   (`NS:probeRoot` kemik, `NS:probeCube` obje). Yani çeviri tablosu değil,
   her yerde tam nitelikli isim: exporter kayıtları, poz köprüsü isimleri
   (`without_namespace` çağrısı kaldırıldı — soymak referanslı rigin pozunu
   sessizce eşleşmez bırakıyordu), importer eğri objeleri.
2. JSON'dan kurulan eğriler FBX'le tutarsızdı: `safe_name` iki noktayı
   `_`'ye çeviriyordu → `NSRig:IKArm_L` kaydı `NSRig_IKArm_L` objesini
   bulamıyordu. `safe_object_name` iki noktayı koruyor (ölçüldü, Blender
   isimleri ':' taşır). Paket tarafında `disambiguate_names` zaten çakışan
   isimleri namespace'le nitelendiriyordu; artık eğri adı her durumda
   `curve_full_name`.
3. `as_rig` → `as_rigs` listesi (şema 43), namespace başına bir kayıt.
   FKIK property'si rig'e nitelikli: `FKIK_Chubs_Arm_L` — iki rig tek
   armature'a düşerse slider çakışması yok. Manifest armature başına
   birleştiriliyor, panel etiketi "Chubs Arm L".

Kalıcı süitte fixture'a namespace'li ikinci mini-AS eklendi — kısa isimleri
kök rig'le bilerek aynı, prodüksiyondaki çakışma bu. Referanslı Chubs'ta
uçtan uca: namespace'ten algı, 5 zincir bildirimi (spine IK'sız, açık
uyarıyla atlandı), 4 zincir kuruldu, 32 siluet, IK rest 0.0, −8 mm çekiş →
bilek tam −0.00800, 178 poz joint'i hepsi nitelikli. Bilinen kozmetik pürüz:
iki rigin `ControlSet` koleksiyonları Blender'da `ControlSet` /
`ControlSet.001` diye numaralanıyor (set adları disambiguate edilmiyor);
işlevsel etkisi yok.

Desteklenmeyen tek yerleşim (bilinçli): iki rigi namespace'siz import etmek.
Maya çakışan setleri `DeformSet1` diye yeniden adlandırıyor ve rigleri ayırt
edecek hiçbir şey kalmıyor; ölçüldü, README'de söylendi.

---

## Animasyonlu paket × AS katmanı — çatışma kapandı, bir sınır ölçüldü

Kullanıcının sorusu ("animasyon rig'le beraber taşınır mı") iki ölçüm çıkardı:

**Kapandı:** animasyonlu pakette FKIK varsayılanı IK kalınca statik hedef
baked animasyonla kavga ediyordu — 3 cm'lik karakterde daha ilk karede 1.3 cm
hata. `build_as_rig` artık armature'de action varsa limbleri **FK'ya parklı**
kuruyor; host testinde dişi var ("an animated package arrives parked").

**Ölçülen sınır (2.35.0'da kapandı):** iskeletin **üstündeki grup
katmanında** yaşayan hareket (AS `Main` üstüne anahtar) bake'e binmiyordu.
Kapatma yolu üç yanlış hipotez eskitti ve her biri ölçümle elendi:

1. Minimal repro sürpriz yaptı: grubun **kendi animCurve'ü** varsa FBX onu
   katlıyor — uçlar birebir, ara kare 0.8 mm (spline→linear düzleşmesi).
   Kaybolan şey yalnız **bağlantıyla sürülen** hareketti (Main → connection),
   o statik değerde donuyor. İki ayrı katlama türü.
2. "Kök kemiği mutlak gerçekle key'le" → Chubs'ta çocuklar 1 cm kaydı:
   FBX kemiği Maya joint'inden **90° roll** farklı eksenlerle kuruyor
   (basis quat 0.707 ölçüldü). Canlı köprü bundan muaf çünkü her kemiği
   mutlak dikte ediyor; tek kökü key'lemek farkı ilk kez görünür kıldı.
3. "Referans karede kalibre et" → fixture'da 2.8 mm: referans karesi (7)
   eğri katlamasının linearize hatasının üstüne denk geldi ve hata
   kalibrasyona sızdı. "Grup gerçeği @ baked pose" özdeşliği tek başına da
   yetmedi — Chubs'ta Main kökün **local**'ini sürüyor, grup dünyası hiç
   kıpırdamıyor.

Nihai bileşim ikisini birleştiriyor: exporter kök joint'in **ve** grubunun
dünya matrislerini kare kare + export anındaki karede bir referans çifti
yazıyor (`skeleton_root_motion`); importer eksen farkını
`(joint_truth)⁻¹ @ (grup_truth @ baked_pose)` ile **temiz** çapada kalibre
edip her karede `joint_truth @ R`'yi kök kemiğe key'liyor. Çapa iki katlama
türünde de temiz: statik katlama tam o karenin değerini tutar, eğri
katlamanın hatası armature objesindedir ve formül ona hiç bakmaz. Bake'in
doğru olduğu yerde no-op — çift uygulama yok. Anahtar okuma iki geçişli:
key basmak henüz basılmamış karelerin evaluasyonunu değiştirir (FBX bazen
seyrek key bırakır, repro'da 1 ve 10).

Doğrulama: minimal repro (iki eksen, spline ara kare) üç karede de 0.0;
Chubs referanslı + `Main` iki eksende keyli → `Root_M` ve `Wrist_L` üç
karede de 0.000000. Kalıcı fixture'da keyli grup + skinli zincir; Blender
testi ara kare 13'te dünya konumu, anahtarların Maya karelerinde durduğu
ve LINEAR olduğunu assert ediyor. 4 Blender sürümü yeşil.

Ders (yasak listesinde zaten var, bir örneği daha): flatCube animasyon testi
yalnız **X** ekseninde assert ediyordu; X→X iki konvansiyonda aynı olduğundan
eksen sorunları o testte tanım gereği görünmez. Minimal repro Y+Z ile kuruldu.

---

## Maya tarzı outliner paneli (2.36.0)

Kullanıcının isteği transfer değil, Blender'a **özellik**: Maya outliner'ının
davranışı. Dördü de istendi ve panel API'sinin dürüst tavanı içinde kuruldu
(Python add-on'u editör tipi ekleyemez, gerçek drag-drop yok — taşıma buton):

- Manuel kardeş sıralaması: `ml_outliner_index` ID property, ▲/▼ ile;
  sırasızlar sıralıların arkasında alfabetik kalır, dosyayla kaydedilir.
- Tek ağaç: transform hiyerarşisi, kapalı başlar, `ml_outliner_open` ile
  açılır; arama eşleşmeleri düz listeler (kapalı dalın içi de bulunur).
- Tık = seç, Shift-tık = ekle (operatör `invoke`'unda `event.shift` — panel
  butonunun modifier okuyabildiği tek yer); satırda göz + render toggle.
- Parent-here: seçiliyken her satırda tek tık parent, dünya konumu korunur
  (`matrix_parent_inverse`), döngü reddedilir; ✕ unparent yine konum koruyarak.

Mantık `outliner.py`'da UI'sız fonksiyonlar (AS panelindeki ayrımın aynısı),
host testte başsız assert'li: kök satırlar, açma/kapama, arama, sıralamanın
kalıcılığı, parent/unparent'ta < 1e-6 dünya sapması, döngü reddi. Çizim 400
satırla sınırlı (UI thread'i onbinlerce satırda durur; arama hepsine ulaşır).
4 Blender sürümü yeşil. Kalan bilinen sınır: gerçek sürükle-bırak ve shape
satırları — ikisi de *panel* API'sinin tavanının ötesinde.

**GPU overlay outliner (2.37.0):** o tavanın üstüne kullanıcının "açık
kaynak Blender, niye olmasın" itirazıyla çıkıldı — fork değil, `gpu`+`blf`
ile add-on içinde kendi çizimimiz + modal operatörle ham fare olayları.
Panelin veremediği jestler artık var: satırı satıra sürükle = parent
(dünya konumu korunarak, seçili satırı sürüklemek seçimin tamamını taşır),
header'a bırak = unparent, çift tık = rename (dialog), Shift-tık toggle,
tekerlek kaydırma, katla/aç. Ağaç/sıra/katlama durumu panel outliner'la
ortak (`outliner.py`), yani iki görünüm hiç ayrışmaz. Overlay açıldığı tek
viewport'ta yaşar; Esc veya buton kapatır.

**Kullanıcı denemesinden çıkan iki eksik (2.38.0):** "objelerin sırasını
kaydırarak değiştiremiyorum" ve "outliner penceresini taşıyamıyorum".
İkisi de gerçek eksikti — ilk sürümde her sürükleme parent'lamaya gidiyordu
ve kart sabit köşedeydi.

- Sürükleme artık iki iş yapıyor: satırın **ortası** parent, **üst/alt
  kenarı** (6 px bant) araya ekler; bırakılacak yer turuncu çizgiyle
  gösterilir. Başka seviyedeki iki satır arasına bırakmak çapanın
  ebeveynini alır — tek sürüklemede hem yuva değiştirme hem sıralama
  (Blender'ın kendi outliner'ının da kuralı budur).
- Header artık tutamak: sürükleyince kart taşınır, konum oturum boyunca
  kalır. Offset **kıskaçlı**: viewport küçülünce ekran dışında kalıp
  geri getirilemeyen bir pencere olmasın diye.

Assert'ler: orta bant vs kenar bantları farklı cevap veriyor mu, bantlar
scroll'la kayıyor mu, kart offset'i uygulanıyor ve kıskaçlanıyor mu,
sıralama gerçekten değişiyor mu (ilk sıraya taşıma, bir satırın altına
bırakma), kendine bırakma reddi, seviye değiştiren bırakmada dünya konumu
< 1e-6, ve ata-torun döngü reddi.

**Eksik envanteri kapatıldı (2.39.0).** Kullanıcı "ne eksik?" diye sordu,
liste çıkarıldı ve hepsi yapıldı:

- **Undo** — en ciddisiydi: sürükleyip parent'ladığında Ctrl+Z geri
  almıyordu (kodda tek `undo_push` yoktu). Önce headless ölçüldü:
  `undo_push` + `undo` bir parent değişikliğini gerçekten geri alıyor.
  Artık parent, reorder, unparent, rename ve görünürlük ayrı ayrı adım
  basıyor. Testte de assert'li — ama testin sonunda, çünkü undo bütün
  datablock'ları yeniden kuruyor ve süitin daha önce tuttuğu Python
  referansları geçersizleşiyor (ölçüldü: `Material has been removed`).
- **Görünürlük** overlay satırlarında (dolu üçgen = açık, boş kare =
  kapalı; GPU modülünde ikon atlası yok, iki şekil dolu/boş ayrımıyla
  okunuyor).
- **Seçileni göster**: `F` ve panel butonu; üstteki bütün dalları açıp
  satırı görünür kılacak kadar kaydırıyor (zaten görünüyorsa liste
  kıpırdamıyor — zıplayan liste yoktan kötüdür).
- **Silme** (`X` / buton / menü) çocuklarıyla birlikte, isimle yeniden
  bakarak: bir objeyi silmek diğerlerinin referansını geçersizleştiriyor.
- **Aralık seçimi**: Ctrl toggle, Shift aralık — aralık *görünen* satırlar
  üzerinden, kapalı dalın içi habersiz süpürülmesin diye.
- **UI ölçeği**: bütün geometri fonksiyonları `scale` alıyor; %150 ekranda
  kart Blender'ın panelleriyle aynı fiziksel boyda ve tıklama isabetleri
  ölçekte de doğru (assert'li).
- **Satır içi rename** (çift tık, caret, Enter/Esc), **sağ tık menü**,
  **scrollbar** (çiziliyor + sürüklenebiliyor), **köşeden boyutlandırma**,
  ve konum/boyutun `.blend` içinde saklanması.

Mimari not: çizim ve hit-test aynı saf geometri fonksiyonlarını kullanır
(`card_rect`, `hit_test`, `row_rect`...) ve süit bunları başsız assert
eder — çizimin kendisi pencere ister, onu göz doğrular. `blf.size` imzası
sürümler arasında değişti (dpi argümanı kalktı), `TypeError` merdiveniyle
korunuyor; `gpu`/`blf` import'unun background'da da çalıştığı 4 sürümde
ölçüldü (contract stub'ları ayrıca eklendi). Fork yolu bilinçli reddedildi:
özel build dağıtmak add-on taşınabilirliğini öldürür, kayıt roadmap'te.

## Maya grubu, Blender özelliği olarak (2.40.0)

Soru "koleksiyonlar Maya grubu gibi davranabilir mi" idi ve kapsam mLender
import'u değil, **Blender'a Maya özelliği eklemek**. Üç ölçüm cevabı verdi:

1. Koleksiyonun transform'u **yok** — `location`/`matrix_world` alanı bile
   yok, yalnız `instance_offset` var. Yani hiçbir add-on koleksiyonu
   hareket ettiremez; bu Blender'ın veri modeli.
2. Grup gibi davranan şey grup **empty**'si: `props` empty'si
   `stdSurfCube`'u taşıyor, `setDressing` `props`'u taşıyor, empty'yi 5
   birim taşıyınca çocuk tam 5 birim gitti.
3. Ama grup yarım doluydu: FBX'ten gelen mesh'ler empty'ye parent'lı,
   **JSON'dan kurulanlar değil** — `curveGroup`'u taşıyınca eğri yerinde
   kalıyordu.

Çözüm `grouping.py`: koleksiyona eksik olan transform'u veren tek bir
mantık, hem kullanıcı komutu hem import tamamlayıcısı olarak. `Group
Selected` (Maya Ctrl+G karşılığı; empty + aynı adlı koleksiyon, işaretli
çift, transform Maya gibi orijinde), `Ungroup`, ve Blender'ın **kendi**
outliner'ının koleksiyon sağ-tık menüsüne eklenen `Make Group (Movable)` +
`Select Group Transform`. Menü sınıf adları (`OUTLINER_MT_collection`,
`VIEW3D_MT_object`) tahmin değil, 4.1 ve 5.2'de probe edildi.

Korumalar: aracın kendi koleksiyonları (light link, set, layer) gruplanmaz
— üyelik onların çalışma şekli. Aynı koleksiyona ikinci kez sorulunca
mevcut transform devralınır, üst üste grup kurulmaz. **Animasyonlu grup
elle sürülmez**: ışık/kamera dünya uzayında örnekleniyor, anahtarlar grubun
hareketini zaten taşıyor; parent'lamak hareketi iki kez uygulardı, o yüzden
atlanıp uyarı yazılıyor.

Yolda iki gerçek hata: `Collection.users_collection` diye bir alan yok (o
Object'in alanı), ebeveyn koleksiyonlar taranarak bulunuyor; ve zaten
bağlı objeyi yeniden saymak "iki kez sorunca üst üste kuruyor" gibi
görünüyordu — `attach_to_empty` artık gerçekten taşınanı sayıyor.

## Unreal alıcısı (2.41.0) — yapıldı, ölçüldü

Kullanıcı kararı: **Maya → Unreal, üçüncü alıcı**; kapsam lookdev çekirdeği;
materyaller melez (instance varsayılan, gerekirse grafik); plugin hem proje hem
engine'e kurulabilir.

Mimarinin bedava çıkan kısmı: exporter zaten host-agnostik. Paket yazıp TCP
mesajı atıyor, kimin dinlediğini bilmiyor. Yani **exporter'a tek satır
dokunulmadı** ve Blender alıcısı hiç etkilenmedi. Üçüncü package `mlender_unreal`.

Ölçülenler (ayrıntı `tests/docs/unreal_calibration.md`):

- **Eksen:** `(x, y, z) → (x, z, y)` — düz Y/Z takası, işaret yok. Blender'ın
  `(x, -z, y)`'siyle **aynı değil**; el değişimi takasa gömülü. Üç eksende
  farklı mesafeli küplerle ölçüldü.
- **Birim:** 1 Maya cm = 1 Unreal birimi. JSON kayıtları için
  `position_scale = mpu × 100` (Blender'da `× 1`).
- **Mesh yolu:** `InterchangeManager.import_scene` headless çalışıyor, Maya
  transform adlarını koruyor, hiyerarşiyi ve birimi kendisi getiriyor. Bizim
  tarafta mesh transform matematiği **yok** — çift uygulama olurdu.
- **Rotasyon:** ışık/kamera JSON'dan geldiği için dönüşüm bizim. Maya −Z'ye,
  Unreal +X'e bakar. Doğrulama döngüsel değil: beklenen Maya matrisinden
  hesaplandı, gerçek Unreal actor'üne soruldu → üç eksende **1e-8**.
- **Enerji:** yeni sabit icat edilmedi. Ölçülmüş π çapası → watt → lümen
  (×683). Kare birim terimi **metre** cinsinden; Unreal konumları santimetre,
  bu yüzden kodda iki ayrı ölçek var.

Üç tuzak ölçümle çıktı, üçü de yasak listesinde:

1. `ImportAssetParameters.import_level` bool değil **Level objesi**.
2. Rect light `LUMENS` isteğini sessizce **`CANDELAS`**'a çeviriyor, değeri
   çevirmiyor → yazıp geçmek 4π hata. Çözüm: geri oku, motorun kendi
   çarpanıyla çevir.
3. Light component property'leri setter istiyor. İlk sürüm çıplak
   `try/except` ile atıyordu, yazma başarısız oldu, exception yutuldu, **bütün
   ışıklar varsayılan 8 candela'da kaldı** — ve "intensity pozitif mi" diye
   soran test geçti. Ders ikili: setter kullan, ve testte *doğru* olduğunu sor.

Rig dersi bir kez daha, bu sefer testin kendisinde: düzeltmeden sonra assertion
yine düştü (10.2994 okundu, 0.214571 bekleniyordu — tam 48×). **Kod doğruydu,
testin elle yazılmış beklentisi yanlıştı**: fixture'ın alan ışığı intensity 12
+ exposure 2 = 48. Beklenti artık kaydın kendisinden türetiliyor, fizik ayrı
bir assertion'da elle hesaplanmış `π × mpu² × 683`'e karşı duruyor.

Materyal mimarisi ölçümle şekillendi: **blend mode ve shading model Material'e
ait, instance'a değil**, yani tek master cam + cutout + unlit içeren sahneyi
karşılayamaz. Yüzey sınıfı başına bir master (Opaque/Masked/Translucent/Unlit),
Python'dan üretiliyor (binary `.uasset` incelenemez ve her sürümde yeniden
kurulur). Opsiyonel texture'lar static switch yerine skaler lerp — permütasyon
yok.

`MaterialProperty` probe edildi: **coat ve sheen girdisi yok**. Metadata olarak
tutuluyor ve uyarı yazılıyor.

Durum: `tests/host/unreal_import_test.py` gerçek 5.8.1'de **24 assertion yeşil**
(uçtan uca import dahil). Sözleşme testi üçlü protokol eşitliğini, üç sürüm
numarasını (`.uplugin` dahil), eksen takasını, iki ölçeği, enerji zincirini ve
kanal kapsamını zorluyor; kanal kapsamı kontrolünün dişi negatif testle
doğrulandı. Kurulmuş artefakt gerçek bir projeye kurulup denendi (repo
`sys.path`'te değilken).

**Kapatılmayan, açıkça borç:**

- **Menü GUI'de doğrulanmadı.** Commandlet'te Slate yok, `find_menu` boş
  dönüyor; kod bunu algılıyor, logluyor ve Python'dan çalışmaya devam ediyor.
  `Tools > mLender`'ı gerçekten görmek insan işi.

## Render karşılaştırması — yapıldı, yarısı kapandı, yarısı rig'e çarptı

Kullanıcı istedi, çalıştırıldı. Rig `render_match_maya.py`'ın **aynı**
`arnold.exr`'ini kullanıyor; dört dosya `tests/calibration/render_match_unreal_*`.

**Kapanan:**

- **Lümen formülü tam.** `683 × π × 0.01² × 80 × 2¹ = 34.331325`, component'e
  ulaşan `34.331326` → **%0.000003**. Enerji zinciri uçtan uca doğrulandı.
- **Geometri, kamera, ışık yönü doğru.** Render edilmiş level'den okundu:
  zemin orijinde ±200, ışık `(0,0,-1)`, kamera forward'ı Maya'nın −14°'sini
  geri veriyor, ufuk geometrinin dediği yerde (%41.7 ölçülen / %42.6 hesap).

**Kapanmayan — ve sebebi rig:** oran ortalama **260×**, yayılım **%45**, ve
rig kendi **simetri kontrolünü geçemiyor**: sahne sol-sağ simetrik, Arnold
bunu beş hanede üretiyor, Unreal ikisini %14 farklı veriyor. Simetrik sahnenin
simetrik render edilmemesi "ölçtüğüm şey ışık değil rig" demektir — materyal
chart'ının iki kontrol hücresiyle aynı ders. Bu yüzden 260 **kalibrasyon
sabiti değil**. Ek iki sınır: GI cvar'ı scene capture'a geçmiyor (iki geçiş
birebir aynı), ve 260'ın içinde Unreal'in çözülmemiş scene-color ölçeği var.

**Yol üstünde üç şey öğrenildi:**

1. **Headless render'ın iki yolu kapalı.** Commandlet render komutlarını
   işletmiyor (kontrol: temizlenen target `(1,0,0)` okuyor,
   `export_render_target` dosya yazmıyor) ve **MRQ bu engine'de kurulu değil**.
   `-game` harita yükledi ama SM5 shader derlemesi 3746 CPU-s yedi.
   Çalışan yol: **editör + proje startup script'i + tick callback**.
   `-ExecutePythonScript` işe yaramıyor — script dönünce editör kapanıyor.
2. **Rig'de gerçek bir hata.** İlk tur üç zemin örneğini tam 0.0 verdi:
   **Blender'ın piksel dizisi alttan yukarı, Unreal'in render target'ı
   yukarıdan aşağı**. Blender formülü kopyalanınca kare dikey aynalandı ve
   örnekler gökyüzüne düştü. 12×12 ızgara + `BaseColor`/`Normal` geçişleri
   bunu bir turda gösterdi; tek patch'e bakıp "sahne siyah" demek yanlış
   sonuca götürecekti.
3. **Önceki oturumun bir iddiası çürütüldü.** "Rect light `LUMENS`'i sessizce
   `CANDELAS`'a çeviriyor" **yanlıştı**. Gerçek: `intensity` ve
   `intensity_units` Python'a read-only, atama **fırlatıyor**; okunan
   `CANDELAS` ışığın dokunulmamış varsayılanıydı (8.0 cd — CDO'nun dediği
   5000 UNITLESS değil). Setter ile üç ışık tipi de `LUMENS`'i koruyor.
   README, CLAUDE.md ve kalibrasyon belgesi düzeltildi; `apply_intensity`'nin
   geri-okuması koruma olarak kaldı, gerekçesi dürüstleştirildi.

## Render karşılaştırması, ikinci tur — hipotez çürütüldü, rig'in tavanı bulundu

Kullanıcı "yap bakalım" dedi; iki iş yapıldı ve ikisi de sonuç verdi.

**1. Çok kare biriktirme → "temporal gürültü" hipotezi çürütüldü.** 8 ayrı
kare, ayrı tick'lerde: **kare-kare yayılım %0.000**. Render deterministik,
gürültü yok. Asimetri gerçek ve kararlı.

**2. Simetri kontrolü assertion oldu.** Tolerans %2; düşünce karşılaştırma
hüküm vermeyi **reddediyor** ve exit 2 veriyor. Çalıştı: Arnold %0.0025,
Unreal %13.42 → "RIG NOT TRUSTWORTHY, no verdict".

**Ve asıl bulgu: capture hiçbir kontrole cevap vermiyor.** GI'ı kapatmanın üç
yolu denendi — console cvar, capture component'in `show_flag_settings`'i (16
flag, "16 of 16 accepted"), proje `DefaultEngine.ini` — ve üçü de sonucu
**bit-bit** değiştirmedi. Bütün turlarda aynı dört sayı:
`0.23611752 / 0.28615112 / 0.32732422 / 0.30765015`. Tutarlı tek okuma:
`capture_scene()` her çağrıda yeniden render etmiyor.

Sonuç: **SceneCapture2D Python'dan kontrol edilebilir bir ölçüm aracı değil.**
Değiştiremediğin bir render'da asimetrinin sebebi (Lumen? ekran-uzayı etki?)
elenmez ve "direct-only" iddia edilemez. Kalan tek yol MRQ + Path Tracer, ve
`MovieRenderPipelineCore` bu kurulumda yok. Bu, belgeye "bir sonraki tur aynı
duvara üç kez çarpmasın" diye yazıldı.

## Unreal parite turu (2.42.0) — yedi alan daha taşınıyor

Kullanıcı "hepsi taşınsın" dedi. Probe önce, tablo sonra: Unreal karşılıkları
ölçüldü, sonra yazıldı.

**Taşınanlar (host testinde assert'li):**

| alan | Unreal karşılığı | durum |
|---|---|---|
| locator / boş null | `Actor` (DefaultSceneRoot'lu), parent zinciriyle | 6/6 |
| NURBS/bezier eğri | üretilen Blueprint üstünde `SplineComponent` | **11/11 spline** |
| aiVolume (.vdb) | `SparseVolumeTexture` + `HeterogeneousVolume` | 1/1 |
| aiStandIn / gpuCache | `.abc` → `GeometryCache` + `GeometryCacheActor` | 4/4, 1 yüklü |
| particle instancer | nokta başına `StaticMeshActor`, mesh paylaşımlı | 1/1 |
| particle sistemi | çapa + instancer'a nokta kaynağı | 3/3 |
| selection set / display layer | **Unreal Layer** (tam karşılık) | çalışıyor |

`objects.py` ortak yerleştirmeyi tek yere koyuyor (spawn, matris, klasör, tag),
yoksa volume ile locator iki konvansiyona ayrılırdı.

**Ölçülen dört mimari gerçek:**

1. **Level actor'üne component eklenemiyor** — `add_component_by_class` bu
   build'de yok. Çözüm: bileşeni zaten taşıyan actor sınıfını spawn et
   (`GeometryCacheActor.geometry_cache_component`, `HeterogeneousVolume`) veya
   `SubobjectDataSubsystem` ile Blueprint üret. Eğriler ikinci yoldan geçiyor.
2. **Yeni Blueprint derlenmeden spawn edilemiyor** — `generated_class` yok ve
   spawn `None` dönüyor, sebep söylemeden. Önce derle, sonra `generated_class()`.
   Bu bulunmadan 11 eğrinin 11'i sessizce çapaya düşüyordu.
3. **Obje rotasyonu ışık rotasyonundan farklı** — ışık/kamera bakışını +X'e
   taşır; obje kendi eksen adlarını korur (`+X=S·mx, +Y=S·mz, +Z=S·my`). Her
   ekseni aynı ada eşlemek sol el çerçevesi, yani ayna verirdi.
4. **`positions` düz float listesi**, üçlü değil → doğrudan iterasyon
   `'float' object is not iterable`. Instancer bu yüzden 0 kuruyordu.

**Testin kendisi bir kez yanlıştı, yine:** "VDB sparse volume texture ekledi"
assertion'ı koşulsuzdu, ama fixture'ın `smoke.vdb`'si **diskte yok** ve çapa
doğru davranış. Artık dosya varsa yüklemeyi, yoksa çapalamayı şart koşuyor.

## Alembic cache (2.42.0) — kapandı, ve gerçek bir delikti

Kullanıcı "alembic cache de önemli" dedi; haklıydı ve düşündüğümden daha
önemliydi: export cache'lediğinde deforme meshler ve emitter parçacıklar FBX'e
**değil** `.abc`'ye gidiyor, yani import edilmezse o objeler level'da **hiç
yok**. Fixture'da 1 mesh + 1 particle tam bu durumdaydı.

`alembic.py`: `.abc` → `GeometryCache` → `GeometryCacheActor` (bileşeni zaten
taşıyor). Eksen/ölçek sorusunun cevabı motorda hazır çıktı:
`AbcConversionPreset.MAYA` = scale (1,−1,1), rotation (90,0,0), flip_v. Sayıları
elle yazmak yerine preset **adıyla** isteniyor (otorite tek kalsın), ama açıkça
set ediliyor — sürümler arası değişen varsayılan, aynı paketin farklı
görünmesinin yoludur. Cache dünya uzayında yazıldığı için actor orijinde:
transform uygulamak geometriyi iki kez taşırdı.

Ölçülen ayrıntı: `imported_object_paths` aynı asset'i **iki kez** bildiriyor,
tekilleştiriliyor. Cache mesh'i FBX'ten geçmediği için materyal eşleşmesine
girmiyor; slotlar Maya adlarını taşıdığından bizim materyallerimiz isimle
aranıyor, bulunmazsa uyarı.

Host testinde iki assertion: cache geldi mi, ve level'da cache taşıyan bir
`GeometryCacheActor` var mı. 38/38.

## Animasyonlu materyal parametreleri (2.47.0) — 1. kategoriden bir sessiz kayıp daha

Roadmap'in en üst kategorisindeki madde: "Zaman ekseninde yalnız ışık, kamera,
particle ve mesh görünürlüğü örnekleniyor. Anahtarlanmış bir roughness veya base
colour export karesinde donuyor." Ölçüldü — doğruydu, ve **bir adım daha
kötüydü**.

`sample_records` zaten `(kayıt, sampler)` çiftleri alıyordu, yani mekanizma
hazırdı; eksik olan materyal kanallarının o listeye girmesiydi.

**Ölçülen iki hata:**

1. **base_color kare 1'de donuyordu**, uyarısız. (Beklenen.)
2. **roughness texture'a bake ediliyordu**: `baked_from` animCurve node'unun
   kendisini gösteriyordu. Yani anahtarlanmış bir skaler, dosyası olmayan bir
   prosedürel sanılıp tek karesi haritaya basılıyordu — "kasıtlı görünen yanlış
   cevap". Upstream yürüyüşü artık animCurve'de duruyor.

**Compound tuzağı:** ilk sürüm roughness'ı buldu, base colour'ı **bulamadı**.
Maya renkleri çocuk plug'lardan anahtarlıyor (`baseColorR`, `baseColorB`) ve
compound "bağlantı yok" diyor. `plug_animated` artık çocuklara da bakıyor, ve
fixture'da ikisi de var — yalnız skaler koysaydım yarım çalışan hali geçerdi.

Blender soketleri doğrudan key'liyor, **LINEAR** (örnekler zaten
değerlendirilmiş eğri; Bezier iki kez ease ederdi). Doğrulama sayma değil
değerlendirme: kare 1'de roughness 0.05 / base (1, 0.8, 0), kare 25'te 0.9 /
(0, 0.8, 1).

Animasyon kapalıyken donma **artık sessiz değil**: kaç kanalın keyli olduğunu ve
hangi karede donduğunu yazıyor.

Yalnız gerçekten keyli kanallar örnekleniyor — görünürlükteki akıl yürütmenin
aynısı. Şema bump'ı yok: `samples` eklenen bir alan, geriye uyumlu, ve düz
`value` yanında duruyor (samples'ı yok sayan alıcı hala export karesini alıyor).

Unreal örnekleri alıyor ve kanal başına bildiriyor; orada animasyon Level
Sequence ister.

## Headless/batch export + preset (2.46.0) — roadmap maddesi 6, kapandı

Kullanıcının sırasındaki son madde. İki parça, tek cevap: UI'ın ayarları her
oturum elle yeniden kuruluyordu, ve batch export'a "sanatçının kullandığı
ayarlar" denemiyordu.

`presets.py` — ayarlar `export_scene`'in aldığı keyword argümanların **birebir
aynısı** artı çıktı klasörü ve LiveLink adresi. Maya tercihleri altında JSON.
Sahnede değil: ayarlar sahnenin ne olduğunu değil kişinin nasıl çalıştığını
anlatır, ve başkasının açtığı sahne gönderenin alışkanlıklarını taşımamalı.

`batch.py` — `--scene/--out/--preset/--send` + her export bayrağı. Üç katman,
sonraki kazanır: varsayılan → preset → komut satırı. **Adı geçmeyen bayrak
hiçbir şeyi sıfırlamıyor** (`None` = "söylenmedi"), yoksa `--out` vermek
diğerlerini varsayılana döndürürdü ve preset'in anlamı kalmazdı.

**Ölçüldü:** iki çağırma biçimi de `PYTHONPATH` olmadan çalışıyor. Düz script
olarak çalıştırınca relative import kırılıyordu (`attempted relative import with
no known parent package`); `__main__` bootstrap'ı paketi yola geri koyuyor —
farm işi `-m` yerine dosya yolunu yazıyor.

Preset round-trip gerçek Maya'da doğrulandı: kaydedilen preset (bake kapalı,
archive açık, 512) geri okundu ve `--out` verilmeden batch export'u sürdü —
arşiv yazıldı, bake sayısı 0.

Sözleşme testinde iki kural: bilinmeyen preset anahtarı **düşürülüyor** (yeni
build'in yazdığı preset eskisinde `export_scene`'e bilinmeyen argüman geçirip
export'u düşürmesin), ve bozuk JSON varsayılanlara düşüyor.

## Vertex colour / colorSet (2.45.0) — roadmap maddesi 3, kapandı

Ölçüm önce, ve iki ayrı şey olduğu ortaya çıktı:

- **Boya zaten geliyordu.** FBX renk setlerini taşıyor; Blender'da corner
  colour attribute olarak, Maya adlarıyla, ve **hepsi** — yalnız current olan
  değil.
- **Okuyan yoktu.** `aiUserDataColor` desteklenmeyen ağ sayılıyordu, yani bake
  kapalıyken kanal düz değere düşüyordu — renk için **siyah**. Ölçüldü:
  `value: [0,0,0]`, `unsupported_network: true`, ve **hiçbir uyarı yok**.

Şema 44: kanal okuduğu seti (`color_set`) kaydediyor, mesh taşıdığı setleri
(`color_sets`) kaydediyor. Blender **Color Attribute** node'u kuruyor ve
kanala bağlıyor.

**Fixture ismin önemli olduğunu kanıtlıyor:** küpte iki set var, shader
birincisini okuyor, ve Maya bilerek **ikincisi** current bırakılmış. "Current
olanı al" diyen bir alıcı yanlış rengi okur ve gayet makul görünür.

**Yolda iki hata daha:**

1. `plug_value` string'i **düşürüyor** (sayısal niçin yazılmış); ilk sürüm set
   adını `None` okuyup sessizce hiçbir şey bulmadı. `raw_attr_value` doğrusu.
2. **`unsupported_network` başından beri yazılıyor ve kimse okumuyormuş.**
   Exporter'ın ifade edemediği her ağ kanalı sessizce düz değerde bırakıyordu.
   Artık iki alıcı da adıyla bildiriyor. (Roadmap 1. bölümdeki "sessiz" madde.)

Unreal aynı kaydı alıyor ama master material'a vertex colour bağlamıyor — kanal
başına uyarı yazıyor.

## Uyarı okunabilirliği (2.44.0) — roadmap maddesi 4, kapandı

Kullanıcının kendi sırasında bekleyen madde ("pakete report.txt, N-panel'de
liste"). Yazıldığından daha değerli hale gelmişti: Unreal alıcısı fixture'da
**67 uyarı** üretiyor ve tek okuma yolu Output Log'du.

Üç rapor, hepsi **paket klasörünün içine**:

```text
mLender_01_report.txt          Maya ne gönderdi + uyarıları
mLender_01_import_blender.txt  Blender ne yaptı
mLender_01_import_unreal.txt   Unreal ne yaptı
```

Paket artık kendi hikayesini taşıyor: ne gönderildi, iki alıcı ne anladı.
Kullanıcıya "konsoldaki satırları kopyala" demek yerine tek dosya isteniyor.

Blender'da ayrıca N-panel'de **Last Import Warnings** alt paneli: ilk 25 uyarı
listeleniyor (yüzlerce satırlık panel UI'ı durdurur) ve bir buton raporu
açıyor. Uyarılar `ml_warnings` collection property'sinde duruyor, yani
import'tan sonra da okunabiliyor.

**Kural:** rapor hiçbir zaman asıl işi düşürmez. Paket klasörü salt okunur
olabilir (başkasının diski, ağ paylaşımı) ve iyi bir export'u log dosyası
yüzünden kaybetmek saçma olurdu.

**Yol üstünde bir tutarsızlık giderildi:** exporter'ın `BUILD_VERSION`'ı
`__init__.py`'deydi, importer'ınki `constants.py`'da. `package.py` raporu
yazarken sürümü gerektirdi ve kökü import edemezdi (döngü), o yüzden exporter'ın
ki de `constants.py`'a taşındı; `build_release.py` artık oradan okuyor.

## AOV'lar (2.43.0) — hiç çalıştırılmamış kod, ilk kez koştu ve iki hata verdi

Kullanıcı "AOV'lardan hangileri yok" diye sordu. Cevabı ararken asıl bulgu çıktı:
**AOV yolu iki tarafta da hiç test edilmemişti.** `tests/` içinde tek AOV
geçmiyordu, fixture 0 AOV üretiyordu. Yani exporter'daki ve importer'daki AOV
kodu bugüne kadar gerçek veriyle **bir kez bile çalışmamıştı**.

Fixture'a on bir `aiAOV` eklendi ve her biri **başka bir yere düşsün** diye
seçildi: Z, N, motionvector, crypto_object, emission, diffuse, specular
(eşleşen dallar), sss + opacity (eşleşmeyen yol), ve iki tuzak: **fuzz** ile
**albedo**.

**İki gerçek hata çıktı:**

1. **`"z" in name` çok gevşekti.** OpenPBR sheen'e **fuzz** diyor → içinde z var
   → sessizce derinlik pass'i açılıyor, sheen hiçbir yere gitmiyordu. Artık
   Arnold'ın `Z`'sine tam eşleşme. Negatif testle doğrulandı: eski substring
   geri konunca assertion düşüyor.
2. **Bare `albedo` diffuse direct+indirect açıyordu.** Albedo renk pass'idir;
   öbür ikisi kimsenin istemediği ışık taşıması.

**Bir tahmin de ölçümle düzeldi:** exporter Arnold'ın AOV `type`'ını ham int
kaydediyor ve yorumda `# 5=RGBA usually` yazıyordu. Canlı oturumdan okundu:
**4=FLOAT** (Z), **5=RGB** (çoğu), **6=RGBA** (tanınmayan adın varsayılanı),
**7=VECTOR** (N). Yani yorum yanlıştı.

**Üçüncü düzeltme:** eşleşmeyen AOV Blender'da custom slot oluyordu ve bu
**sessizdi**. Blender'da custom AOV'a shader yazmadıkça siyah render eder, yani
"pass geldi ama boş" — hiç gelmemesinden daha iyi saklanır. Artık uyarı
yazılıyor ve `cryptomatte_asset` de açılıyor (eskiden yalnız object+material).

Unreal tarafı değişmedi: render pass'ler orada MRQ konfigürasyonu ve MRQ bu
kurulumda yok — sayısıyla bildiriliyor.

## Skinli mesh / AS — kapandı, ve önceki turun teşhisi yanlışmış

Önceki turda "skinli meshler static geliyor, Interchange pipeline override'ı
gerekiyor, çekirdek yola dokunmak riskli" yazmıştım. **Yanlıştı**, ve ölçüm
bunu bir turda çürüttü. Hiçbir override olmadan, alıcının zaten kullandığı
çağrı:

```text
baseline assets = {'SkeletalMesh': 4, 'Skeleton': 4, 'PhysicsAsset': 4,
                   'StaticMesh': 47, 'AnimSequence': 1, ...}
```

Interchange skinli meshi **kendiliğinden** getiriyormuş. Hata benim
`imported_mesh_actors()`'ımdaydı: `isinstance(actor, StaticMeshActor)` ile
filtreliyordu, yani dört skeletal actor level'a giriyor ve **sahipsiz
bırakılıyordu** — kaydına eşleşmiyor, adlandırılmıyor, FBX'in placeholder
materyalini taşıyor.

Düzeltme küçüktü: mesh actor'ü static **veya** skeletal; bileşen
`static_mesh_component` ya da `skeletal_mesh_component`; slot sayısı
`get_num_materials()` (skeletal'da `static_materials` yok).

**Ders:** "çekirdek yola dokunmak riskli" diye ertelediğim iş, aslında
**dokunulmaması gereken** işti. Riski doğru tahmin ettim, sebebi yanlış.

**İki yanlış yol da ölçüldü ve ikisi de sessiz:**

1. `FbxImportUI.import_as_skeletal` → her statik küp tek kemikli skeletal mesh,
   **50 Skeleton**.
2. `override_pipelines`'a soft path → **kabul ediliyor**, `import_scene` True
   dönüyor, üretilen asset **{}**. Sonucu saymasaydım "çalıştı" diye yazacaktım.
   Ayrıca `auto_detect_mesh_type` 5.8'de deprecated.

`asrig.py` manifesti skeletal actor'lere `ml_as_*` tag'i olarak bağlıyor ve her
zinciri tek tek uyarıya yazıyor (start/middle/end + ik/pole/switch/blend), yani
bir sonraki tur manifesti yeniden çıkarmıyor.

**Kalan tek şey kontrol katmanı:** Unreal'de karşılığı **Control Rig** asset'i,
Python'dan üretmek rig grafiği kurmak demek — modül değil proje. Blender'daki
`asrig.py`'ın karşılığı ve tek başına bir tur.

**Taşınmayan dördü, gerekçesiyle** (hepsi sayısı ve sebebiyle uyarıya yazılıyor):
AS rigleri (FBX skinli mesh getiriyor ama bu build static mesh olarak import
ediyor, skeleton/control rig kurmuyor), skeleton root motion (sürecek armature
yok), Maya constraint'leri (Unreal'de karşılığı yok, hareketi FBX bake'i zaten
taşıyor), AOV'lar (Unreal'de render pass MRQ konfigürasyonu ve MRQ bu build'de
kurulu değil). Ayrıca ışık/kamera/görünürlük animasyonu (Level Sequence ister)
ve Alembic cache import edilmiyor.

## Mutlak parlaklık — kapandı, analitik fiziğe karşı

Kullanıcı "doğrulamak için rig yap" dedi. Kilit karar: referansı **Arnold'dan
analitik fiziğe çevirmek**. Arnold'ın piksel değerleri kendi keyfi ölçeğinde
olduğu için ona karşı bir oran zaten hiçbir zaman mutlak olamazdı — bir önceki
turun çözemediği şey buydu, ve daha fazla render tekniği denemek çözmezdi.

Rig `light_absolute_maya.py` + `light_absolute_unreal.py`. Arnold render'ı
kullanılmıyor. Beklenti kapalı formda, lümen değeri alıcının **kendi**
`light_intensity_for_unreal()`'inden, beklenti örneklenen bütün piksellerin
kendi d ve cosθ'sı üzerinden ortalanıyor.

**Rig'i güvenilir yapan geometri:** kamera tam tepeden dik aşağı → görüntü
dönel simetrik → sol/sağ ve üst/alt birer simetri kontrolü; ışık küçük (150
cm'de 20 cm) ve kameraya görünmez; yama 40×40 px. **Simetri %13.42'den %0.29'a
düştü**, yani önceki turun asimetrisi eğik kompozisyon + küçük yamaydı — rig
kusuru, transfer kusuru değil.

**Sonuç:** nokta kaynak yaklaşımının geçerli olduğu varyantlarda oran
**0.9529, yayılım %0.034**.

| varyant | oran | boyut/mesafe |
|---|---|---|
| 2× mesafe (300 cm) | 0.9532 | 0.067 |
| base (150 cm) | 0.9528 | 0.133 |
| 2× yoğunluk | 0.9528 | 0.133 |
| +1 stop | 0.9528 | 0.133 |
| yarım mesafe (75 cm) | 0.9070 | 0.267 |

Ters kare, doğrusallık ve `2^exposure` ayrı ayrı doğrulandı; +1 stop ile 2×
yoğunluk **birebir aynı** ölçümü verdi. Kalan %4.7 modelin nokta-kaynak
varsayımının: oran boyut/mesafe oranıyla birlikte hareket ediyor, yani ışık
yaklaştıkça beklenti bozuluyor. Pratik sonuç: `SCS_SCENE_COLOR_HDR` **nit**
cinsinden ve zincir mutlak doğru.

**İki tuzak kayda geçti, ikisi de "dönüş değerine bakmayan yazma" sınıfı:**

1. Tick callback **kendini çağırıyor** — `import_scene_package` Slate tick'i
   pompalıyor; ilk koşu 21 import derinliğine inip `RecursionError` ile editörü
   götürdü. Guard eklendi.
2. **Material Instance parametresi render'a ulaşmıyor** — albedo 0.4'e
   çekildi, geri okuma 0.4 dedi, setter `False` döndü, ölçülen piksel önceki
   albedoyla birebir aynı kaldı. Işık değişiklikleri aynı rig'de ulaşıyor.
   Albedo varyantı çıkarıldı ve sebebi dosyada yazılı; transfer hatası gibi
   okunan şey rig sınırıydı.

**Yolda gerçek bir ürün hatası çıktı ve düzeltildi.** Rig'i tekrar koşarken
import "2 mesh, **0 materyal**, 0 uyarı" dedi. Zincir: host testi aynı projede
koşup `/Game/mLender`'ı sildi → kaydedilmiş level'in actor'leri null mesh'e
düştü (`mesh_valid: false`) → `assign_materials` mesh yokken **boş liste
dönüyordu**, yani sessiz kayıp. Artık mesh'i olmayan actor uyarı yazıyor ve
düzeltmeyi söylüyor. Taze content root'ta aynı paket 2 materyal veriyor;
tetikleyici "silinen content root'a kaydedilmiş bir level referans veriyor".
Host testi bunu yakalamıyor çünkü untitled level'e import ediyor — koşul yok.
- Düzeltme node zincirleri ve `layeredTexture` grafiği kurulmuyor (uyarı
  yazılıyor, bake taşıyor). "Melez"in grafik yarısı burada eksik kalan kısım.
- UDIM, IES, dome HDR cubemap yok. Lookdev çekirdeği dışındaki her tip
  `_report_uncarried` ile sayısıyla bildiriliyor.

## Sıradakiler — kararlaştırılan sıra

Kullanıcı sırayı verdi: **2 → 7 → 4 → 3 → 6**. Numaralar bu oturumdaki
öneri listesinden; 2 yukarıda kapandı.

| # | iş | durum |
|---|---|---|
| 2 | UV set bağlantısı | **bitti** |
| 7 | `layeredTexture` (diğer ikisi zaten vardı) | **bitti** |
| 4 | Uyarıların okunabilirliği: pakete `report.txt`, N-panel'de liste | **bitti** (2.44.0) |
| 3 | Vertex colour / `colorSet` → Color Attribute node'u | **bitti** (2.45.0) |
| 6 | Headless/batch export girişi + ayar preset'i | **bitti** (2.46.0) |
| — | `aiStandIn` + `gpuCache` (sıra dışı, istendi) | **bitti** |

## layeredTexture — kapatıldı, ölçüldü

**Kapsam düzeltmesi:** "7" üç node olarak listelenmişti, ikisi (`aiMixShader`,
`aiLayerShader`) zaten vardı. Gerçek eksik `layeredTexture`'dı.

Bugünkü davranış ölçüldü: yığın atlanıyor, **alt katmanın dosyası** tüm kanal
sanılıyordu. Sessiz değildi (`unsupported_corrections`'a düşüyordu) ama
taşınmıyordu.

Ölçüm, her modu bake edip pikselleri okuyarak yapıldı — çünkü node batch'te
`getAttr` ile değerlendirilmiyor. Sonuç: desteklenen sekiz modun hepsi
`lerp(alt, f(alt, üst), alpha)` hesaplıyor, ki bu tam olarak Blender'ın Mix
node'unun Fac ile yaptığı şey. Alpha olduğu gibi geçiyor.

Alt katman siyaha karşı kompozit ediliyor (0.8 @ alpha 0.5 → 0.4, @ 0 → siyah),
o yüzden ona da Mix node'u veriliyor. Altı mod (`in`, `out`, `saturate`,
`desaturate`, `illuminate`, `cpv_modulate`) yaklaştırılmadan reddediliyor ve
uyarı yazılıyor. Sözleşme testi on dört modun üçe bölünmüş kümelerini
kapsıyor — yeni bir mod eklenip unutulursa test düşer.

**Rig dersi, bu sefer iki kere:**

1. `getAttr` ile okunan ilk tablo on dört modu **aynı** verdi. Ölü rig.
2. Bake ile alınan ikinci tablo da otuz dört satırın hepsini aynı verdi — ama
   bu ölü rig değil, sormadığım sorunun cevabıydı: **indeks 0 üst katman**.
   Üstte opak bir `Over` varken altındakinin modu görünmez.
3. Üçüncü tablo 0.8/0.4 ile alındı ve `Difference`, `Darken` ile "hiçbir şey
   yapmadı" aynı sayıyı verdi (0.4). Ayırt eden değerler (0.2 üstte 0.6)
   gerekti. Renkli bir çift de kanal-başına çalıştığını doğruladı.

Fixture adı yine çakıştı (`layerCube` mevcut `aiLayerShader` küpüydü) →
`layerTexCube`. Bu oturumda ikinci kez; yeni fixture eklerken önce ada bak.

---

Sıra dışında bırakılan iki büyük iş, gerekçesiyle: **rig** (skin + blendShape
→ armature; bugün Alembic cache, poz verilemiyor) ve **delta sync**. İkisi de
şema kırıyor, ayrı karar ister.

---

## 3. Eksik ama dürüst — uyarıyor, sessiz değil

| iş | not |
|---|---|
| Cubic ve Ball projeksiyonları | Ölçüldü, eşleşmedi, sebebi biliniyor: Cubic `fitType`/`fitFill` ile nesnenin sınır kutusuna bağlı, Ball yansıma küresi eşlemesi. Rig kurulu, u,v tablosu okunmuş. |
| `aiStandardHair` | Blender'da gerçek karşılığı var (Principled Hair BSDF). |
| `rampShader`'ın kalan rampaları | specularColor, reflectivity, environment — Principled'da rampa şeklinde soket yok. |
| `aiToon` | Karşılığı yok, yapılırsa yaklaşık olur. Değeri düşük. |

---

## 4. Kapalı veya ayrı karar

- **Redshift** — plugin bu makinede kurulu değil. Işık çapası (`10.0`) hâlâ
  devralınmış bir tahmin; motion blur ve volume attribute isimleri
  ölçülemiyor. Kurulursa açılır, yöntem `tests/docs/light_calibration.md`.
- **Rig** — ayrı değerlendirilecek. Alembic geldiği için skinli karakter
  bugün cache olarak geçiyor, ama poz verilemiyor.

---

## Hepsinin üstünde: gerçek sahne

Araç bugüne kadar **yalnız yazılmış fixture'ları** gördü. Bu oturumda şema
30'dan 36'ya, sürüm 2.11'den 2.23'e gitti ve materyal boru hattı blend
shader, rampa ve projeksiyon dalları aldı.

Bulunan her ciddi hata, akla gelmemiş bir şey test edildiği anda çıktı.
Gerçek bir sahne, tanımı gereği, akla gelmeyenlerin bulunduğu yerdir. Tek bir
gerçek sahneden gelen `mLender warning:` listesi, günlerce süren probe
turundan daha çok şey söyler.

Kullanıcının adımı kısa: Maya'da `ml.show_ui()` → gönder, Blender'da N-panel'de
`Build` numarasını doğrula, status satırını ve System Console'daki
`mLender warning:` satırlarını getir.
