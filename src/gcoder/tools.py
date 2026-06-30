import numpy as np
from abc import ABC, abstractmethod
from typing import List, Tuple, TYPE_CHECKING

# Avoid circular imports for type hinting
if TYPE_CHECKING:
    from .core import GCodeWriter

class ToolStrategy(ABC):
    """Base class for different machine tools (Mill, Laser, Pen)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the tool mode."""
        pass

    @property
    @abstractmethod
    def fill_method(self) -> str:
        """Preferred fill geometry ('hatch' or 'concentric')."""
        pass

    @abstractmethod
    def tool_on(self, writer: 'GCodeWriter') -> None:
        pass

    @abstractmethod
    def tool_off(self, writer: 'GCodeWriter') -> None:
        pass

    @abstractmethod
    def execute_profile(self, writer: 'GCodeWriter', path: List[Tuple[float, float]], is_closed: bool, feed_xy: int, depth: float, step_down: float) -> None:
        """Executes the toolpath trace."""
        pass


class LaserStrategy(ToolStrategy):
    def __init__(self, intensity: int):
        self.intensity = intensity

    @property
    def name(self) -> str:
        return 'laser'

    @property
    def fill_method(self) -> str:
        return 'hatch'

    def tool_on(self, writer: 'GCodeWriter') -> None:
        writer.add_line(f"M4 S{self.intensity}")

    def tool_off(self, writer: 'GCodeWriter') -> None:
        writer.add_line("M5")

    def execute_profile(self, writer: 'GCodeWriter', path: List[Tuple[float, float]], is_closed: bool, feed_xy: int, depth: float, step_down: float) -> None:
        writer.rapid(z=1.0)
        self.tool_on(writer)
        for x, y in path[1:]:
            writer.feed(x=x, y=y, f=feed_xy)
        self.tool_off(writer)
        writer.rapid(z=writer.safe_z)


class PenStrategy(ToolStrategy):
    def __init__(self, pen_z: float):
        self.pen_z = pen_z

    @property
    def name(self) -> str:
        return 'pen'

    @property
    def fill_method(self) -> str:
        return 'hatch'

    def tool_on(self, writer: 'GCodeWriter') -> None:
        writer.rapid(z=self.pen_z)

    def tool_off(self, writer: 'GCodeWriter') -> None:
        writer.rapid(z=writer.safe_z)

    def execute_profile(self, writer: 'GCodeWriter', path: List[Tuple[float, float]], is_closed: bool, feed_xy: int, depth: float, step_down: float) -> None:
        writer.rapid(z=1.0)
        self.tool_on(writer)
        for x, y in path[1:]:
            writer.feed(x=x, y=y, f=feed_xy)
        self.tool_off(writer)
        writer.rapid(z=writer.safe_z)


class MillStrategy(ToolStrategy):
    def __init__(self, intensity: int):
        self.intensity = intensity

    @property
    def name(self) -> str:
        return 'mill'

    @property
    def fill_method(self) -> str:
        return 'concentric'

    def tool_on(self, writer: 'GCodeWriter') -> None:
        writer.add_line(f"M3 S{self.intensity}")

    def tool_off(self, writer: 'GCodeWriter') -> None:
        writer.add_line("M5")

    def execute_profile(self, writer: 'GCodeWriter', path: List[Tuple[float, float]], is_closed: bool, feed_xy: int, depth: float, step_down: float) -> None:
        writer.rapid(z=1.0)

        path_length = sum(np.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]) for i in range(1, len(path)))
        if path_length == 0:
            path_length = 0.0001

        current_z = 0.0
        while current_z > depth:
            target_z = current_z - step_down
            if target_z < depth:
                target_z = depth

            z_drop = current_z - target_z
            accumulated_dist = 0.0

            for i in range(1, len(path)):
                x, y = path[i]
                prev_x, prev_y = path[i - 1]

                segment_len = np.hypot(x - prev_x, y - prev_y)
                accumulated_dist += segment_len

                point_z = current_z - (z_drop * (accumulated_dist / path_length))
                writer.feed(x=x, y=y, z=point_z, f=feed_xy)

            current_z = target_z

            if current_z == depth and is_closed:
                writer.add_line("( Final flat pass to clean floor )")
                for x, y in path[1:]:
                    writer.feed(x=x, y=y, f=feed_xy)

        writer.rapid(z=writer.safe_z)
