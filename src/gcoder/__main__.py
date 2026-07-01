"""
Main entry point for the gcoder application.
Handles CLI argument parsing and job orchestration for pen plotting.
"""
import argparse
import logging
import os
import sys

import ezdxf

from .core import DXFOutlineCutter
from .core import GCodeWriter

# Configure standard logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments for the application."""
    parser = argparse.ArgumentParser(
        description="Generate G-Code outlines from DXF files using a pen/drag tool.")
    
    parser.add_argument('--dxf',
                        type=str,
                        required=True,
                        help="Path to input DXF")
    parser.add_argument('--output',
                        type=str,
                        default="output.nc",
                        help="Output file path")
    parser.add_argument('--clearance-z',
                        type=float,
                        default=5.0,
                        help="High Z height for safe global travel (mm)")
    parser.add_argument('--rapid-z',
                        type=float,
                        default=1.0,
                        help="Low Z height for rapid hops between cuts (mm)")
    parser.add_argument('--pen-down-z',
                        type=float,
                        default=-1.0,
                        help="Z height to press pen down (mm)")
    parser.add_argument('--feed-xy',
                        type=int,
                        default=1000,
                        help="XY feed rate (mm/min)")

    return parser.parse_args()


def main() -> None:
    """Main execution block for parsing arguments and initiating generation."""
    args = parse_arguments()

    if not os.path.exists(args.dxf):
        logger.error("DXF file not found at '%s'", args.dxf)
        sys.exit(1)

    writer = GCodeWriter(output_file=args.output,
                         clearance_z=args.clearance_z,
                         rapid_z=args.rapid_z,
                         pen_down_z=args.pen_down_z)
    
    operation_name = "DXF_PEN_OUTLINE"

    writer.build_preamble(operation_name=operation_name)
    
    logger.info("Processing DXF: %s for outlining", args.dxf)

    try:
        doc = ezdxf.readfile(args.dxf)
        msp = doc.modelspace()
    except IOError:
        logger.error("Not a DXF file or a generic I/O error.")
        sys.exit(1)
    except ezdxf.DXFStructureError:
        logger.error("Invalid or corrupted DXF file.")
        sys.exit(1)

    cutter = DXFOutlineCutter(writer=writer, feed_xy=args.feed_xy)

    # Process all entities in modelspace
    for entity in msp:
        layer_name = entity.dxf.layer if hasattr(entity.dxf, 'layer') else 'unknown'
        logger.info("Outlining entity on layer '%s'", layer_name)
        cutter.process_entity(entity)

    # Retract to clearance at the very end
    writer.add_line("\n( Retract to clearance height before finishing )")
    writer.rapid(z=writer.clearance_z)

    writer.build_postamble(operation_name=operation_name)
    writer.save(args.output)

    logger.info("Successfully processed DXF. Saved G-code to: %s", args.output)


if __name__ == "__main__":
    main()
