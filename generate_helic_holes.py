import datetime

OUTPUT_FILE = 'helical_grid.nc'

# --- Machine & Tool Parameters ---
TOOL_DIAMETER = 6.0  # mm
HOLE_DIAMETER = 10.0  # mm
FINAL_DEPTH = -5.0  # mm (Total depth of the hole)
Z_STEP_PER_REV = 1.0  # mm (How far down to drop per spiral)
SAFE_Z = 5.0  # mm (Clearance above wood for traveling)

# --- Grid Parameters ---
SPACING = 40.0  # mm between centers
COLUMNS = 4
ROWS = 3

# --- Speeds ---
XY_FEED = 1200  # mm/min (Speed for flat moves)
RAMP_FEED = 800  # mm/min (Speed for the plunging spiral)

# Calculate the radius the center of the tool must travel
path_radius = (HOLE_DIAMETER - TOOL_DIAMETER) / 2.0

# 1. Initialization and Safe Zero Move
current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

gcode = [
    "(Exported by gcoder)",
    f"(Output Time:{current_time})",
    "(Begin preamble)",
    "G17 G90",
    "G21",
    "(Begin operation: Fixture)",
    "(Path: Fixture)",
    "G54",
    "(Finish operation: Fixture)",
    "(Begin operation: TC: Endmill)",
    "(Path: TC: Endmill)",
    "(TC: Endmill)",
    "(Begin toolchange)",
    "( M6 T1 )",
    "M3 S10000",
    "(Finish operation: TC: Endmill)",
    "(Begin operation: Helical_Holes)",
    "(Path: Helical_Holes)",
    "(Helical_Holes)",
    f"G0 Z{SAFE_Z:.3f}",
    "G0 X0.000 Y0.000",
    "G0 Z0.000",
    f"G0 Z{SAFE_Z:.3f}",
    ""
]

# 2. Generate the Toolpath
for row in range(ROWS):
    for col in range(COLUMNS):
        cx = col * SPACING
        cy = row * SPACING

        gcode.append(f"(--- Hole at X:{cx} Y:{cy} ---)")

        # Rapid to hole center
        gcode.append(f"G0 X{cx:.3f} Y{cy:.3f}")
        # Drop rapidly to just above the material to save time
        gcode.append(f"G0 Z1.000")

        # Move outward to the start of the circle (Right side)
        start_x = cx + path_radius
        gcode.append(f"G1 X{start_x:.3f} Y{cy:.3f} F{XY_FEED}")

        # Calculate how many 1mm spirals we need
        current_z = 0.0

        # Loop the helical drops
        while current_z > FINAL_DEPTH:
            current_z -= Z_STEP_PER_REV
            # Prevent overshooting the bottom
            if current_z < FINAL_DEPTH:
                current_z = FINAL_DEPTH

            # The I offset is negative because the center is to our left
            gcode.append(
                f"G2 X{start_x:.3f} Y{cy:.3f} I{-path_radius:.3f} J0.000 Z{current_z:.3f} F{RAMP_FEED}"
            )

        # Do one final flat circle at the bottom to clean the floor
        gcode.append(
            f"G2 X{start_x:.3f} Y{cy:.3f} I{-path_radius:.3f} J0.000 F{XY_FEED}"
        )

        # Return to center and retract to safe height
        gcode.append(f"G1 X{cx:.3f} Y{cy:.3f} F{XY_FEED}")
        gcode.append(f"G0 Z{SAFE_Z:.3f}\n")

# Close out the operation block cleanly
gcode.append(f"G0 Z{SAFE_Z:.3f}")
gcode.append("(Finish operation: Helical_Holes)")

# 3. Postamble
gcode.append("(Begin postamble)")
gcode.append("M5")
gcode.append("G17 G90")
gcode.append("M2")

# Save file
with open(OUTPUT_FILE, 'w') as f:
    f.write('\n'.join(gcode))

print(f"Generated {COLUMNS * ROWS} helical holes.")
print(f"Saved to {OUTPUT_FILE}")
