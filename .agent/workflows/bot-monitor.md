---
description: Live trading bot kontrol ve izleme workflow'u
---

# Bot İzleme Workflow'u

// turbo-all

Bu workflow her 12 saatte veya kullanıcı istediğinde çalıştırılır.

## 1. Hesap durumunu kontrol et
```bash
python /tmp/check_account.py
```
Bu script `logs/performance_dayX.txt` dosyasına sonuçları yazar.

## 2. Sonuçları oku
`logs/` klasöründeki en son performance raporunu oku:
```bash
dir logs\performance_*.txt /o:-d /b
```
En son dosyayı aç ve sonuçları kullanıcıyla paylaş.

## 3. Railway loglarını kontrol et (opsiyonel)
Eğer Railway CLI login yapılmışsa:
```bash
railway logs --project 0d97dbfa-b66b-47df-b72b-916bcae83aca
```

## 4. Kontrol listesi
Her kontrolde şunları değerlendir:
- [ ] Günlük P/L pozitif mi?
- [ ] $150 pozisyon limiti aşılmamış mı?
- [ ] Equity floor ($400) altına düşmemiş mi?
- [ ] Kaskad satış (aynı coin çoklu satış) var mı?
- [ ] Bot aktif mi (son 12 saatte işlem yapmış mı)?
- [ ] Hata logları var mı?

## 5. Sorun varsa
- Hemen kullanıcıya bildir
- Gerekirse acil fix yap ve deploy et
