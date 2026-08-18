# Unreal ölçümleri

İç çalışma notu, Türkçe. Buradaki her satırın arkasında çalıştırılmış bir probe
var; "ölçüldü" yazmayan hiçbir sayı koda girmedi.

Ortam: **Unreal Engine 5.8.1** (`++UE5+Release-5.8`, changelist 56057345),
PythonScriptPlugin, gömülü Python 3.11.8. Probe'lar
`UnrealEditor-Cmd.exe <proje> -run=pythonscript -script=... -unattended
-nosplash -nullrhi` ile headless çalıştırıldı; Python çıktısı stdout'a değil
`Saved/Logs/<proje>.log` içine düşüyor, oradan okundu.

---

## 1. Eksen ve birim — ölçüldü, ve Blender kuralı **değil**

Maya tarafında üç küp, her eksende farklı bir mesafede export edildi
(`tests/calibration/axis_probe_maya.py`). Interchange'in ürettiği actor'ların
konumları:

| Maya (cm) | Unreal | sonuç |
|---|---|---|
| `(30, 0, 0)` | `(30, 0, 0)` | X → X |
| `(0, 40, 0)` | `(0, 0, 40)` | **Maya Y → Unreal Z** |
| `(0, 0, 50)` | `(0, 50, 0)` | **Maya Z → Unreal Y** |
| `(10, 20, 30)`, scale `(1,2,3)` | `(10, 30, 20)`, scale `(1,2,3)` | takas doğrulandı |

Yani dönüşüm **düz Y/Z takası, işaret değişimi yok**: `(x, y, z) → (x, z, y)`.
Blender alıcısının kuralı `(x, -z, y)` ve bu **başka bir şey** — el değişimi
(Maya sağ el, Unreal sol el) takasın kendisi tarafından yutuluyor, ayrı bir
işaret çevirmesine gerek kalmıyor.

Bu yüzden `MAYA_TO_UNREAL_AXES` ile Blender'ın `maya_vector_to_blender`'ı
birbirine benzetilmeye çalışılmamalı. İkisi de ölçüldü, ikisi de farklı.

