# =========================================================
# HARLUR COFFEE - QR TRACEABILITY SYSTEM
# Deployment-safe version (Streamlit Cloud Compatible)
# Last Updated: 2025-11-10
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
import time  # 🆕 untuk efek progress spinner
import zipfile
import io

# ========== KONFIGURASI DASAR ==========
st.set_page_config(page_title="Harlur Coffee QR Traceability", layout="wide")

# Gunakan direktori kerja yang writable (misalnya /tmp di Streamlit Cloud)
BASE_DIR = Path(tempfile.gettempdir()) / "harlur_traceability"
DATA_DIR = BASE_DIR / "app_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "data_produksi.db"
QR_DIR = DATA_DIR / "qr_codes"
QR_DIR.mkdir(parents=True, exist_ok=True)

# Path logo (gunakan Path agar lintas OS)
LOGO_PATH = DATA_DIR / "logo_harlur.png"
if not LOGO_PATH.exists():
    LOGO_PATH = Path("logo_harlur.png")  # fallback jika logo di root

# Set timezone ke WIB
WIB = pytz.timezone("Asia/Jakarta")

# ========== DATABASE ==========
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Tabel produksi
cursor.execute("""
CREATE TABLE IF NOT EXISTS produksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT UNIQUE,  -- 🆕 Unik untuk mencegah duplikasi
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

# Tabel log aktivitas
cursor.execute("""
CREATE TABLE IF NOT EXISTS log_aktivitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    waktu TEXT,
    deskripsi TEXT
)
""")
conn.commit()

# ========== FUNGSI UTILITAS ==========
def now_wib():
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

def backup_to_github(filename: str, content: bytes, commit_message="Auto backup from Streamlit"):
    """Upload file backup (CSV/ZIP) ke repository GitHub via API."""
    GITHUB_USER = "USERNAME_KAMU"     # Ganti dengan username GitHub kamu
    GITHUB_REPO = "REPO_KAMU"         # Ganti dengan nama repo kamu
    GITHUB_PATH = f"backup/{filename}"
    TOKEN = st.secrets["GITHUB_TOKEN"]

    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{GITHUB_PATH}"

    # Cek apakah file sudah ada
    r = requests.get(url, headers={"Authorization": f"token {TOKEN}"})
    sha = r.json().get("sha") if r.status_code == 200 else None

    # Payload data
    data = {
        "message": commit_message,
        "content": base64.b64encode(content).decode("utf-8"),
        "branch": "main"
    }
    if sha:
        data["sha"] = sha

    res = requests.put(url, headers={"Authorization": f"token {TOKEN}"}, json=data)
    if res.status_code in [200, 201]:
        log_activity(f"Backup ke GitHub: {filename}")
        st.success(f"✅ Backup berhasil diunggah ke GitHub ({filename})")
    else:
        st.error(f"Gagal upload ke GitHub: {res.status_code} — {res.text}")

def backup_database():
    """Ekspor data produksi dan QR code ke GitHub (CSV + ZIP)"""
    df = pd.read_sql_query("SELECT * FROM produksi", conn)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    timestamp = datetime.now(WIB).strftime('%Y%m%d_%H%M')

    # Backup CSV
    csv_filename = f"data_backup_{timestamp}.csv"
    backup_to_github(csv_filename, csv_bytes, f"Backup otomatis CSV {timestamp}")

    # Backup semua QR Code ke ZIP
    qr_zip_bytes = io.BytesIO()
    with zipfile.ZipFile(qr_zip_bytes, "w", zipfile.ZIP_DEFLATED) as zf:
        for qr_file in QR_DIR.glob("*.png"):
            zf.write(qr_file, qr_file.name)
    qr_zip_bytes.seek(0)
    zip_filename = f"qr_backup_{timestamp}.zip"
    backup_to_github(zip_filename, qr_zip_bytes.getvalue(), f"Backup otomatis QR {timestamp}")


def safe_path(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def log_activity(deskripsi: str):
    waktu = now_wib()
    cursor.execute("INSERT INTO log_aktivitas (waktu, deskripsi) VALUES (?, ?)", (waktu, deskripsi))
    conn.commit()

def delete_batch(batch_id: str):
    try:
        cursor.execute("DELETE FROM produksi WHERE batch_id = ?", (batch_id,))
        conn.commit()
        qr_path = QR_DIR / f"{batch_id}.png"
        if qr_path.exists():
            qr_path.unlink()
        log_activity(f"Hapus data batch {batch_id}")
    except Exception as e:
        st.error(f"Gagal menghapus data batch {batch_id}: {e}")

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

def export_pdf(batch_id: str):
    """Membuat file PDF berisi detail batch dan QR code."""
    data = get_batch(batch_id)
    if data is None or data.empty:
        st.error("Data batch tidak ditemukan.")
        return None

    info = data.iloc[0]
    pdf_path = DATA_DIR / f"{batch_id}.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4

    # Logo (opsional)
    if LOGO_PATH.exists():
        c.drawImage(ImageReader(str(LOGO_PATH)), 50, height - 120, width=100, height=100, mask='auto')

    # Judul
    c.setFont("Helvetica-Bold", 20)
    c.drawString(170, height - 70, "Harlur Coffee - Product Traceability Report")

    # Garis pembatas
    c.line(50, height - 130, width - 50, height - 130)

    # Detail produk
    c.setFont("Helvetica", 12)
    y = height - 160
    spacing = 20
    details = [
        ("Batch ID", info["batch_id"]),
        ("Tanggal Produksi", info["tanggal"]),
        ("Varian Produksi", info["varian_produksi"]),
        ("Tempat Produksi", info["tempat_produksi"]),
        ("Lokasi Gudang", info["lokasi_gudang"]),
        ("PIC", info["pic"]),
        ("Tanggal Kedaluwarsa", info["expired_date"]),
        ("Dibuat pada", info["timestamp"]),
    ]
    for label, value in details:
        c.drawString(60, y, f"{label}: {value}")
        y -= spacing

    # Tambahkan QR Code
    qr_path = QR_DIR / f"{batch_id}.png"
    if qr_path.exists():
        c.drawImage(ImageReader(str(qr_path)), width - 220, height - 300, width=150, height=150, mask='auto')
    else:
        c.setFont("Helvetica-Oblique", 12)
        c.drawString(width - 210, height - 200, "(QR Code tidak ditemukan)")

    # Footer
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(width / 2, 50, "Dokumen ini dihasilkan otomatis oleh sistem traceability Harlur Coffee.")
    c.showPage()
    c.save()

    log_activity(f"Ekspor PDF batch {batch_id}")
    return pdf_path


# ========== FUNGSI QR DAN DATABASE ==========
def tambah_data(batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date):
    # 🆕 Validasi unik Batch ID
    cursor.execute("SELECT COUNT(*) FROM produksi WHERE batch_id=?", (batch_id,))
    if cursor.fetchone()[0] > 0:
        st.error("⚠️ Batch ID sudah terdaftar, gunakan ID lain.")
        return None, None

    timestamp = now_wib()
    cursor.execute("""
        INSERT INTO produksi (
            batch_id, tanggal, pic, tempat_produksi, varian_produksi,
            lokasi_gudang, expired_date, timestamp, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date, timestamp, timestamp))
    conn.commit()
    log_activity(f"Tambah data batch {batch_id}")

    # Generate QR code
    link = f"https://harlur-traceability.streamlit.app/?menu=Consumer%20View&batch_id={batch_id}"
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")

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

