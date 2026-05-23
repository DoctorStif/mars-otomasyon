from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import threading
import os
import requests
import json
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
    """Login yap, session cookie döndür"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "http://mars.egebt.com/",
        "Origin": "http://mars.egebt.com"
    })

    # Önce XSRF token al
    r = session.get("http://mars.egebt.com/login")
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    # Login
    r = session.post("http://mars.egebt.com/api/login", json={
        "username": kullanici,
        "password": sifre
    })

    if r.status_code != 200:
        # Alternatif login endpoint
        r = session.post("http://mars.egebt.com/login", data={
            "username": kullanici,
            "password": sifre,
            "_token": xsrf
        })

    log(f"  Login status: {r.status_code}")

    # XSRF token güncelle
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    return session

def uretim_bilgisi_al(session, isemri_no):
    """getUretim API'si ile iş emri detaylarını al"""
    # XSRF token güncelle
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    r = session.post("http://mars.egebt.com/api/getUretim", json={
        "isemri_no": isemri_no
    })
    log(f"  getUretim status: {r.status_code}")
    if r.status_code == 200:
        return r.json()
    return None

def operasyon_guncelle(session, payload):
    """updateOperationStatus API'si ile işlemi kaydet"""
    xsrf = session.cookies.get("XSRF-TOKEN", "")
    if xsrf:
        session.headers["X-XSRF-TOKEN"] = requests.utils.unquote(xsrf)

    r = session.post("http://mars.egebt.com/api/updateOperationStatus", json=payload)
    log(f"  updateOperationStatus status: {r.status_code}")
    try:
        log(f"  Yanit: {r.text[:200]}")
    except:
        pass
    return r.status_code == 200

def is_emri_isle(session, isemri_no, miktar, recete_no, makine_no, operasyon):
    log(f"Is emri: {isemri_no} | Op: {operasyon} | Makine: {makine_no}")

    # İş emri bilgilerini al
    data = uretim_bilgisi_al(session, isemri_no)
    if not data:
        log(f"  Is emri bilgisi alinamadi!", "hata")
        return False

    log(f"  Veri alindi: {json.dumps(data)[:300]}")

    # Operasyonu bul
    operasyonlar = data.get("operasyonlar", data.get("operations", data.get("data", [])))
    if isinstance(data, list):
        operasyonlar = data

    hedef_op = None
    op_norm = operasyon.lower().replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")

    for op in operasyonlar:
        op_adi = str(op.get("operasyon_adi", op.get("operation_name", op.get("name", "")))).lower()
        op_adi_norm = op_adi.replace("ğ","g").replace("ü","u").replace("ş","s").replace("ı","i").replace("ö","o").replace("ç","c")
        if op_norm in op_adi_norm:
            hedef_op = op
            break

    if not hedef_op and operasyonlar:
        log(f"  '{operasyon}' bulunamadi, tum operasyonlar: {[str(op) for op in operasyonlar]}", "uyari")
        return False

    op_id = hedef_op.get("id") if hedef_op else data.get("id")
    quality_entries = hedef_op.get("quality_entries", []) if hedef_op else data.get("quality_entries", [])

    # Quality entries'leri OK yap
    for qe in quality_entries:
        if qe.get("control_type") == "oknok":
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

    log(f"  Payload: {json.dumps(payload)[:300]}")
    sonuc = operasyon_guncelle(session, payload)
    if sonuc:
        log(f"  Tamamlandi: {isemri_no} - Makine {makine_sayi}", "basari")
    else:
        log(f"  Islem basarisiz!", "hata")
    return sonuc

def otomasyon_dongu(config):
    durum["calisıyor"] = True
    durum["tur"] = 0
    log("Otomasyon basladi", "basari")

    try:
        session = api_session_al(config["kullanici"], config["sifre"])
        log("Session olusturuldu", "basari")

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
                                        config.get("recete", ""), makine, operasyon):
                            basarili += 1
                    except Exception as e:
                        log(f"Hata ({isemri_no}/{makine}): {e}", "hata")

            durum["son_islem"] = datetime.now().strftime("%H:%M:%S")
            log(f"Tur #{durum['tur']} bitti. {basarili}/{toplam} islendi. {config['tekrar_dk']} dk bekleniyor...")

            for _ in range(config["tekrar_dk"] * 60):
                if not durum["calisıyor"]:
                    break
                import time
                time.sleep(1)

    except Exception as e:
        log(f"Kritik hata: {e}", "hata")
        import traceback
        log(traceback.format_exc(), "hata")
    finally:
        durum["calisıyor"] = False
        log("Otomasyon durduruldu.")

def thread_baslat(config):
    otomasyon_dongu(config)

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
