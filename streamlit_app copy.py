import streamlit as st
import sqlite3
import qrcode
from PIL import Image
import os
import pandas as pd
import base64
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import cv2
import numpy as np

# =============== KONFIGURASI DASAR ===============
st.set_page_config(page_title="QR Tracking Harlur Coffee", page_icon="☕", layout="wide")
st.title("☕ QR Tracking Harlur Coffee")
st.markdown("Mencatat, melacak, dan memverifikasi data produksi kopi Harlur dengan sistem QR Code dua arah.")

# Folder kerja aman untuk Cloud
BASE_DIR = os.path.join(os.getcwd(), "temp_data")
os.makedirs(BASE_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "data_produksi.db")
QR_FOLDER = os.path.join(BASE_DIR, "qr_codes")
os.makedirs(QR_FOLDER, exist_ok=True)

# =============== DATABASE ===============
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS produksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT,
    tanggal TEXT,
    pic TEXT,
    tempat_produksi TEXT,
    varian_produksi TEXT
)
""")
conn.commit()

# =============== FUNGSI QR & DATABASE ===============
def tambah_data(batch_id, tanggal, pic, tempat, varian):
    cursor.execute("""
        INSERT INTO produksi (batch_id, tanggal, pic, tempat_produksi, varian_produksi)
        VALUES (?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian))
    conn.commit()

    # 🔗 QR mengarah ke halaman Streamlit consumer view
    qr_text = f"https://harlur-trace.streamlit.app/?batch_id={batch_id}"

    # Buat QR code dengan warna & ukuran
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)

    # Warna khas kopi (#4B2E05)
    qr_img = qr.make_image(fill_color="#4B2E05", back_color="white").convert("RGB")

    # Tambahkan logo di tengah QR
    logo_path = "logo_harlur.png"
    if os.path.exists(logo_path):
        logo = Image.open(logo_path)

        # Resize logo agar proporsional (±25% dari QR)
        qr_width, qr_height = qr_img.size
        logo_size = int(qr_width * 0.25)
        logo = logo.resize((logo_size, logo_size))

        # Hitung posisi tengah
        pos = ((qr_width - logo_size) // 2, (qr_height - logo_size) // 2)
        qr_img.paste(logo, pos, mask=logo if logo.mode == "RGBA" else None)

    qr_path = os.path.join(QR_FOLDER, f"{batch_id}.png")
    qr_img.save(qr_path)

    return qr_path


def image_to_base64(path):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def get_batch_info(batch_id):
    df = pd.read_sql_query(f"SELECT * FROM produksi WHERE batch_id='{batch_id}'", conn)
    return df if not df.empty else None


def generate_pdf(batch_id, data):
    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 800, "Sertifikat Produksi - Harlur Coffee")
    c.setFont("Helvetica", 12)
    c.drawString(100, 770, f"Batch ID: {batch_id}")
    c.drawString(100, 750, f"Tanggal Produksi: {data['tanggal'].values[0]}")
    c.drawString(100, 730, f"PIC: {data['pic'].values[0]}")
    c.drawString(100, 710, f"Tempat Produksi: {data['tempat_produksi'].values[0]}")
    c.drawString(100, 690, f"Varian Produksi: {data['varian_produksi'].values[0]}")

    qr_path = os.path.join(QR_FOLDER, f"{batch_id}.png")
    if os.path.exists(qr_path):
        c.drawImage(qr_path, 100, 520, width=150, height=150)

    c.setFont("Helvetica-Oblique", 10)
    c.drawString(100, 500, "Disahkan secara digital oleh sistem QR Tracking Harlur Coffee.")
    c.showPage()
    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer

# =============== MENU ===============
menu = st.sidebar.selectbox("📋 Pilih Menu", ["Tambah Data", "Lihat Data", "Scan QR", "Consumer View"])

