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

        # --- Payment logic (Keep your existing database check here) ---
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
            "employment": "Employment Law",
            "land": "Land & Property Law",
            "family": "Family & Children Law",
            "traffic": "Traffic Law",
            "tenant": "Tenancy Law",
            "civil_criminal": "Civil & Criminal Law"
        }
            
        # --- IMPROVED SYSTEM PROMPT ---
        system_msg = (
            f"You are a legal intake assistant for Kenyan {law_map.get(category)}. "
            "Your response MUST be divided by the exact string '|||'.\n\n"
            "PART 1 (FREE SUMMARY): Write exactly 2 sentences. Acknowledge the user's problem. "
            "STRICT FORBIDDEN LIST: Never mention 'Act', 'Section', '2007', '1996', or any law names. "
            "Simply state that the law provides protection and the Deep Dive contains the exact steps to take.\n\n"
            "|||\n\n"
            "PART 2 (PAID DEEP DIVE): Provide the full legal advice, citing specific Acts and Sections."
        )

        # FIX 1: Set temperature=0 for consistency
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.0 # <--- This stops it from giving different answers
        )
        
        full_text = completion.choices[0].message.content
        
        # --- ROBUST SPLITTING ---
        if "|||" in full_text:
            parts = full_text.split("|||")
            summary = parts[0].strip()
            deep_dive = parts[1].strip()
        else:
            # Fallback if AI ignores separator
            summary = "We have identified potential legal grounds for your case. Details are in the Deep Dive."
            deep_dive = full_text

        # FIX 2: Backend Sanitizer (Remove any leaked law names automatically)
        leaks = ["Act", "Section", "Chapter", "Constitution", "2007", "1996", "2010", "1971"]
        for word in leaks:
            if word in summary:
                # If a law name leaked, cut the sentence there and add a teaser
                summary = summary.split(word)[0] + "... [Specific legal citations available in the Deep Dive]"
                break

        # --- THE GATED RETURN ---
        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary, # Always short and vague
            # Fix 3: Content is strictly gated. If not paid, deep_dive is NEVER sent.
            "content": deep_dive if is_paid else "🔒 **Unlock the Deep Dive** to see the specific legal Acts, Section numbers, and a step-by-step guide on how to file your case for just KES 20."
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
