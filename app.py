import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --- 1. CORS CONFIGURATION ---
# Open for testing so your Vercel branches can talk to Render
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 2. DATABASE CONFIGURATION ---
# NOTE: On Render Free Tier, SQLite is wiped every time you deploy.
# Consider adding a "PostgreSQL" database in Render for permanent storage.
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

# IMPORTANT: Ensure this is set to 'False' on Render for real money payments
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
def health():
    mode = "SANDBOX" if IS_SANDBOX else "LIVE"
    return jsonify({"status": "Online", "mode": mode, "db_uri": "Connected"}), 200

@app.route('/test-ai')
def test_ai():
    if not client: return "❌ Groq Key Missing", 500
    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": "Hi"}],
            model="llama-3.1-8b-instant"
        )
        return f"✅ Groq Connected! Response: {chat.choices[0].message.content}"
    except Exception as e:
        return f"❌ Groq Error: {str(e)}", 500

# --- 4. AI CONSULTATION LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI not initialized"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        # Check local DB for payment status
        is_paid = False
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid":
                is_paid = True

        law_map = {
            "employment": "Employment Act 2007",
            "land": "Land Act 2012",
            "family": "Marriage Act and Succession Act",
            "traffic": "Traffic Act Cap 403",
            "tenant": "Rent Restriction Act"
        }
        law = law_map.get(category, "Kenyan Law")
            
        system_prompt = (
            f"You are a Kenyan legal expert specializing in {law}. "
            "You MUST return a valid JSON object. "
            "Structure: {\"free_summary\": \"one sentence\", \"paid_deep_dive\": \"comprehensive markdown\"}"
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": question}],
            response_format={"type": "json_object"}
        )
        
        ai_data = json.loads(completion.choices[0].message.content)
        
        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": ai_data.get("free_summary", "Summary unavailable."),
            "content": ai_data.get("paid_deep_dive") if is_paid else "Payment required to unlock deep dive."
        })
    except Exception as e:
        print(f"🔥 AI Crash: {e}")
        return jsonify({"error": "AI processing failed"}), 500

# --- 5. M-PESA STK PUSH ---
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        elif (phone.startswith("7") or phone.startswith("1")) and len(phone) == 9: phone = "254" + phone
        
        payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        
        print(f"--- Sending STK Push to {phone} [Mode: {BASE_URL}] ---")
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = res.json()
        
        if res.status_code != 200:
            print(f"❌ IntaSend Rejected: {res_data}")
            return jsonify({"error": "Payment rejected by provider", "details": res_data}), 400

        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        if invoice_id:
            db.session.add(Payment(id=invoice_id, status="pending"))
            db.session.commit()
            return jsonify({"checkout_id": invoice_id})
        return jsonify({"error": "Invalid response from IntaSend"}), 400
    except Exception as e:
        print(f"🔥 STK Crash: {e}")
        return jsonify({"error": str(e)}), 500

# --- 6. SMART STATUS CHECKER ---
@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    if not checkout_id or checkout_id == "undefined":
        return jsonify({"status": "error"}), 400

    # 1. Check local database first
    payment = Payment.query.get(checkout_id)
    if payment and payment.status == "paid":
        return jsonify({"status": "paid"})
    
    # 2. Check directly with IntaSend API (The "Sync" fix)
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        url = f"{BASE_URL}/payment/status/{checkout_id}/"
        res = requests.get(url, headers=headers)
        data = res.json()
        
        # IntaSend state is usually 'COMPLETE' for success
        state = data.get("invoice", {}).get("state", "PENDING")
        print(f"DEBUG: Checking {checkout_id} -> API says: {state}")

        if state == "COMPLETE":
            if not payment:
                # If deploy wiped the DB, recreate the record here
                payment = Payment(id=checkout_id, status="paid")
                db.session.add(payment)
            else:
                payment.status = "paid"
            db.session.commit()
            print(f"✅ Payment {checkout_id} marked as PAID in DB")
            return jsonify({"status": "paid"})
            
    except Exception as e:
        print(f"DEBUG Error checking payment status: {e}")
        
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
