"""Tool to apply radio transmission effects to audio files using FFmpeg"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from typing import List, Optional


class RadioEffectProcessor:
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
    
    def apply_radio_effect(self, input_file: str, output_file: str, 
                          effect_type: str = "standard", quality: str = "medium") -> bool:
        """Apply radio transmission effect to audio file"""
        
        # Define filter chains for different radio effects
        filters = self._get_radio_filters(effect_type, quality)
        
        try:
            # Build FFmpeg command
            cmd = [
                self.ffmpeg_path,
                "-i", input_file,
                "-af", filters,
                "-y",  # Overwrite output file
                output_file
            ]
            
            print(f"Applying {effect_type} radio effect...")
            print(f"Command: {' '.join(cmd)}")
            
            # Run FFmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✓ Radio effect applied successfully: {output_file}")
                return True
            else:
                print(f"✗ FFmpeg error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("✗ FFmpeg process timed out")
            return False
        except Exception as e:
            print(f"✗ Error applying radio effect: {e}")
            return False
    
    def _get_radio_filters(self, effect_type: str, quality: str) -> str:
        """Get FFmpeg filter chain for radio effects using only available filters"""
        
        # Base filters for radio transmission simulation (using only available filters)
        base_filters = [
            # High-pass filter to remove low frequencies (like radio)
            "highpass=f=300",
            # Low-pass filter to limit high frequencies
            "lowpass=f=3000",
            # Compression to simulate radio compression
            "acompressor=threshold=0.1:ratio=4:attack=0.1:release=0.1"
        ]
        
        # Quality-specific adjustments
        if quality == "low":
            # More aggressive filtering for low quality
            base_filters.extend([
                "highpass=f=500",
                "lowpass=f=2500"
            ])
        elif quality == "high":
            # Less aggressive for high quality
            base_filters.extend([
                "highpass=f=200",
                "lowpass=f=3500"
            ])
        
        # Effect-specific modifications
        if effect_type == "military":
            # Military radio effect - more formal, clear
            filters = [
                "highpass=f=400",
                "lowpass=f=2800",
                "acompressor=threshold=0.05:ratio=6:attack=0.05:release=0.1"
            ]
        elif effect_type == "amateur":
            # Amateur radio effect - more variable quality
            filters = [
                "highpass=f=250",
                "lowpass=f=3200",
                "acompressor=threshold=0.15:ratio=3:attack=0.2:release=0.3"
            ]
        elif effect_type == "emergency":
            # Emergency radio effect - clear and loud
            filters = [
                "highpass=f=350",
                "lowpass=f=3000",
                "acompressor=threshold=0.02:ratio=8:attack=0.02:release=0.05"
            ]
        elif effect_type == "vintage":
            # Vintage radio effect - old equipment simulation
            filters = [
                "highpass=f=200",
                "lowpass=f=2500",
                "acompressor=threshold=0.2:ratio=2:attack=0.3:release=0.5"
            ]
        else:  # standard
            filters = base_filters
        
        return ",".join(filters)
    
    def batch_process(self, input_dir: str, output_dir: str, 
                     effect_type: str = "standard", quality: str = "medium",
                     file_pattern: str = "*.wav") -> None:
        """Process all audio files in a directory"""
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Find all audio files
        audio_files = list(input_path.glob(file_pattern))
        if not audio_files:
            print(f"No audio files found matching pattern: {file_pattern}")
            return
        
        print(f"Found {len(audio_files)} audio files to process")
        print(f"Effect type: {effect_type}, Quality: {quality}")
        
        success_count = 0
        error_count = 0
        
        for i, audio_file in enumerate(audio_files, 1):
            print(f"\n[{i}/{len(audio_files)}] Processing: {audio_file.name}")
            
            # Create output filename
            output_file = output_path / f"radio_{audio_file.stem}.wav"
            
            # Apply radio effect
            if self.apply_radio_effect(str(audio_file), str(output_file), effect_type, quality):
                success_count += 1
            else:
                error_count += 1
        
        print(f"\n=== Summary ===")
        print(f"Successfully processed: {success_count} files")
        print(f"Errors: {error_count} files")
        print(f"Total processed: {len(audio_files)} files")


def main():
    parser = argparse.ArgumentParser(description="Apply radio transmission effects to audio files using FFmpeg")
    parser.add_argument("input", help="Input audio file or directory")
    parser.add_argument("output", help="Output audio file or directory")
    parser.add_argument("--effect-type", choices=["standard", "military", "amateur", "emergency", "vintage"],
                       default="standard", help="Type of radio effect to apply (default: standard)")
    parser.add_argument("--quality", choices=["low", "medium", "high"],
                       default="medium", help="Quality level of the radio effect (default: medium)")
    parser.add_argument("--ffmpeg-path", default="ffmpeg",
                       help="Path to FFmpeg executable (default: ffmpeg)")
    parser.add_argument("--file-pattern", default="*.wav",
                       help="File pattern for batch processing (default: *.wav)")
    parser.add_argument("--batch", action="store_true",
                       help="Process input as directory (batch mode)")
    
    args = parser.parse_args()
    
    # Initialize processor
    processor = RadioEffectProcessor(args.ffmpeg_path)
    
    if args.batch:
        # Batch processing mode
        if not os.path.isdir(args.input):
            print(f"Error: Input must be a directory when using --batch mode")
            sys.exit(1)
        
        processor.batch_process(args.input, args.output, args.effect_type, 
                              args.quality, args.file_pattern)
    else:
        # Single file processing mode
        if not os.path.isfile(args.input):
            print(f"Error: Input file not found: {args.input}")
            sys.exit(1)
        
        # Create output directory if needed
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        success = processor.apply_radio_effect(args.input, args.output, 
                                             args.effect_type, args.quality)
        
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
