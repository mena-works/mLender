# aiColorCorrect — ölçüldü (2026-08-18)

Rig: `tests/calibration/color_correct_maya.py` + `color_correct_read.py`.
Girdi `(0.2, 0.5, 0.8)` — üç kanal da farklı, çünkü eşit kanallar kanal başına
çalışan bir şeyi gizler ve her yerde 0.5 olsa multiply ile gamma aynı sayıyı
verirdi.

## Önce: rig'in kendisi bir kez yanlıştı

İlk sürüm `convertSolidTx` ile bake ediyordu — `layeredTexture` ölçümünün
yaptığı gibi. **On iki satırın hepsi 0.5 gri çıktı, kimlik satırı dahil.** Ele
veren şey kontroldü: kimlik satırı girdiyi vermek zorundaydı, vermedi.

Sebep: `convertSolidTx` Maya'nın kendi texture değerlendirmesini çalıştırıyor
ve `aiColorCorrect` bir Arnold node'u — Maya onu bilmiyor. `layeredTexture`'da
çalışması, o node'un **Maya'nın** olmasındandı. Arnold node'u Arnold'la
ölçülür: `.ass` export + `kick` → lineer EXR, yüzey `aiFlat` (piksel = renk,
araya ışık girmiyor).

## Tek tek parametreler

| parametre | ölçülen | formül |
|---|---|---|
| gamma = 2 | (0.44721, 0.70711, 0.89443) | `in^(1/gamma)` |
| exposure = 1 | (0.4, 1.0, 1.6) | `in × 2^exposure` |
| multiply = (2, 1, 0.5) | (0.4, 0.5, 0.4) | kanal başına çarpım |
| add = (0.1, 0, −0.1) | (0.3, 0.5, 0.7) | kanal başına toplam |
| contrast = 2 (pivot 0.18) | (0.22, 0.82, 1.42) | `(in − pivot) × c + pivot` |
| invert | (0.8, 0.5, 0.2) | `1 − in` |
| saturation = 0 | (0.8, 0.8, 0.8) | HSV; sonuç **max** kanal, luminans değil |
| hueShift = 0.25 | (0.8, 0.2, 0.8) | HSV'de dönme |

Saturation'ın 0.8 vermesi dikkat ister: Rec709 luminansı 0.458, ortalama
0.5 olurdu. 0.8 girdinin en büyük kanalı, yani node HSV'de çalışıyor.

## Sıra — asıl soru

Her çift, iki olası bileşimden **tam olarak birine** eşit çıktı:

| çift | kazanan |
|---|---|
| multiply + gamma | gamma önce |
| add + gamma | gamma önce |
| multiply + add | multiply önce |
| contrast + gamma | gamma önce |
| exposure + gamma | gamma önce |
| invert + gamma | **invert önce** |
| invert + multiply | invert önce |
| contrast + multiply | contrast önce |
| contrast + add | contrast önce |

Yani zincir:

```text
invert → gamma → contrast(pivot) → exposure → multiply → add
```

`exposure` ile `multiply` ikisi de çarpım olduğu için aralarındaki sıra
görüntüyü değiştirmez.

## Sonucun kullanımı

Gamma'dan **sonraki** her şey afin, yani tek bir çarpan ve tek bir toplamda
toplanabilir. Kanal başına:

```text
A = contrast × 2^exposure × multiply
B = pivot × (1 − contrast) × 2^exposure × multiply + add
out = A × in^(1/gamma) + B
```

Unreal alıcısı bunu iki node ile kuruyor (bir çarpım, bir toplam), gamma zaten
bir `Power`'dı. `invert` gamma'dan önce olduğu için katlanamaz — yalnız gamma 1
iken katlanır (`A → −A`, `B → A + B`), ve gamma 1 değilken bildirilir.

`saturation` ile `hueShift` HSV'de çalışıyor; sabit bir afin yığına girmiyorlar
ve adlarıyla bildiriliyorlar.

## Doğrulama

`tests/host/unreal_import_test.py`, "the colour correct chain folded into the
stack". Fixture: `ccFoldCube`, gamma 2.2 + exposure 1 + multiply + add.
