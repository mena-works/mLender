# Düzeltme node'ları: ölçüm kaydı

Bu belge `aiColorCorrect` ve komşularının **ne hesapladığının** nasıl
ölçüldüğünü anlatır. Attribute isimleri ayrı bir konu ve onlar da ölçüldü;
burada asıl mesele matematiğin kendisi, çünkü üç yerde sezginin tersi çıktı.

## Neden ölçüldü

Bu projede tahmin edilen isimlerin çoğu yanlış çıktı. Formüller daha da
kaygan: "gamma" hem `in^g` hem `in^(1/g)` anlamına gelebilir ve ikisi de
makul görünür. Yanlış olanı seçmek texture'ları sessizce yanlış parlaklıkta
getirir — kimse fark etmez, sadece "Blender'da bir tuhaf" olur.

## Yöntem

**Maya/Arnold tarafı.** Arnold shader'ları DG'de hesaplanmaz, sadece render
sırasında çalışır. Bu yüzden düzeltme node'u ışıksız bir `aiFlat`'ın
`color`'ına bağlanır, ortografik bir kamerayla 8×8 linear EXR render edilir ve
piksel okunur. `aiFlat` unlit olduğu için piksel doğrudan node'un çıktısıdır.

Renderer olarak `kick` kullanılır; `.ass` export'unun iki tuzağı
`light_calibration.md`'de anlatılıyor (denoiser satırı, `lightLinks=0`).

**Maya'nın kendi node'ları** (`gammaCorrect`, `reverse`, `clamp`,
`remapValue`, `luminance`) DG'de hesaplanır, yani `getAttr` yeter — render
gerekmez.

**Blender tarafı.** Test edilecek node zinciri **world background**'a bağlanır;
kamera ışınları arka planı doğrudan döndürdüğü için render edilen piksel
node'un çıktısıdır, arada shading yoktur.

İki tuzak:

1. Factory startup sahnesinde kameranın önünde bir küp durur. Silinmezse
   ölçülen şey küpün aydınlatması olur.
2. **Cycles denoiser varsayılan olarak açıktır** ve 4×4'lük sabit bir
   görüntüde çıktıyı gerçek değerin yanına savurur — üstelik her koşuda
   farklı. Kapatılmalı, çözünürlük de büyütülüp merkez piksel okunmalı.

## Ölçülen: Arnold `aiColorCorrect`

```text
girdi              ayar                        cikti
(.8,.2,.1)         yok                         0.800000  0.200000  0.100000
0.5                gamma 2                     0.707107
0.2                exposure 1                  0.400000
0.5                contrast 2, pivot .18       0.820000
(.8,.2,.1)         saturation 0                0.800000  0.800000  0.800000
(.8,.2,.1)         saturation 2                0.800000  0.114286  0.000000
(1,0,0)            hueShift 0.25               0.500000  1.000000  0.000000
(1,0,0)            hueShift 90                 1.000000  0.000000  0.000000
0.3                multiply 2                  0.600000
0.3                add 0.1                     0.400000
0.3                invert                      0.700000
0.5                gamma 2 + multiply 2        1.414214
0.5                exposure 1 + contrast 2     1.640000
0.4                multiply 2, mask 0.5        0.600000
```

Çözümler:

- **`gamma` ters üstür**: `out = in^(1/gamma)`. `0.5^(1/2) = 0.7071`.
- **`hueShift` tur cinsindendir**, derece değil. `0.25` çeyrek tur döndürür;
  `90` tam sayı tur olduğu için hiçbir şey yapmaz.
- **`saturation` HSV uzayındadır** ve S değeri 1'de kırpılır. `sat 0` sonucu
  luminance değil, HSV'nin `V`'sidir (0.8 = maksimum bileşen).
- **`contrast` doğrusaldır**: `out = c*(in - pivot) + pivot`.
- **Sıra**: `gamma → hue → saturation → contrast → exposure → multiply → add
  → invert → mask`. İki ölçüm bunu sabitliyor: `gamma 2 + multiply 2` sonucu
  `1.4142` (önce gamma), `exposure 1 + contrast 2` sonucu `1.64` (önce
  contrast; ters sıra 1.82 verirdi).
