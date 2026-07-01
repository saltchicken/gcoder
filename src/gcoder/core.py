"""
Core structures and classes for generating and managing G-Code output.
"""
from dataclasses import dataclass
from typing import Optional

from gscrib import GCodeBuilder

from .tools import ToolStrategy


@dataclass
class JobConfig:
    """Unified configuration mapping for all tool types."""
    tool_dia: float
    depth: float
    step_down: float
    feed_ramp: int
    feed_xy: int
    compensation: str


class GCodeWriter:
    """Handles line-by-line formatting and saving of CNC instructions using Gscrib."""

    def __init__(self, tool: ToolStrategy, output_file: str, clearance_z: float = 5.0, rapid_z: float = 1.0) -> None:
        self.builder = GCodeBuilder(output=output_file)
        self.clearance_z: float = clearance_z
        self.rapid_z: float = rapid_z
        self.tool: ToolStrategy = tool
        self.current_f: Optional[int] = None

    def add_line(self, line: str) -> None:
        """Appends a comment or raw instruction to the G-Code sequence."""
        line = line.strip()
        if not line:
            return
            
        if line.startswith('(') and line.endswith(')'):
            # Pass comments straight to gscrib without the parens
            self.builder.comment(line[1:-1].strip(' -'))
        else:
            # Fallback for arbitrary strings
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

    def build_preamble(self,
                       operation_name: str = "GCode_Operation",
                       tool_dia: float = 3.175) -> None:
        """Inserts the initial setup, coordinate systems, and tool metadata."""
        self.builder.comment("Exported by gcoder via Gscrib")
        self.builder.comment(f"META: MODE={self.tool.name.upper()}")
        self.builder.comment(f"META: TOOL_DIA={tool_dia:.3f}")
        self.builder.comment("Begin preamble")
        
        # Core configuration via gscrib
        self.builder.set_plane("xy")  # <--- Changed to lowercase 'xy'
        self.builder.absolute_mode()
        
        if hasattr(self.builder, 'set_length_units'):
            self.builder.set_length_units("mm")
            
        self.builder.comment(f"Begin operation: {operation_name}")

    def build_postamble(self, operation_name: str = "GCode_Operation") -> None:
        """Closes out the operation and machine safely."""
        self.builder.comment(f"Finish operation: {operation_name}")
        self.builder.comment("Begin postamble")
        
        self.tool_off()
        self.builder.set_plane("xy")  # <--- Changed to lowercase 'xy'
        self.builder.absolute_mode()
        self.builder.stop()

    def save(self, filename: str) -> None:
        """Writes the buffered lines to a file."""
        if hasattr(self.builder, 'write') and callable(self.builder.write):
            try:
                self.builder.write(filename)
            except TypeError:
                # Fallback if the build method just returns the final string
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.builder.write())
        elif hasattr(self.builder, 'build'):
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.builder.build())
        else:
            self.builder.flush()

    def tool_on(self) -> None:
        """Activates the tool using the assigned strategy."""
        self.tool.tool_on(self)

    def tool_off(self) -> None:
        """Deactivates the tool using the assigned strategy."""
        self.tool.tool_off(self)