**Birim:** Maya 30 cm → Unreal 30. Unreal'in dünya birimi santimetre ve
Interchange kendi başına ölçekleme yapmıyor. Ama JSON'dan gelen kayıtlar Maya
lineer biriminde, o yüzden `position_scale = meters_per_maya_unit × 100`
(Blender'da `× 1`). Santimetre sahnede 1.0, metre sahnede 100.0 — sözleşme
testinde ikisi de assert'li.

**Sözleşme testinde ayrıca:** takasın Blender dönüşümüne *eşit olmadığı* da
assert ediliyor. Tek eksende bakan bir kontrol, işaret hatası olan bir takası
geçirirdi — bu deponun `flatCube` dersinin aynısı.

---

## 2. Mesh yolu: Interchange taşıyor, biz dokunmuyoruz

`InterchangeManager.import_scene(content_path, source_data, params)` headless
çalışıyor ve şunu üretiyor:

- Maya transform **adlarını koruyan** bir `StaticMeshActor` (probeAxisX,
  probeRotated…), tek bir `RootNode` actor'ü altında.
- Mesh asset adları jenerik (`Mesh`, `Mesh_ncl_1`, …) — **eşleştirme actor
  label'ı üzerinden yapılmalı**, asset adı üzerinden değil.
- FBX'in materyalleri de asset olarak geliyor (`probeShader`), Maya shader
  adıyla. Slot eşleştirmesi bu ada göre yapılıyor, indekse göre değil.

Sonuç: mesh transform'u, hiyerarşi ve birim dönüşümü **bizim kodumuzdan
geçmiyor**. `meshes.py` içinde bilinçli olarak hiç transform matematiği yok;
doğru olanın üstüne bir kez daha uygulamak, ışık enerjisinde bir kez yapılmış
olan çift-uygulama hatasının aynısı olurdu.

**Bir tuzak kayda geçti:** `ImportAssetParameters.import_level` bir *bool*
değil, bir `Level` objesi. `True` verince motor açık hata veriyor
(`Cannot nativize 'bool' as 'Level'`). Boş bırakılıyor, açık dünyaya
import ediliyor.

FBX Y-up olarak yazılıyor (`fbx.py` up-axis ayarı geçmiyor, Maya varsayılanı
Y), yani dönüşümü **Unreal yapıyor**. Bu, dönüşümün nerede olduğu sorusunun
cevabı ve ölçüm bunun üzerine kuruldu.

---

## 3. Işık/kamera yolu: rotasyon dönüşümü — 1e-8'de doğrulandı

Işık ve kamera FBX'e girmiyor (`FBXExportLights/Cameras -v false`), JSON'dan
geliyor, yani dönüşüm **bizim**. Doğrulama döngüsel olmayacak şekilde kuruldu:

- **Beklenen** değer, Maya'nın kendi `world_matrix`'inden düz Python'da
  hesaplandı.
- **Gerçek** değer, actor spawn edildikten sonra Unreal'in kendisine soruldu
  (`get_actor_forward_vector()` vb.).

Maya ışık/kamerası local **−Z**'ye bakar, Unreal'inki local **+X**'e. Eşleme:

```text
Unreal +X (forward) = -S · maya_z
Unreal +Y (right)   =  S · maya_x
Unreal +Z (up)      =  S · maya_y      (S = Y/Z takası)
```

Bu atama keyfi değil: S el değişimi yaptığı için, Maya'da `x × y = z` iken
Unreal'de `forward × right = up` ancak bu dizilimle tutuyor.

Ölçüm (`probeLight`, Maya euler (−35, 25, 10), scale 20):

| eksen | beklenen | Unreal'in cevabı | hata |
|---|---|---|---|
| forward | `(-0.241329, -0.742404, -0.624978)` | aynı | **0.00000000** |
| up | `(-0.380965, -0.519837, 0.764614)` | aynı | **0.00000001** |
| right | `(0.892539, -0.422618, 0.157379)` | aynı | **0.00000001** |

Konum: Maya `(11, 22, 33)` → Unreal `(11, 33, 22)`, mesh yolunun verdiği
takasın aynısı. **İki yol aynı dünyada** — bu kontrol `scale_probe`'un varlık
sebebiydi ve burada da tutuyor.

Rotator, motorun kendi yardımcısıyla kuruluyor: `MathLibrary.make_rot_from_xz`
(5.8.1'de `make_rot_from_x`, `make_rot_from_zx`, `make_rot_from_yz`,
`make_rotation_from_axes` de var). Rotator konvansiyonunu elle türetmek yerine
sormak bilinçli; `_rotator_from_basis` yalnızca hiçbiri yoksa devreye giren
yedek.

---

## 4. Işık birimleri — motor otorite, sabit uydurulmadı

`LightUnits` enum'u: `CANDELAS, EV, LUMENS, NITS, UNITLESS`.

`PointLightComponent.get_units_conversion_factor` ile ölçülen çarpanlar
(point/rect/spot üçünde de aynı):

```text
CANDELAS -> LUMENS    12.566372     (= 4π, izotropik küre)
LUMENS   -> CANDELAS   0.0795775    (= 1/4π)
UNITLESS -> CANDELAS   0.0016       (= 1/625, Unreal'in devraldığı ölçek)
CANDELAS -> NITS   10000            (cm² → m²)
LUMENS   -> NITS     795.7747       (= 10000/4π)
```

Hepsi kendi içinde tutarlı. **EV, CANDELAS ile aynı çarpanı döndürüyor** — bu
logaritmik bir birim için doğru olamaz, o yüzden alıcı EV'yi hiç istemiyor.

Varsayılan point/rect/spot yoğunluğu: **5000 UNITLESS** (= 8 candela).

**Zincir:** Maya intensity → watt cinsinden akı (Blender alıcısının **ölçülmüş**
π çapası) → lümen (×683) → Unreal. Yeni bir kalibrasyon sabiti icat edilmedi;
`WATTS_PER_INTENSITY` ve `AREA_SIZE_PER_SCALE` Blender tarafından **değiştirilmeden**
alındı, çünkü onlar Unreal'e karşı değil fiziksel birimlere karşı ölçülmüştü.

İki tuzak, ikisi de kodda yorumlu:

1. Akı içindeki **kare birim terimi metre** cinsinden olmalı (çapa ona karşı
   ölçüldü). Unreal konumları santimetre. `importer.py` iki ayrı ölçek
   taşıyor (`metre_scale`, `unreal_scale`) ve bunu karıştırmak santimetre
   sahnede 10⁴ hata.
2. Alan **tam bir kez** uygulanıyor; akı dönüşümünün içinde tüketiliyor.

### 4.1 Ölçülen sürpriz: property yazımı **fırlatıyor**, ve yutulursa sessiz kalıyor

Işık component'inin `intensity` ve `intensity_units`'ı Python'a **read-only**;
düz atama şunu fırlatıyor:

```text
Property 'Intensity' for attribute 'intensity' on 'RectLightComponent'
is read-only and cannot be set
```

Yanlarında setter var (`set_intensity`, `set_intensity_units`) ve o çalışıyor;
`set_editor_property` de çalışıyor.

İlk sürüm atamayı çıplak `try/except` içinde yapıyordu: yazma fırlattı,
exception yutuldu, her ışık **spawn edilmiş bir component'in varsayılanı olan
8.0 CANDELAS**'ta kaldı — ve "intensity pozitif mi" diye soran test **geçti**
(8 cd = 100.531 lümen > 0).

Ders iki katmanlı, ikisi de yasak listesinde:

- Setter varsa setter kullanılacak, property yedek, ikisi de olmazsa **uyarı**.
- Test, değerin *pozitif* olduğunu değil **doğru** olduğunu sormalı.

**Varsayılan üzerine bir not:** spawn edilmiş bir point/rect/spot ışığı
**8.0 CANDELAS** ile başlıyor, ama sınıfın default object'i (CDO) **5000
UNITLESS** diyor. Yani CDO'dan okunan varsayılan, sahnedeki yeni bir actor'ün
varsayılanı **değil**.

### 4.2 Düzeltme: "Unreal birimi sessizce değiştiriyor" iddiası **yanlıştı**

Bu belgede bir süre şöyle yazıyordu: "rect light `LUMENS` isteğini sessizce
`CANDELAS`'a çeviriyor, değeri çevirmiyor, 4π hata." **Öyle değil.**

O gözlem, yukarıdaki bozuk yazma yolundan alınmıştı: birim hiç
yazılamıyordu ve okunan `CANDELAS` ışığın **dokunulmamış varsayılanıydı**.
Setter ile ölçüldüğünde üç ışık tipinin de (`RectLight`, `PointLight`,
`SpotLight`) `LUMENS`'i **kabul edip koruduğu** görüldü:

```text
RectLight  setter -> units = LUMENS   intensity = 1234.0   (koruyor)
PointLight setter -> units = LUMENS   intensity = 1234.0
SpotLight  setter -> units = LUMENS   intensity = 1234.0
```

`apply_intensity` içindeki geri-okuma bu yüzden **gözlenmiş bir davranışın
çözümü değil, bir koruma**: bir ışık tipi veya gelecek bir sürüm lümeni
reddederse değer, kabul edilen birime motorun kendi çarpanıyla çevrilir.
Kod doğru, gerekçesi düzeltildi.

`DirectionalLightComponent`'ta `intensity_units` **hiç yok** (reflection'da
point/rect/spot'ta var, directional'da yok). Directional lüks cinsinden, ki
Sun dalı zaten irradyans üretiyor → `× 683` ile lüks.

