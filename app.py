from flask import Flask, request, jsonify, render_template_string
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
    entry = {"zaman": zaman, "mesaj": mesaj, "tip": tip}
    durum["mesajlar"].append(entry)
    if len(durum["mesajlar"]) > 100:
        durum["mesajlar"] = durum["mesajlar"][-100:]
    print(f"[{zaman}] {mesaj}")

async def login(page, kullanici, sifre):
    log("Giriş yapılıyor...")
    await page.goto("http://mars.egebt.com/login")
    await page.wait_for_load_state("networkidle")
    await page.fill('input[name="username"], input[type="text"]', kullanici)
    await page.fill('input[name="password"], input[type="password"]', sifre)
    await page.click('button[type="submit"], input[type="submit"]')
    await page.wait_for_load_state("networkidle")
    if "login" in page.url:
        raise Exception("Giriş başarısız! Kullanıcı adı veya şifre hatalı.")
    log("✓ Giriş başarılı!", "basari")

async def is_emri_isle(page, is_no, miktar, recete_no, makine_no, operasyon):
    url = f"http://mars.egebt.com/uretim?I={is_no}"
    log(f"→ İş emri: {is_no} | Op: {operasyon} | Makine: {makine_no}")
    await page.goto(url)
    await page.wait_for_load_state("networkidle")

    basla_btn = await page.query_selector("button:has-text('Başla'), .btn:has-text('Başla')")
    if basla_btn:
        log(f"  'Başla' tıklanıyor...")
        await basla_btn.click()
        await page.wait_for_timeout(1500)
        await page.wait_for_load_state("networkidle")

    satirlar = await page.query_selector_all("tr, .row, [class*='row']")
    hedef_btn = None
    for satir in satirlar:
        satir_text = (await satir.inner_text()).lower()
        if operasyon.lower() in satir_text:
            btn = await satir.query_selector(
                "button:has-text('Üretim'), button:has-text('Üretimde'), "
                ".btn-success, .btn:has-text('Üretim')"
            )
            if btn:
                hedef_btn = btn
                break

    if not hedef_btn:
        log(f"  ⚠ '{operasyon}' satırında buton yok, ilk deneniyor...", "uyari")
        hedef_btn = await page.query_selector(
            "button:has-text('Üretim'), button:has-text('Üretimde'), .btn-success"
        )

    if not hedef_btn:
        log(f"  ⚠ Üretim butonu bulunamadı: {is_no}", "uyari")
        return False

    await hedef_btn.click()
    await page.wait_for_timeout(1500)

    modal = await page.query_selector(".modal, [role='dialog']")
    if not modal:
        log(f"  ⚠ Modal açılmadı!", "uyari")
        return False

    log(f"  Modal açıldı, veriler giriliyor...")

    miktar_input = await page.query_selector(
        ".modal input[type='number']:first-of-type, "
        ".modal input[type='text']:first-of-type, "
        "input[placeholder*='Onaylı'], input[placeholder*='Miktar']"
    )
    if miktar_input:
        await miktar_input.triple_click()
        await miktar_input.fill(str(miktar))
        log(f"  ✓ Miktar: {miktar}")

    if recete_no:
        try:
            recete_select = await page.query_selector(
                "select[name*='recete'], select[id*='recete'], .modal select:nth-of-type(1)"
            )
            if recete_select:
                await recete_select.select_option(label=recete_no)
                log(f"  ✓ Reçete: {recete_no}")
        except Exception as e:
            log(f"  ⚠ Reçete seçilemedi: {e}", "uyari")

    if makine_no:
        try:
            makine_select = await page.query_selector(
                "select[name*='makine'], select[id*='makine'], .modal select:nth-of-type(2)"
            )
            if makine_select:
                await makine_select.select_option(label=makine_no)
                log(f"  ✓ Makine: {makine_no}")
        except Exception as e:
            log(f"  ⚠ Makine seçilemedi: {e}", "uyari")

    await page.wait_for_timeout(500)

    sonraki_btn = await page.query_selector(
        "button:has-text('Sonraki İşlem'), .btn:has-text('Sonraki')"
    )
    if sonraki_btn:
        await sonraki_btn.click()
        await page.wait_for_timeout(2000)
        log(f"  ✓ Tamamlandı: {is_no} → Makine {makine_no}", "basari")
        return True
    else:
        log(f"  ⚠ 'Sonraki İşlem' butonu yok!", "uyari")
        return False

