import os
import base64
import datetime
import requests
import json
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
import google.generativeai as genai

# =========================
# APP SETUP
# =========================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =========================
# ENV VARIABLES
# =========================
# Set these in your Render/Local Environment
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Safaricom Sandbox Credentials
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# =========================
# INIT AI
# =========================
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
else:
    model = None

# =========================
# TEMP STORAGE
# =========================
# Keys are CheckoutRequestIDs from Safaricom
payments = {}  
chat_history = {}

# =========================
# HELPERS
# =========================
def get_access_token():
    try:
        url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        res = requests.get(url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        if res.status_code == 200:
            return res.json().get("access_token")
        return None
    except Exception as e:
        print(f"Token Error: {e}")
        return None

def format_phone(phone):
    """Converts 07... or +254... to 2547..."""
    phone = str(phone).strip().replace("+", "")
    if phone.startswith("0"):
        return "254" + phone[1:]
    return phone

# =========================
# ROUTES
# =========================

@app.route('/')
def home():
    return jsonify({
        "status": "SheriaHub API is active",
        "ai_ready": bool(GEMINI_API_KEY)
    })

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        data = request.get_json()
        question = data.get("question", "")

        if not model:
            return jsonify({"error": "AI not configured"}), 500

        prompt = f"""
        You are a Kenyan legal expert. Answer the following based on the Rent Restriction Act and Landlord/Tenant Bill 2021.
        Return ONLY valid JSON.
        {{
          "free_summary": "Short 2-sentence summary",
          "paid_deep_dive": "Detailed legal steps and tribunal process"
        }}
        Question: {question}
        """

        response = model.generate_content(prompt)
        # Clean JSON markdown if present
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return jsonify(json.loads(clean_text))

    except Exception as e:
        return jsonify({"free_summary": "Error processing request.", "paid_deep_dive": str(e)})

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = format_phone(data.get("phone"))
        amount = 1 # Keep it 1 for testing sandbox

        access_token = get_access_token()
        if not access_token:
            return jsonify({"error": "M-Pesa Auth Failed"}), 401

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone,
            "CallBackURL": "https://sheriahub.onrender.com/callback",
            "AccountReference": "SheriaHub",
            "TransactionDesc": "Legal Consultation"
        }

        res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        res_data = res.json()
        checkout_id = res_data.get("CheckoutRequestID")

        if checkout_id:
            # We track by CheckoutRequestID because that's what the callback sends
            payments[checkout_id] = {"status": "pending", "phone": phone}
            return jsonify({"checkout_id": checkout_id, "message": "STK Push sent"})
        
        return jsonify({"error": "Failed to initiate", "details": res_data}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/callback', methods=['POST'])
def callback():
    data = request.get_json(force=True)
    try:
        stk_data = data["Body"]["stkCallback"]
        checkout_id = stk_data["CheckoutRequestID"]
        result_code = stk_data["ResultCode"]

        if checkout_id in payments:
            if result_code == 0:
                payments[checkout_id]["status"] = "paid"
            else:
                payments[checkout_id]["status"] = "failed"
                
        print(f"Payment Update: {checkout_id} is now {payments[checkout_id]['status']}")
    except Exception as e:
        print(f"Callback error: {e}")
        
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

@app.route('/check-payment/<checkout_id>')
def check_status(checkout_id):
    status_data = payments.get(checkout_id, {"status": "not_found"})
    return jsonify(status_data)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
