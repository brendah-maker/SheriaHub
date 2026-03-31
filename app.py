import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Allows your specific frontend to communicate with this backend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. AI CONFIGURATION ---
# Ensure GROQ_API_KEY is set in your Render/Heroku Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "FREE_ACCESS"}), 200

# --- 2. THE "OPEN" AI LOGIC ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    if not client: 
        return jsonify({"error": "AI not initialized. Check API Key."}), 500
    
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
            
        # This prompt tells the AI to provide both a summary and full details immediately
        system_msg = (
            f"You are a Kenyan legal expert specialized in {law_map.get(category)}. "
            "Your response MUST follow this structure exactly:\n"
            "1. Start with a 2-sentence professional summary.\n"
            "2. Then write the marker '|||'.\n"
            "3. Then provide the full deep-dive analysis, including specific Kenyan Acts, "
            "Section numbers, and step-by-step guidance."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.1
        )
        
        full_text = completion.choices[0].message.content
        
        # We split the text at the marker '|||' to fill the two boxes on your frontend
        if "|||" in full_text:
            parts = full_text.split("|||")
            summary_text = parts[0].strip()
            content_text = parts[1].strip()
        else:
            # Fallback if the AI forgets the marker
            summary_text = "Legal analysis complete."
            content_text = full_text

        # Returning the exact JSON structure your frontend's script expects
        return jsonify({
            "status": "free",
            "summary": summary_text,
            "content": content_text
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Render uses the PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
