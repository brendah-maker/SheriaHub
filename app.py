import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app)

# --- DATABASE CONFIG ---
uri = os.getenv("DATABASE_URL", "sqlite:///sheriahub.db")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Payment(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(20), default="pending")
    credits = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()

# --- KEYS ---
client = Groq(api_key=os.getenv("GROQ_API_KEY", "").strip())
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY", "").strip()
INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY", "").strip()
IS_SANDBOX = os.getenv("IS_SANDBOX", "True").lower() == "true"
BASE_URL = "https://sandbox.intasend.com/api/v1" if IS_SANDBOX else "https://api.intasend.com/api/v1"

# --- GAME 1: JUA MECHI (RED FLAGS) ---
@app.route('/generate-jua-mechi', methods=['GET'])
def generate_jua_mechi():
    cat = request.args.get("category", "tenant")
    prompt = (
        f"Create a 'Jua Mechi' game for Kenyan {cat} law. Return ONLY a JSON object: "
        "{'contract_html': 'text with 3 errors', 'red_flags': ['exact phrase 1', 'phrase 2', 'phrase 3'], "
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

# --- GAME 2: FACT OR FALLACY ---
@app.route('/get-fact-fallacy', methods=['GET'])
def get_fact_fallacy():
    cat = request.args.get("category", "traffic")
    prompt = (
        f"Generate a 'Fact or Fallacy' challenge for Kenyan {cat} law. Return ONLY JSON: "
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

# --- CORE AI & PAYMENTS ---
@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.get_json()
    msg = f"SUMMARY: short answer. DEEP_DIVE: detailed Kenyan law for {data.get('category')}."
    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": msg}, {"role": "user", "content": data.get("question")}]
        )
        return jsonify({"summary": res.choices[0].message.content.split("DEEP_DIVE:")[0].replace("SUMMARY:","").strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
