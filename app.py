import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
# Allow all origins for testing/Vercel
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

# --- Initialize Database ---
with app.app_context():
    db.create_all()

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "healthy", "mode": "LIVE" if not IS_SANDBOX else "SANDBOX"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        # --- Check if user has already paid ---
        is_paid = False
        if checkout_id and checkout_id != "undefined":
            # Check local DB
            payment_record = Payment.query.get(checkout_id)
            if payment_record and payment_record.status == "paid":
                is_paid = True
            else:
                # Re-verify with IntaSend API (backup sync)
                try:
                    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
                    res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
                    if res.json().get("invoice", {}).get("state") == "COMPLETE":
                        is_paid = True
                        if not payment_record:
                            db.session.add(Payment(id=checkout_id, status="paid"))
                        else:
                            payment_record.status = "paid"
                        db.session.commit()
                except: pass

        law_map = {
            "employment": "Employment Act 2007",
            "land": "Land Act 2012",
            "family": "Children Act 2022 & Marriage Act",
            "traffic": "Traffic Act Cap 403",
            "tenant": "Rent Restriction Act"
        }
        
        # Simpler prompt to avoid AI generation errors
        prompt = (
            f"You are a Kenyan legal expert on {law_map.get(category, 'Kenyan Law')}. "
            f"Question: {question}\n\n"
            "Respond exactly in this format:\n"
            "SUMMARY: [One sentence overview]\n"
            "DEEP_DIVE: [Detailed legal analysis with markdown]"
        )

        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        
        full_text = chat_completion.choices[0].message.content
        
        # Smart splitting of AI response
        if "DEEP_DIVE:" in full_text:
            parts = full_text.split("DEEP_DIVE:")
            summary = parts[0].replace("SUMMARY:", "").strip()
            deep_dive = parts[1].strip()
        else:
            summary = full_text[:150] + "..."
            deep_dive = full_text

        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": summary,
            "content": deep_dive if is_paid else "🔒 Payment required to unlock full analysis."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "SheriaHub"}
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = res.json()
        
        inv_id = res_data.get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending"))
            db.session.commit()
            return jsonify({"checkout_id": inv_id})
        return jsonify({"error": "M-Pesa rejected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    inv_id = data.get("invoice_id")
    if inv_id and data.get("state") == "COMPLETE":
        p = Payment.query.get(inv_id)
        if not p: db.session.add(Payment(id=inv_id, status="paid"))
        else: p.status = "paid"
        db.session.commit()
    return jsonify({"ok": True}), 200

@app.route('/check-payment/<id>')
def check(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": return jsonify({"status": "paid"})
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            if not p: db.session.add(Payment(id=id, status="paid"))
            else: p.status = "paid"
            db.session.commit()
            return jsonify({"status": "paid"})
    except: pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
