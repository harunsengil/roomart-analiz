"""
Rakip Analiz Scripti
Rani Mobilya, Vivense, MinarMobilya ve diğer rakiplerin
Trendyol verilerini çeker ve karşılaştırmalı analiz üretir.
"""
import json, os, re, time, random
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Rakip mağaza listesi ──────────────────────────────
RAKIPLER = {
    'rani':    {
        'ad':  'Rani Mobilya',
        'url': 'https://www.trendyol.com/magaza/rani-mobilya-m-106735?sst=0&channelId=1&pi={}',
        'renk': '#e63946'
    },
    'minar':   {
        'ad':  'Minar Mobilya',
        'url': 'https://www.trendyol.com/magaza/minarmobilya-m-185414?sst=0&channelId=1&pi={}',
        'renk': '#457b9d'
    },
    'vivense': {
        'ad':  'Vivense',
        'url': 'https://www.trendyol.com/magaza/vivense-m-106268?sst=0&channelId=1&pi={}',
        'renk': '#2a9d8f'
    },
}

OUTPUT_FILE = 'data/rakipler.json'
MAX_SAYFA   = 3       # Her rakip için max sayfa (hız için)
MAX_URUN    = 100     # Her rakipten max ürün

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/118.0.0.0 Safari/537.36",
]

def bekle(a=1.0, b=2.5):
    time.sleep(random.uniform(a, b))

def json_kaydet(dosya, veri):
    os.makedirs(os.path.dirname(dosya), exist_ok=True)
    with open(dosya, 'w', encoding='utf-8') as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)

# ── Mağaza listesinden ürün özeti çek (detay sayfasına girmeden) ──
def magaza_ozet_cek(page, magaza_url, max_sayfa=3, max_urun=100):
    """
    Mağaza liste sayfasından hızlı özet veri çeker.
    Her ürün için: ad, fiyat, yorum sayısı, puan, url
    Detay sayfasına girmez → çok daha hızlı.
    """
    urunler = []
    sayfa = 1

    while sayfa <= max_sayfa and len(urunler) < max_urun:
        url = magaza_url.format(sayfa)
        try:
            page.goto(url, timeout=30000)
            page.wait_for_load_state('domcontentloaded', timeout=15000)
            bekle(1.5, 3.0)
            page.keyboard.press('Escape')

            for _ in range(4):
                page.keyboard.press('End')
                bekle(0.5, 0.8)

            # Ürün kartlarını bul
            kartlar = page.query_selector_all('div.p-card-wrppr')
            if not kartlar:
                break

            for kart in kartlar:
                if len(urunler) >= max_urun:
                    break
                try:
                    # Ürün adı
                    ad_el = kart.query_selector('span.prdct-desc-cntnr-name, h3.prdct-name')
                    ad = ad_el.inner_text().strip() if ad_el else '—'

                    # Fiyat
                    fiyat_el = kart.query_selector('div.prc-box-dscntd, span.prc-box-dscntd, div.prc-box')
                    fiyat = 0
                    if fiyat_el:
                        fiyat_str = re.sub(r'[^\d,]', '', fiyat_el.inner_text())
                        fiyat = float(fiyat_str.replace(',', '.') or '0')

                    # Puan
                    puan_el = kart.query_selector('span.rating-score')
                    puan = float(puan_el.inner_text().strip()) if puan_el else 0

                    # Yorum sayısı
                    deg_el = kart.query_selector('span.ratingCount, span.review-count')
                    deg = 0
                    if deg_el:
                        deg = int(re.sub(r'[^\d]', '', deg_el.inner_text()) or '0')

                    # URL
                    link_el = kart.query_selector('a')
                    href = link_el.get_attribute('href') if link_el else ''
                    urun_url = 'https://www.trendyol.com' + href if href.startswith('/') else href

                    if ad != '—' and fiyat > 0:
                        urunler.append({
                            'ad':    ad[:60],
                            'fiyat': round(fiyat, 2),
                            'puan':  round(puan, 2),
                            'deg':   deg,
                            'url':   urun_url,
                        })
                except Exception:
                    continue

            print(f"    Sayfa {sayfa}: {len(kartlar)} kart, toplam {len(urunler)} ürün")

            # Sonraki sayfa var mı?
            sonraki = page.query_selector("a[title='Sonraki Sayfa']")
            if not sonraki:
                break
            sayfa += 1
            bekle(1.5, 2.5)

        except Exception as e:
            print(f"    [HATA] Sayfa {sayfa}: {e}")
            break

    return urunler

