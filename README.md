Falcon BMS HTML Briefings [WIP, may break]
==========
This is a collection of Python scripts to generate editable HTML kneeboard files for use with Falcon BMS. Currently it only parses data from briefing.txt and callsign.ini.

This is heavily inspired by other wonderful BMS kneeboard tools, such as [bms-kneeboard-server](https://github.com/AviiNL/bms-kneeboard-server) and [EZBoards](https://forum.falcon-bms.com/topic/19901/ezboards-generate-kneeboards-flights-comms-stpts-weather-from-briefings)

The main difference is that I wanted a tool that has minimal dependencies, is cross-platform and allows to modify the briefing files after they are filled with the briefing.txt information. The default kneeboard setup is inspired by my practice during multiplayer flights in the style of [UOAF](https://uoaf.net/).

Installation
------------
# Requirements: 
If you use the Python script (and not the provided Windows executable), you need [Python 3](https://www.python.org/downloads/) and jinja2 module for it. If you already have Python you probably know what to do, something like
```
pip install jinja2
```
should work, depending on your operating system. Released executable should work on Windows with no dependencies.

Usage
------------
In the config.ini file (see the example provided!), set the location of your BMS folder, the desired output folder for the .thml files and your callsign. E.g.
```
bms_location = D:\Falcon BMS 4.38
output_folder = C:\Games\bms_html_briefing\output
callsign = wsy
```

Then run
```
python make_pages.py config.ini
```
or, if you are on Windows and don't want to install Python,
```
make_pages.exe config.ini
```

It will generate .html files in the output directory. You can open them in a browser and edit them to your heart's content. When finished, you can, for example, print them to .pdf and use with [OpenKneeboard](https://openkneeboard.com/).

If you set the option ```joined = True``` it will generate a single .html file with all pages in it. When you open it in a (modern) browser and print it to PDF, it should automatically separate pages correctly. This saves some time compared to printing each page separately.

When an .html kneeboard is opened in a browser, the "Save" and "Load" buttons can be clicked. This will save/load the contents of the editable fields to/from the browser memory. The intention is to be able to preserve some of the entered information (e.g. delivery method) even if some other information was changed in the briefing (e.g. flightplan has changed and you have to reload the briefing).

In the config.ini file you may also modify the page contents: it is a list of lines of the form "page = section1, section2, ...", a single list of keywords producing a page of the kneeboard. Keywords refer to various kneeboard sections and coincide with the names of files in the templates folder. 

Modification
-------------
The templates to generate kneeboards are in the "templates" folder. These are jinja2 templates written in simple HTML, so should be easy to modify. 

Example output
-------------
<p float="left">
<img src="examples/1.png" alt="left" width="33%"/>
<img src="examples/2.png" alt="right" width="33%"/>
<img src="examples/3.png" alt="right" width="33%"/>
</p>
