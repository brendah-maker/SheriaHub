import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
# Allows your frontend (sheriahub.co.ke) to communicate with this backend
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 1. CONFIGURATION ---
# Ensure GROQ_API_KEY is set in your Render Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "Healthy", "mode": "FREE_ACCESS"}), 200

# --- 2. THE AI LOGIC (No Payment Gate) ---
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
            
        # The AI is told to use '|||' as a hard separator
        system_msg = (
            f"You are a leading Kenyan legal expert specialized in {law_map.get(category)}. "
            "You MUST format your response into two distinct parts separated by the exact marker '|||'.\n\n"
            "PART 1 (The Summary): Provide a 2-sentence professional overview. "
            "Do NOT include the words 'DEEP DIVE' or specific Act names here.\n\n"
            "|||\n\n"
            "PART 2 (The Deep Dive): Provide the full comprehensive analysis, including specific Kenyan "
            "Acts, Section numbers, and a step-by-step guide for the user."
        )

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": question}
            ],
            temperature=0.1 # Keeps the response focused and consistent
        )
        
        full_text = completion.choices[0].message.content
        
        # --- ROBUST SPLITTING LOGIC ---
        # This prevents 'Deep Dive' text from appearing in the 'Summary' box.
        if "|||" in full_text:
            parts = full_text.split("|||")
            summary_text = parts[0].strip()
            content_text = parts[1].strip()
        else:
            # Fallback if the AI fails to use the separator
            summary_text = "Legal analysis generated. See below for details."
            content_text = full_text

        # Clean up any accidental headers the AI might have added
        summary_text = summary_text.replace("PART 1:", "").replace("Summary:", "").strip()
        content_text = content_text.replace("PART 2:", "").replace("**DEEP DIVE:**", "").strip()

        # Send the clean data back to your frontend
        return jsonify({
            "status": "free",
            "summary": summary_text,
            "content": content_text
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Render looks for the PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