def get_batch(batch_id):
    query = "SELECT * FROM produksi WHERE batch_id = ?"
    df = pd.read_sql_query(query, conn, params=(batch_id,))
    return df if not df.empty else None

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

# 🆕 Perbaikan navigasi otomatis dari query params
query_params = st.query_params
available_menus = [
    "Tambah Data", "Lihat Data", "Edit / Hapus Data",
    "Scan QR", "Log Aktivitas", "Consumer View"
]

# Default menu
default_menu = "Tambah Data"

# Jika URL mengandung menu= atau batch_id=, arahkan otomatis
if "menu" in query_params:
    requested_menu = query_params["menu"]
    if requested_menu in available_menus:
        default_menu = requested_menu
elif "batch_id" in query_params:
    default_menu = "Consumer View"

# Sidebar navigation
menu = st.sidebar.radio("Navigasi", available_menus, index=available_menus.index(default_menu))

# ---------- TAMBAH DATA ----------
if menu == "Tambah Data":
    st.title("Tambah Data Produksi")
    with st.form("form_produksi"):
        col1, col2, col3 = st.columns(3)
        with col1:
            batch_id = st.text_input("Batch ID").strip().upper()
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
            # === VALIDASI DASAR ===
            if not all([batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date]):
                st.warning("⚠️ Harap isi semua kolom dengan lengkap.")
            elif expired_date <= tanggal:
                st.error("❌ Tanggal kedaluwarsa harus setelah tanggal produksi.")
            else:
                # === CEK DUPLIKASI batch_id ===
                cursor.execute("SELECT COUNT(*) FROM produksi WHERE batch_id=?", (batch_id,))
                sudah_ada = cursor.fetchone()[0]
                if sudah_ada > 0:
                    st.warning(f"⚠️ Batch ID '{batch_id}' sudah terdaftar. Gunakan ID lain.")
                else:
                    # === PROSES PENYIMPANAN DATA ===
                    with st.spinner("📦 Menyimpan data dan membuat QR code..."):
                        try:
                            time.sleep(1)
                            qr_path, link = tambah_data(
                                batch_id, str(tanggal), pic, tempat, varian, lokasi_gudang, str(expired_date)
                            )
                            st.success("✅ Data berhasil disimpan dan QR Code dibuat.")
                            st.image(qr_path, caption=f"QR Code Batch {batch_id}", width=200)
                            st.markdown(f"[🔗 Lihat Consumer View]({link})")
                            st.toast(f"Data batch {batch_id} berhasil ditambahkan.", icon="✅")

                            # === BACKUP OTOMATIS KE GITHUB ===
                            with st.spinner("💾 Melakukan backup otomatis ke GitHub..."):
                                try:
                                    backup_database()
                                except Exception as e:
                                    st.error(f"Gagal melakukan backup otomatis: {e}")
                        except Exception as e:
                            st.error(f"Terjadi kesalahan saat menyimpan data: {e}")

