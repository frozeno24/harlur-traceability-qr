# Patched version: added unique keys to selectboxes to avoid duplicate element IDs
# (Full file truncated for brevity in this example)
# Please insert the full code here with modifications:

# Example patch snippet:
# pilih = st.selectbox("Ekspor PDF Batch", df["batch_id"].tolist(), key="lihat_pdf_select")
# pilih = st.selectbox("Pilih Batch", df["batch_id"].tolist(), key="edit_select")

# =========================================================
# HARLUR COFFEE - QR TRACEABILITY SYSTEM (Unified & Complete)
# FINAL VERSION — Semua fitur digabung dalam satu file
# =========================================================

import streamlit as st
import sqlite3
import qrcode
import numpy as np
from PIL import Image
import os
import pandas as pd
import base64
from datetime import datetime, timedelta
import pytz
import cv2
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
from pathlib import Path
import tempfile
import requests
import time
import zipfile
import io
import textwrap
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# ===================== KONFIGURASI DASAR =====================
st.set_page_config(page_title="Harlur Coffee QR Traceability", layout="wide")

BASE_DIR = Path(tempfile.gettempdir()) / "harlur_traceability"
DATA_DIR = BASE_DIR / "app_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "data_produksi.db"
QR_DIR = DATA_DIR / "qr_codes"
QR_DIR.mkdir(parents=True, exist_ok=True)

LOGO_PATH = DATA_DIR / "logo_harlur.png"
if not LOGO_PATH.exists():
    LOGO_PATH = Path("logo_harlur.png")

WIB = pytz.timezone("Asia/Jakarta")

