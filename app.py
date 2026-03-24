import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from intasend import APIService

app = Flask(__name__)
CORS(app)

# Configuration
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
INTASEND_PUBLISHABLE_KEY = os.environ.get("INTASEND_PUBLISHABLE_KEY")
INTASEND_API_KEY = os.environ.get("INTASEND_API_KEY")

service = APIService(
    token=INTASEND_API_KEY,
    publishable_key=INTASEND_PUBLISHABLE_KEY,
    test_mode=False 
)

model = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    question = data.get('question')
    category = data.get('category', 'tenant')
    checkout_id = data.get('checkout_id')

    is_premium = False
    if checkout_id:
        try:
            status_resp = service.collect().status(checkout_id)
            if status_resp.get('invoice', {}).get('state') == 'COMPLETE':
                is_premium = True
        except:
            pass

    prompt_type = "detailed analysis with Kenyan statutes" if is_premium else "2-sentence general summary"
    prompt = f"Provide a {prompt_type} for this {category} issue: {question}"
    
    response = model.generate_content(prompt)
    return jsonify({
        "status": "premium" if is_premium else "free",
        "content": response.text if is_premium else None,
        "summary": response.text if not is_premium else None,
        "credits_left": 1 if is_premium else 0
    })

@app.route('/generate-kanjo', methods=['POST'])
def generate_kanjo():
    prompt = "Generate a JSON scenario for a Nairobi CBD survival game. Include 'scenario', 'choice_a', 'choice_b', 'choice_c' and outcomes for each."
    response = model.generate_content(prompt)
    return response.text, 200, {'Content-Type': 'application/json'}

@app.route('/generate-jua-mechi', methods=['GET'])
def generate_jua_mechi():
    cat = request.args.get('category', 'tenant')
    prompt = f"Create a JSON 'Spot Red Flags' game for Kenyan {cat} law. Include 'snippet' and 'flags' list."
    response = model.generate_content(prompt)
    return response.text, 200, {'Content-Type': 'application/json'}

@app.route('/stkpush-game', methods=['POST'])
def stkpush_game():
    data = request.json
    try:
        response = service.collect().mpesa_stk_push(
            phone_number=data.get('phone'),
            amount=20,
            narrative="SheriaHub Game"
        )
        return jsonify({"checkout_id": response.get('id')}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<checkout_id>', methods=['GET'])
def check_payment(checkout_id):
    try:
        status_resp = service.collect().status(checkout_id)
        state = status_resp.get('invoice', {}).get('state', 'PENDING')
        return jsonify({"status": "paid" if state == 'COMPLETE' else "pending"}), 200
    except:
        return jsonify({"status": "pending"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
