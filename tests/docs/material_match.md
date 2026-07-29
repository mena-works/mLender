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
yapısal sapma olarak görünür — ışık tarafında bulunan üç hata da öyleydi
(10000×, şekil, %20 açıya bağlı).

## Yöntem

Kamera ortografik, ışık **kameranın arkasında**, yüzeyler düz quad'lar. Böylece
her örnek dik geliş açısında alınır ve geometri ile shading normalleri
karşılaştırmadan tamamen çıkar; geriye yalnız materyal cevabı kalır.

İki renderer da doğrudan aydınlatma (GI kapalı), lineer EXR, `Standard` view
transform.

## Eşleşmek yeterli değil

Bir kanal iki tarafta da sessizce sıfırsa tablo yine "eşleşti" der. Bu yüzden
şüphelenilen her kanal için **tek o kanalda farklılaşan bir çift** var. Çiftin
Arnold'da ayrışıp Blender'da ayrışmaması, kanalın aktarımda kaybolduğu
anlamına gelir.

## Sonuç (1.24.0, Maya 2023 / MtoA 5.4.8, Blender 5.2)

On altı hücrenin hepsi **%0.7 içinde**:

```text
hucre            arnold      blender    oran
grey_diffuse     0.0003      0.0003     1.0001
dark_diffuse     0.0001      0.0001     1.0001
red_diffuse      0.0009 R    0.0009 R   1.0001
spec_off         0.0004      0.0004     1.0000
spec_on          0.0006      0.0006     0.9999
spec_rough       0.0008      0.0008     1.0020
metal_off        0.0025      0.0025     1.0001
metal_on         0.0177      0.0178     1.0067
coat_off         0.0009      0.0009     1.0000
coat_on          0.0018      0.0018     0.9964
sheen_off        0.0007      0.0007     1.0000
sheen_on         0.0006      0.0006     1.0074
emission_off     0.0004      0.0004     0.9999
emission_on      0.4003      0.4003     1.0000
opacity_full     0.0006      0.0006     1.0001
opacity_half     0.0002      0.0002     1.0001
```

Ve altı çiftin altısı da iki tarafta ölçülebilir şekilde hareket ediyor:

```text
cift                          arnold      blender
spec_off  -> spec_on          0.000115    0.000115
metal_off -> metal_on         0.015149    0.015267
coat_off  -> coat_on          0.000877    0.000871
sheen_off -> sheen_on         0.000149    0.000145
emission_off -> emission_on   0.399886    0.399886
opacity_full -> opacity_half  0.000397    0.000397
```

`sheen_on`'un `sheen_off`'tan **daha koyu** olması doğrudur: sheen dik gelişte
enerjiyi tabandan alır. İki renderer da aynı yönde hareket ediyor.

**Bu turda aktarım hatası bulunamadı** — ama chart'ın kendisi bir tanesini
kaçırmıştı, aşağıya bak.

## Chart'ın kaçırdığı hata: emission kırpması

`emission_on` hücresi `emissionColor` olarak **0.4** kullanıyordu, yani 1'in
altında. Importer ise her rengi 0–1 aralığına kırpıyordu, dolayısıyla chart
temiz görünüyordu.

Hata ayrı bir deneyde ortaya çıktı: `emissionColor` **50** verilen bir yüzey
Arnold'da 50, Blender'da **1.0** okundu. Yani parlak her emissive materyal
sessizce düzleşiyordu.

Düzeltildi ve chart'a `emission_hdr` hücresi eklendi (`emissionColor` 4.0):

```text
emission_hdr     arnold 4.0003    blender 4.0003    oran 1.0000
```

Ders, bu belgede kalmalı: **sınır değerlerinin öte tarafında da bir hücre
olsun.** 0–1 aralığında kalan bir test, aralığı daraltan bir hatayı göremez.

## OpenPBR: emission ölçekleyicisi 10 kat yanlıştı

Chart artık yüzey tipini ve quad'ların açısını argüman olarak alıyor:

```bash
material_match_maya.py                        # aiStandardSurface, dik
material_match_maya.py aiOpenPBRSurface       # diğer yüzey
material_match_maya.py aiStandardSurface 45    # aynı chart, eğik
```