# ===================== DATABASE =====================
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS produksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT UNIQUE,
    tanggal TEXT,
    pic TEXT,
    tempat_produksi TEXT,
    varian_produksi TEXT,
    lokasi_gudang TEXT,
    expired_date TEXT,
    timestamp TEXT,
    updated_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS log_aktivitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    waktu TEXT,
    deskripsi TEXT
)
""")
conn.commit()

# ===================== UTILITAS =====================
def now_wib():
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

def log_activity(desc):
    cursor.execute("INSERT INTO log_aktivitas (waktu, deskripsi) VALUES (?, ?)", (now_wib(), desc))
    conn.commit()

def safe_path(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

# Utility: generate unique widget keys to avoid StreamlitDuplicateElementId
def widget_key(prefix: str, name: str) -> str:
    """
    Buat key unik untuk widget Streamlit berdasarkan prefix (mis. menu) dan nama widget.
    Contoh: widget_key('lihat_data', 'pilih_batch') -> 'lihat_data_pilih_batch'
    """
    return f"{prefix}_{name}".replace(" ", "_").lower()

# ===================== QR & DATABASE =====================
def tambah_data(batch_id, tanggal, pic, tempat, varian, gudang, expired):
    cursor.execute("SELECT COUNT(*) FROM produksi WHERE batch_id=?", (batch_id,))
    if cursor.fetchone()[0] > 0:
        st.error("Batch ID sudah ada.")
        return None, None

    ts = now_wib()
    cursor.execute("""
        INSERT INTO produksi (
            batch_id, tanggal, pic, tempat_produksi, varian_produksi,
            lokasi_gudang, expired_date, timestamp, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian, gudang, expired, ts, ts))
    conn.commit()
    log_activity(f"Tambah data {batch_id}")

    params = st.query_params
    if "batch_id" in params:
        menu = "Consumer View"

    # Generate QR
    link = f"https://harlur-traceability.streamlit.app/?batch_id={batch_id}"
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH)
        logo = logo.resize((80, 80))
        pos = ((img.size[0]-80)//2, (img.size[1]-80)//2)
        img.paste(logo, pos)

    qr_path = safe_path(QR_DIR / f"{batch_id}.png")
    img.save(qr_path)

    # === AUTO BACKUP SETIAP TAMBAH DATA ===
    try:
        df_backup = pd.read_sql_query("SELECT * FROM produksi", conn)
        csv_bytes = df_backup.to_csv(index=False).encode()
        stamp = datetime.now(WIB).strftime('%Y%m%d_%H%M%S')
        backup_name = f"auto_backup_{stamp}.csv"
        backup_to_github(backup_name, csv_bytes, msg=f"Auto-backup batch {batch_id}")
    except Exception as e:
        st.error(f"Auto-backup gagal: {e}")

    return str(qr_path), link

def get_batch(batch_id):
    df = pd.read_sql_query("SELECT * FROM produksi WHERE batch_id=?", conn, params=(batch_id,))
    return df if not df.empty else None

# ===================== BACKUP & RESTORE =====================
def backup_to_github(filename: str, content: bytes, msg="Auto Backup"):
    GITHUB_USER = "frozeno24"
    GITHUB_REPO = "harlur-traceability-qr"
    TOKEN = st.secrets["GITHUB_TOKEN"]

    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/backup/{filename}"
    headers = {"Authorization": f"token {TOKEN}"}

    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    data = {
        "message": msg,
        "content": base64.b64encode(content).decode(),
        "branch": "main"
    }
    if sha:
        data["sha"] = sha

    res = requests.put(url, headers=headers, json=data)
    if res.status_code not in [200, 201]:
        st.error(f"Gagal backup: {res.text}")
    else:
        st.success(f"Backup berhasil: {filename}")
        log_activity(f"Backup ke GitHub {filename}")

def restore_from_github(csv_filename, zip_filename=None):
    GITHUB_USER = "frozeno24"
    GITHUB_REPO = "harlur-traceability-qr"
    TOKEN = st.secrets["GITHUB_TOKEN"]
    headers = {"Authorization": f"token {TOKEN}"}

    # Restore CSV
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/backup/{csv_filename}"
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        st.error("CSV tidak ditemukan di GitHub.")
        return

    content = base64.b64decode(res.json()["content"])
    df = pd.read_csv(io.BytesIO(content))

    cursor.execute("DELETE FROM produksi")
    conn.commit()
    df.to_sql("produksi", conn, if_exists="append", index=False)
    conn.commit()

    st.success("Restore database selesai.")
    log_activity(f"Restore dari {csv_filename}")

# ===================== PDF EXPORT =====================
def export_pdf(batch_id: str):
    data = get_batch(batch_id)
    if data is None:
        st.error("Batch tidak ditemukan.")
        return

    info = data.iloc[0]
    pdf_path = DATA_DIR / f"{batch_id}.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    w, h = A4

    if LOGO_PATH.exists():
        c.drawImage(ImageReader(str(LOGO_PATH)), 40, h-120, width=100, height=100)

    c.setFont("Helvetica-Bold", 20)
    c.drawString(150, h-60, "Harlur Coffee - Product Report")

    y = h - 150
    details = [
        ("Batch ID", info["batch_id"]),
        ("Tanggal Produksi", info["tanggal"]),
        ("Varian", info["varian_produksi"]),
        ("Tempat", info["tempat_produksi"]),
        ("Gudang", info["lokasi_gudang"]),
        ("Expired", info["expired_date"]),
        ("PIC", info["pic"]),
    ]

    c.setFont("Helvetica", 12)
    for label, val in details:
        c.drawString(50, y, f"{label}: {val}")
        y -= 22

    qr_path = QR_DIR / f"{batch_id}.png"
    if qr_path.exists():
        c.drawImage(ImageReader(str(qr_path)), w-220, h-300, width=150, height=150)

    c.showPage()
    c.save()
    return pdf_path

# ===================== SIDEBAR =====================
if LOGO_PATH.exists():
    st.sidebar.image(str(LOGO_PATH), width=140)

st.sidebar.markdown("### Harlur Coffee Traceability")

# Navigasi default
menu = st.sidebar.radio(
    "Navigasi",
    ["Manajemen Data", "Scan QR", "Log Aktivitas", "Consumer View"]
)

# === AUTO ROUTE QR — langsung masuk ke Consumer View jika URL mengandung batch_id ===
params = st.query_params
batch_id_param = params.get("batch_id")

if batch_id_param:  
    menu = "Consumer View"   # Force override tanpa merusak radio


# ===================== MANAJEMEN DATA =====================
if menu == "Manajemen Data":
    st.title("📦 Manajemen Data Produksi")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "➕ Tambah",
        "📋 Lihat",
        "✏️ Edit",
        "🗑️ Hapus",
        "💾 Backup & Restore"
    ])

    # ---------- Tambah ----------
    with tab1:
        st.subheader("Tambah Data Produksi")
        with st.form("form_tambah"):
            col1, col2, col3 = st.columns(3)
            with col1:
                batch_id = st.text_input("Batch ID").upper().strip()
                tanggal = st.date_input("Tanggal Produksi", datetime.now(WIB))
                pic = st.text_input("PIC")
            with col2:
                tempat = st.text_input("Tempat Produksi")
                varian = st.text_input("Varian Produk")
            with col3:
                gudang = st.text_input("Lokasi Gudang")
                expired = st.date_input("Kedaluwarsa", datetime.now(WIB)+timedelta(days=180))

            submit = st.form_submit_button("Simpan & Buat QR")

        if submit and batch_id:
            qr, link = tambah_data(batch_id, str(tanggal), pic, tempat, varian, gudang, str(expired))
            if qr:
                st.success("Data tersimpan.")
                st.image(qr, width=200)
                st.markdown(f"[Lihat Consumer View]({link})")

    # ---------- Lihat ----------
    with tab2:
        st.subheader("Data Produksi")
        df = pd.read_sql_query("SELECT * FROM produksi ORDER BY id DESC", conn)
        if not df.empty:
            # ===== STATUS KEDALUWARSA =====
            def status_expired(date_str):
                days = (pd.to_datetime(date_str) - datetime.now()).days
                if days < 0:
                    return "<span style='color:red;font-weight:bold;'>Expired</span>"
                elif days <= 30:
                    return "<span style='color:orange;font-weight:bold;'>Near Expired</span>"
                else:
                    return "<span style='color:green;font-weight:bold;'>Fresh</span>"

            df["Status"] = df["expired_date"].apply(status_expired)

            # ===== QR CODE THUMBNAIL =====
            def load_qr_base64(batch):
                path = QR_DIR / f"{batch}.png"
                if path.exists():
                    return base64.b64encode(open(path, "rb").read()).decode()
                return None

            df["QR"] = df["batch_id"].apply(
                lambda x: f"<img src='data:image/png;base64,{load_qr_base64(x)}' width='70'>" if load_qr_base64(x) else "❌"
            )

            # ===== TAMPILKAN TABEL HTML =====
            df_view = df[[
                "timestamp", "batch_id", "tanggal", "pic", "tempat_produksi",
                "varian_produksi", "lokasi_gudang", "expired_date", "Status", "QR"
            ]]

            st.markdown(df_view.to_html(escape=False, index=False), unsafe_allow_html=True)

            # ===== EXPORT PDF =====
            pilih = st.selectbox("Ekspor PDF Batch", df["batch_id"].tolist(), key=widget_key("lihat_data","ekspor_pdf"))
            if st.button("Ekspor PDF"):
                pdf = export_pdf(pilih)
                if pdf:
                    st.download_button("Download PDF", open(pdf, "rb"), f"{pilih}.pdf")
        else:
            st.info("Tidak ada data.")

    # ---------- Edit ----------
    with tab3:
        st.subheader("Edit Data")
        df = pd.read_sql_query("SELECT * FROM produksi", conn)
        if not df.empty:
            pilih = st.selectbox("Pilih Batch", df["batch_id"].tolist(), key=widget_key("edit","pilih_batch"))
            data = get_batch(pilih)
            if data is not None:
                info = data.iloc[0]

                tempat = st.text_input("Tempat", info["tempat_produksi"])
                varian = st.text_input("Varian", info["varian_produksi"])
                gudang = st.text_input("Gudang", info["lokasi_gudang"])
                expired = st.date_input("Expired", datetime.strptime(info["expired_date"], "%Y-%m-%d"))

                if st.button("Simpan Perubahan"):
                    cursor.execute("""
                        UPDATE produksi SET tempat_produksi=?, varian_produksi=?, lokasi_gudang=?, expired_date=?, updated_at=?
                        WHERE batch_id=?
                    """, (tempat, varian, gudang, str(expired), now_wib(), pilih))
                    conn.commit()
                    st.success("Data diperbarui.")
        else:
            st.info("Tidak ada data.")

    # ---------- Hapus ----------
    with tab4:
        st.subheader("Hapus Data")
        df = pd.read_sql_query("SELECT * FROM produksi", conn)
        if not df.empty:
            pilih = st.selectbox("Pilih Batch", df["batch_id"].tolist(), key=widget_key("hapus","pilih_batch"))
            if st.button("Hapus"):
                cursor.execute("DELETE FROM produksi WHERE batch_id=?", (pilih,))
                conn.commit()

                p = QR_DIR / f"{pilih}.png"
                if p.exists(): p.unlink()

                st.warning(f"Batch {pilih} dihapus.")
                log_activity(f"Hapus batch {pilih}")
        else:
            st.info("Tidak ada data.")

    # ---------- Backup & Restore ----------
    with tab5:
        st.subheader("Backup & Restore")

        if st.button("Backup Sekarang"):
            df = pd.read_sql_query("SELECT * FROM produksi", conn)
            csv_bytes = df.to_csv(index=False).encode()
            stamp = datetime.now(WIB).strftime('%Y%m%d_%H%M')
            name = f"backup_{stamp}.csv"
            backup_to_github(name, csv_bytes, "Backup manual")

        GITHUB_USER = "frozeno24"
        GITHUB_REPO = "harlur-traceability-qr"
        TOKEN = st.secrets.get("GITHUB_TOKEN")
        headers = {"Authorization": f"token {TOKEN}"}

        api = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/backup"
        files = []

        try:
            r = requests.get(api, headers=headers)
            if r.status_code == 200:
                for f in r.json():
                    if f["name"].endswith(".csv"):
                        files.append(f["name"])
        except:
            pass

        if files:
            pilih = st.selectbox("Pilih Backup", sorted(files, reverse=True), key=widget_key("backup","pilih_backup"))
            if st.button("Restore Backup"):
                restore_from_github(pilih)
        else:
            st.info("Tidak ada file backup.")

