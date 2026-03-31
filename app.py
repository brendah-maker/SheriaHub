import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Ensures your frontend can talk to this server
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. CONFIGURATION ---
# Make sure your GROQ_API_KEY is set in your Render Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "FREE_ACCESS"}), 200

# --- 2. THE FREE AI LOGIC ---
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
            
        # This prompt ensures the AI gives both a summary and full details separated by '|||'
        # Your frontend uses the first part for the top box and the second for the bottom box.
        system_msg = (
            f"You are a leading Kenyan legal expert specialized in {law_map.get(category)}. "
            "You MUST format your response into two parts separated by '|||'.\n\n"
            "PART 1: A brief 2-sentence professional summary.\n"
            "|||\n"
            "PART 2: The full, comprehensive deep-dive legal analysis, including specific Kenyan "
            "Acts, Section numbers, and the exact steps the user should take."
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
        
        # We split the text at '|||' to populate the two different boxes in your frontend
        if "|||" in full_text:
            parts = full_text.split("|||")
            summary_text = parts[0].strip()
            content_text = parts[1].strip()
        else:
            # Fallback if the AI fails to use the separator
            summary_text = "Legal analysis complete."
            content_text = full_text

        # THE FIX: No more payment checks. We send back the actual data every time.
        return jsonify({
            "status": "free",
            "summary": summary_text,
            "content": content_text # This will now show the real info instead of "Locked"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