OpenPBR koşusu üç anomali gösterdi, biri kesin:

**`OPENPBR_EMISSION_LUMINANCE_SCALE` 100 değil 1000.** Kodda "seçilmiş bir
değer, ölçülmedi" diye duruyordu. Arnold, `emissionLuminance = 100` ve
`emissionColor = 0.4` için **0.0404** veriyor — yani renge uygulanan çarpan
0.1, 1 değil. Blender her OpenPBR emissive yüzeyde **10 kat parlaktı**.

Sabit 1000'e çekildikten sonra, iki farklı parlaklıkta oran tam 1.0000:

```text
nit    hucre           arnold     blender    oran
100    emission_on     0.0404     0.0404     1.0000
100    emission_hdr    0.4003     0.4003     1.0000
400    emission_on     0.1604     0.1604     1.0000
400    emission_hdr    1.6003     1.6003     1.0000
```

Çift deltaları da altı hanede örtüşüyor, yani dönüşüm doğrusal.

### Çözülmemiş iki OpenPBR farklılığı

- **`metal_on`**: Arnold 0.0000, Blender 0.0167. Chart'ın tabanında
  `specular = 0` var; OpenPBR metali `specularWeight`'e bağlı görünüyor,
  Principled'ın metali ise `Specular IOR Level`'a bağlı değil. Aktarım hatası
  mı semantik fark mı, ayrıca sınanmalı.
- **`coat_on`**: %28 fark. Coat modelleri zaten aynı değil; anlamlı olup
  olmadığı belli değil.

## Sıyırma açısı: henüz güvenilir değil

Açı argümanı çalışıyor ve dik koşu bilinen-iyi sayıları aynen üretiyor
(rig'in kendi regresyon kontrolü). Ama 45° ve 70°'de emission ve opacity
hücreleri açıklayamadığım şekilde sapıyor.

**İki hipotez kuruldu ve ikisi de çürütüldü:**

1. Örnekleme yaması dar quad'ı taşıyor — 45°'de quad 38 piksel, yama 12
   piksel; anomali aynı kaldı.
2. Emissive yüzey komşusunu aydınlatıyor — izole deneyde quad'lar birbirine
   **bakacak şekilde** döndürüldü, alıcı iki renderer'da da 0.000000.

Sebep henüz bilinmiyor, o yüzden sıyırma sonuçları bulgu sayılmamalı.

## Kapsamadıkları

Sonucu okurken bunlar akılda tutulmalı:

- Redshift ve `lambert`/`blinn` sınanmadı. OpenPBR artık sınanıyor.
- Pratikte yalnız **dik geliş açısı**; eğik koşu var ama güvenilir değil.
- Yalnız düz değerler; texture'lı kanallar bu rig'de yok.
- **Transmission bilerek yok.** Araç orada Principled yerine Glass BSDF kurar
  ve bu bilinçli bir tercihtir (README "Desteklenen Maya shaderları"), yani
  rig'in "aynı model" varsayımı orada geçerli değil.
- Değerler küçük (1e-4 – 1e-2); dinamik aralık dar.

## Sınanan ve çürütülen bir hipotez

Bir ara "emissive yüzeyler Cycles'ta komşularını aydınlatıyor, Arnold'da
aydınlatmıyor" diye düşünülmüştü. İzole bir deneyle sınandı — iki quad,
biri emissive biri düfüz, sahnede hiç ışık yok, iki tarafta da bir
diffüz sıçrama açık:

```text
                      arnold      blender
emitter (kendisi)   50.000002     1.000000   <- asıl hata buradaydı
receiver (komşu)     0.000000     0.000000
```

Komşu iki tarafta da siyah: **hipotez yanlış**. Ama aynı deney emission
kırpmasını ortaya çıkardı.

## Tekrar çalıştırmak

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" ^
    tests/calibration/material_match_maya.py
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
    --background --factory-startup --python ^
    tests/calibration/material_match_blender.py
```

Yeni bir kanal eklediğinde `MATERIALS`'a bir **çift** ekle, tek hücre değil.
Tek hücre kanalın var olduğunu değil, yalnız iki tarafın aynı şeyi yaptığını
gösterir — ve iki taraf da hiçbir şey yapmıyorsa bu da bir eşleşmedir.
