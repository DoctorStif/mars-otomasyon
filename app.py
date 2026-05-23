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
    await page.goto(f"http://mars.egebt.com/uretim?I={is_no}")
    await page.wait_for_load_state("networkidle")

    basla_btn = await page.query_selector("button:has-text('Basla'), .btn:has-text('Basla')")
    if basla_btn:
        await basla_btn.click()
        await page.wait_for_timeout(1500)
        await page.wait_for_load_state("networkidle")

    satirlar = await page.query_selector_all("tr")
    hedef_btn = None
    for satir in satirlar:
        satir_text = (await satir.inner_text()).lower()
        op_lower = operasyon.lower().replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
        satir_norm = satir_text.replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
        if op_lower in satir_norm:
            btn = await satir.query_selector("button:has-text('Üretim'), button:has-text('Üretimde'), .btn-success, .btn-info")
            if btn:
                hedef_btn = btn
                break

    if not hedef_btn:
        hedef_btn = await page.query_selector("button:has-text('Uretim'), button:has-text('Üretim'), button:has-text('Üretimde'), .btn-success, .btn-info")

    if not hedef_btn:
        log(f"Uretim butonu bulunamadi: {is_no}", "uyari")
        return False

    await hedef_btn.click()
    await page.wait_for_timeout(1500)

    modal = await page.query_selector(".modal, [role='dialog']")
    if not modal:
        log("Modal acilmadi!", "uyari")
        return False

    miktar_input = await page.query_selector(".modal input[type='number']:first-of-type, input[placeholder*='Onayli']")
    if miktar_input:
        await miktar_input.triple_click()
        await miktar_input.fill(str(miktar))

    if recete_no:
        try:
            sel = await page.query_selector(".modal select:nth-of-type(1)")
            if sel:
                await sel.select_option(label=recete_no)
        except:
            pass

    if makine_no:
        try:
            sel = await page.query_selector(".modal select:nth-of-type(2)")
            if sel:
                await sel.select_option(label=makine_no)
        except:
            pass

    await page.wait_for_timeout(500)
    sonraki = await page.query_selector("button:has-text('Sonraki')")
    if sonraki:
        await sonraki.click()
        await page.wait_for_timeout(2000)
        log(f"Tamamlandi: {is_no} - {makine_no}", "basari")
        return True
    log("Sonraki Islem butonu yok!", "uyari")
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
