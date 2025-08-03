"""Tool to convert text to speech using Kokoro local running server"""

import csv
import sys
import argparse
import requests
import subprocess
from pathlib import Path
from typing import List, Dict

server_url = "http://localhost:8880"


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
    
    def apply_radio_effect(self, input_file: str, output_file: str) -> bool:
        """Apply radio transmission effect to audio file using default settings"""
        
        # Use standard effect with medium quality (defaults)
        filters = self._get_radio_filters("standard", "medium")
        
        try:
            # Build FFmpeg command
            cmd = [
                self.ffmpeg_path,
                "-i", input_file,
                "-af", filters,
                "-y",  # Overwrite output file
                output_file
            ]
            
            print(f"Applying radio effect...")
            
            # Run FFmpeg
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✓ Radio effect applied successfully")
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
        """Get FFmpeg filter chain for radio effects"""
        
        # Base filters for radio transmission simulation
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
                       volume_multiplier: float = 1.0, download_format: str = "mp3") -> bool:
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
            reader = csv.DictReader(file, delimiter=';')
            
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
                
                entries.append({
                    'title': title,
                    'text': text,
                    'voice': voice,
                    'type': type_value,
                    'format': response_format,
                    'download_format': download_format,
                    'speed': speed,
                    'volume': volume_multiplier
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


def process_tts_batch(csv_path: str, output_dir: str, tts_client: KokoroTTS, 
                     response_format_override: str = None, download_format_override: str = None,
                     speed_override: float = None, volume_override: float = None) -> None:
    """Process all entries in the CSV file and generate TTS audio files"""
    
    # Read CSV entries
    entries = read_csv_file(csv_path)
    if not entries:
        print("No valid entries found in CSV file.")
        return
    
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Processing {len(entries)} entries...")
    print(f"Output directory: {output_path.absolute()}")
    
    # Initialize radio effect processor
    radio_processor = RadioEffectProcessor()
    
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
        response_format = response_format_override if response_format_override else entry['format']
        download_format = download_format_override if download_format_override else entry['download_format']
        speed = speed_override if speed_override is not None else entry['speed']
        volume = volume_override if volume_override is not None else entry['volume']
        
        # Print overridden parameters if any
        if response_format_override or download_format_override or speed_override is not None or volume_override is not None:
            print(f"  Parameters: format={response_format}, download={download_format}, speed={speed}, volume={volume}")
        
        # Sanitize filename with type prefix
        safe_title = sanitize_filename(entry['title'])
        type_prefix = sanitize_filename(entry['type'])
        
        # For radio type, use a different filename for TTS output to avoid conflicts
        if entry['type'].lower() == 'radio':
            output_file = output_path / f"temp_{safe_title}.{response_format}"
        else:
            output_file = output_path / f"{type_prefix}_{safe_title}.{response_format}"
        
        # Check if file already exists
        if output_file.exists():
            print(f"  Warning: File already exists, overwriting: {output_file.name}")
        
        # Generate speech with additional parameters
        if tts_client.generate_speech(
            entry['text'], 
            entry['voice'], 
            str(output_file),
            response_format=response_format,
            speed=speed,
            volume_multiplier=volume,
            download_format=download_format
        ):
            print(f"  ✓ Generated: {output_file.name}")
            
            # Apply radio effect if type is "radio"
            if entry['type'].lower() == 'radio':
                print(f"  Applying radio effect...")
                # Create the final radio file directly
                final_radio_file = output_path / f"radio_{safe_title}.{response_format}"
                
                if radio_processor.apply_radio_effect(str(output_file), str(final_radio_file)):
                    print(f"  ✓ Radio effect applied successfully")
                    # Remove the intermediate file (original TTS output)
                    try:
                        output_file.unlink()
                        print(f"  ✓ Intermediate file removed")
                    except Exception as e:
                        print(f"  Warning: Could not remove intermediate file: {e}")
                else:
                    print(f"  ✗ Failed to apply radio effect")
                    error_count += 1
                    continue
            
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
    parser.add_argument("--response-format", choices=["mp3", "wav", "opus", "flac", "pcm"],
                       help="Override response format for all entries")
    parser.add_argument("--download-format", choices=["mp3", "wav", "opus", "flac", "pcm"],
                       help="Override download format for all entries")
    parser.add_argument("--speed", type=float, help="Override speed for all entries (0.25 to 4.0)")
    parser.add_argument("--volume", type=float, help="Override volume multiplier for all entries")
    
    args = parser.parse_args()
    
    # Initialize TTS client
    tts_client = KokoroTTS(args.server_url)
    
    # Check server status
    if not tts_client.check_server_status():
        print(f"Error: Cannot connect to TTS server at {args.server_url}")
        print("Please ensure the Kokoro TTS server is running.")
        sys.exit(1)
    
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
    
    # Validate required arguments for processing
    if not args.csv_file or not args.output_dir:
        print("Error: Both csv_file and output_dir are required when not using --check-voices")
        parser.print_help()
        sys.exit(1)
    
    # Process the CSV file
    process_tts_batch(args.csv_file, args.output_dir, tts_client,
                     response_format_override=args.response_format,
                     download_format_override=args.download_format,
                     speed_override=args.speed,
                     volume_override=args.volume)


if __name__ == "__main__":
    main()