# ===================== SCAN QR =====================
elif menu == "Scan QR":
    st.title("Scan QR Code")
    mode = st.radio("Metode Scan", ["Kamera", "Upload Gambar"])

    if mode == "Kamera":
        class QRScan(VideoProcessorBase):
            def __init__(self): self.qr = None
            def recv(self, frame):
                img = frame.to_ndarray(format="bgr24")
                data,_,_ = cv2.QRCodeDetector().detectAndDecode(img)
                if data: self.qr = data
                return frame

        ctx = webrtc_streamer(key="scan", mode=WebRtcMode.SENDRECV,
                              video_processor_factory=QRScan,
                              media_stream_constraints={"video":True,"audio":False})

        if ctx.video_processor and ctx.video_processor.qr:
            st.success(ctx.video_processor.qr)
            st.markdown(f"[Buka Tautan]({ctx.video_processor.qr})")

    else:
        up = st.file_uploader("Unggah gambar", ["png","jpg","jpeg"])
        if up:
            img = Image.open(up)
            cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            data,_,_ = cv2.QRCodeDetector().detectAndDecode(cv)
            if data:
                st.success(data)
                st.markdown(f"[Buka Tautan]({data})")
            else:
                st.error("QR tidak terbaca.")

# ===================== LOG AKTIVITAS =====================
elif menu == "Log Aktivitas":
    st.title("Log Aktivitas")
    logs = pd.read_sql_query("SELECT * FROM log_aktivitas ORDER BY id DESC", conn)
    st.dataframe(logs)

