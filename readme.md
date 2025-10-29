Readily Compliance Audit Tool

This web app analyzes audit questions (from an uploaded PDF) against internal policy documents (stored in MongoDB) using the Gemini AI API to determine compliance status and provide evidence.

Tech Stack

Backend: Python, Flask

Database: MongoDB Atlas

AI Model: Google Gemini (google-generativeai)

Frontend: HTML, Tailwind CSS, JavaScript

Quick Setup & Run

1. Prerequisites:
* Python 3.x, pip

2. Get Code & Setup Environment:
* Place project files in a folder.
* Open terminal in the folder.
* python3 -m venv venv
* source venv/bin/activate (macOS/Linux) or .\venv\Scripts\activate (Windows)
* pip install -r requirements.txt

3. Configure MongoDB Atlas:
* Create a free M0 cluster on MongoDB Atlas.
* Create a Database User (note username/password).
* Add 0.0.0.0/0 to Network Access IP list.
* Get the Connection String (URI).

4. Configure Environment (.env file):
* Create a file named .env in the project root.
* Add your Gemini API key and MongoDB URI:
ini GEMINI_API_KEY=AIzaSy...your_key... MONGO_URI=mongodb+srv://<username>:<password>@<cluster_address>/readily_db?retryWrites=true&w=majority USE_SNIPPET_RETRIEVAL=false # Recommended setting 
* Replace placeholders with your actual credentials.

5. Add Policy Documents:
* Create a folder named policy_documents.
* Place all your policy PDF files inside this folder (subfolders are okay).

6. Populate Database (Run Once):
* Make sure (venv) is active.
* Run: python3 populate_db.py
* Wait for it to complete ("Database population complete.").

7. Run the App:
* Make sure (venv) is active.
* Run: flask --app app run
* Open your browser to http://127.0.0.1:5000.

Usage

Upload an audit questions PDF.

Click "Start Analysis".

View results (MET/NOT MET status and evidence with page numbers).

Use "Print Report" or "Start Over".