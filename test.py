from deepface import DeepFace
import numpy as np
try:
    img = np.zeros((224, 224, 3), dtype=np.uint8)
    res = DeepFace.analyze(img, actions=['age', 'gender'], enforce_detection=False, silent=True)
    print("Type:", type(res))
    if isinstance(res, list):
        print("List length:", len(res))
        if len(res) > 0:
            print("First item keys:", res[0].keys())
    elif isinstance(res, dict):
        print("Dict keys:", res.keys())
    else:
        print("Result:", res)
except Exception as e:
    print("Error:", e)
