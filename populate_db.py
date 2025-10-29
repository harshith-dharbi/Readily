import os
import re
import pdfplumber
import pymongo
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
MONGO_URI = os.getenv("MONGO_URI")
DATABASE_NAME = "readily_db"
COLLECTION_NAME = "policies"
POLICY_DIR = "policy_documents"

def get_mongo_client():
    """Establishes connection to MongoDB."""
    if not MONGO_URI:
        print("Error: MONGO_URI environment variable not set.")
        return None
    try:
        client = pymongo.MongoClient(MONGO_URI)
        client.admin.command('ping')
        print("MongoDB connection successful.")
        return client
    except ConnectionFailure as e:
        print(f"MongoDB connection failed: {e}")
        return None

def populate_database():
    """
    (NEW) Populates the MongoDB database with one document PER PAGE.
    This allows us to retrieve page numbers.
    """
    client = get_mongo_client()
    if not client:
        return

    db = client[DATABASE_NAME]
    collection = db[COLLECTION_NAME]

    # 1. Clear all old data
    try:
        collection.delete_many({})
        print("Clearing old data... Done.")
    except Exception as e:
        print(f"Error clearing collection: {e}")
        return

    # 2. Walk through all sub-folders and find PDFs
    print(f"Searching for PDFs in '{POLICY_DIR}'...")
    pdf_files = []
    for root, _, files in os.walk(POLICY_DIR):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))

    if not pdf_files:
        print(f"No PDF files found in '{POLICY_DIR}'.")
        return

    # 3. (NEW) Loop through each file, then each page, and insert per-page.
    documents_to_insert = []
    for pdf_path in pdf_files:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Get the filename (e.g., "GG.1508.pdf")
                base_filename = os.path.basename(pdf_path)
                
                for page in pdf.pages:
                    text = page.extract_text(x_tolerance=2)
                    if text:
                        # Create a document for this specific page
                        doc = {
                            "filename": base_filename,
                            "page_number": page.page_number,
                            "content": text.strip()
                        }
                        documents_to_insert.append(doc)
                        
        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")
            
    # 4. Insert all new documents at once
    if not documents_to_insert:
        print("No text extracted from any PDFs.")
        return
        
    try:
        collection.insert_many(documents_to_insert)
        print(f"Documents inserted: {len(documents_to_insert)} pages.")
    except Exception as e:
        print(f"Error inserting documents: {e}")
        return

    # 5. (NEW) Re-create the text index on the 'content' field
    # This is critical for searching the new page-based documents.
    try:
        collection.drop_indexes()
        collection.create_index(
            [("content", pymongo.TEXT)],
            name="content_text_index"
        )
        print("Text index created successfully on 'content' field.")
    except Exception as e:
        print(f"Error creating text index: {e}")
        return

    print("Database population complete.")

if __name__ == '__main__':
    populate_database()