async def otomasyon_dongu(config):
    durum["calisıyor"] = True
    durum["tur"] = 0
    log("Otomasyon başlatıldı", "basari")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            await login(page, config["kullanici"], config["sifre"])

            while durum["calisıyor"]:
                durum["tur"] += 1
                log(f"── Tur #{durum['tur']} başladı ──")

                emirler = config["is_emirleri"]
                operasyon = config.get("operasyon", "Yağ alma")
                # Makine listesi: kumlama için birden fazla olabilir
                makineler = config.get("makineler", [])
                if not makineler:
                    tek_makine = config.get("makine", "")
                    makineler = [tek_makine] if tek_makine else [""]

                basarili = 0
                toplam = 0

                for is_no in emirler:
                    if not durum["calisıyor"]:
                        break
                    for makine in makineler:
                        if not durum["calisıyor"]:
                            break
                        toplam += 1
                        try:
                            sonuc = await is_emri_isle(
                                page, is_no,
                                config["miktar"],
                                config.get("recete", ""),
                                makine,
                                operasyon
                            )
                            if sonuc:
                                basarili += 1
                        except Exception as e:
                            log(f"❌ Hata ({is_no} / {makine}): {e}", "hata")

                durum["son_islem"] = datetime.now().strftime("%H:%M:%S")
                log(f"Tur #{durum['tur']} bitti. {basarili}/{toplam} işlendi. {config['tekrar_dk']} dk bekleniyor...")

                for _ in range(config["tekrar_dk"] * 60):
                    if not durum["calisıyor"]:
                        break
                    await asyncio.sleep(1)

            await browser.close()

    except Exception as e:
        log(f"❌ Kritik hata: {e}", "hata")
    finally:
        durum["calisıyor"] = False
        log("Otomasyon durduruldu.")

def thread_baslat(config):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(otomasyon_dongu(config))
    loop.close()

HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mars Otomasyon</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
  :root {
    --bg: #0a0e1a; --surface: #111827; --border: #1e2d40;
    --accent: #0ea5e9; --accent2: #22d3ee; --success: #10b981;
    --warn: #f59e0b; --danger: #ef4444; --text: #e2e8f0; --muted: #64748b;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'IBM Plex Sans', sans-serif; min-height: 100vh; padding: 20px 16px 40px; }
  .header { text-align: center; margin-bottom: 28px; padding-top: 8px; }
  .header h1 { font-family: 'IBM Plex Mono', monospace; font-size: 1.4rem; letter-spacing: 0.12em; color: var(--accent2); text-transform: uppercase; }
  .header p { color: var(--muted); font-size: 0.8rem; margin-top: 4px; font-family: 'IBM Plex Mono', monospace; }
  .status-bar { display: flex; align-items: center; gap: 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; margin-bottom: 20px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
  .dot.aktif { background: var(--success); box-shadow: 0 0 8px var(--success); animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .status-text { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; }
  .status-text span { color: var(--muted); }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
  .card-title { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; letter-spacing: 0.15em; color: var(--accent); text-transform: uppercase; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  label { display: block; font-size: 0.78rem; color: var(--muted); margin-bottom: 5px; font-family: 'IBM Plex Mono', monospace; }
  input, textarea { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 10px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; margin-bottom: 14px; outline: none; transition: border-color 0.2s; }
  input:focus, textarea:focus { border-color: var(--accent); }
  input[type="password"] { letter-spacing: 0.2em; }
  textarea { resize: vertical; min-height: 80px; }
  /* Operasyon tab seçici */
  .op-tabs { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
  .op-tab {
    flex: 1; min-width: 110px; padding: 10px 8px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--muted); font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem; cursor: pointer; text-align: center;
    transition: all 0.2s; -webkit-appearance: none; appearance: none; outline: none;
  }
  .op-tab.aktif { border-color: var(--accent) !important; color: var(--accent) !important; background: rgba(14,165,233,0.12) !important; box-shadow: 0 0 0 1px var(--accent); }
  /* Makine çoklu seçim */
  .makine-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px; }
  .makine-btn {
    padding: 12px 6px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--bg); color: var(--muted);
    font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem;
    cursor: pointer; text-align: center; transition: all 0.2s;
    -webkit-appearance: none; appearance: none; outline: none;
    position: relative;
  }
  .makine-btn.secili {
    border-color: var(--success) !important; color: var(--success) !important;
    background: rgba(16,185,129,0.12) !important;
    box-shadow: 0 0 0 1px var(--success);
  }
  .makine-btn.secili::after { content: '✓'; position: absolute; top: 4px; right: 6px; font-size: 0.65rem; }
  .makine-tekli { display: none; }
  .makine-tekli.goster { display: block; }
  .makine-coklu { display: none; }
  .makine-coklu.goster { display: block; }
  .op-custom { display: none; }
  .op-custom.goster { display: block; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .btn { width: 100%; padding: 14px; border: none; border-radius: 10px; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; font-weight: 600; letter-spacing: 0.08em; cursor: pointer; transition: all 0.2s; text-transform: uppercase; }
  .btn-start { background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #000; margin-bottom: 10px; }
  .btn-start:hover { transform: translateY(-1px); box-shadow: 0 4px 20px rgba(14,165,233,0.4); }
  .btn-start:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  .btn-stop { background: transparent; border: 1px solid var(--danger); color: var(--danger); }
  .btn-stop:hover { background: var(--danger); color: #fff; }
  .btn-stop:disabled { opacity: 0.3; cursor: not-allowed; }
  .log-box { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px; height: 220px; overflow-y: auto; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; line-height: 1.7; }
  .log-info { color: var(--text); } .log-basari { color: var(--success); } .log-uyari { color: var(--warn); } .log-hata { color: var(--danger); }
  .log-time { color: var(--muted); margin-right: 8px; }
  .hint { font-size: 0.72rem; color: var(--muted); margin-top: -10px; margin-bottom: 14px; }
  .secim-ozet { font-size: 0.75rem; color: var(--accent); font-family: 'IBM Plex Mono', monospace; margin-bottom: 10px; min-height: 18px; }
</style>
</head>
<body>
<div class="header">
  <h1>Mars Otomasyon</h1>
  <p>Üretim · Otomatik İşlem</p>
</div>
<div class="status-bar">
  <div class="dot" id="dot"></div>
  <div class="status-text" id="statusText"><span>Bekleniyor</span></div>
</div>

<!-- GİRİŞ -->
<div class="card">
  <div class="card-title">Giriş Bilgileri</div>
  <label>Kullanıcı Adı</label>
  <input type="text" id="kullanici" placeholder="kullanici_adi">
  <label>Şifre</label>
  <input type="password" id="sifre" placeholder="••••••••">
</div>

<!-- OPERASYON -->
<div class="card">
  <div class="card-title">Operasyon Seç</div>
  <div class="op-tabs">
    <button class="op-tab aktif" data-op="Yağ alma">🫙 Yağ Alma</button>
    <button class="op-tab" data-op="Kumlama">⚙️ Kumlama</button>
    <button class="op-tab" data-op="Kaplama-1">🔩 Kaplama-1</button>
    <button class="op-tab" data-op="Kaplama-2">🔩 Kaplama-2</button>
    <button class="op-tab" data-op="__diger__">✏️ Diğer</button>
  </div>
  <div class="op-custom" id="opCustomWrap">
    <label>Operasyon adını yaz (sayfada nasıl yazıyorsa)</label>
    <input type="text" id="opCustom" placeholder="örn: Lak-1">
  </div>
  <input type="hidden" id="operasyon" value="Yağ alma">
</div>

<!-- MAKİNE -->
<div class="card">
  <div class="card-title">Makine Seç</div>

  <!-- Kumlama: çoklu seçim -->
  <div class="makine-coklu" id="makineKumlama">
    <label>Kumlama makinelerini seç (birden fazla seçebilirsin)</label>
    <div class="makine-grid">
      <button class="makine-btn" data-makine="Kumlama-1">⚙️ Kumlama 1</button>
      <button class="makine-btn" data-makine="Kumlama-2">⚙️ Kumlama 2</button>
      <button class="makine-btn" data-makine="Kumlama-3">⚙️ Kumlama 3</button>
      <button class="makine-btn" data-makine="Kumlama-4">⚙️ Kumlama 4</button>
      <button class="makine-btn" data-makine="Kumlama-5">⚙️ Kumlama 5</button>
    </div>
    <div class="secim-ozet" id="kumlamaOzet">Henüz seçilmedi</div>
  </div>

  <!-- Diğer operasyonlar: tekli makine yazma -->
  <div class="makine-tekli goster" id="makineTekli">
    <label>Makine No (boş bırakılabilir)</label>
    <input type="text" id="makineInput" placeholder="Makine adı veya boş bırak">
  </div>
</div>

<!-- İŞ EMİRLERİ -->
<div class="card">
  <div class="card-title">İş Emirleri</div>
  <label>İş Emri Numaraları</label>
  <textarea id="emirler" placeholder="X20260000004117&#10;X20260000004118&#10;X20260000004119"></textarea>
  <p class="hint">Her satıra bir iş emri numarası yaz</p>
</div>

<!-- PARAMETRELER -->
<div class="card">
  <div class="card-title">Üretim Parametreleri</div>
  <div class="row">
    <div>
      <label>Onaylı Miktar</label>
      <input type="number" id="miktar" placeholder="200">
    </div>
    <div>
      <label>Tekrar (dakika)</label>
      <input type="number" id="tekrar" placeholder="15" value="15">
    </div>
  </div>
  <label>Reçete No (boş bırakılabilir)</label>
  <input type="text" id="recete" placeholder="Boş bırakılabilir">
</div>

<!-- BUTONLAR -->
<div class="card">
  <button class="btn btn-start" id="btnBaslat">▶ Başlat</button>
  <button class="btn btn-stop" id="btnDurdur" disabled>■ Durdur</button>
</div>

<!-- LOG -->
<div class="card">
  <div class="card-title">İşlem Günlüğü</div>
  <div class="log-box" id="logBox"><span class="log-info">Henüz işlem yapılmadı...</span></div>
</div>

<script>
var polling = null;
var seciliMakineler = [];

// Operasyon tab seçimi
document.querySelectorAll('.op-tab').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var deger = this.getAttribute('data-op');
    document.querySelectorAll('.op-tab').forEach(function(t) { t.classList.remove('aktif'); });
    this.classList.add('aktif');

    var customWrap = document.getElementById('opCustomWrap');
    var kumlamaDiv = document.getElementById('makineKumlama');
    var tekliDiv = document.getElementById('makineTekli');

    if (deger === '__diger__') {
      customWrap.classList.add('goster');
      document.getElementById('operasyon').value = '';
    } else {
      customWrap.classList.remove('goster');
      document.getElementById('operasyon').value = deger;
    }

    // Kumlama seçilince çoklu makine göster, diğerlerinde tekli
    if (deger === 'Kumlama') {
      kumlamaDiv.classList.add('goster');
      tekliDiv.classList.remove('goster');
    } else {
      kumlamaDiv.classList.remove('goster');
      tekliDiv.classList.add('goster');
    }
  });
});

document.getElementById('opCustom').addEventListener('input', function() {
  document.getElementById('operasyon').value = this.value;
});

document.getElementById('btnBaslat').addEventListener('click', function() { baslat(); });
document.getElementById('btnDurdur').addEventListener('click', function() { durdur(); });

// Kumlama makine çoklu seçimi
document.querySelectorAll('.makine-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var makine = this.getAttribute('data-makine');
    var idx = seciliMakineler.indexOf(makine);
    if (idx === -1) {
      seciliMakineler.push(makine);
      this.classList.add('secili');
    } else {
      seciliMakineler.splice(idx, 1);
      this.classList.remove('secili');
    }
    var ozet = document.getElementById('kumlamaOzet');
    if (seciliMakineler.length === 0) {
      ozet.textContent = 'Henüz seçilmedi';
    } else {
      ozet.textContent = '✓ Seçili: ' + seciliMakineler.join(', ');
    }
  });
});

