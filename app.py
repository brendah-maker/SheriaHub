import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Enable CORS for your GitHub Pages frontend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memory-based tracker for payments
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
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id") # Frontend sends this after payment

        # 1. Check Payment Status
        is_paid = False
        if checkout_id and payments_db.get(checkout_id) == "paid":
            is_paid = True

        # 2. Define Legal Context
        if category == "employment":
            legal_context = (
                "You are an expert in Kenyan Employment Law (Employment Act 2007). "
                "Mention the Ministry of Labour and ELRC."
            )
        else:
            legal_context = (
                "You are an expert in Kenyan Tenancy Law (Rent Restriction Act). "
                "Mention the Rent Restriction Tribunal (RRT)."
            )
            
        system_prompt = (
            f"{legal_context} "
            "Return a valid JSON object with exactly two keys: "
            "1. 'free_summary': A STRICT single-sentence summary of the user's rights. "
            "2. 'paid_deep_dive': A comprehensive legal brief with citations, sections, "
            "and a step-by-step action plan. Use professional markdown formatting."
        )

        # 3. Call AI
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        
        ai_response = json.loads(completion.choices[0].message.content)

        # 4. Gating Logic: Only send back what the user has paid for
        if is_paid:
            return jsonify({
                "status": "premium",
                "summary": ai_response.get("free_summary"),
                "content": ai_response.get("paid_deep_dive")
            })
        else:
            return jsonify({
                "status": "free",
                "summary": ai_response.get("free_summary"),
                "content": "Unlock the full legal analysis and citations for KSh 20."
            })
        
    except Exception as e:
        print(f"AI Error: {e}")
        # If this fails, the frontend's 30s timeout will trigger "Request timed out"
        return jsonify({"error": "Failed to generate legal content"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        
        if phone.startswith("0"): 
            phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"):
            phone = "254" + phone
        
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
    data = request.get_json()
    invoice_id = data.get("invoice_id")
    state = data.get("state") 

    if invoice_id and state == "COMPLETE":
        payments_db[invoice_id] = "paid"
        print(f"✅ Payment Verified: {invoice_id}")
    return jsonify({"status": "received"}), 200

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    status = payments_db.get(checkout_id)
    if status == "paid":
        return jsonify({"status": "paid"})
    
    # Verify with API if local memory is out of sync
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.status_code == 200:
            api_state = res.json().get("invoice", {}).get("state")
            if api_state == "COMPLETE":
                payments_db[checkout_id] = "paid"
                return jsonify({"status": "paid"})
    except Exception as e:
        print(f"Check Error: {e}")

    return jsonify({"status": status or "pending"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
