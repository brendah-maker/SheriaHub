import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"

BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

payments_db = {}

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client:
        return jsonify({"error": "AI not initialized"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")
        checkout_id = data.get("checkout_id")

        # Check if this specific checkout_id is marked as paid
        is_paid = checkout_id is not None and payments_db.get(checkout_id) == "paid"

        system_prompt = (
            "You are a Kenyan legal expert. Return ONLY a JSON object. "
            "JSON structure: {\"summary\": \"one sentence summary\", \"deep_dive\": \"detailed markdown\"}. "
            "For the deep_dive, include Kenyan Acts and Sections."
        )

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Category: {category}. Question: {question}"}
            ],
            response_format={"type": "json_object"}
        )
        
        # Robust JSON extraction
        try:
            ai_data = json.loads(completion.choices[0].message.content)
        except:
            ai_data = {"summary": "Legal record found.", "deep_dive": "Error parsing details."}

        # The GATE: Only send deep_dive if is_paid is True
        return jsonify({
            "status": "premium" if is_paid else "free",
            "summary": ai_data.get("summary", "No summary available."),
            "content": ai_data.get("deep_dive") if is_paid else "Locked"
        })

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": "Failed to reach Sheria AI"}), 500

@app.route('/stkpush', methods=['POST'])
def stk_push():
    try:
        data = request.get_json()
        phone = data.get("phone", "").strip().replace("+", "")
        if phone.startswith("0"): phone = "254" + phone[1:]
        
        payload = {
            "public_key": INTASEND_PUBLISHABLE_KEY,
            "amount": 20,
            "phone_number": phone,
            "api_ref": "SheriaHub-Premium"
        }
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}", "Content-Type": "application/json"}
        res = requests.post(f"{BASE_URL}/payment/mpesa-stk-push/", json=payload, headers=headers)
        invoice_id = res.json().get("invoice", {}).get("invoice_id")
        
        if invoice_id:
            payments_db[invoice_id] = "pending"
            return jsonify({"checkout_id": invoice_id})
        return jsonify({"error": "STK Push Failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<checkout_id>')
def check_payment(checkout_id):
    status = payments_db.get(checkout_id, "pending")
    if status == "paid": return jsonify({"status": "paid"})
    
    try:
        headers = {"Authorization": f"Bearer {INTASEND_SECRET_KEY}"}
        res = requests.get(f"{BASE_URL}/payment/status/{checkout_id}/", headers=headers)
        if res.json().get("invoice", {}).get("state") == "COMPLETE":
            payments_db[checkout_id] = "paid"
            return jsonify({"status": "paid"})
    except: pass
    return jsonify({"status": status})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
