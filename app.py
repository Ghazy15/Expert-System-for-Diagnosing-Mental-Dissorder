import json
import os
from flask import Flask, render_template, request

app = Flask(__name__)

# Load file JSON (knowledge, rules, user_response)
base_dir = os.path.dirname(__file__)

def load_json_prefer(paths):
    for p in paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("Tidak ditemukan file JSON pada: " + ", ".join(paths))

try:
    kb = load_json_prefer([os.path.join(base_dir, "knowledge_base.json")])
except FileNotFoundError:
    print("ERROR: File 'knowledge_base.json' tidak ditemukan.")
    kb = {}

try:
    rules = load_json_prefer([os.path.join(base_dir, "rules.json")])
except FileNotFoundError:
    print("ERROR: File 'rules.json' tidak ditemukan.")
    rules = []

try:
    user_response = load_json_prefer([os.path.join(base_dir, "user_response.json")])
except FileNotFoundError:
    print("ERROR: File 'user_response.json' tidak ditemukan.")
    user_response = []


#
def cf_combine(cf1, cf2):

    if cf1 >= 0 and cf2 >= 0:
        return cf1 + cf2 * (1 - cf1)
    return cf1 + cf2 * (1 - cf1)


# inference engine
def run_inference(user_facts):
    # menyimpan semua fakta baru
    hypotheses = {}

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

        inference_log.append(
            f"--- Memeriksa Aturan {rule['id']}: IF ({' AND '.join(antecedents)}) THEN {consequent} ---")

        # Periksa apakah semua fakta untuk aturan ini ada di input user
        can_fire = True
        min_cf_evidence = 1.0

        antecedent_facts_cf = []

        for fact in antecedents:
            if fact not in user_facts:
                can_fire = False
                inference_log.append(f"-> GAGAL: Fakta {fact} ({kb.get(fact, fact)}) tidak ada di input pengguna.")
                break  # Hentikan pengecekan untuk aturan ini

            # Kumpulkan CF untuk log
            antecedent_facts_cf.append(f"{fact}(CF={user_facts[fact]})")
            min_cf_evidence = min(min_cf_evidence, user_facts[fact])

        if can_fire:
            inference_log.append(f"-> SUKSES: Semua fakta prasyarat terpenuhi: ({', '.join(antecedent_facts_cf)})")
            inference_log.append(f"   -> Mencari CF minimal dari fakta: Min({min_cf_evidence:.3f})")

            cf_new = min_cf_evidence * cf_rule
            inference_log.append(
                f"   -> Menghitung CF baru: CF_baru = CF_min * CF_aturan = {min_cf_evidence:.3f} * {cf_rule} = {cf_new:.3f}")

            cf_old = hypotheses.get(consequent, 0.0)

            if cf_old > 0:
                # Kombinasikan jika hipotesis ini sudah ada
                hypotheses[consequent] = cf_combine(cf_old, cf_new)
                inference_log.append(
                    f"   -> Menggabungkan CF untuk {consequent}: CF_combine(CF_lama={cf_old:.3f}, CF_baru={cf_new:.3f}) = {hypotheses[consequent]:.3f}")
            else:
                # Tetapkan sebagai fakta baru
                hypotheses[consequent] = cf_new
                inference_log.append(f"   -> Menetapkan CF baru untuk {consequent} = {hypotheses[consequent]:.3f}")

    inference_log.append("--- PROSES INFERENSI SELESAI ---")

    # Filter hanya untuk diagnosis akhir
    diagnoses = {code: cf for code, cf in hypotheses.items() if code.startswith('M')}

    # Urutkan diagnosa akhir berdasarkan nilai CF tertinggi
    sorted_diagnoses = sorted(diagnoses.items(), key=lambda item: item[1], reverse=True)

    # Urutkan SEMUA fakta baru untuk ditampilkan
    sorted_all_facts = sorted(hypotheses.items(), key=lambda item: item[1], reverse=True)

    # Kembalikan diagnosa akhir, semua fakta baru, DAN log inferensi
    return sorted_diagnoses, sorted_all_facts, inference_log


# Menampilkan halaman utama dengan daftar gejala
@app.route('/')
def index():
    # Ambil hanya gejaladari knowledge base
    symptoms = {code: desc for code, desc in kb.items() if code.startswith('G')}

    cf_options = []
    if isinstance(user_response, list):
        for item in user_response:
            label = item.get("state", f"CF={item.get('user_cf', '?')}")
            cf_val = float(item.get("user_cf", 0.0))
            cf_options.append({"label": label, "value": cf_val})
    else:
        cf_options = [{"label": "Tidak ada data user_response.json", "value": 0.0}]

    return render_template('index.html', symptoms=symptoms, cf_options=cf_options)

# Memproses form dan menampilkan hasil diagnosa.
@app.route('/diagnose', methods=['POST'])
def diagnose():
    user_facts = {}
    user_inputs_display = {}

    # Kumpulkan fakta dari form
    for code, value in request.form.items():
        cf_value = float(value)
        if cf_value > 0:
            user_facts[code] = cf_value
            user_inputs_display[kb.get(code, code)] = cf_value

    # Jalankan mesin inferensi dan dapatkan list
    sorted_diagnoses, sorted_all_facts, inference_log = run_inference(user_facts)

    # Siapkan hasil untuk ditampilkan (Diagnosa Akhir - MXXX)
    display_results = []
    for code, cf in sorted_diagnoses:
        display_results.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_percent": round(cf * 100, 2)
        })

    # Siapkan daftar semua fakta baru
    display_all_facts_list = []
    for code, cf in sorted_all_facts:
        display_all_facts_list.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_value": cf
        })

    top_diagnosis = display_results[0] if display_results else None

    cf_map = {}
    if isinstance(user_response, list):
        for item in user_response:
            try:
                key = str(float(item.get("user_cf", 0.0)))
            except Exception:
                key = str(item.get("user_cf"))
            cf_map[key] = item.get("state", str(item.get("user_cf")))

    high_threshold = 0.8
    mid_threshold = 0.6

    return render_template(
        'result.html',
        results=display_results,
        top_diagnosis=top_diagnosis,
        inputs=user_inputs_display,
        all_new_facts=display_all_facts_list,
        inference_log=inference_log,
        cf_map=cf_map,
        high_thresh=high_threshold,
        mid_thresh=mid_threshold
    )


if __name__ == '__main__':
    app.run(debug=True)
