"""
Roomart Trendyol Veri Güncelleme Scripti
- Retry mekanizması (tenacity)
- Rastgele delay + user agent pool (bot koruması)
- Veri doğrulama (anomali filtresi)
- pytrends otomatik güncelleme
- Haftalık büyüme hesabı
"""
import json, os, re, time, random
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Ayarlar ───────────────────────────────────────────
MAGAZA_URL    = "https://www.trendyol.com/magaza/roomart-m-362387?sst=0&channelId=1&pi={}"
URUNLER_FILE  = "data/urunler.json"
SNAPSHOT_FILE = "data/snapshots.json"
MAX_RETRY     = 3
MIN_URUN      = 50   # Bu sayının altında veri gelirse hata say

# ── User agent havuzu (bot tespitini zorlaştırır) ─────
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]

# ── Fonksiyon → Kategori eşleştirmesi ────────────────
FONK_KAT = {
    'Lavabolu': 'lavabolu', 'Aynalı': 'ust', 'Aynal': 'ust',
    'Kapaklı': 'banyo', 'Kapaklı + Çekmeceli': 'banyo',
    'Çekmeceli': 'banyo', 'Sepetli': 'banyo', 'Aynasız': 'banyo',
    'Çamaşır Makinesi Dolabı': 'camasir', 'Sabit': 'kiler',
    'Belirtilmemiş': 'banyo',
}

# ── Rastgele bekleme (bot koruması) ───────────────────
def bekle(min_s=1.2, max_s=3.2):
    time.sleep(random.uniform(min_s, max_s))

# ── Dosya işlemleri ───────────────────────────────────
def json_yukle(dosya, varsayilan={}):
    if os.path.exists(dosya):
        with open(dosya, encoding='utf-8') as f:
            return json.load(f)
    return varsayilan

def json_kaydet(dosya, veri):
    os.makedirs(os.path.dirname(dosya), exist_ok=True)
    with open(dosya, 'w', encoding='utf-8') as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)

# ── Veri doğrulama ────────────────────────────────────
def veri_gecerli_mi(u):
    """Bozuk veya anlamsız veriyi filtrele"""
    if not u.get('ad') or u['ad'] == '—':
        return False
    if u.get('fiyat', 0) <= 0:
        return False
    if u.get('fiyat', 0) > 500000:   # 500K TL üstü muhtemelen hatalı
        return False
    if u.get('deg', 0) < 0:
        return False
    return True

# ── Google Trends verisi çek ──────────────────────────
def trends_guncelle():
    print("[TRENDS] Google Trends verisi çekiliyor...")
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl='tr-TR', tz=180, timeout=(10, 25))

        kategoriler = {
            'banyo':    'banyo dolabı',
            'camasir':  'çamaşır makinesi dolabı',
            'kiler':    'kiler dolabı',
            'lavabolu': 'lavabolu banyo dolabı',
            'ust':      'banyo üst dolabı',
        }

        sonuclar = {}
        gruplar = [list(kategoriler.items())[i:i+4] for i in range(0, len(kategoriler), 4)]

        for grup in gruplar:
            anahtar_kelimeler = [v for _, v in grup]
            try:
                pt.build_payload(anahtar_kelimeler, timeframe='today 12-m', geo='TR')
                df = pt.interest_over_time()
                if df.empty:
                    continue
                for key, kw in grup:
                    if kw in df.columns:
                        seri = df[kw]
                        ilk4 = seri.head(4).mean()
                        son4 = seri.tail(4).mean()
                        buyume = round(((son4 - ilk4) / (ilk4 + 0.01)) * 100, 1)
                        # Aşırı değerleri sınırla (0→küçük değer durumu)
                        if abs(buyume) > 200:
                            buyume = 200 if buyume > 0 else -200
                        sonuclar[key] = {
                            'ad': {
                                'banyo': 'Banyo Dolabi', 'camasir': 'Camasir Mak. Dolabi',
                                'kiler': 'Kiler Dolabi', 'lavabolu': 'Lavabolu Banyo Dolabi',
                                'ust': 'Banyo Ust Dolabi'
                            }.get(key, key),
                            'ort':    round(float(seri.mean()), 1),
                            'buyume': buyume,
                            'trend':  'Yukseliyor' if buyume > 5 else ('Dusuyor' if buyume < -5 else 'Stabil')
                        }
                        print(f"  ✓ {key}: ort={sonuclar[key]['ort']}, büyüme={buyume}%")
                time.sleep(2)
            except Exception as e:
                print(f"  [TRENDS HATA] {e}")
                time.sleep(5)

        if len(sonuclar) >= 3:
            print(f"[TRENDS] {len(sonuclar)} kategori güncellendi.")
            return sonuclar
        else:
            print("[TRENDS] Yeterli veri gelmedi, mevcut veri korunuyor.")
            return None

    except Exception as e:
        print(f"[TRENDS HATA] {e} — mevcut veri korunuyor.")
        return None

