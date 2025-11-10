# =========================================================
# HARLUR COFFEE - QR TRACEABILITY SYSTEM
# Internal Production & Distribution Tracking App
# Last Updated: 2025-11-10
# =========================================================

import os
import sqlite3
import qrcode
import base64
import pandas as pd
import cv2
from io import BytesIO
from PIL import Image
from datetime import datetime, timedelta
import streamlit as st
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ---------- KONFIGURASI DASAR ----------

DB_PATH = "data_produksi.db"
QR_DIR = "qr_codes"
os.makedirs(QR_DIR, exist_ok=True)

# ---------- STYLING ----------
st.set_page_config(
    page_title="Harlur Coffee QR Traceability",
    layout="wide",
    page_icon="logo_harlur.png"  # pakai logo di tab browser
)

# Header utama dengan logo
st.set_page_config(
    page_title="Harlur Coffee QR Traceability",
    layout="wide",
    page_icon="logo_harlur.png"
)

# HEADER DENGAN KONTRAS HITAM PUTIH
header_html = """
<div style="
    display: flex;
    align-items: center;
    background-color: #000; /* latar hitam */
    padding: 15px 25px;
    border-radius: 8px;
">
    <img src="./logo_harlur.png" style="width:65px; margin-right:20px; border-radius:8px;">
    <div>
        <h1 style="color:white; margin-bottom:2px; font-family:Arial, sans-serif;">Harlur Coffee</h1>
        <h4 style="color:#ccc; margin-top:0; font-weight:normal;">QR Traceability System</h4>
    </div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)

# ---------- DATABASE SETUP ----------
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS produksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT,
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
    aktivitas TEXT,
    waktu TEXT
)
""")
conn.commit()


# ---------- UTILITAS ----------
def log_activity(aktivitas):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO log_aktivitas (aktivitas, waktu) VALUES (?, ?)", (aktivitas, waktu))
    conn.commit()


def generate_qr(batch_id):
    link = f"https://harlur-traceability.streamlit.app/?menu=Consumer%20View&batch_id={batch_id}"
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    logo_path = "logo_harlur.png"
    if os.path.exists(logo_path):
        logo = Image.open(logo_path)
        basewidth = 80
        wpercent = basewidth / float(logo.size[0])
        hsize = int((float(logo.size[1]) * float(wpercent)))
        logo = logo.resize((basewidth, hsize))
        pos = ((img_qr.size[0] - logo.size[0]) // 2, (img_qr.size[1] - logo.size[1]) // 2)
        img_qr.paste(logo, pos)

    path = f"{QR_DIR}/{batch_id}.png"
    img_qr.save(path)
    return path, link


def get_batch(batch_id):
    df = pd.read_sql_query("SELECT * FROM produksi WHERE batch_id=?", conn, params=(batch_id,))
    return df if not df.empty else None


def delete_batch(batch_id):
    cursor.execute("DELETE FROM produksi WHERE batch_id=?", (batch_id,))
    conn.commit()
    log_activity(f"Hapus data batch {batch_id}")


def status_expired(date_str):
    try:
        exp_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_left = (exp_date.date() - datetime.now().date()).days
        if days_left < 0:
            return "❌ Expired"
        elif days_left <= 7:
            return f"⚠️ {days_left} hari lagi"
        return f"✅ {days_left} hari lagi"
    except:
        return "⏳ Tidak valid"


# ---------- MENU ----------
menu = st.sidebar.radio("Navigasi", [
    "Tambah Data Produksi", "Lihat Data", "Edit / Hapus Data", "Scan QR", "Log Aktivitas", "Consumer View"
])


# ---------- TAMBAH DATA ----------
if menu == "Tambah Data Produksi":
    st.subheader("Tambah Data Produksi")
    with st.form("form_produksi"):
        col1, col2, col3 = st.columns(3)
        with col1:
            batch_id = st.text_input("Batch ID")
            tanggal = st.date_input("Tanggal Produksi", datetime.now())
            pic = st.text_input("Nama PIC")
        with col2:
            tempat = st.text_input("Tempat Produksi")
            varian = st.text_input("Varian Produksi")
        with col3:
            lokasi = st.text_input("Lokasi Gudang")
            expired = st.date_input("Tanggal Kedaluwarsa", datetime.now() + timedelta(days=180))
        submit = st.form_submit_button("Simpan Data & Buat QR")

        if submit and all([batch_id, tanggal, pic, tempat, varian, lokasi, expired]):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO produksi (batch_id, tanggal, pic, tempat_produksi, varian_produksi,
                lokasi_gudang, expired_date, timestamp, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (batch_id, str(tanggal), pic, tempat, varian, lokasi, str(expired), now, now))
            conn.commit()

            qr_path, link = generate_qr(batch_id)
            log_activity(f"Tambah data batch {batch_id}")

            st.success("Data berhasil disimpan!")
            st.image(qr_path, caption=f"QR Code Batch {batch_id}", width=180)
            st.markdown(f"[🔗 Buka Consumer View]({link})")


# ---------- LIHAT DATA ----------
elif menu == "Lihat Data":
    st.subheader("📋 Daftar Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi ORDER BY id DESC", conn)

    if not df.empty:
        df["QR_Code"] = df["batch_id"].apply(lambda x: f'<img src="data:image/png;base64,{base64.b64encode(open(f"qr_codes/{x}.png","rb").read()).decode()}" width="70">')
        df["Status"] = df["expired_date"].apply(status_expired)
        df_display = df[["timestamp", "batch_id", "tanggal", "pic", "tempat_produksi", "varian_produksi",
                         "lokasi_gudang", "expired_date", "Status", "updated_at", "QR_Code"]]
        df_display.columns = ["Timestamp", "Batch ID", "Tanggal", "PIC", "Tempat", "Varian",
                              "Gudang", "Kedaluwarsa", "Status", "Last Updated", "QR Code"]

        st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

        # Ekspor
        st.download_button("📦 Ekspor ke Excel", df.to_csv(index=False).encode("utf-8"), "data_produksi.csv", "text/csv")
    else:
        st.info("Belum ada data produksi.")


# ---------- EDIT / HAPUS ----------
elif menu == "Edit / Hapus Data":
    st.subheader("✏️ Edit atau Hapus Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi", conn)
    if not df.empty:
        selected = st.selectbox("Pilih Batch ID", df["batch_id"].tolist())
        data = get_batch(selected)
        if data is not None:
            info = data.iloc[0]
            tempat = st.text_input("Tempat Produksi", info["tempat_produksi"])
            varian = st.text_input("Varian Produksi", info["varian_produksi"])
            gudang = st.text_input("Lokasi Gudang", info["lokasi_gudang"])
            expired = st.date_input("Tanggal Kedaluwarsa", datetime.strptime(info["expired_date"], "%Y-%m-%d"))
            colA, colB = st.columns(2)
            with colA:
                if st.button("💾 Simpan Perubahan"):
                    cursor.execute("""UPDATE produksi SET tempat_produksi=?, varian_produksi=?, lokasi_gudang=?, expired_date=?, updated_at=? WHERE batch_id=?""",
                                   (tempat, varian, gudang, str(expired), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), selected))
                    conn.commit()
                    log_activity(f"Edit data batch {selected}")
                    st.success("Data berhasil diperbarui.")
            with colB:
                if st.button("🗑️ Hapus Data"):
                    delete_batch(selected)
                    st.warning(f"Data batch {selected} telah dihapus.")
    else:
        st.info("Belum ada data untuk diedit.")


