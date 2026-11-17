"""Layout tests for callout placement.  Run with: uv run python -m unittest discover tests"""
import unittest

from kicad_callouts import BOX_H, COL_W, GAP, MARGIN, TITLE_H, crosses, place

# A 148 x 60 mm board with its outline from (74, 75) to (222, 135) mm: one footprint
# near the top edge and a row of connectors along the bottom, in file order.
OX, OY, BW = 74, 75, 148
FOOTPRINTS = [("J4", 111.5, 78), ("J7", 147.5, 127.055), ("J8", 164, 127.055), ("J11", 208.2, 125.705),
              ("J9", 180.5, 127.055), ("J10", 195.2, 125.705), ("J6", 131, 127.055), ("J5", 114.5, 127.055),
              ("J2", 77.695, 94), ("J1", 87, 123.795), ("J3", 99, 127.055)]
BOARD_X, BOARD_Y = MARGIN + COL_W + GAP, MARGIN + TITLE_H


def layout(footprints, ox=OX, oy=OY, bw=BW):
    """Place footprints the way main() does and return (left, right, crossings)."""
    items = [dict(ref=ref, x=x - ox, y=y - oy) for ref, x, y in footprints]
    left = [i for i in items if i["x"] < bw / 2]
    right = [i for i in items if i["x"] >= bw / 2]
    crossings = []
    for col, x0, ax in ((left, MARGIN, MARGIN + COL_W), (right, BOARD_X + bw + GAP, BOARD_X + bw + GAP)):
        place(col, x0, ax, BOARD_X, BOARD_Y)
        leaders = [((ax, i["box"][1] + BOX_H / 2), (BOARD_X + i["x"], BOARD_Y + i["y"])) for i in col]
        crossings += [(a["ref"], b["ref"]) for n, a in enumerate(col) for m, b in enumerate(col)
                      if n < m and crosses(*leaders[n], *leaders[m])]
    return left, right, crossings


class LayoutTest(unittest.TestCase):
    def test_row_of_connectors(self):
        left, right, crossings = layout(FOOTPRINTS)
        self.assertEqual([i["ref"] for i in left], ["J4", "J2", "J1", "J3", "J5", "J6", "J7"])
        self.assertEqual([i["ref"] for i in right], ["J11", "J10", "J9", "J8"])
        self.assertEqual(crossings, [])

    def test_boxes_clear_title_and_each_other(self):
        left, right, _ = layout(FOOTPRINTS)
        for col in (left, right):
            ys = [i["box"][1] for i in col]
            self.assertGreaterEqual(ys[0], MARGIN + TITLE_H)
            for a, b in zip(ys, ys[1:]):
                self.assertGreaterEqual(b, a + BOX_H)
        self.assertEqual(left[0]["box"][1], MARGIN + TITLE_H)  # J4 is 3 mm from the top edge

    def test_near_ties_do_not_cross(self):
        # B is 1 mm lower than A but much nearer the column; C pushes both boxes down.
        left, _, crossings = layout([("C", 5, 48), ("A", 40, 50), ("B", 10, 51)], ox=0, oy=0)
        self.assertEqual([i["ref"] for i in left], ["C", "B", "A"])
        self.assertEqual(crossings, [])


if __name__ == "__main__":
    unittest.main()
