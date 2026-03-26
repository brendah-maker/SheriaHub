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
# Allows your Vercel frontend to communicate with this Render backend
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

# --- AUTO-MIGRATION: Ensures 'credits' column exists in Production ---
with app.app_context():
    db.create_all()
    try:
        # This adds the credits column if it's missing from your existing Render DB
        db.session.execute(text("ALTER TABLE payment ADD COLUMN credits INTEGER DEFAULT 0"))
        db.session.commit()
    except Exception:
        db.session.rollback()

# --- 2. API KEYS & ENVIRONMENT ---
# .strip() prevents errors from accidental spaces in Render environment variables
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

# --- 3. CORE AI LOGIC (CONSULTATION & SURVIVAL GAME) ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI client not initialized"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        is_paid = False
        credits_left = 0

        # CREDIT CHECK & CONSUMPTION
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            
            # Sync with IntaSend if record is missing (Auto-repair database)
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

        # DEFINE AI BEHAVIOR
        if category == "game":
            # Survival Game instructions
            system_msg = (
                "You are the 'Sheria Survival Master'. Kenyan legal street scenarios. "
                "YOU MUST RESPOND ONLY IN VALID JSON. NO MARKDOWN. NO BACKTICKS. "
                "Type 1 (Scenario): {'type': 'question', 'text': 'Scenario here', 'a': '...', 'b': '...', 'c': '...'} "
                "Type 2 (Grading): {'type': 'result', 'correct': true/false, 'reaction': 'funny text in Sheng', 'explanation': 'legal fact'}"
            )
            response_format = {"type": "json_object"}
        else:
            # Legal Consultation instructions
            law_map = {
                "employment": "Employment Law", "land": "Land & Property Law",
                "family": "Family Law", "traffic": "Traffic Law",
                "tenant": "Tenancy Law", "civil_criminal": "Civil & Criminal Law"
            }
            context = law_map.get(category, "Kenyan Law")
            system_msg = (
                f"You are a Kenyan legal expert on {context}. "
                "Follow this strict structure:\n"
                "1. SUMMARY: Provide a 1-sentence helpful overview. NO Act/Section names allowed here.\n"
                "2. DEEP_DIVE: Provide full details, specific Sections, Acts, and step-by-step court guides."
            )
            response_format = None

        # CALL AI
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": question}],
            response_format=response_format
        )
        
        ai_resp = completion.choices[0].message.content

        if category == "game":
            # Clean AI response in case it includes markdown backticks
            cleaned_json = re.sub(r'```json\s*|\s*```', '', ai_resp).strip()
            return jsonify(json.loads(cleaned_json))
        else:
            # Parse Consultation Output
            clean_txt = ai_resp.replace("**SUMMARY:**", "SUMMARY:").replace("**DEEP_DIVE:**", "DEEP_DIVE:")
            if "DEEP_DIVE:" in clean_txt:
                parts = clean_txt.split("DEEP_DIVE:")
                summary = parts[0].replace("SUMMARY:", "").strip()
                content = parts[1].strip()
            else:
                summary = ai_resp.split('.')[0] + "."
                content = ai_resp

            return jsonify({
                "status": "premium" if is_paid else "free",
                "credits_left": credits_left,
                "summary": summary,
                "content": content if is_paid else "🔒 Unlock for specific Acts, Section citations, and step-by-step filing guides."
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 4. M-PESA PAYMENT ROUTES ---
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
        return jsonify({"error": "Payment rejected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    try:
        data = request.get_json()
        inv_id = data.get("invoice_id")
        if inv_id and data.get("state") == "COMPLETE":
            p = Payment.query.get(inv_id)
            if not p: db.session.add(Payment(id=inv_id, status="paid", credits=2))
            else: p.status = "paid"; p.credits = 2
            db.session.commit()
        return jsonify({"ok": True}), 200
    except: return jsonify({"ok": False}), 500

@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid", "credits": p.credits})
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if not p: p = Payment(id=id, status="paid", credits=2)
            else: p.status = "paid"; p.credits = 2
            db.session.add(p); db.session.commit()
            return jsonify({"status": "paid", "credits": 2})
    except: pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    # Using Render's PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