# ---------- QR SCANNER ----------
elif menu == "Scan QR":
    st.subheader("📸 Scan QR Code Realtime")
    class QRScanner(VideoProcessorBase):
        def __init__(self): self.qr_result = None
        def recv(self, frame):
            img = frame.to_ndarray(format="bgr24")
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
            if data: self.qr_result = data
            return frame

    ctx = webrtc_streamer(key="scanner", mode=WebRtcMode.SENDRECV,
                          video_processor_factory=QRScanner,
                          media_stream_constraints={"video": True, "audio": False})
    if ctx.video_processor and ctx.video_processor.qr_result:
        st.success(f"QR Code Terbaca: {ctx.video_processor.qr_result}")


# ---------- LOG ----------
elif menu == "Log Aktivitas":
    st.subheader("🕒 Riwayat Aktivitas Sistem")
    logs = pd.read_sql_query("SELECT * FROM log_aktivitas ORDER BY id DESC", conn)
    if not logs.empty:
        st.dataframe(logs)
    else:
        st.info("Belum ada aktivitas.")


# ---------- CONSUMER VIEW ----------
elif menu == "Consumer View":
    st.subheader("Informasi Produk Harlur Coffee")
    params = st.query_params
    if "batch_id" in params:
        batch_id = params["batch_id"]
        data = get_batch(batch_id)
        if data is not None:
            info = data.iloc[0]
            st.image("logo_harlur.png", width=150)
            st.write(f"### Varian: {info['varian_produksi']}")
            st.write(f"📅 Tanggal Produksi: {info['tanggal']}")
            st.write(f"🏭 Tempat Produksi: {info['tempat_produksi']}")
            st.write(f"📦 Lokasi Gudang: {info['lokasi_gudang']}")
            st.write(f"⏳ Kedaluwarsa: {info['expired_date']}")
            st.markdown(status_expired(info['expired_date']), unsafe_allow_html=True)
            st.write(f"👤 PIC: {info['pic']}")
            st.markdown("---")
            st.info("Terima kasih telah memilih Harlur Coffee!")
        else:
            st.error("Data batch tidak ditemukan.")
    else:
        st.info("Scan QR Code pada kemasan untuk melihat informasi produk.")
