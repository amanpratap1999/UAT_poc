import os
import time
from pathlib import Path
from dotenv import load_dotenv
import moondream as md
from PIL import Image

def run_test():
    load_dotenv()
    api_key = os.getenv("MOONDREAM_API_KEY")
    if not api_key:
        print("Error: MOONDREAM_API_KEY not found in .env")
        return
        
    img_path = Path("screenshots/before_perception_24167.png")
    if not img_path.exists():
        print(f"Error: Could not find screenshot at {img_path}")
        return

    print("=== Moondream Isolated Grounding Test ===")
    
    # Load image and get dims
    try:
        img = Image.open(img_path)
        width, height = img.size
        print(f"Image loaded: {width}x{height} pixels")
    except Exception as e:
        print(f"Failed to load image: {e}")
        return

    # Initialize client
    try:
        model = md.vl(api_key=api_key)
        # Encode image
        t0 = time.time()
        encoded_image = model.encode_image(img)
        print(f"Image encoded in {time.time() - t0:.2f}s")
    except Exception as e:
        print(f"Failed to initialize or encode: {e}")
        return

    target = "Show Password"
    print(f"\n--- Testing point() for '{target}' ---")
    try:
        t0 = time.time()
        point_res = model.point(encoded_image, target)
        latency = time.time() - t0
        print(f"Latency: {latency:.2f}s")
        print(f"Response: {point_res}")
        
        # Verify coordinates
        if point_res and "x" in point_res and "y" in point_res:
            x = point_res["x"] * width
            y = point_res["y"] * height
            is_valid = (0 <= x <= width) and (0 <= y <= height)
            print(f"Mapped Coords: ({x:.1f}, {y:.1f})")
            print(f"Coordinates Valid: {is_valid}")
        elif hasattr(point_res, 'points'): # If it's an object with attributes
             if len(point_res.points) > 0:
                 pt = point_res.points[0]
                 x = pt.x * width
                 y = pt.y * height
                 is_valid = (0 <= x <= width) and (0 <= y <= height)
                 print(f"Mapped Coords: ({x:.1f}, {y:.1f})")
                 print(f"Coordinates Valid: {is_valid}")
        elif isinstance(point_res, dict) and "points" in point_res:
             pts = point_res["points"]
             if len(pts) > 0:
                 pt = pts[0]
                 x = pt["x"] * width
                 y = pt["y"] * height
                 is_valid = (0 <= x <= width) and (0 <= y <= height)
                 print(f"Mapped Coords: ({x:.1f}, {y:.1f})")
                 print(f"Coordinates Valid: {is_valid}")
             else:
                 print("No points found.")
        elif hasattr(point_res, 'point'):
             if point_res.point:
                 for pt in point_res.point:
                     x = pt.x * width
                     y = pt.y * height
                     is_valid = (0 <= x <= width) and (0 <= y <= height)
                     print(f"Mapped Coords: ({x:.1f}, {y:.1f})")
                     print(f"Coordinates Valid: {is_valid}")
                     break

    except Exception as e:
        print(f"point() failed: {e}")

    print(f"\n--- Testing detect() for '{target}' ---")
    try:
        t0 = time.time()
        detect_res = model.detect(encoded_image, target)
        latency = time.time() - t0
        print(f"Latency: {latency:.2f}s")
        print(f"Response: {detect_res}")
        
        # Verify bounding box
        if hasattr(detect_res, 'objects') and len(detect_res.objects) > 0:
            box = detect_res.objects[0]
            xmin = box.x_min * width
            ymin = box.y_min * height
            xmax = box.x_max * width
            ymax = box.y_max * height
            is_valid = (0 <= xmin <= xmax <= width) and (0 <= ymin <= ymax <= height)
            print(f"Mapped BBox: ({xmin:.1f}, {ymin:.1f}) to ({xmax:.1f}, {ymax:.1f})")
            print(f"BBox Valid: {is_valid}")
        elif isinstance(detect_res, dict) and "objects" in detect_res:
            objs = detect_res["objects"]
            if len(objs) > 0:
                 box = objs[0]
                 xmin = box["x_min"] * width
                 ymin = box["y_min"] * height
                 xmax = box["x_max"] * width
                 ymax = box["y_max"] * height
                 is_valid = (0 <= xmin <= xmax <= width) and (0 <= ymin <= ymax <= height)
                 print(f"Mapped BBox: ({xmin:.1f}, {ymin:.1f}) to ({xmax:.1f}, {ymax:.1f})")
                 print(f"BBox Valid: {is_valid}")
    except Exception as e:
        print(f"detect() failed: {e}")

if __name__ == '__main__':
    run_test()
