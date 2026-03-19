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

# --- Configuration ---
# Ensure these are set in your Render Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
payments_db = {}

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub Live", "engine": "Llama 4 Maverick"}), 200

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "API Key missing"}), 500
        
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        
        persona = "Kenyan Employment Law expert" if category == "employment" else "Kenyan Landlord & Tenant Law expert"
        
        system_prompt = f"""
        You are a {persona}. Focus strictly on Kenyan statutes. 
        Return ONLY valid JSON with exactly these two keys:
        "free_summary": "2-sentence legal overview",
        "paid_deep_dive": "detailed citations and action plan"
        """

        completion = client.chat.completions.create(
            model="llama-4-maverick",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            response_format={"type": "json_object"}
        )

        ai_response = json.loads(completion.choices[0].message.content)
        
        return jsonify({
            "free_summary": ai_response.get("free_summary", "Summary unavailable."),
            "paid_deep_dive": ai_response.get("paid_deep_dive", "Detailed plan unavailable.")
        })
    except Exception as e:
        return jsonify({"error": "Failed to reach AI"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        amount = data.get("amount", 20)

        if phone.startswith("0"): phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"): phone = "254" + phone
        
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
            "TransactionDesc": "Legal Fee"
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
        return jsonify({"error": "STK failed"}), 400
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
