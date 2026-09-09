# kicad-callouts

Generate a static, annotated top-down 3D image of a KiCad PCB with a labelled callout for each connector (or any other footprint you choose).

Give it a `.kicad_pcb` file in which the footprints you want called out carry a `Callout` property. It renders the board with KiCad, draws a red box around each listed footprint, adds a leader line to a label box on the nearest side of the board, and adds overall board dimensions. The result is a PNG, PDF, or SVG suitable for a datasheet, README, or assembly guide.

![Example output: a small demo board with seven labelled callouts](https://raw.githubusercontent.com/keenanjohnson/kicad-callouts/main/docs/example.png)

The image above was made from the sample board in [docs/demo/](docs/demo/) with:

```
kicad-callouts docs/demo/demo.kicad_pcb -o docs/example.png --title "Demo board"
```

## Install

With [uv](https://docs.astral.sh/uv/):

```
uv tool install kicad-callouts
```

## Usage

```
kicad-callouts board.kicad_pcb -o docs/connectors.png
```

Arguments and options:

| Argument | Meaning |
| --- | --- |
| `pcb` | Path to the `.kicad_pcb` file. |
| `-o`, `--out` | Output path. The extension picks the format: `.png`, `.pdf`, or `.svg`. Defaults to `connectors.png`. |
| `--dpi` | Resolution for PNG/PDF output. Defaults to 300. |
| `--title` | Title printed at the top of the image. Defaults to the PCB filename. |

If the PCB lives in a git repository, the short commit hash is printed under the title so you can tell which board revision the image was made from.

### Marking footprints for callout

Every footprint with a non-empty `Callout` property gets a callout. Two properties are read:

| Property | Meaning |
| --- | --- |
| `Callout` | Short label shown in bold next to the reference designator, such as `USB-C`. Required. |
| `Callout Description` | Longer text shown under the label. Wrapped to two lines; anything beyond that is cut. Optional. |

The easiest place to set them is the schematic: add the fields to each symbol (Symbol Properties, or the Symbol Fields Table for many at once), then run **Update PCB from Schematic**. KiCad copies symbol fields onto the footprints, and they survive later updates. Adding them directly to a footprint in the PCB editor also works, but the next update from the schematic may remove them. Either way, mark the fields as hidden so they are not drawn on the board.

### Layout

Callouts are placed in a column on whichever side of the board the footprint is closer to, ordered top to bottom by the footprint's position. Boxes that would overlap are pushed down. Callout text can be any footprint, not just connectors, so the same tool works for switches, LEDs, test points, or mounting holes.

## License

MIT. See [LICENSE](LICENSE).
