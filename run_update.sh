#!/bin/bash
# ======================================================
# HARLUR COFFEE STREAMLIT AUTO DEPLOY SCRIPT
# ======================================================

echo "🔄 Menyiapkan auto-deploy ke Streamlit Cloud..."

# Pastikan semua file tersimpan
git add .

# Pesan commit dengan tanggal otomatis
msg="Auto update $(date '+%Y-%m-%d %H:%M:%S')"
git commit -m "$msg"

# Tarik dulu update remote agar tidak konflik
git pull --rebase origin main

# Push perubahan
git push origin main

echo "✅ Berhasil di-push ke GitHub!"
echo "⏳ Tunggu beberapa menit, Streamlit Cloud akan rebuild otomatis."
