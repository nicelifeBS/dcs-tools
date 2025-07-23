"""Tool to convert text to speech using Kokoro local running server"""

import csv
import os
import sys
import argparse
import requests
import json
from pathlib import Path
from typing import List, Dict, Optional

server_url = "http://localhost:8880"


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
            reader = csv.DictReader(file, delimiter=',')
            
            # Validate required columns
            required_columns = ['title', 'text', 'voice']
            if not all(col in reader.fieldnames for col in required_columns):
                print(f"Error: CSV must contain columns: {', '.join(required_columns)}")
                print(f"Found columns: {', '.join(reader.fieldnames or [])}")
                return []
            
            for row_num, row in enumerate(reader, start=2):
                # Clean and validate data
                title = row['title'].strip()
                text = row['text'].strip()
                voice = row['voice'].strip()
                
                if not title or not text or not voice:
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
    
    # Get available voices for validation
    available_voices = tts_client.get_available_voices()
    if available_voices:
        print(f"Available voices: {', '.join(available_voices)}")
    
    success_count = 0
    error_count = 0
    
    for i, entry in enumerate(entries, 1):
        print(f"\n[{i}/{len(entries)}] Processing: {entry['title']}")
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
        
        # Sanitize filename
        safe_title = sanitize_filename(entry['title'])
        output_file = output_path / f"{safe_title}.{response_format}"
        
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






