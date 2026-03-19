import os
import base64
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from google import genai  # Modern 2026 SDK

# =========================
# APP CONFIG
# =========================
app = Flask(__name__)
CORS(app)

# Environment Variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

# M-Pesa Constants
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# =========================
# AI INITIALIZATION
# =========================
client = None
if GEMINI_API_KEY:
    try:
        # Initialize the modern Gemini Client
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Sheria AI Initialized with Gemini 2.0 Flash")
    except Exception as e:
        print(f"❌ AI Init Error: {e}")

# In-memory storage for payment tracking
payments = {}

# =========================
# ROUTES
# =========================

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API Online", "ai_ready": client is not None})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI client not initialized"}), 500

    try:
        data = request.get_json()
        question = data.get("question", "")
        
        prompt = f"""
        Act as a Kenyan Landlord/Tenant legal expert. 
        Focus on: Rent Restriction Act & Landlord/Tenant Bill 2021.
        Return ONLY valid JSON with no markdown:
        {{
          "free_summary": "Short 2-3 sentence legal overview.",
          "paid_deep_dive": "Step-by-step legal procedure with law citations."
        }}
        Question: {question}
        """

        # Calling Gemini 2.0 Flash (1.5 is likely 404 because it's retired)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        
        # Clean response text (remove ```json wrappers if present)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return jsonify(json.loads(text))

    except Exception as e:
        print(f"❌ AI Route Error: {str(e)}")
        return jsonify({
            "free_summary": "Sheria AI is temporarily offline.",
            "paid_deep_dive": f"Error: {str(e)}"
        })

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]

        # Get Token
        auth_url = "[https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials](https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials)"
        auth_res = requests.get(auth_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        token = auth_res.json().get("access_token")

        # Prepare STK
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
            "CallBackURL": "[https://sheriahub.onrender.com/callback](https://sheriahub.onrender.com/callback)",
            "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Advice"
        }

        headers = {"Authorization": f"Bearer {token}"}
        res = requests.post("[https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest](https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest)", json=stk_payload, headers=headers)
        res_data = res.json()
        
        checkout_id = res_data.get("CheckoutRequestID")
        if checkout_id:
            payments[checkout_id] = {"status": "pending"}
            return jsonify({"checkout_id": checkout_id})
        
        return jsonify({"error": "STK Push failed", "details": res_data}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/callback', methods=['POST'])
def callback():
    data = request.get_json(force=True)
    try:
        stk = data["Body"]["stkCallback"]
        cid = stk["CheckoutRequestID"]
        code = stk["ResultCode"]
        if cid in payments:
            payments[cid]["status"] = "paid" if code == 0 else "failed"
    except: pass
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

@app.route('/check-payment/<checkout_id>')
def check_status(checkout_id):
    return jsonify(payments.get(checkout_id, {"status": "not_found"}))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
