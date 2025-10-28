import json
import os
from flask import Flask, render_template, request

app = Flask(__name__)

# --- Muat Basis Pengetahuan dan Aturan ---
# Menggunakan metode loading yang aman untuk Flask
try:
    with open('knowledge_base.json', 'r', encoding='utf-8') as f:
        kb = json.load(f)
except FileNotFoundError:
    print("ERROR: File 'knowledge_base.json' tidak ditemukan.")
    kb = {}

try:
    with open('rules.json', 'r', encoding='utf-8') as f:
        rules = json.load(f)
except FileNotFoundError:
    print("ERROR: File 'rules.json' tidak ditemukan.")
    rules = []

try:
    # Memuat user_response.json (file baru Anda) untuk dropdown CF
    with open('user_response.json', 'r', encoding='utf-8') as f:
        user_response = json.load(f)
except FileNotFoundError:
    print("ERROR: File 'user_response.json' tidak ditemukan. Menggunakan fallback.")
    user_response = [
        {"state": "Kemungkinan Kecil", "user_cf": 0.5},
        {"state": "Mungkin", "user_cf": 0.6},
        {"state": "Kemungkinan Besar", "user_cf": 0.7},
        {"state": "Hampir Pasti", "user_cf": 0.8},
        {"state": "Pasti", "user_cf": 1.0}
    ]


# --- ======================================================= ---
# --- KODE KELAS INFERENSI BARU ANDA (TELAH DIINTEGRASIKAN) ---
# --- ======================================================= ---
class SequentialForwardChaining:
    # (Perbaikan: _init_ -> __init__)
    def __init__(self, rules, default_operator="AND", max_iter=100):
        self.rules = rules
        self.default_operator = default_operator.upper()
        self.max_iter = max_iter
        self.trace_log = []

    def infer(self, user_facts):
        facts_meta = {}
        for code, cf in user_facts.items():
            facts_meta[code] = {"cf": float(cf), "source": "user", "gen": 0}

        changed = True
        iteration = 0
        while changed and iteration < self.max_iter:
            iteration += 1
            changed = False
            # Snapshot MENGGUNAKAN fakta dari iterasi SEBELUMNYA
            snapshot = {k: v.copy() for k, v in facts_meta.items()}
            new_meta = {} # Fakta baru yang ditemukan di iterasi INI

            for rule in self.rules:
                antecedents = rule.get("if") or rule.get("antecedent") or []
                consequent = rule.get("then") or rule.get("consequent")
                if not consequent or not antecedents:
                    continue

                operator = (rule.get("operator") or self.default_operator).upper()
                rule_cf = float(rule.get("cf", 1.0))

                # Pastikan semua antecedent sudah ada di fakta (snapshot)
                if not all(a in snapshot for a in antecedents):
                    continue # Lewati aturan ini jika premis tidak lengkap

                # --- INI ADALAH LOGIKA KUNCI ANDA ---
                eff_cfs = []
                for a in antecedents:
                    meta = snapshot[a]
                    # Jika antecedent hasil dari rule sebelumnya DAN user juga beri CF,
                    # lakukan perkalian sekuensial
                    if meta["source"] == "rule" and a in user_facts:
                         # Logika: CF_derived * CF_user
                        eff = meta["cf"] * user_facts[a]
                    else:
                        # Jika hanya fakta user, atau fakta turunan murni
                        eff = meta["cf"]
                    eff_cfs.append(eff)
                # --- AKHIR LOGIKA KUNCI ---

                cf_premis = min(eff_cfs) if operator == "AND" else max(eff_cfs)
                cf_conclusion = cf_premis * rule_cf

                # Logika Paralel: Ambil CF tertinggi jika >1 aturan menghasilkan kesimpulan yg sama
                prev = new_meta.get(consequent)
                if (prev is None) or (cf_conclusion > prev["cf"]):
                    new_meta[consequent] = {
                        "cf": round(cf_conclusion, 6),
                        "source": "rule",
                        "gen": iteration, # Tandai dari iterasi ke berapa
                    }

                # Tambahkan ke log pelacakan (trace_log)
                self.trace_log.append({
                    "iteration": iteration,
                    "rule_id": rule.get("id"),
                    "antecedents": antecedents,
                    "antecedent_eff_cfs": eff_cfs,
                    "cf_premis": cf_premis,
                    "rule_cf": rule_cf,
                    "consequent": consequent,
                    "cf_conclusion": cf_conclusion,
                })

            # Merge hasil baru dari iterasi ini ke fakta utama
            for cons, meta in new_meta.items():
                old = facts_meta.get(cons)
                # Jika fakta ini benar-benar baru, atau nilainya berubah
                if (old is None) or (abs(meta["cf"] - old["cf"]) > 1e-9):
                    facts_meta[cons] = meta
                    changed = True # Tandai untuk lanjut ke iterasi berikutnya

        # hasil akhir (hanya fakta turunan yang nilainya beda dari input user)
        final_derived_facts = {
            k: round(v["cf"], 6)
            for k, v in facts_meta.items()
            if v["source"] == "rule" and abs(v["cf"] - user_facts.get(k, -1)) > 1e-9
        }
        return final_derived_facts

