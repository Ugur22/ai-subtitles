"""
GPU Memory Management Utilities

Provides utilities for monitoring and managing GPU memory usage
during model loading and inference.
"""

import torch
import gc


def log_gpu_memory(label: str = ""):
    """
    Log current GPU memory usage.

    Args:
        label: Optional label to identify the logging point
    """
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3  # GB
        reserved = torch.cuda.memory_reserved() / 1024**3    # GB
        max_allocated = torch.cuda.max_memory_allocated() / 1024**3  # GB

        print(f"[GPU Memory {label}] Allocated: {allocated:.2f}GB, Reserved: {reserved:.2f}GB, Max: {max_allocated:.2f}GB")
    else:
        print(f"[GPU Memory {label}] No CUDA GPU available")


def clear_gpu_memory(label: str = ""):
    """
    Clear GPU memory cache and run garbage collection.

    Args:
        label: Optional label to identify the cleanup point
    """
    if torch.cuda.is_available():
        print(f"[GPU Cleanup {label}] Clearing GPU cache...")
        log_gpu_memory(f"{label}:Before")

        # Force garbage collection
        gc.collect()

        # Clear CUDA cache
        torch.cuda.empty_cache()

        log_gpu_memory(f"{label}:After")
    else:
        # Still run garbage collection for CPU memory
        gc.collect()
        print(f"[GPU Cleanup {label}] No CUDA GPU available, ran garbage collection")
