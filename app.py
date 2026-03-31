import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Allows your frontend (sheriahub.co.ke) to communicate with this backend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. CONFIGURATION ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "FREE_ACCESS"}), 200

# --- 2. THE AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: 
        return jsonify({"error": "AI not initialized. Check your API Key."}), 500
    
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
            
        # Simplified prompt to get a single, professional legal response
        system_msg = (
            f"You are a leading Kenyan legal expert specialized in {law_map.get(category)}. "
            "Provide a comprehensive professional analysis regarding the user's query. "
            "Include specific Kenyan Acts, relevant Section numbers, and clear, "
            "step-by-step guidance for the user."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.1 
        )
        
        # Get the full feedback text
        ai_feedback = completion.choices[0].message.content.strip()

        # Send the direct AI feedback back to your frontend
        return jsonify({
            "status": "success",
            "answer": ai_feedback
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
