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
    storage = await page.evaluate("""() => ({
        ls: JSON.stringify(localStorage).substring(0,150),
        ss: JSON.stringify(sessionStorage).substring(0,150),
        ck: document.cookie.substring(0,150)
    })""")
    log(f"  ls: {storage['ls']}")
    log(f"  ss: {storage['ss']}")
    log(f"  ck: {storage['ck']}")
    log("Giris basarili!", "basari")

async def is_emri_isle(page, is_no, miktar, recete_no, makine_no, operasyon):
    log(f"Is emri: {is_no} | Op: {operasyon} | Makine: {makine_no}")
    # SPA navigation - page.goto yerine window.location kullan
    await page.evaluate(f"window.location.href = '/uretim?I={is_no}'")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(3000)

    if "login" in page.url:
        raise Exception("Oturum sona erdi!")

    log(f"  URL: {page.url}")
    satir_sayisi = await page.evaluate("document.querySelectorAll('tbody tr').length")
    log(f"  Satir sayisi: {satir_sayisi}")

    if satir_sayisi == 0:
        for i in range(15):
            await page.wait_for_timeout(1000)
            satir_sayisi = await page.evaluate("document.querySelectorAll('tbody tr').length")
            if satir_sayisi > 0:
                log(f"  {i+1}. saniyede {satir_sayisi} satir bulundu")
                break

    if satir_sayisi == 0:
        log("  Tablo yuklenemedi!", "hata")
        return False

    # Operasyonu JS ile bul ve tikla
    op_norm = operasyon.lower().replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
    
    buton_tiklandi = await page.evaluate(f"""
        () => {{
            const opAra = "{op_norm}";
            const satirlar = document.querySelectorAll('tbody tr');
            for (let satir of satirlar) {{
                const tdler = satir.querySelectorAll('td');
                if (tdler.length < 2) continue;
                const opText = tdler[1].textContent.toLowerCase()
                    .replace(/[ğ]/g,'g').replace(/[ü]/g,'u').replace(/[ş]/g,'s')
                    .replace(/[ı]/g,'i').replace(/[ö]/g,'o').replace(/[ç]/g,'c');
                if (opText.includes(opAra)) {{
                    const btn = tdler[0].querySelector('button');
                    if (btn && !btn.disabled) {{
                        btn.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }}
    """)

    if not buton_tiklandi:
        log(f"  '{operasyon}' butonu bulunamadi veya disabled!", "uyari")
        return False

    log(f"  Buton tiklandi, modal bekleniyor...")
    await page.wait_for_timeout(2000)

    # Modal acildi mi JS ile kontrol et
    modal_var = await page.evaluate("!!document.querySelector('.production-dialog__panel')")
    if not modal_var:
        log("  Modal acilmadi!", "uyari")
        return False

    log("  Modal acildi, veriler giriliyor...")

    # Onayli Miktar
    await page.evaluate(f"""
        () => {{
            const input = document.querySelector('.production-dialog__metric--ok input');
            if (input) {{
                input.value = '';
                input.dispatchEvent(new Event('input', {{bubbles: true}}));
            }}
        }}
    """)
    miktar_input = await page.query_selector(".production-dialog__metric--ok input")
    if miktar_input:
        await miktar_input.click()
        await miktar_input.triple_click()
        await miktar_input.type(str(miktar))
        log(f"  Miktar girildi: {miktar}")

    # Kalite kontrolleri - tum OK/NOK selectleri OK yap
    await page.evaluate("""
        () => {
            document.querySelectorAll('.production-dialog__quality-item select').forEach(sel => {
                sel.value = 'OK';
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            });
        }
    """)

    # Recete No
    if recete_no:
        try:
            await page.evaluate(f"""
                () => {{
                    const sels = document.querySelectorAll('.production-dialog__form-grid select');
                    if (sels[0]) {{
                        sels[0].value = '{recete_no}';
                        sels[0].dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)
            log(f"  Recete girildi: {recete_no}")
        except Exception as e:
            log(f"  Recete hatasi: {e}", "uyari")

    # Makine No - "Kumlama-1" -> "1"
    if makine_no:
        try:
            makine_sayi = makine_no.split("-")[-1].strip()
            await page.evaluate(f"""
                () => {{
                    const sels = document.querySelectorAll('.production-dialog__form-grid select');
                    if (sels[1]) {{
                        sels[1].value = '{makine_sayi}';
                        sels[1].dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)
            log(f"  Makine girildi: {makine_sayi}")
        except Exception as e:
            log(f"  Makine hatasi: {e}", "uyari")

    await page.wait_for_timeout(500)

    # Sonraki Islem butonu
    sonraki_tiklandi = await page.evaluate("""
        () => {
            const footer = document.querySelector('.production-dialog__footer');
            if (!footer) return false;
            const btns = footer.querySelectorAll('button');
            for (let btn of btns) {
                if (btn.textContent.includes('Sonraki')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }
    """)

    if sonraki_tiklandi:
        await page.wait_for_timeout(2000)
        log(f"  Tamamlandi: {is_no} - {makine_no}", "basari")
        return True
    else:
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
