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

# =========================
# APP SETUP
# =========================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =========================
# ENV VARIABLES
# =========================
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# =========================
# INIT AI
# =========================
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# TEMP STORAGE (Upgrade later)
# =========================
payments = {}        # {ref: {status: paid/pending/failed}}
chat_history = {}    # {user_id: [messages]}

# =========================
# HEALTH CHECK
# =========================
@app.route('/')
def home():
    return jsonify({
        "status": "SheriaHub API is running",
        "ai_connected": bool(GEMINI_API_KEY)
    })

# =========================
# SAFARICOM TOKEN
# =========================
def get_access_token():
    try:
        url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        res = requests.get(url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))

        if res.status_code != 200:
            print(f"❌ Safaricom Auth Error: {res.text}")
            return None

        return res.json().get("access_token")

    except Exception as e:
        print("❌ Token Error:", e)
        return None

# =========================
# AI QUESTION (PAYWALLED)
# =========================
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    try:
        data = request.get_json()
        question = data.get("question", "")

        if not client:
            return jsonify({
                "free_summary": "AI not configured",
                "paid_deep_dive": "Missing GEMINI_API_KEY"
            })

        print(f"📩 Question: {question}")

        prompt = f"""
You are a Kenyan legal expert.

Use:
- Rent Restriction Act (Kenya)
- Landlord and Tenant Bill 2021

Answer clearly and practically.

Return ONLY JSON:
{{
  "free_summary": "simple explanation",
  "paid_deep_dive": "detailed explanation with legal steps and tribunal process"
}}

Question: {question}
"""

        res = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        text = res.text.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(text)
        except:
            parsed = {
                "free_summary": text[:200],
                "paid_deep_dive": text
            }

        return jsonify(parsed)

    except Exception as e:
        print("❌ AI ERROR:")
        print(traceback.format_exc())

        return jsonify({
            "free_summary": "Sheria AI is temporarily unavailable.",
            "paid_deep_dive": str(e)
        })

# =========================
# CHAT (MEMORY SYSTEM)
# =========================
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        message = data.get("message")

        if not user_id or not message:
            return jsonify({"error": "Missing data"}), 400

        if user_id not in chat_history:
            chat_history[user_id] = []

        chat_history[user_id].append(message)

        history = "\n".join(chat_history[user_id][-5:])

        prompt = f"""
You are a Kenyan legal assistant.

Conversation:
{history}

Reply helpfully and clearly.
"""

        res = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        reply = res.text
        chat_history[user_id].append(reply)

        return jsonify({"reply": reply})

    except Exception as e:
        print("❌ CHAT ERROR:")
        print(traceback.format_exc())
        return jsonify({"reply": "Chat error occurred"})

# =========================
# STK PUSH (INITIATE PAYMENT)
# =========================
@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone")

        if not phone:
            return jsonify({"error": "Phone required"}), 400

        access_token = get_access_token()
        if not access_token:
            return jsonify({"error": "Safaricom auth failed"}), 401

        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')

        password = base64.b64encode(
            (BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()
        ).decode()

        reference = f"Sheria-{timestamp}"

        payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": 20,
            "PartyA": phone,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone,
            "CallBackURL": "https://sheriahub.onrender.com/callback",
            "AccountReference": reference,
            "TransactionDesc": "Legal Access"
        }

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers=headers
        )

        payments[reference] = {"status": "pending"}

        return jsonify({
            "ref": reference,
            "mpesa_response": res.json()
        })

    except Exception as e:
        print("❌ STK ERROR:")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# =========================
# CALLBACK (VERIFY PAYMENT)
# =========================
@app.route('/callback', methods=['POST'])
def callback():
    data = request.json

    try:
        print("📲 CALLBACK RECEIVED:")
        print(json.dumps(data, indent=2))

        stk = data["Body"]["stkCallback"]
        result_code = stk["ResultCode"]

        metadata = stk.get("CallbackMetadata", {}).get("Item", [])

        reference = None
        for item in metadata:
            if item["Name"] == "AccountReference":
                reference = item["Value"]

        if reference:
            if result_code == 0:
                payments[reference] = {"status": "paid"}
            else:
                payments[reference] = {"status": "failed"}

    except Exception as e:
        print("❌ CALLBACK ERROR:", e)

    return jsonify({"status": "received"})

# =========================
# CHECK PAYMENT STATUS
# =========================
@app.route('/check-payment/<ref>')
def check_payment(ref):
    return jsonify(payments.get(ref, {"status": "not_found"}))

# =========================
# RUN SERVER
# =========================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
