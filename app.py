from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import threading
import os
from datetime import datetime
from playwright.async_api import async_playwright

app = Flask(__name__)
CORS(app)

durum = {
    "calisıyor": False,
    "mesajlar": [],
    "tur": 0,
    "son_islem": None
}

def log(mesaj, tip="info"):
    zaman = datetime.now().strftime("%H:%M:%S")
    durum["mesajlar"].append({"zaman": zaman, "mesaj": mesaj, "tip": tip})
    if len(durum["mesajlar"]) > 100:
        durum["mesajlar"] = durum["mesajlar"][-100:]
    print(f"[{zaman}] {mesaj}")

async def login(page, kullanici, sifre):
    log("Giris yapiliyor...")
    await page.goto("http://mars.egebt.com/login")
    await page.wait_for_load_state("networkidle")
    await page.fill('input[name="username"], input[type="text"]', kullanici)
    await page.fill('input[name="password"], input[type="password"]', sifre)
    await page.click('button:has-text("Giriş yap"), button:has-text("Giris yap"), button[type="submit"], input[type="submit"]')
    await page.wait_for_load_state("networkidle")
    if "login" in page.url:
        raise Exception("Giris basarisiz!")
    log("Giris basarili!", "basari")

async def is_emri_isle(page, is_no, miktar, recete_no, makine_no, operasyon):
    log(f"Is emri: {is_no} | Op: {operasyon} | Makine: {makine_no}")
    await page.goto(f"http://mars.egebt.com/uretim?I={is_no}", wait_until="domcontentloaded")

    if "login" in page.url:
        raise Exception("Oturum sona erdi, yeniden baslatin.")

    # Vue render icin polling bekle - max 30 saniye
    tum_satirlar = []
    for i in range(30):
        await page.wait_for_timeout(1000)
        tum_satirlar = await page.query_selector_all("tbody tr")
        if len(tum_satirlar) > 0:
            log(f"  Tablo {i+1}. saniyede yuklendi, {len(tum_satirlar)} satir")
            break
    
    if len(tum_satirlar) == 0:
        log("  Tablo yuklenemedi!", "hata")
        return False

    basla_btn = await page.query_selector(".btn-primary:has-text('Basla'), .btn:has-text('Basla')")
    if basla_btn:
        await basla_btn.click()
        await page.wait_for_timeout(2000)
        tum_satirlar = await page.query_selector_all("table tbody tr")

    # Tablodaki her satiri gez: buton 1. td'de, operasyon adi 2. td'de
    tum_satirlar = await page.query_selector_all("table tbody tr")
    hedef_btn = None
    op_norm = operasyon.lower().replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
    log(f"  Toplam {len(tum_satirlar)} satir bulundu")
    for satir in tum_satirlar:
        op_td = await satir.query_selector("td:nth-child(2)")
        if not op_td:
            continue
        op_text = (await op_td.inner_text()).lower()
        op_text_norm = op_text.replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
        log(f"  Satir: {op_text.strip()}")
        if op_norm in op_text_norm:
            btn = await satir.query_selector("td:first-child button")
            if btn:
                hedef_btn = btn
                log(f"  Buton bulundu: {op_text.strip()}", "basari")
                break

    if not hedef_btn:
        log(f"'{operasyon}' icin buton bulunamadi!", "uyari")
        return False

    await hedef_btn.click()
    # production-dialog'un acilmasini bekle
    await page.wait_for_selector(".production-dialog__panel", timeout=10000)
    log("  Modal acildi")

    # Onayli Miktar - production-dialog__metric--ok icindeki input
    miktar_input = await page.query_selector(".production-dialog__metric--ok input")
    if miktar_input:
        await miktar_input.triple_click()
        await miktar_input.fill(str(miktar))
        log(f"  Miktar girildi: {miktar}")

    # Kalite kontrolleri: OK/NOK select'lerini OK yap
    kalite_selectler = await page.query_selector_all(".production-dialog__quality-item select.form-select")
    for sel in kalite_selectler:
        try:
            await sel.select_option(value="OK")
        except:
            pass

    # Recete No - production-dialog__form-grid icindeki ilk select
    if recete_no:
        try:
            sel = await page.query_selector(".production-dialog__form-grid select:nth-of-type(1)")
            if sel:
                await sel.select_option(value=recete_no)
                log(f"  Recete secildi: {recete_no}")
        except Exception as e:
            log(f"  Recete secilemedi: {e}", "uyari")

    # Makine No - production-dialog__form-grid icindeki ikinci select (deger 1-5)
    if makine_no:
        try:
            # makine_no "Kumlama-1" gibi geliyor, sayiyi al
            makine_sayi = makine_no.split("-")[-1].strip()
            sel = await page.query_selector(".production-dialog__form-grid select:nth-of-type(2)")
            if sel:
                await sel.select_option(value=makine_sayi)
                log(f"  Makine secildi: {makine_sayi}")
        except Exception as e:
            log(f"  Makine secilemedi: {e}", "uyari")

    await page.wait_for_timeout(500)
    sonraki = await page.query_selector(".production-dialog__footer .btn-primary")
    if sonraki:
        await sonraki.click()
        await page.wait_for_timeout(2000)
        log(f"  Tamamlandi: {is_no} - {makine_no}", "basari")
        return True
    log("  Sonraki Islem butonu yok!", "uyari")
    return False

async def otomasyon_dongu(config):
    durum["calisıyor"] = True
    durum["tur"] = 0
    log("Otomasyon basladi", "basari")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await login(page, config["kullanici"], config["sifre"])

            while durum["calisıyor"]:
                durum["tur"] += 1
                log(f"Tur #{durum['tur']} basladi")
                operasyon = config.get("operasyon", "Yag alma")
                makineler = config.get("makineler", [""])
                if not makineler:
                    makineler = [""]
                basarili = 0
                toplam = 0

                for is_no in config["is_emirleri"]:
                    if not durum["calisıyor"]:
                        break
                    for makine in makineler:
                        if not durum["calisıyor"]:
                            break
                        toplam += 1
                        try:
                            if await is_emri_isle(page, is_no, config["miktar"], config.get("recete",""), makine, operasyon):
                                basarili += 1
                        except Exception as e:
                            log(f"Hata ({is_no}/{makine}): {e}", "hata")

                durum["son_islem"] = datetime.now().strftime("%H:%M:%S")
                log(f"Tur #{durum['tur']} bitti. {basarili}/{toplam} islendi. {config['tekrar_dk']} dk bekleniyor...")

                for _ in range(config["tekrar_dk"] * 60):
                    if not durum["calisıyor"]:
                        break
                    await asyncio.sleep(1)

            await browser.close()
    except Exception as e:
        log(f"Kritik hata: {e}", "hata")
    finally:
        durum["calisıyor"] = False
        log("Otomasyon durduruldu.")

def thread_baslat(config):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(otomasyon_dongu(config))
    loop.close()

@app.route('/')
def index():
    return open('/app/index.html', encoding='utf-8').read()

@app.route('/baslat', methods=['POST'])
def baslat():
    if durum["calisıyor"]:
        return jsonify({"ok": False, "mesaj": "Zaten calisiyor!"})
    t = threading.Thread(target=thread_baslat, args=(request.json,), daemon=True)
    t.start()
    return jsonify({"ok": True})

@app.route('/durdur', methods=['POST'])
def durdur():
    durum["calisıyor"] = False
    return jsonify({"ok": True})

@app.route('/durum')
def durum_al():
    return jsonify(durum)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
