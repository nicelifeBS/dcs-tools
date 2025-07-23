import pandas as pd
import math
import argparse
import sys
import os
from xml.etree.ElementTree import Element, SubElement, ElementTree

def uv_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def csv_to_svg(csv_path, svg_path, max_dist=0.05, width=1000, height=1000, flip_vertical=False, wrap_u=False):
    # Load CSV
    df = pd.read_csv(csv_path)
    
    # Check for missing u,v columns
    if "u" not in df.columns or "v" not in df.columns:
        print(f"Error: CSV must contain 'u' and 'v' columns. Found columns: {list(df.columns)}")
        return
    
    # Handle UV wrapping: map 1.0-2.0e to00 range
    if wrap_u:
        df["u"] = df["u"] - 1.0
    
    df = df[["u", "v"]].dropna().copy()
    
    # Remove points where u or v are not in [0, 1]
    df = df[(df["u"] >= 0.0) & (df["u"] <= 1.0) & (df["v"] >= 0.0) & (df["v"] <= 1.0)]
    
    # Remove duplicate points
    df = df.drop_duplicates()

    # Convert UV to scaled coordinates (with optional vertical flip)
    if flip_vertical:
        points = [(u * width, (1 - v) * height) for u, v in df[["u", "v"]].values]
    else:
        points = [(u * width, v * height) for u, v in df[["u", "v"]].values]

    # Check if we have any points to process
    if len(points) == 0:
        print(f"Warning: No valid data points found in {csv_path}. SVG not created.")
        return

    # Group points into segments based on max distance
    segments = []
    current_segment = [points[0]]
    for i in range(1, len(points)):
        if uv_distance(points[i-1], points[i]) < max_dist * width:
            current_segment.append(points[i])
        else:
            if len(current_segment) > 1:
                segments.append(current_segment)
            current_segment = [points[i]]
    if len(current_segment) > 1:
        segments.append(current_segment)

    # Create SVG
    svg = Element("svg", xmlns="http://www.w3.org/2000/svg",
                  width=str(width), height=str(height))
    for seg in segments:
        polyline_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in seg)
        SubElement(svg, "polyline", points=polyline_points,
                   fill="none", stroke="black", stroke_width="1")

    # Write SVG
    ElementTree(svg).write(svg_path)
    print(f"SVG written to {svg_path}")

def main():
    parser = argparse.ArgumentParser(description='Convert CSV with UV coordinates to SVG')
    parser.add_argument('input_csv', help='Input CSV file path')
    parser.add_argument('output_svg', nargs='?', help='Output SVG file path (optional: defaults to input filename with .svg extension)')
    parser.add_argument('--max-dist', type=float, default=0.05, 
                       help='Maximum distance between points to group into segments (default: 0.05)')
    parser.add_argument('--width', type=int, default=1000,
                       help='SVG width in pixels (default: 1000)')
    parser.add_argument('--height', type=int, default=1000,
                       help='SVG height in pixels (default: 1000)')
    parser.add_argument('--flip-vertical', action='store_true',
                       help='Flip the SVG vertically (default: no flip)')
    parser.add_argument('--wrap-u', action='store_true',
                       help='Wrap the U coordinate from 1.0-2.0 to 0.0-1.0 (default: no wrap)')
    
    args = parser.parse_args()
    
    # Generate output filename if not provided
    if args.output_svg is None:
        base_name = os.path.splitext(args.input_csv)[0]
        args.output_svg = base_name + '.svg'
    try:
        csv_to_svg(args.input_csv, args.output_svg, args.max_dist, args.width, args.height, args.flip_vertical, args.wrap_u)
    except FileNotFoundError:
        print(f"Error: Input file '{args.input_csv}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()