# 1. Gunakan base image Python yang slim (ringan)
FROM python:3.10-slim-buster

# 2. Tetapkan direktori kerja di dalam container
WORKDIR /app

# 3. Salin file dependensi terlebih dahulu (untuk caching)
COPY requirements.txt requirements.txt

# 4. Install dependensi
RUN pip install --upgrade pip && \
    pip install -r requirements.txt --no-cache-dir

# 5. Salin semua sisa file proyek ke dalam direktori /app
COPY . .

# 6. Perintah untuk menjalankan aplikasi saat container dimulai
# Kita gunakan Gunicorn untuk menjalankan app.py, dengan 'app' sebagai nama variabel Flask
# Bind ke 0.0.0.0:5000 agar bisa diakses dari luar container
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]