# ---------- LIHAT DATA ----------
elif menu == "Lihat Data":
    st.subheader("📋 Daftar Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi ORDER BY id DESC", conn)
    if not df.empty:
        df["QR_Code"] = df["batch_id"].apply(
            lambda x: f'<img src="data:image/png;base64,{base64.b64encode(open(QR_DIR / f"{x}.png","rb").read()).decode()}" width="70">'
            if (QR_DIR / f"{x}.png").exists() else "❌"
        )
        df["Status"] = df["expired_date"].apply(status_expired)
        df_display = df[["timestamp", "batch_id", "tanggal", "pic", "tempat_produksi",
                         "varian_produksi", "lokasi_gudang", "expired_date", "Status", "updated_at", "QR_Code"]]
        df_display.columns = ["Timestamp", "Batch ID", "Tanggal", "PIC", "Tempat", "Varian",
                              "Gudang", "Kedaluwarsa", "Status", "Last Updated", "QR Code"]

        st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)
        st.download_button("📦 Ekspor ke CSV", df.to_csv(index=False).encode("utf-8"),
                           "data_produksi.csv", "text/csv")

        # Pilih batch untuk ekspor PDF
        selected_pdf = st.selectbox("Pilih Batch untuk Ekspor PDF", df["batch_id"].tolist())

        # Tombol ekspor ke PDF
        if st.button("📄 Ekspor ke PDF"):
            pdf_path = export_pdf(selected_pdf)
            if pdf_path and pdf_path.exists():
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label=f"⬇️ Unduh Laporan {selected_pdf}.pdf",
                        data=f,
                        file_name=f"{selected_pdf}.pdf",
                        mime="application/pdf"
                    )
                    
    else:
        st.info("Belum ada data produksi.")

# ---------- SCAN QR ----------
elif menu == "Scan QR":
    st.subheader("📸 Scan QR Code Realtime atau Upload Gambar")

    # Pilihan metode scan
    metode = st.radio("Pilih Metode Pemindaian", ["Kamera", "Upload Gambar"])

    # --- OPSI 1: SCAN DARI KAMERA ---
    if metode == "Kamera":
        class QRScanner(VideoProcessorBase):
            def __init__(self): self.qr_result = None
            def recv(self, frame):
                img = frame.to_ndarray(format="bgr24")
                data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
                if data: self.qr_result = data
                return frame

        ctx = webrtc_streamer(
            key="scanner",
            mode=WebRtcMode.SENDRECV,
            video_processor_factory=QRScanner,
            media_stream_constraints={"video": True, "audio": False}
        )

        if ctx.video_processor and ctx.video_processor.qr_result:
            st.success(f"QR Code Terbaca: {ctx.video_processor.qr_result}")
            st.markdown(f"[🔗 Buka Tautan]({ctx.video_processor.qr_result})")

    # --- OPSI 2: UPLOAD GAMBAR QR ---
    else:
        uploaded_qr = st.file_uploader("Unggah Gambar QR (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if uploaded_qr:
            img = Image.open(uploaded_qr)
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img_cv)

            if data:
                st.image(img, caption="QR Terdeteksi", width=200)
                st.success(f"QR Code Terbaca: {data}")
                st.markdown(f"[🔗 Buka Tautan]({data})")
            else:
                st.warning("⚠️ QR tidak dapat dibaca dari gambar ini.")

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
                    cursor.execute("""
                        UPDATE produksi
                        SET tempat_produksi=?, varian_produksi=?, lokasi_gudang=?, expired_date=?, updated_at=?
                        WHERE batch_id=?
                    """, (tempat, varian, gudang, str(expired), now_wib(), selected))
                    conn.commit()
                    log_activity(f"Edit data batch {selected}")
                    st.success("Data berhasil diperbarui.")
            with colB:
                if st.button("🗑️ Hapus Data"):
                    delete_batch(selected)
                    st.warning(f"Data batch {selected} telah dihapus.")
    else:
        st.info("Belum ada data untuk diedit.")

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
            if LOGO_PATH.exists():
                st.image(str(LOGO_PATH), width=150)
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
