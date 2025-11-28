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

    # Generate QR
    link = f"https://harlur-traceability.streamlit.app/?menu=Consumer%20View&batch_id={batch_id}"
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

menu = st.sidebar.radio("Navigasi", [
    "Manajemen Data", "Scan QR", "Log Aktivitas", "Consumer View"
])

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
            st.dataframe(df)
            st.download_button("📄 Ekspor CSV", df.to_csv(index=False).encode(), "produksi.csv")

            pilih = st.selectbox("Ekspor PDF Batch", df["batch_id"].tolist())
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
            pilih = st.selectbox("Pilih Batch", df["batch_id"].tolist())
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
            pilih = st.selectbox("Pilih Batch", df["batch_id"].tolist())
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
            pilih = st.selectbox("Pilih Backup", sorted(files, reverse=True))
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
    st.title("Informasi Produk")
    params = st.query_params
    if "batch_id" in params:
        b = params["batch_id"]
        data = get_batch(b)
        if data is not None:
            info = data.iloc[0]
            st.write(f"### Varian: {info['varian_produksi']}")
            st.write(f"Tanggal Produksi: {info['tanggal']}")
            st.write(f"Tempat Produksi: {info['tempat_produksi']}")
            st.write(f"Gudang: {info['lokasi_gudang']}")
            st.write(f"Expired: {info['expired_date']}")
            st.write(f"PIC: {info['pic']}")
        else:
            st.error("Data batch tidak ditemukan.")
    else:
        st.info("Scan QR untuk melihat informasi.")
