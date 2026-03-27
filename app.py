import os
import json
import requests
import pdfplumber
import io
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
CORS(app)

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
IS_LIVE = os.environ.get("IS_LIVE", "False").lower() == "true"
BASE_URL = "https://api.intasend.com/api/v1" if IS_LIVE else "https://sandbox.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- 3. AUDIT CONTRACT ROUTE (THE MISSING ONE) ---
@app.route('/audit-contract', methods=['POST'])
def audit_contract():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    try:
        with pdfplumber.open(io.BytesIO(file.read())) as pdf:
            contract_text = " ".join([page.extract_text() or "" for page in pdf.pages])

        if not contract_text.strip():
            return jsonify({"analysis": "❌ Could not read text from this PDF."})

        system_msg = (
            "You are an expert Kenyan Legal Auditor. Analyze the contract for: "
            "1. ILLEGAL CLAUSES, 2. HIDDEN RISKS, 3. TERMINATION TERMS. "
            "Use clear sections."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Audit: {contract_text[:4000]}"}
            ]
        )
        return jsonify({"analysis": completion.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 4. STANDARD AI ROUTE ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
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

        law_map = {"employment": "Employment Law", "land": "Land Law", "family": "Family Law", "traffic": "Traffic Law", "tenant": "Tenancy Law", "civil_criminal": "Civil/Criminal Law"}
        system_msg = f"Kenyan legal expert on {law_map.get(category)}. Start with 'SUMMARY: ' then 'DEEP_DIVE: '."

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": question}]
        )
        
        full_text = completion.choices[0].message.content
        parts = full_text.split("DEEP_DIVE:")
        summary = parts[0].replace("SUMMARY:", "").strip()
        deep_dive = parts[1].strip() if len(parts) > 1 else full_text

        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if is_paid else "🔒 Detailed analysis locked."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 5. PAYMENT ROUTES ---
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = res.json()
        inv_id = res_data.get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending", credits=0))
            db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "Failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid", "credits": p.credits})
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if not p: p = Payment(id=id, status="paid", credits=2)
            else: p.status, p.credits = "paid", 2
            db.session.add(p); db.session.commit()
            return jsonify({"status": "paid", "credits": 2})
    except: pass
    return jsonify({"status": "pending"})

@app.route('/health')
def health(): return jsonify({"ok": True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
