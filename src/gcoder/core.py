"""
Core structures and classes for generating and managing G-Code output for pen plotting.
"""
from typing import Optional, Sequence, Tuple

from ezdxf.path import make_path
from gscrib import GCodeBuilder


class GCodeWriter:
    """Handles line-by-line formatting and saving of CNC instructions using Gscrib."""

    def __init__(self, output_file: str, clearance_z: float = 5.0, rapid_z: float = 1.0, pen_down_z: float = -1.0) -> None:
        self.builder = GCodeBuilder(output=output_file)
        self.clearance_z: float = clearance_z
        self.rapid_z: float = rapid_z
        self.pen_z: float = pen_down_z
        self.current_f: Optional[int] = None

    def add_line(self, line: str) -> None:
        """Appends a comment or raw instruction to the G-Code sequence."""
        line = line.strip()
        if not line:
            return
            
        if line.startswith('(') and line.endswith(')'):
            self.builder.comment(line[1:-1].strip(' -'))
        else:
            if hasattr(self.builder, 'command'):
                self.builder.command(line)
            else:
                self.builder.annotate(line)

    def rapid(self,
              x: Optional[float] = None,
              y: Optional[float] = None,
              z: Optional[float] = None) -> None:
        """Generates a G0 rapid move."""
        kwargs = {}
        if x is not None: kwargs['x'] = round(x, 3)
        if y is not None: kwargs['y'] = round(y, 3)
        if z is not None: kwargs['z'] = round(z, 3)
        
        if kwargs:
            self.builder.rapid(**kwargs)

    def feed(self,
             x: Optional[float] = None,
             y: Optional[float] = None,
             z: Optional[float] = None,
             f: Optional[int] = None) -> None:
        """Generates a G1 linear feed move."""
        if f is not None and f != self.current_f:
            self.builder.set_feed_rate(f)
            self.current_f = f
            
        kwargs = {}
        if x is not None: kwargs['x'] = round(x, 3)
        if y is not None: kwargs['y'] = round(y, 3)
        if z is not None: kwargs['z'] = round(z, 3)
        
        if kwargs:
            self.builder.move(**kwargs)

    def build_preamble(self, operation_name: str = "GCode_Operation") -> None:
        """Inserts the initial setup, coordinate systems, and tool metadata."""
        self.builder.comment("Exported by gcoder via Gscrib")
        self.builder.comment("META: MODE=PEN")
        self.builder.comment("Begin preamble")
        
        self.builder.set_plane("xy")
        self.builder.absolute_mode()
        
        if hasattr(self.builder, 'set_length_units'):
            self.builder.set_length_units("mm")
            
        self.builder.comment(f"Begin operation: {operation_name}")

    def build_postamble(self, operation_name: str = "GCode_Operation") -> None:
        """Closes out the operation and machine safely."""
        self.builder.comment(f"Finish operation: {operation_name}")
        self.builder.comment("Begin postamble")
        
        self.pen_up()
        self.builder.set_plane("xy")
        self.builder.absolute_mode()
        self.builder.stop()

    def save(self, filename: str) -> None:
        """Writes the buffered lines to a file."""
        if hasattr(self.builder, 'flush'):
            self.builder.flush()

    def pen_down(self) -> None:
        """Activates the tool by lowering it."""
        self.rapid(z=self.pen_z)

    def pen_up(self) -> None:
        """Deactivates the tool by raising it."""
        self.rapid(z=self.rapid_z)

    def execute_profile(self, path: Sequence[Tuple[float, float]], feed_xy: int) -> None:
        """Executes the toolpath trace using dragging mechanics."""
        if not path:
            return

        self.add_line("\n(--- New Outline Profile ---)")
        start_x, start_y = path[0]
        
        self.rapid(z=self.clearance_z)
        self.rapid(x=start_x, y=start_y)
        self.rapid(z=self.rapid_z)
        
        self.pen_down()
        for x, y in path[1:]:
            self.feed(x=x, y=y, f=feed_xy)
            
        self.pen_up()
        self.rapid(z=self.rapid_z)


class DXFOutlineCutter:
    """Generates continuous geometric toolpaths tracing the contours of the DXF paths directly."""
    
    def __init__(self, writer: GCodeWriter, feed_xy: int) -> None:
        self.writer = writer
        self.feed_xy = feed_xy

    def process_entity(self, entity, flatten_distance: float = 0.01) -> None:
        """Processes an isolated DXF entity to generate an outline."""
        paths = []
        
        # ezdxf.path.make_path fails for complex entities (like LWPOLYLINEs or paths). 
        # We need to fall back to make_paths_from_entity for broader support.
        try:
            from ezdxf.path import make_paths_from_entity
            paths = list(make_paths_from_entity(entity))
        except Exception:
            pass
            
        if not paths:
            try:
                paths = [make_path(entity)]
            except Exception:
                # Completely unsupported entity type
                return

        for p in paths:
            points = [(float(v.x), float(v.y)) for v in p.flattening(distance=flatten_distance)]
            if len(points) < 2:
                continue
            
            if p.is_closed and points[0] != points[-1]:
                points.append(points[0])

            self.writer.execute_profile(points, self.feed_xy)
