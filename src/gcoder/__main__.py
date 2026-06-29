import argparse
import logging
import os
import sys

from .core import GCodeWriter
from .operations import SVGProfileCutter

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate G-Code toolpaths from SVGs.")

    # SVG profile requirements
    parser.add_argument('--svg',
                        type=str,
                        required=True,
                        help="Path to the input SVG file")
    parser.add_argument(
        '--compensation',
        type=str,
        default='on',
        choices=['outside', 'inside', 'on'],
        help="Tool compensation position relative to the vector profile")

    # Tool parameters
    parser.add_argument('--tool-dia',
                        type=float,
                        default=3.175,
                        help="Tool diameter (mm)")
    parser.add_argument('--depth',
                        type=float,
                        default=-3.0,
                        help="Final cutting depth (mm)")
    parser.add_argument('--step-down',
                        type=float,
                        default=1.0,
                        help="Z drop per pass (mm)")

    # Machine speeds
    parser.add_argument('--feed-xy',
                        type=int,
                        default=1000,
                        help="XY feed rate (mm/min)")
    parser.add_argument('--feed-ramp',
                        type=int,
                        default=400,
                        help="Plunge feed rate (mm/min)")
    parser.add_argument('--safe-z',
                        type=float,
                        default=5.0,
                        help="Safe Z clearance (mm)")

    # Output
    parser.add_argument('--output',
                        type=str,
                        default="profile_output.nc",
                        help="Output file path")

    args = parser.parse_args()

    if not os.path.exists(args.svg):
        logger.error(f"SVG file not found at '{args.svg}'")
        sys.exit(1)

    # Initialize the core writer
    writer = GCodeWriter(safe_z=args.safe_z)
    operation_name = f"SVG_Profile_{args.compensation.upper()}"
    
    # Pass the tool diameter to embed the metadata
    writer.build_preamble(operation_name=operation_name, tool_dia=args.tool_dia)

    logger.info(f"Processing SVG: {args.svg}")
    
    # Generate toolpath using the Class directly (Legacy wrapper removed)
    cutter = SVGProfileCutter(
        writer=writer,
        svg_path_file=args.svg,
        compensation=args.compensation,
        tool_dia=args.tool_dia,
        depth=args.depth,
        step_down=args.step_down,
        feed_xy=args.feed_xy,
        feed_ramp=args.feed_ramp
    )
    cutter.execute()

    # Finalize and export
    writer.build_postamble(operation_name=operation_name)
    writer.save(args.output)

    logger.info(f"Successfully processed profile with '{args.compensation}' alignment.")
    logger.info(f"Saved G-code toolpath to: {args.output}")


if __name__ == "__main__":
    main()
