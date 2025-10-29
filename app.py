import os
import re
import pdfplumber
import pymongo
import concurrent.futures
from flask import Flask, request, render_template, jsonify
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# --- Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
USE_SNIPPET_RETRIEVAL = os.getenv("USE_SNIPPET_RETRIEVAL", "true").lower() == "true"
DATABASE_NAME = "readily_db"
COLLECTION_NAME = "policies"

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
if not MONGO_URI:
    print("Error: MONGO_URI environment variable not set.")

# --- Initialize Gemini ---
try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.0-flash')
    print("Google AI Studio (Gemini) initialized successfully.")
except Exception as e:
    print(f"Error configuring Gemini: {e}")
    gemini_model = None

# --- Database Connection ---
def get_mongo_client():
    """Establishes connection to MongoDB."""
    try:
        client = pymongo.MongoClient(MONGO_URI)
        client.admin.command('ping')
        print("MongoDB connection successful.")
        return client
    except ConnectionFailure as e:
        print(f"MongoDB connection failed: {e}")
        return None
    except Exception as e:
        print(f"An error occurred connecting to MongoDB: {e}")
        return None

# --- Core Logic ---

def extract_questions_from_pdf(file_stream):
    """Extracts questions from an uploaded PDF file."""
    full_text = ""
    try:
        with pdfplumber.open(file_stream) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2)
                if text:
                    full_text += text + "\n"
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return []

    if not full_text:
        print("PDF was empty or unreadable, no questions extracted.")
        return []

    text = re.sub(r"-\s*\n\s*", "", full_text)
    text = re.sub(r"([a-z,;])\s*\n\s*([a-z])", r"\1 \2", text)
    lines = text.split('\n')
    cleaned_lines = []
    prefix_re = re.compile(r"^\s*(\(\s*reference:[^)]+\)|yes\s*no\s*citation:|yes\s*no:|citation:)\s*", re.IGNORECASE)
    for line in lines:
        cleaned_line = prefix_re.sub("", line).strip()
        if cleaned_line:
            cleaned_lines.append(cleaned_line)

    questions = []
    current_question_lines = []
    for line in cleaned_lines:
        current_question_lines.append(line)
        if line.endswith('?'):
            potential_question = " ".join(current_question_lines).strip()
            q_text = re.sub(r"\s+", " ", potential_question).strip()
            if len(q_text.split()) > 4:
                questions.append(q_text)
            else:
                 print(f"Skipping short/bad question fragment: {q_text}")
            current_question_lines = []
        elif re.match(r"^\s*\d+\.", line) and current_question_lines:
             potential_question_no_q = " ".join(current_question_lines[:-1]).strip()
             if potential_question_no_q and len(potential_question_no_q.split()) > 4 and potential_question_no_q.endswith('.'):
                  print(f"Possible missed question fragment (ignoring): {potential_question_no_q[:100]}...")
             current_question_lines = [line]

    print(f"Extracted {len(questions)} questions using simpler method.")
    return questions

