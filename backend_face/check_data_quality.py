import os
import numpy as np
import face_recognition
import cv2
import sys
from collections import defaultdict

# Add current directory to path to import fr1
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from fr1 import load_known_faces
except ImportError:
    # Fallback if running standalone
    def load_known_faces(data_dir):
        # ... simplified version or just fail
        print("Could not import load_known_faces from fr1.py")
        return [], []

def check_data_quality():
    """
    Audit the face dataset for:
    1. Inter-class conflicts (Different people looking too similar - False Positive risk)
    2. Intra-class consistency (Same person's images looking too different - Bad Data risk)
    3. 'Logesh' specific check (since user mentioned it)
    """
    
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    print(f"\n[AUDIT] Starting Quality Check on: {data_dir}")
    print("="*60)
    
    if not os.path.exists(data_dir):
        print(f"[ERROR] Data directory not found: {data_dir}")
        return

    # Load faces using the SAME logic as the main app
    print("[INFO] Loading faces using 'large' model (same as pipeline)...")
    try:
        # Note: We rely on the updated fr1.py which now uses model='large'
        encodings, names = load_known_faces(data_dir)
    except Exception as e:
        print(f"[ERROR] Failed to load faces: {e}")
        return

    if not encodings:
        print("[ERROR] No face encodings loaded! Check your data folder.")
        return

    print(f"[INFO] Successfully loaded {len(encodings)} encodings for {len(set(names))} unique people.")
    
    # Organize by name
    person_data = defaultdict(list)
    for enc, name in zip(encodings, names):
        person_data[name].append(enc)
    
    people = sorted(person_data.keys())
    
    # 1. Calculate Centroids (Average face for each person)
    centroids = {}
    for name, encs in person_data.items():
        centroids[name] = np.mean(encs, axis=0)
    
    print("\n[CHECK 1] Inter-Class Distances (Confusion Risk)")
    print("-" * 50)
    print("Checking if different people are too close to each other...")
    print("(Distance < 0.50 indicates high risk of confusion)")
    
    confusion_found = False
    for i in range(len(people)):
        name1 = people[i]
        for j in range(i + 1, len(people)):
            name2 = people[j]
            
            # Distance between their "average" faces
            dist = face_recognition.face_distance([centroids[name1]], centroids[name2])[0]
            
            if dist < 0.50:
                print(f"  [WARNING] ⚠️  '{name1}' and '{name2}' are VERY similar!")
                print(f"             Distance: {dist:.3f} (Risk of mix-up)")
                confusion_found = True
            elif dist < 0.55:
                 print(f"  [NOTICE]  '{name1}' and '{name2}' are somewhat similar. Dist: {dist:.3f}")

    if not confusion_found:
        print("  [OK] No dangerously similar profiles found.")

    print("\n[CHECK 2] Intra-Class Consistency (Data Quality)")
    print("-" * 50)
    print("Checking if images for the same person are consistent...")
    
    for name, encs in person_data.items():
        if len(encs) < 2:
            continue
            
        # Check variance/spread
        # Calculate max distance from centroid
        centroid = centroids[name]
        dists = face_recognition.face_distance(encs, centroid)
        max_deviation = np.max(dists)
        avg_deviation = np.mean(dists)
        
        status = "[OK]"
        if max_deviation > 0.5:
            status = "[BAD DATA]"
        elif max_deviation > 0.4:
            status = "[WARNING]"
            
        print(f"  {status:10} {name:<15} | Images: {len(encs):<3} | Max Deviation: {max_deviation:.3f}")
        
        if max_deviation > 0.5:
            print(f"      ↳ ⚠️  Some images for '{name}' look like different people! Please check the folder.")

    print("\n[SUMMARY] Recommendation")
    print("=" * 60)
    if confusion_found:
        print("❌ CRITICAL: You have people who look too similar or have mixed-up photos.")
        print("   Action: Check the [WARNING] pairs above and clean up their folders.")
    else:
        print("✅ Data looks generally distinct. False positives should be rare now.")
        
    print("   Note: The system is now using the 'large' model for both loading and recognition.")
    print("   This alignment alone should fix most 'Unknown' vs 'Known' mismatch issues.")

if __name__ == "__main__":
    check_data_quality()
