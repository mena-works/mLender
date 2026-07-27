# Işık enerjisi kalibrasyonu

Bu belge `WATTS_PER_INTENSITY` değerlerinin nereden geldiğini ve nasıl yeniden
ölçüleceğini anlatır. Kısa cevap: Arnold ve native Maya için **ölçüldü ve π
çıktı**; Redshift hâlâ devralınmış bir tahmin.

## Sorun

Arnold'ın `intensity`'si ve Redshift'in "Image" unit'i boyutsuzdur. Blender'ın
light Power'ı ise watt cinsinden **toplam ışıl akıdır**. Aradaki dönüşüm
tahminle yazılırsa tüm sahnelerin aydınlatması kayar.

Eskiden bu araç "ampirik kalibrasyon" adıyla Arnold ve Maya için `×1000`,
Redshift için `×10` kullanıyordu. Ölçüm bunun Arnold tarafında **318× fazla
parlak** olduğunu gösterdi.

## Yöntem

İki renderer'da birebir aynı sahne kurulur, ikisi de linear EXR'a render edilir
ve merkez pikselin oranı çözülür. Piksel değeri güce doğrusal bağlı olduğu için
tek render yeter.

Sahne (sayılar iki tarafta **aynen** aynı olmalı; Arnold birimden bağımsızdır,
sadece ham sayılar karşılaştırılabilir):

```text
duzlem   20 x 20, orijinde, beyaz Lambert, albedo 1
isik     quad, kenar 0.1, 10 birim yukarida, asagi bakiyor,
         normalize on, intensity 1, exposure 0
kamera   ortografik, genislik 1, 30 birimde, duz asagi bakiyor
```

Işık mesafeye göre küçük tutulur (0.1 / 10), böylece iki renderer'ın quad boyut
konvansiyonu farklı olsa bile sonuç etkilenmez.

**Maya tarafı.** Sahneyi Maya'da kur, `cmds.arnoldExportAss` ile `.ass` çıkar,
sonra `kick` ile render et:

```bash
kick -i calib.ass -o arnold_ref.exr -r 64 64 -dw -nostdin
```

Üç tuzak:

1. `currentUnit(linear="m")` sadece UI birimini değiştirir; Maya içeride cm
   saklar ve `.ass` iç birimleri taşır. Sahneyi **cm'de** kur.
2. Export edilen `.ass`, var olmayan bir `defaultArnoldDenoiser` referansı
   içerir ve kick bu yüzden abort eder. `input "defaultArnoldDenoiser"`
   satırını sil.
3. `.ass` içinde `exposure` hem ışıkta hem kamerada bulunur. Varyant üretirken
   yalnızca `quad_light` bloğunu düzenle, yoksa yanlış node'u değiştirirsin.

**Blender tarafı.** Aynı sahneyi kur, bilinen bir güçle (ör. 1000 W) render et,
merkez pikselleri karşılaştır:

```text
watt_per_intensity = blender_power * (arnold_piksel / blender_piksel)
                     / (intensity * 2^exposure)
```

`view_transform = "Standard"`, `max_bounces = 0`, 32-bit EXR, sıkıştırma yok.

## Rig'in doğruluğunu nasıl bilirsin

Blender ölçümü kapalı-formla karşılaştırılabilir. Lambert alan ışığı, toplam
akı `P`, mesafe `d`, albedo 1 yüzey:

```text
piksel = P / (pi^2 * d^2)
```

Ölçülen değerler (P = 1000 W):

```text
d = 5    olculen 4.05145   beklenen 4.0528
d = 10   olculen 1.01312   beklenen 1.0132
d = 20   olculen 0.253297  beklenen 0.2533
```

Kamera yanlış yöne baksa, ışık yanlış yöne emit etse veya mesafe şaşsa bu
özdeşlik tutmaz. Rig doğrulaması budur — göz kararı değil.

## Sonuç

Beş varyant (mesafe 5/10/20, intensity 1/4, exposure 0/2):

