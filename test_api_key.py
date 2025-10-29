import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables (GEMINI_API_KEY)
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("--- FAILED ---")
    print("Error: Could not find GEMINI_API_KEY in your .env file.")
    print("Please make sure your .env file is in the same folder and has your key.")
    exit()

print("Found API key. Attempting to connect to Google AI Studio...")

try:
    # 1. Configure the key
    genai.configure(api_key=API_KEY)
    
    # 2. Select the model (gemini-pro is a safe bet)
    model = genai.GenerativeModel('gemini-pro')
    
    # 3. Send a simple test prompt
    print("Sending test prompt 'Hello' to gemini-pro...")
    response = model.generate_content("Hello")
    
    # 4. Check response
    if response.text:
        print("\n--- SUCCESS! ---")
        print(f"Your API key is working. Gemini responded: {response.text}")
    else:
        print("\n--- FAILED ---")
        print("Authentication succeeded, but the response was empty.")
        print(f"Full response details: {response}")

except Exception as e:
    print("\n--- FAILED ---")
    print("An error occurred. This usually means your API key is invalid or has restrictions.")
    print("\n--- Full Error Message ---")
    print(e)
    print("--------------------------")