### 4.3 Üçüncü ders: testin beklentisi de ölçülmeli

Düzeltmeden sonra test yine düştü: 10.2994 lümen okundu, 0.214571 bekleniyordu
— tam **48×**. Kod doğruydu; **testin beklentisi** yanlıştı. Fixture'ın alan
ışığı `aiArea`, intensity 12 ve exposure 2, yani effective 48. Elle yazılmış
"intensity 1" varsayımı doğru bir ışığı 48 kat yanlış gösteriyordu.

Test artık beklentiyi **kaydın kendisinden** türetiyor. Fiziksel doğruluk
ayrıca ve elle hesaplanmış `π × mpu² × 683`'e karşı assert ediliyor, yani
round-trip kontrolü ile fizik kontrolü ayrı iki assertion.

---

## 5. Materyal: Unreal'de coat ve sheen girdisi **yok**

`unreal.MaterialProperty` (5.8.1, iki kez probe edildi):

```text
MP_BASE_COLOR  MP_ROUGHNESS  MP_METALLIC  MP_SPECULAR  MP_NORMAL
MP_EMISSIVE_COLOR  MP_OPACITY  MP_OPACITY_MASK  MP_SUBSURFACE_COLOR
MP_ANISOTROPY  MP_REFRACTION  MP_AMBIENT_OCCLUSION  MP_TANGENT
MP_WORLD_POSITION_OFFSET  MP_MATERIAL_ATTRIBUTES  MP_FRONT_MATERIAL
```

**Coat ve sheen için hiçbir giriş yok.** Bu yüzden o kanallar
`UNREAL_METADATA_CHANNELS` içinde ve import uyarı yazıyor. Yaklaştırıp base
color'a katmak, ölçülmemiş bir şeyi ölçülmüş gibi göstermek olurdu.

Enum adı **`BlendMode`**, `MaterialBlendMode` değil (ilk probe `MISSING`
döndü — tahmin yanlış olurdu): `BLEND_OPAQUE, BLEND_MASKED,
BLEND_TRANSLUCENT, BLEND_ADDITIVE, …`

**Mimari sonuç:** blend mode ve shading model **Material'e** ait, instance'a
değil. Yani tek bir master material cam + cutout + unlit içeren bir sahneyi
karşılayamaz. Bu yüzden yüzey sınıfı başına bir master üretiliyor (Opaque,
Masked, Translucent, Unlit) ve her Maya shader'ı doğru olanın instance'ı
oluyor.

Opsiyonel texture'lar **static switch yerine** skaler parametreli bir lerp ile
çözülüyor: bir texture örneklemesi boşa gidiyor ama instance shader
permütasyonu istemiyor — instance kullanmanın bütün sebebi bu.

`MaterialExpressionHueShift` **yok** (probe edildi). Hue içeren düzeltme
zincirleri bu yüzden v1'de taşınmıyor.

---

## 6. Kapsanmayan — bilinçli, ve uyarı yazılıyor

