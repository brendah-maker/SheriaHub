import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from intasend import APIService

app = Flask(__name__)
CORS(app)

# --- Configuration ---
# Set these in your Render Dashboard Environment Variables
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
INTASEND_PUBLISHABLE_KEY = os.environ.get("INTASEND_PUBLISHABLE_KEY")
INTASEND_API_KEY = os.environ.get("INTASEND_API_KEY")

# Initialize IntaSend
service = APIService(
    token=INTASEND_API_KEY,
    publishable_key=INTASEND_PUBLISHABLE_KEY,
    test_mode=False # Set to False for live M-Pesa
)

model = genai.GenerativeModel('gemini-1.5-flash')

# --- 1. Main AI Legal Consultant Route ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    question = data.get('question')
    category = data.get('category', 'general')
    checkout_id = data.get('checkout_id')

    # If user provided a checkout_id, verify it for premium access
    is_premium = False
    if checkout_id:
        status_resp = service.collect().status(checkout_id)
        if status_resp.get('invoice', {}).get('state') == 'COMPLETE':
            is_premium = True

    if is_premium:
        prompt = f"Provide a detailed legal analysis of this Kenyan {category} issue: {question}. Cite specific sections of the relevant Kenyan Acts."
        response = model.generate_content(prompt)
        return jsonify({
            "status": "premium",
            "content": response.text,
            "credits_left": 1 # Simplified for this example
        })
    else:
        prompt = f"Give a 2-sentence summary of the legal position on this Kenyan {category} issue: {question}. Do not give specific legal advice."
        response = model.generate_content(prompt)
        return jsonify({
            "status": "free",
            "summary": response.text
        })

# --- 2. Kanjo Chronicles Game Route ---
@app.route('/generate-kanjo', methods=['POST'])
def generate_kanjo():
    # In a production app, you'd track the 10-play limit in a database
    # For now, we allow the request unless the frontend sends a 'limit reached' signal
    prompt = """Generate a short 'Kanjo Chronicles' survival scenario in Nairobi CBD. 
    Provide: 1 scenario, 3 choices (A, B, C), and 3 outcomes. 
    Format as JSON: {"scenario": "...", "choice_a": "...", "outcome_a": "...", ...}"""
    
    response = model.generate_content(prompt)
    # Clean up the response to ensure it's valid JSON
    return response.text, 200, {'Content-Type': 'application/json'}

# --- 3. Jua Mechi Game Route (Fixes your 404) ---
@app.route('/generate-jua-mechi', methods=['GET'])
def generate_jua_mechi():
    category = request.args.get('category', 'tenant')
    prompt = f"""Create a 'Spot the Red Flag' game for Kenyan {category} law. 
    Provide a short contract snippet with 3 illegal clauses.
    Format as JSON: {"snippet": "...", "flags": ["clause1", "clause2", "clause3"]}"""
    
    response = model.generate_content(prompt)
    return response.text, 200, {'Content-Type': 'application/json'}

# --- 4. Payment Routes ---
@app.route('/stkpush-game', methods=['POST'])
def stkpush_game():
    data = request.json
    phone = data.get('phone')
    try:
        response = service.collect().mpesa_stk_push(
            phone_number=phone,
            amount=20,
            narrative="SheriaHub Unlimited Game"
        )
        return jsonify({"checkout_id": response.get('id')}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<checkout_id>', methods=['GET'])
def check_payment(checkout_id):
    try:
        status_resp = service.collect().status(checkout_id)
        # Check the actual state from the invoice object
        state = status_resp.get('invoice', {}).get('state', 'PENDING')
        
        if state == 'COMPLETE':
            return jsonify({"status": "paid"}), 200
        return jsonify({"status": "pending"}), 200
    except Exception:
        return jsonify({"status": "pending"}), 200

if __name__ == '__main__':
    # Render uses the PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
