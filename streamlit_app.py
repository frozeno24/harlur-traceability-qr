import streamlit as st
import sqlite3
import qrcode
from PIL import Image
import os
import pandas as pd
import base64
from datetime import datetime, timedelta
import cv2
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO

# ========= CONFIG =========
DB_PATH = "data_produksi.db"
os.makedirs("qr_codes", exist_ok=True)
st.set_page_config(page_title="Harlur Coffee QR Traceability", layout="wide")

# ========= DATABASE =========
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

# ========= FUNGSI =========
def tambah_data(batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO produksi (
            batch_id, tanggal, pic, tempat_produksi, varian_produksi,
            lokasi_gudang, expired_date, timestamp, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian, lokasi_gudang, expired_date, timestamp, timestamp))
    conn.commit()

    link = f"https://harlur-traceability.streamlit.app/?batch_id={batch_id}"
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


def update_data(batch_id, tempat, varian, lokasi_gudang, expired_date):
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        UPDATE produksi
        SET tempat_produksi = ?, varian_produksi = ?, lokasi_gudang = ?, expired_date = ?, updated_at = ?
        WHERE batch_id = ?
    """, (tempat, varian, lokasi_gudang, expired_date, updated_at, batch_id))
    conn.commit()


def delete_data(batch_id):
    cursor.execute("DELETE FROM produksi WHERE batch_id = ?", (batch_id,))
    conn.commit()


def status_expired(expired_date_str):
    try:
        exp_date = datetime.strptime(expired_date_str, "%Y-%m-%d")
        today = datetime.now().date()
        delta = (exp_date.date() - today).days
        if delta < 0:
            return f"<span style='color:red;font-weight:bold;'>❌ Expired</span>"
        elif delta <= 7:
            return f"<span style='color:orange;font-weight:bold;'>⚠️ Hampir kedaluwarsa ({delta} hari lagi)</span>"
        else:
            return f"<span style='color:green;font-weight:bold;'>✅ Aman ({delta} hari lagi)</span>"
    except Exception:
        return "⏳ Tidak valid"


def make_img_tag(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
            return f'<img src="data:image/png;base64,{img_b64}" width="100">'
    else:
        return "❌ Tidak ditemukan"


def generate_pdf(batch_id):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    data = get_batch_info(batch_id)
    if data is not None:
        d = data.iloc[0]
        c.setFont("Helvetica-Bold", 16)
        c.drawString(100, 800, "Sertifikat Produksi Harlur Coffee")
        c.setFont("Helvetica", 12)
        y = 760
        for label, value in [
            ("Batch ID", d["batch_id"]),
            ("Tanggal Produksi", d["tanggal"]),
            ("PIC", d["pic"]),
            ("Tempat Produksi", d["tempat_produksi"]),
            ("Varian", d["varian_produksi"]),
            ("Lokasi Gudang", d["lokasi_gudang"]),
            ("Tanggal Kedaluwarsa", d["expired_date"])
        ]:
            c.drawString(100, y, f"{label}: {value}")
            y -= 20
        qr_path = f"qr_codes/{batch_id}.png"
        if os.path.exists(qr_path):
            c.drawImage(qr_path, 100, y - 180, width=150, height=150)
    c.save()
    buffer.seek(0)
    return buffer


# ========= SIDEBAR =========
st.sidebar.image("logo_harlur.png", width=130)
st.sidebar.markdown("### Harlur Coffee Traceability")
menu = st.sidebar.radio("Navigasi", ["Tambah Data", "Lihat Data", "Edit Data", "Hapus Data", "Scan QR Realtime", "Consumer View"])

# ========= CSS Table =========
st.markdown("""
<style>
table {
    width: 100%;
    border-collapse: collapse;
}
th {
    text-align: left !important;
    background-color: #f5f5f5;
    padding: 8px !important;
}
td {
    padding: 6px !important;
}
</style>
""", unsafe_allow_html=True)

# ========= TAMBAH DATA =========
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
                st.success("Data berhasil disimpan.")
                st.image(qr_path, caption=f"QR Code Batch {batch_id}", width=200)
                st.markdown(f"[Lihat Consumer View]({link})")
            else:
                st.warning("Harap isi semua kolom.")

# ========= LIHAT DATA =========
elif menu == "Lihat Data":
    st.subheader("📋 Daftar Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi", conn)
    if not df.empty:
        search = st.text_input("🔍 Cari Batch ID / Varian:", "")
        if search:
            df = df[df.apply(lambda row: search.lower() in str(row["batch_id"]).lower() or search.lower() in str(row["varian_produksi"]).lower(), axis=1)]
        df["QR_Code_Path"] = df["batch_id"].apply(lambda x: f"qr_codes/{x}.png")
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
        st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)
        selected_batch = st.selectbox("📄 Unduh Sertifikat QR untuk Batch:", df["batch_id"])
        if st.button("Download PDF"):
            pdf_data = generate_pdf(selected_batch)
            st.download_button("⬇️ Download PDF", pdf_data, file_name=f"QR_{selected_batch}.pdf", mime="application/pdf")
    else:
        st.info("Belum ada data produksi tersimpan.")

# ========= EDIT DATA =========
elif menu == "Edit Data":
    st.subheader("✏️ Edit Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi", conn)
    if not df.empty:
        batch_list = df["batch_id"].tolist()
        selected_batch = st.selectbox("Pilih Batch ID", batch_list)
        data = get_batch_info(selected_batch)
        if data is not None:
            info = data.iloc[0]
            tempat = st.text_input("Tempat Produksi", info["tempat_produksi"])
            varian = st.text_input("Varian Produksi", info["varian_produksi"])
            lokasi_gudang = st.text_input("Lokasi Gudang", info["lokasi_gudang"])
            expired_date = st.date_input("Tanggal Kedaluwarsa", datetime.strptime(info["expired_date"], "%Y-%m-%d"))
            if st.button("Simpan Perubahan"):
                update_data(selected_batch, tempat, varian, lokasi_gudang, str(expired_date))
                st.success("✅ Data berhasil diperbarui!")
    else:
        st.info("Belum ada data untuk diedit.")

# ========= HAPUS DATA =========
elif menu == "Hapus Data":
    st.subheader("🗑️ Hapus Data Produksi")
    df = pd.read_sql_query("SELECT * FROM produksi", conn)
    if not df.empty:
        selected_batch = st.selectbox("Pilih Batch ID untuk Dihapus", df["batch_id"].tolist())
        if st.button("Hapus Data Ini"):
            delete_data(selected_batch)
            st.success(f"Data batch {selected_batch} berhasil dihapus!")
    else:
        st.info("Belum ada data untuk dihapus.")

# ========= CONSUMER VIEW =========
elif menu == "Consumer View":
    st.title("Informasi Produk Harlur Coffee")
    query_params = dict(st.query_params)
    batch_id = query_params.get("batch_id")
    if isinstance(batch_id, list):
        batch_id = batch_id[0]
    if batch_id:
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
