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

# --- CONFIGURATION (Render Environment Variables) ---
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        if r.status_code != 200:
            print(f"SAFARICOM LOGIN FAILED: {r.status_code} - {r.text}")
            return None
        return r.json().get('access_token')
    except Exception as e:
        print(f"SAFARICOM EXCEPTION: {e}")
        return None

@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API Live", "ai_check": bool(GEMINI_API_KEY)})

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    user_question = request.json.get('question')
    print(f"AI Request for: {user_question}")
    
    prompt = f"""
    You are 'Sheria AI', a Kenyan Legal Expert. 
    Question: {user_question}
    Return ONLY a JSON object with keys: 'free_summary' and 'paid_deep_dive'.
    Use Kenyan Laws like Rent Restriction Act (Cap 296). No markdown.
    """

    try:
        response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
        # Handle empty AI response
        if not response.text:
            return jsonify({"free_summary": "AI returned no text.", "paid_deep_dive": "Check your API quota."})
            
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean_text))
    except Exception as e:
        print(f"AI CRASHED: {str(e)}")
        return jsonify({"free_summary": "AI Error.", "paid_deep_dive": f"Technical Reason: {str(e)}"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    phone = request.json.get('phone')
    access_token = get_access_token()
    if not access_token:
        return jsonify({"CustomerMessage": "Internal Server Error: Safaricom Keys Invalid."}), 500

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
    # Render uses port 10000 often, this covers all bases
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
