#!/usr/bin/env python3
"""Render an annotated 3D top view of a KiCad PCB with a callout for each connector.

    kicad-callouts board.kicad_pcb -o docs/connectors.png

Every footprint with a non-empty "Callout" property gets a callout; the optional
"Callout Description" property supplies the longer text under the label.

Requires: KiCad 9+ (for `kicad-cli pcb render`), Pillow, and rsvg-convert for
PNG/PDF output (`brew install librsvg` / `apt install librsvg2-bin`).
`kicad-cli` is found from the KICAD_CLI environment variable, PATH, or the
default install locations on macOS and Windows.
"""
import argparse, base64, glob, html, math, os, re, shutil, subprocess, sys, tempfile, textwrap
import xml.etree.ElementTree as ET
from PIL import Image

RENDER_W = 2400     # px; the 3D render is downsampled into the final image

# Layout constants, all in mm (the SVG user unit).
COL_W = 62.0        # width of each callout column
GAP = 12.0          # space between callout column and board (holds the height dimension)
MARGIN = 6.0
BOX_H = 13.0
TITLE_H = 12.0


def find_kicad_cli():
    candidates = [os.environ.get("KICAD_CLI"), shutil.which("kicad-cli"),
                  "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
                  *sorted(glob.glob(r"C:\Program Files\KiCad\*\bin\kicad-cli.exe"), reverse=True)]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("kicad-cli not found: add it to PATH or set KICAD_CLI")


# --- Callout text from footprint properties ---------------------------------

