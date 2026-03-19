import os
import base64
import datetime
import requests
import json
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
# M-Pesa Keys
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"  # Sandbox
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

# Gemini AI Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- HELPERS ---
def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        r.raise_for_status()
        return r.json().get('access_token')
    except Exception as e:
        print(f"Safaricom Token Error: {e}")
        return None

# --- ROUTES ---
@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API is Live", "message": "Ready for AI & M-Pesa requests!"})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get('question')
    
    # The System Prompt defines the AI's "personality" and knowledge base
    prompt = f"""
    You are 'Sheria AI', a Kenyan Legal Expert specializing in Tenant and Landlord rights.
    The user is asking: "{user_question}"
    
    Please provide your response in exactly this JSON format:
    {{
      "free_summary": "A 1-sentence general right regarding this issue in simple terms.",
      "paid_deep_dive": "A detailed explanation (approx 100 words) including references to the Rent Restriction Act or Landlord & Tenant Bill, specific notice periods, and steps to take at the Rent Restriction Tribunal."
    }}
    Rules: 
    1. Use Kenyan context only. 
    2. Do not include markdown code blocks (like ```json). 
    3. Be empathetic but professional.
    """

    try:
        response = model.generate_content(prompt)
        # Clean up response text to ensure it's valid JSON
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        ai_data = json.loads(clean_text)
        return jsonify(ai_data)
    except Exception as e:
        print(f"Gemini AI Error: {e}")
        return jsonify({"free_summary": "Error connecting to AI.", "paid_deep_dive": "AI is currently unavailable."}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    data = request.json
    phone_number = data.get('phone') 
    
    if not phone_number:
        return jsonify({"CustomerMessage": "Phone number is required"}), 400

    access_token = get_access_token()
    if not access_token:
        return jsonify({"CustomerMessage": "Failed to connect to Safaricom"}), 500

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = BUSINESS_SHORT_CODE + PASSKEY + timestamp
    password = base64.b64encode(password_str.encode()).decode('utf-8')
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    payload = {
        "BusinessShortCode": BUSINESS_SHORT_CODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": 1,
        "PartyA": phone_number,
        "PartyB": BUSINESS_SHORT_CODE,
        "PhoneNumber": phone_number,
        "CallBackURL": "[https://sheriahub.onrender.com/callback](https://sheriahub.onrender.com/callback)", 
        "AccountReference": "SheriaHub",
        "TransactionDesc": "Legal Info Payment"
    }
    
    try:
        response = requests.post(
            "[https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest](https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest)",
            json=payload,
            headers=headers
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"CustomerMessage": str(e)}), 500

@app.route('/callback', methods=['POST'])
def mpesa_callback():
    print("M-Pesa Callback:", request.json)
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
