import os
import base64
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from google import genai  # 2026 Standard SDK
from google.genai import types

app = Flask(__name__)
CORS(app)

# --- Config ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# --- AI Client ---
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
payments = {} 

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI Keys Missing"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        prompt = f"""
        Role: Kenyan Legal Expert (Tenant/Landlord Law).
        Return ONLY valid JSON.
        {{
          "free_summary": "Short 2-sentence legal overview.",
          "paid_deep_dive": "Full legal steps with Kenyan law citations."
        }}
        Question: {question}
        """
        # Switching to the 2026 stable workhorse: gemini-2.5-flash
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json')
        )
        return jsonify(json.loads(response.text))
    except Exception as e:
        return jsonify({"free_summary": "System error.", "paid_deep_dive": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]

        auth_res = requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", 
                                auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        token = auth_res.json().get("access_token")

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE, "Password": password, "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline", "Amount": 1, "PartyA": phone, "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone, "CallBackURL": "https://sheriahub.onrender.com/callback",
            "AccountReference": "SheriaHub", "TransactionDesc": "Legal Info"
        }

        res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", 
                             json=payload, headers={"Authorization": f"Bearer {token}"})
        
        cid = res.json().get("CheckoutRequestID")
        if cid:
            payments[cid] = "pending"
            return jsonify({"checkout_id": cid})
        return jsonify({"error": "Push failed"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/callback', methods=['POST'])
def callback():
    data = request.get_json()
    stk = data.get("Body", {}).get("stkCallback", {})
    cid = stk.get("CheckoutRequestID")
    if cid: payments[cid] = "paid" if stk.get("ResultCode") == 0 else "failed"
    return jsonify({"ResultCode": 0})

@app.route('/check-payment/<cid>')
def check(cid):
    return jsonify({"status": payments.get(cid, "not_found")})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
