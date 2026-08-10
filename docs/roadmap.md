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
