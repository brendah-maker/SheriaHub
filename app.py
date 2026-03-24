# ... (Keep your imports and Database/IntaSend setup from the previous message)

# Helper to call Gemini
def call_gemini(prompt):
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    return response.text

@app.route('/ask-ai', methods=['POST'])
def ask_ai():
    data = request.json
    user_q = data.get('question')
    category = data.get('category') # 'tenant', 'game', etc.
    checkout_id = data.get('checkout_id')

    # --- CASE 1: THE QUIZ GAME ---
    if category == "game":
        prompt = f"""
        You are 'Sheria Quiz Master'. Generate a multiple-choice question about Kenyan {user_q} law.
        Format:
        Question: [The Question]
        A) [Option]
        B) [Option]
        C) [Option]
        Correct Answer: [Letter]
        Explanation: [Brief why]
        """
        response = call_gemini(prompt)
        return jsonify({"summary": response})

    # --- CASE 2: LEGAL CONSULTATION ---
    # Check if payment is valid for premium content
    is_paid = False
    if checkout_id:
        payment = Payment.query.filter_by(checkout_id=checkout_id, status='paid').first()
        if payment:
            is_paid = True

    if is_paid:
        prompt = f"Provide a detailed legal analysis for a Kenyan citizen regarding: {user_q}. Cite specific Kenyan Acts or Sections."
        full_text = call_gemini(prompt)
        return jsonify({"status": "premium", "content": full_text})
    else:
        prompt = f"Provide a 2-sentence brief summary for: {user_q} in the context of Kenyan Law. Do not give detailed advice."
        summary = call_gemini(prompt)
        return jsonify({"status": "free", "summary": summary})

# ... (Keep your /stkpush-game and /check-payment routes)
