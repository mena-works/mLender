# Film fit — ölçüldü (2026-08-18)

Maya'da çerçeveyi film back **tek başına** belirlemiyor: film back + **film
fit** + render çözünürlüğü belirliyor. Blender'ın `sensor_fit`'i bunu birebir
modelliyor. Unreal'in cine kamerasında fit **yok** — yalnız filmback oranı var.
Yani Unreal'e ham film back yazmak, ancak render aspect'i film back aspect'ine
eşitse Maya'nın çerçevesini verir.

Bu depodaki fixture'da eşit değil: `orthoCam` 36×24 (aspect 1.5), render ise
1920×804 (aspect 2.388).

## Rig ölüydü — sorgu cevabı vermiyor

İlk deneme `cmds.camera(q=True, horizontalFieldOfView=True)` ile yapıldı. Dört
fit de **aynı** sayıyı verdi (hfov 39.598, vfov 26.992, yani ham 36×24). Sorgu
ne fit'i ne çözünürlüğü hesaba katıyor.

## Render ederek ölçüldü

Kurulum: 50mm lens, 36×24 back, z=-100'de **tam yatay alanı dolduran** bir quad
(72×48 birim). Böylece:

* genişliği koruyan bir fit → quad çerçeveyi yatayda doldurur, yanlarda siyah yok
* yüksekliği koruyan bir fit → çerçeve quad'dan geniş kalır, yanlarda siyah var

İki yönde de render edildi — render aspect'i back'ten geniş (2.4) ve dar
(0.4167).

| fit | render **geniş** | render **dar** |
|---|---|---|
| Horizontal | genişlik | genişlik |
| Vertical | yükseklik | yükseklik |
| Fill | genişlik | yükseklik |
| Overscan | yükseklik | genişlik |

Yani `Horizontal` ve `Vertical` mutlak; `Fill` back'i çerçeveye sığdırıyor,
`Overscan` çerçeveyi back'e sığdırıyor ve ikisi yön değiştirince yer
değiştiriyor.

## Unreal'e yazılan

Fit çözülüp filmback'e **pişiriliyor**:

```text
genişlik korunuyorsa: (w, w / render_aspect)
yükseklik korunuyorsa: (h * render_aspect, h)
```

Fixture'da ölçülen sonuç:

| kamera | Maya back | fit | Unreal filmback | aspect |
|---|---|---|---|---|
| orthoCam | 36 × 24 | Horizontal | 36 × 15.075 | 2.3881 |
| shotCam | 24 × 13.5 | Vertical | 32.239 × 13.5 | 2.3881 |

Üçü de render aspect'ine (1920/804 = 2.3881) oturuyor.

## Render aspect'i nereden okunuyor

`width / height × pixel_aspect` — yani görüntünün gerçekte ne olduğu.
Maya'nın `deviceAspectRatio`'su yalnızca **yedek**: onu arayüz güncelliyor,
`setAttr` ile genişlik/yükseklik doğrudan yazılınca bayat kalıyor. Bu depodaki
fixture tam bu durumda — 1920×804 render ederken device aspect hâlâ 1.7778
diyor.

## Doğrulama

`tests/host/unreal_import_test.py`, "the film fit was resolved against the
render aspect". Blender tarafında değişiklik yok: `sensor_fit` zaten Maya'nın
modelinin aynısı, çözmek gerekmiyor.
