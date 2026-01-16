import argparse
import csv
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from indextts.infer_v2 import IndexTTS2


# Default emotion values (used if not found in CSV)
DEFAULT_EMOTIONS = {
    "happy": 0.3,
    "angry": 0.0,
    "sad": 0,
    "afraid": 0,
    "disgusted": 0.0,
    "melancholic": 0,
    "surprised": 0,
    "calm": 0.2
}


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


def parse_row_indices(row_spec: str) -> set:
    """Parse row specification string into a set of 1-based row indices.
    
    Supports:
    - Individual numbers: "1,3,5"
    - Ranges: "1-5" or "1:5"
    - Mixed: "1,3,5-8,10"
    
    Returns a set of 1-based indices (1 = first data row after header).
    """
    if not row_spec or not row_spec.strip():
        return set()
    
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
    
    return indices


def read_csv_data(csv_path, voice_samples_dir, row_indices=None):
    """Read text, reference audio, and emotions from CSV file.
    
    Expected columns: title, text, voice, type, happy, angry, sad, afraid, 
    disgusted, melancholic, surprised, calm
    
    Args:
        csv_path: Path to CSV file
        voice_samples_dir: Directory containing voice sample audio files
        row_indices: Optional set of 1-based row indices to process (None = all rows)
    
    Returns:
        List of tuples: (text, reference_audio_path, emotions, title, type_value, row_number)
    """
    rows_data = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as file:
            # Try to detect delimiter
            sample = file.read(1024)
            file.seek(0)
            delimiter = ',' if sample.count(',') > sample.count(';') else ';'
            
            reader = csv.DictReader(file, delimiter=delimiter)
            
            # Normalize column names (case-insensitive)
            fieldnames_lower = {name.lower().strip(): name for name in reader.fieldnames}
            
            # Validate required columns exist
            required_columns = ['text', 'voice']
            missing_columns = []
            for col in required_columns:
                if col not in fieldnames_lower:
                    missing_columns.append(col)
            
            if missing_columns:
                print(f"Error: Missing required columns: {', '.join(missing_columns)}")
                print(f"Available columns: {', '.join(reader.fieldnames)}")
                print("Expected columns: title, text, voice, type, happy, angry, sad, afraid, disgusted, melancholic, surprised, calm")
                return []
            
            # Read all rows or selected rows
            for row_num, row in enumerate(reader, start=1):
                # Skip rows not in selection if row_indices is specified
                if row_indices is not None and row_num not in row_indices:
                    continue
                
                # Extract required fields
                text = row[fieldnames_lower['text']].strip()
                voice_filename = row[fieldnames_lower['voice']].strip()
                
                # Read optional fields
                title = row[fieldnames_lower['title']].strip() if 'title' in fieldnames_lower else ''
                type_value = row[fieldnames_lower['type']].strip() if 'type' in fieldnames_lower else ''
                
                if not text:
                    print(f"Warning: Row {row_num}: 'text' column is empty, skipping")
                    continue
                
                if not voice_filename:
                    print(f"Warning: Row {row_num}: 'voice' column is empty, skipping")
                    continue
                
                # Build full reference audio path
                reference_audio_path = os.path.join(voice_samples_dir, voice_filename)
                
                # If not found and no extension, try with .wav extension
                if not os.path.exists(reference_audio_path) and not os.path.splitext(voice_filename)[1]:
                    reference_audio_path = os.path.join(voice_samples_dir, voice_filename + ".wav")
                
                if not os.path.exists(reference_audio_path):
                    print(f"Error: Row {row_num}: Reference audio file not found: {reference_audio_path}")
                    print(f"  Looked for: {os.path.join(voice_samples_dir, voice_filename)}")
                    if not os.path.splitext(voice_filename)[1]:
                        print(f"  Also tried: {os.path.join(voice_samples_dir, voice_filename + '.wav')}")
                    continue
                
                # Extract emotion values (with defaults if missing)
                emotions = {}
                emotion_keys = ['happy', 'angry', 'sad', 'afraid', 'disgusted', 'melancholic', 'surprised', 'calm']
                for emotion in emotion_keys:
                    if emotion in fieldnames_lower:
                        try:
                            emotion_value = row[fieldnames_lower[emotion]].strip()
                            emotions[emotion] = float(emotion_value) if emotion_value else DEFAULT_EMOTIONS[emotion]
                        except (ValueError, KeyError):
                            emotions[emotion] = DEFAULT_EMOTIONS[emotion]
                    else:
                        emotions[emotion] = DEFAULT_EMOTIONS[emotion]
                
                # Validate title exists
                if not title:
                    title = f"untitled_row_{row_num}"
                    print(f"Warning: Row {row_num}: 'title' column is empty, using '{title}'")
                
                rows_data.append((text, reference_audio_path, emotions, title, type_value, row_num))
            
            if not rows_data:
                if row_indices:
                    print(f"Error: No valid rows found for specified indices: {sorted(row_indices)}")
                else:
                    print("Error: CSV file has no valid data rows")
                return []
            
            return rows_data
            
    except FileNotFoundError:
        print(f"Error: CSV file not found: {csv_path}")
        return []
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        import traceback
        traceback.print_exc()
        return []


