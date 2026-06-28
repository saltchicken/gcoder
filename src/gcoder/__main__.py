import argparse
import sys
from .core import GCodeWriter
from .operations import cut_helical_hole
from .patterns import generate_grid

def main():
    parser = argparse.ArgumentParser(description="Generate G-Code toolpaths.")
    
    # Grid parameters
    parser.add_argument('--cols', type=int, default=4, help="Number of columns")
    parser.add_argument('--rows', type=int, default=3, help="Number of rows")
    parser.add_argument('--spacing', type=float, default=40.0, help="Grid spacing (mm)")
    
    # Tool and Hole parameters
    parser.add_argument('--tool-dia', type=float, default=6.0, help="Tool diameter (mm)")
    parser.add_argument('--hole-dia', type=float, default=10.0, help="Hole diameter (mm)")
    parser.add_argument('--depth', type=float, default=-5.0, help="Final hole depth (mm)")
    parser.add_argument('--step-down', type=float, default=1.0, help="Z drop per revolution (mm)")
    
    # Machine parameters
    parser.add_argument('--feed-xy', type=int, default=1200, help="XY feed rate (mm/min)")
    parser.add_argument('--feed-ramp', type=int, default=800, help="Plunge/ramp feed rate (mm/min)")
    parser.add_argument('--safe-z', type=float, default=5.0, help="Safe Z clearance (mm)")
    
    # Output
    parser.add_argument('--output', type=str, default="helical_grid.nc", help="Output file path")
    
    args = parser.parse_args()

    # Input validation
    if args.tool_dia >= args.hole_dia:
        print("Error: Tool diameter must be smaller than hole diameter.", file=sys.stderr)
        sys.exit(1)

    # Initialize the core writer
    writer = GCodeWriter(safe_z=args.safe_z)
    writer.build_preamble()

    # Generate the layout and apply operations
    for cx, cy in generate_grid(args.rows, args.cols, args.spacing):
        cut_helical_hole(
            writer=writer,
            cx=cx, cy=cy,
            tool_dia=args.tool_dia, 
            hole_dia=args.hole_dia, 
            depth=args.depth,
            step_down=args.step_down, 
            feed_xy=args.feed_xy, 
            feed_ramp=args.feed_ramp
        )

    # Finalize and export
    writer.build_postamble()
    writer.save(args.output)
    
    print(f"Generated {args.cols * args.rows} helical holes.")
    print(f"Saved toolpath to {args.output}")

if __name__ == "__main__":
    main()
