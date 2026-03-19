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
# Crucial: This allows your GitHub site to talk to your Render server without being blocked
CORS(app, resources={r"/*": {"origins": "*"}})

# --- CONFIGURATION (Ensure these are in Render Environment Variables) ---
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini Client (Standard for 2026)
client = genai.Client(api_key=GEMINI_API_KEY)

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        if r.status_code != 200:
            print(f"SAFARICOM LOGIN ERROR: {r.status_code} - {r.text}")
            return None
        return r.json().get('access_token')
    except Exception as e:
        print(f"TOKEN EXCEPTION: {e}")
        return None

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API is Live", "ai": bool(GEMINI_API_KEY)})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get('question', 'Tell me about Kenyan law.')
    print(f"Processing: {user_question}")
    
    prompt = f"Role: Kenyan Legal Expert. Question: {user_question}. Return ONLY JSON: {{'free_summary': '...', 'paid_deep_dive': '...'}}"

    try:
        # Using gemini-3-flash-preview (The 2026 stable version)
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
                ]
            )
        )
        
        if not response.text:
            raise ValueError("AI returned an empty string.")

        # Clean JSON to prevent SyntaxErrors in browser
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean_text))

    except Exception as e:
        print(f"AI CRASHED: {str(e)}")
        # Always return valid JSON to avoid "Unexpected end of input" error in JS
        return jsonify({
            "free_summary": "Sheria AI is temporarily offline.",
            "paid_deep_dive": f"Developer Log: {str(e)}"
        }), 200 # Returning 200 keeps the frontend from crashing

@app.route('/stkpush', methods=['POST'])
def stk_push():
    phone = request.json.get('phone')
    access_token = get_access_token()
    
    if not access_token:
        return jsonify({"CustomerMessage": "Safaricom login failed."}), 401

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
                            json=payload, headers={"Authorization": f"Bearer {access_token}"})
        return jsonify(res.json())
    except Exception as e:
        return jsonify({"CustomerMessage": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
