import os
import json
import requests
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Database ---
uri = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(20), default="pending")

# Create tables
with app.app_context():
    db.create_all()

# --- Config ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Online", "mode": "SANDBOX" if IS_SANDBOX else "LIVE"}), 200

# --- Robust AI Logic ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI not initialized"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        print(f"--- AI Request Received: {category} ---")

        # 1. Check Payment Status
        is_paid = False
        if checkout_id and checkout_id != "undefined":
            try:
                payment = Payment.query.get(checkout_id)
                if payment and payment.status == "paid":
                    is_paid = True
                    print(f"✅ Verified Paid Status for {checkout_id}")
            except Exception as db_err:
                print(f"⚠️ DB Query Warning: {db_err}")

        # 2. Select Law Context
        law_map = {
            "employment": "Employment Act 2007",
            "land": "Land Act 2012 & Land Registration Act",
            "family": "Children Act 2022, Marriage Act, and Succession Act",
            "traffic": "Traffic Act Cap 403",
            "tenant": "Rent Restriction Act"
        }
        law = law_map.get(category, "Kenyan Law")
            
        system_prompt = (
            f"You are a Kenyan legal expert specializing in {law}. "
            "You MUST return a JSON object with two keys: "
            "'free_summary' (one brief sentence) and 'paid_deep_dive' (detailed markdown with specific sections). "
            "Do not include any text outside the JSON block."
        )

        # 3. Call AI
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": question}],
            response_format={"type": "json_object"}
        )
        
        raw_content = completion.choices[0].message.content
        print(f"🤖 AI Response length: {len(raw_content)}")

        # 4. Self-Healing JSON Parsing
        try:
            ai_data = json.loads(raw_content)
        except:
            print("⚠️ JSON Parse failed, attempting cleanup...")
            # Fallback: find the first { and last }
            match = re.search(r'({.*})', raw_content, re.DOTALL)
            if match:
                ai_data = json.loads(match.group(1))
            else:
                raise ValueError("AI output is not valid JSON")

        # 5. Final Output
        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": ai_data.get("free_summary", "Legal summary unavailable."),
            "content": ai_data.get("paid_deep_dive", "Deep dive details currently processing...") if is_paid else "Payment required for deep dive."
        })

    except Exception as e:
        print(f"🔥 CRITICAL ERROR in ask-ai: {str(e)}")
        return jsonify({"error": "AI processing error", "msg": str(e)}), 500

# --- Payment Routes (Maintained) ---
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
        
        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        if invoice_id:
            db.session.add(Payment(id=invoice_id, status="pending"))
            db.session.commit()
            return jsonify({"checkout_id": invoice_id})
        return jsonify({"error": "Payment rejected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    invoice_id = data.get("invoice_id")
    state = data.get("state") 
    if invoice_id and state == "COMPLETE":
        payment = Payment.query.get(invoice_id)
        if not payment:
            payment = Payment(id=invoice_id, status="paid")
            db.session.add(payment)
        else:
            payment.status = "paid"
        db.session.commit()
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    if not checkout_id or checkout_id == "undefined": return jsonify({"status": "error"}), 400
    payment = Payment.query.get(checkout_id)
    if payment and payment.status == "paid": return jsonify({"status": "paid"})
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if not payment: payment = Payment(id=checkout_id, status="paid")
            else: payment.status = "paid"
            db.session.add(payment)
            db.session.commit()
            return jsonify({"status": "paid"})
    except: pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
