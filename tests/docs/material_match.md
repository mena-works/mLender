# Materyal render eşleşmesi

Işık kalibrasyonu (`light_calibration.md`) nötr beyaz materyal kullanır, çünkü
işi ışığı izole etmektir. Bu belge diğer yarısıdır: sabit nötr ışık, değişen
materyal.

## Bu rig neyi yanıtlar, neyi yanıtlamaz

Arnold'ın `standard_surface`'ı ile Blender'ın Principled'ı **farklı BRDF'ler**.
Birebir piksel eşleşmesi beklenmiyor ve yüzde birkaçlık fark hiçbir şey ifade
etmiyor.

Yakaladığı şey **aktarım hatası**: hiç ulaşmamış bir kanal, ters çevrilmiş bir
değer, yanlış sokete düşmüş bir ağırlık. Bunlar gürültü olarak değil, büyük ve
yapısal sapma olarak görünür.

## Yöntem

Kamera ortografik, ışık **sabit renkli bir dome**, yüzeyler düz quad'lar.
Sıyırma açısı istendiğinde **kamera** eğilir, quad'lar değil.

İki renderer da doğrudan aydınlatma (GI kapalı), lineer EXR, `Standard` view
transform.

## Eşleşmek yeterli değil

Bir kanal iki tarafta da sessizce sıfırsa tablo yine "eşleşti" der. Bu yüzden
şüphelenilen her kanal için **tek o kanalda farklılaşan bir çift** var. Çiftin
Arnold'da ayrışıp Blender'da ayrışmaması, kanalın aktarımda kaybolduğu
anlamına gelir.

## Enstrüman önce kendini kanıtlar: kontrol hücreleri

Chart'ın sonunda iki **kontrol** hücresi var; her biri sıranın ortasındaki bir
hücrenin birebir kopyası. Konumdan başka hiçbir şeyleri farklı değil, dolayısı
ile **aynı okumak zorundalar**. Ayrışırlarsa rig materyali değil kendi
geometrisini ölçüyordur ve tablodaki hiçbir satıra güvenilemez; Blender tarafı
bu durumda hata koduyla çıkar.

Bu kontroller eklendiği anda rig'in üç ayrı kusurunu ortaya çıkardı. Üçü de
sessizdi — tablo makul görünmeye devam ediyordu:

1. **Işık homojen değildi.** 60 birim uzakta sonlu bir quad ışık vardı, sıra
   ise 200 birimden genişti. Uçtaki hücreler ışığın çok azını görüyordu: aynı
   materyali taşıyan iki quad **%36** farklı okundu, bir coat hücresi yalnızca
   sıra boyunca kaydırıldığı için **53 kat** değişti. Sabit bir dome her
   konumda aynı ışınımı verir; kontroller o değişiklikten sonra tam sıfır
   fark verdi.

2. **En-boy oranı tam sayı değildi.** Genişlik sabit 1024 alınıp hücre
   sayısına bölününce yükseklik kırpılıyor, gerçek en-boy bildirilen değerden
   sapıyordu. Merkezde önemsiz, sıranın ucunda ~8 piksel kayma. Artık genişlik
   yükseklikten türetiliyor (`chart_size`), oran tam.

3. **Eğik quad'lar birbirini gölgeliyordu.** Sıyırma açısı için her quad
   döndürülüyordu; bu onları ortak düzlemden çıkarıyor ve dome altında komşular
   birbirinin gökyüzünü kapatıyordu. Sıranın ucundaki hücrenin bir yanı açık
   kaldığı için kendi ikizinden %12 parlak geliyordu. Artık **kamera** eğiliyor,
   quad'lar eş düzlemde kalıyor. Kamera ayrıca sıranın yarısı kadar geri
   çekiliyor, yoksa 45°'nin ötesinde sıranın bir ucu kameranın arkasına
   düşüp kırpılıyor.

Ders: **enstrümanı önce kendi üstünde sına.** Bu rig üç tur boyunca yanlış
sayı üretti ve hiçbiri tabloya bakarak fark edilebilir değildi.

## Sonuç: aiStandardSurface, dik geliş

```text
hucre            arnold      blender    oran
grey_diffuse     0.5000      0.5000     1.0000
dark_diffuse     0.1800      0.1800     1.0000
red_diffuse      0.8000 R    0.8000 R   1.0000
spec_off         0.3000      0.3000     1.0000
spec_on          0.3280      0.3280     1.0000
spec_rough       0.3235      0.3239     1.0014
metal_off        0.9000      0.9000     1.0000
metal_on         0.8981      0.8993     1.0014
metal_spec       0.8994      0.8998     1.0004
coat_off         0.3000      0.3000     1.0000
coat_on          0.3280      0.3280     1.0000
sheen_off        0.3000      0.3000     1.0000
sheen_on         0.3262      0.3006     0.9213
emission_off     0.3000      0.3000     1.0000
emission_on      0.7000      0.7000     1.0000
emission_hdr     4.3000      4.3000     1.0000
opacity_full     0.8000      0.8000     1.0000
opacity_half     0.9000      0.9000     1.0000
control_diffuse  0.5000      0.5000     1.0000
control_coat     0.3280      0.3280     1.0000
```