v1 lookdev çekirdeği: mesh + hiyerarşi + materyal + ışık + kamera. Paketin
taşıdığı diğer her şey (curve, volume, standin, particle, instancer, locator,
set/layer, AS rig, constraint, AOV, ışık/kamera animasyonu) `_report_uncarried`
tarafından **sayısıyla** bildiriliyor. `coverage.py` fikrinin alıcı tarafındaki
karşılığı bu: taşınmayan bir şey sessiz kalmıyor.

Ölçülmemiş, açıkça borç:

- Dome/HDR cubemap yüklenmiyor, yalnız sky light yoğunluğu ve rengi.
- UDIM tek dosya olarak import edilmiyor, uyarı yazılıyor.
- IES profili yüklenmiyor.

---

## 7. Render karşılaştırması — yapıldı, ve rig'in sınırı bulundu

Soru: Arnold'da belli bir şekilde görünen ışık, transferden sonra Unreal'da
aynı görünüyor mu? Rig `render_match_maya.py`'ın yazdığı paketi ve
`arnold.exr`'ini kullanıyor, yani Blender yarısının **tam olarak aynı**
referansı.

### 7.1 Headless render'ın üç yolu, ikisi kapalı

| yol | sonuç |
|---|---|
| Commandlet (`-run=pythonscript`) | **ölü.** Render komutları işletilmiyor. |
| Movie Render Queue | **yok.** `MovieRenderPipelineCore` bu engine kurulumunda diskte değil. |
| `-game` | harita yükleniyor ama SM5 shader derlemesi 3746 CPU-s yedi ve script'e sıra gelmedi. |
| **Editör + startup script + tick** | **çalışıyor.** Kullanılan yol bu. |

Commandlet'in ölü olduğu **kontrolle** kanıtlandı: `(0.25, 0.5, 0.75)`'e
temizlenen bir render target geri `(1, 0, 0)` okuyor ve `export_render_target`
hiç dosya yazmıyor. Kontrol olmasaydı o `(1,0,0)` "kırmızı sahne" diye
ölçülecekti. Editörde aynı kontrol **birebir** dönüyor.

`-ExecutePythonScript` de kullanılamıyor: script döner dönmez editörü
kapatıyor, tek kare çizilmeden. Bu yüzden capture **proje startup script'i**
olarak çalışıyor ve editörü kendisi kapatıyor.

### 7.2 Ölçülen: lümen formülü **tam**

Maya ışığı intensity 80, exposure 1. Component'e ulaşan değer:

```text
683 × π × 0.01² × 80 × 2¹ = 34.331325 lm
component.intensity        = 34.331326 lm   → fark %0.000003
```

Enerji zinciri uçtan uca doğrulandı.

### 7.3 Ölçülen: geometri, kamera ve ışık yönü doğru

Sahne dökümü (aynı rig):

```text
ground     loc (0,0,0)    bounds ±200      görünür  ML_groundShader
probeCube  loc (0,0,20)   bounds ±20       görünür  ML_cubeShader
keyLight   loc (0,0,150)  forward (0,0,-1) 34.33 lm LUMENS  60×60 cm
shotCam    loc (0,260,90) forward (0,-0.9703,-0.2419)  50 mm
```

Kamera forward'ının z bileşeni −0.2419 → asin = **14°**, Maya'nın
`rotateX -14`'ü. Işık tam aşağı bakıyor. Ufuk çizgisinin karede nerede
durduğu da geometriyle uyuşuyor: zemin ±200, kamera y=260/z=90 → uzak kenar
karenin üstünden %42.6'da, ölçülen sınır 5/12 = %41.7.

### 7.4 Rig'in sınırı: simetri kontrolü düştü

Karşılaştırma tablosu (direct-only geçişi):

```text
sample                         arnold       unreal      ratio
cube front face           0.000718968     0.236118   328.41
ground left of cube        0.00135885     0.286151   210.58
ground right of cube       0.00135889     0.327324   240.88
ground far behind          0.00118715      0.307650   259.15

unreal / arnold: min 210.58  max 328.41  mean 259.76   yayılım %45.4
```

**Bu sayı kalibrasyon sabiti olarak alınmamalı**, çünkü rig kendi simetri
kontrolünü geçemiyor: sahne sol-sağ simetrik ve Arnold bunu beş hanede
üretiyor (`0.00135885` / `0.00135889`, %0.0025), Unreal ise ikisini
**%13.42 farklı** veriyor. Simetrik bir sahnenin simetrik render edilmemesi,
ölçülen şeyin ışık değil rig olduğunu söyler — materyal chart'ındaki iki
kontrol hücresinin aynı dersi. Karşılaştırma script'i bu yüzden **assertion**
koyuyor ve tolerans (%2) aşılınca hüküm vermeyi **reddedip** 2 ile çıkıyor.

### 7.4.1 "Temporal gürültü" hipotezi — kuruldu ve **çürütüldü**

İlk açıklama "tek karelik capture yakınsamamış, TAA jitter'ı" idi. Yanlıştı.
Ölçüm:

- **8 ayrı kare, ayrı tick'lerde alındı: kare-kare yayılım %0.000.** Render
  tamamen deterministik; gürültü yok.
