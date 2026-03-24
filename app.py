import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import google.generativeai as genai
from intasend import APIService

app = Flask(__name__)
CORS(app)

# 1. FIXED: Correct SQLAlchemy Config Key
# The key is 'SQLALCHEMY_DATABASE_URI', not 'DATABASE_DATABASE_URI'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Payment Model
class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    checkout_id = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending')
    amount = db.Column(db.Integer)
    phone = db.Column(db.String(20))

# Initialize External Services
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Use 'test=True' for development, 'test=False' for live
service = APIService(
    token=os.environ.get("INTASEND_API_KEY"),
    publishable_key=os.environ.get("INTASEND_PUBLISHABLE_KEY"),
    test_mode=False 
)

@app.route('/stkpush-game', methods=['POST'])
def stkpush_game():
    data = request.json
    phone = data.get('phone')
    
    try:
        # 2. FIXED: IntaSend SDK syntax
        # Using service.collect.mpesa_stk_push (no brackets on collect)
        response = service.collect.mpesa_stk_push(
            phone_number=phone,
            amount=20,
            narrative="SheriaHub Unlimited"
        )
        
        # IntaSend returns 'invoice' object containing the 'id'
        checkout_id = response.get('id') or response.get('invoice', {}).get('invoice_id')
        
        if not checkout_id:
            return jsonify({"error": "Failed to generate checkout ID"}), 400

        new_payment = Payment(checkout_id=checkout_id, amount=20, phone=phone)
        db.session.add(new_payment)
        db.session.commit()
        
        return jsonify({"checkout_id": checkout_id}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/check-payment/<checkout_id>', methods=['GET'])
def check_payment(checkout_id):
    try:
        # 3. FIXED: IntaSend status check syntax
        status_resp = service.collect.status(invoice_id=checkout_id)
        
        # Dig into the invoice object for the state
        invoice = status_resp.get('invoice', {})
        state = invoice.get('state', 'PENDING').upper()
        
        payment = Payment.query.filter_by(checkout_id=checkout_id).first()
        
        if not payment:
            return jsonify({"status": "not_found"}), 404

        if state == 'COMPLETE':
            payment.status = 'paid'
            db.session.commit()
            return jsonify({"status": "paid"}), 200
        
        # If the API says it's failed, update DB accordingly
        if state in ['FAILED', 'CANCELLED']:
            payment.status = 'failed'
            db.session.commit()
            return jsonify({"status": "failed"}), 200
            
        return jsonify({"status": "pending"}), 200
    except Exception as e:
        print(f"Error checking status: {e}")
        return jsonify({"status": "pending"}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
