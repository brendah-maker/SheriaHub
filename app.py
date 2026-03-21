import os
import json
import requests
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
# Open CORS for testing and production
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

# --- 2. API KEYS & URLS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "SANDBOX" if IS_SANDBOX else "LIVE"}), 200

# --- 3. ROBUST AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI not initialized"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        is_paid = False
        credits_left = 0

        # LOOPHOLE FIX: Credit Consumption & Sync
        if checkout_id and checkout_id != "undefined":
            payment = Payment.query.get(checkout_id)
            
            # Auto-repair DB if record is missing but payment is COMPLETE on IntaSend
            if not payment:
                try:
                    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
                    res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
                    if res.json().get("invoice", {}).get("state") == "COMPLETE":
                        payment = Payment(id=checkout_id, status="paid", credits=2)
                        db.session.add(payment)
                        db.session.commit()
                except: pass

            if payment and payment.status == "paid" and payment.credits > 0:
                is_paid = True
                payment.credits -= 1
                credits_left = payment.credits
                db.session.commit()

        law_map = {
            "employment": "Employment Act 2007",
            "land": "Land Act 2012 & Land Registration Act",
            "family": "Children Act 2022, Marriage Act, and Succession Act",
            "traffic": "Traffic Act Cap 403",
            "tenant": "Rent Restriction Act"
        }
        law = law_map.get(category, "Kenyan Law")
            
        prompt = (
            f"You are a Kenyan legal expert specializing in {law}. "
            f"User Question: {question}\n\n"
            "Format your response EXACTLY like this:\n"
            "SUMMARY: [One short sentence explaining the law]\n"
            "DEEP_DIVE: [Detailed markdown analysis with sections and citations]"
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[{"role": "user", "content": prompt}]
        )
        
        full_text = completion.choices[0].message.content
        summary = ""
        deep_dive = ""
        
        # Robust Parsing to prevent 'undefined'
        if "DEEP_DIVE:" in full_text:
            parts = full_text.split("DEEP_DIVE:")
            summary = parts[0].replace("SUMMARY:", "").replace("**", "").strip()
            deep_dive = parts[1].strip()
        else:
            summary = full_text.split('.')[0] + "."
            deep_dive = full_text

        if len(summary) < 5:
            summary = "Analysis generated. Please unlock the deep-dive for full details."

        return jsonify({
            "status": "premium" if is_paid else "free",
            "credits_left": credits_left,
            "summary": summary,
            "content": deep_dive if is_paid else "Payment r