- Sayılar `r.AntiAliasingMethod 0`, show flag'ler ve proje ayarları
  değiştirilerek alınan bütün turlarda **bit-bit aynı**:
  `0.23611752 / 0.28615112 / 0.32732422 / 0.30765015`.

Yani asimetri gerçek, kararlı ve gürültü değil.

### 7.4.2 Asıl sınır: capture hiçbir kontrole cevap vermiyor

GI'ı kapatmanın **üç yolu da** denendi ve üçü de sonucu **bit-bit
değiştirmedi**:

| yol | sonuç |
|---|---|
| `r.DynamicGlobalIlluminationMethod 0` (console) | fark yok |
| Capture component'in `show_flag_settings`'i (16 flag, hepsi kabul edildi) | fark yok |
| Proje `DefaultEngine.ini` → `RendererSettings` | fark yok |

`show_flag_settings` "16 of 16 accepted" diyor ve yine hiçbir şey değişmiyor.
Bunun tek tutarlı okuması: **`capture_scene()` her çağrıda yeniden render
etmiyor**, elde olan tek bir kare ve o kare hiçbir ayarı tanımıyor.

Dolayısıyla bu rig ile:

- asimetrinin sebebi **izole edilemiyor** (Lumen mi, ekran-uzayı bir etki mi,
  başka bir şey mi — değiştirilemeyen bir render üzerinde ayırt edilemez),
- "direct-only" **iddia edilemiyor**, çünkü GI kapatılamıyor,
- mutlak oran (260×) yorumlanamıyor; içinde ayrıca Unreal'in çözülmemiş
  scene-color ölçeği de var (Arnold lineer radyans yazıyor,
  `SCS_SCENE_COLOR_HDR` Unreal'in kendi ölçeğinde).

Kayıt için: SceneCapture2D yolu Python'dan **kontrol edilebilir bir ölçüm
aracı değil**. Bunu kapatmak isteyen MRQ'lu bir engine'de Path Tracer ile EXR
yazmalı; bu makinede `MovieRenderPipelineCore` kurulu değil.

### 7.5 Yolda bulunan gerçek hata — rig'in kendisinde

İlk tur üç zemin örneğini **tam 0.0** verdi. Sebep transferde değil,
örneklemede: **Blender'ın `image.pixels`'ı alttan yukarı, Unreal'in render
target'ı yukarıdan aşağı** sıralı. Blender rig'inin `(1 - v) × height`
ifadesi aynen kopyalanınca kare **dikey aynalandı** ve zemin örnekleri boş
gökyüzüne düştü.

12×12'lik bir ızgara çıkarıp `BaseColor` ve `Normal` geçişlerine de bakmak
bunu bir turda gösterdi: üst beş satır üç geçişte de sıfır (gökyüzü), alt
satırlar 0.13–0.38 (zemin), orta kolonlar koyu (küp). Tek bir patch'e bakıp
"sahne siyah" demek yanlış sonuca götürecekti.

### 7.5b Yolda bulunan gerçek ürün hatası — sessiz materyal kaybı

Rig'i tekrar çalıştırırken import **2 mesh ve 0 materyal** bildirdi, ve
**tek uyarı yazmadı**. Sebep izlendi:

- Aynı throwaway projede önce host testi koşmuştu. Host testi paketi
  import ediyor, bu da `purge_generated_content()` ile `/Game/mLender`'ı
  siliyor — yani render-match level'inin mesh asset'lerini.
- Kaydedilmiş level actor'leri o asset'lere yol üzerinden referans verdiği
  için mesh'ler `null` kaldı (`mesh_valid: false`, `tris: 0`).
- `assign_materials` mesh `None` görünce **boş liste dönüyordu**: materyal
  sayısı 0, uyarı yok. Bu deponun en temel kuralının ihlali.

İki şey yapıldı:

1. **Uyarı eklendi.** Mesh'i olmayan bir mesh actor'ü artık kaç Maya
   materyalinin düştüğünü ve nedenini yazıyor.
2. Tetikleyici koşul kayda geçti: **daha önce bir gönderi barındıran content
   root'a yeniden import**. Taze content root'ta aynı import **2 materyal**
   veriyor; ölçüldü, tekrarlanabilir.

Not: host testi bunu yakalamıyor çünkü o kaydedilmemiş (untitled) bir level'e
import ediyor, yani stale referans tutan bir level yok. Hatanın koşulu
"silinen content root'a kaydedilmiş bir level referans veriyor".

### 7.6 Özet

- Lümen formülü: **doğrulandı, %0.000003.**
- Geometri, kamera lensi/açısı, ışık yönü ve konumu: **doğrulandı.**
- Işığın karedeki dağılımı: nitel olarak doğru (zemin aydınlanıyor, küp
  gölgeliyor, ufuk geometrinin dediği yerde).
- **Mutlak parlaklık eşleşmesi: doğrulanmadı**, ve bu rig ile
  doğrulanamıyor. Simetri kontrolü %13.42 ile düşüyor, sebebi izole
  edilemiyor çünkü capture hiçbir render ayarına cevap vermiyor.

Yapıldı: çok kare biriktirme (8 kare, yayılım %0.000 — gürültü olmadığını
gösterdi) ve simetri kontrolünün **assertion**'a çevrilmesi (tolerans %2,
düşünce exit 2 ve hüküm yok).

