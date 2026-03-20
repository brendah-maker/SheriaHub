import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Enable CORS for all routes to handle requests from your GitHub Pages frontend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

# IntaSend API Endpoints
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memory-based tracker (Note: restarts wipe this; consider a DB for production)
payments_db = {}

@app.route('/')
def health():
    return jsonify({
        "status": "active",
        "provider": "IntaSend",
        "model": "llama-3.3-70b-versatile",
        "region": "Kenya"
    }), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI client not initialized"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant") # Default to tenant
        
        # Define high-authority legal contexts
        if category == "employment":
            legal_context = (
                "You are an expert in Kenyan Employment Law. Use the Employment Act 2007, "
                "Regulation of Wages and Conditions of Employment Act, and the Labour Institutions Act. "
                "Mention the Ministry of Labour and the Employment and Labour Relations Court (ELRC)."
            )
        else:
            legal_context = (
                "You are an expert in Kenyan Property and Tenancy Law. Use the Rent Restriction Act, "
                "Landlord and Tenant (Shops, Hotels and Catering Establishments) Act, and the Distress for Rent Act. "
                "Mention the Rent Restriction Tribunal (RRT) and the Business Premises Rent Tribunal (BPRT)."
            )
            
        system_prompt = (
            f"{legal_context} "
            "You must return a valid JSON object with exactly two keys: "
            "1. 'free_summary': A high-level, 3-sentence explanation of the user's rights. "
            "2. 'paid_deep_dive': A comprehensive, high-value legal brief. This must include: "
            "   - Specific Section citations from Kenyan law. "
            "   - A step-by-step Action Plan (e.g., how to draft a demand letter). "
            "   - Specific Tribunal or Office locations for filing complaints. "
            "   - Possible outcomes and timelines. Make this content rich enough to justify a KSh 20 payment."
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
        print(f"AI Error: {e}")
        return jsonify({"error": "Failed to generate legal content"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        
        # Ensure 254 format
        if phone.startswith("0"): 
            phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"):
            phone = "254" + phone
        
        # KSh 20 charge for the deep dive
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 20, 
            "phone_number": phone,
            "email": "user@sheriahub.co.ke",
            "api_ref": "SheriaHub-Premium",
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
        
        return jsonify({"error": "Could not initiate M-Pesa push", "details": res_data}), 400
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    """Receives payment updates from IntaSend Webhook"""
    data = request.get_json()
    invoice_id = data.get("invoice_id")
    state = data.get("state") 

    if invoice_id and state == "COMPLETE":
        payments_db[invoice_id] = "paid"
        print(f"✅ Payment Verified: {invoice_id}")
    elif invoice_id:
        print(f"ℹ️ Transaction Update: {invoice_id} is {state}")
        
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    """Checks if the payment was successful"""
    # Check local memory first
    status = payments_db.get(checkout_id)
    if status == "paid":
        return jsonify({"status": "paid"})
    
    # Backup: Double-check directly with IntaSend API
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
    except Exception as e:
        print(f"Check Error: {e}")

    return jsonify({"status": status or "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
