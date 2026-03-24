import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai
from groq import Groq  # The module that was missing
from intasend import APIService

app = Flask(__name__)
CORS(app)

# Database
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
db = SQLAlchemy(app)

# Initialize Clients
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY")) # Ensure this ENV is set on Render

# The "Kanjo" Game Prompt
KANJO_SYSTEM_PROMPT = """
You are 'Kanjo-GPT', an expert on Kenyan City Council (Kanjo) Bylaws. 
The user is in a simulation where they are confronted by Kanjo officers in Nairobi.
1. Present a scenario (e.g., parking, hawking, littering).
2. Give 3 options (A, B, C) on how to respond legally.
3. If they choose correctly, explain the specific Bylaw.
"""

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    user_q = data.get('question')
    category = data.get('category')

    # --- KANJO GAME LOGIC (Using Groq for speed) ---
    if category == "kanjo":
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": KANJO_SYSTEM_PROMPT},
                {"role": "user", "content": user_q}
            ]
        )
        return jsonify({"summary": completion.choices[0].message.content})

    # --- REGULAR LEGAL ADVICE (Using Gemini) ---
    model = genai.GenerativeModel('gemini-1.5-flash')
    # ... (Keep your existing Gemini logic here)