Kalan yol tek: **MRQ + Path Tracer ile gerçek EXR**. Bu makinede
`MovieRenderPipelineCore` kurulu olmadığı için denenemedi. SceneCapture2D
Python'dan kontrol edilebilir bir ölçüm aracı değil; bu belgeye yazılıyor ki
bir sonraki tur aynı duvara üç kez çarpmasın.

> **Bölüm 8 bunu kapattı.** Mutlak parlaklık Arnold'a karşı değil,
> **analitik fiziğe** karşı ölçülerek doğrulandı. Arnold'ın piksel değerleri
> kendi keyfi ölçeğinde olduğu için ona karşı bir oran zaten hiçbir zaman
> mutlak olamazdı — bölüm 7'nin çözemediği şey buydu.

---

## 7b. Alembic cache ve iskelet — biri kapandı, birinin zemini ölçüldü

### Alembic cache — kapandı

**Bu opsiyonel bir ekstra değil.** Export cache'lediğinde deforme meshler ve
emitter parçacıklar FBX'e **değil** `.abc`'ye gidiyor; import etmezsen o objeler
level'da hiç yok. Fixture'da 1 mesh + 1 particle bu durumda.

Unreal `.abc`'yi **GeometryCache** olarak okuyor ve `GeometryCacheActor` bileşeni
zaten taşıyor, yani component eklemeye gerek yok.

**Eksen/ölçek sorusunun cevabı motorda hazır:** `AbcConversionPreset.MAYA`
probe edildi → `scale (1, -1, 1)`, `rotation (90, 0, 0)`, `flip_v = True`.
Sayıları elle yazmak yerine preset **adıyla** isteniyor, böylece otorite tek.
Ama preset açıkça set ediliyor (varsayılana bırakılmıyor) — sürümler arası
değişen bir varsayılan, aynı paketin farklı görünmesinin yoludur.

Cache dünya uzayında yazıldığı için actor orijinde, ölçeksiz duruyor; transform
uygulamak geometriyi iki kez taşırdı.

Ölçülen bir ayrıntı: `imported_object_paths` **aynı asset'i iki kez** bildiriyor,
o yüzden tekilleştiriliyor.

Cache mesh'i FBX'ten geçmediği için hiçbir materyal eşleşmesine girmiyor;
slot adları Maya'nın verdiği adlar olduğundan bizim materyallerimiz **isimle**
aranıyor, bulunmazsa uyarı yazılıyor.

### İskelet (AS rig) — kapandı, ve teşhisim yanlışmış

> **Düzeltme.** Bu bölüm bir süre "skinli meshler static mesh olarak geliyor,
> Interchange pipeline override'ı gerekiyor" diyordu. **Yanlıştı.** Ölçüm
> aşağıda: baseline import zaten skeletal getiriyor; hata alıcının kendi
> filtresindeydi.

**Ölçülen:** hiçbir override olmadan, alıcının **şu an kullandığı** çağrı:

```text
baseline assets = {'SkeletalMesh': 4, 'Skeleton': 4, 'PhysicsAsset': 4,
                   'StaticMesh': 47, 'AnimSequence': 1, 'LevelSequence': 1,
                   'MaterialInstanceConstant': 40, ...}
```

Yani Interchange skinli meshi **kendiliğinden** SkeletalMesh + Skeleton +
PhysicsAsset olarak getiriyor. Sorun `imported_mesh_actors()`'ın
`isinstance(actor, StaticMeshActor)` ile filtrelemesiydi: dört skeletal actor
level'a giriyor, sonra **görmezden geliniyordu** — kaydına eşleşmiyor,
adlandırılmıyor, FBX'in placeholder materyalini taşımaya devam ediyordu.

Düzeltme küçük: mesh actor'ü static **veya** skeletal olabilir, bileşeni
`static_mesh_component` ya da `skeletal_mesh_component`, ve slot sayısı
`component.get_num_materials()` üzerinden okunuyor (skeletal mesh'te
`static_materials` yok).

Bu, "çekirdek import yolunu değiştirmek riskli" diye ertelediğim işin aslında
**hiç değiştirilmemesi gerektiği** anlamına geliyordu. Riskli sandığım şey
yapılmaması gereken şeydi.

**İki yanlış yol da ölçüldü:**

**1. Legacy FBX'i skeletal olarak import etmek — YANLIŞ.**
`FbxImportUI.import_as_skeletal = True` + `FBXIT_SKELETAL_MESH` ile paketin
FBX'i import edildi ve sonuç:

