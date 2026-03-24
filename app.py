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
# Enable CORS for your frontend domain
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

# --- 2. API KEYS & CONFIG ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
def health():
    return jsonify({"status": "Online", "app": "SheriaHub Engine", "mode": "Sandbox" if IS_SANDBOX else "Live"}), 200

# --- 3. JUA MECHI GAME ENGINE ---
@app.route('/generate-jua-mechi', methods=['GET'])
def generate_jua_mechi():
    category = request.args.get("category", "tenant")
    
    prompt = (
        f"Act as a Kenyan Legal Expert. Create a 'Jua Mechi' (Spot the Error) game snippet for {category} law. "
        "Generate a short 2-paragraph contract text that looks official but contains EXACTLY 3 illegal clauses "
        "under Kenyan Statutes (e.g., the Employment Act 2007 or Rent Restriction Act). "
        "Return ONLY a JSON object with these keys: "
        "'contract_html' (the full text), "
        "'red_flags' (array of the 3 illegal phrases exactly as they appear in the text), "
        "'explanations' (array of 3 brief reasons why they are illegal)."
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

# --- 4. GATED AI CONSULTATION ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI Not Configured"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        is_paid = False
        credits_left = 0

        # Check for active payment session
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        law_context = {
            "tenant": "Kenyan Tenancy Law (Rent Restriction Act & Landlord/Tenant Bill)",
            "employment": "Employment Act 2007 Kenya",
            "traffic": "Traffic Act Cap 403 Kenya",
            "family": "Children Act 2022 & Marriage Act Kenya",
            "land": "Land Act & Land Registration Act Kenya",
            "civil_criminal": "Penal Code & Civil Procedure Act Kenya"
        }

        system_msg = (
            f"You are a Kenyan legal expert on {law_context.get(category, 'Kenyan Law')}. "
            "Format: Start with 'SUMMARY: ' (1-2 sentences, no Act names). "
            "Then 'DEEP_DIVE: ' (Full legal sections, steps, and citations)."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ]
        )
        
        full_text = completion.choices[0].message.content
        parts = full_text.split("DEEP_DIVE:")
        summary = parts[0].replace("SUMMARY:", "").strip()
        deep_dive = parts[1].strip() if len(parts) > 1 else "Analysis loading..."

        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if is_paid else "🔒 Unlock Deep-Dive with KSh 20."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 5. MPESA PAYMENT ROUTES (INTASEND) ---
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 20,
            "phone_number": phone,
            "api_ref": "SheriaHub_Game"
        }
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
        state = res.json().get("invoice", {}).get("state")
        
        if state == "COMPLETE":
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
    # Render/Vercel typically provide a PORT env var
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
