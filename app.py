import os
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- DATABASE CONFIG ---
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
    is_unlimited_game = db.Column(db.Boolean, default=False)

class GameSession(db.Model):
    ip_address = db.Column(db.String(50), primary_key=True)
    daily_count = db.Column(db.Integer, default=0)
    last_played = db.Column(db.Date, default=datetime.utcnow().date())

with app.app_context():
    db.create_all()
    # Migration helper for new column
    try:
        db.session.execute(text("ALTER TABLE payment ADD COLUMN is_unlimited_game BOOLEAN DEFAULT FALSE"))
        db.session.commit()
    except: db.session.rollback()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "False").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- KANJO GAME LOGIC ---
@app.route('/generate-kanjo', methods=['POST'])
def generate_kanjo():
    data = request.get_json() or {}
    user_ip = request.remote_addr
    checkout_id = data.get("checkout_id")
    
    # Check if user has paid for unlimited
    unlimited = False
    if checkout_id:
        p = Payment.query.get(checkout_id)
        if p and p.status == "paid" and p.is_unlimited_game:
            unlimited = True

    if not unlimited:
        today = datetime.utcnow().date()
        sess = GameSession.query.get(user_ip)
        if not sess:
            sess = GameSession(ip_address=user_ip, daily_count=0, last_played=today)
            db.session.add(sess)
        
        if sess.last_played < today:
            sess.daily_count = 0
            sess.last_played = today
        
        if sess.daily_count >= 10:
            return jsonify({"error": "limit_reached", "message": "You've exhausted your 10 daily survival attempts!"}), 403
        
        sess.daily_count += 1
        db.session.commit()

    prompt = (
        "Generate a funny 'Kanjo Chronicles' Nairobi survival scenario. "
        "Focus on hawkers, pedestrians, or motorists facing 'unpredictable' City Council officers. "
        "Return ONLY JSON: {'scenario': '...', 'choice_a': '...', 'choice_b': '...', 'choice_c': '...', "
        "'outcome_a': '...', 'outcome_b': '...', 'outcome_c': '...', 'correct_choice': 'C'}"
    )
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return completion.choices[0].message.content

# --- EXISTING ASK-AI LOGIC (Keep as is) ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    # ... (Your existing ask_ai code here) ...
    pass 

# --- UPDATED PAYMENT ROUTES FOR GAME ---
@app.route('/stkpush-game', methods=['POST'])
def stk_push_game():
    data = request.get_json()
    phone = data.get("phone", "").replace("+", "")
    if phone.startswith("0"): phone = "254" + phone[1:]
    payload = {"public_key": INTASEND_PUBLISHABLE_KEY, "amount": 20, "phone_number": phone, "api_ref": "KanjoUnlimited"}
    headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
    res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
    inv_id = res.json().get("invoice", {}).get("invoice_id")
    if inv_id:
        db.session.add(Payment(id=inv_id, status="pending", is_unlimited_game=True))
        db.session.commit()
        return jsonify({"checkout_id": inv_id})
    return jsonify({"error": "Failed"}), 400

# ... (Include your existing /check-payment and /health routes) ...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
