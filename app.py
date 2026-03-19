import os
import base64
import datetime
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth
from google import genai

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
# Ensure these are exactly named in Render Environment Variables
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the latest Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

def get_access_token():
    """Fetches Safaricom Access Token with error logging"""
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        if r.status_code != 200:
            print(f"Safaricom Login Error: {r.status_code} - {r.text}")
            return None
        return r.json().get('access_token')
    except Exception as e:
        print(f"Token Request Failed: {e}")
        return None

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API Live", "ai": "Ready"})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get('question')
    
    prompt = f"""
    You are 'Sheria AI', a Kenyan Legal Expert. 
    Question: {user_question}
    Return ONLY a JSON object with keys: 'free_summary' (1 sentence) and 'paid_deep_dive' (detailed legal explanation).
    Use Kenyan Laws only. No markdown.
    """

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        # Clean up text in case of markdown formatting
        text = response.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(text))
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"free_summary": "AI is temporarily unavailable.", "paid_deep_dive": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    data = request.json
    phone = data.get('phone') 
    
    access_token = get_access_token()
    if not access_token:
        return jsonify({"CustomerMessage": "Failed to connect to Safaricom. Check your API keys."}), 500

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = BUSINESS_SHORT_CODE + PASSKEY + timestamp
    password = base64.b64encode(password_str.encode()).decode('utf-8')
    
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
        "TransactionDesc": "Legal Info Payment"
    }
    
    try:
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"CustomerMessage": str(e)}), 500

@app.route('/callback', methods=['POST'])
def mpesa_callback():
    print("M-Pesa Callback Received:", request.json)
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
