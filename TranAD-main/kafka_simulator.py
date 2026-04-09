import requests
import numpy as np
import time

DATASET = 'SMD'
test_arr = np.load(f'processed/{DATASET}/machine-1-1_test.npy')
labels_arr = np.load(f'processed/{DATASET}/machine-1-1_labels.npy')

print(f"Loaded {len(test_arr)} telemetry rows from {DATASET}.")
print("Starting live Kafka-simulated streaming ingestion...")

url = "http://localhost:8000/ingest"

# We start pushing data tick by tick
for i in range(len(test_arr)):
    sensors = test_arr[i].tolist()
    
    payload = {
        "timestamp_ms": int(time.time() * 1000),
        "sensors": sensors
    }
    
    try:
        response = requests.post(url, json=payload, timeout=2)
        if i % 100 == 0:
            print(f"[{i}/{len(test_arr)}] -> Ingested frame successfully.")
    except Exception as e:
        print(f"Error connecting to ingest server: {e}")
        
    # Simulate a streaming 10 Hz frequency limit (100ms gap)
    time.sleep(0.1)
