"""The study area and the project grid (requirements D1, FD1, section 5).

The area was chosen in F0 by a scoring rule (``docs/flood/reports/F0-derisk.md``, section 4) and
decided by Yuri on 2026-11-25. Everything that needs the grid takes it from here.

Two extents are kept apart:

* the **square**: 4 km by 4 km in UTM zone 18N. The depth model runs on it, because water does not
  stop at a neighbourhood's edge and the East River is the model's open boundary;
* the **study area**: the Brooklyn land inside the square. Assets, losses and indices are reported
  for it only. The square also holds part of the East River and of Manhattan, which are modelled
  and not studied.
"""

from __future__ import annotations

from dataclasses import dataclass

CRS = "EPSG:32618"
#: west, south, east, north of the square, metres, UTM zone 18N
SQUARE = (585_500.0, 4_504_500.0, 589_500.0, 4_508_500.0)
CENTRE_LONLAT = (-73.9642, 40.7048)
#: project cell, metres [P]: may change after the first real solver run (requirements section 5)
CELL_M = 5.0
#: terrain is fetched this far beyond the square, so that slopes at its edge are real
TERRAIN_MARGIN_M = 500.0
#: the borough whose land in the square is the study area
BOROUGH = "Brooklyn"
#: a cell is wet at this depth, metres [P] (requirements section 5)
WET_M = 0.05
#: local days are counted in this zone (requirements section 5)
TIMEZONE = "America/New_York"


@dataclass(frozen=True)
class Grid:
    """The project grid: square cells, row 0 at the north as rasters are stored."""

    west: float
    south: float
    east: float
    north: float
    cell: float

    @property
    def width(self) -> int:
        return int(round((self.east - self.west) / self.cell))

    @property
    def height(self) -> int:
        return int(round((self.north - self.south) / self.cell))

    @property
    def transform(self) -> tuple[float, float, float, float, float, float]:
        """Affine coefficients (a, b, c, d, e, f) as rasterio's ``Affine`` takes them."""
        return (self.cell, 0.0, self.west, 0.0, -self.cell, self.north)

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """(row, column) of the cell holding a point; a point on a shared edge goes north-east."""
        col = int((x - self.west) // self.cell)
        row = int((self.north - y) // self.cell)
        if (self.north - y) % self.cell == 0 and y < self.north:
            row -= 1
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise ValueError(f"point ({x}, {y}) is outside the grid")
        return row, col


GRID = Grid(*SQUARE, CELL_M)
