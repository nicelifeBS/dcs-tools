# DCS Toolkit

Helpers for Digital Combat Simulator World. For mission making, livery creation and other stuff.

## Overview

The DCS Toolkit is a collection of Python utilities designed to streamline various tasks related to Digital Combat Simulator (DCS) World. Whether you're creating custom liveries, working with UV coordinates, or managing texture conversions, these tools will help automate and simplify your workflow.

## Tools Included

### 1. CSV to SVG Converter (`csvTosvg.py`)
Converts CSV files containing UV coordinates into SVG vector graphics. Perfect for visualizing texture mappings and creating reference images for livery work.

**Features:**
- Converts UV coordinate data to scalable vector graphics
- Configurable distance threshold for point grouping
- Optional vertical flip for different coordinate systems
- Customizable SVG dimensions
- Automatic output filename generation

**Usage:**
```bash
python scripts/csvTosvg.py input.csv output.svg
python scripts/csvTosvg.py input.csv --max-dist 0.03 --width 800 --height 800 --flip-vertical
```

### 2. Livery Duplicate Cleaner (`clean_livery_duplicates.py`)
Removes duplicate entries from DCS livery description files, helping to maintain clean and efficient livery configurations.

**Features:**
- Automatically detects and removes duplicate livery entries
- Creates backup files before making changes
- Provides detailed analysis of duplicates found
- Sorts entries by component name for better organization
- Preserves original file structure

**Usage:**
```bash
python scripts/clean_livery_duplicates.py path/to/livery.lua
```

### 3. PNG to DDS Converter (`watch_and_convert.py`)
Monitors a directory for PNG files and automatically converts them to DDS format using NVIDIA Texture Tools. Essential for livery texture optimization.

**Features:**
- Real-time file watching with automatic conversion
- Configurable input and output directories
- Multiple compression format support (BC1, BC3, BC7)
- Uses NVIDIA Texture Tools for optimal compression
- Detailed conversion logging

**Usage:**
```bash
python scripts/watch_and_convert.py /path/to/pngs /path/to/dds
```

## Installation

### Prerequisites
- Python 3.12.5 or higher
- NVIDIA Texture Tools (for PNG to DDS conversion)

### Setup
1. Clone or download this repository
2. Install Python dependencies:
   ```bash
   pip install pandas watchdog
   ```
   Or use uv (recommended):
   ```bash
   uv sync
   ```

### NVIDIA Texture Tools Installation
For the PNG to DDS converter, you'll need NVIDIA Texture Tools:
1. Download from [NVIDIA Developer](https://developer.nvidia.com/nvidia-texture-tools)
2. Install to the default location or update the path in `watch_and_convert.py`

## Project Structure

```
Tools/
├── README.md              # This file
├── pyproject.toml         # Project configuration
├── uv.lock               # Dependency lock file
└── scripts/              # Tool scripts
    ├── csvTosvg.py       # CSV to SVG converter
    ├── clean_livery_duplicates.py  # Livery duplicate cleaner
    ├── watch_and_convert.py       # PNG to DDS converter
    ├── csv2svg.spec      # PyInstaller spec file
    ├── build/            # Build artifacts
    └── dist/             # Distribution files
```

## Use Cases

### Livery Creation
- Use the CSV to SVG converter to visualize UV mappings from 3D models
- Clean up livery files to remove duplicate texture references
- Automatically convert PNG textures to optimized DDS format

### Mission Development
- Convert coordinate data for mission planning
- Create reference graphics for briefing materials

### Asset Management
- Batch process texture files for optimal performance
- Maintain clean livery configurations across multiple aircraft

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve the toolkit. When contributing:

1. Follow the existing code style
2. Add appropriate documentation for new features
3. Test your changes thoroughly
4. Update this README if adding new tools

## License

This project is open source. Please check individual files for specific licensing information.

## Support

For issues or questions:
1. Check the existing documentation
2. Review the script help messages (`python script.py --help`)
3. Open an issue on the project repository

---

*Happy flying in DCS World!*