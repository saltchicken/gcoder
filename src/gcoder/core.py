"""
Core structures and classes for generating and managing G-Code output.
"""
from dataclasses import dataclass
from typing import List, Optional

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
    """Handles line-by-line formatting and saving of CNC instructions."""

    def __init__(self, tool: ToolStrategy, clearance_z: float = 5.0, rapid_z: float = 1.0) -> None:
        self.lines: List[str] = []
        self.clearance_z: float = clearance_z
        self.rapid_z: float = rapid_z
        self.tool: ToolStrategy = tool
        
        # State tracking to avoid redundant moves
        self.current_x: Optional[float] = None
        self.current_y: Optional[float] = None
        self.current_z: Optional[float] = None
        self.current_f: Optional[int] = None

    def add_line(self, line: str) -> None:
        """Appends a raw string directly to the G-Code sequence."""
        self.lines.append(line)

    def rapid(self,
              x: Optional[float] = None,
              y: Optional[float] = None,
              z: Optional[float] = None) -> None:
        """Generates a G0 rapid move, omitting redundant axes."""
        coords: List[str] = []
        
        if x is not None and (self.current_x is None or round(x, 3) != round(self.current_x, 3)):
            coords.append(f"X{x:.3f}")
            self.current_x = x
            
        if y is not None and (self.current_y is None or round(y, 3) != round(self.current_y, 3)):
            coords.append(f"Y{y:.3f}")
            self.current_y = y
            
        if z is not None and (self.current_z is None or round(z, 3) != round(self.current_z, 3)):
            coords.append(f"Z{z:.3f}")
            self.current_z = z
            
        if coords:
            self.add_line(f"G0 {' '.join(coords)}")

    def feed(self,
             x: Optional[float] = None,
             y: Optional[float] = None,
             z: Optional[float] = None,
             f: Optional[int] = None) -> None:
        """Generates a G1 linear feed move, omitting redundant axes and feedrates."""
        coords: List[str] = []
        
        if x is not None and (self.current_x is None or round(x, 3) != round(self.current_x, 3)):
            coords.append(f"X{x:.3f}")
            self.current_x = x
            
        if y is not None and (self.current_y is None or round(y, 3) != round(self.current_y, 3)):
            coords.append(f"Y{y:.3f}")
            self.current_y = y
            
        if z is not None and (self.current_z is None or round(z, 3) != round(self.current_z, 3)):
            coords.append(f"Z{z:.3f}")
            self.current_z = z
            
        if f is not None and f != self.current_f:
            coords.append(f"F{f}")
            self.current_f = f
            
        if coords:
            self.add_line(f"G1 {' '.join(coords)}")

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def arc(self,
            x: float,
            y: float,
            i: float,
            j: float,
            z: Optional[float] = None,
            f: Optional[int] = None,
            cw: bool = True) -> None:
        """Generates a G2/G3 arc move."""
        command = "G2" if cw else "G3"
        parts: List[str] = [
            command, f"X{x:.3f}", f"Y{y:.3f}", f"I{i:.3f}", f"J{j:.3f}"
        ]
        
        # Always update current X/Y for the endpoint of the arc
        self.current_x = x
        self.current_y = y
        
        if z is not None and (self.current_z is None or round(z, 3) != round(self.current_z, 3)):
            parts.append(f"Z{z:.3f}")
            self.current_z = z
            
        if f is not None and f != self.current_f:
            parts.append(f"F{f}")
            self.current_f = f
            
        self.add_line(' '.join(parts))

    def build_preamble(self,
                       operation_name: str = "GCode_Operation",
                       tool_dia: float = 3.175) -> None:
        """Inserts the initial setup, coordinate systems, and tool metadata."""
        self.lines.extend([
            "(Exported by gcoder)",
            f"(META: MODE={self.tool.name.upper()})",
            f"(META: TOOL_DIA={tool_dia:.3f})",
            "(Begin preamble)", "G17 G90",
            "G21", "G54",
            f"(Begin operation: {operation_name})"
        ])

    def build_postamble(self, operation_name: str = "GCode_Operation") -> None:
        """Closes out the operation and machine safely without making movements."""
        self.lines.extend([
            f"(Finish operation: {operation_name})",
            "(Begin postamble)", "M5", "G17 G90", "M2"
        ])

    def save(self, filename: str) -> None:
        """Writes the buffered lines to a file."""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.lines))

    def tool_on(self) -> None:
        """Activates the tool using the assigned strategy."""
        self.tool.tool_on(self)

    def tool_off(self) -> None:
        """Deactivates the tool using the assigned strategy."""
        self.tool.tool_off(self)