async function baslat() {
  var kullanici = document.getElementById('kullanici').value.trim();
  var sifre = document.getElementById('sifre').value.trim();
  var emirlerRaw = document.getElementById('emirler').value.trim();
  var miktar = document.getElementById('miktar').value.trim();
  var tekrar = parseInt(document.getElementById('tekrar').value) || 15;
  var recete = document.getElementById('recete').value.trim();
  var operasyon = document.getElementById('operasyon').value.trim();

  if (!kullanici || !sifre) { alert('Kullanıcı adı ve şifre gerekli!'); return; }
  if (!emirlerRaw) { alert('En az bir iş emri numarası gir!'); return; }
  if (!miktar) { alert('Onaylı miktar gerekli!'); return; }
  if (!operasyon) { alert('Operasyon seç veya yaz!'); return; }

  var emirler = emirlerRaw.split('\n').map(function(x) { return x.trim(); }).filter(Boolean);

  // Makine listesini belirle
  var makineler = [];
  if (operasyon === 'Kumlama') {
    if (seciliMakineler.length === 0) { alert('En az bir kumlama makinesi seç!'); return; }
    makineler = seciliMakineler.slice();
  } else {
    var tekMakine = document.getElementById('makineInput').value.trim();
    makineler = tekMakine ? [tekMakine] : [''];
  }

  var res = await fetch('/baslat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ kullanici: kullanici, sifre: sifre, is_emirleri: emirler, miktar: miktar, tekrar_dk: tekrar, recete: recete, operasyon: operasyon, makineler: makineler })
  });
  var data = await res.json();
  if (data.ok) {
    document.getElementById('btnBaslat').disabled = true;
    document.getElementById('btnDurdur').disabled = false;
    document.getElementById('dot').className = 'dot aktif';
    baslaPoll();
  } else {
    alert('Hata: ' + data.mesaj);
  }
}