# ── Rakip özet istatistikleri hesapla ─────────────────
def ozet_hesapla(urunler):
    if not urunler:
        return {}
    fiyatlar = [u['fiyat'] for u in urunler if u['fiyat'] > 0]
    puanlar  = [u['puan']  for u in urunler if u['puan']  > 0]
    deglar   = [u['deg']   for u in urunler if u['deg']   > 0]

    return {
        'urun_sayisi':      len(urunler),
        'ort_fiyat':        round(sum(fiyatlar) / len(fiyatlar), 2) if fiyatlar else 0,
        'min_fiyat':        round(min(fiyatlar), 2) if fiyatlar else 0,
        'max_fiyat':        round(max(fiyatlar), 2) if fiyatlar else 0,
        'ort_puan':         round(sum(puanlar)  / len(puanlar),  2) if puanlar  else 0,
        'toplam_deg':       sum(deglar),
        'ort_deg':          round(sum(deglar)   / len(deglar),   1) if deglar   else 0,
        'en_cok_deg':       max(urunler, key=lambda x: x['deg'])  if urunler else {},
        'en_ucuz':          min(urunler, key=lambda x: x['fiyat'] if x['fiyat']>0 else 999999) if urunler else {},
        'en_pahali':        max(urunler, key=lambda x: x['fiyat']) if urunler else {},
    }

# ── Ana işlem ─────────────────────────────────────────
def rakip_analizi_calistir():
    tarih   = datetime.now().strftime('%Y-%m-%d')
    sonuclar = {
        'tarih':   tarih,
        'rakipler': {}
    }

    with sync_playwright() as p:
        ua      = random.choice(USER_AGENTS)
        browser = p.chromium.launch(headless=True)
        page    = browser.new_context(
            user_agent=ua,
            viewport={'width': random.randint(1280,1920), 'height': 900},
            locale='tr-TR',
        ).new_page()

        for key, rakip in RAKIPLER.items():
            print(f"\n[{rakip['ad']}] Veriler çekiliyor...")
            urunler = magaza_ozet_cek(page, rakip['url'], MAX_SAYFA, MAX_URUN)

            if not urunler:
                print(f"  [UYARI] {rakip['ad']} için veri gelmedi.")
                continue

            ozet = ozet_hesapla(urunler)
            sonuclar['rakipler'][key] = {
                'ad':    rakip['ad'],
                'renk':  rakip['renk'],
                'ozet':  ozet,
                'urunler': urunler[:50],  # İlk 50 ürün detay olarak sakla
            }

            print(f"  ✓ {len(urunler)} ürün | Ort. {ozet['ort_fiyat']:,.0f} TL | "
                  f"Ort. puan {ozet['ort_puan']} | Top. {ozet['toplam_deg']:,} deg.")

        browser.close()

    # Roomart karşılaştırma verisi ekle
    try:
        with open('data/urunler.json', encoding='utf-8') as f:
            roomart_data = json.load(f)
        roomart_urunler = roomart_data.get('urunler', [])
        sonuclar['roomart'] = {
            'ad':   'Roomart',
            'renk': '#1D3557',
            'ozet': {
                'urun_sayisi':  len(roomart_urunler),
                'ort_fiyat':    round(sum(u['fiyat'] for u in roomart_urunler if u['fiyat']>0)
                                      / max(len([u for u in roomart_urunler if u['fiyat']>0]),1), 2),
                'ort_puan':     round(sum(u['puan'] for u in roomart_urunler if u['puan']>0)
                                      / max(len([u for u in roomart_urunler if u['puan']>0]),1), 2),
                'toplam_deg':   sum(u['deg'] for u in roomart_urunler),
                'ort_deg':      round(sum(u['deg'] for u in roomart_urunler)
                                      / max(len(roomart_urunler),1), 1),
            }
        }
    except Exception as e:
        print(f"[UYARI] Roomart verisi okunamadı: {e}")

    json_kaydet(OUTPUT_FILE, sonuclar)
    print(f"\n[TAMAMLANDI] Rakip analizi → {OUTPUT_FILE}")

    # Özet rapor
    print("\n" + "="*55)
    print(f"{'Marka':<20} {'Ürün':>6} {'Ort.Fiyat':>12} {'Ort.Puan':>10} {'Top.Deg':>10}")
    print("="*55)
    if 'roomart' in sonuclar:
        r = sonuclar['roomart']['ozet']
        print(f"{'ROOMART':<20} {r['urun_sayisi']:>6} {r['ort_fiyat']:>12,.0f} {r['ort_puan']:>10.2f} {r['toplam_deg']:>10,}")
    for key, v in sonuclar['rakipler'].items():
        r = v['ozet']
        print(f"{v['ad']:<20} {r['urun_sayisi']:>6} {r['ort_fiyat']:>12,.0f} {r['ort_puan']:>10.2f} {r['toplam_deg']:>10,}")

if __name__ == '__main__':
    rakip_analizi_calistir()
