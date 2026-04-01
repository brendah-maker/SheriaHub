import os
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)

# Allows your website to talk to this backend
CORS(app, resources={r"/*": {
    "origins": [
        "https://www.sheriahub.co.ke", 
        "https://sheriahub.co.ke", 
        "http://localhost:5500", 
        "http://127.0.0.1:5500"
    ],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

# --- CONFIGURATION ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy"}), 200

# --- THE AI LOGIC ---
@app.route('/ask-ai', methods=['POST', 'OPTIONS'])
def ask_ai():
    if request.method == 'OPTIONS':
        return make_response('', 204)

    if not client: 
        return jsonify({"error": "AI not initialized"}), 500
    
    try:
        data = request.get_json()
        question = data.get("question", "").strip()
        category = data.get("category", "tenant")

        law_map = {
            "employment": "Employment Law",
            "land": "Land & Property Law",
            "family": "Family & Children Law",
            "traffic": "Traffic Law",
            "tenant": "Tenancy Law",
            "civil_criminal": "Civil & Criminal Law"
        }
            
        system_msg = (
            f"You are a leading Kenyan legal expert specialized in {law_map.get(category)}. "
            "Provide a comprehensive professional analysis. Include specific Kenyan Acts, "
            "Section numbers, and a step-by-step guide. DO NOT include any warnings about credits or locks."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.1 
        )
        
        ai_response = completion.choices[0].message.content.strip()

        # SUCCESS: Sending ONLY the answer
        return jsonify({
            "status": "success",
            "answer": ai_response
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.after_request
def add_headers(response):
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    return response

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
