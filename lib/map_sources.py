LOCAL_MAP_ID = "local"

WEB_MAP_SOURCES = {
    "esri_imagery_hybrid": {
        "label": "Web satelite",
        "max_zoom": 18,
        "layers": [
            {
                "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "attribution": "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                "filter": "brightness(1.0) saturate(1.0) contrast(1.0)",
                "opacity": 1.0,
                "max_native_zoom": 23,
                "z_index": 200,
            },
            {
                "url_template": "https://server.arcgisonline.com/arcgis/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
                "attribution": "Tiles &copy; Esri",
                "opacity": 1.0,
                "blend_mode": "multiply",
                "export": False,
                "max_zoom": 14,
                "max_native_zoom": 16,
                "z_index": 210,
            },
            {
                "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                "attribution": "Tiles &copy; Esri",
                "opacity": 1.0,
                "max_native_zoom": 23,
                "z_index": 650,
            },
        ],
    },
#    "esri_terrain": {
#        "label": "Web terrain",
#        "max_zoom": 13,
#        "layers": [
#            {
#                "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}",
#                "attribution": "Tiles &copy; Esri",
#                "max_native_zoom": 13,
#            },
#        ],
#    },
}

REPLACED_MAP_SYSTEM_KEYS = {
    "map_base_mode",
    "web_tile_url_template",
    "web_tile_attribution",
    "web_tile_filter",
    "web_tile_layers",
}


def map_source_options():
    options = [{"id": LOCAL_MAP_ID, "label": "BMS local"}]
    options.extend(
        {"id": map_id, "label": source.get("label", map_id)}
        for map_id, source in WEB_MAP_SOURCES.items()
    )
    return options


def map_selection(conf):
    try:
        raw = conf["system"].get("map", LOCAL_MAP_ID)
    except Exception:
        raw = LOCAL_MAP_ID
    map_id = str(raw).strip().lower().replace("-", "_") or LOCAL_MAP_ID
    if map_id in WEB_MAP_SOURCES:
        return map_selection_from_id(map_id)

    return map_selection_from_id(LOCAL_MAP_ID)


def map_selection_from_id(map_id):
    if map_id in WEB_MAP_SOURCES:
        source = WEB_MAP_SOURCES[map_id]
        layers = source.get("layers") or [source]
        first_layer = layers[0] if layers else {}
        return {
            "id": map_id,
            "base_mode": "web",
            "web_tile_layers": layers,
            "web_tile_url_template": first_layer.get("url_template", ""),
            "web_tile_attribution": first_layer.get("attribution", ""),
            "web_tile_filter": first_layer.get("filter", ""),
            "web_tile_max_zoom": source.get("max_zoom", 19),
        }
    return {
        "id": LOCAL_MAP_ID,
        "base_mode": "local_tiles",
        "web_tile_layers": [],
        "web_tile_url_template": "",
        "web_tile_attribution": "",
        "web_tile_filter": "",
        "web_tile_max_zoom": 19,
    }
