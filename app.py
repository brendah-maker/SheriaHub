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

# --- CONFIGURATION ---
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize the 2026 Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        if r.status_code != 200:
            print(f"SAFARICOM AUTH ERROR: {r.status_code} - {r.text}")
            return None
        return r.json().get('access_token')
    except Exception as e:
        print(f"MPESA TOKEN EXCEPTION: {e}")
        return None

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API is Online", "ai_check": "Ready" if GEMINI_API_KEY else "Missing API Key"})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get('question', '')
    print(f"--- NEW REQUEST: {user_question} ---")
    
    # Prompting for a clean JSON response
    prompt = f"""
    Role: Kenyan Legal Expert.
    User Question: {user_question}
    Return ONLY a JSON object with these keys:
    'free_summary': A 1-sentence legal right.
    'paid_deep_dive': A detailed explanation referencing Kenyan statutes.
    """

    try:
        # Use gemini-3-flash-preview (The 2026 high-speed standard)
        # We also disable safety filters that often block legal advice
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                ]
            )
        )
        
        if not response.text:
            print("AI ERROR: Empty response from Google")
            return jsonify({"free_summary": "AI is silent.", "paid_deep_dive": "Empty response."}), 500

        # Strip markdown if Gemini adds it
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        print(f"AI SUCCESS: {clean_json[:50]}...")
        return jsonify(json.loads(clean_json))

    except Exception as e:
        print(f"AI CRASHED: {str(e)}")
        return jsonify({
            "free_summary": "Connection to Sheria AI failed.",
            "paid_deep_dive": f"Technical Detail: {str(e)}"
        }), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    phone = request.json.get('phone')
    access_token = get_access_token()
    
    if not access_token:
        return jsonify({"CustomerMessage": "Safaricom Authentication Failed. Check Keys."}), 500

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
        print(f"STK PUSH ERROR: {e}")
        return jsonify({"CustomerMessage": "STK Push failed to send."}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
