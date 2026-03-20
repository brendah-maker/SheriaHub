import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
# Enable CORS for your GitHub Pages frontend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Database Configuration ---
# On Render, the DATABASE_URL starts with 'postgres://', 
# but SQLAlchemy needs 'postgresql://'. This fix ensures it works.
uri = os.getenv("DATABASE_URL", "sqlite:///test.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define the persistent Payment Table
class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)  # Stores invoice_id
    status = db.Column(db.String(20), default="pending")

# Create the table if it doesn't exist
with app.app_context():
    db.create_all()

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

# IntaSend API Endpoints
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
def health():
    return jsonify({"status": "active", "region": "Kenya", "database": "connected"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI client not initialized"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        # 1. Verify Payment Status from PostgreSQL
        is_paid = False
        if checkout_id:
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid":
                is_paid = True

        # 2. Define Legal Context
        if category == "employment":
            legal_context = "Expert in Kenyan Employment Law (Employment Act 2007)."
        else:
            legal_context = "Expert in Kenyan Tenancy Law (Rent Restriction Act)."
            
        system_prompt = (
            f"You are a {legal_context}. Return ONLY a JSON object. "
            "Structure: {\"free_summary\": \"one sentence\", \"paid_deep_dive\": \"comprehensive markdown\"}"
        )

        # 3. Call AI
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        
        try:
            ai_raw = json.loads(completion.choices[0].message.content)
            summary = ai_raw.get("free_summary", "Summary unavailable.")
            deep_dive = ai_raw.get("paid_deep_dive", "Deep dive unavailable.")
        except:
            summary = "Error parsing AI response."
            deep_dive = "Please contact support."

        # 4. THE GATE
        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": summary,
            "content": deep_dive if is_paid else "Payment required to unlock deep dive."
        })
        
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        
        if phone.startswith("0"): 
            phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"):
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

        response = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = response.json()
        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            # Save pending payment to PostgreSQL
            new_payment = Payment(id=invoice_id, status="pending")
            db.session.add(new_payment)
            db.session.commit()
            return jsonify({"checkout_id": invoice_id})
        
        return jsonify({"error": "M-Pesa push failed", "details": res_data}), 400
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    invoice_id = data.get("invoice_id")
    state = data.get("state") 
    
    if invoice_id and state == "COMPLETE":
        payment = Payment.query.get(invoice_id)
        if payment:
            payment.status = "paid"
            db.session.commit()
            print(f"✅ Payment {invoice_id} updated to PAID in DB")
            
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    payment = Payment.query.get(checkout_id)
    
    if payment and payment.status == "paid":
        return jsonify({"status": "paid"})
    
    # Verification fallback (Check directly with IntaSend)
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if payment:
                payment.status = "paid"
            else:
                payment = Payment(id=checkout_id, status="paid")
                db.session.add(payment)
            db.session.commit()
            return jsonify({"status": "paid"})
    except:
        pass
        
    return jsonify({"status": payment.status if payment else "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