# ── Sayfa özellikleri çek ─────────────────────────────
def ozellikleri_cek(page):
    hedef = {'Fonksiyon': '', 'Materyal': '', 'Kapak Sayısı': '', 'Dolap Ölçüsü': ''}
    try:
        for kart in page.query_selector_all('div.attribute-item'):
            try:
                k = kart.query_selector('div.name').inner_text().strip()
                v = kart.query_selector('div.value').inner_text().strip()
                if k in hedef:
                    hedef[k] = v
            except:
                continue
    except:
        pass
    return hedef

# ── Tek ürün verisi çek (retry ile) ──────────────────
def urun_cek(page, url, deneme=0):
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state('domcontentloaded', timeout=15000)
        bekle(1.0, 2.5)
        page.keyboard.press('Escape')

        # Ürün adı
        try:
            ad = page.get_by_test_id('product-title').inner_text(timeout=5000).strip()
        except:
            ad = '—'

        # Fiyat
        try:
            fel = (page.query_selector('span.discounted') or
                   page.query_selector('span.prc-dsc'))
            fiyat = float(re.sub(r'[^\d,]', '', fel.inner_text()).replace(',', '.') or '0') if fel else 0
        except:
            fiyat = 0

        # Puan
        try:
            pel = page.query_selector('span.reviews-summary-average-rating')
            puan = float(pel.inner_text().strip()) if pel else 0
        except:
            puan = 0

        # Değerlendirme
        try:
            draw = page.get_by_test_id('review-info-link').inner_text(timeout=5000)
            deg = int(re.sub(r'[^\d]', '', draw) or '0')
        except:
            deg = 0

        # Satıcı
        try:
            satici = page.get_by_test_id('store-link').inner_text(timeout=3000).strip()
        except:
            satici = 'ROOMART'

        ozellikler = ozellikleri_cek(page)
        pid = url.split('-p-')[-1].split('?')[0] if '-p-' in url else ''

        return {
            'ad': ad, 'fiyat': fiyat, 'puan': puan,
            'deg': deg, 'satici': satici, 'url': url,
            'fonk': ozellikler.get('Fonksiyon', ''),
            'materyal': ozellikler.get('Materyal', ''),
            'pid': pid,
        }

    except PWTimeout:
        if deneme < MAX_RETRY:
            bekle(3, 6)
            return urun_cek(page, url, deneme + 1)
        return None
    except Exception as e:
        if deneme < MAX_RETRY:
            bekle(2, 4)
            return urun_cek(page, url, deneme + 1)
        print(f"  [HATA] {url[:60]}: {e}")
        return None

# ── URL listesi topla ─────────────────────────────────
def urlleri_topla(page):
    tum_urller = []
    sayfa = 1

    while True:
        url = MAGAZA_URL.format(sayfa)
        print(f"[Sayfa {sayfa}] URL toplanıyor...")
        try:
            page.goto(url, timeout=30000)
            page.wait_for_load_state('domcontentloaded', timeout=15000)
            bekle(2, 3)
            page.keyboard.press('Escape')

            for _ in range(5):
                page.keyboard.press('End')
                bekle(0.5, 0.9)

            yeni = []
            for a in page.query_selector_all("a[href*='-p-']"):
                href = a.get_attribute('href')
                if href:
                    tam = 'https://www.trendyol.com' + href if href.startswith('/') else href
                    if tam not in tum_urller:
                        yeni.append(tam)

            if not yeni:
                print(f"  → Sayfa {sayfa} boş, toplama tamamlandı.")
                break

            tum_urller.extend(yeni)
            print(f"  → {len(yeni)} URL. Toplam: {len(tum_urller)}")

            sonraki = page.query_selector("a[title='Sonraki Sayfa']")
            if not sonraki:
                print("  → Son sayfa.")
                break
            sayfa += 1
            bekle(1.5, 2.5)

        except Exception as e:
            print(f"  [HATA] Sayfa {sayfa}: {e}")
            break

    return list(dict.fromkeys(tum_urller))

