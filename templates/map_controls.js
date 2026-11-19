/* SPDX-License-Identifier: AGPL-3.0-only
 * Drawing glyphs adapted from BMS-Cards briefing.js at 7436fa4:
 * https://github.com/Evilangel19/BMS-Cards (AGPLv3).
 * Changes (2026-11-17): shared icons and accessible buttons for all map controls.
 */
(function (global) {
    "use strict";
    const ICONS = {
        pan: '<path d="M12 3v18M3 12h18M12 3l-3 3m3-3l3 3M12 21l-3-3m3 3l3-3M3 12l3-3m-3 3l3 3M21 12l-3-3m3 3l-3 3"/>',
        select: '<path d="M5 3l12 8-5.5 1.2L9 18z"/>',
        laser: '<circle cx="12" cy="12" r="3" fill="currentColor"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l2.5 2.5M16.5 16.5L19 19M5 19l2.5-2.5M16.5 7.5L19 5"/>',
        point: '<circle cx="12" cy="12" r="4"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>',
        pen: '<path d="M4 20l1.2-4.4L16 4.8l3.2 3.2L8.4 18.8zM14 6.8l3.2 3.2"/>',
        marker: '<path d="M5 15l8-8 4 4-8 8H5zM13 7l2-2 4 4-2 2"/>',
        arrow: '<path d="M5 19L19 5M10 5h9v9"/>',
        line: '<path d="M5 19L19 5"/>',
        circle: '<circle cx="12" cy="12" r="8"/>',
        rectangle: '<rect x="4" y="6" width="16" height="12" rx="1"/>',
        text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
        symbol: '<path d="M12 3l9 9-9 9-9-9z"/>',
        erase: '<path d="M8 20h12M5 15l9-9 5 5-7 7H8zM9.5 10.5l5 5"/>',
        undo: '<path d="M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3"/>',
        redo: '<path d="M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3"/>',
        clear: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    };
    Object.assign(ICONS, {
        ruler: '<path d="M4 15l11-11 5 5L9 20zM13 6l2 2M10 9l2 2M7 12l2 2"/>',
        close: '<path d="M18 6L6 18M6 6l12 12"/>',
        done: '<path d="M5 12l4 4L19 6"/>',
        expand: '<path d="M9 3H3v6M15 3h6v6M21 15v6h-6M9 21H3v-6"/>',
        collapse: '<path d="M3 9h6V3M15 3v6h6M21 15h-6v6M9 21v-6H3"/>',
        "threat-filled": '<circle cx="12" cy="12" r="8" fill="currentColor" stroke="none"/>',
        "threat-outline": '<circle cx="12" cy="12" r="8"/>',
        "threat-none": '<circle cx="12" cy="12" r="8"/><path d="M8 8l8 8M16 8l-8 8"/>',
    });
    // One glyph per meaning, reused by the launcher and the drawing toolbar.
    ICONS.pencil = ICONS.pen;
    ICONS.delete = ICONS.clear;
    function setIcon(element, name) {
        element.dataset.mapIcon = name;
        element.innerHTML = '<svg class="map-control-icon" viewBox="0 0 24 24" aria-hidden="true">' + ICONS[name] + '</svg>';
    }
    function button(label, icon, action) {
        const element = document.createElement("button");
        element.type = "button";
        element.className = "map-icon-button";
        element.title = label;
        element.setAttribute("aria-label", label);
        if (icon) setIcon(element, icon);
        if (action) element.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            action(event);
        });
        return element;
    }
    global.MapControls = { button, setIcon };
})(window);