Sheen dışında her hücre **%0.2 içinde**. Dome, eski rig'in eksik bulunan
dinamik aralığını da genişletti: okumalar artık 1e-4 civarında değil,
albedonun kendisinde.

## Sonuç: aiOpenPBRSurface, dik geliş

```text
hucre            arnold      blender    oran
metal_off        0.9000      0.9000     1.0000
metal_on         0.0000      0.8988     sonsuz
metal_spec       0.8919      0.8999     1.0090
coat_off         0.3000      0.3000     1.0000
coat_on          0.1765      0.3373     1.9112
coat_nodark      0.3373      0.3373     1.0000
emission_on      0.3400      0.3400     1.0000
emission_hdr     0.7000      0.7000     1.0000
opacity_half     0.9000      0.9000     1.0000
```

## OpenPBR'ın metali `specularWeight`'e bağlı

`metal_on` uzun süre açıklanamamış bir fark olarak durdu. Chart'ın tabanında
`specular = 0` var ve `metal_on` onu miras alıyordu. Yalnız bu ağırlıkta
farklılaşan bir eş eklendi (`metal_spec`) ve soru tek koşuda kapandı:

```text
                specularWeight   arnold    blender    oran
metal_on              0.0        0.0000    0.8988     sonsuz
metal_spec            1.0        0.8919    0.8999     1.0090
```

OpenPBR'da `baseMetalness = 1` iken `specularWeight = 0` yüzeyi **tamamen
siyah** bırakıyor: metal lobu ağırlığa bağlı, difüz ise metalness tarafından
zaten kaldırılmış. `aiStandardSurface`'ta böyle değil — orada aynı hücre
0.8981 okuyor.

Principled'ın metali `Specular IOR Level`'a bu şekilde bağlı olmadığı için
Blender iki durumda da parlak metal gösteriyordu.

### Ölçüm ve düzeltme

Ağırlıkta **tam doğrusal** (taban 0.9, metalness 1):

```text
specularWeight   0.00     0.25     0.50     0.75     1.00
arnold           0.0000   0.2231   0.4460   0.6690   0.8919
```

Her adımda eğim 0.892. Metalness ile birlikte tarandığında
(`specularWeight = 0`):

```text
metalness        0.00     0.25     0.50     0.75     1.00
arnold           0.9000   0.6750   0.4500   0.2250   0.0000
```

Bu tam olarak `base·(1 − m)`. İkisi birleşince:

```text
f = 1 − metalness · (1 − specularWeight)
```

Beş metalness ve beş ağırlık değerinin hepsinde birebir. Varsayılan ağırlık
1.0'da `f = 1`, yani hiçbir şeye dokunulmuyor.

Importer bu çarpanı base colour'a uyguluyor. Kayıt exporter'da
`OPENPBR_SPECULAR_SEMANTIC` ile işaretleniyor, çünkü `aiStandardSurface` aynı
şeyi yapmıyor ve fark kanalın kendisiyle taşınmalı.

Düzeltmeden sonra:

```text
hucre         arnold    blender    oran
metal_on      0.0000    0.0000     —
metal_half    0.4500    0.4490     0.9977
metal_spec    0.8915    0.8997     1.0092
```

Ara metalness'te yaklaşıklık var: base colour'ı ölçeklemek difüzü de
ölçekliyor, oysa yalnız metal lobu ölçeklenmeli. Toplam enerji doğru, açısal
dağılım yaklaşık. İki uçta (m=0 ve m=1) tam.

Aynı ayrımın `aiStandardSurface`'taki zayıf hali dokunulmadan bırakıldı:
70°'de `metal_on` → `metal_spec` Arnold'da 0.0802, Blender'da 0.0006 hareket
ediyor. Orada metal ağırlıkla sıfırlanmıyor, o yüzden aynı düzeltme yanlış
olurdu.

## Coat farkının sebebi `coatDarkening` — ölçüldü ve kapatıldı