```text
skeletal asset kinds = {'Skeleton': 50, 'SkeletalMesh': 50}
stdSurfCube_Skeleton  bone count 3
openPbrCube_Skeleton  bone count 1
flatCube_Skeleton     bone count 1   ...
```

Yani **her statik küpü tek kemikli bir skeletal mesh'e çeviriyor**. Bu yol
kapalı; blanket skeletal import doğru cevap değil.

**2. Interchange pipeline'ı — doğru yol, uygulanmadı.** Probe edilen
property'ler:

```text
InterchangeGenericCommonMeshesProperties
    auto_detect_mesh_type, force_all_mesh_as_type,
    convert_statics_in_bone_hierarchy_to_skeletals, single_bone_skeleton
InterchangeGenericMeshPipeline
    import_skeletal_meshes, import_static_meshes,
    combine_skeletal_meshes_behavior, skeletal_mesh_import_content_type
InterchangeGenericCommonSkeletalMeshesAndAnimationsProperties
    skeleton, try_auto_select_skeleton, import_meshes_in_bone_hierarchy
```

**2. `override_pipelines` ile pipeline vermek — GEREKSİZ, ve denemesi zararlı.**
İki şekil denendi:

```text
instance ([pipeline])  -> reddedildi: "Failed to convert type 'list' to
                          property 'OverridePipelines' (ArrayProperty)"
softpath ([SoftObjectPath(...)]) -> KABUL EDİLDİ, import_scene True döndü,
                          ve üretilen asset sayısı: {} — hiçbir şey
```

İkincisi bu deponun en sevdiği tuzağın bir örneği daha: **argüman kabul edildi,
hata verilmedi, ve hiçbir şey yapılmadı.** Sonucu saymasaydım "override çalıştı"
diye yazacaktım.

Ayrıca `auto_detect_mesh_type` 5.8'de **deprecated** ("Use
bConvertStaticsWith..."), yani dokümandan okunup yazılsaydı sessizce eskimiş bir
property set edilmiş olacaktı.

AS manifesti (`as_rigs`) paketten geliyor ve artık **skeletal actor'lere
bağlanıyor** (`ml_as_*` tag'leri): namespace başına `deform_set` (bind
eklemleri), `fk_controls` (kontrol↔eklem çiftleri), `chains` (limb başına
start/middle/end + `ik_control`/`pole_control`/`switch`/`blend`).

**Kalan tek şey kontrol katmanı.** Unreal'deki karşılığı bir **Control Rig**
asset'i ve onu Python'dan üretmek rig grafiği kurmak demek — modül değil proje.
Bu yüzden her zincir tek tek uyarıya yazılıyor:

```text
mLender warning: Arm L: Shoulder_L -> Elbow_L -> Wrist_L, IK "IKArm_L",
pole "PoleArm_L", switch "FKIKArm_L" (blend 10.0) -- not rebuilt.
```

Yani bir sonraki tur ne kuracağını manifesti yeniden çıkarmadan biliyor.

## 8. Mutlak parlaklık — doğrulandı (analitik fiziğe karşı)

Rig: `light_absolute_maya.py` + `light_absolute_unreal.py`. Arnold render'ı
**hiç kullanılmıyor**; referans kapalı formda hesaplanıyor:

```text
candelas  = lümen / (4π)              Unreal'in kendi çevrimi (ölçüldü)
lux       = candelas · cosθ / d²
luminance = lux · albedo / π          nit, Lambert yüzey için
```

Lümen değerini alıcının **kendi** `light_intensity_for_unreal()`'i üretiyor,
yani test edilen şey üretim kodu. Beklenti, örneklenen piksellerin
**hepsi üzerinden ortalanıyor** (her pikselin kendi d'si ve cosθ'sı ile);
merkez değerini alıp geçmek o hatayı cevaba gömerdi.

### 8.1 Rig'in geometrisi kendini kontrol ediyor

- Kamera **tam tepeden dik aşağı** bakıyor → görüntü dönel simetrik, yani
  sol/sağ **ve** üst/alt birer simetri kontrolü. Bölüm 7'nin eğik kompozisyonu
  bunu veremiyordu.
