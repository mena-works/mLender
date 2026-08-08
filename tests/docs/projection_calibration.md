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
tarandı; hepsi **0.1063'te düzleşti**. Yani kalan fark bir yönelim meselesi
değil, Blender'ın `SPHERE`'ü ile Maya'nın spherical'ının farklı
parametrelendirmesi. Uydurup eşiği gevşetmektense eşleşmedi denmiştir.

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
