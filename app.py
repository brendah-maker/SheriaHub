import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. API KEYS ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "FREE_ACCESS"}), 200

# --- 2. THE SIMPLIFIED "OPEN" AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: return jsonify({"error": "AI not initialized"}), 500
    try:
        data = request.get_json()
        question = data.get("question", "")
        category = data.get("category", "tenant")

        law_map = {
            "employment": "Employment Law",
            "land": "Land & Property Law",
            "family": "Family & Children Law",
            "traffic": "Traffic Law",
            "tenant": "Tenancy Law",
            "civil_criminal": "Civil & Criminal Law"
        }
            
        # Updated Prompt: Just ask for the full, expert answer
        system_msg = (
            f"You are a leading Kenyan legal expert specialized in {law_map.get(category)}. "
            "Provide a comprehensive, professional, and helpful response to the user's question. "
            "Include specific references to Kenyan Acts, Section numbers, and the exact steps the user "
            "should take (e.g., which court or tribunal to visit). Format the response clearly."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.2 # Slightly more creative for better legal explanations
        )
        
        full_response = completion.choices[0].message.content

        # Return everything as 'content'
        return jsonify({
            "status": "free",
            "summary": "Full Legal Consultation",
            "content": full_response # The user sees the full Deep Dive immediately
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
