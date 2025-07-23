# Kokoro TTS Voice Generation Tool

This tool automates text-to-speech generation using a local Kokoro TTS server. It reads a CSV file containing text entries and generates corresponding audio files.

## Features

- Batch processing of multiple TTS requests from CSV files
- Support for different voices per entry
- Automatic filename sanitization
- Progress tracking and error reporting
- Server health checking
- Voice availability listing

## Prerequisites

1. **Kokoro TTS Server**: Ensure your local Kokoro TTS server is running on `http://localhost:8880`
2. **Python Dependencies**: Install required packages:
   ```bash
   pip install requests
   ```
   Or if using uv:
   ```bash
   uv sync
   ```

## CSV File Format

The CSV file must use semicolon (`;`) as delimiter and contain these columns:

| Column | Description | Required | Default |
|--------|-------------|----------|---------|
| `title` | Name for the output audio file | Yes | - |
| `text` | Text to convert to speech | Yes | - |
| `voice` | Voice ID to use for TTS | Yes | - |
| `format` | Response format (mp3, wav, opus, flac, pcm) | No | wav |
| `download_format` | Download format (mp3, wav, opus, flac, pcm) | No | mp3 |
| `speed` | Speech speed (0.25 to 4.0) | No | 1.0 |
| `volume` | Volume multiplier | No | 1.0 |

### Example CSV (`sample_tts_data.csv`):
```csv
title;text;voice;format;download_format;speed;volume
welcome_message;Welcome to our application! We're glad you're here.;af_heart;wav;mp3;1.0;1.0
error_notification;An error has occurred. Please try again or contact support.;af_heart_2;mp3;mp3;0.9;1.2
success_message;Operation completed successfully. Your changes have been saved.;af_heart_3;wav;mp3;1.1;1.0
system_alert;System maintenance will begin in 5 minutes. Please save your work.;af_heart_4;mp3;mp3;0.8;1.5
```

## Usage

### Basic Usage
```bash
python scripts/tts.py input.csv output_directory
```

### Check Available Voices
```bash
python scripts/tts.py --check-voices
```

### Custom Server URL
```bash
python scripts/tts.py input.csv output_directory --server-url http://localhost:9999
```

### Full Example
```bash
# First, check available voices
python scripts/tts.py --check-voices

# Then process your CSV file
python scripts/tts.py sample_tts_data.csv ./audio_output
```

## Output

- Audio files are saved as WAV format
- Filenames are automatically sanitized for file system compatibility
- Duplicate files are skipped (existing files won't be overwritten)
- Progress is displayed in real-time
- Summary statistics are shown at the end

## Error Handling

The script handles various error conditions:

- **Server Connection**: Checks if TTS server is running
- **CSV Format**: Validates required columns and data
- **File System**: Creates output directories and handles file permissions
- **Network**: Handles timeouts and connection issues
- **Invalid Characters**: Sanitizes filenames automatically

## Troubleshooting

### Server Not Running
```
Error: Cannot connect to TTS server at http://localhost:8880
Please ensure the Kokoro TTS server is running.
```
**Solution**: Start your Kokoro TTS server before running the script.

### Invalid CSV Format
```
Error: CSV must contain columns: title, text, voice
Found columns: name, content, speaker
```
**Solution**: Ensure your CSV has the correct column names and uses semicolon (`;`) as delimiter.

### Voice Not Found
```
Error generating speech: 400 - Voice not found
```
**Solution**: Use `--check-voices` to see available voices and update your CSV accordingly.

### File Permission Issues
```
Error saving audio file: [Errno 13] Permission denied
```
**Solution**: Ensure you have write permissions to the output directory.

## API Endpoints

The script uses these endpoints on your Kokoro TTS server:

- `GET /health` - Server health check
- `GET /v1/audio/voices` - List available voices
- `POST /v1/audio/speech` - Generate speech

### Request Format
```json
{
  "model": "kokoro",
  "input": "Your text here",
  "voice": "af_heart",
  "response_format": "wav",
  "download_format": "mp3",
  "speed": 1.0,
  "volume_multiplier": 1.0
}
```

### Supported Audio Formats
- `mp3` - MP3 audio (default)
- `wav` - WAV audio
- `opus` - Opus audio
- `flac` - FLAC audio
- `pcm` - Raw PCM samples

## Customization

You can modify the script to:

- Change audio format (currently WAV)
- Add additional TTS parameters
- Implement different error handling
- Add support for other CSV delimiters
- Include audio quality settings

## Example Output

```
✓ Connected to TTS server: http://localhost:8880
Available voices: af_heart, af_heart_2, af_heart_3, af_heart_4, af_heart_5, af_heart_6, af_heart_7, af_heart_8, af_heart_9, af_heart_10
Processing 4 entries...
Output directory: C:\path\to\audio_output

[1/4] Processing: welcome_message
  Text: Welcome to our application! We're glad you're here.
  Voice: af_heart
  ✓ Generated: welcome_message.wav

[2/4] Processing: error_notification
  Text: An error has occurred. Please try again or contact support.
  Voice: af_heart_2
  ✓ Generated: error_notification.wav

=== Summary ===
Successfully generated: 4 files
Errors: 0 files
Total processed: 4 entries
``` 