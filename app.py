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

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "SANDBOX" if IS_SANDBOX else "LIVE"}), 200


# --- 3. THE UPDATED "GATED" AI LOGIC ---

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

        # --- 1. Payment Logic (Remains the same) ---
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if not payment:
                try:
                    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
                    res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
                    if res.json().get("invoice", {}).get("state") == "COMPLETE":
                        payment = Payment(id=checkout_id, status="paid", credits=2)
                        db.session.add(payment)
                        db.session.commit()
                except: pass
            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        law_map = {
            "employment": "Employment Law", "land": "Land Law", "family": "Family Law",
            "traffic": "Traffic Law", "tenant": "Tenancy Law", "civil_criminal": "Civil/Criminal Law"
        }
            
        # --- 2. THE STRICTOR "FEW-SHOT" PROMPT ---
        system_msg = (
            f"You are a Kenyan {law_map.get(category)} intake bot. You MUST split your response with '|||'.\n\n"
            "PART 1 (FREE SUMMARY): Be vague. Max 2 sentences. Never mention Acts, Sections, or Years.\n"
            "Example: 'It sounds like you have a dispute. Kenyan law provides protections for this, which are detailed in the Deep Dive below.'\n\n"
            "|||\n\n"
            "PART 2 (PAID DEEP DIVE): Provide full technical legal advice with specific Act and Section citations."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"User question: {question}. REMEMBER: Do NOT give citations in Part 1."}
            ],
            temperature=0.0 # Force consistency
        )
        
        full_text = completion.choices[0].message.content
        
        # --- 3. AGGRESSIVE BACKEND CLEANING ---
        if "|||" in full_text:
            parts = full_text.split("|||")
            summary = parts[0].strip()
            deep_dive = parts[1].strip()
        else:
            # Fallback if split fails
            summary = "We have analyzed your query. Full legal details are available in the Deep Dive."
            deep_dive = full_text

        # REMOVE ANY LEAKED HEADERS
        summary = re.sub(r'^(Summary|PART 1|Overview):', '', summary, flags=re.IGNORECASE).strip()
        
        # FORCE LENGTH LIMIT (The 'Hammer')
        # If the AI gives more than 200 chars in a summary, we cut it off.
        if len(summary) > 200:
            summary = summary[:180] + "... [Details hidden in Deep Dive]"

        # --- 4. THE PAYWALL ---
        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if is_paid else "🔒 **Unlock the Deep Dive** to see specific legal Acts (e.g. Employment Act), Sections, and step-by-step court procedures for just KES 20."
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
        return jsonify({"error": "Rejected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# FIX: Added Callback Route back in
@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    inv_id = data.get("invoice_id")
    if inv_id and data.get("state") == "COMPLETE":
        p = Payment.query.get(inv_id)
        if not p: db.session.add(Payment(id=inv_id, status="paid", credits=2))
        else:
            p.status = "paid"
            p.credits = 2
        db.session.commit()
    return jsonify({"ok": True}), 200

@app.route('/check-payment/<id>')
def check_payment(id):
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
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
