"""Tool to convert WAV files to OGG format using FFmpeg"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from typing import List, Optional


class WavToOggConverter:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        """Check if FFmpeg is available"""
        try:
            result = subprocess.run([self.ffmpeg_path, "-version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print(f"✓ FFmpeg found: {result.stdout.split()[2]}")
                return True
            else:
                print(f"✗ FFmpeg check failed: {result.stderr}")
                return False
        except FileNotFoundError:
            print(f"✗ FFmpeg not found at: {self.ffmpeg_path}")
            print("Please install FFmpeg and ensure it's in your PATH")
            return False
        except Exception as e:
            print(f"✗ Error checking FFmpeg: {e}")
            return False
    
    def convert_file(self, input_file: str, output_file: str, 
                    quality: int = 6, bitrate: Optional[str] = None) -> bool:
        """Convert a single WAV file to OGG format"""
        
        try:
            # Build FFmpeg command
            cmd = [
                self.ffmpeg_path,
                "-i", input_file,
                "-y"  # Overwrite output file
            ]
            
            # Add quality or bitrate settings
            if bitrate:
                cmd.extend(["-b:a", bitrate])
            else:
                cmd.extend(["-q:a", str(quality)])
            
            cmd.append(output_file)
            
            print(f"Converting: {Path(input_file).name}")
            print(f"Command: {' '.join(cmd)}")
            
            # Run FFmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✓ Converted successfully: {Path(output_file).name}")
                return True
            else:
                print(f"✗ FFmpeg error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("✗ FFmpeg process timed out")
            return False
        except Exception as e:
            print(f"✗ Error converting file: {e}")
            return False
    
    def batch_convert(self, input_dir: str, output_dir: str, 
                     quality: int = 6, bitrate: Optional[str] = None,
                     file_pattern: str = "*.wav") -> None:
        """Convert all WAV files in a directory to OGG format"""
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Find all WAV files
        wav_files = list(input_path.glob(file_pattern))
        if not wav_files:
            print(f"No WAV files found matching pattern: {file_pattern}")
            return
        
        print(f"Found {len(wav_files)} WAV files to convert")
        print(f"Quality: {quality}, Bitrate: {bitrate or 'auto'}")
        
        success_count = 0
        error_count = 0
        
        for i, wav_file in enumerate(wav_files, 1):
            print(f"\n[{i}/{len(wav_files)}] Processing: {wav_file.name}")
            
            # Create output filename (replace .wav with .ogg)
            output_file = output_path / f"{wav_file.stem}.ogg"
            
            # Convert file
            if self.convert_file(str(wav_file), str(output_file), quality, bitrate):
                success_count += 1
            else:
                error_count += 1
        
        print(f"\n=== Summary ===")
        print(f"Successfully converted: {success_count} files")
        print(f"Errors: {error_count} files")
        print(f"Total processed: {len(wav_files)} files")
    
    def get_file_info(self, file_path: str) -> Optional[dict]:
        """Get audio file information using FFprobe"""
        try:
            cmd = [
                self.ffmpeg_path.replace("ffmpeg", "ffprobe"),
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
            else:
                return None
                
        except Exception:
            return None


def main():
    parser = argparse.ArgumentParser(description="Convert WAV files to OGG format using FFmpeg")
    parser.add_argument("input", help="Input WAV file or directory")
    parser.add_argument("output", help="Output OGG file or directory")
    parser.add_argument("--quality", type=int, choices=range(0, 11), default=6,
                       help="OGG quality setting (0-10, higher is better, default: 6)")
    parser.add_argument("--bitrate", type=str,
                       help="Target bitrate (e.g., '128k', '256k') - overrides quality setting")
    parser.add_argument("--ffmpeg-path", default="ffmpeg",
                       help="Path to FFmpeg executable (default: ffmpeg)")
    parser.add_argument("--file-pattern", default="*.wav",
                       help="File pattern for batch processing (default: *.wav)")
    parser.add_argument("--batch", action="store_true",
                       help="Process input as directory (batch mode)")
    parser.add_argument("--info", action="store_true",
                       help="Show file information before conversion")
    
    args = parser.parse_args()
    
    # Initialize converter
    converter = WavToOggConverter(args.ffmpeg_path)
    
    # Determine if input is directory or file
    is_directory = os.path.isdir(args.input)
    is_file = os.path.isfile(args.input)
    
    if args.batch or is_directory:
        # Batch processing mode
        if not is_directory:
            print(f"Error: Input must be a directory when using --batch mode")
            sys.exit(1)
        
        converter.batch_convert(args.input, args.output, args.quality, 
                              args.bitrate, args.file_pattern)
    else:
        # Single file processing mode
        if not is_file:
            print(f"Error: Input file not found: {args.input}")
            sys.exit(1)
        
        # Show file info if requested
        if args.info:
            info = converter.get_file_info(args.input)
            if info:
                print(f"File information for: {args.input}")
                if 'format' in info:
                    format_info = info['format']
                    print(f"  Duration: {format_info.get('duration', 'Unknown')} seconds")
                    print(f"  Size: {format_info.get('size', 'Unknown')} bytes")
                    print(f"  Bitrate: {format_info.get('bit_rate', 'Unknown')} bps")
                if 'streams' in info and info['streams']:
                    stream = info['streams'][0]
                    print(f"  Sample rate: {stream.get('sample_rate', 'Unknown')} Hz")
                    print(f"  Channels: {stream.get('channels', 'Unknown')}")
                    print(f"  Codec: {stream.get('codec_name', 'Unknown')}")
            else:
                print("Could not retrieve file information")
        
        # Create output directory if needed
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        success = converter.convert_file(args.input, args.output, 
                                       args.quality, args.bitrate)
        
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main() 