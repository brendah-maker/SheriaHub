import os
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)

# 1. ENHANCED CORS CONFIGURATION
# This allows your specific website and local testing to talk to this backend.
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

# --- 2. CONFIGURATION ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "FREE_ACCESS"}), 200

# --- 3. THE AI LOGIC ---
@app.route('/ask-ai', methods=['POST', 'OPTIONS'])
def ask_ai():
    # Handle the browser's "Preflight" check (OPTIONS request)
    if request.method == 'OPTIONS':
        return make_response('', 204)

    if not client: 
        return jsonify({"error": "AI not initialized. Check GROQ_API_KEY environment variable."}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400

        question = data.get("question", "").strip()
        category = data.get("category", "tenant")

        if not question:
            return jsonify({"error": "Question cannot be empty"}), 400

        law_map = {
            "employment": "Employment Law (Employment Act 2007)",
            "land": "Land & Property Law (Land Act, Land Registration Act)",
            "family": "Family & Children Law (Marriage Act, Children Act 2022)",
            "traffic": "Traffic Law (Traffic Act Cap 403)",
            "tenant": "Tenancy Law (Rent Restriction Act, Landlord & Tenant Act)",
            "civil_criminal": "Civil & Criminal Law (Penal Code, Constitution of Kenya Article 49)"
        }
            
        system_msg = (
            f"You are a leading Kenyan legal expert specialized in {law_map.get(category, 'Kenyan Law')}. "
            "Provide a comprehensive professional analysis based ONLY on Kenyan Statutes. "
            "Include specific Kenyan Acts, Section numbers, and a clear step-by-step guide for the user. "
            "Maintain a helpful but professional tone."
        )

        # Call Groq API
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.2 
        )
        
        ai_response = completion.choices[0].message.content.strip()

        # Return the success response
# In app.py
return jsonify({
    "status": "success",
    "answer": ai_response  # Ensure you use 'answer' here
})
    except Exception as e:
        print(f"Error occurred: {str(e)}") # This shows up in your Render logs
        return jsonify({"error": str(e)}), 500

# --- 4. GLOBAL CORS HEADERS (Double Security) ---
@app.after_request
def add_headers(response):
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
