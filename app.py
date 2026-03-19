import os
import base64
import datetime
import requests
import json
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from google import genai
from google.genai import types

# ================================
# APP SETUP
# ================================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ================================
# ENV VARIABLES
# ================================
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# ================================
# INIT GEMINI
# ================================
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

# ================================
# HEALTH CHECK
# ================================
@app.route('/')
def home():
    return jsonify({
        "status": "SheriaHub API is Live",
        "ai_connected": bool(GEMINI_API_KEY)
    })

# ================================
# SAFARICOM TOKEN
# ================================
def get_access_token():
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        res = requests.get(url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))

        if res.status_code != 200:
            print(f"❌ SAFARICOM ERROR: {res.status_code} - {res.text}")
            return None

        return res.json().get("access_token")

    except Exception as e:
        print(f"❌ TOKEN ERROR: {str(e)}")
        return None

# ================================
# AI ENDPOINT
# ================================
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        data = request.get_json()
        user_question = data.get("question", "Explain tenant rights in Kenya")

        print(f"📩 Question: {user_question}")

        if not client:
            return jsonify({
                "free_summary": "AI service is not configured.",
                "paid_deep_dive": "Missing GEMINI_API_KEY"
            })

        # ✅ STRICT JSON PROMPT
        prompt = f"""
You are a Kenyan legal expert.

Answer the question below and return ONLY valid JSON.

Format:
{{
  "free_summary": "Short simple answer",
  "paid_deep_dive": "Detailed legal explanation with references to Kenyan law"
}}

Question: {user_question}
"""

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        if not response.text:
            raise ValueError("Empty AI response")

        # ✅ CLEAN RESPONSE
        clean_text = response.text.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(clean_text)
        except:
            # fallback if AI messes up JSON
            parsed = {
                "free_summary": clean_text[:200],
                "paid_deep_dive": clean_text
            }

        return jsonify(parsed)

    except Exception as e:
        print("❌ AI ERROR:")
        print(traceback.format_exc())

        return jsonify({
            "free_summary": "Sheria AI is temporarily unavailable.",
            "paid_deep_dive": str(e)
        }), 200

# ================================
# MPESA STK PUSH
# ================================
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone")

        if not phone:
            return jsonify({"error": "Phone number required"}), 400

        access_token = get_access_token()

        if not access_token:
            return jsonify({"error": "Failed to authenticate with Safaricom"}), 401

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode(
            (BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()
        ).decode('utf-8')

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
            "TransactionDesc": "Legal Info Access"
        }

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers=headers
        )

        return jsonify(res.json())

    except Exception as e:
        print("❌ STK PUSH ERROR:")
        print(traceback.format_exc())

        return jsonify({"error": str(e)}), 500

# ================================
# CALLBACK (MPESA RESPONSE)
# ================================
@app.route('/callback', methods=['POST'])
def callback():
    data = request.json
    print("📲 MPESA CALLBACK:")
    print(json.dumps(data, indent=2))
    return jsonify({"status": "received"})

# ================================
# RUN SERVER
# ================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
