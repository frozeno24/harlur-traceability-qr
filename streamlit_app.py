import streamlit as st
import sqlite3
import qrcode
from PIL import Image
import os
import pandas as pd
import base64
from datetime import datetime, timedelta
import cv2
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode

# ========== CONFIG ==========
DB_PATH = "data_produksi.db"
os.makedirs("qr_codes", exist_ok=True)
st.set_page_config(page_title="Harlur Coffee QR Traceability", layout="wide")

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
cursor.execute("""
CREATE TABLE IF NOT EXISTS log_aktivitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    aksi TEXT,
    batch_id TEXT,
    pic TEXT,
    keterangan TEXT
)
""")
conn.commit()

# ========== FUNGSI LOG ==========
def tambah_log(aksi, batch_id, pic, keterangan=""):
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO log_aktivitas (timestamp, aksi, batch_id, pic, keterangan)
        VALUES (?, ?, ?, ?, ?)
    """, (waktu, aksi, batch_id, pic, keterangan))
    conn.commit()


# ========== FUNCTIONS PRODUKSI ==========
def tambah_data(batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO produksi (
            batch_id, tanggal, pic, tempat_produksi, varian_produksi,
            lokasi_gudang, expired_date, timestamp, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date, timestamp, timestamp))
    conn.commit()
    tambah_log("Tambah Data", batch_id, pic, "Data baru ditambahkan ke sistem")

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

    qr_path = f"qr_codes/{batch_id}.png"
    img_qr.save(qr_path)
    return qr_path, link


def get_batch_info(batch_id):
    query = "SELECT * FROM produksi WHERE batch_id = ?"
    df = pd.read_sql_query(query, conn, params=(batch_id,))
    return df if not df.empty else None


def delete_batch(batch_id):
    cursor.execute("SELECT pic FROM produksi WHERE batch_id = ?", (batch_id,))
    row = cursor.fetchone()
    pic = row[0] if row else "-"
    cursor.execute("DELETE FROM produksi WHERE batch_id = ?", (batch_id,))
    conn.commit()
    qr_path = f"qr_codes/{batch_id}.png"
    if os.path.exists(qr_path):
        os.remove(qr_path)
    tambah_log("Hapus Data", batch_id, pic, "Data dihapus dari sistem")


def generate_pdf(batch_id, data):
    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 800, "Data Produksi Harlur Coffee")
    c.setFont("Helvetica", 12)
    y = 770
    for key, value in data.iloc[0].items():
        c.drawString(100, y, f"{key}: {value}")
        y -= 20
    qr_path = f"qr_codes/{batch_id}.png"
    if os.path.exists(qr_path):
        c.drawImage(qr_path, 100, y-160, width=150, height=150)
    c.showPage()
    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def status_expired(expired_date_str):
    try:
        exp_date = datetime.strptime(expired_date_str, "%Y-%m-%d")
        today = datetime.now().date()
        delta = (exp_date.date() - today).days
        if delta < 0:
            return f"<span style='color:red;font-weight:bold;'>❌ Expired</span>"
        elif delta <= 7:
            return f"<span style='color:orange;font-weight:bold;'>⚠️ Hampir Kedaluwarsa ({delta} hari lagi)</span>"
        else:
            return f"<span style='color:green;font-weight:bold;'>✅ Aman ({delta} hari lagi)</span>"
    except Exception:
        return "⏳ Tidak valid"


# ========== SIDEBAR ==========
st.sidebar.image("logo_harlur.png", width=130)
st.sidebar.markdown("### Harlur Coffee Traceability")
menu = st.sidebar.radio("Navigasi", ["Tambah Data", "Lihat Data", "Riwayat Aktivitas", "Scan QR Realtime", "Consumer View"])

# ========== TAMBAH DATA ==========
if menu == "Tambah Data":
    st.title("Tambah Data Produksi")

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
            lokasi_gudang = st.text_input("Lokasi Gudang")
            expired_date = st.date_input("Tanggal Kedaluwarsa", datetime.now() + timedelta(days=180))

        submitted = st.form_submit_button("Simpan Data dan Buat QR Code")

        if submitted:
            if all([batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date]):
                qr_path, link = tambah_data(batch_id, str(tanggal), pic, tempat, varian, lokasi_gudang, str(expired_date))
                st.success("✅ Data berhasil disimpan.")
                st.image(qr_path, caption=f"QR Code Batch {batch_id}", width=200)
                st.markdown(f"[🔗 Lihat Consumer View]({link})")
            else:
                st.warning("⚠️ Harap isi semua kolom.")

# ========== LIHAT DATA ==========
elif menu == "Lihat Data":
    st.subheader("📋 Daftar Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi", conn)

    if not df.empty:
        df["QR_Code_Path"] = df["batch_id"].apply(lambda x: f"qr_codes/{x}.png")

        def make_img_tag(path):
            if os.path.exists(path):
                with open(path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                    return f'<img src="data:image/png;base64,{img_b64}" width="80">'
            else:
                return "❌ Tidak ditemukan"

        df["Status"] = df["expired_date"].apply(status_expired)
        df["QR_Code"] = df["QR_Code_Path"].apply(make_img_tag)

        df_display = df[[
            "timestamp", "batch_id", "tanggal", "pic", "tempat_produksi",
            "varian_produksi", "lokasi_gudang", "expired_date", "Status", "updated_at", "QR_Code"
        ]]
        df_display.columns = [
            "Timestamp", "Batch ID", "Tanggal", "PIC", "Tempat Produksi",
            "Varian", "Lokasi Gudang", "Kedaluwarsa", "Status", "Last Updated", "QR Code"
        ]

        st.markdown("""
        <style>
        table {width:100%; border-collapse: collapse;}
        th {background-color: black; color: white; padding: 8px;}
        td {padding: 8px; border-bottom: 1px solid #ddd;}
        </style>
        """, unsafe_allow_html=True)
        st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

        # Ekspor data
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📦 Ekspor ke Excel (CSV)", csv, "data_produksi.csv", "text/csv")

        batch_to_export = st.selectbox("Pilih batch untuk ekspor PDF:", df["batch_id"])
        if st.button("📄 Ekspor ke PDF"):
            data = get_batch_info(batch_to_export)
            if data is not None:
                pdf = generate_pdf(batch_to_export, data)
                st.download_button(
                    label=f"⬇️ Download Sertifikat Batch {batch_to_export}",
                    data=pdf,
                    file_name=f"Sertifikat_{batch_to_export}.pdf",
                    mime="application/pdf"
                )

        batch_to_delete = st.selectbox("🗑️ Pilih batch untuk dihapus:", df["batch_id"])
        if st.button("Hapus Data"):
            delete_batch(batch_to_delete)
            st.warning(f"Data batch {batch_to_delete} telah dihapus.")
            st.experimental_rerun()

    else:
        st.info("Belum ada data produksi tersimpan.")

# ========== RIWAYAT AKTIVITAS ==========
elif menu == "Riwayat Aktivitas":
    st.subheader("📜 Log Aktivitas Sistem")
    log_df = pd.read_sql_query("SELECT * FROM log_aktivitas ORDER BY id DESC", conn)
    if not log_df.empty:
        st.markdown("""
        <style>
        table {width:100%; border-collapse: collapse;}
        th {background-color: black; color: white; padding: 8px;}
        td {padding: 8px; border-bottom: 1px solid #ddd;}
        </style>
        """, unsafe_allow_html=True)
        st.markdown(log_df.to_html(index=False, escape=False), unsafe_allow_html=True)
    else:
        st.info("Belum ada aktivitas yang tercatat.")

# ========== QR SCANNER ==========
elif menu == "Scan QR Realtime":
    st.title("Scan QR Code Langsung dari Kamera")

    class QRScanner(VideoProcessorBase):
        def __init__(self):
            self.qr_result = None
        def recv(self, frame):
            img = frame.to_ndarray(format="bgr24")
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(img)
            if data:
                self.qr_result = data
            return frame

    ctx = webrtc_streamer(key="scanner", mode=WebRtcMode.SENDRECV, video_processor_factory=QRScanner,
                          media_stream_constraints={"video": True, "audio": False}, async_processing=True)

    if ctx.video_processor and ctx.video_processor.qr_result:
        st.success(f"QR Code Terbaca: {ctx.video_processor.qr_result}")
        if "batch_id=" in ctx.video_processor.qr_result:
            batch_id = ctx.video_processor.qr_result.split("=")[-1]
            data = get_batch_info(batch_id)
            if data is not None:
                st.dataframe(data)
            else:
                st.warning("Batch ID tidak ditemukan.")

# ========== CONSUMER VIEW ==========
elif menu == "Consumer View":
    st.title("Informasi Produk Harlur Coffee")
    query_params = st.query_params
    if "batch_id" in query_params:
        batch_id = query_params["batch_id"]
        data = get_batch_info(batch_id)
        if data is not None:
            info = data.iloc[0]
            st.image("logo_harlur.png", width=150)
            st.subheader(f"Varian: {info['varian_produksi']}")
            st.write(f"Tanggal Produksi: {info['tanggal']}")
            st.write(f"Tempat Produksi: {info['tempat_produksi']}")
            st.write(f"Lokasi Gudang: {info['lokasi_gudang']}")
            st.write(f"Kedaluwarsa: {info['expired_date']}")
            st.markdown(status_expired(info["expired_date"]), unsafe_allow_html=True)
            st.write(f"PIC: {info['pic']}")
            st.markdown("---")
            st.info("Terima kasih telah memilih Harlur Coffee!")
        else:
            st.error("Data batch tidak ditemukan.")
    else:
        st.info("Scan QR Code dari kemasan untuk melihat informasi produk.")
