import os
import requests
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# SYSTEM PROMPT FOR JSON OUTPUT
GAME_PROMPT = """
You are a game engine for 'Nairobi Survival'. 
Provide a random high-stakes street scenario in Nairobi (Traffic, Landlords, Touts, Kanjo, or Scammers).
You MUST return ONLY a JSON object in this exact format:
{
  "scene": "Short 1-sentence situation (max 12 words)",
  "A": "Short option (max 4 words)",
  "B": "Short option (max 4 words)",
  "resultA": {"text": "1-sentence outcome", "money": -500, "life": 0},
  "resultB": {"text": "1-sentence outcome", "money": 0, "life": -1}
}
Keep it witty, Kenyan, and brief. No extra text.
"""

@app.route('/game-step', methods=['POST'])
def game_step():
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": GAME_PROMPT}],
            response_format={"type": "json_object"} # Forces JSON
        )
        return completion.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Keep your existing /ask-ai and /stkpush routes here...
# (Omitted for brevity, but keep them in your file)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
