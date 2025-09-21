Falcon BMS HTML Briefings [WIP, may break]
==========
This is a collection of Python scripts to generate editable HTML kneeboard files for use with Falcon BMS. Currently it only parses data from briefing.txt.

This is heavily inspired by other wonderful BMS kneeboard tools, such as [bms-kneeboard-server](https://github.com/AviiNL/bms-kneeboard-server) and [EZBoards](https://forum.falcon-bms.com/topic/19901/ezboards-generate-kneeboards-flights-comms-stpts-weather-from-briefings)

The main difference is that I wanted a tool that has minimal dependencies, is cross-platform and allows to modify the briefing files after they are filled with the briefing.txt information. The default kneeboard setup is inspired by my practice during multiplayer flights in the style of [UOAF](https://uoaf.net/).

Installation
------------
# Requirements: 
You need [Python 3](https://www.python.org/downloads/) and jinja2 module for it. If you already have Python you probably know what to do, something like
```
pip install jinja2
```
should work, depending on your operating system.

Usage
------------
In the config file, set the location of your briefing.txt file, e.g. 
```
briefing_location = "C:\Falcon BMS 4.37\User\Briefings\briefing.txt"
```
Then go to the html_brief folder and run
```
python make_pages.py
```
It will generate two .html files, html_left.html and html_right.html. You can open them in browser and edit them to your heart's content. When finished, you can, for example, print them to .pdf and use with [OpenKneeboard](https://openkneeboard.com/).

Modification
-------------
The templates to generate kneeboards are in the "templates" folder. These are jinja2 templates written in simple HTML, so should be easy to modify. 