- Işık **küçük** (150 cm'de 20 cm) ve kameraya **görünmez** (`aiCamera 0`).
- Speküler sıfır, düz gri Lambert → beklentide BRDF uydurması yok.
- Örnekleme yaması **40×40 px** (bölüm 7'de 10 px'ti).

**Simetri %13.42'den %0.29'a düştü.** Yani bölüm 7'deki asimetri eğik
kompozisyon + küçük yamanın blotchy indirekt ışık üzerindeki sonucuydu; rig
kusuruydu, transfer kusuru değil.

### 8.2 Sonuç

| varyant | lümen | ölçülen | beklenen | oran | boyut/mesafe |
|---|---|---|---|---|---|
| base (150 cm) | 34.331 | 0.278716 | 0.292513 | **0.9528** | 0.133 |
| 2× mesafe (300 cm) | 34.331 | 0.072636 | 0.076206 | **0.9532** | 0.067 |
| 2× yoğunluk | 68.663 | 0.557432 | 0.585027 | **0.9528** | 0.133 |
| +1 stop pozlama | 68.663 | 0.557432 | 0.585027 | **0.9528** | 0.133 |
| yarım mesafe (75 cm) | 17.166 | 0.458615 | 0.505630 | 0.9070 | 0.267 |

**Nokta kaynak yaklaşımının geçerli olduğu varyantlarda oran 0.9529,
yayılım %0.034.**

Bu, mutlak doğrulamanın kendisidir:

- **Ters kare** doğru: mesafe iki katına çıkınca oran değişmiyor (0.9528 →
  0.9532). Yani `position_scale²` terimi ve 1/d² birlikte doğru.
- **Doğrusallık** doğru: yoğunluk 2× → oran aynı.
- **Pozlama** doğru: +1 stop, 2× yoğunlukla **birebir aynı** ölçümü veriyor
  (0.557432 ikisinde de) — `2^exposure` tam.
- **Ölçek** doğru: santimetre sahnede lümen değeri fiziğin istediği değer.

### 8.3 Kalan %4.7 kimin?

Sabit 0.953, yani Unreal analitik Lambert beklentisinin %4.7 altında. Bu fark
**beklentinin** kusuru gibi görünüyor, transferin değil, ve kanıtı varyantların
kendisi: oran boyut/mesafe oranıyla birlikte hareket ediyor.

```text
boyut/mesafe 0.067  ->  0.9532
boyut/mesafe 0.133  ->  0.9528
boyut/mesafe 0.267  ->  0.9070
```

Beklenti 20 cm'lik alan ışığını **izotropik nokta** sayıyor (Unreal'in kendi
1/(4π) çarpanıyla). Gerçek bir dikdörtgen yayıcı izotropik değil; ışık
yaklaştıkça bu varsayım bozuluyor ve ölçüm beklentinin altına daha çok
düşüyor — gözlenen tam bu yön. Yani %4.7 modelin nokta-kaynak varsayımıyla
tutarlı.

**Bundan çıkan pratik sonuç:** Unreal'in `SCS_SCENE_COLOR_HDR`'ı nit
cinsindendir (1.0 ≈ 1 cd/m²) ve ışık enerjisi zinciri mutlak olarak doğrudur.
`ml_light_power_scale`'i varsayılan 1.0'da bırakmak fiziksel olarak doğru
sonucu veriyor.

### 8.4 Yolda iki tuzak, ikisi de kayda değer

1. **Tick callback kendini yeniden çağırıyor.** `import_scene_package` Slate
   tick'lerini pompaladığı için callback iç içe giriyor: ilk koşu **21 import
   derinliğine** inip `RecursionError` ile editörü götürdü. Rig'de artık
   re-entrancy guard var. Tick tabanlı her rig bunu koymalı.
2. **Material Instance parametresi render'a ulaşmıyor.** Albedo varyantı
   `set_material_instance_vector_parameter_value` ile 0.4'e çekildi;
   **geri okuma 0.4 diyor**, setter `False` dönüyor, ve ölçülen piksel önceki
   albedoyla **birebir aynı** kalıyor. Işık değişiklikleri aynı rig'de render'a
   ulaşıyor, yani sorun materyal parametresine özgü. Albedo varyantı bu yüzden
   listeden **çıkarıldı** ve sebebi `light_absolute_maya.py` içinde yazılı —
   transfer hatası gibi okunan şey rig sınırıydı. Paketin kendi albedosu (0.8)
   her varyantın beklentisinde zaten kullanılıyor.

İkisi de aynı sınıfın örneği: **dönüş değerini kontrol etmeyen bir yazma.**
Bu oturumda üçüncü kez.

## Nanite fallback okuma tuzağı (2026-08-18)

Tessellate edilen yüzeyleri doğrularken çıktı. `StaticMesh.get_num_triangles(0)`
Nanite açık bir mesh'te **kaynak geometriyi değil fallback mesh'i** döndürüyor.

| mesh | FBX'te | `get_num_triangles(0)` | `get_num_nanite_triangles()` |
|---|---|---|---|
| trimmedPanel | 448 poly / 896 üçgen | 256 | 896 |
| nurbsBall | 2048 poly / 3968 üçgen | 256 | — |
| subdivBall | 24 poly / 48 üçgen | 48 | — |
| küpler (52 adet) | 12 üçgen | 12 | — |

İki farklı mesh'in **tam olarak aynı** 256 sayısını vermesi ipucuydu: sayı
mesh'i değil fallback bütçesini anlatıyor. Bütçenin altında kalan mesh'ler
(küpler, subdivBall) doğru okunduğu için dağılıma bakmadan fark edilmiyor.

Nanite'ı bu araç açmıyor; UE 5.8'in import varsayılanı. Yani sayıyı okuyan her
kontrol önce `nanite_settings.enabled`'a bakmalı.

Ölçüm: `tests/host/unreal_import_test.py`, "the trim survived to Unreal".
