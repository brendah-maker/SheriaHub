import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Updated CORS to be more permissive for GitHub Pages
CORS(app, resources={r"/*": {"origins": "*"}})

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
payments_db = {}

@app.route('/')
def health():
    return jsonify({"status": "active"}), 200

@app.route('/ask-ai', methods=['POST', 'OPTIONS'])
def ask_ai():
    if request.method == 'OPTIONS':
        return '', 200
        
    if not client:
        return jsonify({"error": "AI not configured"}), 500
        
    try:
        data = request.get_json()
        user_q = data.get("question", "General legal inquiry")
        
        # Using a reliable model with a clear system prompt
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Kenyan Legal Expert. Return ONLY JSON: {'free_summary': '...', 'paid_deep_dive': '...'}"},
                {"role": "user", "content": user_q}
            ],
            response_format={"type": "json_object"}
        )
        
        ai_response = json.loads(completion.choices[0].message.content)
        return jsonify(ai_response)
    except Exception as e:
        print(f"AI ERROR: {str(e)}")
        return jsonify({"error": "AI took too long or failed. Please try again."}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 1, 
            "phone_number": phone,
            "email": "user@sheriahub.co.ke",
            "api_ref": "SheriaHub-Consultation",
        }

        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        response = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        res_data = response.json()
        invoice_id = res_data.get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            payments_db[invoice_id] = "pending"
            return jsonify({"checkout_id": invoice_id})
        return jsonify({"error": "Failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    # Direct check against IntaSend API to ensure accuracy
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.status_code == 200:
            api_state = res.json().get("invoice", {}).get("state")
            if api_state == "COMPLETE":
                return jsonify({"status": "paid"})
            elif api_state in ["FAILED", "CANCELLED"]:
                return jsonify({"status": "failed"})
    except:
        pass
    return jsonify({"status": "pending"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
