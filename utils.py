from sqlquery import run_orchestrated_agent


def query_sqlite_json_with_openai(user_question,bot_prompt_instr):

    # Ensure conversation_history exists in session state
    if not hasattr(st.session_state, 'conversation_history'):
        st.session_state.conversation_history = []
    
    if not hasattr(st.session_state, 'conversation'):
        st.session_state.conversation = [{"role": "system", "content": "You are a helpful assistant."}]
        
    # Step 0: Load your business glossary
    # business_dict = load_business_context()

    # Step 1: Feedback / FAISS
    # feedback_data = load_feedback_data()
    # faiss_index, feedback_data_indexed = create_faiss_index(feedback_data)
    # feedback_insights = retrieve_feedback_insights(
    #     user_question, faiss_index, feedback_data_indexed
    # )

    # Step 2: Orchestrated SQL (single or multi-query)
    result, is_multi = run_orchestrated_agent(user_question, conversation_history=st.session_state.conversation_history)

    if is_multi:
        all_context = result["synthesis"]
    else:
        if "error" in result:
            all_context = f"Error in SQL query: {result['error']}"
        elif "columns" not in result or "rows" not in result:
            all_context = "Error: SQL query returned an unexpected structure"
        else:
            # simple table: columns + rows
            cols = result["columns"]
            rows = result["rows"]
            header = " | ".join(cols)
            body = "\n".join(" | ".join(map(str, row)) for row in rows)
            all_context = f"{header}\n{body}"

    all_context_token_count = len(enc.encode(all_context))
    if all_context_token_count > 7090:
        return "We've encountered a data volume limitation while processing your question. The information returned exceeds our current processing capacity (Token Limit). To receive a complete and accurate response, please refine your question with more specific parameters, such as:\n* Narrowing the date range\n* Adding more precise filters\n* Including aggregation terms (sum, average, total)\n* Focusing on specific metrics or dimensions"

    file_names = []
    
    # prompt_Instr = bot_prompt_instr
    # if prompt_Instr == None:
    #     return "⚠️ No Prompt Instruction Found."

    # Step 6: Category context phrase
    category_context = (
        f"for the {category} category"
        if category and category != "All"
        else ""
    )

    # Step 7: Compose the system prompt for the main answer
    context_message = f"""
    📌 VERIFIED FEEDBACK (Authoritative Corrections):
    🗂️ PREPROCESSED DATA (Official Trading Statistics):
    This section contains structured trading data {category_context}.
    {all_context} 

    ⚠️ INSTRUCTION (STRICTLY FOLLOW THESE STEPS — DO NOT IGNORE):
    You are a pharma product complain analyst. your job is to analyze user quires and provide your response in concrete and concise manner. Answer the user's question precisely using only the data provided above. Provide clear, concise explanations with specific numbers when available.
    """

    # Token count for full context
    token_count = len(enc.encode(context_message))
    st.write("🧮 Token count:", token_count)
    # Also display the all_context token count separately
    st.write("🧮 Data context token count:", all_context_token_count)

    # Step 8: Send through your session‐based conversation to get the main answer
    st.session_state.conversation.append({"role": "system", "content": context_message})
    st.session_state.conversation.append({"role": "user", "content": user_question})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=st.session_state.conversation,
        temperature=0.7,
    )
    gpt_answer = response.choices[0].message.content.strip()
    st.session_state.conversation.append({"role": "assistant", "content": gpt_answer})

    # Step 9: Generate recommended follow-up questions in a separate call
    recommendation_prompt = f"""
        📌 VERIFIED FEEDBACK (Authoritative Corrections):
        Use this section as the most accurate reference if it directly answers the question.
        {feedback_text}

        📘 BUSINESS GLOSSARY (Terms & Labels):
        This glossary helps you interpret technical terms into business language when answering user questions.
        reat 'Net open position' questions as the sum of VOLUME_BL for the REPORT_DATE unless the context clearly refers to monetary value, in which case use MKT_VAL_BL + {business_context_text}

        🗂️ PREPROCESSED DATA (Official Trading Statistics):
        This section contains structured trading data {category_context}.
        This Data is CRITICAL: {all_context}

        ⚠️ IMPORTANT CONTEXT PRESERVATION:
        When processing the data results, ALWAYS assume that any filtering conditions mentioned in the original user question (like specific books, traders, commodities, etc.) apply to ALL the data shown in the results, even if column names don't explicitly include these filters.

        Original Question Context: "{user_question}"
        - If the original question filtered by a specific book (e.g., GTUO), assume ALL data in the results is for that book
        - If the original question filtered by commodity, trader, or other dimension, assume ALL data reflects those filters
        - The SQL query engine has already applied these filters, so the data shown is the correct filtered subset


        ⚠️ INSTRUCTION (STRICTLY FOLLOW THESE STEPS — DO NOT IGNORE):
        You are an expert Natural Language Query Parser specialized in Energy Trading and Risk Management (ETRM) queries.
        CORE RESPONSIBILITIES:
        1. Query Understanding
        ● Extract key components from natural language queries
        ● Identify temporal references and constraints
        ● Recognize trading-specific terminology
        ● Detect multiple intents within single queries
        2. Parameter Extraction
        ● Identify and normalize:
        ○ Time periods and dates
        ○ Commodities and markets
        ○ Traders and counterparties
        ○ Metrics and measurements
        ○ Comparison requests
        ○ Aggregation levels
        3. Query Intent Recognition Primary intents include:
        ● Position analysis
        ● Market exposure evaluation
        ● Risk assessment
        ● Performance measurement
        ● Compliance checking
        ● Strategic analysis

        Based on the user's previous question: "{user_question}" and the answer that was provided, generate exactly 3 related follow-up questions that would be helpful and relevant. Format them as a numbered list (1, 2, 3).

        DO NOT DEVIATE FROM THESE STEPS. ANSWERS MUST FOLLOW THIS EXACT LOGIC.

        {prompt_Instr}
        """

    recommendation_messages = [
        {"role": "system", "content": recommendation_prompt},
        {"role": "user", "content": f"Previous question: {user_question}\nPrevious answer: {gpt_answer}\n\nSuggest 3 related follow-up questions try to give simple questions."}
    ]

    recommendation_response = client.chat.completions.create(
        model="gpt-4o",
        messages=recommendation_messages,
        temperature=0.7,
    )
    recommended_questions = recommendation_response.choices[0].message.content.strip()

    # Keep history to last 5 messages
    if len(st.session_state.conversation) > 6:
        st.session_state.conversation = (
            [st.session_state.conversation[0]]
            + st.session_state.conversation[-4:]
        )

    # Step 10: Compute confidence and write output
    confidence_score = calculate_confidence_score(0.7, feedback_insights, file_names)
    st.session_state.confidence_score = confidence_score

    with open("query_output.txt", "w", encoding="utf-8") as f:
        f.write("🔹 Extracted Data:\n" + all_context)
        f.write("\n\n🔹 GPT Answer:\n" + gpt_answer)
        f.write("\n\n🔹 Recommended Questions:\n" + recommended_questions)

    # Store the recommended questions for display in the UI
    st.session_state.recommended_questions = recommended_questions
    
    # NEW: Log the conversation to a separate log file
    full_response = gpt_answer + "\n\n" + "You might also want to ask:\n" + recommended_questions
    
    return full_response