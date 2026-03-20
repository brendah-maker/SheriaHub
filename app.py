import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuration (Set these in Render Environment Variables) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
payments_db = {}

@app.route('/')
def health():
    return jsonify({"status": "active", "model": "llama-3.3-70b"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "Missing AI API Key"}), 500
    try:
        data = request.get_json()
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are a Kenyan legal expert. Return JSON: {'free_summary': '...', 'paid_deep_dive': '...'}"},
                {"role": "user", "content": data.get("question", "")}
            ],
            response_format={"type": "json_object"}
        )
        return jsonify(json.loads(completion.choices[0].message.content))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        # FORCED TO 1 KES FOR TESTING
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 1, 
            "phone_number": phone,
            "email": "user@sheriahub.co.ke",
            "api_ref": "SheriaHub-Consultation",
        }

        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        response = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = response.json()
        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            payments_db[invoice_id] = "pending"
            return jsonify({"checkout_id": invoice_id})
        return jsonify({"error": "Failed", "details": res_data}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    invoice_id = data.get("invoice_id")
    state = data.get("state") 
    if invoice_id:
        payments_db[invoice_id] = "paid" if state == "COMPLETE" else "failed"
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    status = payments_db.get(checkout_id)
    if status == "paid":
        return jsonify({"status": "paid"})
    
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.status_code == 200:
            api_state = res.json().get("invoice", {}).get("state")
            if api_state == "COMPLETE":
                payments_db[checkout_id] = "paid"
                return jsonify({"status": "paid"})
            elif api_state in ["FAILED", "CANCELLED"]:
                return jsonify({"status": "failed"})
    except:
        pass
    return jsonify({"status": status or "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
