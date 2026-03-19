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
# APP CONFIG
# =========================
app = Flask(__name__)
CORS(app)

# Environment Variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

# Safaricom Sandbox Constants
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# =========================
# AI INITIALIZATION
# =========================
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Using the standard model name
        model = genai.GenerativeModel('gemini-1.5-flash')
        print("✅ Sheria AI Initialized Successfully")
    except Exception as e:
        print(f"❌ AI Init Error: {e}")
        model = None
else:
    model = None
    print("⚠️ WARNING: GEMINI_API_KEY not found!")

# Simple in-memory storage for payments
payments = {}

# =========================
# HELPERS
# =========================
def get_mpesa_token():
    try:
        url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        r = requests.get(url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        return r.json().get("access_token")
    except:
        return None

def clean_ai_json(raw_text):
    """Strips Markdown backticks and returns a clean dict."""
    text = raw_text.strip()
    if text.startswith("```"):
        # Remove ```json and ```
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())

# =========================
# ROUTES
# =========================

@app.route('/')
def health_check():
    return jsonify({"status": "online", "ai_ready": model is not None})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not model:
        return jsonify({"free_summary": "AI is offline.", "paid_deep_dive": "Check API Key."})

    try:
        data = request.get_json()
        question = data.get("question", "")
        
        prompt = f"""
        Act as a Kenyan Landlord/Tenant legal expert. 
        Refer to the Rent Restriction Act.
        Return ONLY a JSON object with two keys: "free_summary" and "paid_deep_dive".
        Question: {question}
        """

        response = model.generate_content(prompt)
        ai_data = clean_ai_json(response.text)
        return jsonify(ai_data)

    except Exception as e:
        print(f"AI Route Error: {e}")
        return jsonify({
            "free_summary": "Consultation failed.", 
            "paid_deep_dive": f"Technical issue: {str(e)}"
        })

@app.route('/stkpush', methods=['POST'])
def stk_push():
    token = get_mpesa_token()
    if not token:
        return jsonify({"error": "M-Pesa Auth Failed"}), 401

    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode()

        payload = {
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
            "TransactionDesc": "Legal Advice"
        }

        headers = {"Authorization": f"Bearer {token}"}
        res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=payload, headers=headers)
        res_json = res.json()
        
        checkout_id = res_json.get("CheckoutRequestID")
        if checkout_id:
            payments[checkout_id] = {"status": "pending"}
            return jsonify({"checkout_id": checkout_id})
        
        return jsonify({"error": "STK Failed", "details": res_json}), 400
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
    except:
        pass
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    return jsonify(payments.get(checkout_id, {"status": "not_found"}))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
