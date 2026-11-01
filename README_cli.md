# Chart generator (command line)

The chart generator used by the app can also be run on its own to produce charts for a whole theater, for example to publish a replacement for the charts shipped with BMS. It does not need the web interface. It is available as a separate download on the release page (`openchart_cli.exe` or `openchart_cli`), not part of the app archive) and takes the same options as the source version. 

```
openchart_cli.exe [options]
./openchart_cli [options]
python -m openchart.cli [options]     # from the repository root
```

For every airfield it can write up to three charts:

- **Ground chart** - taxiways, runways and parking.
- **Parking charts** - one page per runway end, with numbered parking spots. Airfields without parking data have none.
- **Local chart** - the topographic chart (50 x 50 NM, 500 ft elevation bands), only with `--topo` or `--bms-layout`.

## Options

| Option             | Description                                                                                                                                                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--data-root PATH` | The BMS theater data folder, for example `C:\Falcon BMS 4.38\Data` for Korea or `C:\Falcon BMS 4.38\Data\Add-On Hellas` for an add-on theater. The folder must be `Data` itself or sit directly inside a folder named `Data`. |
| `--output DIR`     | Folder to write the charts to (default: `test_charts`).                                                                                                                                                                       |
| `--airport ID`     | Campaign ID of an airfield; repeat for several. Without it, four Korea airfields are used (995, 1784, 1486, 983).                                                                                                             |
| `--all-airports`   | Generate every airfield in the theater instead of listing IDs.                                                                                                                                                                |
| `--format`         | `svg`, `png`, `pdf`, `both` (svg + pdf) or `all` (svg + png + pdf). Default `svg`. With `--bms-layout`: `png`, `pdf` or `all` (png + pdf).                                                                                    |
| `--topo`           | Also write the local (topographic) chart.                                                                                                                                                                                     |
| `--bms-layout`     | Write the charts in the folder layout described below, one folder per airfield, grouped by team. Includes the local chart.                                                                                                    |
| `--campaign FILE`  | Use the airfields and owners of a campaign file (`.tac`/`.cam`) instead of the theater defaults.                                                                                                                              |
| `--dpi N`          | Resolution of PNG and PDF output (default 150).                                                                                                                                                                               |

## Examples

```
# Every airfield of a theater, PNG and PDF, grouped by team
openchart_cli.exe --data-root "C:\Falcon BMS 4.38\Data\Add-On Hellas" --all-airports --bms-layout --format all --output "Hellas Charts"

# Two airfields as PDF including the local chart
openchart_cli.exe --data-root "C:\Falcon BMS 4.38\Data" --airport 1784 --airport 995 --format pdf --topo --output charts
```

## Finding airfield IDs

The IDs are the campaign IDs of the airfields. From source:

```
python -c "from openchart.source import AirportRepository; r=AirportRepository(r'C:\Falcon BMS 4.38\Data'); [print(e.campaign_id,'|',e.name,'|',e.icao) for e in sorted(r.entries,key=lambda e:e.name)]"
```

## Output layout (`--bms-layout`)

```
<output>/<Team>/<Airfield name (ICAO)>/<Airfield name (ICAO)>_AGC.png|pdf
                                       <Airfield name (ICAO)>_APC_RWY09L.png ...
                                       <Airfield name (ICAO)>_APC.pdf
                                       <Airfield name (ICAO)>_LOC.png|pdf
```

- `_AGC` is the ground chart, `_APC` the parking charts and `_LOC` the local chart. PNG output has one `_APC_RWYxx` image per runway end; the PDF has one `_APC.pdf` with all runway ends as pages.
- The team folder is the airfield's owner at the start of the campaign, read from `Campaign/Te_New_Nt.tac` of the theater (or the file given with `--campaign`). Team names are used as they are stored (for example `ROK`, `Turkey`, `NATO`); rename the folders afterwards if you prefer. Airfields that are not in the file go to `Unassigned`.
- The airfield name drops a trailing "Airport" or "Airbase" and adds the ICAO code when the airfield has one. Folder names ending with a dot lose it (`U.S.` becomes `U.S`) because Windows does not allow it.

## Notes

- The generated pages are A4 portrait at 150 dpi (unlike the landscape images shipped with BMS).
- Existing files are overwritten, but folders from earlier runs are not removed.
- Each file path is printed as it is written. An airfield whose local chart cannot be created (for example because the theater has no height map) is reported and skipped.

## From source

1. (Optional) Create and activate a Python venv.
2. `pip install -r requirements.txt`
3. `python -m openchart.cli [options]`
