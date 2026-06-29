import datetime


class GCodeWriter:

    def __init__(self, safe_z=5.0):
        self.lines = []
        self.safe_z = safe_z

    def add_line(self, line):
        self.lines.append(line)

    def rapid(self, x=None, y=None, z=None):
        """Generates a G0 rapid move."""
        coords = []
        if x is not None:
            coords.append(f"X{x:.3f}")
        if y is not None:
            coords.append(f"Y{y:.3f}")
        if z is not None:
            coords.append(f"Z{z:.3f}")
        self.add_line(f"G0 {' '.join(coords)}")

    def feed(self, x=None, y=None, z=None, f=None):
        """Generates a G1 linear feed move."""
        coords = []
        if x is not None:
            coords.append(f"X{x:.3f}")
        if y is not None:
            coords.append(f"Y{y:.3f}")
        if z is not None:
            coords.append(f"Z{z:.3f}")
        if f is not None:
            coords.append(f"F{f}")
        self.add_line(f"G1 {' '.join(coords)}")

    def arc(self, x, y, i, j, z=None, f=None, cw=True):
        """Generates a G2/G3 arc move."""
        command = "G2" if cw else "G3"
        parts = [command, f"X{x:.3f}", f"Y{y:.3f}", f"I{i:.3f}", f"J{j:.3f}"]
        if z is not None:
            parts.append(f"Z{z:.3f}")
        if f is not None:
            parts.append(f"F{f}")
        self.add_line(' '.join(parts))

    def build_preamble(self, operation_name="Helical_Holes"):
        """Inserts the initial setup, tool changes, and safe heights."""
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        self.lines.extend([
            "(Exported by gcoder)", f"(Output Time:{current_time})",
            "(Begin preamble)", "G17 G90", "G21", "(Begin operation: Fixture)",
            "(Path: Fixture)", "G54", "(Finish operation: Fixture)",
            "(Begin operation: TC: Endmill)", "(Path: TC: Endmill)",
            "(TC: Endmill)", "(Begin toolchange)", "( M6 T1 )", "M3 S10000",
            "(Finish operation: TC: Endmill)",
            f"(Begin operation: {operation_name})", f"(Path: {operation_name})",
            f"({operation_name})", f"G0 Z{self.safe_z:.3f}", "G0 X0.000 Y0.000",
            "G0 Z0.000", f"G0 Z{self.safe_z:.3f}"
        ])

    def build_postamble(self, operation_name="Helical_Holes"):
        """Closes out the operation and machine safely."""
        self.lines.extend([
            f"G0 Z{self.safe_z:.3f}", f"(Finish operation: {operation_name})",
            "(Begin postamble)", "M5", "G17 G90", "M2"
        ])

    def save(self, filename):
        """Writes the buffered lines to a file."""
        with open(filename, 'w') as f:
            f.write('\n'.join(self.lines))
