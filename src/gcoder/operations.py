import numpy as np
from shapely.geometry import Polygon, LineString
from svgpathtools import Document

def cut_svg_profile(writer, svg_path_file, compensation, tool_dia, depth, step_down, feed_xy, feed_ramp):
    """Parses an SVG and generates profile paths using continuous ramping."""
    doc = Document(svg_path_file)
    paths = doc.paths() 
    
    center_x, center_y = _get_svg_center(doc)
    offset_distance = tool_dia / 2.0
    
    for path in paths:
        if len(path) == 0:
            continue
            
        points = _extract_and_flip_points(path, center_y)
        if len(points) < 2:
            continue
            
        is_closed = path.isclosed()
        offset_geom = _apply_tool_compensation(points, is_closed, compensation, offset_distance)
        
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
                
            _write_ramped_profile(writer, tpath, is_closed, compensation, depth, step_down, feed_xy)


def _get_svg_center(doc):
    """Extracts viewBox or dimensions to dynamically compute the middle pivot."""
    root = doc.tree.getroot()
    viewbox_str = root.get('viewBox')
    
    if viewbox_str:
        vb_parts = viewbox_str.replace(',', ' ').split()
        center_x = float(vb_parts[0]) + (float(vb_parts[2]) / 2.0)
        center_y = float(vb_parts[1]) + (float(vb_parts[3]) / 2.0)
    else:
        w_str = root.get('width', '100').replace('mm', '').replace('px', '').replace('%', '')
        h_str = root.get('height', '100').replace('mm', '').replace('px', '').replace('%', '')
        center_x = float(w_str) / 2.0
        center_y = float(h_str) / 2.0
        
    return center_x, center_y


def _extract_and_flip_points(path, center_y, steps=50):
    """Interpolates SVG segments into dense coordinates and flips the Y-axis."""
    points = []
    for segment in path:
        for t in np.linspace(0, 1, steps, endpoint=False):
            p = segment.point(t)
            flipped_y = (2.0 * center_y) - p.imag
            points.append((p.real, flipped_y))
            
    if path.isclosed():
        p_end = path[-1].point(1)
        flipped_y_end = (2.0 * center_y) - p_end.imag
        points.append((p_end.real, flipped_y_end))
        
    return points


def _apply_tool_compensation(points, is_closed, compensation, offset_distance):
    """Calculates tool compensation geometry using Shapely buffers."""
    if is_closed and compensation in ('outside', 'inside'):
        geom = Polygon(points)
        if compensation == 'outside':
            return geom.buffer(offset_distance, join_style=1)  # 1 = Round join
        else:
            return geom.buffer(-offset_distance, join_style=1)
            
    geom = LineString(points)
    if compensation == 'on':
        return geom
    else:
        side = 'left' if compensation == 'outside' else 'right'
        return geom.parallel_offset(offset_distance, side=side)


def _write_ramped_profile(writer, tpath, is_closed, compensation, depth, step_down, feed_xy):
    """Generates continuous 3D ramping G-code for a structured point path."""
    if not tpath:
        return
        
    writer.add_line(f"\n(--- New Profile Cut: {compensation} ---)")
    
    # Rapid to start location above material
    start_x, start_y = tpath[0]
    writer.rapid(x=start_x, y=start_y)
    writer.rapid(z=1.0)
    
    # Calculate the total linear length of this toolpath layer
    path_length = sum(np.hypot(tpath[i][0] - tpath[i-1][0], tpath[i][1] - tpath[i-1][1]) for i in range(1, len(tpath)))
    if path_length == 0:
        path_length = 0.0001 
        
    current_z = 0.0
    while current_z > depth:
        target_z = current_z - step_down
        if target_z < depth:
            target_z = depth
            
        z_drop = current_z - target_z
        accumulated_dist = 0.0
        
        # Ramp down continuously along the profile instead of standard plunging
        for i in range(1, len(tpath)):
            x, y = tpath[i]
            prev_x, prev_y = tpath[i-1]
            
            segment_len = np.hypot(x - prev_x, y - prev_y)
            accumulated_dist += segment_len
            
            # Interpolate Z based on distance traveled relative to full cycle length
            point_z = current_z - (z_drop * (accumulated_dist / path_length))
            writer.feed(x=x, y=y, z=point_z, f=feed_xy)
            
        current_z = target_z
        
        # Perform flat cleanup pass at the absolute bottom floor if part is closed
        if current_z == depth and is_closed:
            writer.add_line("( Final flat pass to clean floor )")
            for x, y in tpath[1:]:
                writer.feed(x=x, y=y, f=feed_xy)
                
    writer.rapid(z=writer.safe_z)


def cut_helical_hole(writer, cx, cy, tool_dia, hole_dia, depth, step_down, feed_xy, feed_ramp):
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