def generate_audio_chunks(text, output_path, reference_audio_path, selected_chunks, tts_model, emotions, base_output_path, num_chunks):
    """Generate audio chunks from text."""
    for chunk_idx in range(num_chunks):
        # Skip if this chunk index is not selected
        if chunk_idx not in selected_chunks:
            continue
        
        # Get the two sentences for this chunk
        start_idx = chunk_idx * 2
        end_idx = min(start_idx + 2, len(text))
        chunk_sentences = text[start_idx:end_idx]
        
        # Combine sentences with periods
        chunk_text = ". ".join([s.strip() for s in chunk_sentences]) + "."
        
        # Generate output path with chunk number
        chunk_output_path = f"{base_output_path}_{chunk_idx}.wav"
        print(f"Generating chunk {chunk_idx} (sentences {start_idx}-{end_idx-1}): {chunk_text[:80]}...")
        tts_model.infer(
            spk_audio_prompt=reference_audio_path, 
            text=chunk_text, 
            output_path=chunk_output_path, 
            emo_vector=[emotions["happy"], emotions["angry"], emotions["sad"], emotions["afraid"], emotions["disgusted"], emotions["melancholic"], emotions["surprised"], emotions["calm"]], 
            emo_alpha=0.6,
            use_random=False, 
            verbose=False
        )
        print(f"Generated: {chunk_output_path}")


