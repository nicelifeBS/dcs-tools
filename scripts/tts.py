"""Tool to convert text to speech using Kokoro local running server"""

import csv
import sys
import argparse
import requests
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Optional

server_url = "http://localhost:8880"


def check_ffmpeg(ffmpeg_path: str = "ffmpeg") -> bool:
    """Check if FFmpeg is available and provide installation guidance"""
    try:
        result = subprocess.run([ffmpeg_path, "-version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"✓ FFmpeg found: {result.stdout.split()[2]}")
            return True
        else:
            print(f"✗ FFmpeg check failed: {result.stderr}")
            return False
    except FileNotFoundError:
        print(f"✗ FFmpeg not found at: {ffmpeg_path}")
        print("\n📋 FFmpeg Installation Guide:")
        print("=" * 50)
        print("Windows:")
        print("  1. Download from: https://ffmpeg.org/download.html")
        print("  2. Extract to C:\\ffmpeg\\")
        print("  3. Add C:\\ffmpeg\\bin to your PATH environment variable")
        print("  4. Or use: winget install ffmpeg")
        print()
        print("macOS:")
        print("  1. Install via Homebrew: brew install ffmpeg")
        print("  2. Or download from: https://ffmpeg.org/download.html")
        print()
        print("Linux (Ubuntu/Debian):")
        print("  1. sudo apt update && sudo apt install ffmpeg")
        print()
        print("Linux (CentOS/RHEL):")
        print("  1. sudo yum install ffmpeg")
        print()
        print("After installation, restart your terminal and try again.")
        return False
    except Exception as e:
        print(f"✗ Error checking FFmpeg: {e}")
        return False





class AudioProcessor:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
    
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
    
    def process_audio(self, input_file: str, output_file: str, 
                     target_peak: float = -2.0, leveler_preset: str = "broadcast",
                     apply_radio_effect: bool = False, radio_effect_type: str = "standard",
                     radio_quality: str = "medium") -> bool:
        """Process audio with leveling and optionally radio effect in a single FFmpeg operation"""
        
        try:
            # First, analyze the audio to get current levels for leveling
            print("Analyzing audio levels...")
            analysis = self.analyze_audio_levels(input_file)
            
            if not analysis:
                print("✗ Could not analyze audio levels")
                return False
            
            current_max = analysis['max_volume']
            current_mean = analysis['mean_volume']
            
            print(f"Current levels - Mean: {current_mean:.1f} dB, Max: {current_max:.1f} dB")
            
            # Calculate the volume adjustment needed
            volume_adjustment = target_peak - current_max
            
            print(f"Volume adjustment needed: {volume_adjustment:.1f} dB")
            
            # Build combined filter chain
            filters = []
            
            # 1. Volume adjustment (leveling)
            filters.append(f"volume={volume_adjustment:.1f}dB")
            
            # 2. Preset-specific filters (leveling)
            if leveler_preset == "broadcast":
                filters.extend(["highpass=f=20", "lowpass=f=20000"])
            elif leveler_preset == "streaming":
                filters.extend(["highpass=f=30", "lowpass=f=18000"])
            elif leveler_preset == "gaming":
                filters.extend(["highpass=f=40", "lowpass=f=16000"])
            elif leveler_preset == "voice":
                filters.extend(["highpass=f=80", "lowpass=f=8000"])
            elif leveler_preset == "music":
                filters.extend(["highpass=f=20", "lowpass=f=22000"])
            elif leveler_preset == "radio":
                filters.extend(["highpass=f=300", "lowpass=f=3000"])
            
            # 3. Radio effect filters (if requested)
            if apply_radio_effect:
                radio_filters = self._get_radio_filters(radio_effect_type, radio_quality)
                filters.extend(radio_filters)
                # Add volume boost after radio effect to compensate for compression
                filters.append("volume=+10dB")
            
            filter_chain = ",".join(filters)
            
            # Build FFmpeg command
            cmd = [
                self.ffmpeg_path,
                "-i", input_file,
                "-af", filter_chain,
                "-y",  # Overwrite output file
                output_file
            ]
            
            # Determine what we're doing
            if apply_radio_effect:
                print(f"Applying {leveler_preset} leveling + radio effect in single operation...")
            else:
                print(f"Applying {leveler_preset} leveling...")
            
            # Run FFmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                if apply_radio_effect:
                    print(f"✓ Audio leveled and radio effect applied successfully: {Path(output_file).name}")
                else:
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
            print(f"✗ Error processing audio: {e}")
            return False
    
    def _get_radio_filters(self, effect_type: str, quality: str) -> List[str]:
        """Get FFmpeg filter chain for radio effects"""
        
        # Base filters for radio transmission simulation
        base_filters = [
            # High-pass filter to remove low frequencies (like radio)
            "highpass=f=300",
            # Low-pass filter to limit high frequencies
            "lowpass=f=3000",
            # Compression to simulate radio compression (less aggressive)
            "acompressor=threshold=0.05:ratio=2:attack=0.1:release=0.1"
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
        
        return filters


class KokoroTTS:
    def __init__(self, server_url: str = "http://localhost:8880"):
        self.server_url = server_url
        self.session = requests.Session()
    
    def check_server_status(self) -> bool:
        """Check if the Kokoro TTS server is running"""
        try:
            response = self.session.get(f"{self.server_url}/health", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def get_available_voices(self) -> List[str]:
        """Get list of available voices from the server"""
        try:
            response = self.session.get(f"{self.server_url}/v1/audio/voices", timeout=10)
            if response.status_code == 200:
                voices_data = response.json()
                # Extract voice names from the response
                if isinstance(voices_data, list):
                    voices = []
                    for voice in voices_data:
                        if isinstance(voice, dict):
                            voices.append(voice.get('name', voice.get('id', str(voice))))
                        else:
                            voices.append(str(voice))
                    return voices
                elif isinstance(voices_data, dict) and 'voices' in voices_data:
                    voices = []
                    for voice in voices_data['voices']:
                        if isinstance(voice, dict):
                            voices.append(voice.get('name', voice.get('id', str(voice))))
                        else:
                            voices.append(str(voice))
                    return voices
                else:
                    # Fallback to common voices if response format is unexpected
                    print(f"Warning: Unexpected voices response format: {type(voices_data)}")
                    return self._get_fallback_voices()
            else:
                print(f"Warning: Could not fetch voices from server (status: {response.status_code})")
                return self._get_fallback_voices()
        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not connect to voices endpoint: {e}")
            return self._get_fallback_voices()
    
    def _get_fallback_voices(self) -> List[str]:
        """Return fallback list of common Kokoro voices"""
        return [
            "af_heart", "af_heart_2", "af_heart_3", "af_heart_4", "af_heart_5",
            "af_heart_6", "af_heart_7", "af_heart_8", "af_heart_9", "af_heart_10"
        ]
    
    def generate_speech(self, text: str, voice: str, output_path: str, 
                       response_format: str = "wav", speed: float = 1.0, 
                       volume_multiplier: float = 3.0, download_format: str = "mp3") -> bool:
        """Generate speech from text using specified voice and save to output path"""
        try:
            # Prepare the TTS request according to Kokoro API format
            payload = {
                "model": "kokoro",
                "input": text,
                "voice": voice,
                "response_format": response_format,
                "download_format": download_format,
                "speed": speed,
                "volume_multiplier": volume_multiplier,
                "lang_code": "a",
            }
            
            # Make the TTS request to the correct endpoint
            response = self.session.post(
                f"{self.server_url}/v1/audio/speech",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                # Save the audio file
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                print(f"Error generating speech: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return False
        except Exception as e:
            print(f"Error saving audio file: {e}")
            return False


def read_csv_file(csv_path: str) -> List[Dict[str, str]]:
    """Read CSV file with title, text, and voice columns"""
    entries = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file, delimiter=',')
            
            # Validate required columns
            required_columns = ['title', 'text', 'voice', 'type']
            if not all(col in reader.fieldnames for col in required_columns):
                print(f"Error: CSV must contain columns: {', '.join(required_columns)}")
                print(f"Found columns: {', '.join(reader.fieldnames or [])}")
                return []
            
            for row_num, row in enumerate(reader, start=2):
                # Clean and validate data
                title = row['title'].strip()
                text = row['text'].strip()
                voice = row['voice'].strip()
                type_value = row['type'].strip()
                
                if not title or not text or not voice or not type_value:
                    print(f"Warning: Skipping row {row_num} - missing required data")
                    continue
                
                # Get optional parameters with defaults
                response_format = row.get('format', 'wav').strip()
                download_format = row.get('download_format', 'mp3').strip()
                speed = float(row.get('speed', '1.0').strip())
                volume_multiplier = float(row.get('volume', '1.0').strip())
                output_format = row.get('output_format', '').strip().lower()  # Will default to ogg in processing if empty
                
                entries.append({
                    'title': title,
                    'text': text,
                    'voice': voice,
                    'type': type_value,
                    'format': response_format,
                    'download_format': download_format,
                    'speed': speed,
                    'volume': volume_multiplier,
                    'output_format': output_format
                })
        
        return entries
        
    except FileNotFoundError:
        print(f"Error: CSV file not found: {csv_path}")
        return []
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file system usage"""
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    
    # Ensure filename is not empty
    if not filename:
        filename = "untitled"
    
    return filename


def parse_row_indices(row_spec: str) -> Optional[set]:
    """Parse row specification string into a set of 1-based row indices.
    
    Supports:
    - Individual numbers: "1,3,5"
    - Ranges: "1-5" or "1:5"
    - Mixed: "1,3,5-8,10"
    
    Returns None if invalid, or a set of 1-based indices.
    """
    if not row_spec or not row_spec.strip():
        return None
    
    indices = set()
    parts = row_spec.replace(':', '-').split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Check for range
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start_idx = int(start.strip())
                end_idx = int(end.strip())
                if start_idx < 1 or end_idx < 1:
                    print(f"Warning: Row indices must be >= 1, ignoring: {part}")
                    continue
                if start_idx > end_idx:
                    print(f"Warning: Invalid range (start > end), ignoring: {part}")
                    continue
                indices.update(range(start_idx, end_idx + 1))
            except ValueError:
                print(f"Warning: Invalid range format, ignoring: {part}")
                continue
        else:
            # Single number
            try:
                idx = int(part)
                if idx < 1:
                    print(f"Warning: Row indices must be >= 1, ignoring: {idx}")
                    continue
                indices.add(idx)
            except ValueError:
                print(f"Warning: Invalid row number, ignoring: {part}")
                continue
    
    return indices if indices else None


def process_tts_batch(csv_path: str, output_dir: str, tts_client: KokoroTTS, 
                      download_format_override: str = None,
                      speed_override: float = None, volume_override: float = None,
                      level_audio: bool = False, output_format: Optional[str] = None, 
                      target_peak: float = -2.0, leveler_preset: str = "broadcast",
                      retain_original: bool = False, row_indices: Optional[set] = None) -> None:
    """Process all entries in the CSV file and generate TTS audio files
    
    Args:
        row_indices: Optional set of 1-based row indices to process. If None, all rows are processed.
    """
    
    # Read CSV entries
    entries = read_csv_file(csv_path)
    if not entries:
        print("No valid entries found in CSV file.")
        return
    
    # Filter entries by row indices if specified
    if row_indices is not None:
        original_count = len(entries)
        entries = [entry for idx, entry in enumerate(entries, start=1) if idx in row_indices]
        filtered_count = len(entries)
        if filtered_count == 0:
            print(f"No entries match the specified row indices. Total entries in CSV: {original_count}")
            return
        print(f"Filtered to {filtered_count} of {original_count} entries based on row indices")
        # Check for invalid indices
        max_valid = original_count
        invalid_indices = [idx for idx in row_indices if idx > max_valid]
        if invalid_indices:
            print(f"Warning: Some specified row indices exceed the CSV row count ({max_valid}): {sorted(invalid_indices)}")
    
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    leveled_dir = output_path
    leveled_dir.mkdir(exist_ok=True)
    
    print(f"Processing {len(entries)} entries...")
    print(f"Output directory: {output_path.absolute()}")

    # Initialize audio processor
    audio_processor = AudioProcessor()
    
    # Get available voices for validation
    available_voices = tts_client.get_available_voices()
    if available_voices:
        print(f"Available voices: {', '.join(available_voices)}")
    
    success_count = 0
    error_count = 0
    
    for i, entry in enumerate(entries, 1):
        print(f"\n[{i}/{len(entries)}] Processing: {entry['title']}")
        print(f"  Type: {entry['type']}")
        print(f"  Text: {entry['text'][:50]}{'...' if len(entry['text']) > 50 else ''}")
        print(f"  Voice: {entry['voice']}")
        
        # Apply command line overrides
        download_format = download_format_override if download_format_override else entry['download_format']
        speed = speed_override if speed_override is not None else entry['speed']
        volume = volume_override if volume_override is not None else entry['volume']
        
        # Determine output format: command line override takes precedence, then CSV entry, default to "ogg"
        if output_format is not None:
            # Command line override: force this format for all entries
            final_output_format = output_format
        else:
            # Use CSV entry value if valid, otherwise default to "ogg"
            entry_output_format = entry.get('output_format', '')
            if entry_output_format and entry_output_format in ['wav', 'ogg']:
                final_output_format = entry_output_format
            else:
                final_output_format = "ogg"  # Default fallback
        
        # Print overridden parameters if any
        if download_format_override or speed_override is not None or volume_override is not None or output_format is not None:
            print(f"  Parameters: download={download_format}, speed={speed}, volume={volume}, output_format={final_output_format}")
        
        # Sanitize filename with type prefix
        safe_title = sanitize_filename(entry['title'])
        type_prefix = sanitize_filename(entry['type'])
        
        # Create generated directory only if we need to retain original files
        if retain_original:
            generated_dir = output_path / "generated"
            generated_dir.mkdir(exist_ok=True)
            output_file = generated_dir / f"temp_{safe_title}.wav"
        else:
            # Use a temporary file in the main directory
            output_file = leveled_dir / f"temp_{safe_title}.wav"
        
        # Check if file already exists
        if output_file.exists():
            print(f"  Warning: File already exists, overwriting: {output_file.name}")
        
        # Generate speech with additional parameters
        if tts_client.generate_speech(
            entry['text'], 
            entry['voice'], 
            str(output_file),
            response_format="wav",
            speed=speed,
            volume_multiplier=volume,
            download_format=download_format
        ):
            print(f"  ✓ Generated: {output_file}")
            
            # Always process audio to convert to output format, but skip leveling if --no-leveling is used
            if level_audio or entry['type'].lower() == 'radio':
                # Determine output file and processing options
                final_file = leveled_dir / f"{type_prefix}_{safe_title}.{final_output_format}"
                apply_radio_effect = entry['type'].lower() == 'radio'
                
                # Process audio with combined filters
                if audio_processor.process_audio(
                    str(output_file), 
                    str(final_file),
                    target_peak=target_peak,
                    leveler_preset=leveler_preset,
                    apply_radio_effect=apply_radio_effect
                ):
                    print(f"  ✓ Audio processing completed successfully")
                else:
                    print(f"  ✗ Failed to process audio")
                    error_count += 1
                    continue
            elif not level_audio and entry['type'].lower() != 'radio':
                # When --no-leveling is used and it's not a radio entry, just convert format
                final_file = leveled_dir / f"{type_prefix}_{safe_title}.{final_output_format}"
                
                # Simple format conversion without leveling
                cmd = [
                    "ffmpeg",
                    "-i", str(output_file),
                    "-y",  # Overwrite output file
                    str(final_file)
                ]
                
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    if result.returncode == 0:
                        print(f"  ✓ Format conversion completed successfully")
                    else:
                        print(f"  ✗ Failed to convert format: {result.stderr}")
                        error_count += 1
                        continue
                except Exception as e:
                    print(f"  ✗ Error converting format: {e}")
                    error_count += 1
                    continue
            
            # Remove the original TTS output file unless retain_original is True
            if not retain_original:
                try:
                    output_file.unlink()
                    print(f"  ✓ Original TTS file removed")
                except Exception as e:
                    print(f"  Warning: Could not remove original TTS file: {e}")
            else:
                print(f"  ✓ Original TTS file retained: {output_file.name}")
            
            success_count += 1
        else:
            print(f"  ✗ Failed to generate: {output_file.name}")
            error_count += 1
    
    print(f"\n=== Summary ===")
    print(f"Successfully generated: {success_count} files")
    print(f"Errors: {error_count} files")
    print(f"Total processed: {len(entries)} entries")


def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio files from CSV using Kokoro TTS server")
    parser.add_argument("csv_file", nargs='?', help="Path to CSV file with title;text;voice columns")
    parser.add_argument("output_dir", nargs='?', help="Output directory for generated audio files")
    parser.add_argument("--server-url", default="http://localhost:8880", 
                       help="Kokoro TTS server URL (default: http://localhost:8880)")
    parser.add_argument("--check-voices", action="store_true", 
                       help="List available voices and exit")
    parser.add_argument("--download-format", choices=["mp3", "wav", "opus", "flac", "pcm"],
                       help="Override download format for all entries")
    parser.add_argument("--speed", type=float, help="Override speed for all entries (0.25 to 4.0)")
    parser.add_argument("--volume", type=float, help="Override volume multiplier for all entries")
    parser.add_argument("--leveling", action="store_true", help="Enable audio leveling step (disabled by default)")
    parser.add_argument("--retain-original", action="store_true", help="Keep original TTS files (not just processed versions)")
    parser.add_argument("--output-format", choices=["ogg", "wav", "mp3", "flac"], default=None,
                       help="Override output format for all entries, overriding CSV values (default: use CSV or 'ogg')")
    parser.add_argument("--target-peak", type=float, default=-2.0,
                       help="Target peak in dB for audio leveling (default: -2.0)")
    parser.add_argument("--leveler-preset", choices=["broadcast", "streaming", "gaming", "voice", "music", "radio"],
                       default="broadcast", help="Audio leveling preset (default: broadcast)")
    parser.add_argument("--rows", type=str, metavar="SPEC",
                       help="Process only specific rows. Examples: '1,3,5' or '1-5' or '1,3,5-8,10'. Row numbers are 1-based.")
    
    args = parser.parse_args()
    
    # Collect all validation issues before exiting
    issues = []
    
    # Check FFmpeg availability (skip if just checking voices)
    if not args.check_voices:
        if not check_ffmpeg():
            issues.append("FFmpeg is required for audio processing features. Please install FFmpeg and try again.")
    
    # Initialize TTS client
    tts_client = KokoroTTS(args.server_url)
    
    # Check server status
    if not tts_client.check_server_status():
        issues.append(f"Cannot connect to TTS server at {args.server_url}. Please ensure the Kokoro TTS server is running.")
    
    # Validate required arguments for processing (only if not checking voices)
    if not args.check_voices and (not args.csv_file or not args.output_dir):
        issues.append("Both csv_file and output_dir are required when not using --check-voices")
    
    # Check CSV file existence (only if not checking voices and CSV file is provided)
    if not args.check_voices and args.csv_file and not Path(args.csv_file).exists():
        issues.append(f"CSV file not found: {args.csv_file}")
    
    # Report all issues at once
    if issues:
        print("\n❌ Validation Issues Found:")
        print("=" * 50)
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
        print("\nPlease fix the above issues and try again.")
        if not args.check_voices and (not args.csv_file or not args.output_dir):
            parser.print_help()
        sys.exit(1)
    
    # If we get here, all checks passed
    if not args.check_voices:
        print(f"✓ FFmpeg found and available")
        print(f"✓ Connected to TTS server: {args.server_url}")
    else:
        print(f"✓ Connected to TTS server: {args.server_url}")
    
    # If just checking voices, do that and exit
    if args.check_voices:
        voices = tts_client.get_available_voices()
        if voices:
            print("Available voices:")
            for voice in voices:
                print(f"  - {voice}")
        else:
            print("No voices found or error retrieving voices.")
        return
    
    # Parse row indices if specified
    row_indices = None
    if args.rows:
        row_indices = parse_row_indices(args.rows)
        if row_indices is None:
            print(f"Error: Invalid row specification: {args.rows}")
            print("Examples: '1,3,5' or '1-5' or '1,3,5-8,10'")
            sys.exit(1)
        print(f"Processing rows: {sorted(row_indices)}")
    
    # Process the CSV file
    process_tts_batch(args.csv_file, args.output_dir, tts_client,
                      download_format_override=args.download_format,
                      speed_override=args.speed,
                      volume_override=args.volume,
                      level_audio=args.leveling,
                      output_format=args.output_format,
                      target_peak=args.target_peak,
                      leveler_preset=args.leveler_preset,
                      retain_original=args.retain_original,
                      row_indices=row_indices)


if __name__ == "__main__":
    main()






