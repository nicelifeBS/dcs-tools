# Audio Leveling Tool

This tool normalizes and levels audio files using FFmpeg's professional-grade audio processing capabilities. It ensures consistent volume levels across multiple audio files while preventing clipping and maintaining audio quality.

## Features

- **Multiple Presets**: Broadcast, Streaming, Gaming, Voice, Music, Radio
- **Loudness Normalization**: EBU R128 standard compliance
- **Peak Normalization**: Prevents clipping
- **Dynamic Range Compression**: Optional compression for consistent levels
- **Batch Processing**: Process multiple files at once
- **Audio Analysis**: Analyze levels before and after processing
- **FFmpeg Integration**: Uses professional-grade audio processing

## Prerequisites

1. **FFmpeg**: Install FFmpeg and ensure it's in your PATH
   - Download from: https://ffmpeg.org/download.html
   - Or install via package manager: `choco install ffmpeg` (Windows)

## Audio Leveling Presets

### Broadcast (-23 LUFS)
- **Target**: -23 LUFS, -1 dB peak
- **Use Case**: TV, radio, professional broadcasting
- **Features**: Conservative approach, full frequency range
- **Standards**: EBU R128, ATSC A/85 compliant

### Streaming (-16 LUFS)
- **Target**: -16 LUFS, -1 dB peak
- **Use Case**: YouTube, Spotify, online platforms
- **Features**: Optimized for streaming platforms
- **Standards**: Platform-specific loudness targets

### Gaming (-18 LUFS)
- **Target**: -18 LUFS, -1 dB peak
- **Use Case**: Video games, interactive media
- **Features**: Optimized for game audio systems
- **Frequency Range**: 40 Hz - 16 kHz

### Voice (-20 LUFS)
- **Target**: -20 LUFS, -1 dB peak
- **Use Case**: Podcasts, audiobooks, speech content
- **Features**: Optimized for speech intelligibility
- **Frequency Range**: 80 Hz - 8 kHz

### Music (-14 LUFS)
- **Target**: -14 LUFS, -1 dB peak
- **Use Case**: Music production, albums
- **Features**: Preserves full frequency range
- **Frequency Range**: 20 Hz - 22 kHz

### Radio (-23 LUFS)
- **Target**: -23 LUFS, -1 dB peak
- **Use Case**: Radio transmission, communication
- **Features**: Optimized for radio systems
- **Frequency Range**: 300 Hz - 3 kHz

## Usage

### Single File Processing
```bash
python scripts/audio_leveler.py input.wav output_leveled.wav --preset broadcast
```

### Batch Processing
```bash
python scripts/audio_leveler.py input_directory output_directory --batch --preset streaming
```

### Custom Loudness Target
```bash
python scripts/audio_leveler.py input.wav output.wav --target-lufs -18 --target-peak -0.5
```

### With Compression
```bash
python scripts/audio_leveler.py input.wav output.wav --preset voice --compression
```

### Analyze Audio Levels
```bash
python scripts/audio_leveler.py input.wav output.wav --preset broadcast --analyze
```

### Command Line Options
```bash
python scripts/audio_leveler.py --help
```

Options:
- `--preset`: Audio leveling preset (broadcast, streaming, gaming, voice, music, radio)
- `--target-lufs`: Target loudness in LUFS (default: -23.0)
- `--target-peak`: Target peak in dB (default: -1.0)
- `--compression`: Apply dynamic range compression
- `--ffmpeg-path`: Path to FFmpeg executable
- `--file-pattern`: File pattern for batch processing (default: *.wav)
- `--batch`: Process input as directory
- `--analyze`: Analyze audio levels before and after processing
- `--info`: Show file information before processing

## Examples

### Normalize TTS Output for Broadcasting
```bash
python scripts/audio_leveler.py tts_output.wav broadcast_ready.wav --preset broadcast --analyze
```

### Level Gaming Audio
```bash
python scripts/audio_leveler.py game_audio.wav leveled_game.wav --preset gaming --compression
```

### Batch Process Voice Files
```bash
python scripts/audio_leveler.py voice_files/ leveled_voice/ --batch --preset voice --analyze
```

### Custom Streaming Target
```bash
python scripts/audio_leveler.py music.wav streaming_music.wav --target-lufs -14 --target-peak -0.5
```

## Integration with Existing Tools

### Complete TTS + Leveling + Radio Effect Workflow
```bash
# 1. Generate TTS files
python scripts/tts.py input.csv tts_output/

# 2. Level the TTS files
python scripts/audio_leveler.py tts_output/ leveled_tts/ --batch --preset voice --analyze

# 3. Apply radio effects to leveled files
python scripts/radio_effect.py leveled_tts/ radio_output/ --batch --effect-type military
```

### Level Radio Effect Output
```bash
# Apply radio effects first
python scripts/radio_effect.py input.wav radio.wav --effect-type military

# Then level the radio output
python scripts/audio_leveler.py radio.wav leveled_radio.wav --preset radio --analyze
```

## Technical Details

### Loudness Normalization (EBU R128)
The tool uses FFmpeg's `loudnorm` filter which implements the EBU R128 standard:

- **Integrated Loudness (I)**: Target loudness level
- **True Peak (TP)**: Maximum peak level to prevent clipping
- **Loudness Range (LRA)**: Dynamic range measurement

### Dynamic Range Compression
Optional compression using `acompressor` filter:
- **Threshold**: Level at which compression starts
- **Ratio**: Compression ratio (4:1 = 4dB input = 1dB output)
- **Attack**: How quickly compression responds
- **Release**: How quickly compression recovers

### Frequency Filtering
Preset-specific frequency ranges:
- **High-pass filter**: Removes low frequencies below threshold
- **Low-pass filter**: Removes high frequencies above threshold

## Audio Analysis

The `--analyze` option provides detailed information about audio levels:

### Input Analysis
- **Input Integrated Loudness**: Overall loudness of the original file
- **Input True Peak**: Maximum peak level in the original file
- **Input Loudness Range**: Dynamic range of the original file

### Output Analysis
- **Output Integrated Loudness**: Overall loudness after processing
- **Output True Peak**: Maximum peak level after processing
- **Output Loudness Range**: Dynamic range after processing

## Troubleshooting

### FFmpeg Not Found
``` 