# ── Ana işlem ─────────────────────────────────────────
def veri_cek():
    tarih     = datetime.now().strftime('%Y-%m-%d')
    snapshots = json_yukle(SNAPSHOT_FILE, {})
    mevcut    = json_yukle(URUNLER_FILE, {'meta': {}, 'trends': {}, 'urunler': []})
    snap_bugun = {}

    # Önceki snapshot (büyüme hesabı için)
    tarihler    = sorted(snapshots.keys())
    onceki_snap = snapshots[tarihler[-1]] if tarihler else {}

    # Google Trends güncelle
    yeni_trends = trends_guncelle()
    trends = yeni_trends if yeni_trends else mevcut.get('trends', {})

    urunler = []

    with sync_playwright() as p:
        ua = random.choice(USER_AGENTS)
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent=ua,
            viewport={'width': random.randint(1280, 1920), 'height': random.randint(800, 1080)},
            locale='tr-TR',
        ).new_page()

        print(f"\n[VERİ] URL'ler toplanıyor... (UA: {ua[:40]}...)")
        tum_urller = urlleri_topla(page)
        print(f"\n[VERİ] {len(tum_urller)} URL işlenecek...\n")

        for i, url in enumerate(tum_urller):
            veri = urun_cek(page, url)
            if not veri:
                print(f"  [{i+1}/{len(tum_urller)}] Atlandı: {url[:50]}")
                continue

            # Veri doğrulama
            if not veri_gecerli_mi(veri):
                print(f"  [{i+1}/{len(tum_urller)}] Geçersiz veri, atlandı: {veri.get('ad','?')[:40]}")
                continue

            fonk    = veri['fonk']
            kat     = FONK_KAT.get(fonk, 'banyo')
            tr      = trends.get(kat, {'buyume': 0, 'trend': 'Stabil'})
            pid     = veri['pid']
            haftalik = veri['deg'] - onceki_snap.get(pid, {}).get('deg', veri['deg'])

            snap_bugun[pid] = {
                'ad': veri['ad'][:60], 'deg': veri['deg'],
                'fiyat': veri['fiyat'], 'puan': veri['puan']
            }

            urunler.append({
                'ad':         veri['ad'].replace('ROOMART ', '')[:60],
                'fiyat':      round(veri['fiyat'], 2),
                'puan':       round(veri['puan'], 2),
                'deg':        veri['deg'],
                'snap_deg':   veri['deg'],
                'haftalik':   haftalik,
                'fonk':       fonk,
                'materyal':   veri.get('materyal', ''),
                'bcg':        '',
                'url':        url,
                'kat':        kat,
                'kat_buyume': tr.get('buyume', 0),
                'kat_trend':  tr.get('trend', 'Stabil'),
                'pid':        pid,
            })
            print(f"  [{i+1}/{len(tum_urller)}] ✓ {veri['ad'][:45]} | {veri['deg']} deg | Δ{haftalik:+d}")

        browser.close()

    # Minimum veri kontrolü
    if len(urunler) < MIN_URUN:
        print(f"\n[HATA] Sadece {len(urunler)} ürün çekildi (min: {MIN_URUN}). Güncelleme iptal.")
        raise ValueError(f"Yetersiz veri: {len(urunler)} ürün")

    # BCG hesapla
    plot = [u for u in urunler if u['deg'] > 0 and u['puan'] > 0]
    degs  = sorted([u['deg']  for u in plot])
    puans = sorted([u['puan'] for u in plot])
    DE = float(degs[len(degs)//2])   if degs  else 24
    PE = float(puans[len(puans)//2]) if puans else 4.6

    def bcg(u):
        if u['deg']>=DE and u['puan']>=PE: return 'Yildiz'
        if u['deg']>=DE and u['puan']< PE: return 'NakitInek'
        if u['deg']< DE and u['puan']>=PE: return 'SoruIsareti'
        return 'Kopek'

    for u in urunler:
        u['bcg'] = bcg(u)

    # Snapshot kaydet
    snapshots[tarih] = snap_bugun
    # 12 haftadan eskiyi sil (storage tasarrufu)
    if len(snapshots) > 52:
        for eski in sorted(snapshots.keys())[:-52]:
            del snapshots[eski]

    json_kaydet(SNAPSHOT_FILE, snapshots)

    # urunler.json güncelle
    mevcut['meta'] = {
        'guncelleme': tarih,
        'urun_sayi':  len(urunler),
        'de':         DE,
        'pe':         PE,
        'kaynak':     'Trendyol + Google Trends TR',
        'snapshot_sayi': len(snapshots),
    }
    mevcut['trends']  = trends
    mevcut['urunler'] = urunler

    json_kaydet(URUNLER_FILE, mevcut)
    print(f"\n[TAMAMLANDI] {len(urunler)} ürün güncellendi. DE={DE}, PE={PE}")
    print(f"[SNAPSHOTS] Toplam {len(snapshots)} hafta birikti.")

if __name__ == '__main__':
    veri_cek()