TOKEN = re.compile(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+')


def sexp(text):
    """Parse an s-expression file into nested lists; atoms are strings."""
    stack = [[]]
    for t in TOKEN.findall(text):
        if t == "(":
            stack.append([])
        elif t == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(re.sub(r'\\(.)', lambda m: "\n" if m[1] == "n" else m[1], t[1:-1]) if t[0] == '"' else t)
    return stack[0][0]


def read_callouts(pcb):
    """Return [{ref, name, description}] for each footprint with a non-empty "Callout" property."""
    items = []
    for node in sexp(open(pcb, encoding="utf-8").read()):
        if isinstance(node, list) and node[:1] == ["footprint"]:
            props = {n[1]: n[2] for n in node if isinstance(n, list) and n[:1] == ["property"] and len(n) > 2}
            if props.get("Callout"):
                items.append(dict(ref=props.get("Reference", "?"), name=props["Callout"],
                                  description=props.get("Callout Description", "")))
    return items


def strip_models(text):
    """Return the board file text with every footprint's (model ...) block removed."""
    out, pos, depth, head, start = [], 0, 0, False, None
    for m in TOKEN.finditer(text):
        t = m.group()
        if t == "(":
            depth += 1
            open_at, head = m.start(), True
            continue
        if t == ")":
            depth -= 1
            if start is not None and depth == 2:
                out.append(text[pos:start])
                pos, start = m.end(), None
        elif head and t == "model" and depth == 3 and start is None:
            start = open_at
        head = False
    out.append(text[pos:])
    return "".join(out)


# --- Board geometry via IPC-2581 -------------------------------------------

def read_board(kicad_cli, pcb, xml_path):
    """Export the board as IPC-2581 and return (outline bbox, {ref: (x, y, bbox)})
    in KiCad board coordinates (mm, y down).  IPC-2581 uses y up, so y is negated.
    A footprint's bbox covers its courtyard outline plus its pin positions."""
    subprocess.run([kicad_cli, "pcb", "export", "ipc2581", "-o", xml_path, "--units", "mm", pcb],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    root = ET.parse(xml_path).getroot()
    ns = root.tag[1:root.tag.index("}")]
    tag = lambda t: f"{{{ns}}}{t}"
    points = lambda node: [(float(e.get("x")), float(e.get("y"))) for e in node.iter() if e.get("x") is not None]

    profile = points(root.find(f".//{tag('Profile')}"))  # arcs are already flattened into segments
    xs, ys = [x for x, _ in profile], [-y for _, y in profile]
    outline = (min(xs), min(ys), max(xs), max(ys))

    packages = {}
    for pk in root.iter(tag("Package")):
        pts = points(pk.find(tag("Outline"))) if pk.find(tag("Outline")) is not None else []
        pts += [points(pin.find(tag("Location")))[0] for pin in pk.iter(tag("Pin"))]
        packages[pk.get("name")] = pts or [(0.0, 0.0)]

    fps = {}
    for comp in root.iter(tag("Component")):
        loc = comp.find(tag("Location"))
        cx, cy = float(loc.get("x")), float(loc.get("y"))
        xform = comp.find(tag("Xform"))
        rot = math.radians(float(xform.get("rotation", 0))) if xform is not None else 0.0
        mx = -1 if xform is not None and xform.get("mirror") == "true" else 1  # back-side parts: rotate, then mirror X
        c, s = math.cos(rot), math.sin(rot)
        world = [(cx + mx * (x * c - y * s), -(cy + x * s + y * c)) for x, y in packages[comp.get("packageRef")]]
        fps[comp.get("refDes")] = (cx, -cy, (min(x for x, _ in world), min(y for _, y in world),
                                             max(x for x, _ in world), max(y for _, y in world)))
    return outline, fps


# --- Rendering ---------------------------------------------------------------

def render_board(kicad_cli, pcb, out, aspect):
    """Render a top-down 3D view on a transparent background and return
    (PNG bytes, left, top, right, bottom, content_bbox) where left..bottom are
    the pixel coordinates of the board outline and content_bbox is the extent
    of everything rendered, including parts overhanging the outline.  The
    renderer does not expose its camera maths, so the outline is measured from
    a second render of the board with its 3D models removed: the camera frames
    the board edges alone, so both renders share the same scale and offset."""
    bare = os.path.join(os.path.dirname(out), "bare.kicad_pcb")
    open(bare, "w", encoding="utf-8").write(strip_models(open(pcb, encoding="utf-8").read()))
    bare_png = os.path.join(os.path.dirname(out), "bare.png")
    h = int(RENDER_W * aspect * 1.2)  # extra room for parts overhanging top/bottom
    for src, dst in ((pcb, out), (bare, bare_png)):
        subprocess.run([kicad_cli, "pcb", "render", "-o", dst, "--side", "top", "--background", "transparent",
                        "--quality", "basic", "--zoom", "0.8", "-w", str(RENDER_W), "-h", str(h), src],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mask = lambda path: Image.open(path).convert("RGBA").split()[3].point(lambda v: 255 if v > 128 else 0)
    full = mask(out).getbbox()
    W, H = Image.open(out).size
    if full[0] == 0 or full[1] == 0 or full[2] == W or full[3] == H:
        print("warning: render is clipped at the image edge", file=sys.stderr)
    left, top, right, bottom = mask(bare_png).getbbox()
    return open(out, "rb").read(), left, top, right - 1, bottom - 1, full


def esc(s):
    return html.escape(s, quote=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcb")
    ap.add_argument("-o", "--out", default="connectors.png", help=".png or .pdf (via rsvg-convert), or .svg")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--title", default=None)
    a = ap.parse_args()

    kicad_cli = find_kicad_cli()
    rows = read_callouts(a.pcb)
    if not rows:
        sys.exit(f'no footprints with a "Callout" property in {a.pcb}')
    with tempfile.TemporaryDirectory() as td:
        (ox, oy, ex, ey), fps = read_board(kicad_cli, a.pcb, os.path.join(td, "board.xml"))
        bw, bh = ex - ox, ey - oy
        png, pl, pt, pr, pb, full = render_board(kicad_cli, a.pcb, os.path.join(td, "render.png"), bh / bw)
        im_w, im_h = Image.open(os.path.join(td, "render.png")).size
        scale = (pr - pl) / bw  # render px per mm

        # Connector positions in board-local mm (origin at the top-left of the outline).
        items = []
        for r in rows:
            if r["ref"] not in fps:
                print(f"warning: {r['ref']} not on board", file=sys.stderr)
                continue
            fx, fy, (l, t, rr, b) = fps[r["ref"]]
            items.append(dict(r, x=fx - ox, y=fy - oy, bx=l - ox, by=t - oy, bwid=rr - l, bhgt=b - t))

        # Put each callout on the side of the board nearest to it, stacked top to bottom.
        left = sorted([i for i in items if i["x"] < bw / 2], key=lambda i: i["y"])
        right = sorted([i for i in items if i["x"] >= bw / 2], key=lambda i: i["y"])
        over_top, over_bot = (pt - full[1]) / scale, (full[3] - pb) / scale  # parts overhanging the outline, mm
        board_x = MARGIN + COL_W + GAP
        board_y = MARGIN + TITLE_H + over_top
        W = board_x + bw + GAP + COL_W + MARGIN
        dim_y = board_y + bh + over_bot + 5  # width dimension line, below any overhang
        H = max(dim_y + 4, board_y + max(len(left), len(right)) * (BOX_H + 3)) + MARGIN

        def place(col, x0):
            ys = []
            for i in col:
                y = max(MARGIN + TITLE_H, i["y"] + board_y - BOX_H / 2)  # keep clear of the title
                if ys and y < ys[-1] + BOX_H + 2:
                    y = ys[-1] + BOX_H + 2
                ys.append(y)
                i["box"] = (x0, y)

        place(left, MARGIN)
        place(right, board_x + bw + GAP)

        title = a.title or os.path.splitext(os.path.basename(a.pcb))[0]
        rev = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(a.pcb)), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        subtitle = f"Connector overview · git {rev}" if rev else "Connector overview"

        data = base64.b64encode(png).decode()
        inner = (f'<image x="{board_x - pl / scale}" y="{board_y - pt / scale}" width="{im_w / scale}" height="{im_h / scale}" '
                 f'href="data:image/png;base64,{data}"/>')

        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
               f'<rect width="{W}" height="{H}" fill="white"/>',
               f'<text x="{MARGIN}" y="{MARGIN + 5}" font-size="5" font-weight="bold">{esc(title)}</text>',
               f'<text x="{MARGIN}" y="{MARGIN + 9.5}" font-size="2.6" fill="#555">{esc(subtitle)}</text>',
               inner]
        # Overall board dimensions: width below the board, height in the gap to its left.
        dim = 'stroke="#222" stroke-width="0.25"'
        dim_x = board_x - 5
        out += [f'<line x1="{board_x}" y1="{board_y + bh}" x2="{board_x}" y2="{dim_y + 1.5}" {dim}/>',
                f'<line x1="{board_x + bw}" y1="{board_y + bh}" x2="{board_x + bw}" y2="{dim_y + 1.5}" {dim}/>',
                f'<line x1="{board_x}" y1="{dim_y}" x2="{board_x + bw}" y2="{dim_y}" {dim}/>',
                f'<text x="{board_x + bw / 2}" y="{dim_y - 1}" font-size="2.6" text-anchor="middle">{bw:g} mm</text>',
                f'<line x1="{board_x}" y1="{board_y}" x2="{dim_x - 1.5}" y2="{board_y}" {dim}/>',
                f'<line x1="{board_x}" y1="{board_y + bh}" x2="{dim_x - 1.5}" y2="{board_y + bh}" {dim}/>',
                f'<line x1="{dim_x}" y1="{board_y}" x2="{dim_x}" y2="{board_y + bh}" {dim}/>',
                f'<text transform="translate({dim_x - 1},{board_y + bh / 2}) rotate(-90)" font-size="2.6" text-anchor="middle">{bh:g} mm</text>']
        for i in items:
            x0, y0 = i["box"]
            on_left = x0 < board_x
            ax = x0 + COL_W if on_left else x0          # anchor on the box edge facing the board
            cx = board_x + i["x"]; cy = board_y + i["y"]
            out.append(f'<rect x="{board_x + i["bx"]}" y="{board_y + i["by"]}" width="{i["bwid"]}" height="{i["bhgt"]}" '
                       f'fill="none" stroke="#d62828" stroke-width="0.4" rx="0.6"/>')
            out.append(f'<line x1="{ax}" y1="{y0 + BOX_H / 2}" x2="{cx}" y2="{cy}" stroke="#d62828" stroke-width="0.35"/>')
            out.append(f'<circle cx="{cx}" cy="{cy}" r="0.8" fill="#d62828"/>')
            out.append(f'<rect x="{x0}" y="{y0}" width="{COL_W}" height="{BOX_H}" fill="#fff" stroke="#d62828" stroke-width="0.35" rx="1"/>')
            out.append(f'<text x="{x0 + 2}" y="{y0 + 4.2}" font-size="3.2" font-weight="bold">{esc(i["ref"])}  '
                       f'<tspan font-weight="normal">{esc(i["name"])}</tspan></text>')
            for n, line in enumerate(textwrap.wrap(i["description"], 58)[:2]):
                out.append(f'<text x="{x0 + 2}" y="{y0 + 8.2 + 3 * n}" font-size="2.2" fill="#333">{esc(line)}</text>')
        out.append("</svg>")

        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        svg_path = a.out if a.out.endswith(".svg") else os.path.join(td, "out.svg")
        open(svg_path, "w", encoding="utf-8").write("\n".join(out))
        if svg_path != a.out:
            if not shutil.which("rsvg-convert"):
                sys.exit("rsvg-convert not found (install librsvg), or use a .svg output path")
            fmt = os.path.splitext(a.out)[1][1:]
            subprocess.run(["rsvg-convert", "-f", fmt, "-d", str(a.dpi), "-p", str(a.dpi), "-o", a.out, svg_path], check=True)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
