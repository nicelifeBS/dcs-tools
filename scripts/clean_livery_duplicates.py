#!/usr/bin/env python3
"""
Script to clean duplicate entries from DCS livery description files.
"""

import re
import sys
from pathlib import Path

def parse_livery_file(file_path):
    """Parse the livery file and extract all entries."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract the livery table entries
    # Look for the pattern: {"component", type, "texture", true};
    entries = []
    
    # Find all lines that match the livery entry pattern
    lines = content.split('\n')
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if line.startswith('{"') and line.endswith('true};'):
            entries.append((line_num, line))
    
    return entries

def analyze_duplicates(entries):
    """Analyze and identify duplicate entries."""
    seen = {}
    duplicates = []
    unique_entries = []
    
    for line_num, entry in entries:
        if entry in seen:
            duplicates.append((line_num, entry, seen[entry]))
        else:
            seen[entry] = line_num
            unique_entries.append((line_num, entry))
    
    return unique_entries, duplicates

def create_clean_livery(unique_entries):
    """Create a clean livery file with only unique entries."""
    # Sort entries by component name for better organization
    def get_component_name(entry):
        match = re.match(r'^\{"([^"]+)"', entry[1])
        return match.group(1) if match else entry[1]
    
    sorted_entries = sorted(unique_entries, key=lambda x: get_component_name(x))
    
    # Create the new content
    content = "livery = {\n"
    for _, entry in sorted_entries:
        content += f"\t{entry}\n"
    content += "}\n"
    
    return content

def main():
    if len(sys.argv) != 2:
        print("Usage: python clean_livery_duplicates.py <livery_file>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File {file_path} does not exist.")
        sys.exit(1)
    
    print(f"Analyzing {file_path}...")
    
    # Parse the file
    entries = parse_livery_file(file_path)
    print(f"Found {len(entries)} total entries")
    
    # Analyze duplicates
    unique_entries, duplicates = analyze_duplicates(entries)
    
    print(f"Found {len(unique_entries)} unique entries")
    print(f"Found {len(duplicates)} duplicate entries")
    
    if duplicates:
        print("\nDuplicate entries found:")
        for line_num, entry, original_line in duplicates[:10]:  # Show first 10
            print(f"  Line {line_num}: {entry}")
            print(f"    (Original at line {original_line})")
        
        if len(duplicates) > 10:
            print(f"  ... and {len(duplicates) - 10} more duplicates")
        
        # Create backup
        backup_path = file_path.with_suffix(file_path.suffix + '.backup')
        if backup_path.exists():
            backup_path.unlink()  # Remove existing backup
        print(f"\nCreating backup: {backup_path}")
        file_path.rename(backup_path)
        
        # Create clean file
        clean_content = create_clean_livery(unique_entries)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(clean_content)
        
        print(f"Created clean file: {file_path}")
        print(f"Removed {len(duplicates)} duplicate entries")
        print(f"File size reduced from {len(entries)} to {len(unique_entries)} entries")
    else:
        print("No duplicates found!")

if __name__ == "__main__":
    main() 