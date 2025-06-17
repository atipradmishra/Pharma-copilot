import os
import sqlite3
import openai
from flask import Flask, request, jsonify
from config import DB_NAME, client



def get_context_from_raw_data(user_message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Basic search, enhance later with similarity logic
    query = f"""
        SELECT id, global_id, name,lifecycle_state,quality_event_type, title,description,origin_site_name,comments
        FROM raw_data
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return "No relevant data found."
    context = "\n".join(" | ".join(map(str, row)) for row in rows)
    return context

# Function to generate response from OpenAI

def generate_rag_response(user_message):
    context = get_context_from_raw_data(user_message)
    prompt = f"""
    You are a pharma product complain analyst. your job is to analyze user quires and provide your response in concrete and concise manner. Answer the user's question precisely using only the data provided above. Provide clear, concise explanations with specific numbers when available.
    Use the following data context to answer the user's question:

    Data:
    {context}

    Question: {user_message}
    Answer:
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating response: {e}"

# @app.route("/rag-chat/api", methods=["POST"])
# def rag_chat_api():
#     data = request.get_json()
#     user_message = data.get("message")
#     rag_response = generate_rag_response(user_message)
#     return jsonify({"response": rag_response})
