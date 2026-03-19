import os
import base64
import datetime
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from requests.auth import HTTPBasicAuth

app = Flask(__name__)
CORS(app)  # This allows your GitHub Pages site to access this API

# Configuration (Use Environment Variables for Security)
CONSUMER_KEY = "YOUR_Safaricom_Consumer_Key"
CONSUMER_SECRET = "YOUR_Safaricom_Consumer_Secret"
BUSINESS_SHORT_CODE = "174379"  # Sandbox Paybill
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919" # Sandbox Passkey

def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    r = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
    return r.json()['access_token']

@app.route('/stkpush', methods=['POST'])
def stk_push():
    data = request.json
    phone_number = data.get('phone') # Expected format: 2547XXXXXXXX
    
    access_token = get_access_token()
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    
    # Generate Password
    password_str = BUSINESS_SHORT_CODE + PASSKEY + timestamp
    password = base64.b64encode(password_str.encode()).decode('utf-8')
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    payload = {
        "BusinessShortCode": BUSINESS_SHORT_CODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": 20,
        "PartyA": phone_number,
        "PartyB": BUSINESS_SHORT_CODE,
        "PhoneNumber": phone_number,
        "CallBackURL": "https://your-callback-url.com/api/callback", # You'll need this later
        "AccountReference": "SheriaHub",
        "TransactionDesc": "Legal Info Payment"
    }
    
    response = requests.post(
        "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers=headers
    )
    
    return jsonify(response.json())

if __name__ == '__main__':
    # Use port 5000 for local testing
    app.run(port=5000, debug=True)