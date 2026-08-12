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
| NURBS yüzeyler | **ölçüldü, kayboluyor** | Keşif `ls(type="mesh")` ile başlıyor; NURBS yüzey mesh değil, FBX seçimine de girmiyor. Maya'da marjinal değil: ürün/endüstriyel modelleme ve eski asset'ler. |
| Maya subdiv yüzeyleri | **ölçüldü, kayboluyor** | Aynı sebep, aynı çözüm yolundan gider. |
| Animasyonlu materyal parametreleri | **ölçüldü, gitmiyor** | Zaman ekseninde yalnız ışık, kamera, particle ve mesh görünürlüğü örnekleniyor. Anahtarlanmış bir roughness veya base colour export karesinde donuyor. Görünürlükte aynı sınıf hata çıkmıştı. |
| Desteklenmeyen texture ağı uyarısı | **ölçüldü, sessiz** | `unsupported_network` exporter'da yazılıyor, importer'da hiç okunmuyor. Bake kapalıyken kanal düz değere çöküyor. `unsupported_corrections` zaten okunuyor; desen orada. Küçük iş. |

Ölçüm için:

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" -c "..."   # geom probe
```

NURBS için üç yol var, seçim önemlidir:

1. **FBX'e tessellate ettirmek** — trim'li yüzeyler dahil her şey doğru gelir,
   Blender'da poly olur. Önerilen.
2. **Blender'da yerel NURBS kurmak** — düzenlenebilir kalır ama trim'li
   yüzeyleri temsil edemez. Yarım çözüm.
3. **`nurbsToPoly` ile geçici mesh** — sahneyi değiştirir; CLAUDE.md bunu
   yasaklıyor, atomik temizlikle yapılabilir ama karmaşık.

FBX'in NURBS ayarının gerçek adı **probe edilmeden** tabloya yazılmamalıdır.

---

## 2. Envanter turu — yapıldı

Probe çalıştırıldı. Sonuçlar:

**Sessizce kayboluyordu** (artık uyarılıyor, aşağıya bak):
`fluidShape`, ışık filtreleri (`aiGobo`), `hairSystem` — ve daha önce ölçülen NURBS yüzeyler ile Maya subdiv yüzeyleri.

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
satırları — ikisi de API tavanının ötesinde.

## Sıradakiler — kararlaştırılan sıra

Kullanıcı sırayı verdi: **2 → 7 → 4 → 3 → 6**. Numaralar bu oturumdaki
öneri listesinden; 2 yukarıda kapandı.

| # | iş | durum |
|---|---|---|
| 2 | UV set bağlantısı | **bitti** |
| 7 | `layeredTexture` (diğer ikisi zaten vardı) | **bitti** |
| 4 | Uyarıların okunabilirliği: pakete `report.txt`, N-panel'de liste | bekliyor |
| 3 | Vertex colour / `colorSet` → Color Attribute node'u | bekliyor |
| 6 | Headless/batch export girişi + ayar preset'i | bekliyor |
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
