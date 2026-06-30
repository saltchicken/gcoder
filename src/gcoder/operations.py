import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, MultiLineString
from svgpathtools import Document, Path
from typing import List, Tuple, Optional
from .core import GCodeWriter

# Shapely Buffer Join Styles
# 1 = Round, 2 = Mitre, 3 = Bevel
JOIN_STYLE_ROUND: int = 1


class SVGProfileCutter:
    """Encapsulates the state and logic for generating continuous ramping toolpaths from SVGs."""

    def __init__(self,
                 writer: GCodeWriter,
                 svg_path_file: str,
                 compensation: str,
                 tool_dia: float,
                 depth: float,
                 step_down: float,
                 feed_xy: int,
                 feed_ramp: Optional[int] = None) -> None:
        
        self.writer: GCodeWriter = writer
        self.svg_path_file: str = svg_path_file
        self.compensation: str = compensation
        self.tool_dia: float = tool_dia
        self.offset_distance: float = tool_dia / 2.0
        self.depth: float = depth
        self.step_down: float = step_down
        self.feed_xy: int = feed_xy
        self.feed_ramp: Optional[int] = feed_ramp

        # State variables calculated during execution
        self.center_x: float = 0.0
        self.center_y: float = 0.0

    def execute(self) -> None:
        """Parses the SVG and generates the toolpaths."""
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

            # Handle cases where buffering splits geometry (MultiPolygon / MultiLineString)
            geoms = offset_geom.geoms if hasattr(offset_geom, 'geoms') else [offset_geom]

            for g in geoms:
                if isinstance(g, Polygon):
                    tpath = list(g.exterior.coords)
                elif isinstance(g, LineString):
                    tpath = list(g.coords)
                else:
                    continue

                self._write_ramped_profile(tpath, is_closed)

    def _calculate_svg_center(self, doc: Document) -> None:
        """Extracts viewBox or dimensions to dynamically compute the middle pivot."""
        root = doc.tree.getroot()
        viewbox_str = root.get('viewBox')

        if viewbox_str:
            vb_parts = viewbox_str.replace(',', ' ').split()
            self.center_x = float(vb_parts[0]) + (float(vb_parts[2]) / 2.0)
            self.center_y = float(vb_parts[1]) + (float(vb_parts[3]) / 2.0)
        else:
            w_str = root.get('width', '100').replace('mm', '').replace('px', '').replace('%', '')
            h_str = root.get('height', '100').replace('mm', '').replace('px', '').replace('%', '')
            self.center_x = float(w_str) / 2.0
            self.center_y = float(h_str) / 2.0

    def _extract_and_flip_points(self, path: Path, steps: int = 50) -> List[Tuple[float, float]]:
        """Interpolates SVG segments into dense coordinates and flips the Y-axis."""
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

        return points

    def _apply_tool_compensation(self, points: List[Tuple[float, float]], is_closed: bool) -> BaseGeometry:
        """Calculates tool compensation geometry using Shapely buffers."""
        if is_closed and self.compensation in ('outside', 'inside'):
            geom = Polygon(points)
            if self.compensation == 'outside':
                return geom.buffer(self.offset_distance, join_style=JOIN_STYLE_ROUND)
            else:
                return geom.buffer(-self.offset_distance, join_style=JOIN_STYLE_ROUND)

        geom = LineString(points)
        if self.compensation == 'on':
            return geom
        else:
            side = 'left' if self.compensation == 'outside' else 'right'
            return geom.parallel_offset(self.offset_distance, side=side)

    def _write_ramped_profile(self, tpath: List[Tuple[float, float]], is_closed: bool) -> None:
        if not tpath:
            return

        self.writer.add_line(f"\n(--- New Profile Cut: {self.compensation} ---)")

        start_x, start_y = tpath[0]
        self.writer.rapid(x=start_x, y=start_y)

        # ---------------------------------------------------------
        # LASER / PEN MODE (Single Pass, No Ramping)
        # ---------------------------------------------------------
        if self.writer.mode in ('laser', 'pen'):
            # Rapid to focus height (or pen hover height)
            self.writer.rapid(z=1.0) 
            
            # Turn tool on (Laser ON or Pen DOWN)
            self.writer.tool_on() # NO ARGUMENTS NEEDED HERE
            
            # Trace the 2D path
            for x, y in tpath[1:]:
                self.writer.feed(x=x, y=y, f=self.feed_xy)
                
            # Turn tool off (Laser OFF or Pen UP)
            self.writer.tool_off()
            self.writer.rapid(z=self.writer.safe_z)
            return

        # ---------------------------------------------------------
        # MILLING MODE (Keep your existing ramping logic below)
        # ---------------------------------------------------------
        self.writer.rapid(z=1.0)

        path_length = sum(np.hypot(tpath[i][0] - tpath[i - 1][0], tpath[i][1] - tpath[i - 1][1]) for i in range(1, len(tpath)))
        if path_length == 0:
            path_length = 0.0001

        current_z = 0.0
        while current_z > self.depth:
            target_z = current_z - self.step_down
            if target_z < self.depth:
                target_z = self.depth

            z_drop = current_z - target_z
            accumulated_dist = 0.0

            for i in range(1, len(tpath)):
                x, y = tpath[i]
                prev_x, prev_y = tpath[i - 1]

                segment_len = np.hypot(x - prev_x, y - prev_y)
                accumulated_dist += segment_len

                point_z = current_z - (z_drop * (accumulated_dist / path_length))
                self.writer.feed(x=x, y=y, z=point_z, f=self.feed_xy)

            current_z = target_z

            if current_z == self.depth and is_closed:
                self.writer.add_line("( Final flat pass to clean floor )")
                for x, y in tpath[1:]:
                    self.writer.feed(x=x, y=y, f=self.feed_xy)

        self.writer.rapid(z=self.writer.safe_z)


