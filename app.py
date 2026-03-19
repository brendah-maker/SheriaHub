import os
import base64
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from google import genai  # Latest 2026 SDK
from google.genai import types

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURATION (Environment Variables)
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

# M-Pesa Sandbox Credentials
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# Initialize Gemini 2.5 Flash
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# In-memory storage for payment status (For production, use Redis or MongoDB)
payments_db = {}

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API 2.5 Online", "region": "Kenya"})

# =========================
# AI LEGAL ENGINE
# =========================
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI Configuration missing"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant") # tenant or employment

        # Dynamic Persona Switch
        if category == "employment":
            persona = "You are a Kenyan Employment Law expert. Focus on the Employment Act 2007, NSSF/NHIF, and Labour Court procedures."
        else:
            persona = "You are a Kenyan Landlord & Tenant Law expert. Focus on the Rent Restriction Act and Tribunal (RTB) procedures."

        prompt = f"""
        {persona}
        Provide a response in strictly valid JSON format.
        {{
          "free_summary": "A high-level 2-sentence legal overview.",
          "paid_deep_dive": "A detailed step-by-step action plan including specific sections of Kenyan law and where to file a case."
        }}
        User Question: {question}
        """

        # Gemini 2.5 Flash Generation
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                temperature=0.3
            )
        )
        
        return jsonify(json.loads(response.text))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================
# M-PESA GATEWAY (SCALED PRICING)
# =========================
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        amount = data.get("amount", 20) # Dynamic amount from frontend (20 or 50)

        # 1. Format Phone Number
        if phone.startswith("0"): 
            phone = "254" + phone[1:]
        elif phone.startswith("7") or phone.startswith("1"):
            phone = "254" + phone

        # 2. Get M-Pesa OAuth Token
        auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        res = requests.get(auth_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        access_token = res.json().get("access_token")

        # 3. Prepare STK Push
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
            "CallBackURL": "https://sheriahub.vercel.app/api/callback", # Update with your Vercel URL
            "AccountReference": "SheriaHub_Legal",
            "TransactionDesc": f"Payment for {amount} KES"
        }

        headers = {"Authorization": f"Bearer {access_token}"}
        stk_res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=stk_payload,
            headers=headers
        )
        
        res_data = stk_res.json()
        checkout_id = res_data.get("CheckoutRequestID")
        
        if checkout_id:
            payments_db[checkout_id] = "pending"
            return jsonify({"checkout_id": checkout_id})
        
        return jsonify({"error": "STK Push failed", "details": res_data}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/callback', methods=['POST'])
def callback():
    # M-Pesa hits this when user enters PIN
    data = request.get_json()
    stk_data = data.get("Body", {}).get("stkCallback", {})
    checkout_id = stk_data.get("CheckoutRequestID")
    result_code = stk_data.get("ResultCode")

    if checkout_id:
        # ResultCode 0 means Success
        payments_db[checkout_id] = "paid" if result_code == 0 else "failed"
        
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

@app.route('/check-payment/<checkout_id>', methods=['GET'])
def check_payment(checkout_id):
    status = payments_db.get(checkout_id, "not_found")
    return jsonify({"status": status})

# For local testing
if __name__ == '__main__':
    app.run(debug=True)
