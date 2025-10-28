import json
from flask import Flask, render_template, request

app = Flask(__name__)

# --- Muat Basis Pengetahuan dan Aturan ---
try:
    with open('knowledge_base.json', 'r') as f:
        kb = json.load(f)
except FileNotFoundError:
    print("ERROR: File 'knowledge_base.json' tidak ditemukan.")
    kb = {}

try:
    with open('rules.json', 'r') as f:
        rules = json.load(f)
except FileNotFoundError:
    print("ERROR: File 'rules.json' tidak ditemukan.")
    rules = []

# --- Fungsi Helper untuk Certainty Factor ---
def cf_combine(cf1, cf2):
    """
    Menggabungkan dua Certainty Factor (hanya untuk nilai positif
    sesuai contoh di jurnal).
    """
    if cf1 >= 0 and cf2 >= 0:
        return cf1 + cf2 * (1 - cf1)
    # Tambahkan logika lain jika ada CF negatif, 
    # tapi jurnal ini hanya menggunakan CF positif.
    return cf1 + cf2 * (1 - cf1)

# --- Logika Mesin Inferensi ---
def run_inference(user_facts):
    """
    Menjalankan mesin inferensi berdasarkan fakta dari pengguna.
    Ini adalah implementasi single-pass non-chaining
    sesuai perhitungan di jurnal.
    """
    # 'hypotheses' akan menyimpan SEMUA fakta baru (Gxxx dan Mxxx)
    hypotheses = {}
    
    # === PERUBAHAN DIMULAI: Menambahkan list untuk log ===
    inference_log = []
    
    # Tambahkan fakta awal dari pengguna ke log
    inference_log.append("--- FAKTA AWAL (dari Pengguna) ---")
    if not user_facts:
        inference_log.append("Tidak ada fakta yang diberikan pengguna.")
    for fact, cf in user_facts.items():
        inference_log.append(f"FAKTA: {kb.get(fact, fact)} ({fact}) dengan CF = {cf}")
    
    inference_log.append("--- MEMULAI PROSES INFERENSI ---")
    
    for rule in rules:
        antecedents = rule['if']
        consequent = rule['then']
        cf_rule = rule['cf']

        inference_log.append(f"--- Memeriksa Aturan {rule['id']}: IF ({' AND '.join(antecedents)}) THEN {consequent} ---")

        # Periksa apakah semua fakta untuk aturan ini ada di input user
        can_fire = True
        min_cf_evidence = 1.0
        
        antecedent_facts_cf = [] # Untuk log
        
        for fact in antecedents:
            if fact not in user_facts:
                can_fire = False
                inference_log.append(f"-> GAGAL: Fakta {fact} ({kb.get(fact, fact)}) tidak ada di input pengguna.")
                break # Hentikan pengecekan untuk aturan ini
            
            # Kumpulkan CF untuk log
            antecedent_facts_cf.append(f"{fact}(CF={user_facts[fact]})")
            min_cf_evidence = min(min_cf_evidence, user_facts[fact])

        # Jika aturan bisa aktif, hitung CF
        if can_fire:
            inference_log.append(f"-> SUKSES: Semua fakta prasyarat terpenuhi: ({', '.join(antecedent_facts_cf)})")
            inference_log.append(f"   -> Mencari CF minimal dari fakta: Min({min_cf_evidence:.3f})")
            
            cf_new = min_cf_evidence * cf_rule
            inference_log.append(f"   -> Menghitung CF baru: CF_baru = CF_min * CF_aturan = {min_cf_evidence:.3f} * {cf_rule} = {cf_new:.3f}")
            
            cf_old = hypotheses.get(consequent, 0.0)
            
            if cf_old > 0:
                # Kombinasikan jika hipotesis ini sudah ada
                hypotheses[consequent] = cf_combine(cf_old, cf_new)
                inference_log.append(f"   -> Menggabungkan CF untuk {consequent}: CF_combine(CF_lama={cf_old:.3f}, CF_baru={cf_new:.3f}) = {hypotheses[consequent]:.3f}")
            else:
                # Tetapkan sebagai fakta baru
                hypotheses[consequent] = cf_new
                inference_log.append(f"   -> Menetapkan CF baru untuk {consequent} = {hypotheses[consequent]:.3f}")
    
    inference_log.append("--- PROSES INFERENSI SELESAI ---")
    # === PERUBAHAN SELESAI ===

    # Filter hanya untuk diagnosis akhir (MXXX)
    diagnoses = {code: cf for code, cf in hypotheses.items() if code.startswith('M')}
    
    # Urutkan diagnosa akhir berdasarkan nilai CF tertinggi
    sorted_diagnoses = sorted(diagnoses.items(), key=lambda item: item[1], reverse=True)
    
    # Urutkan SEMUA fakta baru (Gxxx dan Mxxx) untuk ditampilkan
    sorted_all_facts = sorted(hypotheses.items(), key=lambda item: item[1], reverse=True)

    # Kembalikan diagnosa akhir, semua fakta baru, DAN log inferensi
    return sorted_diagnoses, sorted_all_facts, inference_log


# --- Rute Aplikasi Web ---

@app.route('/')
def index():
    """Menampilkan halaman utama dengan daftar gejala."""
    
    # Ambil hanya gejala (GXXX) dari knowledge base
    symptoms = {code: desc for code, desc in kb.items() if code.startswith('G')}
    
    # Opsi CF berdasarkan Tabel 3 di jurnal
    cf_options = [
        {"label": "Tidak yakin / Tidak ada", "value": 0.0},
        {"label": "Kemungkinan kecil (0.5)", "value": 0.5},
        {"label": "Mungkin (0.6)", "value": 0.6},
        {"label": "Kemungkinan besar (0.7)", "value": 0.7},
        {"label": "Hampir pasti (0.8)", "value": 0.8},
        {"label": "Pasti (1.0)", "value": 1.0}
    ]
    
    return render_template('index.html', symptoms=symptoms, cf_options=cf_options)

@app.route('/diagnose', methods=['POST'])
def diagnose():
    """Memproses form dan menampilkan hasil diagnosa."""
    
    user_facts = {}
    user_inputs_display = {}
    
    # Kumpulkan fakta dari form
    for code, value in request.form.items():
        cf_value = float(value)
        if cf_value > 0:
            user_facts[code] = cf_value
            user_inputs_display[kb.get(code, code)] = cf_value

    # === PERUBAHAN DIMULAI ===
    # Jalankan mesin inferensi dan dapatkan ketiga list
    sorted_diagnoses, sorted_all_facts, inference_log = run_inference(user_facts)
    
    # Siapkan hasil untuk ditampilkan (Diagnosa Akhir - MXXX)
    display_results = []
    for code, cf in sorted_diagnoses:
        display_results.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_percent": round(cf * 100, 2)
        })
        
    # Siapkan daftar SEMUA FAKTA BARU (GXXX dan MXXX)
    display_all_facts_list = []
    for code, cf in sorted_all_facts:
        display_all_facts_list.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_value": cf  # Kita kirim nilai CF mentah (misal 0.455)
        })
    
    top_diagnosis = display_results[0] if display_results else None

    return render_template(
        'result.html', 
        results=display_results,
        top_diagnosis=top_diagnosis,
        inputs=user_inputs_display,
        all_new_facts=display_all_facts_list,
        inference_log=inference_log  # Kirim list log baru ke template
    )
    # === PERUBAHAN SELESAI ===

if __name__ == '__main__':
    app.run(debug=True)
