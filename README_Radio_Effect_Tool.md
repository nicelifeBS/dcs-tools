# Radio Effect Tool

This tool applies radio transmission effects to audio files using FFmpeg, simulating the characteristic sound of radio communications.

## Features

- **Multiple Radio Types**: Standard, Military, Amateur, Emergency, Vintage
- **Quality Levels**: Low, Medium, High
- **Batch Processing**: Process multiple files at once
- **FFmpeg Integration**: Uses professional-grade audio processing

## Prerequisites

1. **FFmpeg**: Install FFmpeg and ensure it's in your PATH
   - Download from: https://ffmpeg.org/download.html
   - Or install via package manager: `choco install ffmpeg` (Windows)

## Radio Effect Types

### Standard
- Balanced radio transmission effect
- Good for general use

### Military
- Clear, formal communication style
- Higher compression and volume
- Narrower frequency range

### Amateur
- Variable quality simulation
- More distortion and artifacts
- Typical of amateur radio equipment

### Emergency
- Clear and loud for emergency communications
- High compression for clarity
- Optimized for urgent messages

### Vintage
- Old radio equipment simulation
- More distortion and noise
- Lower volume levels

## Usage

### Single File Processing
```bash
python scripts/radio_effect.py input.wav output_radio.wav --effect-type military
```

### Batch Processing
```bash
python scripts/radio_effect.py input_directory output_directory --batch --effect-type emergency
```

### Command Line Options
```bash
python scripts/radio_effect.py --help
```

Options:
- `--effect-type`: Type of radio effect (standard, military, amateur, emergency, vintage)
- `--quality`: Quality level (low, medium, high)
- `--ffmpeg-path`: Path to FFmpeg executable
- `--file-pattern`: File pattern for batch processing (default: *.wav)
- `--batch`: Process input as directory

## Examples

### Military Radio Effect
```bash
python scripts/radio_effect.py speech.wav military_radio.wav --effect-type military --quality high
```

### Emergency Broadcast
```bash
python scripts/radio_effect.py alert.wav emergency_radio.wav --effect-type emergency --quality high
```

### Vintage Radio Effect
```bash
python scripts/radio_effect.py music.wav vintage_radio.wav --effect-type vintage --quality low
```

### Batch Process TTS Files
```bash
python scripts/radio_effect.py "C:\Users\username\Documents\tmp" "C:\Users\username\Documents\tmp\radio" --batch --effect-type standard
```

## Technical Details

The tool applies various audio filters to simulate radio transmission:

- **High-pass filter**: Removes low frequencies (typical of radio)
- **Low-pass filter**: Limits high frequencies
- **Compression**: Simulates radio compression
- **Distortion**: Adds authenticity
- **Volume adjustment**: Optimizes levels

## Integration with TTS Tool

You can combine this with the TTS tool for complete voice generation workflow:

1. Generate TTS audio files
2. Apply radio effects to make them sound like radio transmissions
3. Use in your applications

Example workflow:
```bash
# Generate TTS files
python scripts/tts.py input.csv output_dir

# Apply radio effects to all generated files
python scripts/radio_effect.py output_dir radio_output_dir --batch --effect-type military
```
```

## 🎯 **Radio Effect Tool Features**

### **5 Radio Effect Types**:
1. **Standard** - Balanced radio transmission
2. **Military** - Clear, formal communication
3. **Amateur** - Variable quality simulation
4. **Emergency** - Clear and loud for urgent messages
5. **Vintage** - Old radio equipment simulation

### **3 Quality Levels**:
- **Low** - More aggressive filtering, smaller file sizes
- **Medium** - Balanced quality (default)
- **High** - Less aggressive filtering, better quality

### **Usage Examples**:

```bash
# Single file with military effect
python scripts/radio_effect.py input.wav output_radio.wav --effect-type military

# Batch process all WAV files
python scripts/radio_effect.py input_dir output_dir --batch --effect-type emergency

# Apply to your TTS files
python scripts/radio_effect.py "C:\Users\username\Documents\tmp" "C:\Users\username\Documents\tmp\radio" --batch
```

### **FFmpeg Filters Applied**:
- High-pass filter (removes low frequencies)
- Low-pass filter (limits high frequencies)
- Compression (simulates radio compression)
- Distortion (adds authenticity)
- Volume adjustment

The tool will check for FFmpeg availability and provide detailed feedback during processing. You can save the code above to `scripts/radio_effect.py` and start using it immediately!