def _tokenize(text):
    """Basic tokenization for snippet matching."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())

def _pick_snippets(content, question, per_doc=3, max_chars_per_snippet=800):
    """Selects relevant text snippets from content based on the question."""
    if not content: return []
    lc_content = content.lower()
    q_toks = _tokenize(question)
    stop = {"the","a","an","and","or","of","to","in","for","on","by","with","is","are","be","as","at","that","this","it","from"}
    q_toks_nostop = [t for t in q_toks if t not in stop]
    phrases = set()
    for n in (5, 4, 3):
        for i in range(0, max(0, len(q_toks_nostop) - n + 1)):
            phrases.add(" ".join(q_toks_nostop[i:i + n]))

    windows = []
    for ph in phrases:
        if not ph: continue
        idx = lc_content.find(ph)
        if idx != -1:
            start = max(0, idx - 400)
            end = min(len(content), idx + len(ph) + 500)
            windows.append(content[start:end])
            if len(windows) >= per_doc: break
    if windows: return [w[:max_chars_per_snippet] for w in windows]

    paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    if not paras: return []
    q_tokens = set(q_toks)
    def score(p):
        p_tokens = set(_tokenize(p))
        return sum(1 for t in q_tokens if t in p_tokens)
    scored = sorted(paras, key=score, reverse=True)
    return [p[:max_chars_per_snippet] for p in scored[:per_doc]]

def find_relevant_context(question, db):
    """Searches MongoDB for policy pages relevant to the question."""
    collection = db[COLLECTION_NAME]
    try:
        cursor = collection.find(
            {"$text": {"$search": question}},
            {"score": {"$meta": "textScore"}, "content": 1, "filename": 1, "page_number": 1}
        ).sort([("score", {"$meta": "textScore"})]).limit(7)

        context_parts = []
        total_len = 0
        max_total = 18000

        for doc in cursor:
            filename = doc.get("filename", "Unknown Document")
            page_num = doc.get("page_number", "N/A")
            content = doc.get("content", "")
            block_text = ""

            if USE_SNIPPET_RETRIEVAL:
                snippets = _pick_snippets(content, question)
                if snippets:
                    doc_block = [f"--- START (Filename: {filename}, Page: {page_num}) ---"]
                    doc_block.extend(snippets)
                    doc_block.append(f"--- END (Filename: {filename}, Page: {page_num}) ---")
                    block_text = "\n\n".join(doc_block) + "\n\n"
            else:
                block_text = f"\n\n--- START (Filename: {filename}, Page: {page_num}) ---\n\n{content}\n\n--- END (Filename: {filename}, Page: {page_num}) ---\n\n"

            if block_text and (total_len + len(block_text) <= max_total or not context_parts):
                context_parts.append(block_text)
                total_len += len(block_text)
            elif block_text:
                 break # Stop if adding exceeds limit

        context = "".join(context_parts)

        if not context:
            print(f"No relevant context found in DB for question: {question[:80]}...")
            return "No relevant policy documents found."

        print(f"Context length: {len(context)} for question: {question[:80]} | snippets={'on' if USE_SNIPPET_RETRIEVAL else 'off'}")
        return context
    except Exception as e:
        print(f"Error during MongoDB search: {e}")
        return "Error searching database."

def analyze_question_with_gemini(question, db):
    """Analyzes a question against context from the DB using Gemini."""
    if not gemini_model:
        return "Error: Gemini model not initialized.", ""

    context = find_relevant_context(question, db)
    prompt = f"""
    You are a compliance auditor. Your task is to determine if a policy document meets a specific requirement.

    Requirement (Question):
    "{question}"

    Policy Document Excerpts (Context from Database):
    "{context[:12000]}"

    Instructions:
    1. Read the Requirement and Context carefully. Pay attention to Filename and Page markers.
    2. Determine if the Context *fully satisfies* the Requirement.
    3. If the Requirement is vague or nonsensical, respond "STATUS: Not Met".
    4. Respond ONLY in the following exact format:
        STATUS: Met|Not Met
        EVIDENCE: (From Filename: <file>, Page: <page_num>) "<exact quote>"    [ONLY if Met]
    5. If Met, quote the exact text and cite the filename AND page number.

    Example Response (Met):
    STATUS: Met
    EVIDENCE: (From Filename: GG.1508_v2.pdf, Page: 10) "For a retrospective request... no later than fourteen (14) calendar days..."

    Example Response (Not Met):
    STATUS: Not Met

    Begin analysis.
    """
    try:
        response = gemini_model.generate_content(prompt)
        return response.text or "Error: AI generated an empty response.", context
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return f"Error: Could not analyze question. {e}", context

def parse_gemini_response(text, context):
    """Parses the raw Gemini response to find Status and Evidence."""
    status = "Not Met"
    evidence = "N/A"
    try:
        status_match = re.search(r'STATUS:\s*Met', text, re.IGNORECASE)
        if status_match:
            status = "Met"
            evidence_match = re.search(r'EVIDENCE:(.*)', text, re.IGNORECASE | re.DOTALL)
            if evidence_match:
                evidence_text = evidence_match.group(1).strip()
                if evidence_text:
                    quote_match = re.search(r'(["“])(.*?)(?:["”])', evidence_text, re.DOTALL)
                    quote_text = quote_match.group(2).strip() if quote_match else ""
                    cite_match = re.search(r'\(\s*From\s+Filename:\s*([^,]+?)\s*,\s*Page:\s*(\d+)\s*\)', evidence_text, re.IGNORECASE)
                    found_fname = cite_match.group(1).strip() if cite_match else None
                    found_page = cite_match.group(2).strip() if cite_match else None

                    actual_fname, actual_page = found_fname, found_page
                    if quote_text and context:
                        block_re = re.compile(r"--- START \(Filename: ([^,]+), Page: (\d+)\) ---\n\n([\s\S]*?)--- END \(Filename: \1, Page: \2\) ---", re.MULTILINE | re.IGNORECASE)
                        best_match_score = -1
                        for m in block_re.finditer(context):
                            fname, page, block = m.groups()
                            norm_block = re.sub(r"\s+", " ", block).lower()
                            norm_quote = re.sub(r"\s+", " ", quote_text).lower()
                            if norm_quote and norm_quote in norm_block:
                                block_start = norm_block.find(norm_quote)
                                if block_start != -1:
                                    score = 1.0 / (block_start + 1)
                                    if score > best_match_score:
                                        best_match_score = score
                                        actual_fname, actual_page = fname, page

                    if quote_text and actual_fname and actual_page:
                        evidence = f"(From Filename: {actual_fname}, Page: {actual_page}) \"{quote_text}\""
                    elif quote_text and found_fname and found_page:
                         evidence = f"(From Filename: {found_fname}, Page: {found_page}) \"{quote_text}\""
                    else:
                        evidence = evidence_text
                else:
                    evidence = "Evidence section was found but was empty."
            else:
                evidence = "STATUS was 'Met' but no EVIDENCE: section was found."
        return status, evidence
    except Exception as e:
        print(f"Error parsing Gemini response: {e}")
        return "Error", f"Failed to parse AI response: {e}"

# --- Flask App ---
app = Flask(__name__)
mongo_client = get_mongo_client()
if mongo_client is None:
    print("FATAL: Could not connect to MongoDB.")

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template("index.html")

@app.route('/upload-audit-pdf', methods=['POST'])
def upload_audit_pdf():
    """Handles PDF upload, extracts questions, analyzes them, returns results."""
    if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400
    if not mongo_client: return jsonify({"error": "Database not connected"}), 500
    if not gemini_model: return jsonify({"error": "Gemini model not initialized"}), 500

    try:
        questions = extract_questions_from_pdf(file.stream)
        if not questions: return jsonify({"error": "Could not extract questions."}), 400

        db = mongo_client.get_database(DATABASE_NAME)

        def analyze_single_question_task(question):
            try:
                text, used_context = analyze_question_with_gemini(question, db)
                print(f"DEBUG: Raw Gemini Response for question '{question[:50]}...': {text}")
                status, evidence = parse_gemini_response(text, used_context)
                return {"question": question, "status": status, "evidence": evidence}
            except Exception as e:
                 print(f"ERROR: Exception in task for '{question[:50]}...': {e}")
                 return {"question": question, "status": "Error", "evidence": f"Analysis failed: {e}"}

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(analyze_single_question_task, questions))

        return jsonify(results)
    except Exception as e:
        print(f"Error during upload/analysis: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)

