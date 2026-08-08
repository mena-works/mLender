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

## Formülü tahmin etmeyi bırakmak

Cylindrical bu aramayla çözülmedi: en iyi aday 0.248'de kaldı ve ilk dördü
0.001 içinde toplandı, yani arama yanlış yerde geziyordu.

Yöntem değiştirildi. Formül denemek yerine **Maya'nın u,v'si doğrudan
okundu**: u'yu kırmızıya, v'yi yeşile kodlayan bir görüntü projekte edilip
bake edildi, böylece her yüzey noktası Maya'nın kendisi için hesapladığı
çifti bildirdi. Aynı noktaların yerleştirme-yerel koordinatları Blender'da
bakelendi ve ikisi yan yana kondu.

Tablo okununca formüller çıktı:

| tip | u | v |
|---|---|---|
| Spherical | `0.5 + atan2(x, z) / 2π` | `0.5 + asin(y/\|p\|) / π` |
| Cylindrical | `0.5 + atan2(x, z) / π` | `0.5 + y / 2` |

Cylindrical'ın u'su spherical'ınkinin **tam iki katı eksi yarım** — beş
örnekte de tutuyor (0.285→0.067, 0.583→0.663, 0.981→0.459). Yani görüntü
360° değil **180°** sarıyor. `uAngle = 180` bu; spherical'da aynı sayı tam
tur anlamına geliyor.

## Uzatma davranışı tipe göre değişiyor

| tip | EXTEND | REPEAT | CLIP |
|---|---|---|---|
| Planar | **0.028** | 0.504 | 0.362 |
| Cylindrical | 0.219 | **0.020** | 0.278 |

Planar kenarında sabitliyor; cylindrical'ın yarım turu nesneyi iki kez
dolaştığı için sarıyor. Tek kural ikisine de uygulanırsa hangisi olursa
olsun 0.2 kaybediliyor.

## Kalanlar

Cubic, TriPlanar, Ball, Concentric ve Perspective için u,v tablosu da
okundu ama tek bir kapalı formüle oturmadı — Cubic yüzeye göre yüz seçiyor,
Ball bir yansıma küresi eşlemesi. Bunlar bake'e bırakıldı; okunmuş u,v
tablosu elde olduğu için devam edecek olanın başlangıç noktası hazır.

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
