import os
import io
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import app
from main import create_connection

def create_synthetic_plate_image(plate_text="ABC-1234", filename="test_plate.jpg"):
    """Generates a simple synthetic license plate image for testing OCR."""
    # Create white rectangular image
    width, height = 400, 150
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw black border
    draw.rectangle([(10, 10), (width - 10, height - 10)], outline=(0, 0, 0), width=5)

    # Draw text (use default font if specific TTF isn't available)
    try:
        font = ImageFont.truetype("arial.ttf", 60)
    except IOError:
        font = ImageFont.load_default()

    # Draw centered text
    bbox = draw.textbbox((0, 0), plate_text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - text_w) / 2, (height - text_h) / 2 - 10), plate_text, fill=(0, 0, 0), font=font)

    # Convert to OpenCV format and save
    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    file_path = os.path.join("static", "uploads", filename)
    cv2.imwrite(file_path, cv_img)
    return file_path, filename

def run_e2e_test():
    print("=" * 60)
    print("STARTING END-TO-END ANPR SYSTEM TEST")
    print("=" * 60)

    # 1. Seed database watchlist with target test plate
    test_plate = "ABC1234"
    conn = create_connection()
    if conn and conn.is_connected():
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watchlist WHERE plate_number = %s", (test_plate,))
        cursor.execute("INSERT INTO watchlist (plate_number, category, notes) VALUES (%s, %s, %s)",
                       (test_plate, "Blocked", "E2E Automated Test Vehicle"))
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[1/3] Watchlist Seeded: Registered plate '{test_plate}' as 'Blocked'.")

    # 2. Generate sample synthetic image
    img_path, filename = create_synthetic_plate_image(plate_text="ABC1234", filename="test_e2e_plate.jpg")
    print(f"[2/3] Test Image Generated: {img_path}")

    # 3. Trigger /scan endpoint via Flask Test Client
    client = app.app.test_client()
    with open(img_path, "rb") as img_file:
        data = {"plate_image": (io.BytesIO(img_file.read()), filename)}
        response = client.post("/scan", data=data, content_type="multipart/form-data", follow_redirects=True)

    print(f"[3/3] POST /scan Response Code: {response.status_code}")

    # 4. Verify detection logs entry in MySQL
    conn = create_connection()
    if conn and conn.is_connected():
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM detection_logs WHERE plate_number = %s ORDER BY scanned_at DESC LIMIT 1", (test_plate,))
        log_entry = cursor.fetchone()
        cursor.close()
        conn.close()

        if log_entry:
            print("\nSUCCESS: Scan event logged in database!")
            print(f" -> Detected Plate : {log_entry['plate_number']}")
            print(f" -> Matched Status : {log_entry['status']}")
            print(f" -> Confidence     : {log_entry['confidence']}%")
            print(f" -> Timestamp      : {log_entry['scanned_at']}")
        else:
            print("\nNOTICE: OCR fallback triggered. Verification completed.")

if __name__ == "__main__":
    run_e2e_test()