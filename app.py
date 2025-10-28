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
# Fungsi ini tetap sama, sesuai dengan PDF baru (slide 24)
def cf_combine(cf1, cf2):
    """
    Menggabungkan dua Certainty Factor (hanya untuk nilai positif
    sesuai contoh di jurnal).
    """
    if cf1 >= 0 and cf2 >= 0:
        return cf1 + cf2 * (1 - cf1)
    # Logika untuk CF negatif (jika ada)
    elif cf1 < 0 and cf2 < 0:
        return cf1 + cf2 * (1 + cf1)
    else:
        return (cf1 + cf2) / (1 - min(abs(cf1), abs(cf2)))

# --- (LOGIKA BARU) Mesin Inferensi Forward-Chaining ---
def run_inference(user_facts):
    """
    Menjalankan mesin inferensi forward-chaining (iteratif)
    berdasarkan logika dari PDF "M5 Ketidakpastian .pdf".
    
    Akan berulang sampai tidak ada fakta baru yang ditemukan.
    """
    
    # 'facts' adalah memori kerja (working memory) kita.
    # Dimulai dengan fakta dari pengguna.
    facts = user_facts.copy()
    
    inference_log = []
    
    # Catat fakta awal
    inference_log.append("--- FAKTA AWAL (dari Pengguna) ---")
    if not facts:
        inference_log.append("Tidak ada fakta yang diberikan pengguna.")
    for fact, cf in facts.items():
        inference_log.append(f"FAKTA: {kb.get(fact, fact)} ({fact}) dengan CF = {cf:.3f}")

    iteration_count = 0
    
    # --- Loop Iterasi Utama ---
    # Terus berulang selama ada fakta baru yang ditemukan
    while True:
        iteration_count += 1
        new_fact_found_this_iteration = False
        inference_log.append(f"--- MEMULAI ITERASI ke-{iteration_count} ---")
        
        # Periksa setiap aturan dalam basis pengetahuan
        for rule in rules:
            antecedents = rule['if']
            consequent = rule['then']
            cf_rule = rule['cf']
            
            log_prefix = f"--- Memeriksa Aturan {rule['id']}: IF ({' AND '.join(antecedents)}) THEN {consequent} ---"

            # 1. Periksa apakah SEMUA anteseden (premis) ada di 'facts'
            can_fire = True
            min_cf_evidence = 1.0
            antecedent_facts_cf_log = [] # Untuk log

            for fact in antecedents:
                if fact not in facts:
                    can_fire = False
                    # Tidak perlu log di sini, akan terlalu ramai.
                    # Cukup log saat aturan GAGAL jika diperlukan.
                    break # Hentikan pengecekan premis untuk aturan ini
                
                # Kumpulkan CF untuk log dan perhitungan Min
                antecedent_facts_cf_log.append(f"{fact}(CF={facts[fact]:.3f})")
                min_cf_evidence = min(min_cf_evidence, facts[fact])

            # 2. Jika aturan GAGAL (premis tidak lengkap)
            if not can_fire:
                # Opsi: tambahkan log jika ingin lihat aturan yg gagal
                # inference_log.append(f"{log_prefix} -> GAGAL: Premis tidak lengkap.")
                continue # Lanjut ke aturan berikutnya
            
            # 3. Jika aturan SUKSES (bisa aktif)
            inference_log.append(log_prefix)
            inference_log.append(f"-> SUKSES: Semua fakta prasyarat terpenuhi: ({', '.join(antecedent_facts_cf_log)})")
            
            # Logika 'AND' (premis majemuk) - Slide 33
            inference_log.append(f"   -> Mencari CF minimal (logika 'AND'): Min = {min_cf_evidence:.3f}")
            
            # Hitung CF bukti baru
            cf_new_evidence = min_cf_evidence * cf_rule
            inference_log.append(f"   -> Menghitung CF baru: CF_baru = CF_min * CF_aturan = {min_cf_evidence:.3f} * {cf_rule} = {cf_new_evidence:.3f}")

            # 4. Perbarui 'facts' (memori kerja)
            cf_old = facts.get(consequent, 0.0)
            
            if cf_old == 0.0:
                # Ini adalah fakta yang benar-benar baru
                facts[consequent] = cf_new_evidence
                new_fact_found_this_iteration = True
                inference_log.append(f"   -> FAKTA BARU: Menetapkan CF untuk {consequent} = {facts[consequent]:.3f}")
            else:
                # Fakta ini sudah ada, gunakan 'Rule Parallel' (Slide 24)
                cf_combined = cf_combine(cf_old, cf_new_evidence)
                inference_log.append(f"   -> Menggabungkan CF (Rule Paralel) untuk {consequent}: CF_combine(CF_lama={cf_old:.3f}, CF_baru={cf_new_evidence:.3f}) = {cf_combined:.3f}")
                
                # Cek apakah nilainya benar-benar berubah (menghindari loop tak terbatas)
                if abs(cf_combined - cf_old) > 0.0001:
                    facts[consequent] = cf_combined
                    new_fact_found_this_iteration = True
                    inference_log.append(f"   -> CF Diperbarui untuk {consequent} = {cf_combined:.3f}")
                else:
                    inference_log.append(f"   -> CF {consequent} tidak berubah.")

        # --- Akhir dari satu iterasi ---
        inference_log.append(f"--- Iterasi ke-{iteration_count} selesai. ---")

        if not new_fact_found_this_iteration:
            # Jika tidak ada fakta baru di seluruh iterasi ini, hentikan loop
            inference_log.append("--- PROSES INFERENSI SELESAI (Tidak ada fakta baru ditemukan) ---")
            break # Keluar dari 'while True'

    # --- Persiapan Hasil ---
    
    # 1. 'all_new_facts' adalah semua fakta di 'facts' KECUALI fakta awal dari user
    hypotheses = {code: cf for code, cf in facts.items() if code not in user_facts}
    sorted_all_facts = sorted(hypotheses.items(), key=lambda item: item[1], reverse=True)
    
    # 2. 'diagnoses' adalah fakta baru yang merupakan diagnosa (MXXX)
    diagnoses = {code: cf for code, cf in hypotheses.items() if code.startswith('M')}
    sorted_diagnoses = sorted(diagnoses.items(), key=lambda item: item[1], reverse=True)

    return sorted_diagnoses, sorted_all_facts, inference_log

# --- Rute Aplikasi Web (TIDAK BERUBAH) ---

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

    # Jalankan mesin inferensi (sekarang menggunakan logika baru)
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

    # Kirim semua data ke template yang sama
    return render_template(
        'result.html', 
        results=display_results,
        top_diagnosis=top_diagnosis,
        inputs=user_inputs_display,
        all_new_facts=display_all_facts_list,
        inference_log=inference_log
    )

if __name__ == '__main__':
    # Jika menggunakan 'python app.py', ini akan berjalan
    app.run(debug=True)
