import os
import json
import base64
import datetime
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from groq import Groq

app = Flask(__name__)
CORS(app)

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# M-Pesa Credentials from Render Env Vars
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# Initialize Groq Client
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Temporary In-Memory Database for Payment Status
payments_db = {}

@app.route('/')
def health():
    # Matches the status check shown in your browser screenshot
    return jsonify({"status": "active", "model": "llama-3.3-70b"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "Missing API Key"}), 500
        
    try:
        data = request.get_json()
        question = data.get("question", "")
        
        # Using verified model ID to stop the 404 error found in your logs
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are a Kenyan legal expert. Return JSON: {'free_summary': '...', 'paid_deep_dive': '...'}"},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )
        return jsonify(json.loads(completion.choices[0].message.content))
    except Exception as e:
        print(f"GROQ ERROR: {str(e)}")
        return jsonify({"error": "AI provider rejected the request. Check model ID."}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        amount = data.get("amount", 20)
        
        # Phone formatting for 254
        if phone.startswith("0"): phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"): phone = "254" + phone
        
        # 1. Get Access Token
        auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        res = requests.get(auth_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        access_token = res.json().get("access_token")
        
        # 2. Prepare STK Push
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
            "TransactionDesc": "Legal Advice Deep Dive"
        }
        
        stk_res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=stk_payload,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        checkout_id = stk_res.json().get("CheckoutRequestID")
        if checkout_id:
            payments_db[checkout_id] = "pending"
            return jsonify({"checkout_id": checkout_id})
        return jsonify({"error": "STK Push failed", "details": stk_res.json()}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    stk = data.get("Body", {}).get("stkCallback", {})
    cid = stk.get("CheckoutRequestID")
    if cid:
        # ResultCode 0 indicates success in Daraja
        payments_db[cid] = "paid" if stk.get("ResultCode") == 0 else "failed"
    return jsonify({"ResultCode": 0})

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    status = payments_db.get(checkout_id, "pending")
    return jsonify({"status": status})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
