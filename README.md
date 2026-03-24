<img src="examples/1.png" alt="left" width="50%"/>

# Falcon BMS HTML Briefings
This is a tool to generate editable kneeboard files for use with Falcon BMS.

HTML Briefing is inspired by other wonderful BMS kneeboard tools, such as [bms-kneeboard-server](https://github.com/AviiNL/bms-kneeboard-server) and [EZBoards](https://forum.falcon-bms.com/topic/19901/ezboards-generate-kneeboards-flights-comms-stpts-weather-from-briefings)

The main difference is that I wanted an open source tool that has ~~minimal~~ reasonable dependencies, is cross-platform, and allows quick edits to briefing files after they are filled with briefing.txt data. The default kneeboard setup is informed by my practice during multiplayer flights with [UOAF](https://uoaf.net/).

## Main features and goals
- [x] Works both on Linux and Windows.
- [x] Automatically reads BMS and theater data from the registry.
- [x] Allows to edit kneeboards after they are populated with callsign.ini and briefing.txt data.
- [x] Single-click PDF and BMS kneeboards export.
- [x] Functional map.

#### Possible future features
- [ ] Support adding airport and approach charts.
- [ ] (long term) Parse binary save file data.

## Usage
### Using the provided executable
Make sure that "Briefing output to file" option is ```ON``` in BMS config, and "HTML Briefings" is ```OFF```.

Unpack the archive and launch the html_brief executable. You can then access the application interface in your browser at 127.0.0.1:8000 (the port can be changed via the ```-p PORT``` launch option).

Linux users need to specify the **absolute** Wine prefix—the folder where the BMS ```drive_c``` lives—either in config.ini or in the interface (and save it from there).

Click "Show settings" on the top dashboard to open the settings toolbar, where you can verify detected folders and choose the BMS version and airframe you are using.

The "Copy to KTO" checkbox copies the .dds kneeboard to the default KTO folder. This may be needed for some theater/aircraft combinations; see this [forum thread](https://forum.falcon-bms.com/topic/31944/f-15-kneeboard-textures-sourced-from-wrong-folder-in-all-standard-add-on-theaters).

To update the briefing and steerpoints information, you need to do these things in BMS 2D map screen: 0) Click your flight and seat; 1) press "Briefing" -> "Print"; 2) save DTC. 
#### Note on kneeboard export: 
All the ```.pdf, .png, .jpg``` files in the ```kneeboards``` folder will be exported to BMS kneeboards, in alphabetical order; so you can add your own kneeboard pages.

#### Logo
Replace ```logo.png``` with your own logo (appears in the flight roster section), because why not.

### From source
1. (Optional) Create and activate a Python venv.
2. ```pip install -r requirements.txt```
3. ```python html_brief.py```

When launched from a frozen executable, the app starts in the system tray by default. The tray menu contains a single action: ```Quit```.

### Configuration
- The app reads and writes `config.ini` next to the executable (or this repository root when run from source). If it does not exist, a default one is created on first launch.
- Settings changed in the UI are saved back to `config.ini` and theatersXXX.ini on "Save config" click.
- Paths can be absolute or relative; relative paths are resolved from the folder where the executable/script lives.
- Minimal example:
```
[system]
output_dir = output
pdf_output_dir = kneeboards
wine_prefix =
auto_export_on_change = False
auto_export_pdf_only = False

[bms]
bms_version = 4.38
bms_available_versions = 4.37, 4.38
default_airframe = F-16

[pages]
# Comma-separated sections per page; edit to reorder or remove panels.
page1 = package, flightplan
page2 = roster, admin, weapons, weapon_settings, wpn_targets, cmds, custom_checklist
```
#### Configuration override
In case you want to override the auto-detected BMS parameters (for example, if your callsign was read from the registry with some weird characters and the app fails to detect the .ini file), you can add an 'override' section to the config.ini as follows:
```
[override]
callsign = <SET CALLSIGN>
base_dir = <BMS base dir>
thater = <BMS theater>
```
### Map
Starting with version 0.5 there is an option to add a map to the kneeboards. This uses [Leaflet](https://leafletjs.com/).

The app will try to find the default map for some theaters (official ones and 4.37 Coastal Front). A map can also be loaded by setting ```map_file``` in the corresponding theaters_XXX.ini, or by choosing the file in the widget itself.

The map can be dragged with the mouse and zoomed with the mouse wheel. Double-click sets the bullseye.

The map images usually come with the theater install. For example (all folders are relative to the Falcon BMS install path):
* KTO has several 4K map images to choose from in ```Docs/05 Maps/``` folder
* ITO similarly has those in ```Data/Add-On Israel/Docs/02 Maps``` folder,
* Coastal Front for BMS 4.37 has maps in ```Data/Add-On Coastal Front/Docs/Tacview_and_WDP_files/WDP/Coastal Front``` folder.

### Reference images
Targets section of the kneeboard can be used to upload target reference images. Put them into ```assets/targets/``` folder.

### Launch options
- ```-p PORT```: set the port (default: 8000).
- ```--no-browser```: prevent the app from automatically opening a browser tab on startup.
- ```--tray```: force tray mode when running from source.
- ```--no-tray```: disable tray mode for the frozen executable.

Modification
-------------
The templates to generate kneeboards are in the "templates" folder. These are jinja2 templates written in simple HTML, so should be easy to modify.

Example output
-------------
<p float="left">
<img src="examples/2.png" alt="right" width="66%"/>
</p>
