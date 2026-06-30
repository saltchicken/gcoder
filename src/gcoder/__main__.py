"""
Main entry point for the gcoder application.
Handles CLI argument parsing and job orchestration.
"""
import argparse
import logging
import os
import sys

from svgpathtools import svg2paths, Document

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
    shared.add_argument('--clearance-z',
                        type=float,
                        default=5.0,
                        help="High Z height for safe global travel (mm)")
    shared.add_argument('--rapid-z',
                        type=float,
                        default=1.0,
                        help="Low Z height for rapid hops between cuts (mm)")
    shared.add_argument('--feed-xy',
                        type=int,
                        default=1000,
                        help="XY feed rate (mm/min)")
    shared.add_argument('--stepover',
                        type=float,
                        default=2.0,
                        help="Fill line spacing")
    shared.add_argument('--fill-angle',
                        type=float,
                        default=0.0,
                        help="Angle for fill pattern in degrees (e.g., 45)")
    shared.add_argument('--fill-method',
                        type=str,
                        default='auto',
                        choices=['auto', 'hatch', 'crosshatch', 'concentric', 'spiral'],
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
        args.clearance_z = 0.0
        args.rapid_z = 0.0
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

    writer = GCodeWriter(tool=tool, clearance_z=args.clearance_z, rapid_z=args.rapid_z)
    operation_name = f"SVG_{args.mode.upper()}"

    writer.build_preamble(operation_name=operation_name,
                          tool_dia=config.tool_dia)
    
    logger.info("Processing SVG: %s in %s mode", args.svg, args.mode.upper())

    # 1. Use Document to preserve all group transformations (rotations/translations)
    doc = Document(args.svg)
    transformed_paths = doc.paths()

    # 2. Use svg2paths strictly to extract the raw XML attributes in document order
    _, attributes = svg2paths(args.svg)

    profile_cutter = SVGProfileCutter(writer=writer, svg_path_file=args.svg, config=config)
    fill_cutter = SVGFillCutter(writer=writer,
                                svg_path_file=args.svg,
                                config=config,
                                stepover_percent=args.stepover,
                                fill_angle=args.fill_angle,
                                fill_method=args.fill_method)

    # 3. Zip them together so we evaluate the transformed path alongside its fill property
    for path, attrs in zip(transformed_paths, attributes):
        if len(path) == 0:
            continue

        # Check for direct attribute first
        fill_val = attrs.get('fill', '').strip().lower()
        
        # If not found, check inside the 'style' attribute
        if not fill_val:
            style = attrs.get('style', '').strip().lower()
            for part in style.split(';'):
                if ':' in part:
                    key, val = part.split(':', 1)
                    if key.strip() == 'fill':
                        fill_val = val.strip()
                        break

        has_fill = bool(fill_val and fill_val != 'none')

        if has_fill and path.isclosed():
            logger.info("Entity has fill property '%s' -> Generating FILL toolpath", fill_val)
            original_compensation = config.compensation
            config.compensation = 'inside'
            fill_cutter.offset_distance = config.tool_dia / 2.0
            fill_cutter.compensation = config.compensation
            
            fill_cutter.process_single_path(path)
            
            config.compensation = original_compensation
        else:
            logger.info("Entity has no fill -> Generating PROFILE toolpath")
            profile_cutter.process_single_path(path)

    # Retract to clearance at the very end
    writer.add_line("\n( Retract to clearance height before finishing )")
    writer.rapid(z=writer.clearance_z)

    writer.build_postamble(operation_name=operation_name)
    writer.save(args.output)

    logger.info("Successfully processed profile. Saved G-code to: %s", args.output)


if __name__ == "__main__":
    main()