```text
varyant       yukseklik  int   exp   arnold        blender    capa
base            10.0     1.00  0.0   0.0031824     1.01312    3.1412
intensity4      10.0     4.00  0.0   0.0127296     1.01312    3.1412
height5          5.0     1.00  0.0   0.0127263     4.05145    3.1412
exposure2       10.0     1.00  2.0   0.0127296     1.01312    3.1412
height20        20.0     1.00  0.0   0.000795651   0.253297   3.1412

yayilim %0.00006      mean/pi = 0.99987
```

Native Maya `areaLight` MtoA üzerinden **birebir aynı `quad_light`'a** dönüşür
ve pikseli aynıdır (oran 1.000000), yani onun çapası da π.

## Neden tam olarak π

Arnold'ın normalize edilmiş `intensity`'si, ışığın normali yönündeki **ışıl
şiddettir** (`I₀`). Lambert yayıcı için toplam akı `Φ = π·I₀`. Blender'ın
Power'ı toplam akı.

## Birim ölçeği de girer — ilk ölçümün kör noktası

Yukarıdaki ölçüm iki sahneyi de **aynı ham sayılarla** kurmuştu (ışık 10
birimde, Blender'da da 10). Bu, dönüşümün sahne birimine bağlı olduğunu
gizledi.

Arnold birimden bağımsızdır: ışık `d` birim uzaktaysa aydınlatma `1/d²` düşer,
`d`'nin ne anlama geldiğine bakmaz. Blender metre çalışır. Maya santimetredeyse
150 birimlik mesafe Blender'da 1.5 m olur ve aynı ışık **10⁴ kat** parlak
görünür.

```text
piksel_arnold  = k · I / d_maya²
piksel_blender = P / (pi² · (s·d_maya)²)        s = meters_per_maya_unit

esitle  ->  P = pi · s² · I
```

Doğru dönüşüm:

```text
Blender Power = pi * s^2 * intensity * 2^exposure
```

`s = 0.01` (santimetre sahne) için bu, çıplak π'nin **10⁻⁴ katıdır**. Kalibrasyon
sahnesi `s = 1` kullandığı için terim görünmüyordu.

## Uçtan uca doğrulama

`calibration/render_match_maya.py` + `calibration/render_match_blender.py` bunu gerçek hattan sınar:
Maya'da bir küp, zemin, alan ışığı ve kamera kurar, paketi export eder, `.ass`'i
kick ile render eder; Blender paketi import edip **aynı kameradan** render eder
ve pikselleri karşılaştırır.

Bu karşılaştırma üç ayrı hata ortaya çıkardı:

```text
1. birim olcegi enerjide yok sayiliyordu        ~10000x
2. Arnold quad'i -1..1, yani scale'in 2 kati    sekil/yumusaklik
3. specular agirligi hic aktarilmiyordu         ~%20 + aciya gore degisim
```

Üçü düzeltildikten sonra dört örnek noktasının üçü beş anlamlı hanede birebir
aynı, ortalama oran **0.9976**, yayılım %1.03.

Üçüncüsü sinsiydi: Principled enerji korur, dolayısıyla Maya'da `specular 0`
olan bir yüzeye Blender'ın varsayılan 0.5 speküler seviyesini bırakmak hem
olmayan bir parlama ekler hem o enerjiyi diffuse'dan çalar.

## Redshift

Ölçülemedi: `redshift4maya` bu makinede kurulu değil. Girdi orijinal araçtan
devralınan `10.0` olarak duruyor ve bu, Arnold/Maya'nın π'siyle tutarsız.

Redshift kurulu bir makinede yukarıdaki yöntem aynen uygulanabilir. O zamana
kadar en güvenli yol Redshift ışığının `unitsType`'ını **fiziksel bir birime**
(Lumens / Candela / Watts) çevirmektir; kod o dalları tam çevirir ve çapaya hiç
uğramaz.

## Kullanıcı çarpanı

`Light Power Scale` (N-panel, `za_light_power_scale`) dönüşümün üstünde sanatsal
bir çarpandır, varsayılanı `1.0`. Bütün ışıkları eşit ölçekler, yani ışıklar
arası oranlar bozulmaz. Dönüşüm ölçülmüş olduğu için `1.0` Maya render'ıyla
eşleşmelidir; başka bir değere ihtiyaç duyuyorsan ya sahnede fiziksel birim
kullanılıyordur ya da burada bir bulgu vardır.
