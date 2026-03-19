import os
import base64
import datetime
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth

app = Flask(__name__)
CORS(app) 

# 1. Configuration - Pulled from Render Environment Variables for security
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORT_CODE = "174379"  # Default Sandbox Shortcode
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
        r.raise_for_status()
        return r.json().get('access_token')
    except Exception as e:
        print(f"Token Error: {e}")
        return None

# 2. Add a Home Route so the URL doesn't show "Not Found"
@app.route('/')
def home():
    return jsonify({"status": "SheriaHub API is Live", "message": "Ready for M-Pesa requests!"})

@app.route('/stkpush', methods=['POST'])
def stk_push():
    data = request.json
    phone_number = data.get('phone') 
    
    # Basic Validation
    if not phone_number or len(str(phone_number)) < 10:
        return jsonify({"CustomerMessage": "Invalid phone number format"}), 400

    access_token = get_access_token()
    if not access_token:
        return jsonify({"CustomerMessage": "Internal Server Error: Failed to connect to Safaricom"}), 500

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = BUSINESS_SHORT_CODE + PASSKEY + timestamp
    password = base64.b64encode(password_str.encode()).decode('utf-8')
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    payload = {
        "BusinessShortCode": BUSINESS_SHORT_CODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": 1, # Set to 1 for testing
        "PartyA": phone_number,
        "PartyB": BUSINESS_SHORT_CODE,
        "PhoneNumber": phone_number,
        "CallBackURL": "https://sheriahub.onrender.com/callback", 
        "AccountReference": "SheriaHub",
        "TransactionDesc": "Legal Info Payment"
    }
    
    try:
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers=headers
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"CustomerMessage": str(e)}), 500

# 3. Add a Callback Route to handle Safaricom's response
@app.route('/callback', methods=['POST'])
def mpesa_callback():
    data = request.json
    print("M-Pesa Callback Received:", data)
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

if __name__ == '__main__':
    # Render uses the PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
