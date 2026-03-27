import os
import json
import requests
import pdfplumber
import io
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
# Enable CORS for your frontend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. DATABASE CONFIGURATION ---
# Works with local SQLite or Render PostgreSQL
uri = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db")
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True) # IntaSend Invoice ID
    status = db.Column(db.String(20), default="pending")
    credits = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

# --- 2. API KEYS & CONFIG ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.environ.get("INTASEND_PUBLISHABLE_KEY", "").strip()
INTASEND_SECRET_KEY = os.environ.get("INTASEND_SECRET_KEY", "").strip()
IS_LIVE = os.environ.get("IS_LIVE", "False").lower() == "true"
BASE_URL = "https://api.intasend.com/api/v1" if IS_LIVE else "https://sandbox.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- 3. HELPER: PHONE FORMATTING ---
def format_phone(phone):
    phone = phone.strip().replace("+", "")
    if phone.startswith("0"):
        return "254" + phone[1:]
    elif (phone.startswith("7") or phone.startswith("1")) and len(phone) == 9:
        return "254" + phone
    return phone

# --- 4. ROUTES ---

@app.route('/')
def health():
    return jsonify({"status": "Logic Foundry Systems Active", "mode": "Live" if IS_LIVE else "Sandbox"}), 200

# NEW: MKATABACHECK (Agreement Audit)
@app.route('/audit-contract', methods=['POST'])
def audit_contract():
    if 'file' not in request.files:
        return jsonify({"error": "No PDF file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        # Extract text from PDF
        with pdfplumber.open(io.BytesIO(file.read())) as pdf:
            contract_text = " ".join([page.extract_text() or "" for page in pdf.pages])

        if len(contract_text.strip()) < 50:
            return jsonify({"analysis": "❌ The document appears to be empty or unreadable. Please upload a clear PDF agreement."})

        # AI Prompt for Contract Safety
        system_msg = (
            "You are an expert Kenyan Legal Auditor. Analyze the provided contract text for: "
            "1. ILLEGAL CLAUSES (Violations of Kenyan Law e.g Employment Act 2007, Tenancy Law). "
            "2. HIDDEN RISKS (Unfair penalties or compounding interest). "
            "3. TERMINATION TERMS (Is the notice period fair?). "
            "Provide a professional report in clear sections."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Audit this contract: {contract_text[:5000]}"}
            ],
            temperature=0.1
        )
        
        return jsonify({"analysis": completion.choices[0].message.content})

    except Exception as e:
        print(f"AUDIT ERROR: {e}")
        return jsonify({"error": "Failed to process the document audit."}), 500

# STANDARD LEGAL Q&A
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI client not ready"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        is_paid = False
        credits_left = 0

        # Check Payment & Credits
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        system_msg = (
            f"You are a Kenyan legal expert specializing in {category.replace('_', ' ')}. "
            "Follow these rules strictly:\n"
            "1. Start with 'SUMMARY: ' followed by a 2-sentence simple overview. No Act citations here.\n"
            "2. Then write 'DEEP_DIVE: ' followed by the technical legal details (Acts, Sections, Court Procedures)."
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
        deep_dive = parts[1].strip() if len(parts) > 1 else full_text

        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if is_paid else "🔒 Deep-dive locked. Pay KSh 20 to unlock legal citations and procedures."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# PAYMENT: STK PUSH
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = format_phone(data.get("phone", ""))
        
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 20, 
            "phone_number": phone, 
            "api_ref": "SheriaHub"
        }
        headers = {
            "Authorization": f"Bearer {INTASEND_SECRET_KEY}", 
            "Content-Type": "application/json"
        }
        
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = res.json()
        
        inv_id = res_data.get("invoice", {}).get("invoice_id")
        if inv_id:
            db.session.add(Payment(id=inv_id, status="pending", credits=0))
            db.session.commit()
            return jsonify({"checkout_id": inv_id})
        
        return jsonify({"error": "M-Pesa rejected the request"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# PAYMENT: STATUS CHECK
@app.route('/check-payment/<id>')
def check_payment(id):
    p = Payment.query.get(id)
    if p and p.status == "paid": 
        return jsonify({"status": "paid", "credits": p.credits})
    
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{id}/", headers=headers)
        state = res.json().get("invoice", {}).get("state")
        
        if state == "COMPLETE":
            if not p:
                p = Payment(id=id, status="paid", credits=2)
                db.session.add(p)
            else:
                p.status = "paid"
                p.credits = 2
            db.session.commit()
            return jsonify({"status": "paid", "credits": 2})
    except: pass
    
    return jsonify({"status": "pending"})

# WEBHOOK (For production reliability)
@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    inv_id = data.get("invoice_id")
    if inv_id and data.get("state") == "COMPLETE":
        p = Payment.query.get(inv_id)
        if not p:
            db.session.add(Payment(id=inv_id, status="paid", credits=2))
        else:
            p.status = "paid"
            p.credits = 2
        db.session.commit()
    return jsonify({"ok": True}), 200

if __name__ == '__main__':
    # Render dynamic port binding
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
