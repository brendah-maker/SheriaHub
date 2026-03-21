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

uri = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(20), default="pending")

with app.app_context():
    db.create_all()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/health')
def health():
    return jsonify({"status": "Online"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        # --- PREVENT DOUBLE PAYMENT CHECK ---
        is_paid = False
        if checkout_id and checkout_id != "undefined":
            # 1. Check local DB
            p = Payment.query.get(checkout_id)
            if p and p.status == "paid":
                is_paid = True
            else:
                # 2. Re-verify with IntaSend API just in case
                try:
                    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
                    res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
                    if res.json().get("invoice", {}).get("state") == "COMPLETE":
                        is_paid = True
                        if not p: db.session.add(Payment(id=checkout_id, status="paid"))
                        else: p.status = "paid"
                        db.session.commit()
                except: pass

        law_map = {
            "employment": "Employment Act 2007",
            "land": "Land Act 2012",
            "family": "Children Act 2022 & Marriage Act",
            "traffic": "Traffic Act Cap 403",
            "tenant": "Rent Restriction Act"
        }
        
        # We removed "response_format=json" to prevent the 400 Error in your logs
        prompt = (
            f"You are a Kenyan legal expert on {law_map.get(category)}. "
            f"User Question: {question}\n\n"
            "Provide your response in this EXACT format:\n"
            "SUMMARY: [One short sentence]\n"
            "DEEP_DIVE: [Detailed markdown with sections and citations]"
        )

        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        
        response_text = chat_completion.choices[0].message.content
        
        # Simple parsing logic
        summary = "Summary unavailable"
        deep_dive = "Details unavailable"
        
        if "SUMMARY:" in response_text and "DEEP_DIVE:" in response_text:
            parts = response_text.split("DEEP_DIVE:")
            summary = parts[0].replace("SUMMARY:", "").strip()
            deep_dive = parts[1].strip()
        else:
            summary = response_text[:100] + "..."
            deep_dive = response_text

        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": summary,
            "content": deep_dive if is_paid else "Payment required to unlock deep dive."
        })

    except Exception as e:
        print(f"🔥 ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# Payment routes remain the same, adding the callback fix
@app.route('/stkpush', methods=['POST'])
def stk_push():
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
    return jsonify({"error": "Failed"}), 400

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
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
