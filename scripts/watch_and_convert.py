#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "watchdog",
# ]
# ///

import time
import os
import subprocess
import argparse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Default paths
DEFAULT_WATCH_PATH = r"C:\Users\bjoern\Saved Games\DCS\Liveries\Mi-24P\Clipped Hussars\tmp"
DEFAULT_OUTPUT_PATH = r"C:\Users\bjoern\Saved Games\DCS\Liveries\Mi-24P\Clipped Hussars"
COMPRESSION = "bc7"  # Options: bc1, bc3, bc7, etc.
NVCOMPRESS_PATH = r"C:\Program Files\NVIDIA Corporation\NVIDIA Texture Tools\nvcompress.exe"

class PNGHandler(FileSystemEventHandler):
    def __init__(self, output_path):
        self.output_path = output_path

    def on_modified(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.png'):
            self.convert(event.src_path)

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.png'):
            self.convert(event.src_path)

    def convert(self, src_path):
        base = os.path.splitext(os.path.basename(src_path))[0]
        out_file = os.path.join(self.output_path, base + ".dds")
        print(f"Converting: {src_path} -> {out_file}")
        try:
            # Using NVIDIA Texture Tools (nvcompress) with full path
            result = subprocess.run([
                NVCOMPRESS_PATH, f"-{COMPRESSION}", src_path, out_file
            ], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✓ Successfully converted {src_path}")
            else:
                print(f"✗ Failed to convert {src_path}: {result.stderr}")
        except FileNotFoundError:
            print(f"Error: nvcompress not found at {NVCOMPRESS_PATH}")
            print("Please check the installation path.")
        except Exception as e:
            print(f"Error: {e}")

def parse_arguments():
    parser = argparse.ArgumentParser(description='Watch for PNG files and convert them to DDS format')
    parser.add_argument('--watch-path', '-w', 
                       default=DEFAULT_WATCH_PATH,
                       help=f'Path to watch for PNG files (default: {DEFAULT_WATCH_PATH})')
    parser.add_argument('--output-path', '-o',
                       default=DEFAULT_OUTPUT_PATH,
                       help=f'Path to save converted DDS files (default: {DEFAULT_OUTPUT_PATH})')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    
    # Validate paths
    if not os.path.exists(args.watch_path):
        print(f"Error: Watch path does not exist: {args.watch_path}")
        exit(1)
    
    os.makedirs(args.output_path, exist_ok=True)
    
    event_handler = PNGHandler(args.output_path)
    observer = Observer()
    observer.schedule(event_handler, args.watch_path, recursive=False)
    observer.start()
    print(f"Watching {args.watch_path} for PNG changes. Press Ctrl+C to stop.")
    print(f"Output directory: {args.output_path}")
    print(f"Using compression: {COMPRESSION}")
    print(f"Using nvcompress: {NVCOMPRESS_PATH}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join() 