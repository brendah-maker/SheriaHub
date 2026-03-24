import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- DATABASE CONFIG ---
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

# --- KANJO GAME ENGINE ---
@app.route('/generate-kanjo', methods=['GET'])
def generate_kanjo():
    prompt = (
        "Generate a 'Kanjo Chronicles' survival scenario in Nairobi CBD. "
        "The user is faced with a city council officer. Provide 3 options: "
        "A (Compliant/Bribe-prone), B (Aggressive), C (Legally correct). "
        "Return ONLY a JSON object: {"
        "'scenario': '...', 'choice_a': '...', 'choice_b': '...', 'choice_c': '...', "
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
    question = data.get("question", "")
    category = data.get("category", "tenant")
    checkout_id = data.get("checkout_id")

    is_paid, credits_left = False, 0
    if checkout_id and checkout_id != "undefined":
        p = Payment.query.get(checkout_id)
        if p and p.status == "paid" and p.credits > 0:
            is_paid = True
            p.credits -= 1
            credits_left = p.credits
            db.session.commit()

    sys_msg = f"You are a Kenyan legal expert on {category} law. Start with 'SUMMARY: ' then 'DEEP_DIVE: '."
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": question}]
    )
    full_text = completion.choices[0].message.content
    summary = full_text.split("DEEP_DIVE:")[0].replace("SUMMARY:", "").strip()
    content = full_text.split("DEEP_DIVE:")[1].strip() if "DEEP_DIVE:" in full_text else full_text

    return jsonify({
        "status": "premium" if is_paid else "free",
        "credits_left": credits_left,
        "summary": summary,
        "content": content if is_paid else "🔒 Pay KSh 20 to unlock Section citations and full legal steps."
    })

# --- PAYMENT ROUTES ---
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
def check_payment(id):
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
