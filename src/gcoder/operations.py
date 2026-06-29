import numpy as np
from shapely.geometry import Polygon, LineString
from svgpathtools import Document

def cut_svg_profile(writer, svg_path_file, compensation, tool_dia, depth, step_down, feed_xy, feed_ramp):
    """
    Parses an SVG and generates profile paths.
    
    compensation: 'outside' | 'inside' | 'on'
    """
    # 1. Parse SVG paths and apply all parent <g> transforms
    doc = Document(svg_path_file)
    paths = doc.paths() # This returns the mathematically flattened paths
    
    # svgpathtools uses complex numbers (X + Yj). 
    # For a 100x100 viewBox, the center is X=50, Y=50.
    pivot_point = 50 + 50j 
    
    flipped_paths = []
    for path in paths:
        if len(path) > 0:
            # Translate to origin -> Scale Y by -1 -> Translate back
            flipped = path.translated(-pivot_point).scaled(1, -1).translated(pivot_point)
            flipped_paths.append(flipped)
    paths = flipped_paths
    # -------------------------------------
    
    # Calculate offset distance (Tool Radius)
    offset_distance = tool_dia / 2.0
    
    for path in paths:
        if len(path) == 0:
            continue
            
        # Convert SVG path segments into sequential XY coordinates
        points = []
        # Increase steps for smoother curve approximation
        steps = 50 
        for segment in path:
            for t in np.linspace(0, 1, steps, endpoint=False):
                p = segment.point(t)
                points.append((p.real, p.imag))
                
        # Close path if it looks closed
        if path.isclosed():
            p_end = path[-1].point(1)
            points.append((p_end.real, p_end.imag))
            
        if len(points) < 2:
            continue
            
        # 2. Convert to Shapely Geometry and Apply Tool Compensation
        is_closed = path.isclosed()
        
        if is_closed and compensation in ('outside', 'inside'):
            # Closed shapes form a polygon
            geom = Polygon(points)
            
            # Determine correct buffer sign based on shape logic
            # Positive offsets grow outward, negative shrinks inward
            if compensation == 'outside':
                offset_geom = geom.buffer(offset_distance, join_style=1) # 1 = Round join
            else:
                offset_geom = geom.buffer(-offset_distance, join_style=1)
        else:
            # Open paths or 'on' center-line cutting use standard LineString
            geom = LineString(points)
            if compensation == 'on':
                offset_geom = geom
            else:
                # Offsetting an open line creates a parallel line side block
                # Shapely parallel_offset can be used here if needed
                offset_geom = geom.parallel_offset(offset_distance, side='left' if compensation == 'outside' else 'right')

        # 3. Extract points from generated toolpath geometry
        toolpaths = []
        if offset_geom.is_empty:
            continue
            
        # Handle cases where buffering splits a geometry into multiple pieces (MultiPolygon)
        if hasattr(offset_geom, 'geoms'):
            geoms = offset_geom.geoms
        else:
            geoms = [offset_geom]
            
        for g in geoms:
            if isinstance(g, Polygon):
                toolpaths.append(list(g.exterior.coords))
            elif isinstance(g, LineString):
                toolpaths.append(list(g.coords))

        # 4. Generate the G-Code layer by layer
        for tpath in toolpaths:
            if not tpath:
                continue
                
            writer.add_line(f"\n(--- New Profile Cut: {compensation} ---)")
            
            # Rapid to start location above material
            start_x, start_y = tpath[0]
            writer.rapid(x=start_x, y=start_y)
            writer.rapid(z=1.0)
            
            current_z = 0.0
            while current_z > depth:
                current_z -= step_down
                if current_z < depth:
                    current_z = depth
                    
                # Plunge down to the current layer depth
                writer.feed(z=current_z, f=feed_ramp)
                
                # Interpolate linear toolpath around the offset profile
                for x, y in tpath[1:]:
                    writer.feed(x=x, y=y, f=feed_xy)
                    
                # If closed, re-verify tool returns to start point cleanly
                if is_closed:
                    writer.feed(x=start_x, y=start_y, f=feed_xy)
                    
            # Safe retract
            writer.rapid(z=writer.safe_z)

def cut_helical_hole(writer, cx, cy, tool_dia, hole_dia, depth, step_down, feed_xy, feed_ramp):
    """Calculates and writes a single helical hole to the writer buffer."""
    path_radius = (hole_dia - tool_dia) / 2.0
    start_x = cx + path_radius
    
    writer.add_line(f"\n(--- Hole at X:{cx:.1f} Y:{cy:.1f} ---)")
    
    # Rapid to hole center and drop to 1mm above material
    writer.rapid(x=cx, y=cy)
    writer.rapid(z=1.0)
    
    # Move outward to the start of the circle (Right side)
    writer.feed(x=start_x, y=cy, f=feed_xy)

    writer.feed(z=0.0, f=feed_ramp)
    
    current_z = 0.0
    
    # Helical plunge
    while current_z > depth:
        current_z -= step_down
        if current_z < depth:
            current_z = depth
            
        # I offset is negative because center is to the left
        writer.arc(x=start_x, y=cy, i=-path_radius, j=0.0, z=current_z, f=feed_ramp, cw=True)
        
    # Final flat circle at the bottom to clean the floor
    writer.arc(x=start_x, y=cy, i=-path_radius, j=0.0, f=feed_xy, cw=True)
    
    # Return to center and retract to safe height
    writer.feed(x=cx, y=cy, f=feed_xy)
    writer.rapid(z=writer.safe_z)
