import time
import requests
import numpy as np

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
            res = requests.post('http://127.0.0.1:8000/ingest', json=payload)
            # if dropped due to lock during hot-swap, we simply hold the tick
            if res.json().get('status') == 'dropped':
                time.sleep(0.05)
                continue
            
            tick += 1
            if tick >= total_len:
                tick = 0
                
            print(f"\r[SIMULATOR] Streaming tick {tick}/{total_len} to {current_dataset}", end='')
            time.sleep(0.05)
            
        except requests.exceptions.ConnectionError:
            print("\rWaiting for API to boot...", end='')
            time.sleep(1)

if __name__ == "__main__":
    simulate_stream()
