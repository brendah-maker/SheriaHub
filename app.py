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
CORS(app)

# --- DATABASE ---
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

# --- API KEYS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY)

# --- AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        # Check if it's a file upload (MkatabaCheck) or a text question
        category = request.form.get("category", "tenant")
        question = request.form.get("question", "")
        checkout_id = request.form.get("checkout_id")
        
        contract_text = ""
        if 'contract_file' in request.files:
            file = request.files['contract_file']
            with pdfplumber.open(io.BytesIO(file.read())) as pdf:
                contract_text = " ".join([page.extract_text() or "" for page in pdf.pages])

        # Credit System Logic
        is_paid = False
        credits_left = 0
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        # System Prompt logic based on Category
        if category == "contract_audit":
            system_msg = (
                "You are an expert Kenyan Contract Lawyer. Analyze the provided agreement for:\n"
                "1. ILLEGAL CLAUSES: Does it violate Kenyan laws (Employment Act, Tenancy Act, etc.)?\n"
                "2. HIDDEN COSTS: Are there compounding interests or unfair penalties?\n"
                "3. TERMINATION TRAPS: Is the exit strategy unfair?\n\n"
                "Return ONLY JSON: { 'summary': 'short overview', 'red_flags': ['list of risks'], 'legal_counsel': 'full advice' }"
            )
            user_input = f"CONTRACT TEXT: {contract_text[:4000]}"
        else:
            system_msg = "You are a Kenyan legal expert. Start with 'SUMMARY: ' then 'DEEP_DIVE: '."
            user_input = question

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_input}],
            response_format={"type": "json_object"} if category == "contract_audit" else None
        )
        
        raw_res = completion.choices[0].message.content

        if category == "contract_audit":
            data = json.loads(raw_res)
            return jsonify({
                "status": "premium" if is_paid else "free",
                "credits_left": credits_left,
                "summary": data.get("summary"),
                "red_flags": data.get("red_flags"),
                "content": data.get("legal_counsel") if is_paid else "🔒 Deep-Dive Locked. Pay 20/- to unlock full legal counsel."
            })
        
        # Standard Legal Question Logic
        parts = raw_res.split("DEEP_DIVE:")
        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": parts[0].replace("SUMMARY:", "").strip(),
            "content": parts[1].strip() if is_paid else "🔒 Detailed section locked."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# (Keep your existing stkpush, check_payment, and callback routes exactly as they were)
