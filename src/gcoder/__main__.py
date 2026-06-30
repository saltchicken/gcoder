import argparse
import logging
import os
import sys

from .core import GCodeWriter
from .operations import SVGProfileCutter
from .tools import LaserStrategy, MillStrategy, PenStrategy

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

def main() -> None:
    # 1. Main Parser
    parser = argparse.ArgumentParser(description="Generate G-Code toolpaths from SVGs.")
    subparsers = parser.add_subparsers(dest='mode', required=True, help="Target machine type")

    # 2. Shared Arguments (Parent Parser)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--svg', type=str, required=True, help="Path to input SVG")
    shared.add_argument('--output', type=str, default="output.nc", help="Output file path")
    shared.add_argument('--safe-z', type=float, default=5.0, help="Safe travel Z (mm)")
    shared.add_argument('--feed-xy', type=int, default=1000, help="XY feed rate (mm/min)")
    shared.add_argument('--fill', action='store_true', help="Perform an interior fill instead of an outline")
    shared.add_argument('--stepover', type=float, default=0.4, help="Fill line spacing as a percentage of tool diameter")

    # 3. Mill Sub-command
    mill = subparsers.add_parser('mill', parents=[shared], help="CNC Router/Mill mode")
    mill.add_argument('--compensation', type=str, default='outside', choices=['outside', 'inside', 'on'])
    mill.add_argument('--tool-dia', type=float, default=3.175, help="Endmill diameter (mm)")
    mill.add_argument('--depth', type=float, default=-3.0, help="Final cutting depth (mm)")
    mill.add_argument('--step-down', type=float, default=1.0, help="Z drop per pass (mm)")
    mill.add_argument('--feed-ramp', type=int, default=400, help="Plunge feed rate (mm/min)")

    # 4. Laser Sub-command
    laser = subparsers.add_parser('laser', parents=[shared], help="Laser engraver mode")
    laser.add_argument('--compensation', type=str, default='on', choices=['outside', 'inside', 'on'])
    laser.add_argument('--kerf', type=float, default=0.1, help="Laser beam width for compensation (mm)")
    laser.add_argument('--power', type=int, default=1000, help="Laser intensity (S-value)")
    laser.add_argument('--focus-z', type=float, default=0.0, help="Z height for ideal laser focus")

    # 5. Pen Plotter Sub-command
    pen = subparsers.add_parser('pen', parents=[shared], help="Pen plotter mode")
    pen.add_argument('--pen-down-z', type=float, default=-1.0, help="Z height to press pen to paper")

    # Parse the arguments
    args = parser.parse_args()

    if not os.path.exists(args.svg):
        logger.error(f"SVG file not found at '{args.svg}'")
        sys.exit(1)

    # 6. Instantiate the correct Tool Strategy
    if args.mode == 'laser':
        tool = LaserStrategy(intensity=getattr(args, 'power', 1000))
    elif args.mode == 'pen':
        tool = PenStrategy(pen_z=getattr(args, 'pen_down_z', getattr(args, 'depth', 0.0)))
    elif args.mode == 'mill':
        tool = MillStrategy(intensity=getattr(args, 'power', 10000))

    # Initialize the core writer via dependency injection
    writer = GCodeWriter(tool=tool, safe_z=args.safe_z)
    operation_name = f"SVG_{args.mode.upper()}"
    
    # 7. Unify arguments for the SVGProfileCutter
    tool_dia = getattr(args, 'tool_dia', getattr(args, 'kerf', 0.1))
    depth = getattr(args, 'depth', getattr(args, 'focus_z', getattr(args, 'pen_down_z', 0.0)))
    step_down = getattr(args, 'step_down', depth) 
    feed_ramp = getattr(args, 'feed_ramp', args.feed_xy)
    compensation = getattr(args, 'compensation', 'on') 

    writer.build_preamble(operation_name=operation_name, tool_dia=tool_dia)
    logger.info(f"Processing SVG: {args.svg} in {args.mode.upper()} mode")
    
    if args.fill:
        logger.info(f"Generating FILL toolpaths for {args.svg}")
        from .operations import SVGFillCutter
        cutter = SVGFillCutter(
            writer=writer,
            svg_path_file=args.svg,
            compensation='inside', 
            tool_dia=tool_dia,
            depth=depth,
            step_down=step_down,
            feed_xy=args.feed_xy,
            feed_ramp=feed_ramp,
            stepover_percent=args.stepover
        )
    else:
        logger.info(f"Generating PROFILE toolpaths for {args.svg}")
        cutter = SVGProfileCutter(
            writer=writer,
            svg_path_file=args.svg,
            compensation=compensation,
            tool_dia=tool_dia,
            depth=depth,
            step_down=step_down,
            feed_xy=args.feed_xy,
            feed_ramp=feed_ramp
        )
        
    cutter.execute()

    writer.build_postamble(operation_name=operation_name)
    writer.save(args.output)

    logger.info(f"Successfully processed profile. Saved G-code to: {args.output}")

if __name__ == "__main__":
    main()
