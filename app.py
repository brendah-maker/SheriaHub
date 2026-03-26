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

# --- 1. DATABASE ---
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

# --- 2. CONFIG ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "SANDBOX" if IS_SANDBOX else "LIVE"}), 200

# --- 3. THE AI BRAIN ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI offline"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        is_paid = False
        credits_left = 0

        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if not payment: # Sync fallback
                try:
                    res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}"})
                    if res.json().get("invoice", {}).get("state") == "COMPLETE":
                        payment = Payment(id=checkout_id, status="paid", credits=2)
                        db.session.add(payment); db.session.commit()
                except: pass

            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        if category == "game":
            system_msg = (
                "You are the host of 'Street Smarts: Nairobi Edition'. "
                "Scenario focus: Nairobi County By-laws and basic constitutional rights. "
                "1. If 'START', give 1 street scenario (Kanjo arrest, ID check, etc) with 3 options: A, B, C. "
                "2. If an answer is given, tell them if CORRECT/WRONG with a funny reaction and 1-sentence legal truth."
            )
        else:
            law_map = {
                "employment": "Employment Law", "land": "Land Law", "family": "Family Law",
                "traffic": "Traffic Law", "tenant": "Tenancy Law", "civil_criminal": "Civil/Criminal Law"
            }
            system_msg = (
                f"You are a Kenyan legal expert on {law_map.get(category, 'Law')}. "
                "Rule: Start with 'SUMMARY: ' followed by a 1-sentence overview without Act names. "
                "Then write 'DEEP_DIVE: ' followed by the citations and steps."
            )

        completion = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": question}])
        full_text = completion.choices[0].message.content
        
        if category == "game":
            summary = full_text; content = "Game Active"
        else:
            clean_txt = full_text.replace("**SUMMARY:**", "SUMMARY:").replace("**DEEP_DIVE:**", "DEEP_DIVE:")
            if "DEEP_DIVE:" in clean_txt:
                parts = clean_txt.split("DEEP_DIVE:")
                summary = parts[0].replace("SUMMARY:", "").strip()
                content = parts[1].strip()
            else:
                summary = full_text.split('.')[0] + "."; content = full_text

        return jsonify({"status": "premium" if (is_paid or category=="game") else "free", "credits_left": credits_left, "summary": summary, "content": content})
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
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"})
        res_data = res.json()
        inv_id = res_data.get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending", credits=0)); db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "Failed"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    inv_id = data.get("invoice_id")
    if inv_id and data.get("state") == "COMPLETE":
        p = Payment.query.get(inv_id)
        if not p: db.session.add(Payment(id=inv_id, status="paid", credits=2))
        else: p.status = "paid"; p.credits = 2
        db.session.commit()
    return jsonify({"ok": True}), 200

@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid", "credits": p.credits})
    try:
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}"})
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if not p: p = Payment(id=id, status="paid", credits=2)
            else: p.status = "paid"; p.credits = 2
            db.session.add(p); db.session.commit()
            return jsonify({"status": "paid", "credits": 2})
    except: pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