def combine_audio_chunks(base_output_path, output_path, num_chunks=None):
    """Combine all chunk audio files into a single WAV file with pauses."""
    print("\nCombining all chunk files...")
    chunk_files = []
    
    # If num_chunks not provided, detect from existing files
    if num_chunks is None:
        chunk_idx = 0
        while os.path.exists(f"{base_output_path}_{chunk_idx}.wav"):
            chunk_files.append(f"{base_output_path}_{chunk_idx}.wav")
            chunk_idx += 1
        if not chunk_files:
            print("Error: No chunk files found to combine")
            sys.exit(1)
        num_chunks = len(chunk_files)
        print(f"Detected {num_chunks} chunk files")
    else:
        # Use provided num_chunks to find files
        for chunk_idx in range(num_chunks):
            chunk_file = f"{base_output_path}_{chunk_idx}.wav"
            if os.path.exists(chunk_file):
                chunk_files.append(chunk_file)
            else:
                print(f"Warning: Chunk file {chunk_file} not found, skipping in concatenation")

    if not chunk_files:
        print("Error: No chunk files found to combine")
        sys.exit(1)

    if len(chunk_files) < num_chunks:
        print(f"Warning: Expected {num_chunks} chunk files, but only found {len(chunk_files)}")

    # Probe first chunk file to get audio format for silence generation
    probe_cmd = [
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'a:0',
        '-show_entries', 'stream=sample_rate,channels',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        chunk_files[0]
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    if probe_result.returncode != 0:
        print("Error: Could not probe audio format. Using default (44100 Hz, 2 channels)")
        sample_rate = 44100
        channels = 2
    else:
        lines = probe_result.stdout.strip().split('\n')
        sample_rate = int(lines[0]) if lines[0] else 44100
        channels = int(lines[1]) if len(lines) > 1 and lines[1] else 2

    # Generate a 0.5 second silence file with matching format
    silence_path = os.path.join(os.path.dirname(chunk_files[0]), '_silence_temp.wav')
    channel_layout = 'stereo' if channels == 2 else 'mono'
    silence_cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', f'anullsrc=channel_layout={channel_layout}:sample_rate={sample_rate}',
        '-t', '0.5',
        '-y',
        silence_path
    ]
    result = subprocess.run(silence_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error generating silence file:")
        print(result.stderr)
        sys.exit(1)

    # Create a temporary file list for ffmpeg concat demuxer with silence between chunks
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        silence_abs_path = os.path.abspath(silence_path).replace('\\', '/').replace("'", "\\'")
        for i, chunk_file in enumerate(chunk_files):
            # Add chunk file
            abs_path = os.path.abspath(chunk_file).replace('\\', '/').replace("'", "\\'")
            f.write(f"file '{abs_path}'\n")
            # Add silence between chunks (not after the last one)
            if i < len(chunk_files) - 1:
                f.write(f"file '{silence_abs_path}'\n")
        filelist_path = f.name

    try:
        # Use ffmpeg concat demuxer to combine files with silence
        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', filelist_path,
            '-c', 'copy',
            '-y',  # Overwrite output file if it exists
            output_path
        ]
        print(f"Combining {len(chunk_files)} chunks with 0.5s pauses into: {output_path}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"Successfully combined {len(chunk_files)} chunks into: {output_path}")
            
            # Remove original chunk files after successful combination
            print("Removing original chunk files...")
            removed_count = 0
            for chunk_file in chunk_files:
                try:
                    if os.path.exists(chunk_file):
                        os.unlink(chunk_file)
                        removed_count += 1
                except OSError as e:
                    print(f"Warning: Could not remove chunk file {chunk_file}: {e}")
            print(f"Removed {removed_count} chunk file(s)")
        else:
            print(f"Error combining files:")
            print(result.stderr)
            sys.exit(1)
    finally:
        # Clean up temporary files
        if os.path.exists(filelist_path):
            os.unlink(filelist_path)
        if os.path.exists(silence_path):
            os.unlink(silence_path)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate TTS audio files from text in chunks of 2 sentences")
    parser.add_argument(
        "csv_file",
        type=str,
        help="Path to CSV file containing text, reference audio, and emotion values"
    )
    parser.add_argument(
        "output_path",
        type=str,
        help="Directory path for output WAV files (files will be named using 'title' from CSV)"
    )
    parser.add_argument(
        "--voice-samples-dir",
        type=str,
        required=True,
        help="Directory containing voice sample audio files referenced in CSV"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["generate", "combine", "both"],
        default="generate",
        help="Operation mode: 'generate' (create chunks only), 'combine' (combine existing chunks only), 'both' (generate and combine, default)"
    )
    parser.add_argument(
        "--chunks",
        type=str,
        help="Comma-separated list of chunk indices to regenerate (e.g., 0,1,2). Chunk 0 = sentences 0-1, chunk 1 = sentences 2-3, etc. Only used with --mode generate or both."
    )
    parser.add_argument(
        "--rows",
        type=str,
        help="Comma-separated list or range of row indices to process (e.g., 1,3,5 or 1-5). Row 1 is the first data row after the header. If not specified, all rows are processed."
    )
    args = parser.parse_args()
    
    # Use Path for proper path handling (like tts.py does)
    csv_file = Path(args.csv_file)
    output_dir = Path(args.output_path)
    
    # Validate CSV file exists
    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}")
        sys.exit(1)
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir.absolute()}")
    
    # Parse row indices if specified
    row_indices = None
    if args.rows:
        row_indices = parse_row_indices(args.rows)
        if not row_indices:
            print("Error: Invalid row specification. Use format like '1,3,5' or '1-5'")
            sys.exit(1)
        print(f"Processing rows: {sorted(row_indices)}")
    
    # Read data from CSV (only needed for generation)
    rows_data = []
    if args.mode in ["generate", "both"]:
        print(f"Reading CSV file: {csv_file}")
        rows_data = read_csv_data(str(csv_file), args.voice_samples_dir, row_indices)
        if not rows_data:
            print("Error: No valid rows found to process")
            sys.exit(1)
        print(f"Found {len(rows_data)} row(s) to process")
    
    # Process each row separately
    for row_data in rows_data:
        text, reference_audio_path, emotions, title, type_value, row_num = row_data
        
        print(f"\n{'='*60}")
        print(f"Processing Row {row_num}: {title}")
        print(f"{'='*60}")
        print(f"Type: {type_value if type_value else 'N/A'}")
        print(f"Text length: {len(text)} characters")
        print(f"Reference audio: {reference_audio_path}")
        print(f"Emotions: {emotions}")
        
        # Parse and prepare text
        sentences = text.split(".")
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Sanitize title for use in filenames
        sanitized_title = sanitize_filename(title)
        
        # Use title to construct base output path and final output path
        base_output_path = output_dir / sanitized_title
        final_output_path = output_dir / f"{sanitized_title}.wav"
        
        # Calculate number of chunks (2 sentences per chunk)
        num_chunks = math.ceil(len(sentences) / 2)
        
        # Determine which chunks to process
        selected_chunks = None
        if args.mode in ["generate", "both"]:
            if args.chunks:
                # Parse comma-separated chunk indices
                try:
                    selected_chunks = [int(idx.strip()) for idx in args.chunks.split(",")]
                    # Validate chunk indices are within range
                    valid_chunks = [chunk for chunk in selected_chunks if 0 <= chunk < num_chunks]
                    invalid_chunks = [chunk for chunk in selected_chunks if chunk not in valid_chunks]
                    if invalid_chunks:
                        print(f"Warning: Invalid chunk indices (out of range): {invalid_chunks}")
                    if not valid_chunks:
                        print(f"Warning: No valid chunk indices for row {row_num}. Skipping generation.")
                        selected_chunks = []
                    else:
                        selected_chunks = sorted(set(valid_chunks))  # Remove duplicates and sort
                        print(f"Processing chunks: {selected_chunks}")
                except ValueError:
                    print("Error: --chunks must contain comma-separated integers (e.g., 0,1,2)")
                    continue
            else:
                # Process all chunks if no --chunks specified
                selected_chunks = list(range(num_chunks))
                print(f"Processing all {num_chunks} chunks ({len(sentences)} sentences)")
            
            # Generate audio chunks
            if selected_chunks:
                tts = IndexTTS2(cfg_path="checkpoints/config.yaml", model_dir="checkpoints", use_fp16=False, use_cuda_kernel=False, use_deepspeed=False)
                generate_audio_chunks(sentences, str(final_output_path), reference_audio_path, selected_chunks, tts, emotions, str(base_output_path), num_chunks)
        
        # Combine audio chunks if requested
        if args.mode in ["combine", "both"]:
            combine_audio_chunks(str(base_output_path), str(final_output_path), num_chunks)
            
            # Apply radio effect if type is "radio"
            if type_value and type_value.lower() == "radio":
                print(f"\nApplying radio effect to: {final_output_path.name}")
                audio_processor = AudioProcessor()
                
                # Create temporary file for processing
                temp_output = output_dir / f"{sanitized_title}_temp.wav"
                
                # Apply radio effect
                if audio_processor.process_audio(
                    str(final_output_path),
                    str(temp_output),
                    target_peak=-2.0,
                    leveler_preset="broadcast",
                    apply_radio_effect=True,
                    radio_effect_type="radio",
                    radio_quality="medium"
                ):
                    # Replace original with processed version
                    temp_output.replace(final_output_path)
                    print(f"✓ Radio effect applied successfully")
                else:
                    print(f"✗ Failed to apply radio effect, keeping original file")
                    if temp_output.exists():
                        temp_output.unlink()
    
    # Handle combine-only mode (when no rows were read for generation)
    if args.mode == "combine" and not rows_data:
        # Try to find existing chunk files and combine them
        existing_files = [f for f in output_dir.iterdir() if f.is_file() and f.name.endswith('_0.wav')]
        if existing_files:
            # Group files by base name
            base_names = {}
            for f in existing_files:
                base_name = f.stem.replace('_0', '')  # Remove _0 from stem
                base_names[base_name] = base_name
            
            for base_name in base_names.values():
                print(f"\nCombining chunks for: {base_name}")
                base_output_path = output_dir / base_name
                final_output_path = output_dir / f"{base_name}.wav"
                combine_audio_chunks(str(base_output_path), str(final_output_path), None)
        else:
            print("Error: No chunk files found for combining. Need to generate chunks first or specify correct output path.")
            sys.exit(1)


if __name__ == "__main__":
    main()
