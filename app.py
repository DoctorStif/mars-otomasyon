from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import os
import requests
from datetime import datetime

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

def api_session_al(kullanici, sifre):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    })

    # 1. Login sayfasini ac, CSRF token al
    r = session.get("http://mars.egebt.com/login")
    log(f"  Login sayfasi: {r.status_code}")

    # XSRF-TOKEN cookie'den al
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    laravel_session = session.cookies.get("laravel_session", "")
    log(f"  XSRF: {xsrf[:30] if xsrf else 'YOK'}")
    log(f"  Session: {laravel_session[:20] if laravel_session else 'YOK'}")

    # HTML'den _token bul
    csrf_token = ""
    if "_token" in r.text:
        import re
        m = re.search(r'name="_token"\s+value="([^"]+)"', r.text)
        if m:
            csrf_token = m.group(1)
            log(f"  _token: {csrf_token[:20]}")

    # 2. Form ile login
    session.headers.update({
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "http://mars.egebt.com/login",
        "X-XSRF-TOKEN": requests.utils.unquote(xsrf) if xsrf else ""
    })

    login_data = {
        "_token": csrf_token,
        "email": kullanici,
        "password": sifre,
    }

    r2 = session.post("http://mars.egebt.com/login", data=login_data, allow_redirects=True)
    log(f"  Login POST: {r2.status_code}, URL: {r2.url}")

    # Başarılı mı kontrol et - login sayfasında değilsek başarılı
    if "login" not in r2.url:
        log("  Form login basarili!", "basari")
    else:
        # username ile de dene
        login_data2 = {
            "_token": csrf_token,
            "username": kullanici,
            "password": sifre,
        }
        r2 = session.post("http://mars.egebt.com/login", data=login_data2, allow_redirects=True)
        log(f"  Username login: {r2.status_code}, URL: {r2.url}")
        if "login" in r2.url:
            log("  Login basarisiz! Kullanici adi/sifre yanlis olabilir.", "hata")

    # Son XSRF token'i header'a ekle
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "http://mars.egebt.com/",
        "X-Requested-With": "XMLHttpRequest"
    })

    return session

def uretim_bilgisi_al(session, isemri_no):
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    r = session.post("http://mars.egebt.com/api/getUretim", json={"isemri_no": isemri_no})
    log(f"  getUretim: {r.status_code}")
    if r.status_code == 200:
        try:
            data = r.json()
            log(f"  Veri: {str(data)[:200]}")
            return data
        except:
            log(f"  JSON parse hatasi: {r.text[:100]}", "hata")
    else:
        log(f"  Hata: {r.text[:100]}", "hata")
    return None

def operasyon_guncelle(session, payload):
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    r = session.post("http://mars.egebt.com/api/updateOperationStatus", json=payload)
    log(f"  updateStatus: {r.status_code}, {r.text[:100]}")
    return r.status_code == 200

def is_emri_isle(session, isemri_no, miktar, recete_no, makine_no, operasyon):
    log(f"Is emri: {isemri_no} | Op: {operasyon} | Makine: {makine_no}")

    data = uretim_bilgisi_al(session, isemri_no)
    if not data:
        return False

    # Veri yapısını anla
    import json
    log(f"  Ham veri: {json.dumps(data)[:500]}")

    # Operasyon listesini bul
    operasyonlar = []
    if isinstance(data, list):
        operasyonlar = data
    elif isinstance(data, dict):
        for key in ["operasyonlar", "operations", "data", "items", "rows"]:
            if key in data and isinstance(data[key], list):
                operasyonlar = data[key]
                break
        if not operasyonlar:
            # Tek operasyon objesi olabilir
            operasyonlar = [data]

    log(f"  {len(operasyonlar)} operasyon bulundu")

    op_norm = operasyon.lower().replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
    hedef_op = None

    for op in operasyonlar:
        if not isinstance(op, dict):
            continue
        for key in ["operasyon_adi", "operation_name", "name", "adi", "title"]:
            val = str(op.get(key, "")).lower()
            val_norm = val.replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
            if op_norm in val_norm:
                hedef_op = op
                break
        if hedef_op:
            break

    if not hedef_op:
        if operasyonlar:
            log(f"  '{operasyon}' bulunamadi. Anahtarlar: {list(operasyonlar[0].keys()) if operasyonlar else []}", "uyari")
        return False

    op_id = hedef_op.get("id")
    quality_entries = hedef_op.get("quality_entries", [])

    for qe in quality_entries:
        if isinstance(qe, dict) and qe.get("control_type") == "oknok":
            qe["entered_value"] = "OK"
            qe["result_status"] = "OK"

    makine_sayi = str(makine_no).split("-")[-1].strip() if makine_no else ""

    payload = {
        "id": str(op_id),
        "status": "2",
        "quantity": str(miktar),
        "rejected_quantity": "0",
        "rejection_disposition": "",
        "rejection_notes": "",
        "machine_no": makine_sayi,
        "recipe_no": str(recete_no) if recete_no else "",
        "note1": "",
        "note2": "",
        "quality_entries": quality_entries
    }

    sonuc = operasyon_guncelle(session, payload)
    if sonuc:
        log(f"  Tamamlandi!", "basari")
    return sonuc

def otomasyon_dongu(config):
    durum["calisıyor"] = True
    durum["tur"] = 0
    log("Otomasyon basladi", "basari")
    import time

    try:
        session = api_session_al(config["kullanici"], config["sifre"])

        while durum["calisıyor"]:
            durum["tur"] += 1
            log(f"Tur #{durum['tur']} basladi")

            operasyon = config.get("operasyon", "Yag alma")
            makineler = config.get("makineler", [""])
            if not makineler:
                makineler = [""]

            basarili = 0
            toplam = 0

            for isemri_no in config["is_emirleri"]:
                if not durum["calisıyor"]:
                    break
                for makine in makineler:
                    if not durum["calisıyor"]:
                        break
                    toplam += 1
                    try:
                        if is_emri_isle(session, isemri_no, config["miktar"],
                                        config.get("recete",""), makine, operasyon):
                            basarili += 1
                    except Exception as e:
                        log(f"Hata ({isemri_no}/{makine}): {e}", "hata")

            durum["son_islem"] = datetime.now().strftime("%H:%M:%S")
            log(f"Tur #{durum['tur']} bitti. {basarili}/{toplam} islendi. {config['tekrar_dk']} dk bekleniyor...")

            for _ in range(config["tekrar_dk"] * 60):
                if not durum["calisıyor"]:
                    break
                time.sleep(1)

    except Exception as e:
        import traceback
        log(f"Kritik hata: {e}", "hata")
        log(traceback.format_exc(), "hata")
    finally:
        durum["calisıyor"] = False
        log("Otomasyon durduruldu.")

@app.route('/')
def index():
    return open('/app/index.html', encoding='utf-8').read()

@app.route('/baslat', methods=['POST'])
def baslat():
    if durum["calisıyor"]:
        return jsonify({"ok": False, "mesaj": "Zaten calisiyor!"})
    t = threading.Thread(target=otomasyon_dongu, args=(request.json,), daemon=True)
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
