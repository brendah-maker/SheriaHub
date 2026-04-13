import os
import io
import PyPDF2
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)

# Allowed origins for CORS
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

# --- EXISTING AI LOGIC ---
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
            f"ACT as the Lead Counsel at SheriaHub Kenya, an expert in {law_map.get(category)}. "
            "Provide detailed legal analysis using the Laws of Kenya. "
            "FORMAT: 1. Legal Context, 2. Your Rights, 3. Step-by-Step Action Plan."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.1 
        )
        return jsonify({"status": "success", "answer": completion.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- NEW: CONTRACT REVIEW LOGIC ---
@app.route('/review-contract', methods=['POST'])
def review_contract():
    if not client: 
        return jsonify({"error": "AI not initialized"}), 500
    
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    
    try:
        # Extract text from PDF
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
        contract_text = ""
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text: contract_text += text
        
        # Limit text to first 12,000 chars to fit AI context
        contract_text = contract_text[:12000]

        system_msg = (
            "ACT as a Senior Kenyan Advocate. You are reviewing a legal contract (Lease, Employment, or Service Agreement). "
            "Analyze it strictly under the Laws of Kenya (Law of Contract Act, Employment Act, etc.). "
            "Structure your response: "
            "1. CRITICAL RED FLAGS (Unfair or illegal clauses), "
            "2. OMISSION ALERT (What is missing that should be there?), "
            "3. RECOMMENDATION (Should they sign? What should they negotiate?). "
            "Be precise and protective of the user."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Review this contract text and provide analysis: {contract_text}"}
            ],
            temperature=0.1 
        )
        
        return jsonify({
            "status": "success",
            "answer": completion.choices[0].message.content.strip()
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
