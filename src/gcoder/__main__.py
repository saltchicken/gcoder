"""
Main entry point for the gcoder application.
Handles CLI argument parsing and job orchestration.
"""
import argparse
import logging
import os
import sys

from .core import GCodeWriter
from .core import JobConfig
from .operations import SVGFillCutter
from .operations import SVGProfileCutter
from .tools import LaserStrategy
from .tools import MillStrategy
from .tools import PenStrategy

# Configure standard logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments for the application."""
    parser = argparse.ArgumentParser(
        description="Generate G-Code toolpaths from SVGs.")
    subparsers = parser.add_subparsers(dest='mode',
                                       required=True,
                                       help="Target machine type")

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--svg',
                        type=str,
                        required=True,
                        help="Path to input SVG")
    shared.add_argument('--output',
                        type=str,
                        default="output.nc",
                        help="Output file path")
    shared.add_argument('--safe-z',
                        type=float,
                        default=5.0,
                        help="Safe travel Z (mm)")
    shared.add_argument('--feed-xy',
                        type=int,
                        default=1000,
                        help="XY feed rate (mm/min)")
    shared.add_argument('--fill',
                        action='store_true',
                        help="Perform interior fill")
    shared.add_argument('--stepover',
                        type=float,
                        default=0.4,
                        help="Fill line spacing")
    shared.add_argument('--fill-angle',
                        type=float,
                        default=0.0,
                        help="Angle for fill pattern in degrees (e.g., 45)")
    shared.add_argument('--fill-method',
                        type=str,
                        default='auto',
                        choices=['auto', 'hatch', 'crosshatch', 'concentric'],
                        help="Override tool default fill pattern")

    mill = subparsers.add_parser('mill',
                                 parents=[shared],
                                 help="CNC Router/Mill mode")
    mill.add_argument('--compensation',
                      type=str,
                      default='outside',
                      choices=['outside', 'inside', 'on'])
    mill.add_argument('--tool-dia',
                      type=float,
                      default=3.175,
                      help="Endmill diameter (mm)")
    mill.add_argument('--depth',
                      type=float,
                      default=-3.0,
                      help="Final cutting depth (mm)")
    mill.add_argument('--step-down',
                      type=float,
                      default=1.0,
                      help="Z drop per pass (mm)")
    mill.add_argument('--feed-ramp',
                      type=int,
                      default=400,
                      help="Plunge feed rate (mm/min)")

    laser = subparsers.add_parser('laser',
                                  parents=[shared],
                                  help="Laser engraver mode")
    laser.add_argument('--compensation',
                       type=str,
                       default='on',
                       choices=['outside', 'inside', 'on'])
    laser.add_argument('--kerf',
                       type=float,
                       default=0.1,
                       help="Laser beam width (mm)")
    laser.add_argument('--power',
                       type=int,
                       default=1000,
                       help="Laser intensity (S-value)")
    laser.add_argument('--focus-z',
                       type=float,
                       default=0.0,
                       help="Z height for focus")

    pen = subparsers.add_parser('pen',
                                parents=[shared],
                                help="Pen plotter mode")
    pen.add_argument('--pen-down-z',
                     type=float,
                     default=-1.0,
                     help="Z height to press pen")

    return parser.parse_args()


def main() -> None:
    """Main execution block for parsing arguments and initiating generation."""
    args = parse_arguments()

    if not os.path.exists(args.svg):
        logger.error("SVG file not found at '%s'", args.svg)
        sys.exit(1)

    if args.mode == 'mill':
        tool = MillStrategy(intensity=10000)
        config = JobConfig(tool_dia=args.tool_dia,
                           depth=args.depth,
                           step_down=args.step_down,
                           feed_ramp=args.feed_ramp,
                           feed_xy=args.feed_xy,
                           compensation=args.compensation)
    elif args.mode == 'laser':
        tool = LaserStrategy(intensity=args.power)
        config = JobConfig(tool_dia=args.kerf,
                           depth=args.focus_z,
                           step_down=args.focus_z,
                           feed_ramp=args.feed_xy,
                           feed_xy=args.feed_xy,
                           compensation=args.compensation)
    elif args.mode == 'pen':
        tool = PenStrategy(pen_z=args.pen_down_z)
        config = JobConfig(tool_dia=0.1,
                           depth=args.pen_down_z,
                           step_down=args.pen_down_z,
                           feed_ramp=args.feed_xy,
                           feed_xy=args.feed_xy,
                           compensation='on')
    else:
        logger.error("Unknown machine mode.")
        sys.exit(1)

    writer = GCodeWriter(tool=tool, safe_z=args.safe_z)
    operation_name = f"SVG_{args.mode.upper()}"

    writer.build_preamble(operation_name=operation_name,
                          tool_dia=config.tool_dia)
    logger.info("Processing SVG: %s in %s mode", args.svg, args.mode.upper())

    if args.fill:
        logger.info("Generating FILL toolpaths for %s", args.svg)
        config.compensation = 'inside'
        cutter = SVGFillCutter(writer=writer,
                               svg_path_file=args.svg,
                               config=config,
                               stepover_percent=args.stepover,
                               fill_angle=args.fill_angle,
                               fill_method=args.fill_method)
    else:
        logger.info("Generating PROFILE toolpaths for %s", args.svg)
        cutter = SVGProfileCutter(writer=writer,
                                  svg_path_file=args.svg,
                                  config=config)

    cutter.execute()

    writer.build_postamble(operation_name=operation_name)
    writer.save(args.output)

    logger.info("Successfully processed profile. Saved G-code to: %s",
                args.output)


if __name__ == "__main__":
    main()
