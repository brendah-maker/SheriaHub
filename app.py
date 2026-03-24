import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- DATABASE ---
uri = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(20), default="pending")
    credits = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

# --- API KEYS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- UPDATED KANJO ENGINE (Chaos Edition) ---
@app.route('/generate-kanjo', methods=['GET'])
def generate_kanjo():
    prompt = (
        "Generate a funny but realistic 'Kanjo Chronicles' scenario in Nairobi. "
        "Scenarios should vary: a hawker running with oranges, a pedestrian crossing at the wrong spot, "
        "or a motorist being harrassed. Make the Kanjo dialogue 'street-smart'. "
        "Include 3 options: A (Try to bribe/negotiate), B (Run/Argue), C (Know your rights/Demand ID). "
        "Return ONLY JSON: {'scenario': '...', 'choice_a': '...', 'choice_b': '...', 'choice_c': '...', "
        "'outcome_a': '...', 'outcome_b': '...', 'outcome_c': '...', 'correct_choice': 'C'}"
    )
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return completion.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- CONSULTATION LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.get_json()
    q, ck_id = data.get("question"), data.get("checkout_id")
    is_paid, credits = False, 0
    if ck_id and ck_id != "undefined":
        p = Payment.query.get(ck_id)
        if p and p.status == "paid" and p.credits > 0:
            is_paid, p.credits = True, p.credits - 1
            credits = p.credits
            db.session.commit()

    sys_msg = "You are a Kenyan legal expert. Start with 'SUMMARY: ' then 'DEEP_DIVE: '."
    res = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": q}])
    txt = res.choices[0].message.content
    sum_part = txt.split("DEEP_DIVE:")[0].replace("SUMMARY:", "").strip()
    deep_part = txt.split("DEEP_DIVE:")[1].strip() if "DEEP_DIVE:" in txt else txt
    
    return jsonify({"status": "premium" if is_paid else "free", "credits_left": credits, "summary": sum_part, "content": deep_part if is_paid else "🔒 Pay KSh 20 to unlock Section citations."})

# --- PAYMENTS ---
@app.route('/stkpush', methods=['POST'])
def stk_push():
    data = request.get_json()
    phone = data.get("phone", "").replace("+", "")
    if phone.startswith("0"): phone = "254" + phone[1:]
    payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
    res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}"})
    inv_id = res.json().get("invoice", {}).get("invoice_id")
    if inv_id:
        db.session.add(Payment(id=inv_id, status="pending", credits=0))
        db.session.commit()
        return jsonify({"checkout_id": inv_id})
    return jsonify({"error": "Failed"}), 400

@app.route('/check-payment/<id>')
def check_p(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid"})
    res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}"})
    if res.json().get("invoice", {}).get("state") == "COMPLETE":
        p.status, p.credits = "paid", 2
        db.session.commit()
        return jsonify({"status": "paid"})
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
