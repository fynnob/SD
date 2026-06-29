import os
import re
import cv2
import numpy as np
import base64
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Replace 'helloworld' with your actual free key from ocr.space for higher rate limits
OCR_SPACE_API_KEY = 'K81382992088957' 

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_photo', methods=['POST'])
def process_photo():
    try:
        # 1. Get image and group name from frontend
        data = request.json.get('image')
        group_name = request.json.get('group_name', 'DefaultGroup')
        
        # Clean the group name for safe folder creation
        group_name = "".join(x for x in group_name if x.isalnum())
        if not group_name:
            group_name = "DefaultGroup"

        # Decode the base64 image from the browser into an OpenCV matrix
        encoded_data = data.split(',')[1]
        nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 2. Crop and Soft Pre-process (Keep it simple!)
        height, width = img.shape[:2]
        cropped_img = img[int(height * 0.5):height, 0:width]
        
        # FIX: Just use standard grayscale. Do NOT use THRESH_BINARY_INV.
        gray = cv2.cvtColor(cropped_img, cv2.COLOR_BGR2GRAY)

        # 3. Convert the clean grayscale image BACK to base64
        _, buffer = cv2.imencode('.png', gray)
        processed_b64 = base64.b64encode(buffer).decode('utf-8')
        api_b64_string = f"data:image/png;base64,{processed_b64}"

        # 4. Send the request to OCR.space API
        payload = {
            'apikey': OCR_SPACE_API_KEY,
            'base64Image': api_b64_string,
            'language': 'eng',
            'OCREngine': '2',        # FIX: Engine 2 is dramatically more accurate
            'isOverlayRequired': 'false'
        }
        
        response = requests.post('https://api.ocr.space/parse/image', data=payload)
        result_json = response.json()
        
                # 5. Extract and filter the recognized text from the JSON response
        recognized_text = ""
        if not result_json.get('IsErroredOnProcessing'):
            parsed_results = result_json.get('ParsedResults', [])
            if parsed_results:
                raw_text = parsed_results[0].get('ParsedText', '').strip()
                
                # Split text into individual words
                words = raw_text.split()
                
                # FILTER: Only keep words that are NOT completely uppercase
                # (isupper() returns False if the word has lowercase letters like 'Kian' or 'Aust')
                filtered_words = [w for w in words if not w.isupper()]
                
                # Rejoin the filtered words back into a single string
                recognized_text = " ".join(filtered_words)

        # 6. Clean up the name for the file path safely
        if recognized_text:
            # Convert spaces between the kept words into underscores
            clean_name = recognized_text.replace(" ", "_")
            # Strip out any remaining illegal file path characters
            clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '', clean_name)
        else:
            clean_name = "UnknownPerson"

        # 7. Create the folder and save the original full-color image
        os.makedirs(group_name, exist_ok=True)
        filepath = os.path.join(group_name, f"{clean_name}.png")
        cv2.imwrite(filepath, img) 

        return jsonify({
            'status': 'success', 
            'recognized_name': recognized_text if recognized_text else "No text found",
            'saved_path': filepath
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")