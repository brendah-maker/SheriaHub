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
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

def get_access_token():
    # Debug: Check if keys exist
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        print("ERROR: CONSUMER_KEY or CONSUMER_SECRET is missing in Render Env!")
        return None
        
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        if r.status_code != 200:
            print(f"Safaricom Auth Failed: {r.status_code} - {r.text}")
            return None
        return r.json().get('access_token')
    except Exception as e:
        print(f"Token Exception: {e}")
        return None

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub Live", "ai_ready": bool(GEMINI_API_KEY)})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    user_question = request.json.get('question')
    print(f"AI Request Received: {user_question}")
    
    prompt = f"You are a Kenyan Legal Expert. Answer this JSON only: {{'free_summary': '...', 'paid_deep_dive': '...'}}. Question: {user_question}"

    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean_text))
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"free_summary": "AI Error", "paid_deep_dive": str(e)}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    phone = request.json.get('phone')
    print(f"STK Push Request for: {phone}")
    
    access_token = get_access_token()
    if not access_token:
        return jsonify({"CustomerMessage": "Failed to login to M-Pesa. Check Render Env Keys."}), 500

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode((BUSINESS_SHORT_CODE + PASSKEY + timestamp).encode()).decode('utf-8')
    
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
        "TransactionDesc": "Legal Info"
    }
    
    try:
        res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", 
                            json=payload, 
                            headers={"Authorization": f"Bearer {access_token}"})
        return jsonify(res.json())
    except Exception as e:
        return jsonify({"CustomerMessage": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
