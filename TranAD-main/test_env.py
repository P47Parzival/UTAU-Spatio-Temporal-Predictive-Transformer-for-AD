import sys
import traceback

print("Python:", sys.version)

try:
    import torch
    print("PyTorch:", torch.__version__)
    print("CUDA:", torch.cuda.is_available())
except Exception as e:
    print("TORCH FAILED:", e)
    traceback.print_exc()

try:
    import dgl
    print("DGL:", dgl.__version__)
except Exception as e:
    print("DGL FAILED:", e)
    traceback.print_exc()
