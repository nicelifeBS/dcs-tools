"""Tool to normalize and level audio files using FFmpeg"""

import os
import sys
import argparse
import subprocess
import re
from pathlib import Path
from typing import List, Optional, Dict


class AudioLeveler:
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
    
    def analyze_audio_levels(self, file_path: str) -> Optional[Dict]:
        """Analyze audio levels using volumedetect filter"""
        try:
            cmd = [
                self.ffmpeg_path,
                "-i", file_path,
                "-filter:a", "volumedetect",
                "-map", "0:a",
                "-f", "null",
                "-"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Parse the volumedetect output
                output = result.stderr
                
                # Extract values using regex
                mean_match = re.search(r'mean_volume: ([-\d.]+) dB', output)
                max_match = re.search(r'max_volume: ([-\d.]+) dB', output)
                samples_match = re.search(r'n_samples: (\d+)', output)
                
                if mean_match and max_match:
                    return {
                        'mean_volume': float(mean_match.group(1)),
                        'max_volume': float(max_match.group(1)),
                        'n_samples': int(samples_match.group(1)) if samples_match else 0
                    }
            
            return None
            
        except Exception as e:
            print(f"Error analyzing audio levels: {e}")
            return None
    
    def level_audio(self, input_file: str, output_file: str, 
                   target_peak: float = -1.0, preset: str = "broadcast") -> bool:
        """Level audio file using volumedetect analysis"""
        
        try:
            # First, analyze the audio to get current levels
            print("Analyzing audio levels...")
            analysis = self.analyze_audio_levels(input_file)
            
            if not analysis:
                print("✗ Could not analyze audio levels")
                return False
            
            current_max = analysis['max_volume']
            current_mean = analysis['mean_volume']
            
            print(f"Current levels - Mean: {current_mean:.1f} dB, Max: {current_max:.1f} dB")
            
            # Calculate the volume adjustment needed
            # We want to bring the max volume to target_peak
            volume_adjustment = target_peak - current_max
            
            print(f"Volume adjustment needed: {volume_adjustment:.1f} dB")
            
            # Build FFmpeg command with volume filter
            filters = [f"volume={volume_adjustment:.1f}dB"]
            
            # Add preset-specific filters
            if preset == "broadcast":
                filters.extend(["highpass=f=20", "lowpass=f=20000"])
            elif preset == "streaming":
                filters.extend(["highpass=f=30", "lowpass=f=18000"])
            elif preset == "gaming":
                filters.extend(["highpass=f=40", "lowpass=f=16000"])
            elif preset == "voice":
                filters.extend(["highpass=f=80", "lowpass=f=8000"])
            elif preset == "music":
                filters.extend(["highpass=f=20", "lowpass=f=22000"])
            elif preset == "radio":
                filters.extend(["highpass=f=300", "lowpass=f=3000"])
            
            filter_chain = ",".join(filters)
            
            cmd = [
                self.ffmpeg_path,
                "-i", input_file,
                "-af", filter_chain,
                "-y",  # Overwrite output file
                output_file
            ]
            
            print(f"Applying {preset} leveling with volume adjustment...")
            
            # Run FFmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                print(f"✓ Audio leveled successfully: {Path(output_file).name}")
                
                # Analyze the output to verify the result
                print("Verifying output levels...")
                output_analysis = self.analyze_audio_levels(output_file)
                if output_analysis:
                    print(f"Output levels - Mean: {output_analysis['mean_volume']:.1f} dB, Max: {output_analysis['max_volume']:.1f} dB")
                
                return True
            else:
                print(f"✗ FFmpeg error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("✗ FFmpeg process timed out")
            return False
        except Exception as e:
            print(f"✗ Error leveling audio: {e}")
            return False
    
    def get_audio_info(self, file_path: str) -> Optional[Dict]:
        """Get audio file information using FFprobe"""
        try:
            ffprobe_path = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
            cmd = [
                ffprobe_path,
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
    
    def batch_process(self, input_dir: str, output_dir: str, 
                     target_peak: float = -1.0, preset: str = "broadcast",
                     file_pattern: str = "*.wav", analyze: bool = False) -> None:
        """Process all audio files in a directory"""
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        # If output directory is the same as input directory, ask for confirmation
        if input_path.resolve() == output_path.resolve():
            print(f"⚠️  Warning: Output directory is the same as input directory")
            print(f"   Input: {input_path}")
            print(f"   Output: {output_path}")
            print(f"   This will overwrite existing files!")
            
            response = input("Do you want to proceed? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print("Operation cancelled.")
                return
        
        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Find all audio files
        audio_files = list(input_path.glob(file_pattern))
        if not audio_files:
            print(f"No audio files found matching pattern: {file_pattern}")
            return
        
        print(f"Found {len(audio_files)} audio files to process")
        print(f"Preset: {preset}, Target peak: {target_peak} dB")
        print(f"Output directory: {output_path}")
        
        success_count = 0
        error_count = 0
        
        for i, audio_file in enumerate(audio_files, 1):
            print(f"\n[{i}/{len(audio_files)}] Processing: {audio_file.name}")
            
            # Analyze audio levels if requested
            if analyze:
                print("  Analyzing original audio levels...")
                analysis = self.analyze_audio_levels(str(audio_file))
                if analysis:
                    print(f"    Mean volume: {analysis.get('mean_volume', 'N/A'):.1f} dB")
                    print(f"    Max volume: {analysis.get('max_volume', 'N/A'):.1f} dB")
            
            # Create output filename (keep original name)
            output_file = output_path / f"{audio_file.stem}.wav"
            
            # Level audio
            if self.level_audio(str(audio_file), str(output_file), target_peak, preset):
                success_count += 1
            else:
                error_count += 1
        
        print(f"\n=== Summary ===")
        print(f"Successfully processed: {success_count} files")
        print(f"Errors: {error_count} files")
        print(f"Total processed: {len(audio_files)} files")


def main():
    parser = argparse.ArgumentParser(description="Level and normalize audio files using FFmpeg volumedetect")
    parser.add_argument("input", help="Input audio file or directory")
    parser.add_argument("output", help="Output audio file or directory")
    parser.add_argument("--preset", choices=["broadcast", "streaming", "gaming", "voice", "music", "radio"],
                       default="broadcast", help="Audio leveling preset (default: broadcast)")
    parser.add_argument("--target-peak", type=float, default=0.0,
                       help="Target peak in dB (default: 0.0)")
    parser.add_argument("--ffmpeg-path", default="ffmpeg",
                       help="Path to FFmpeg executable (default: ffmpeg)")
    parser.add_argument("--file-pattern", default="*.wav",
                       help="File pattern for batch processing (default: *.wav)")
    parser.add_argument("--batch", action="store_true",
                       help="Process input as directory (batch mode)")
    parser.add_argument("--analyze", action="store_true",
                       help="Analyze audio levels before and after processing")
    parser.add_argument("--info", action="store_true",
                       help="Show file information before processing")
    
    args = parser.parse_args()
    
    # Initialize leveler
    leveler = AudioLeveler(args.ffmpeg_path)
    
    # Determine if input is directory or file
    is_directory = os.path.isdir(args.input)
    is_file = os.path.isfile(args.input)
    
    if args.batch or is_directory:
        # Batch processing mode
        if not is_directory:
            print(f"Error: Input must be a directory when using --batch mode")
            sys.exit(1)
        
        leveler.batch_process(args.input, args.output, args.target_peak, 
                            args.preset, args.file_pattern, args.analyze)
    else:
        # Single file processing mode
        if not is_file:
            print(f"Error: Input file not found: {args.input}")
            sys.exit(1)
        
        # Show file info if requested
        if args.info:
            info = leveler.get_audio_info(args.input)
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
        
        # Analyze audio levels if requested
        if args.analyze:
            print("Analyzing original audio levels...")
            analysis = leveler.analyze_audio_levels(args.input)
            if analysis:
                print(f"Mean volume: {analysis.get('mean_volume', 'N/A'):.1f} dB")
                print(f"Max volume: {analysis.get('max_volume', 'N/A'):.1f} dB")
        
        # Handle output path
        input_path = Path(args.input)
        output_path = Path(args.output)
        
        # If output is the same as input, ask for confirmation
        if input_path.resolve() == output_path.resolve():
            print(f"⚠️  Warning: Output file is the same as input file")
            print(f"   Input: {input_path}")
            print(f"   Output: {output_path}")
            print(f"   This will overwrite the existing file!")
            
            response = input("Do you want to proceed? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print("Operation cancelled.")
                sys.exit(0)
        
        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        success = leveler.level_audio(args.input, str(output_path), args.target_peak, args.preset)
        
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main() 