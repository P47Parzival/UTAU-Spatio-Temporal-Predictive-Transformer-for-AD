import time
import requests
import numpy as np
import os

STREAM_PERIOD_SEC = float(os.getenv('STREAM_PERIOD_SEC', '1.0'))
DROP_RETRY_BASE_SEC = float(os.getenv('DROP_RETRY_BASE_SEC', '0.2'))
MAX_POST_RETRIES = int(os.getenv('MAX_POST_RETRIES', '3'))

def post_with_retry(url: str, payload: dict, max_retries: int = MAX_POST_RETRIES):
    for attempt in range(max_retries):
        try:
            res = requests.post(url, json=payload, timeout=2)
            if res.status_code != 200:
                time.sleep(DROP_RETRY_BASE_SEC * (2 ** attempt))
                continue
            body = res.json()
            if body.get('status') == 'ingested':
                return True, body
            time.sleep(DROP_RETRY_BASE_SEC * (2 ** attempt))
        except requests.exceptions.RequestException:
            time.sleep(DROP_RETRY_BASE_SEC * (2 ** attempt))
    return False, {"status": "failed", "reason": "max retries exceeded"}

def simulate_stream():
    current_dataset = None
    test_arr = None
    tick = 0
    total_len = 0
    
    print("Initiating IoT Streaming Simulator...")

    while True:
        try:
            # Poll status to detect UI dataset changes every tick
            resp = requests.get('http://127.0.0.1:8000/status')
            if resp.status_code == 200:
                status = resp.json()
                active_dataset = status['active_dataset']
                
                # If a Hot-Swap occurred, intercept and reload physics
                if active_dataset != current_dataset:
                    print(f"\n[SIMULATOR] Dataset change detected -> {active_dataset}. Reloading physical simulation...")
                    
                    if active_dataset == 'SMD':
                        test_arr = np.load(f'processed/{active_dataset}/machine-1-1_test.npy')
                    elif active_dataset == 'MSL':
                        test_arr = np.load(f'processed/{active_dataset}/C-1_test.npy')
                    elif active_dataset == 'SMAP':
                        test_arr = np.load(f'processed/{active_dataset}/A-1_test.npy')
                    elif active_dataset == 'synthetic':
                        test_arr = np.load(f'processed/{active_dataset}/test.npy')
                    else:
                        raise ValueError(f"Unsupported active dataset: {active_dataset}")
                        
                    current_dataset = active_dataset
                    total_len = len(test_arr)
                    tick = 0 # Reset simulation clock to 0
                    
            if test_arr is None:
                time.sleep(1)
                continue
                
            # Stream the active sensor window
            sensor_values = test_arr[tick].tolist()
            payload = {
                "timestamp_ms": int(time.time() * 1000),
                "sensors": sensor_values
            }
            
            # Fire to FastAPI INGEST endpoint
            ok, response = post_with_retry('http://127.0.0.1:8000/ingest', payload)
            # Hold tick for transient drops during hot-swap, then retry same frame.
            if not ok:
                print(f"\n[SIMULATOR] Ingest retry exhausted: {response.get('reason', 'unknown')}")
                time.sleep(STREAM_PERIOD_SEC)
                continue
            
            tick += 1
            if tick >= total_len:
                tick = 0
                
            print(f"\r[SIMULATOR] Streaming tick {tick}/{total_len} to {current_dataset} @ {STREAM_PERIOD_SEC:.2f}s", end='')
            time.sleep(STREAM_PERIOD_SEC)
            
        except requests.exceptions.ConnectionError:
            print("\rWaiting for API to boot...", end='')
            time.sleep(1)

if __name__ == "__main__":
    simulate_stream()