# =============== 1️⃣ TAMBAH DATA ===============
if menu == "Tambah Data":
    st.subheader("📦 Input Data Produksi Baru")

    with st.form("form_produksi"):
        batch_id = st.text_input("Batch ID")
        tanggal = st.date_input("Tanggal Produksi")
        pic = st.text_input("Nama PIC")
        tempat = st.text_input("Tempat Produksi")
        varian = st.text_input("Varian Produksi (jenis kopi, rasa, dll.)")
        submitted = st.form_submit_button("Simpan Data & Buat QR")

        if submitted:
            if all([batch_id, tanggal, pic, tempat, varian]):
                qr_path = tambah_data(batch_id, str(tanggal), pic, tempat, varian)
                st.success("✅ Data berhasil disimpan!")
                st.image(qr_path, caption=f"QR Code untuk Batch {batch_id}", width=250)
                st.markdown(f"🔗 [Buka Halaman Batch Ini](https://harlur-trace.streamlit.app/?batch_id={batch_id})")
            else:
                st.error("⚠️ Harap isi semua kolom sebelum menyimpan.")

# =============== 2️⃣ LIHAT DATA ===============
elif menu == "Lihat Data":
    st.subheader("📋 Daftar Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi", conn)

    if not df.empty:
        df["QR_Code_Path"] = df["batch_id"].apply(lambda x: os.path.join(QR_FOLDER, f"{x}.png"))

        def make_img_tag(path):
            if os.path.exists(path):
                img_b64 = image_to_base64(path)
                return f'<img src="data:image/png;base64,{img_b64}" width="100">'
            else:
                return "❌ Tidak ditemukan"

        df["QR_Code"] = df["QR_Code_Path"].apply(make_img_tag)
        df_display = df[["batch_id", "tanggal", "pic", "tempat_produksi", "varian_produksi", "QR_Code"]]
        df_display.columns = ["Batch ID", "Tanggal", "PIC", "Tempat Produksi", "Varian Produksi", "QR Code"]

        st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

        # Tombol ekspor Excel
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Unduh Data Produksi (Excel/CSV)", csv, "data_produksi.csv", "text/csv")

        # Tombol ekspor PDF
        selected_batch = st.selectbox("Pilih batch untuk ekspor PDF:", df["batch_id"])
        if st.button("📄 Unduh Sertifikat PDF"):
            data = get_batch_info(selected_batch)
            if data is not None:
                pdf_data = generate_pdf(selected_batch, data)
                st.download_button(
                    label=f"⬇️ Download Sertifikat Batch {selected_batch}",
                    data=pdf_data,
                    file_name=f"Sertifikat_{selected_batch}.pdf",
                    mime="application/pdf"
                )
    else:
        st.info("Belum ada data produksi tersimpan.")

# =============== 3️⃣ SCAN QR ===============
elif menu == "Scan QR":
    st.subheader("📸 Scan QR Code dari Gambar (OpenCV)")
    uploaded_file = st.file_uploader("Unggah gambar QR (png/jpg)", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

        # Gunakan OpenCV QRCodeDetector (tanpa zbar)
        qr_detector = cv2.QRCodeDetector()
        data, bbox, _ = qr_detector.detectAndDecode(img)

        if data:
            st.success(f"QR Code terbaca: {data}")
            if "batch_id=" in data:
                batch_id = data.split("=")[-1]
                batch = get_batch_info(batch_id)
                if batch is not None:
                    st.write("### Informasi Batch:")
                    st.dataframe(batch)
                else:
                    st.warning("Batch ID tidak ditemukan di database.")
        else:
            st.error("Tidak dapat membaca QR code dari gambar yang diunggah.")

# =============== 4️⃣ CONSUMER VIEW ===============
elif menu == "Consumer View":
    query_params = st.query_params
    if "batch_id" in query_params:
        batch_id = query_params["batch_id"]
        data = get_batch_info(batch_id)
        if data is not None:
            st.success(f"Menampilkan informasi untuk Batch {batch_id}")
            st.dataframe(data)
        else:
            st.error("Batch ID tidak ditemukan di database.")
    else:
        st.info("Gunakan QR Code pada kemasan untuk membuka halaman ini langsung.")
