import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Allows your GitHub Pages frontend to communicate with this Render backend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuration (Set these in Render Environment Variables) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")  # The 'API Token' from IntaSend
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

# IntaSend API Endpoints
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Ephemeral payment tracker (Note: This resets if Render service restarts)
payments_db = {}

@app.route('/')
def health():
    return jsonify({
        "status": "active",
        "provider": "IntaSend",
        "environment": "sandbox" if IS_SANDBOX else "production",
        "model": "llama-3.3-70b"
    }), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "Missing AI API Key"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are a Kenyan legal expert. Return a JSON object with two keys: 'free_summary' (concise advice) and 'paid_deep_dive' (detailed breakdown)."},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        # Parse the JSON string from Groq's response
        response_content = json.loads(completion.choices[0].message.content)
        return jsonify(response_content)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        
        # Phone formatting (Ensure it starts with 254)
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        # IntaSend requires an email and amount
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": data.get("amount", 1), # Default 10 KES for testing
            "phone_number": phone,
            "email": data.get("email", "user@sheriahub.co.ke"),
            "api_ref": "SheriaHub-Consultation",
        }

        headers = {
            "Authorization": f"Bearer {INTASEND_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        # IntaSend STK Push Endpoint
        response = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = response.json()

        # IntaSend returns an 'invoice' object containing the ID
        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            payments_db[invoice_id] = "pending"
            return jsonify({"checkout_id": invoice_id})
        
        return jsonify({"error": "M-Pesa request failed", "details": res_data}), 400
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    """IntaSend Webhook Handler"""
    data = request.get_json()
    
    # IntaSend sends invoice_id and state (COMPLETE/FAILED)
    invoice_id = data.get("invoice_id")
    state = data.get("state") 

    if invoice_id:
        payments_db[invoice_id] = "paid" if state == "COMPLETE" else "failed"
        print(f"Payment Update: {invoice_id} is now {payments_db[invoice_id]}")
        
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    """Checks the payment status, falling back to IntaSend API if not in memory"""
    status = payments_db.get(checkout_id)
    
    # If the app restarted and memory is empty, ask IntaSend directly
    if not status:
        try:
            headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
            res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
            if res.status_code == 200:
                state = res.json().get("invoice", {}).get("state")
                status = "paid" if state == "COMPLETE" else "pending"
        except:
            status = "pending"

    return jsonify({"status": status or "pending"})

if __name__ == '__main__':
    # Render dynamic port binding
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
