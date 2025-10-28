import json
import os
from collections import defaultdict
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

# Inference engine (optimized: dependency index + candidate rules)
class ForwardChaining:
    def __init__(self, rules, default_operator="AND", max_iter=100):
        self.rules = rules
        self.default_operator = default_operator.upper()
        self.max_iter = max_iter
        self.trace_log = []

        # Build antecedent -> rule indices map for fast lookup
        self.ante_to_rules = defaultdict(list)
        for idx, rule in enumerate(self.rules):
            antecedents = rule.get('if') or rule.get('antecedent') or []
            for a in antecedents:
                self.ante_to_rules[a].append(idx)

    def infer(self, user_facts):
        # facts_meta: code -> {'cf': float, 'source': 'user'|'rule', 'gen': int}
        facts_meta = {code: {'cf': float(cf), 'source': 'user', 'gen': 0} for code, cf in user_facts.items()}

        changed = True
        iteration = 0
        self.trace_log = []

        # initial set of facts that may trigger rules = user-provided facts
        new_facts = set(user_facts.keys())

        while new_facts and iteration < self.max_iter:
            iteration += 1
            snapshot = {k: v.copy() for k, v in facts_meta.items()}
            new_meta_candidates = {}
            candidate_rule_indices = set()

            # collect candidate rules affected by new_facts
            for f in new_facts:
                for ridx in self.ante_to_rules.get(f, []):
                    candidate_rule_indices.add(ridx)

            # clear new_facts for this iteration; will be filled with consequents that actually changed
            new_facts = set()

            # Evaluate only candidate rules (sorted for deterministic order)
            for ridx in sorted(candidate_rule_indices):
                rule = self.rules[ridx]
                antecedents = rule.get('if') or rule.get('antecedent') or []
                consequent = rule.get('then') or rule.get('consequent')
                if not consequent or not antecedents:
                    continue
                operator = (rule.get('operator') or self.default_operator).upper()
                rule_cf = float(rule.get('cf', 1.0))

                # ensure all antecedents are present in snapshot
                if not all(a in snapshot for a in antecedents):
                    continue

                # compute effective antecedent CFs (propagation if antecedent was rule-produced in earlier iter)
                eff_cfs = []
                for a in antecedents:
                    meta = snapshot[a]
                    if meta['source'] == 'rule' and meta['gen'] < iteration and a in user_facts:
                        eff = meta['cf'] * float(user_facts[a])
                    else:
                        eff = meta['cf']
                    eff_cfs.append(eff)

                cf_premis = min(eff_cfs) if operator == 'AND' else max(eff_cfs)
                cf_conclusion = cf_premis * rule_cf

                # keep the best candidate for this consequent in this iteration
                prev = new_meta_candidates.get(consequent)
                if (prev is None) or (cf_conclusion > prev['cf']):
                    new_meta_candidates[consequent] = {'cf': round(cf_conclusion, 6), 'source': 'rule', 'gen': iteration}

                # trace log (only for evaluated candidate rules)
                self.trace_log.append({
                    'iteration': iteration,
                    'rule_id': rule.get('id'),
                    'antecedents': antecedents,
                    'antecedent_eff_cfs': [round(x,6) for x in eff_cfs],
                    'cf_premis': round(cf_premis,6),
                    'rule_cf': rule_cf,
                    'consequent': consequent,
                    'cf_conclusion': round(cf_conclusion,6)
                })

            # merge candidates into facts_meta and collect which consequents actually changed
            for cons, meta in new_meta_candidates.items():
                old = facts_meta.get(cons)
                if old is None or abs(meta['cf'] - old['cf']) > 1e-9:
                    facts_meta[cons] = meta
                    new_facts.add(cons)

            # loop continues if new_facts non-empty

        # build final mapping: only rule-sourced facts that differ from user input (for UI compatibility)
        final = {
            k: round(v['cf'], 6)
            for k, v in facts_meta.items()
            if v['source'] == 'rule' and abs(v['cf'] - user_facts.get(k, -1)) > 1e-9
        }
        return final

# run inference
def run_inference(user_facts):
    engine = ForwardChaining(rules)
    final = engine.infer(user_facts)

    diagnoses = {k: v for k, v in final.items() if k.startswith('M')}
    sorted_diagnoses = sorted(diagnoses.items(), key=lambda x: x[1], reverse=True)
    sorted_all_facts = sorted(final.items(), key=lambda x: x[1], reverse=True)

    inference_log = []
    inference_log.append("--- MEMULAI PROSES INFERENSI ---")

    # Fakta awal
    inference_log.append("--- Fakta Awal dari Pengguna ---")
    if not user_facts:
        inference_log.append("Tidak ada fakta yang diberikan pengguna.")
    else:
        for fact, cf in user_facts.items():
            desc = kb.get(fact, fact)
            inference_log.append(f"FAKTA: {fact} ({desc}) dengan CF = {cf:.3f}")

    # Proses inferensi per rule
    inference_log.append("\n--- PROSES INFERENSI ---")
    current_iter = None

    for t in engine.trace_log:
        if current_iter != t['iteration']:
            current_iter = t['iteration']
            inference_log.append(f"\n>>> ITERASI {current_iter}")

        rule_name = t.get('rule_id', 'R?')
        ant_str = " AND ".join(t['antecedents'])
        inference_log.append(f"--- Memeriksa Aturan {rule_name}: IF ({ant_str}) THEN {t['consequent']} ---")

        if len(t['antecedents']) == len(t['antecedent_eff_cfs']):
            # tampilkan fakta dengan CF-nya
            facts_info = ", ".join([f"{a}(CF={cf:.3f})" for a, cf in zip(t['antecedents'], t['antecedent_eff_cfs'])])
            inference_log.append(f"-> SUKSES: Semua fakta prasyarat terpenuhi: ({facts_info})")
            inference_log.append(f"-> Mencari CF minimal dari fakta: Min({t['cf_premis']:.3f})")
            inference_log.append(
                f"-> Menghitung CF baru: CF_baru = CF_min * CF_aturan = {t['cf_premis']:.3f} * {t['rule_cf']:.3f} = {t['cf_conclusion']:.3f}"
            )
            inference_log.append(f"-> Menetapkan CF baru untuk {t['consequent']} = {t['cf_conclusion']:.3f}")
        else:
            # jika antecedent tidak lengkap
            missing = [a for a in t['antecedents'] if a not in user_facts]
            inference_log.append(f"-> GAGAL: Fakta {', '.join(missing)} tidak ada di input pengguna.")

    inference_log.append("\n--- PROSES INFERENSI SELESAI ---")

    return sorted_diagnoses, sorted_all_facts, inference_log

# Flask routes
@app.route('/')
def index():
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

## form dan hasil
@app.route('/diagnose', methods=['POST'])
def diagnose():
    user_facts = {}
    user_inputs_display = {}

    for code, value in request.form.items():
        try:
            cf_value = float(value)
        except Exception:
            continue
        if cf_value > 0:
            user_facts[code] = cf_value
            user_inputs_display[kb.get(code, code)] = cf_value

    sorted_diagnoses, sorted_all_facts, inference_log = run_inference(user_facts)

    display_results = []
    for code, cf in sorted_diagnoses:
        display_results.append({
            "code": code,
            "name": kb.get(code, code),
            "cf_percent": round(cf * 100, 2)
        })

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

