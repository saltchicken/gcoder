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
