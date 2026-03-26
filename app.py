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

# --- 3. ROBUST AI LOGIC ---
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
            if not payment:
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
                "You are the 'Sheria Survival Master'. Kenyan legal scenarios. "
                "Respond ONLY in JSON. "
                "If START: {'type': 'question', 'text': '...', 'a': '...', 'b': '...', 'c': '...'} "
                "If grading: {'type': 'result', 'correct': true/false, 'reaction': '...', 'explanation': '...'} "
            )
            response_format = {"type": "json_object"}
        else:
            law_map = {
                "employment": "Employment Law", "land": "Land Law", "family": "Family Law",
                "traffic": "Traffic Law", "tenant": "Tenancy Law", "civil_criminal": "Civil/Criminal Law"
            }
            system_msg = f"Expert in {law_map.get(category, 'Law')}. Format: SUMMARY: [text] DEEP_DIVE: [text]"
            response_format = None

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": question}],
            response_format=response_format
        )
        
        ai_resp = completion.choices[0].message.content

        if category == "game":
            # REFINEMENT: Pull JSON out even if AI wraps it in backticks
            try:
                json_match = re.search(r'\{.*\}', ai_resp, re.DOTALL)
                if json_match:
                    return jsonify(json.loads(json_match.group()))
                return jsonify(json.loads(ai_resp))
            except:
                return jsonify({"type": "result", "correct": False, "reaction": "AI Error", "explanation": "The AI sent bad data. Please try again."})
        else:
            clean_txt = ai_resp.replace("**SUMMARY:**", "SUMMARY:").replace("**DEEP_DIVE:**", "DEEP_DIVE:")
            if "DEEP_DIVE:" in clean_txt:
                parts = clean_txt.split("DEEP_DIVE:")
                summary = parts[0].replace("SUMMARY:", "").strip(); content = parts[1].strip()
            else:
                summary = ai_resp.split('.')[0] + "."; content = ai_resp
            return jsonify({"status": "premium" if is_paid else "free", "credits_left": credits_left, "summary": summary, "content": content})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# (Payment routes: callback, stkpush, check_payment - same as previous working version)
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers={"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"})
        res_data = res.json()
        if res.status_code == 200:
            inv_id = res_data.get("invoice", {}).get("invoice_id")
            db.session.add(Payment(id=inv_id, status="pending", credits=0)); db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "Failed"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    if data.get("invoice_id") and data.get("state") == "COMPLETE":
        p = Payment.query.get(data.get("invoice_id"))
        if not p: db.session.add(Payment(id=data.get("invoice_id"), status="paid", credits=2))
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
