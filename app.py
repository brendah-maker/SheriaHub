import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --- 1. CORS CONFIGURATION ---
# Allows your website to talk to this backend
CORS(app, resources={r"/*": {
    "origins": [
        "https://www.sheriahub.co.ke", 
        "https://sheriahub.co.ke",
        "https://sheria-hub.vercel.app" # Your vercel domain
    ]
}})

# --- 2. DATABASE CONFIGURATION ---
# On Render, use a PostgreSQL database for live payments to persist!
uri = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)  # invoice_id
    status = db.Column(db.String(20), default="pending")

with app.app_context():
    db.create_all()

# --- 3. API KEYS & URLS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")

# Check if we are in Sandbox or Live
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
def health():
    mode = "SANDBOX" if IS_SANDBOX else "LIVE"
    return jsonify({"status": "active", "mode": mode, "region": "Kenya"}), 200

# --- 4. AI CONSULTATION LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI client not initialized"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        # Check Payment Status
        is_paid = False
        if checkout_id:
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid":
                is_paid = True

        legal_context = "Expert in Kenyan Employment Law" if category == "employment" else "Expert in Kenyan Tenancy Law"
            
        system_prompt = (
            f"You are a {legal_context}. Return ONLY a JSON object. "
            "Structure: {\"free_summary\": \"one sentence\", \"paid_deep_dive\": \"comprehensive markdown\"}"
        )

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        
        ai_raw = json.loads(completion.choices[0].message.content)
        
        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": ai_raw.get("free_summary", "Summary unavailable."),
            "content": ai_raw.get("paid_deep_dive") if is_paid else "Payment required to unlock deep dive."
        })
        
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"error": "AI Processing error"}), 500

# --- 5. LIVE M-PESA STK PUSH ---
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        
        # Clean phone number for Kenyan Standards (e.g., 2547...)
        if phone.startswith("0"): 
            phone = "254" + phone[1:]
        elif (phone.startswith("7") or phone.startswith("1")) and len(phone) == 9:
            phone = "254" + phone
        
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 20, 
            "phone_number": phone,
            "api_ref": "SheriaHub-Premium",
        }

        headers = {
            "Authorization": f"Bearer {INTASEND_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        print(f"--- Sending LIVE STK Push to {phone} ---")
        response = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = response.json()
        
        if response.status_code != 200:
            print(f"❌ IntaSend Error: {res_data}")
            return jsonify({"error": "Payment initialization failed", "details": res_data}), 400

        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            new_payment = Payment(id=invoice_id, status="pending")
            db.session.add(new_payment)
            db.session.commit()
            return jsonify({"checkout_id": invoice_id})
        
        return jsonify({"error": "Invalid response from payment gateway"}), 400
        
    except Exception as e:
        print(f"🔥 STK Push Crash: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# --- 6. PAYMENT STATUS CHECKER ---
@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    if not checkout_id or checkout_id == "undefined":
        return jsonify({"status": "error", "message": "Invalid ID"}), 400

    payment = Payment.query.get(checkout_id)
    if payment and payment.status == "paid":
        return jsonify({"status": "paid"})
    
    # Live Status Check with IntaSend API
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        data = res.json()
        state = data.get("invoice", {}).get("state")

        if state == "COMPLETE":
            if not payment:
                payment = Payment(id=checkout_id, status="paid")
                db.session.add(payment)
            else:
                payment.status = "paid"
            db.session.commit()
            return jsonify({"status": "paid"})
    except Exception as e:
        print(f"Status check failed: {e}")
        
    return jsonify({"status": payment.status if payment else "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
