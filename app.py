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
# Crucial for cross-origin requests from GitHub Pages
CORS(app, resources={r"/*": {"origins": "*"}})

# Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# This is our payment tracker
payments_db = {}

@app.route('/')
def health():
    return jsonify({"model": "llama-3.3-70b", "status": "active"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "Missing API Key"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
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
        return jsonify({"error": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        # Get Token
        auth_res = requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        access_token = auth_res.json().get("access_token")
        
        # Prepare STK
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()
        
        stk_payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": 1, # Testing with 1 bob
            "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone,
            "CallBackURL": "https://sheriahub.onrender.com/api/callback",
            "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Advice"
        }
        
        res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", 
                            json=stk_payload, 
                            headers={"Authorization": f"Bearer {access_token}"})
        
        checkout_id = res.json().get("CheckoutRequestID")
        if checkout_id:
            payments_db[checkout_id] = "pending"
            return jsonify({"checkout_id": checkout_id})
        return jsonify({"error": "M-Pesa rejected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    # This matches your log entry
    data = request.get_json()
    stk = data.get("Body", {}).get("stkCallback", {})
    cid = stk.get("CheckoutRequestID")
    code = stk.get("ResultCode")
    
    if cid:
        payments_db[cid] = "paid" if code == 0 else "failed"
        print(f"Update: {cid} is now {payments_db[cid]}") # View this in Render Logs
        
    return jsonify({"ResultCode": 0})

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    # Retrieve status from the global dictionary
    status = payments_db.get(checkout_id, "pending")
    return jsonify({"status": status})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
