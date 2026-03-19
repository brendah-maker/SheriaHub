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

# Configuration - Ensure these are in Render Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
payments_db = {}

@app.route('/')
def health():
    return jsonify({"status": "SheriaHub Backend Live", "engine": "Llama-3.3"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI client missing"}), 500
        
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        persona = "Kenyan Employment Law expert" if category == "employment" else "Kenyan Landlord & Tenant Law expert"
        
        # CHANGED: Using a verified active model ID to fix the 404 error
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": f"You are a {persona}. Return ONLY JSON with 'free_summary' and 'paid_deep_dive'."},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        return jsonify(json.loads(completion.choices[0].message.content))
    except Exception as e:
        print(f"AI ERROR: {str(e)}") # This will show in Render logs
        return jsonify({"error": "Sheria AI is temporarily overloaded. Please try again."}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        amount = data.get("amount", 20)
        if phone.startswith("0"): phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"): phone = "254" + phone
        
        auth_res = requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        access_token = auth_res.json().get("access_token")
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        stk_payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE, "Password": password, "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline", "Amount": int(amount), "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE, "PhoneNumber": phone, "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Advice", "CallBackURL": "https://sheriahub.onrender.com/api/callback"
        }
        res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=stk_payload, headers={"Authorization": f"Bearer {access_token}"})
        cid = res.json().get("CheckoutRequestID")
        if cid:
            payments_db[cid] = "pending"
            return jsonify({"checkout_id": cid})
        return jsonify({"error": "M-Pesa rejected request"}), 400
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
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
