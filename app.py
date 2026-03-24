import os
import json
import requests
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. DATABASE CONFIGURATION ---
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

# --- 2. API KEYS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- NEW: DRAMA COURT ENGINE ---
@app.route('/generate-drama', methods=['GET'])
def generate_drama():
    prompt = (
        "Generate a 'Who is the Drama' legal scenario for Kenya. "
        "It should be a dispute between two people (e.g. Mama Njuguna vs Baba Otis) "
        "involving money, property, or relationships. "
        "Return ONLY a JSON object: {"
        "'scenario': 'Short 2-sentence story', "
        "'person_a': 'Name of Person A', 'person_b': 'Name of Person B', "
        "'judgment': 'A 3-sentence legal explanation citing Kenyan law on who is right'}"
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

# --- PRE-EXISTING ROUTES ---
@app.route('/')
def health(): return jsonify({"status": "Healthy"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI not initialized"}), 500
    data = request.get_json()
    question = data.get("question", "")
    category = data.get("category", "tenant")
    checkout_id = data.get("checkout_id")

    is_paid = False
    credits_left = 0

    if checkout_id and checkout_id != "undefined":
        payment = Payment.query.get(checkout_id)
        if payment and payment.status == "paid" and payment.credits > 0:
            is_paid = True
            payment.credits -= 1
            credits_left = payment.credits
            db.session.commit()

    system_msg = f"You are a Kenyan legal expert. Start with 'SUMMARY: ' then 'DEEP_DIVE: ' for {category}."
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant", 
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": question}]
    )
    full_text = completion.choices[0].message.content
    summary = full_text.split("DEEP_DIVE:")[0].replace("SUMMARY:", "").strip()
    deep_dive = full_text.split("DEEP_DIVE:")[1].strip() if "DEEP_DIVE:" in full_text else full_text

    return jsonify({
        "status": "premium" if is_paid else "free",
        "credits_left": credits_left,
        "summary": summary,
        "content": deep_dive if is_paid else "🔒 Payment required for specific Acts."
    })

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        inv_id = res.json().get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending", credits=0))
            db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "Rejected"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid"})
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