async function durdur() {
  await fetch('/durdur', { method: 'POST' });
  document.getElementById('btnBaslat').disabled = false;
  document.getElementById('btnDurdur').disabled = true;
  document.getElementById('dot').className = 'dot';
  if (polling) clearInterval(polling);
}

function baslaPoll() {
  if (polling) clearInterval(polling);
  polling = setInterval(guncelle, 2000);
}

async function guncelle() {
  var res = await fetch('/durum');
  var data = await res.json();
  var dot = document.getElementById('dot');
  var statusText = document.getElementById('statusText');
  if (data.calisıyor) {
    dot.className = 'dot aktif';
    statusText.innerHTML = 'Tur #' + data.tur + ' · Son: <span>' + (data.son_islem || '-') + '</span>';
  } else {
    dot.className = 'dot';
    statusText.innerHTML = '<span>Bekleniyor</span>';
    document.getElementById('btnBaslat').disabled = false;
    document.getElementById('btnDurdur').disabled = true;
    if (polling) clearInterval(polling);
  }
  var logBox = document.getElementById('logBox');
  var scroll = logBox.scrollHeight - logBox.clientHeight - logBox.scrollTop < 40;
  if (data.mesajlar && data.mesajlar.length > 0) {
    logBox.innerHTML = data.mesajlar.map(function(m) {
      return '<div class="log-' + m.tip + '"><span class="log-time">' + m.zaman + '</span>' + m.mesaj + '</div>';
    }).join('');
  } else {
    logBox.innerHTML = '<span class="log-info">Henüz işlem yapılmadı...</span>';
  }
  if (scroll) logBox.scrollTop = logBox.scrollHeight;
}
</script>
</body>
</html>"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/baslat', methods=['POST'])
def baslat():
    if durum["calisıyor"]:
        return jsonify({"ok": False, "mesaj": "Zaten çalışıyor!"})
    config = request.json
    t = threading.Thread(target=thread_baslat, args=(config,), daemon=True)
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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
