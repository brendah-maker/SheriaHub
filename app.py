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

# =========================
# CONFIGURATION
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

# M-Pesa Sandbox Credentials
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# =========================
# AI INITIALIZATION (2026 SDK)
# =========================
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
payments = {} # Temporary store for demo/testing

@app.route('/')
def health():
    return jsonify({"status": "SheriaHub 2026 Online", "model": "Gemini 2.5 Flash"})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI not configured"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "")

        prompt = f"""
        Role: Kenyan Legal Expert (Rent Restriction Act).
        Return ONLY valid JSON. No markdown.
        {{
          "free_summary": "2-sentence legal overview.",
          "paid_deep_dive": "Full legal steps and citations."
        }}
        Question: {question}
        """

        # Gemini 2.5 Flash is the 2026 stable workhorse
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                temperature=0.2
            )
        )
        
        return jsonify(json.loads(response.text))
    except Exception as e:
        return jsonify({"free_summary": "System busy.", "paid_deep_dive": str(e)})

# =========================
# M-PESA STK PUSH LOGIC
# =========================
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]

        # Get OAuth Token
        auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        auth_res = requests.get(auth_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        token = auth_res.json().get("access_token")

        # Payload
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        stk_payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": 1,
            "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone,
            "CallBackURL": "https://sheriahub.onrender.com/callback",
            "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Info"
        }

        res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=stk_payload,
            headers={"Authorization": f"Bearer {token}"}
        )
        
        checkout_id = res.json().get("CheckoutRequestID")
        if checkout_id:
            payments[checkout_id] = "pending"
            return jsonify({"checkout_id": checkout_id})
        return jsonify({"error": "Failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/callback', methods=['POST'])
def callback():
    data = request.get_json()
    stk = data.get("Body", {}).get("stkCallback", {})
    cid = stk.get("CheckoutRequestID")
    if cid:
        payments[cid] = "paid" if stk.get("ResultCode") == 0 else "failed"
    return jsonify({"ResultCode": 0})

@app.route('/check-payment/<cid>')
def check(cid):
    return jsonify({"status": payments.get(cid, "not_found")})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