`coat_on` %91 sapıyordu. OpenPBR coat'un altındaki tabanı karartıyor
(`coatDarkening`, varsayılan **1.0**, yani coat'lu her materyalde);
Principled'da karşılığı yok. Bunu izole eden bir hücre eklendi:

```text
                coatDarkening   arnold    blender    oran
coat_on              1.0        0.1765    0.3373     1.9112
coat_nodark          0.0        0.3373    0.3373     1.0000
```

Blender tam olarak karartmasız durumu üretiyordu. Fark tümüyle bu
attribute'tan geliyordu.

### Eğrinin ölçümü

Karartma **taban albedosuna bağlı**, sabit bir çarpan değil. Dört albedoda,
coat özgülü (`R₀`) çıkarıldıktan sonra:

```text
albedo   karartmasiz   karartmali   D
0.1      0.1479        0.0886       0.374
0.3      0.3373        0.1765       0.434
0.6      0.6213        0.3786       0.573
0.9      0.9053        0.7714       0.843
```

Bu klasik iç yansıma modeli: `D(b) = (1 − rᵢ) / (1 − rᵢ·b)`. İlk noktadan
`rᵢ = 0.6503` çıkıyor ve diğer üçünü üç hane tutturuyor.

`rᵢ` coat IOR'una bağlı. Üç IOR'da ölçüldü ve standart yaklaşımla
karşılaştırıldı:

```text
eta    olculen rᵢ    -1.440/eta² + 0.710/eta + 0.668 + 0.0636·eta
1.3    0.44462       0.44476
1.6    0.65030       0.65110
2.0    0.79033       0.79020
```

Bir parça on binde. Formül tahmin değil, bu yüzden tablo yerine formül
kullanılıyor.

Kısmi değerler ayrıca ölçüldü:

- **Karartma miktarında doğrusal.** b=0.3'te d = 0 / 0.25 / 0.5 / 1 için
  D = 1.000 / 0.858 / 0.717 / 0.434; doğrusal öngörü üç hane tutuyor. b=0.9'da
  da öyle.
- **Coat ağırlığında doğrusal değil, karesel.** Işık coat'u girerken ve
  çıkarken iki kez geçiyor. Ağırlıkta doğrusal varsaymak yarım kaplamada
  **%17** yanlış; `w²` yarım yüzde içinde.

Uygulanan biçim:

```text
D = 1 − d·w²·(1 − (1 − rᵢ)/(1 − rᵢ·b))
```

### Düzeltmeden sonra

```text
hucre                arnold    blender    oran
coat_on              0.1765    0.1764     0.9997
coat_nodark          0.3373    0.3373     1.0000
coat_dark_bright     0.7714    0.7714     0.9999
coat_dark_partial    0.2784    0.2773     0.9959
```

`coat_dark_partial`'daki %0.4, `w²`'nin bıraktığı bilinen artıktır.
`aiStandardSurface`'ta `coatDarkening` attribute'u yok, dolayısıyla kanal da
üretilmiyor ve o yüzey etkilenmiyor — chart'ta coat hücrelerinin hepsi
1.0000.

### Node zinciri ayrıca sınanır

Düz renk Python'da karartılıyor, texture'lı base color ise sekiz Vector Math
node'uyla. İkincisini hiçbir şey sınamıyordu; ters çevrilmiş bir çıkarma veya
baş aşağı bir bölme sessizce yanlış render ederdi. `coat_darkening_nodes.py`
sabit renkli bir görüntüyü node yolundan, aynı rengi düz yoldan geçirip
ikisini render ediyor — sabit görüntü iki yolu inşa gereği denk kılar.

Rig'in kendisi de sınandı: bölme node'unun operandları bilerek ters çevrildi
ve beş vakanın beşi de düştü.

## Sheen: soketler doğru, loblar farklı

`sheen_off → sheen_on` Arnold'da 0.0262, Blender'da 0.0006 hareket ediyor.
Eski quad ışıkta bu 0.000149'a karşı 0.000145 görünüyordu, yani "eşleşmiş"
sayılıyordu — dome, sheen'in yaşadığı sıyırma yönlerini de aydınlattığı için
farkı görünür kıldı.

Import edilen materyal doğrudan okundu:

```text
sheen_on_shd   Sheen Weight = 1.0   Sheen Roughness = 0.3   Sheen Tint = beyaz
```

Soketler doğru dolmuş. Fark `standard_surface`'ın sheen lobu ile Principled'ın
mikrolif sheen'inin farklı modeller olmasından. Aktarım hatası değil.

## Sıyırma açısı: artık güvenilir

Kamera eğilen sürümde 70° koşusunda kontroller 0.000000 ve 0.00008 fark
veriyor, yani rig konumdan bağımsız. O açıda tablo, yukarıda anlatılan iki
bilinen fark (`sheen_on` 0.7101, metal ve specular ağırlığı) dışında
eşleşiyor.

Bundan önceki "açıklayamadığım sapmalar" kaydı **enstrümanın kendisiydi**;
malzeme bulgusu değildi.

## Kapsamadıkları

- Redshift ve `lambert`/`blinn` bu rig'de sınanmadı. Native shader'ların
  aktarımı host testlerinde sınanıyor (`maya_export_test.py`).
- Yalnız düz değerler; texture'lı kanallar bu rig'de yok.
- **Transmission bilerek yok.** Araç orada Principled yerine Glass BSDF kurar
  ve bu bilinçli bir tercihtir (README "Desteklenen Maya shaderları"), yani
  rig'in "aynı model" varsayımı orada geçerli değil.

## Tekrar çalıştırmak

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" ^
    tests/calibration/material_match_maya.py [SURFACE] [TILT]
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python ^
    tests/calibration/material_match_blender.py
```

Yeni bir kanal eklediğinde `MATERIALS`'a bir **çift** ekle, tek hücre değil.
Tek hücre kanalın var olduğunu değil, yalnız iki tarafın aynı şeyi yaptığını
gösterir — ve iki taraf da hiçbir şey yapmıyorsa bu da bir eşleşmedir.

Rig'in geometrisine dokunduğunda **önce kontrol satırlarına bak.** Onlar
tutmuyorsa geri kalan tablo okunmamalıdır.
