import os
import base64
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from groq import Groq

app = Flask(__name__)
CORS(app)

# --- Configuration (Check Render Env Vars for these!) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# Initialize AI Client
client = None
if GROQ_API_KEY:
    try:
        client = Groq(api_key=GROQ_API_KEY)
    except Exception as e:
        print(f"Groq Initialization Error: {e}")

payments_db = {}

@app.route('/')
def home():
    # This helps Render detect the port is open
    return jsonify({"status": "SheriaHub Live", "port": os.environ.get("PORT")}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI client not initialized. Check GROQ_API_KEY."}), 500
        
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        
        persona = "Kenyan Employment Law expert" if category == "employment" else "Kenyan Landlord & Tenant Law expert"
        
        # Standardized Prompt for 2026 Llama Models
        system_prompt = f"""
        You are a {persona}. Return ONLY valid JSON:
        {{
            "free_summary": "2-sentence legal overview.",
            "paid_deep_dive": "detailed steps with Kenyan law citations."
        }}
        """

        completion = client.chat.completions.create(
            model="llama-4-maverick", # Ensure this model name is correct in your Groq console
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )

        return jsonify(json.loads(completion.choices[0].message.content))
    except Exception as e:
        print(f"AI Error: {str(e)}")
        return jsonify({"error": "AI processing failed"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        amount = data.get("amount", 20)

        # Normalize phone to 254...
        if phone.startswith("0"): phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"): phone = "254" + phone
        
        # M-Pesa OAuth
        auth_res = requests.get(
            "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", 
            auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET)
        )
        access_token = auth_res.json().get("access_token")

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        stk_payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone,
            "CallBackURL": "https://sheriahub.onrender.com/api/callback", 
            "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Advice Fee"
        }

        res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=stk_payload, 
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        cid = res.json().get("CheckoutRequestID")
        if cid:
            payments_db[cid] = "pending"
            return jsonify({"checkout_id": cid})
        return jsonify({"error": "M-Pesa request failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    stk = data.get("Body", {}).get("stkCallback", {})
    cid = stk.get("CheckoutRequestID")
    if cid:
        payments_db[cid] = "paid" if stk.get("ResultCode") == 0 else "failed"
    return jsonify({"ResultCode": 0})

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    return jsonify({"status": payments_db.get(checkout_id, "pending")})

if __name__ == '__main__':
    # CRITICAL: Dynamic port binding for Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
