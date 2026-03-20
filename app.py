import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Crucial for communication between GitHub Pages (Frontend) and Render (Backend)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuration (Set these in Render Environment Variables) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

# IntaSend API Endpoints
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memory-based tracker for the current session
payments_db = {}

@app.route('/')
def health():
    return jsonify({
        "status": "active",
        "provider": "IntaSend",
        "model": "llama-3.3-70b-versatile"
    }), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "Missing AI API Key"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant") 
        
        # Dynamically inject the right Kenyan legal statutes based on the frontend toggle
        if category == "employment":
            legal_context = "Focus specifically on the Employment Act 2007, the Labour Institutions Act, and the Industrial Court procedures."
        else:
            legal_context = "Focus specifically on the Rent Restriction Act, the Landlord and Tenant (Shops, Hotels and Catering Establishments) Act, and the Distress for Rent Act."
            
        system_prompt = (
            f"You are a strict Kenyan legal expert. {legal_context} "
            "You must return a valid JSON object with exactly two keys: "
            "'free_summary' (a brief overview of rights) and "
            "'paid_deep_dive' (detailed citations, tribunal steps, and legal action plan)."
        )

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        return jsonify(json.loads(completion.choices[0].message.content))
    except Exception as e:
        print(f"AI Generation Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        
        # Phone formatting to 254...
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        # FORCED TO 1 KES FOR TESTING
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 1, 
            "phone_number": phone,
            "email": data.get("email", "user@sheriahub.co.ke"),
            "api_ref": "SheriaHub-Consultation",
        }

        headers = {
            "Authorization": f"Bearer {INTASEND_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = response.json()
        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            payments_db[invoice_id] = "pending"
            return jsonify({"checkout_id": invoice_id})
        
        return jsonify({"error": "M-Pesa request failed", "details": res_data}), 400
        
    except Exception as e:
        print(f"STK Push Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    """IntaSend Webhook Handler"""
    data = request.get_json()
    invoice_id = data.get("invoice_id")
    state = data.get("state") 

    if invoice_id:
        # BUG FIX: Only update to 'paid' if it is complete. Do NOT overwrite with 'failed' on intermediate states.
        if state == "COMPLETE":
            payments_db[invoice_id] = "paid"
            print(f"✅ WEBHOOK SUCCESS: {invoice_id} is now paid")
        else:
            print(f"ℹ️ WEBHOOK UPDATE: {invoice_id} is currently {state}")
        
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    """Refined status check"""
    # 1. If we already know it's paid, return immediately
    status = payments_db.get(checkout_id)
    if status == "paid":
        return jsonify({"status": "paid"})
    
    # 2. Always double-check with IntaSend API if not paid locally
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.status_code == 200:
            api_data = res.json().get("invoice", {})
            api_state = api_data.get("state")
            
            # Use IntaSend's 'COMPLETE' state as the final truth
            if api_state == "COMPLETE":
                payments_db[checkout_id] = "paid"
                return jsonify({"status": "paid"})
            elif api_state in ["FAILED", "CANCELLED"]:
                return jsonify({"status": "failed"})
    except Exception as e:
        print(f"API Check Error: {e}")

    return jsonify({"status": status or "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
