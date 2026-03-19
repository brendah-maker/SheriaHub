import os
import base64
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)

# --- Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
# Use a dictionary to track payment status in memory
payments_db = {}

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")

        persona = "Kenyan Employment Law expert" if category == "employment" else "Kenyan Landlord & Tenant Law expert"
        
        prompt = f"""
        {persona}. Focus on Kenyan statutes. 
        Return ONLY valid JSON: 
        {{
            "free_summary": "2-sentence overview", 
            "paid_deep_dive": "Step-by-step action plan with law citations"
        }}
        Question: {question}
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        return jsonify(json.loads(response.text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        amount = data.get("amount", 20)

        # Standardize phone to 254...
        if phone.startswith("0"): phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"): phone = "254" + phone
        
        # 1. Get OAuth Token
        auth_res = requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", 
                                auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        access_token = auth_res.json().get("access_token")

        # 2. Prepare Password
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        # 3. Request Payload
        stk_payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone,
            "CallBackURL": "https://sheriahub.vercel.app/api/callback", # Replace with your actual domain
            "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Advice Fee"
        }

        res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
                             json=stk_payload, headers={"Authorization": f"Bearer {access_token}"})
        
        res_data = res.json()
        cid = res_data.get("CheckoutRequestID")
        
        if cid:
            payments_db[cid] = "pending"
            return jsonify({"checkout_id": cid})
        return jsonify({"error": "STK Push failed", "details": res_data}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    stk = data.get("Body", {}).get("stkCallback", {})
    cid = stk.get("CheckoutRequestID")
    res_code = stk.get("ResultCode")

    if cid:
        payments_db[cid] = "paid" if res_code == 0 else "failed"
    return jsonify({"ResultCode": 0})

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    status = payments_db.get(checkout_id, "pending")
    return jsonify({"status": status})

if __name__ == '__main__':
    app.run()
