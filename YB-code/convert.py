import os
import re
import uuid
from dotenv import load_dotenv
from supabase import create_client, Client
from thefuzz import process, fuzz
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

# --- Load Environment Variables ---
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RAW_KEY = os.getenv("ENCRYPTION_KEY")

# --- Structural Verification ---
if not all([SUPABASE_URL, SUPABASE_KEY, RAW_KEY]):
    raise ValueError("Missing environment variables in .env file.")

ENCRYPTION_KEY = RAW_KEY.encode('utf-8')
if len(ENCRYPTION_KEY) != 32:
    raise ValueError(f"ENCRYPTION_KEY must be exactly 32 bytes. Current length: {len(ENCRYPTION_KEY)} bytes.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helper Functions ---
def normalize_german(text):
    """Normalizes German characters for easier fuzzy matching."""
    if not text: return ""
    replacements = {
        'ß': 'ss', 'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
    }
    for search, replace in replacements.items():
        text = text.replace(search, replace)
    return text

def clean_filename(filename):
    """Removes extension, converts _ to space, removes numbers."""
    name = os.path.splitext(filename)[0]
    name = name.replace('_', ' ')
    name = re.sub(r'\d+', '', name).strip()
    return name

def encrypt_file(input_path, output_path, key):
    """Encrypts a file using AES-256-GCM to prevent padding oracle attacks."""
    # AES-GCM standard uses a 12-byte initialization vector (nonce)
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    
    with open(input_path, 'rb') as f:
        file_data = f.read()
        
    # Encrypt data and generate a 16-byte authentication tag
    ciphertext, tag = cipher.encrypt_and_digest(file_data)
    
    # Prepend Nonce (12 bytes) and Tag (16 bytes) to the encrypted payload
    # Total metadata header overhead = 28 bytes
    with open(output_path, 'wb') as f:
        f.write(nonce + tag + ciphertext)

# --- Main Logic ---
def process_images():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_base_dir = os.path.join(base_dir, 'images')
    
    success_count = 0
    not_found_list = []
    
    if not os.path.exists(output_base_dir):
        os.makedirs(output_base_dir)

    for folder_name in os.listdir(base_dir):
        folder_path = os.path.join(base_dir, folder_name)
        
        if not os.path.isdir(folder_path) or folder_name == 'images' or folder_name.startswith('.'):
            continue
            
        current_class = folder_name
        section_match = re.match(r'(\d+)', current_class)
        if not section_match:
            continue
        section = section_match.group(1).zfill(2)

        for filename in os.listdir(folder_path):
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue

            image_path = os.path.join(folder_path, filename)
            cleaned_name = clean_filename(filename)
            normalized_search_name = normalize_german(cleaned_name)

            print(f"Processing: {filename} -> Searched as: {cleaned_name}")

            response = supabase.table('maindata').select('*').ilike('Class', f'{section}%').execute()
            section_records = response.data

            if not section_records:
                print(f"No database records found for section {section}. Skipping.")
                not_found_list.append({"name": cleaned_name, "class": current_class})
                continue

            expected_db_class = current_class
            if not re.match(r'^\d{2}', current_class):
                expected_db_class = section + current_class[len(section_match.group(1)):]

            exact_class_records = [r for r in section_records if r.get('Class') == expected_db_class]
            best_match_record = None
            
            for record in exact_class_records:
                db_name_norm = normalize_german(record.get('Name'))
                if db_name_norm.lower() == normalized_search_name.lower():
                    best_match_record = record
                    break
            
            if not best_match_record:
                db_name_map = {normalize_german(r.get('Name')): r for r in section_records}
                db_names_list = list(db_name_map.keys())
                
                match_result = process.extractOne(normalized_search_name, db_names_list, scorer=fuzz.token_sort_ratio)
                
                if match_result:
                    best_match_name, score = match_result[0], match_result[1]
                    if score >= 80: 
                        best_match_record = db_name_map[best_match_name]

            if best_match_record:
                actual_class = best_match_record.get('Class')
                record_id = best_match_record.get('id') 
                
                class_output_dir = os.path.join(output_base_dir, actual_class)
                os.makedirs(class_output_dir, exist_ok=True)
                
                # Strip file extensions from output name for absolute metadata privacy
                new_uuid = str(uuid.uuid4())
                output_filename = f"{new_uuid}.enc" 
                output_path = os.path.join(class_output_dir, output_filename)
                
                encrypt_file(image_path, output_path, ENCRYPTION_KEY)
                
                supabase.table('maindata').update({
                    'YearbookPhoto': new_uuid,
                    'YearbookName': cleaned_name
                }).eq('id', record_id).execute()
                
                print(f"Success: Matched '{cleaned_name}' to '{best_match_record.get('Name')}' in class {actual_class}")
                success_count += 1
            else:
                print(f"Failed: Could not find a suitable match for '{cleaned_name}' in section {section}")
                not_found_list.append({"name": cleaned_name, "class": current_class})

    print("\n" + "="*40)
    print(" 🎉 PROCESSING COMPLETE 🎉 ")
    print("="*40)
    print(f"Successfully Encrypted: {success_count}")
    print(f"Not Found: {len(not_found_list)}")
    
    if not_found_list:
        print("-" * 40)
        print("📝 List of Not Found:")
        for item in not_found_list:
            print(f"  • {item['name']} (Folder: {item['class']})")
    print("="*40 + "\n")

if __name__ == "__main__":
    process_images()
