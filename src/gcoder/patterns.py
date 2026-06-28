def generate_grid(rows, cols, spacing):
    """Yields (x, y) coordinates for a standard grid."""
    for row in range(rows):
        for col in range(cols):
            yield (col * spacing, row * spacing)