class SVGFillCutter(SVGProfileCutter):
    """Generates interior fill toolpaths (Hatching for Lasers/Pens, Concentric for Mills)."""

    def __init__(self, stepover_percent: float = 0.5, fill_angle: float = 0.0, **kwargs):
        super().__init__(**kwargs)
        # Stepover is how much the tool shifts over per pass (e.g., 50% of the tool diameter)
        self.stepover = self.tool_dia * stepover_percent
        self.fill_angle = fill_angle

    def execute(self) -> None:
        doc = Document(self.svg_path_file)
        self._calculate_svg_center(doc)

        for path in doc.paths():
            if len(path) == 0 or not path.isclosed():
                continue # Only fill closed shapes

            points = self._extract_and_flip_points(path)
            base_polygon = Polygon(points)
            
            # 1. Apply initial tool compensation so we don't cut outside the line
            # For a fill, we ALWAYS want inside compensation
            working_polygon = base_polygon.buffer(-self.offset_distance, join_style=JOIN_STYLE_ROUND)

            if working_polygon.is_empty:
                continue

            # Handle MultiPolygons if the inward buffer split the shape
            geoms = working_polygon.geoms if hasattr(working_polygon, 'geoms') else [working_polygon]

            for geom in geoms:
                if not isinstance(geom, Polygon):
                    continue

                if self.writer.mode in ('laser', 'pen'):
                    self._execute_linear_hatch(geom)
                else:
                    self._execute_concentric_pocket(geom)

    def _execute_linear_hatch(self, polygon: Polygon) -> None:
        """Generates a zig-zag raster fill for lasers and pens."""
        self.writer.add_line(f"\n(--- New Hatch Fill ---)")
        
        # Rotate polygon to horizontal to make grid generation easy
        rotated_poly = rotate(polygon, -self.fill_angle, origin='centroid')
        minx, miny, maxx, maxy = rotated_poly.bounds

        # Generate horizontal lines
        y_coords = np.arange(miny + self.stepover/2, maxy, self.stepover)
        lines = [LineString([(minx - 1, y), (maxx + 1, y)]) for y in y_coords]

        fill_lines = []
        for i, line in enumerate(lines):
            intersection = rotated_poly.intersection(line)
            if intersection.is_empty:
                continue

            segments = []
            if isinstance(intersection, LineString):
                segments.append(intersection)
            elif hasattr(intersection, 'geoms'):
                segments.extend([g for g in intersection.geoms if isinstance(g, LineString)])

            # Reverse the coordinates on alternating lines to create a zig-zag (minimizes rapid travels)
            if i % 2 == 1:
                segments = [LineString(list(seg.coords)[::-1]) for seg in segments[::-1]]

            fill_lines.extend(segments)

        # Rotate the lines back to the target angle
        final_lines = [rotate(line, self.fill_angle, origin=polygon.centroid) for line in fill_lines]

        # Write G-code for each line
        for line in final_lines:
            coords = list(line.coords)
            self.writer.rapid(x=coords[0][0], y=coords[0][1])
            self.writer.rapid(z=1.0)
            
            self.writer.tool_on()
            for x, y in coords[1:]:
                self.writer.feed(x=x, y=y, f=self.feed_xy)
            self.writer.tool_off()
            
        self.writer.rapid(z=self.writer.safe_z)

    def _execute_concentric_pocket(self, polygon: Polygon) -> None:
        """Generates inward offsetting rings for milling pockets."""
        self.writer.add_line(f"\n(--- New Concentric Pocket ---)")
        
        rings = []
        current_poly = polygon

        # Keep shrinking the polygon until it disappears
        while not current_poly.is_empty:
            if isinstance(current_poly, Polygon):
                rings.append(current_poly)
            elif hasattr(current_poly, 'geoms'):
                for geom in current_poly.geoms:
                    if isinstance(geom, Polygon):
                        rings.append(geom)

            current_poly = current_poly.buffer(-self.stepover, join_style=JOIN_STYLE_ROUND)

        # Cut rings from the inside out to allow chip clearing
        for ring in reversed(rings):
            tpath = list(ring.exterior.coords)
            self._write_ramped_profile(tpath, is_closed=True)

def cut_helical_hole(writer: GCodeWriter, cx: float, cy: float, tool_dia: float, hole_dia: float, depth: float, step_down: float, feed_xy: int, feed_ramp: int) -> None:
    """Calculates and writes a single helical hole to the writer buffer."""
    path_radius = (hole_dia - tool_dia) / 2.0
    start_x = cx + path_radius

    writer.add_line(f"\n(--- Hole at X:{cx:.1f} Y:{cy:.1f} ---)")

    writer.rapid(x=cx, y=cy)
    writer.rapid(z=1.0)

    writer.feed(x=start_x, y=cy, f=feed_xy)
    writer.feed(z=0.0, f=feed_ramp)

    current_z = 0.0
    while current_z > depth:
        current_z -= step_down
        if current_z < depth:
            current_z = depth

        writer.arc(x=start_x, y=cy, i=-path_radius, j=0.0, z=current_z, f=feed_ramp, cw=True)

    writer.arc(x=start_x, y=cy, i=-path_radius, j=0.0, f=feed_xy, cw=True)

    writer.feed(x=cx, y=cy, f=feed_xy)
    writer.rapid(z=writer.safe_z)