# --- ======================================================= ---
# --- FUNGSI HELPER UNTUK FORMAT LOG (BARU) ---
# --- ======================================================= ---

def format_inference_log(raw_log, user_facts, kb):
    """
    Mengubah trace_log (list of dicts) dari class
    menjadi list of strings yang bisa dibaca oleh result.html
    """
    log_strings = []
    log_strings.append("--- FAKTA AWAL (dari Pengguna) ---")
    if not user_facts:
        log_strings.append("Tidak ada fakta yang diberikan pengguna.")
    for fact, cf in user_facts.items():
        log_strings.append(f"FAKTA: {kb.get(fact, fact)} ({fact}) dengan CF = {cf:.3f}")
    
    log_strings.append("\n--- MEMULAI PROSES INFERENSI (FORWARD CHAINING) ---")
    log_strings.append("--- Logika Premis: CF_eff = (CF_derived * CF_user) atau CF_saja ---")

    current_iter = 0
    if not raw_log:
        log_strings.append("\nTidak ada aturan yang dieksekusi.")
        
    for entry in raw_log:
        if entry['iteration'] != current_iter:
            # Jika ini pass baru, tambahkan header
            current_iter = entry['iteration']
            log_strings.append(f"\n--- PASS {current_iter} ---")
        
        # Log pengecekan aturan
        rule_id = entry['rule_id']
        consequent = entry['consequent']
        log_strings.append(f"--- Memeriksa Aturan {rule_id}: IF ({' AND '.join(entry['antecedents'])}) THEN {consequent} ---")
        
        # Log premis
        for i, ante in enumerate(entry['antecedents']):
            log_strings.append(f"   -> Premis {ante}: CF efektif dihitung = {entry['antecedent_eff_cfs'][i]:.3f}")
        
        # Log kesimpulan
        log_strings.append(f"-> SUKSES: Aturan {rule_id} AKTIF.")
        log_strings.append(f"   -> CF_premis (Min) = {entry['cf_premis']:.3f}")
        log_strings.append(f"   -> CF_aturan = {entry['rule_cf']:.3f}")
        log_strings.append(f"   -> CF_baru_dihitung = {entry['cf_conclusion']:.3f}")
        log_strings.append(f"   -> (Mencoba memperbarui {consequent} dengan CF = {entry['cf_conclusion']:.3f})")

    if current_iter > 0:
        log_strings.append(f"\n--- PASS {current_iter + 1} ---")
        log_strings.append("Tidak ada aturan baru yang dapat diaktifkan. Proses inferensi selesai.")
        
    return log_strings

# --- ======================================================= ---
# --- RUTE APLIKASI WEB FLASK (TELAH DIMODIFIKASI) ---
# --- ======================================================= ---

@app.route('/')
def index():
    """Menampilkan halaman utama dengan daftar gejala."""
    
    # Ambil hanya gejala (GXXX) dari knowledge base
    symptoms = {code: desc for code, desc in kb.items() if code.startswith('G')}
    
    # --- PERUBAHAN ---
    # Gunakan 'user_response.json' untuk opsi CF
    cf_options = []
    for item in user_response:
        cf_options.append({
            "label": f"{item['state']} ({item['user_cf']})",
            "value": float(item['user_cf'])
        })
    # Pastikan opsi 0.0 ada di paling atas
    if not any(opt['value'] == 0.0 for opt in cf_options):
         cf_options.insert(0, {"label": "Tidak yakin / Tidak ada (0.0)", "value": 0.0})
    
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

    # --- PERUBAHAN: MENGGUNAKAN MESIN INFERENSI BARU ---
    
    # 1. Inisialisasi engine dengan aturan
    engine = SequentialForwardChaining(rules)
    
    # 2. Jalankan inferensi
    derived_facts_map = engine.infer(user_facts)
    
    # 3. Ambil log mentah (list of dicts)
    raw_inference_log = engine.trace_log
    
    # 4. Format log agar bisa dibaca template
    inference_log_strings = format_inference_log(raw_inference_log, user_facts, kb)
    
    # --- AKHIR PERUBAHAN ---

    # Siapkan hasil untuk ditampilkan
    
    # 1. Siapkan daftar SEMUA FAKTA BARU (GXXX dan MXXX)
    sorted_all_facts = sorted(derived_facts_map.items(), key=lambda item: item[1], reverse=True)
    display_all_facts_list = []
    for code, cf in sorted_all_facts:
        display_all_facts_list.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_value": cf
        })

    # 2. Siapkan daftar Diagnosa Akhir (hanya MXXX)
    diagnoses = {
        code: cf for code, cf in derived_facts_map.items() 
        if code.startswith('M')
    }
    sorted_diagnoses = sorted(diagnoses.items(), key=lambda item: item[1], reverse=True)
    display_results = []
    for code, cf in sorted_diagnoses:
        display_results.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_percent": round(cf * 100, 2)
        })
        
    # 3. Dapatkan diagnosa teratas
    top_diagnosis = display_results[0] if display_results else None

    return render_template(
        'result.html', 
        results=display_results,
        top_diagnosis=top_diagnosis,
        inputs=user_inputs_display,
        all_new_facts=display_all_facts_list,
        inference_log=inference_log_strings  # Kirim log yang sudah diformat
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)