# kicad-callouts

Generate a static, annotated top-down 3D image of a KiCad PCB with a labelled callout for each connector (or any other footprint you choose).

Give it a `.kicad_pcb` file and a CSV listing the reference designators you want called out. It renders the board with KiCad, draws a red box around each listed footprint, adds a leader line to a label box on the nearest side of the board, and adds overall board dimensions. The result is a PNG, PDF, or SVG suitable for a datasheet, README, or assembly guide.

## Install

With [uv](https://docs.astral.sh/uv/):

```
uv tool install git+https://github.com/keenanjohnson/kicad-callouts
```

## Usage

```
kicad-callouts board.kicad_pcb connectors.csv -o docs/connectors.png
```

Arguments and options:

| Argument | Meaning |
| --- | --- |
| `pcb` | Path to the `.kicad_pcb` file. |
| `csv` | CSV of footprints to call out (see below). |
| `-o`, `--out` | Output path. The extension picks the format: `.png`, `.pdf`, or `.svg`. Defaults to `connectors.png`. |
| `--dpi` | Resolution for PNG/PDF output. Defaults to 300. |
| `--title` | Title printed at the top of the image. Defaults to the PCB filename. |

If the PCB lives in a git repository, the short commit hash is printed under the title so you can tell which board revision the image was made from.

### The CSV file

A header row followed by one line per footprint, with these columns:

| Column | Meaning |
| --- | --- |
| `ref` | Reference designator on the board, such as `J1`. |
| `name` | Short label shown in bold next to the reference. |
| `description` | Longer text shown under the label. Wrapped to two lines; anything beyond that is cut. |

Example `connectors.csv`:

```csv
ref,name,description
J1,USB-C,Power input and USB 2.0 data. 5 V at up to 3 A.
J2,Debug,SWD header for programming and debugging. 1.27 mm pitch.
J3,I2C,Qwiic / STEMMA QT connector. 3.3 V logic.
J4,Battery,2-pin JST-PH for a single-cell LiPo.
```

Any `ref` that is not found on the board is skipped with a warning, and the rest of the image is still produced.

### Layout

Callouts are placed in a column on whichever side of the board the footprint is closer to, ordered top to bottom by the footprint's position. Boxes that would overlap are pushed down. Callout text can be any footprint, not just connectors, so the same tool works for switches, LEDs, test points, or mounting holes.

## License

MIT. See [LICENSE](LICENSE).
