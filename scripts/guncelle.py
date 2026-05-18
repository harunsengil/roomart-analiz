"""
GitHub Actions üzerinde çalışan güncelleme scripti.
Her Pazartesi Trendyol'dan veri çeker, snapshots ve urunler.json'u günceller.
"""
import json, os, re, time
from datetime import datetime
from playwright.sync_api import sync_playwright

MAGAZA_URL    = "https://www.trendyol.com/magaza/roomart-m-362387?sst=0&channelId=1&pi={}"
URUNLER_FILE  = "data/urunler.json"
SNAPSHOT_FILE = "data/snapshots.json"

FONK_KAT = {
    'Lavabolu': 'lavabolu', 'Aynalı': 'ust', 'Aynal': 'ust',
    'Kapaklı': 'banyo', 'Kapaklı + Çekmeceli': 'banyo',
    'Çekmeceli': 'banyo', 'Sepetli': 'banyo', 'Aynasız': 'banyo',
    'Çamaşır Makinesi Dolabı': 'camasir', 'Sabit': 'kiler', 'Belirtilmemiş': 'banyo',
}
TRENDS = {
    'banyo':    {'ad': 'Banyo Dolabi',          'ort': 83.8, 'buyume': 12.5,  'trend': 'Yukseliyor'},
    'camasir':  {'ad': 'Camasir Mak. Dolabi',   'ort': 18.2, 'buyume': 16.7,  'trend': 'Yukseliyor'},
    'kiler':    {'ad': 'Kiler Dolabi',           'ort': 71.5, 'buyume': -10.4, 'trend': 'Dusuyor'},
    'lavabolu': {'ad': 'Lavabolu Banyo Dolabi',  'ort': 3.6,  'buyume': -17.6, 'trend': 'Dusuyor'},
    'ust':      {'ad': 'Banyo Ust Dolabi',       'ort': 0.3,  'buyume': -49.5, 'trend': 'Dusuyor'},
}

def snapshots_yukle():
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}

def snapshots_kaydet(data):
    with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

def veri_cek():
    urunler = []
    snapshots = snapshots_yukle()
    tarih = datetime.now().strftime('%Y-%m-%d')

    if tarih in snapshots:
        print(f"[BİLGİ] Bugün ({tarih}) için snapshot zaten var.")
        snap = snapshots[tarih]
    else:
        snap = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )).new_page()

        sayfa = 1
        tum_urller = []

        # URL topla
        while True:
            url = MAGAZA_URL.format(sayfa)
            print(f"[Sayfa {sayfa}] URL toplanıyor...")
            page.goto(url)
            page.wait_for_load_state('domcontentloaded')
            time.sleep(2)
            page.keyboard.press('Escape')

            for _ in range(5):
                page.keyboard.press('End')
                time.sleep(0.6)

            yeni = []
            for a in page.query_selector_all("a[href*='-p-']"):
                href = a.get_attribute('href')
                if href:
                    tam = 'https://www.trendyol.com' + href if href.startswith('/') else href
                    if tam not in tum_urller:
                        yeni.append(tam)

            if not yeni:
                break
            tum_urller.extend(yeni)
            print(f"  → {len(yeni)} URL. Toplam: {len(tum_urller)}")

            sonraki = page.query_selector("a[title='Sonraki Sayfa']")
            if not sonraki:
                break
            sayfa += 1
            time.sleep(1)

        print(f"\n[VERİ] {len(tum_urller)} ürün sayfası işlenecek...")

        # Detay çek
        for url in tum_urller:
            try:
                page.goto(url)
                page.wait_for_load_state('domcontentloaded')
                time.sleep(1.2)
                page.keyboard.press('Escape')

                try:
                    ad = page.get_by_test_id('product-title').inner_text().strip()
                except:
                    ad = '—'

                try:
                    fel = page.query_selector('span.discounted') or page.query_selector('span.prc-dsc')
                    fiyat = float(re.sub(r'[^\d,]', '', fel.inner_text()).replace(',', '.') or '0') if fel else 0
                except:
                    fiyat = 0

                try:
                    pel = page.query_selector('span.reviews-summary-average-rating')
                    puan = float(pel.inner_text().strip()) if pel else 0
                except:
                    puan = 0

                try:
                    draw = page.get_by_test_id('review-info-link').inner_text()
                    deg = int(re.sub(r'[^\d]', '', draw) or '0')
                except:
                    deg = 0

                try:
                    satici = page.get_by_test_id('store-link').inner_text().strip()
                except:
                    satici = 'ROOMART'

                ozellikler = ozellikleri_cek(page)
                fonk = ozellikler.get('Fonksiyon', '')
                kat  = FONK_KAT.get(fonk, 'banyo')
                tr   = TRENDS.get(kat, {'buyume': 0, 'trend': 'Stabil'})
                pid  = url.split('-p-')[-1].split('?')[0] if '-p-' in url else ''

                # Haftalık değişim
                onceki_snap = {}
                tarihler = sorted(snapshots.keys())
                if tarihler:
                    onceki_snap = snapshots[tarihler[-1]]
                haftalik = deg - onceki_snap.get(pid, {}).get('deg', deg)

                snap[pid] = {'ad': ad[:60], 'deg': deg, 'fiyat': fiyat, 'puan': puan}

                urunler.append({
                    'ad':        ad.replace('ROOMART ', '')[:60],
                    'fiyat':     round(fiyat, 2),
                    'puan':      round(puan, 2),
                    'deg':       deg,
                    'snap_deg':  deg,
                    'haftalik':  haftalik,
                    'fonk':      fonk,
                    'bcg':       '',  # sonra hesaplanacak
                    'url':       url,
                    'kat':       kat,
                    'kat_buyume': tr['buyume'],
                    'kat_trend':  tr['trend'],
                    'pid':        pid,
                })
                print(f"  ✓ {ad[:45]} | {deg} deg. | Δ{haftalik:+d}")
                time.sleep(0.8)
            except Exception as e:
                print(f"  [HATA] {e}")

        browser.close()

    # BCG hesapla
    plot = [u for u in urunler if u['deg'] > 0 and u['puan'] > 0]
    if plot:
        degs  = sorted([u['deg']  for u in plot])
        puans = sorted([u['puan'] for u in plot])
        DE = degs[len(degs)//2]
        PE = puans[len(puans)//2]
    else:
        DE, PE = 24, 4.6

    def bcg(u):
        if u['deg']>=DE and u['puan']>=PE: return 'Yildiz'
        if u['deg']>=DE and u['puan']< PE: return 'NakitInek'
        if u['deg']< DE and u['puan']>=PE: return 'SoruIsareti'
        return 'Kopek'

    for u in urunler:
        u['bcg'] = bcg(u)

    # Snapshot kaydet
    snapshots[tarih] = snap
    snapshots_kaydet(snapshots)

    # urunler.json güncelle
    with open(URUNLER_FILE, encoding='utf-8') as f:
        mevcut = json.load(f)

    mevcut['meta']['guncelleme'] = tarih
    mevcut['meta']['urun_sayi']  = len(urunler)
    mevcut['meta']['de'] = DE
    mevcut['meta']['pe'] = PE
    mevcut['urunler'] = urunler

    with open(URUNLER_FILE, 'w', encoding='utf-8') as f:
        json.dump(mevcut, f, ensure_ascii=False, indent=2)

    print(f"\n[TAMAMLANDI] {len(urunler)} ürün güncellendi.")

if __name__ == '__main__':
    veri_cek()
