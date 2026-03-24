import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
CORS(app)

# --- 1. DATABASE CONFIG ---
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
        db.session.execute(text("SELECT credits FROM payment LIMIT 1"))
    except:
        db.session.execute(text("ALTER TABLE payment ADD COLUMN credits INTEGER DEFAULT 0"))
        db.session.commit()

# --- 2. KEYS & CLIENTS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY)

# --- 3. AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.get_json()
    question = data.get("question", "")
    category = data.get("category", "tenant")
    checkout_id = data.get("checkout_id")

    is_paid = False
    credits_left = 0

    # Check for credits
    if checkout_id and checkout_id != "null":
        payment = Payment.query.get(checkout_id)
        if payment and payment.status == "paid" and payment.credits > 0:
            is_paid = True
            payment.credits -= 1
            credits_left = payment.credits
            db.session.commit()

    # System Prompts
    if category == "kanjo":
        system_msg = "You are 'Kanjo-GPT'. Create a Nairobi street survival scenario with options A, B, C. Be fast-paced and use Kenyan street slang occasionally. Explain the bylaws if they pick an option."
    else:
        system_msg = f"You are a Kenyan legal expert on {category}. 1. Start with 'SUMMARY: ' (1-2 sentences, NO section numbers). 2. Then 'DEEP_DIVE: ' (Full legal acts and sections)."

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": question}]
        )
        full_text = completion.choices[0].message.content

        # Handle Gating
        if category == "kanjo":
            return jsonify({"status": "premium", "summary": full_text, "content": ""})
        
        if "DEEP_DIVE:" in full_text:
            parts = full_text.split("DEEP_DIVE:")
            summary = parts[0].replace("SUMMARY:", "").strip()
            deep_dive = parts[1].strip()
        else:
            summary = full_text
            deep_dive = full_text

        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if is_paid else "🔒 Pay KSh 20 to unlock specific Acts and Sections."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 4. PAYMENT ROUTES ---
@app.route('/stkpush', methods=['POST'])
def stk_push():
    data = request.get_json()
    phone = data.get("phone", "").strip()
    if phone.startswith("0"): phone = "254" + phone[1:]
    
    payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
    
    res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
    inv_id = res.json().get("invoice", {}).get("invoice_id")
    
    if inv_id:
        db.session.add(Payment(id=inv_id, status="pending", credits=0))
        db.session.commit()
        return jsonify({"checkout_id": inv_id})
    return jsonify({"error": "Failed"}), 400

@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid", "credits": p.credits})
    
    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
    res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
    if res.json().get("invoice", {}).get("state") == "COMPLETE":
        if not p: p = Payment(id=id, status="paid", credits=2)
        else: p.status = "paid"; p.credits = 2
        db.session.commit()
        return jsonify({"status": "paid", "credits": 2})
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
