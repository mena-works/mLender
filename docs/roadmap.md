# Yol haritası

İç çalışma notu, Türkçe. `tests/docs/` ölçüm kayıtlarına ayrılmıştır; burası
ne yapılacağına dair karar defteri.

Sıralama "ne kadar değerli" değil, **hata ne kadar kötü × gerçek sahnede ne
kadar sık** ile yapılmıştır. Gerekçesi şu: bu araçta bulunan ciddi hataların
tamamı eksik özellik değil **sessiz kayıp** oldu — instance, locator, curve,
volume, particle, instancer, projeksiyon. Kullanıcı gönderdiğini aldığını
sandı.

**Ölçülen ile ölçülmeyen ayrımı korunmalıdır.** Aşağıda "ölçüldü" yazan her
satırın arkasında çalıştırılmış bir probe vardır; "kontrol edilmedi" yazan
satırlar iddia değil şüphedir.

---

## 1. Sessizce kaybolanlar

En yüksek öncelik. Kullanıcıya tek satır uyarı gitmiyor.

| iş | durum | not |
|---|---|---|
| NURBS yüzeyler | **ölçüldü, kayboluyor** | Keşif `ls(type="mesh")` ile başlıyor; NURBS yüzey mesh değil, FBX seçimine de girmiyor. Maya'da marjinal değil: ürün/endüstriyel modelleme ve eski asset'ler. |
| Maya subdiv yüzeyleri | **ölçüldü, kayboluyor** | Aynı sebep, aynı çözüm yolundan gider. |
| Animasyonlu materyal parametreleri | **ölçüldü, gitmiyor** | Zaman ekseninde yalnız ışık, kamera, particle ve mesh görünürlüğü örnekleniyor. Anahtarlanmış bir roughness veya base colour export karesinde donuyor. Görünürlükte aynı sınıf hata çıkmıştı. |
| Desteklenmeyen texture ağı uyarısı | **ölçüldü, sessiz** | `unsupported_network` exporter'da yazılıyor, importer'da hiç okunmuyor. Bake kapalıyken kanal düz değere çöküyor. `unsupported_corrections` zaten okunuyor; desen orada. Küçük iş. |

Ölçüm için:

```bash
"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe" -c "..."   # geom probe
```

NURBS için üç yol var, seçim önemlidir:

1. **FBX'e tessellate ettirmek** — trim'li yüzeyler dahil her şey doğru gelir,
   Blender'da poly olur. Önerilen.
2. **Blender'da yerel NURBS kurmak** — düzenlenebilir kalır ama trim'li
   yüzeyleri temsil edemez. Yarım çözüm.
3. **`nurbsToPoly` ile geçici mesh** — sahneyi değiştirir; CLAUDE.md bunu
   yasaklıyor, atomik temizlikle yapılabilir ama karmaşık.

FBX'in NURBS ayarının gerçek adı **probe edilmeden** tabloya yazılmamalıdır.

---

## 2. Kontrol edilmedi, aynı sınıfta olabilir

Bunlar **ölçülmedi**. Keşif listesinde aranmadıkları kesin, ama FBX üzerinden
gelip gelmedikleri bilinmiyor. Her biri yarım saatlik bir probe ile kapanır.

- `gpuCache` düğümleri — prodüksiyonda yaygın
- `aiStandIn` (Arnold procedural) — yaygın
- Işık filtreleri: gobo, barn door, blocker
- XGen, nHair, nCloth, fluid
- VDB **dizileri** (kare başına dosya) — volume kaydı tek yol taşıyor
- Kamera image plane animasyonu, overscan, film offset

**Bu turu 1'den önce yapmak savunulabilir:** neyin kaybolduğunu bilmeden
neyin taşınacağını seçmek zordur.

---

## 3. Eksik ama dürüst — uyarıyor, sessiz değil

| iş | not |
|---|---|
| Cubic ve Ball projeksiyonları | Ölçüldü, eşleşmedi, sebebi biliniyor: Cubic `fitType`/`fitFill` ile nesnenin sınır kutusuna bağlı, Ball yansıma küresi eşlemesi. Rig kurulu, u,v tablosu okunmuş. |
| `aiStandardHair` | Blender'da gerçek karşılığı var (Principled Hair BSDF). |
| `rampShader`'ın kalan rampaları | specularColor, reflectivity, environment — Principled'da rampa şeklinde soket yok. |
| `aiToon` | Karşılığı yok, yapılırsa yaklaşık olur. Değeri düşük. |

---

## 4. Kapalı veya ayrı karar

- **Redshift** — plugin bu makinede kurulu değil. Işık çapası (`10.0`) hâlâ
  devralınmış bir tahmin; motion blur ve volume attribute isimleri
  ölçülemiyor. Kurulursa açılır, yöntem `tests/docs/light_calibration.md`.
- **Rig** — ayrı değerlendirilecek. Alembic geldiği için skinli karakter
  bugün cache olarak geçiyor, ama poz verilemiyor.

---

## Hepsinin üstünde: gerçek sahne

Araç bugüne kadar **yalnız yazılmış fixture'ları** gördü. Bu oturumda şema
30'dan 36'ya, sürüm 2.11'den 2.23'e gitti ve materyal boru hattı blend
shader, rampa ve projeksiyon dalları aldı.

Bulunan her ciddi hata, akla gelmemiş bir şey test edildiği anda çıktı.
Gerçek bir sahne, tanımı gereği, akla gelmeyenlerin bulunduğu yerdir. Tek bir
gerçek sahneden gelen `mLender warning:` listesi, günlerce süren probe
turundan daha çok şey söyler.

Kullanıcının adımı kısa: Maya'da `ml.show_ui()` → gönder, Blender'da N-panel'de
`Build` numarasını doğrula, status satırını ve System Console'daki
`mLender warning:` satırlarını getir.
