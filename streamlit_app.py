# =========================================================
# HARLUR COFFEE - QR TRACEABILITY SYSTEM
# Internal Production & Distribution Tracking App
# Last Updated: 2025-11-10
# =========================================================

import streamlit as st
import sqlite3
import qrcode
from PIL import Image
import os
import pandas as pd
import base64
from datetime import datetime, timedelta
import pytz
import cv2
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
from pathlib import Path

# ========== KONFIGURASI DASAR ==========
st.set_page_config(page_title="Harlur Coffee QR Traceability", layout="wide")

# Path aman berbasis direktori Streamlit
BASE_DIR = Path(st.__file__).resolve().parent.parent  # path root Streamlit app
DATA_DIR = BASE_DIR / "app_data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "data_produksi.db"
QR_DIR = DATA_DIR / "qr_codes"
QR_DIR.mkdir(exist_ok=True)

# Path logo (gunakan Path agar lintas OS)
LOGO_PATH = DATA_DIR / "logo_harlur.png"
if not LOGO_PATH.exists():
    LOGO_PATH = Path("logo_harlur.png")  # fallback jika logo di root

# Set timezone ke WIB
WIB = pytz.timezone("Asia/Jakarta")

# ========== DATABASE ==========
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
conn.commit()

# ========== FUNGSI UTILITAS ==========
def now_wib():
    """Mengembalikan waktu saat ini dalam format WIB"""
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

def safe_path(path: Path):
    """Pastikan folder path tersedia"""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

# ========== FUNGSI QR DAN DATABASE ==========
def tambah_data(batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date):
    timestamp = now_wib()
    cursor.execute("""
        INSERT INTO produksi (
            batch_id, tanggal, pic, tempat_produksi, varian_produksi,
            lokasi_gudang, expired_date, timestamp, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date, timestamp, timestamp))
    conn.commit()

    # Gunakan path-safe untuk file QR
    link = f"https://harlur-traceability.streamlit.app/?menu=Consumer%20View&batch_id={batch_id}"
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Tambahkan logo jika tersedia
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH)
        basewidth = 80
        wpercent = basewidth / float(logo.size[0])
        hsize = int((float(logo.size[1]) * float(wpercent)))
        logo = logo.resize((basewidth, hsize))
        pos = ((img_qr.size[0] - logo.size[0]) // 2, (img_qr.size[1] - logo.size[1]) // 2)
        img_qr.paste(logo, pos)

    qr_path = safe_path(QR_DIR / f"{batch_id}.png")
    img_qr.save(qr_path)
    return str(qr_path), link


def get_batch_info(batch_id):
    query = "SELECT * FROM produksi WHERE batch_id = ?"
    df = pd.read_sql_query(query, conn, params=(batch_id,))
    return df if not df.empty else None


def update_data(batch_id, tempat, varian, lokasi_gudang, expired_date):
    updated_at = now_wib()
    cursor.execute("""
        UPDATE produksi
        SET tempat_produksi = ?, varian_produksi = ?, lokasi_gudang = ?, expired_date = ?, updated_at = ?
        WHERE batch_id = ?
    """, (tempat, varian, lokasi_gudang, expired_date, updated_at, batch_id))
    conn.commit()


def status_expired(expired_date_str):
    try:
        exp_date = datetime.strptime(expired_date_str, "%Y-%m-%d")
        today = datetime.now(WIB).date()
        delta = (exp_date.date() - today).days
        if delta < 0:
            return f"<span style='color:red;font-weight:bold;'>❌ Expired</span>"
        elif delta <= 7:
            return f"<span style='color:orange;font-weight:bold;'>⚠️ Hampir kedaluwarsa ({delta} hari lagi)</span>"
        else:
            return f"<span style='color:green;font-weight:bold;'>✅ Aman ({delta} hari lagi)</span>"
    except Exception:
        return "⏳ Tidak valid"

# ========== SIDEBAR ==========
if LOGO_PATH.exists():
    st.sidebar.image(str(LOGO_PATH), width=130)
st.sidebar.markdown("### Harlur Coffee Traceability")
menu = st.sidebar.radio("Navigasi", ["Tambah Data", "Lihat Data", "Edit Data", "Scan QR Realtime", "Consumer View"])

# ========== TAMBAH DATA ==========
if menu == "Tambah Data":
    st.title("Tambah Data Produksi")

    with st.form("form_produksi"):
        col1, col2, col3 = st.columns(3)
        with col1:
            batch_id = st.text_input("Batch ID")
            tanggal = st.date_input("Tanggal Produksi", datetime.now(WIB))
            pic = st.text_input("Nama PIC")
        with col2:
            tempat = st.text_input("Tempat Produksi")
            varian = st.text_input("Varian Produksi")
        with col3:
            lokasi_gudang = st.text_input("Lokasi Gudang")
            expired_date = st.date_input("Tanggal Kedaluwarsa", datetime.now(WIB) + timedelta(days=180))

        submitted = st.form_submit_button("Simpan Data dan Buat QR Code")

        if submitted:
            if all([batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date]):
                qr_path, link = tambah_data(batch_id, str(tanggal), pic, tempat, varian, lokasi_gudang, str(expired_date))
                st.success("Data berhasil disimpan.")
                st.image(qr_path, caption=f"QR Code Batch {batch_id}", width=200)
                st.markdown(f"[Lihat Consumer View]({link})")
            else:
                st.warning("Harap isi semua kolom.")

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