- **`mask`** düzeltilmiş sonucu ham girdiye karşı lerp eder.

## Ölçülen: Arnold `aiRange`

```text
0.5    in .2-.8 -> 0-1                 0.500000
0.35   in .2-.8, smoothstep            0.156250      = 3t^2-2t^3, t=0.25
0.7    contrast 2, pivot .5            0.900000
0.5    bias 0.25                       0.250000      = Schlick bias
0.5    gain 0.75                       0.500000      (t=0.5 simetrik, bilgisiz)
```

Doğrusal remap ve contrast yeniden kuruluyor. `smoothstep`, `bias` ve `gain`
kurulmuyor; bunlar için importer uyarı yazıyor. `gain` ölçümü t=0.5'te
simetrik olduğu için zaten bilgi vermedi — kurmak isteyen önce başka bir
örnek noktada ölçmeli.

## Ölçülen: Blender node'ları

```text
Gamma      0.5, g=2            0.250000     -> out = in^g
Gamma      0.5, g=0.5          0.707107
HSV        (1,0,0) hue .75     0.5 1.0 0.0  -> 0.5 notr, ofset
HSV        (.8,.2,.1) sat 0    0.8 0.8 0.8  -> Arnold ile ayni
HSV        (.8,.2,.1) sat 2    0.8 0.114285 0.0  -> Arnold ile ayni
B/C        0.5, b=0 c=0        0.500000
B/C        0.2, b=0 c=1        0.000000     -> max(...,0) ile kirpiyor
B/C        0.5, b=0.1 c=0      0.600000
Invert     0.3, fac=1          0.700000
```

Blender'ın Bright/Contrast'ı: `out = max((1+C)*in + (B - C/2), 0)`.

## Eşlemeler

```text
Arnold gamma g          ->  Blender Gamma = 1/g
Arnold hueShift h       ->  Blender Hue   = (0.5 + h) mod 1
Arnold saturation s     ->  Blender Saturation = s        (birebir)
Arnold contrast c,      ->  Blender Contrast   = c - 1
       pivot p              Blender Brightness = (1-c)*(p-0.5)
Arnold exposure e       ->  multiply *= 2^e                (aynı node'a katlanır)
```

Contrast eşlemesi doğrulandı: Arnold `contrast 2, pivot .18` girdi `0.5` için
**0.820000** verdi; aynı değerlerle kurulan Blender Bright/Contrast de
**0.820000** verdi.

Tek fark Blender'ın sıfırda kırpması. Arnold kırpmaz, yani çok yüksek
contrast'ta negatife inen bölgeler Blender'da sıfırda durur.

## Soket isimleri sürümle değişti

Ölçüm sırasında çıkan ayrı bir bulgu: aynı node'ların soket **isimleri** 4.1
ile 5.2 arasında değişmiş, **indeksleri** değişmemiş.

```text
ShaderNodeMixRGB           input 0:  "Fac"     -> "Factor"
ShaderNodeBrightContrast   input 1:  "Bright"  -> "Brightness"
ShaderNodeInvert           input 0:  "Fac"     -> "Factor"
ShaderNodeHueSaturation    input 3:  "Fac"     -> "Factor"
```

Bu yüzden `corrections.py` soketlere **indeksle** erişir. İsimle erişseydi kod
4.1'de veya 5.2'de sessizce varsayılan değerde kalırdı.

`ShaderNodeMixRGB` her iki sürümde de kurulabiliyor (5.2'de "legacy" sayılsa
da), `ShaderNodeMix` ise veri tipi başına tekrar eden soket isimleri taşıyor.
Bu yüzden eski olan tercih edildi.

## Tekrar ölçmek isteyen için

Prob scriptleri kalıcı değil; yöntem yukarıda tam olarak yazılı. Maya tarafı
`aiFlat` + `kick`, Blender tarafı world background + denoiser kapalı. İkisinde
de linear EXR, `view_transform = "Standard"`, sıkıştırma yok.
