"""
Defines geometrical operations to map SVG paths into compensated CNC trajectories.
"""
from typing import List, Optional, Sequence, Tuple

import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from svgpathtools import Document
from svgpathtools import Path

from .core import GCodeWriter
from .core import JobConfig

JOIN_STYLE_ROUND = 'round'


class SVGOperation:
    """
    Abstract base class for all SVG-to-GCode operations.
    Handles document parsing, center calculation, coordinate mapping,
    and tool compensation geometry.
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(self, writer: GCodeWriter, svg_path_file: str,
                 config: JobConfig) -> None:
        self.writer: GCodeWriter = writer
        self.svg_path_file: str = svg_path_file

        self.compensation: str = config.compensation
        self.tool_dia: float = config.tool_dia
        self.offset_distance: float = config.tool_dia / 2.0
        self.depth: float = config.depth
        self.step_down: float = config.step_down
        self.feed_xy: int = config.feed_xy
        self.feed_ramp: Optional[int] = config.feed_ramp

        self.center_x: float = 0.0
        self.center_y: float = 0.0

    def execute(self) -> None:
        """Abstract execution method to be overridden by subclasses."""
        raise NotImplementedError(
            "Subclasses must implement the execute method.")

    def _calculate_svg_center(self, doc: Document) -> None:
        """Determines the center of the SVG document from viewBox or dimensions."""
        if doc.tree is None:
            return

        root = doc.tree.getroot()
        if root is None:
            return

        viewbox_str = root.get('viewBox')

        if viewbox_str is not None:
            vb_parts = viewbox_str.replace(',', ' ').split()
            self.center_x = float(vb_parts[0]) + (float(vb_parts[2]) / 2.0)
            self.center_y = float(vb_parts[1]) + (float(vb_parts[3]) / 2.0)
        else:
            w_val = root.get('width', '100')
            h_val = root.get('height', '100')
            w_str = str(w_val).replace('mm', '').replace('px',
                                                         '').replace('%', '')
            h_str = str(h_val).replace('mm', '').replace('px',
                                                         '').replace('%', '')
            self.center_x = float(w_str) / 2.0
            self.center_y = float(h_str) / 2.0

    def _extract_and_flip_points(self,
                                 path: Path,
                                 steps: int = 50) -> List[Tuple[float, float]]:
        """Extracts points from an SVG path and flips the Y axis to match CNC coordinates."""
        points: List[Tuple[float, float]] = []
        for segment in path:
            for t in np.linspace(0, 1, steps, endpoint=False):
                p = segment.point(t)
                flipped_y = (2.0 * self.center_y) - p.imag
                points.append((p.real, flipped_y))

        if path.isclosed():
            p_end = path[-1].point(1)
            flipped_y_end = (2.0 * self.center_y) - p_end.imag
            points.append((p_end.real, flipped_y_end))

        # TODO: Investigate how this worked to prevent straight lines from being split into segments.
        # To remove this just return points from here
        geom = LineString(points)
        simplified_geom = geom.simplify(0.01, preserve_topology=True)
        return list(simplified_geom.coords)

    def _apply_tool_compensation(self, points: List[Tuple[float, float]],
                                 is_closed: bool) -> BaseGeometry:
        """Applies tool radius compensation based on configuration style."""
        if is_closed and self.compensation in ('outside', 'inside'):
            geom = Polygon(points)
            if self.compensation == 'outside':
                return geom.buffer(self.offset_distance,
                                   join_style=JOIN_STYLE_ROUND)
            return geom.buffer(-self.offset_distance,
                               join_style=JOIN_STYLE_ROUND)

        geom = LineString(points)
        if self.compensation == 'on':
            return geom

        side = 'left' if self.compensation == 'outside' else 'right'
        return geom.parallel_offset(self.offset_distance, side=side)

    def _write_profile(self, tpath: Sequence[Tuple[float, float]],
                              is_closed: bool) -> None:
        """Moves machine to the start coordinate and hands execution to the ToolStrategy."""
        if not tpath:
            return

        self.writer.add_line(
            f"\n(--- New Profile Cut: {self.compensation} ---)")
        start_x, start_y = tpath[0]
        self.writer.rapid(z=self.writer.clearance_z)
        self.writer.rapid(x=start_x, y=start_y)

        self.writer.tool.execute_profile(writer=self.writer,
                                         path=tpath,
                                         is_closed=is_closed,
                                         feed_xy=self.feed_xy,
                                         depth=self.depth,
                                         step_down=self.step_down)


class SVGProfileCutter(SVGOperation):
    """Generates continuous geometric toolpaths tracing the contours of the SVG paths."""

    def execute(self) -> None:
        doc = Document(self.svg_path_file)
        paths: List[Path] = doc.paths()
        self._calculate_svg_center(doc)

        for path in paths:
            if len(path) == 0:
                continue

            points = self._extract_and_flip_points(path)
            if len(points) < 2:
                continue

            is_closed = path.isclosed()
            offset_geom = self._apply_tool_compensation(points, is_closed)

            if offset_geom.is_empty:
                continue

            geoms = getattr(offset_geom, 'geoms', [offset_geom])

            for g in geoms:
                if isinstance(g, Polygon):
                    tpath = [(float(x), float(y)) for x, y in g.exterior.coords]
                elif isinstance(g, LineString):
                    tpath = [(float(x), float(y)) for x, y in g.coords]
                else:
                    continue

                self._write_profile(tpath, is_closed)


class SVGFillCutter(SVGOperation):
    """Generates geometric interior fill strategies determined by the assigned ToolStrategy."""

    def __init__(self,
                 stepover_percent: float = 0.5,
                 fill_angle: float = 0.0,
                 fill_method: str = 'auto',
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.stepover: float = self.tool_dia * stepover_percent
        self.fill_angle: float = fill_angle
        # Use tool's default if not overridden by CLI
        self.fill_method: str = fill_method if fill_method != 'auto' else self.writer.tool.fill_method

    def execute(self) -> None:
        doc = Document(self.svg_path_file)
        self._calculate_svg_center(doc)

        for path in doc.paths():
            if len(path) == 0 or not path.isclosed():
                continue

            points = self._extract_and_flip_points(path)
            base_polygon = Polygon(points)
            working_polygon = base_polygon.buffer(-self.offset_distance,
                                                  join_style=JOIN_STYLE_ROUND)

            if working_polygon.is_empty:
                continue

            geoms = getattr(working_polygon, 'geoms', [working_polygon])

            for geom in geoms:
                if not isinstance(geom, Polygon):
                    continue

                if self.fill_method == 'hatch':
                    self._execute_linear_hatch(geom)
                elif self.fill_method == 'crosshatch':
                    self._execute_cross_hatch(geom)
                elif self.fill_method == 'spiral':
                    self._execute_spiral(geom)
                else:
                    self._execute_concentric_pocket(geom)

    # pylint: disable=too-many-locals
    def _execute_linear_hatch(self, polygon: Polygon) -> None:
        """Hatching line-fill generator for raster tools (Lasers/Pens)."""
        self.writer.add_line("\n(--- New Hatch Fill ---)")

        rotated_poly = rotate(polygon, -self.fill_angle, origin='centroid')
        minx, miny, maxx, maxy = rotated_poly.bounds

        y_coords = np.arange(miny + self.stepover / 2, maxy, self.stepover)
        lines = [LineString([(minx - 1, y), (maxx + 1, y)]) for y in y_coords]

        fill_lines = []
        for i, line in enumerate(lines):
            intersection = rotated_poly.intersection(line)
            if intersection.is_empty:
                continue

            segments = []
            if isinstance(intersection, LineString):
                segments.append(intersection)
            else:
                inter_parts = getattr(intersection, 'geoms', [])
                segments.extend(
                    [g for g in inter_parts if isinstance(g, LineString)])

            if i % 2 == 1:
                segments = [
                    LineString(list(seg.coords)[::-1]) for seg in segments[::-1]
                ]

            fill_lines.extend(segments)

        final_lines = [
            rotate(line, self.fill_angle, origin=polygon.centroid)
            for line in fill_lines
        ]

        for line in final_lines:
            coords = list(line.coords)
            self.writer.rapid(x=coords[0][0], y=coords[0][1])
            self.writer.rapid(z=self.writer.rapid_z)
            self.writer.tool_on()
            for x, y in coords[1:]:
                self.writer.feed(x=x, y=y, f=self.feed_xy)
            self.writer.tool_off()

        self.writer.rapid(z=self.writer.rapid_z)

    def _execute_cross_hatch(self, polygon: Polygon) -> None:
        """Generates a cross-hatch pattern by running linear hatch twice perpendicularly."""
        self.writer.add_line("\n(--- Cross Hatch Pass 1 ---)")
        self._execute_linear_hatch(polygon)
        
        self.writer.add_line("\n(--- Cross Hatch Pass 2 ---)")
        original_angle = self.fill_angle
        # Temporarily shift the angle by 90 degrees for the perpendicular pass
        self.fill_angle += 90.0
        self._execute_linear_hatch(polygon)
        
        # Restore the original angle
        self.fill_angle = original_angle

    def _execute_concentric_pocket(self, polygon: Polygon) -> None:
        """Concentric pocket loop generator for material removal tools (Mills)."""
        self.writer.add_line("\n(--- New Concentric Pocket ---)")

        rings = []
        current_poly = polygon

        while not current_poly.is_empty:
            if isinstance(current_poly, Polygon):
                rings.append(current_poly)
            else:
                parts = getattr(current_poly, 'geoms', [])
                for geom in parts:
                    if isinstance(geom, Polygon):
                        rings.append(geom)

            current_poly = current_poly.buffer(-self.stepover,
                                               join_style=JOIN_STYLE_ROUND)

        for ring in reversed(rings):
            tpath = [(float(x), float(y)) for x, y in ring.exterior.coords]
            self._write_profile(tpath, is_closed=True)

    def _execute_spiral(self, polygon: Polygon) -> None:
        """Generates an Archimedean spiral fill pattern from the polygon's centroid."""
        self.writer.add_line("\n(--- New Spiral Fill ---)")

        cx, cy = polygon.centroid.x, polygon.centroid.y
        minx, miny, maxx, maxy = polygon.bounds
        
        # Calculate maximum radius needed to clear the bounding box corners
        max_r = np.max([
            np.hypot(minx - cx, miny - cy),
            np.hypot(maxx - cx, miny - cy),
            np.hypot(minx - cx, maxy - cy),
            np.hypot(maxx - cx, maxy - cy)
        ])

        if max_r == 0 or self.stepover <= 0:
            return

        # Archimedean spiral: r = b * theta
        # Radial distance between turns is 2 * pi * b
        b = self.stepover / (2.0 * np.pi)
        max_theta = max_r / b

        # Target a maximum physical length for each straight line segment (e.g., 0.25mm)
        # This guarantees the outer rings stay just as smooth as the inner rings.
        # TODO: Modify this from the command line
        max_segment_length = 0.25
        
        # Calculate the angular step required at the maximum radius to hit our target length
        theta_step = max_segment_length / max_r if max_r > 0 else 0.1
        
        num_points = max(int(max_theta / theta_step), 10)
        theta = np.linspace(0, max_theta, num_points)
        r = b * theta

        x_coords = cx + r * np.cos(theta)
        y_coords = cy + r * np.sin(theta)

        points = np.column_stack((x_coords, y_coords))
        spiral_line = LineString(points)

        # Clip spiral to the interior polygon bounds
        intersection = polygon.intersection(spiral_line)

        if intersection.is_empty:
            return

        segments = []
        if isinstance(intersection, LineString):
            segments.append(intersection)
        else:
            inter_parts = getattr(intersection, 'geoms', [])
            segments.extend([g for g in inter_parts if isinstance(g, LineString)])

        for line in segments:
            coords = [(float(x), float(y)) for x, y in line.coords]
            if not coords:
                continue
            self._write_profile(coords, is_closed=False)
