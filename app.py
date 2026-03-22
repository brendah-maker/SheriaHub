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
    try:
        db.session.execute(text("ALTER TABLE payment ADD COLUMN credits INTEGER DEFAULT 0"))
        db.session.commit()
    except Exception:
        db.session.rollback()

# --- 2. API KEYS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "SANDBOX" if IS_SANDBOX else "LIVE"}), 200

# --- 3. IMPROVED AI LOGIC (No Truncation) ---
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

        law_map = {
            "employment": "Employment Act 2007",
            "land": "Land Act 2012 & Land Registration Act",
            "family": "Marriage Act, Children Act 2022",
            "traffic": "Traffic Act Cap 403",
            "tenant": "Rent Restriction Act",
            "civil_criminal": "Penal Code of Kenya & Civil Procedure"
        }
        
        prompt = (
            f"You are a Kenyan legal expert on {law_map.get(category)}. "
            f"User Question: {question}\n\n"
            "Provide your response in two distinct parts exactly like this:\n"
            "SUMMARY: [Provide a full, clear paragraph explaining the core legal answer without cutting it off]\n"
            "DEEP_DIVE: [Provide the detailed legal sections and citations]"
        )

        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        
        txt = chat.choices[0].message.content
        
        # SMART PARSING: Handle bold markers and case-sensitivity
        # We split by 'DEEP_DIVE:' but we remove any bold stars '**' around labels
        clean_txt = txt.replace("**SUMMARY:**", "SUMMARY:").replace("**DEEP_DIVE:**", "DEEP_DIVE:")
        
        if "DEEP_DIVE:" in clean_txt:
            parts = clean_txt.split("DEEP_DIVE:")
            summary = parts[0].replace("SUMMARY:", "").strip()
            deep_dive = parts[1].strip()
        else:
            # Fallback if AI missed the marker: Take first paragraph as summary
            paragraphs = txt.split('\n\n')
            summary = paragraphs[0].replace("SUMMARY:", "").strip()
            deep_dive = txt

        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary, # This is now full-length
            "content": deep_dive if is_paid else "Payment required for deep dive."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 4. PAYMENT ROUTES ---
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
        
        if res.status_code != 200:
            return jsonify({"error": "Rejected", "details": res_data}), 400

        inv_id = res_data.get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending", credits=0))
            db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "No ID"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<id>')
def check(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid", "credits": p.credits})
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if not p: p = Payment(id=id, status="paid", credits=2)
            else:
                p.status = "paid"
                p.credits = 2
            db.session.add(p)
            db.session.commit()
            return jsonify({"status": "paid", "credits": 2})
    except: pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
