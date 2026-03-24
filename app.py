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
    # Migration check for credits column
    try:
        db.session.execute(text("SELECT credits FROM payment LIMIT 1"))
    except Exception:
        db.session.execute(text("ALTER TABLE payment ADD COLUMN credits INTEGER DEFAULT 0"))
        db.session.commit()

# --- 2. API KEYS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- 3. THE "GATED" AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI not initialized"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        is_paid = False
        credits_left = 0

        # Credit Validation Logic
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        # Logic Branching: KANJO GAME vs LEGAL CONSULTANT
        if category == "kanjo":
            system_msg = (
                "You are 'Kanjo-GPT', an expert on Nairobi City Council Bylaws. "
                "The user is playing a street survival game. "
                "If the user says 'START', create a scenario where they are confronted by Kanjo officers. "
                "Provide 3 options: A, B, and C. "
                "If they choose an option, tell them if they are legally right or wrong based on the Nairobi County Bylaws. "
                "Always keep the tone fast-paced and 'Nairobi Street Smart'."
            )
        else:
            law_map = {
                "employment": "Employment Law", "land": "Land & Property Law",
                "family": "Family & Children Law", "traffic": "Traffic Law",
                "tenant": "Tenancy Law", "civil_criminal": "Civil & Criminal Law"
            }
            system_msg = (
                f"You are a Kenyan legal expert on {law_map.get(category, 'Law')}. "
                "Follow these formatting rules strictly:\n"
                "1. Start with 'SUMMARY: ' followed by a 1-2 sentence overview. NEVER mention specific Act names or Sections here.\n"
                "2. Then write 'DEEP_DIVE: ' followed by full details, Sections, Acts, and legal steps."
            )

        # Call Llama-3.1
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ]
        )
        
        full_text = completion.choices[0].message.content
        
        # Split Logic for Gated Content
        if "DEEP_DIVE:" in full_text:
            parts = full_text.split("DEEP_DIVE:")
            summary = parts[0].replace("SUMMARY:", "").strip()
            deep_dive = parts[1].strip()
        else:
            summary = full_text if category == "kanjo" else "Refer to summary."
            deep_dive = full_text

        return jsonify({
            "status": "premium" if is_paid or category == "kanjo" else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if (is_paid or category == "kanjo") else "🔒 Payment required for specific Acts, Section citations, and court filing guides."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 4. PAYMENT ROUTES (STK, Callback, Check) ---

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        elif (phone.startswith("7") or phone.startswith("1")) and len(phone) == 9: phone = "254" + phone
        
        payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = res.json()
        
        inv_id = res_data.get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending", credits=0))
            db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "STK Push Rejected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid", "credits": p.credits})
    
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
        status = res.json().get("invoice", {}).get("state")
        
        if status == "COMPLETE":
            if not p: p = Payment(id=id, status="paid", credits=2)
            else:
                p.status = "paid"
                p.credits = 2
            db.session.commit()
            return jsonify({"status": "paid", "credits": 2})
    except: pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
