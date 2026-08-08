# Texture projection ölçümü

Rig: `tests/calibration/projection_match_maya.py` + `projection_match_blender.py`

Maya'nın dokuz `projType` değeri tek bir küreye (r=1, 32×16) bake edilir, aynı
küre FBX ile Blender'a gider, aday node ağacı aynı UV uzayına bake edilir ve
iki görüntü piksel piksel karşılaştırılır. Metrik: ortalama mutlak fark
(0 = birebir aynı).

Test değil **ölçüm rig'i** — tabloyu doğrulamaz, üretir.

## Zincir kontrolleri

Rig'e güvenmeden önce iki kontrol hücresi çalıştırıldı; ikisi de geçmeden
hiçbir sayı okunmadı:

| kontrol | sonuç |
|---|---|
| Maya, düz UV texture bake → kaynak görüntü | birebir, çevirme yok |
| Blender, düz UV texture bake → kaynak görüntü | birebir, çevirme yok |

İkisi de sadık olduğu için, kalan her fark eşlemenin kendisine aittir.

Kontroller yazılmadan önce rig **her adaya ~0.41 verdi, Planar dahil** — yani
doğru olduğu bağımsız olarak bilinen eşlemeye de. İki gerçek hata oradan çıktı
(aşağıda).

## Sonuç

| Maya `projType` | Blender adayı | en iyi fark | karar |
|---|---|---|---|
| Planar | `FLAT`, rotX −90°, konum +0.5, `EXTEND` | **0.028** | **eşleşti** |
| Spherical | `SPHERE`, rotZ 180°, offU 0.5 | 0.106 | yakın, eşleşmedi |
| Ball | `SPHERE`, rotZ 180°, offU 0.5 | 0.107 | eşleşmedi |
| Cylindrical | `TUBE` | 0.415 | eşleşmedi |
| Cubic | `BOX` | 0.412 | eşleşmedi |
| TriPlanar | `BOX` | 0.412 | eşleşmedi |
| Concentric | — | 0.416 | Blender karşılığı yok |
| Perspective | — | 0.425 | Blender karşılığı yok |

Eşik 0.06. Planar 0.028'de, en yakın yanlış aday 0.106'da; aradaki boşluk
geniş, yani karar keskin.

Spherical için rotX/rotZ ve Y/Z işaret çevirmelerinin tüm kombinasyonları
tarandı; hepsi **0.1063'te düzleşti**. Yani Blender'ın `SPHERE`'ü ile
Maya'nın spherical'ı farklı parametrelendirilmiş; çevirmekle düzelmez.

## Spherical'ı node'larla kurmak

Hazır mod yerine Maya'nın matematiği Math node'larıyla kuruldu ve tarandı:

| aday | fark |
|---|---|
| `atan2(+x, +z)`, v = `asin(y/len)` | **0.0189** |
| `atan2(-z, -x)` | 0.1229 |
| `atan2(+z, +x)` | 0.1236 |
| `atan2(+x, +z)`, v ters | 0.2317 |

Yani Maya spherical: **u = 0.5 + atan2(x, z)/2π**, **v = 0.5 + asin(y/|p|)/π**.

**Fixture'ın kendisi bir kez değiştirildi ve bu şart oldu.** Dört çeyrekli
görüntüyle `atan2(x,z)` ile aynadaki eşi `atan2(x,-z)` **0.0216'ya karşı
0.0217** aldı — bu bir cevap değil, yazı tura. On altı hücreli ızgaraya
geçilince kazanan 0.0189, ikincisi 0.1229 oldu ve seçim kesinleşti. Üstelik
kazanan, dört çeyreğin işaret ettiğinin **tersi** çıktı.

Cylindrical aynı yöntemle tarandı, en iyi 0.248'de kaldı ve ilk dört aday
0.001 içinde toplandı — yani hiçbiri doğru değil. `projection` node'unda
`uAngle = 180` ve `vAngle = 90` var; spherical'da bu tam tur demek ve
formülü doğruluyor, cylindrical'ın dikey ölçeği ise bunlarla açıklanamadı.
Devam edecek olan için iz burada.

Planar'ın 0.028'i sıfır değil çünkü bake küre dikişinde filtreleme yapıyor;
eşleme hatası değil.

## Rig'in yakaladığı iki hata

**1. Birim ölçeği yerleştirmenin scale'inde yoktu.** Empty Maya'nın kendi
ölçeğini taşıyordu ama sahne birimini taşımıyordu. Maya yerleştirmenin iki
yanında yarım **Maya birimi** kadar projekte eder, Blender'ın object
koordinatları ise metre cinsinden gelir; santimetre bir sahnede görüntü yüz
kat küçük projekte oluyordu ve bir kürede bu tek düz renk olarak okunuyordu.

İlk ölçüm bunu göremezdi: ölçek 1'de yapılmıştı, orada iki birim çakışıyor.

**2. Maya projeksiyonu kenarında tekrar etmiyor, sabitliyor.** Blender'ın
varsayılan `REPEAT`'i yanlış:

| extension | Planar farkı |
|---|---|
| `REPEAT` (Blender varsayılanı) | 0.504 |
| `CLIP` | 0.362 |
| `EXTEND` | **0.028** |

## Tekrar çalıştırma

```bash
blender --background --factory-startup \
    --python tests/calibration/projection_match_blender.py -- write
mayapy tests/calibration/projection_match_maya.py
blender --background --factory-startup \
    --python tests/calibration/projection_match_blender.py -- compare
```

Sırası önemli: Blender önce projekte edilecek dört çeyrekli görüntüyü yazar.
