import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# SYSTEM PROMPT FOR THE WIDGET GAME
GAME_SYSTEM_PROMPT = """
You are a Nairobi Survival Game engine. 
Provide a random, witty 1-sentence street scenario (Traffic, Landlords, Kanjo, or Scammers).
You MUST return ONLY a JSON object:
{
  "scene": "1-sentence situation (max 10 words)",
  "A": "Option A (max 3 words)",
  "B": "Option B (max 3 words)",
  "resA": {"msg": "Outcome A (10 words)", "cash": -500, "hp": 0},
  "resB": {"msg": "Outcome B (10 words)", "cash": 0, "hp": -1}
}
"""

@app.route('/')
def home():
    return "SheriaHub Widget API is Live!", 200

@app.route('/game-step', methods=['POST'])
def game_step():
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": GAME_SYSTEM_PROMPT}],
            response_format={"type": "json_object"} 
        )
        return completion.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Keep your existing /ask-ai and /stkpush routes below this...
# ...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