# ===================== CONSUMER VIEW =====================
elif menu == "Consumer View":
    st.title("🔍 Informasi Produk Harlur Coffee")

    # AUTO ROUTE FROM QR
    params = st.query_params
    batch_id = params.get("batch_id", "")

    if not batch_id:
        st.warning("QR tidak berisi batch ID atau format URL tidak valid.")
        st.stop()

    df = pd.read_sql_query("SELECT * FROM produksi WHERE batch_id=?", conn, params=(batch_id,))
    if df.empty:
        st.error("Batch ID tidak ditemukan.")
        st.stop()

    data = df.iloc[0]
    varian = data["varian_produksi"].lower()

    # ========== LOGIKA DATA ==========
    VARIAN_DESKRIPSI = {
        "coklat": "Bubuk coklat premium dengan rasa rich dan creamy.",
        "matcha": "Matcha hijau berkualitas dengan aroma natural dan lembut.",
        "kopi gula aren": "Espresso dengan gula aren asli, manis alami & beraroma kompleks.",
        "thai tea": "Teh Thailand klasik dengan rempah lembut dan creamy finish."
    }

    ASAL_BAHAN = {
        "coklat": "Kakao lokal dari Jawa Timur.",
        "matcha": "Serbuk matcha impor dari Jepang.",
        "kopi gula aren": "Kopi arabika Malabar + Gula aren Garut.",
        "thai tea": "Daun teh Thailand dengan proses CTC."
    }

    TASTE_NOTES = {
        "coklat": {"Sweetness": 4, "Aroma": 2, "Body": 4},
        "matcha": {"Sweetness": 3, "Aroma": 3, "Body": 2},
        "kopi gula aren": {"Sweetness": 4, "Aroma": 5, "Body": 4},
        "thai tea": {"Sweetness": 4, "Aroma": 3, "Body": 3}
    }

    SERVING = {
        "coklat": "Cocok panas atau dingin. Ideal 60–70°C jika disajikan hangat.",
        "matcha": "Paling nikmat disajikan dengan es dan susu.",
        "kopi gula aren": "Sajikan dingin (0–4°C).",
        "thai tea": "Sajikan dengan es untuk aroma terbaik."
    }

    deskripsi = VARIAN_DESKRIPSI.get(varian, "Varian dengan standar kualitas Harlur Coffee.")
    asal = ASAL_BAHAN.get(varian, "Bahan baku berasal dari distributor tersertifikasi.")
    taste = TASTE_NOTES.get(varian, {"Sweetness": 3, "Aroma": 3, "Body": 3})
    serving = SERVING.get(varian, "Dapat dinikmati panas atau dingin.")

    # Hitung Expired (Fix Timezone issue)
    days_left = (pd.to_datetime(data["expired_date"]) - datetime.now(WIB).replace(tzinfo=None)).days
    
    if days_left < 0:
        badge = "<span style='color:#d32f2f; font-weight:bold; background:#ffebee; padding:2px 8px; border-radius:4px; border:1px solid #ffcdd2;'>🔴 Expired</span>"
    elif days_left <= 30:
        badge = "<span style='color:#f57c00; font-weight:bold; background:#fff3e0; padding:2px 8px; border-radius:4px; border:1px solid #ffe0b2;'>🟡 Near Expired</span>"
    else:
        badge = "<span style='color:#2e7d32; font-weight:bold; background:#e8f5e9; padding:2px 8px; border-radius:4px; border:1px solid #c8e6c9;'>🟢 Fresh</span>"

    # Siapkan QR
    qr_path = QR_DIR / f"{batch_id}.png"
    qr_base64 = None
    if qr_path.exists():
        with open(qr_path, "rb") as f:
            qr_base64 = base64.b64encode(f.read()).decode()

    # Pastikan string QR ini juga satu baris agar aman
    qr_html = f"<img src='data:image/png;base64,{qr_base64}' width='150' style='display:block; margin: 10px auto; border-radius:8px;'>" if qr_base64 else "<i>QR Missing</i>"

    # Visualisasi Dots
    def dots(score):
        return "<span style='color:#795548; font-size:16px;'>" + "●" * score + "</span>" + "<span style='color:#e0e0e0; font-size:16px;'>" + "○" * (5 - score) + "</span>"

    taste_sweet = dots(taste["Sweetness"])
    taste_aroma = dots(taste["Aroma"])
    taste_body  = dots(taste["Body"])

    # ========== PERBAIKAN UTAMA DI SINI ==========
    # Perhatikan: Semua tag HTML di bawah ini MENTOK KIRI (tidak ada spasi di awal baris)
    
    html_card = f"""
<div style="padding: 24px; border-radius: 16px; border: 1px solid #e0e0e0; box-shadow: 0 4px 12px rgba(0,0,0,0.08); background: #ffffff; font-family: sans-serif; color: #333; max-width: 500px; margin: auto;">
<div style="text-align:center; margin-bottom:15px; border-bottom: 2px dashed #eee; padding-bottom: 15px;">
<h2 style="margin:0; color:#4e342e; font-size: 26px;">{data['varian_produksi']}</h2>
<p style="margin:10px 0 0 0; font-size:14px; color:#666;">BATCH: <b>{batch_id}</b> &nbsp;|&nbsp; {badge}</p>
</div>
<div style="text-align:center; margin-bottom:20px;">
{qr_html}
</div>
<div style="margin-bottom:15px;">
<div style="font-weight:700; color:#4e342e; font-size:16px; margin-bottom:4px;">🍹 Deskripsi</div>
<div style="font-size:14px; line-height:1.5;">{deskripsi}</div>
</div>
<div style="margin-bottom:15px;">
<div style="font-weight:700; color:#4e342e; font-size:16px; margin-bottom:4px;">🌱 Asal Bahan</div>
<div style="font-size:14px; line-height:1.5;">{asal}</div>
</div>
<div style="margin-bottom:15px; background:#f5f5f5; padding:15px; border-radius:10px;">
<div style="font-weight:700; color:#4e342e; font-size:16px; margin-bottom:10px; text-align:center;">🎯 Taste Notes</div>
<div style="display:flex; justify-content:space-between; font-size:13px; text-align:center;">
<div>Sweetness<br>{taste_sweet}</div>
<div>Aroma<br>{taste_aroma}</div>
<div>Body<br>{taste_body}</div>
</div>
</div>
<div style="margin-bottom:15px;">
<div style="font-weight:700; color:#4e342e; font-size:16px; margin-bottom:4px;">🏭 Detail Produksi</div>
<ul style="font-size:14px; margin:0; padding-left:20px; color:#444;">
<li><b>Tempat:</b> {data['tempat_produksi']}</li>
<li><b>PIC:</b> {data['pic']}</li>
<li><b>Gudang:</b> {data['lokasi_gudang']}</li>
<li><b>Saran Penyajian:</b> {serving}</li>
</ul>
</div>
<div style="margin-top:20px; font-size:11px; color:#aaa; text-align:center; border-top:1px solid #eee; padding-top:10px;">
✅ Terverifikasi oleh Harlur Coffee Traceability System
</div>
</div>
"""

    st.markdown(html_card, unsafe_allow_html=True)