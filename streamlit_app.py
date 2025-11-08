import streamlit as st
import sqlite3
import qrcode
from PIL import Image
import os
import pandas as pd
import base64
from datetime import datetime
import cv2
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
    varian_produksi TEXT
)
""")
conn.commit()

# ========== FUNCTIONS ==========
def tambah_data(batch_id, tanggal, pic, tempat, varian):
    cursor.execute("""
        INSERT INTO produksi (batch_id, tanggal, pic, tempat_produksi, varian_produksi)
        VALUES (?, ?, ?, ?, ?)
    """, (batch_id, tanggal, pic, tempat, varian))
    conn.commit()

    # Generate QR code (link to consumer view)
    link = f"https://harlur-traceability.streamlit.app/?batch_id={batch_id}"
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img_qr = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Optional logo in center
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

# ========== AUTO ROUTE HANDLER ==========
query_params = st.query_params
if "batch_id" in query_params:
    # Jika ada batch_id di URL, langsung buka halaman Consumer View
    st.session_state["menu_override"] = "Consumer View"
    st.session_state["batch_id_param"] = query_params["batch_id"]
else:
    st.session_state["menu_override"] = None

# ========== SIDEBAR ==========
st.sidebar.image("logo_harlur.png", width=130)
st.sidebar.markdown("### Harlur Coffee Traceability")

default_menu = st.session_state.get("menu_override", None)
menu_list = ["Tambah Data", "Lihat Data", "Scan QR Realtime", "Consumer View"]
menu = st.sidebar.radio(
    "Navigasi",
    menu_list,
    index=menu_list.index(default_menu) if default_menu else 0
)

# ========== TAMBAH DATA ==========
if menu == "Tambah Data":
    st.title("Tambah Data Produksi")

    with st.form("form_produksi"):
        col1, col2 = st.columns(2)
        with col1:
            batch_id = st.text_input("Batch ID")
            tanggal = st.date_input("Tanggal Produksi", datetime.now())
            pic = st.text_input("Nama PIC")
        with col2:
            tempat = st.text_input("Tempat Produksi")
            varian = st.text_input("Varian Produksi")

        submitted = st.form_submit_button("Simpan Data dan Buat QR Code")

        if submitted:
            if all([batch_id, tanggal, pic, tempat, varian]):
                qr_path, link = tambah_data(batch_id, str(tanggal), pic, tempat, varian)
                st.success("Data berhasil disimpan.")
                st.image(qr_path, caption=f"QR Code Batch {batch_id}", width=200)
                st.markdown(f"[Lihat Consumer View]({link})")
            else:
                st.warning("Harap isi semua kolom.")

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
                    return f'<img src="data:image/png;base64,{img_b64}" width="100">'
            else:
                return "❌ Tidak ditemukan"

        df["QR_Code"] = df["QR_Code_Path"].apply(make_img_tag)
        df_display = df[["batch_id", "tanggal", "pic", "tempat_produksi", "varian_produksi", "QR_Code"]]
        df_display.columns = ["Batch ID", "Tanggal", "PIC", "Tempat Produksi", "Varian Produksi", "QR Code"]

        st.markdown(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Belum ada data produksi tersimpan.")

# ========== QR SCANNER REALTIME ==========
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

    ctx = webrtc_streamer(
        key="scanner",
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=QRScanner,
        media_stream_constraints={"video": True, "audio": False},
        async_processing=True,
    )

    if ctx.video_processor and ctx.video_processor.qr_result:
        st.success(f"QR Code Terbaca: {ctx.video_processor.qr_result}")
        if "batch_id=" in ctx.video_processor.qr_result:
            batch_id = ctx.video_processor.qr_result.split("=")[-1]
            data = get_batch_info(batch_id)
            if data is not None:
                info = data.iloc[0]
                st.write("### Informasi Batch")
                st.json({
                    "Batch ID": info["batch_id"],
                    "Tanggal": info["tanggal"],
                    "Tempat Produksi": info["tempat_produksi"],
                    "Varian": info["varian_produksi"],
                    "PIC": info["pic"]
                })
            else:
                st.warning("Batch ID tidak ditemukan.")

# ========== CONSUMER VIEW ==========
elif menu == "Consumer View":
    st.title("Informasi Produk Harlur Coffee")

    query_params = st.query_params
    batch_id = query_params.get("batch_id") or st.session_state.get("batch_id_param")

    if batch_id:
        data = get_batch_info(batch_id)
        if data is not None:
            info = data.iloc[0]
            st.image("logo_harlur.png", width=150)
            st.subheader(f"Varian: {info['varian_produksi']}")
            st.write(f"Tanggal Produksi: {info['tanggal']}")
            st.write(f"Tempat Produksi: {info['tempat_produksi']}")
            st.write(f"PIC: {info['pic']}")
            st.markdown("---")
            st.info("Terima kasih telah memilih Harlur Coffee!")
        else:
            st.error("Data batch tidak ditemukan.")
    else:
        st.info("Scan QR Code dari kemasan untuk melihat informasi produk.")
