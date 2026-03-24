import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app) # Vital for your Vercel-to-Render connection

# --- DB & KEYS ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db").replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(20), default="pending")
    credits = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

client = Groq(api_key=os.getenv("GROQ_API_KEY", "").strip())

@app.route('/')
def home(): return jsonify({"status": "SheriaHub API is Live"}), 200

# --- JUA MECHI ENGINE ---
@app.route('/generate-jua-mechi', methods=['GET'])
def generate_jua_mechi():
    cat = request.args.get("category", "tenant")
    prompt = (
        f"Create a 'Jua Mechi' game for Kenyan {cat} law. Return ONLY a JSON object: "
        "{'contract_html': 'Short text with 3 errors', 'red_flags': ['exact phrase 1', 'phrase 2', 'phrase 3'], "
        "'explanations': ['reason 1', 'reason 2', 'reason 3']}"
    )
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return completion.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- FACT OR FALLACY ENGINE ---
@app.route('/get-fact-fallacy', methods=['GET'])
def get_fact_fallacy():
    cat = request.args.get("category", "traffic")
    prompt = (
        f"Generate a 'Fact or Fallacy' for Kenyan {cat} law. Return ONLY JSON: "
        "{'statement': 'The claim', 'is_fact': true/false, 'explanation': 'The legal truth'}"
    )
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return completion.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- CONSULTATION ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.get_json()
    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": "You are a Kenyan legal expert. Summarize the answer simply."}, 
                      {"role": "user", "content": data.get("question")}]
        )
        return jsonify({"summary": res.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
