/* SPDX-License-Identifier: AGPL-3.0-only
 * Adapted 2026-11-17 from BMS-Cards' mapview.js and briefing.js at 7436fa4:
 * https://github.com/Evilangel19/BMS-Cards (AGPLv3).
 * Changes: independent briefing annotations, BMS-plane geometry, persistent
 * rectangles, local undo/redo, standalone toolbar, and canvas export.
 * No DTC, campaign, multiplayer, or weather writes.
 * Changes (2026-11-19): local, transient BMS-Cards laser pointer.
 */
(function (global) {
    "use strict";
    const NM = 6076.12;
    const DEFAULT_COLOR = "#f5c842";
    const SYMBOLS = ["armor", "inf", "art", "missile", "ad", "hq", "eng", "generic",
        "trk", "ab", "IP", "CP", "tgt", "bull", "orbit", "hold", "ring"];
    const PAIRED_SYMBOLS = ["trk", "orbit", "hold", "ring"];
    const KINDS = ["point", "line", "rectangle", "pen", "marker", "arrow", "circle", "text", "symbol"];
    const clone = (value) => JSON.parse(JSON.stringify(value));
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const signs = [[-1, 1], [1, 1], [1, -1], [-1, -1]];

    // Coordinates are [east, north] in feet, independent of the Leaflet CRS.
    function rectanglePoint(rect, x, y) {
        const angle = rect.rotation * Math.PI / 180;
        return [rect.center[0] + x * Math.cos(angle) + y * Math.sin(angle),
            rect.center[1] - x * Math.sin(angle) + y * Math.cos(angle)];
    }
    function corners(rect) {
        return signs.map(([x, y]) => rectanglePoint(rect, x * rect.a, y * rect.b));
    }
    function resizeRectangle(rect, index, position, opposite) {
        const angle = rect.rotation * Math.PI / 180;
        const dx = position[0] - opposite[0], dy = position[1] - opposite[1];
        const [sx, sy] = signs[index];
        const x = sx * Math.max(20, sx * (dx * Math.cos(angle) - dy * Math.sin(angle)));
        const y = sy * Math.max(20, sy * (dx * Math.sin(angle) + dy * Math.cos(angle)));
        rect.a = Math.abs(x) / 2;
        rect.b = Math.abs(y) / 2;
        rect.center = [opposite[0] + (x * Math.cos(angle) + y * Math.sin(angle)) / 2,
            opposite[1] + (-x * Math.sin(angle) + y * Math.cos(angle)) / 2];
    }
    function points(feature) {
        if (feature.kind === "rectangle") return corners(feature);
        if (feature.kind === "circle" || feature.symbol === "ring") {
            const [a, b] = feature.points;
            const radius = Math.hypot(b[0] - a[0], b[1] - a[1]);
            return Array.from({ length: 64 }, (_, i) => {
                const angle = i * Math.PI / 32;
                return [a[0] + radius * Math.cos(angle), a[1] + radius * Math.sin(angle)];
            });
        }
        return feature.points;
    }
    function labelPoint(feature) {
        if (feature.kind === "rectangle") return feature.center;
        if (["circle", "text", "symbol"].includes(feature.kind)) return feature.points[0];
        const coords = feature.points;
        const lengths = coords.slice(1).map((p, i) => Math.hypot(p[0] - coords[i][0], p[1] - coords[i][1]));
        let remaining = lengths.reduce((sum, length) => sum + length, 0) / 2;
        for (let i = 0; i < lengths.length; i++) {
            if (lengths[i] > 0 && remaining <= lengths[i]) {
                return coords[i].map((n, axis) => n + (coords[i + 1][axis] - n) * remaining / lengths[i]);
            }
            remaining -= lengths[i];
        }
        return coords[0];
    }
    function validFeature(feature, extent) {
        if (!feature || !KINDS.includes(feature.kind)
            || typeof feature.id !== "string" || typeof feature.label !== "string"
            || !feature.id.length || feature.id.length > 200 || feature.label.length > 2000
            || typeof feature.color !== "string" || !/^#[0-9a-f]{6}$/i.test(feature.color)
            || (feature.width !== undefined && (!Number.isFinite(feature.width) || feature.width < 1 || feature.width > 20))
            || (feature.size !== undefined && (!Number.isFinite(feature.size) || feature.size < 10 || feature.size > 72))) return false;
        if (feature.kind === "rectangle" && (!Array.isArray(feature.center)
            || !feature.center.every(Number.isFinite) || feature.center.length !== 2
            || ![feature.a, feature.b, feature.rotation].every(Number.isFinite)
            || feature.a <= 0 || feature.b <= 0)) return false;
        const coordinate = (p) => Array.isArray(p) && p.length === 2
            && p.every((n) => Number.isFinite(n) && n >= 0 && n <= extent);
        if (feature.kind !== "rectangle") {
            if (!Array.isArray(feature.points) || feature.points.length > 4000 || !feature.points.every(coordinate)) return false;
            const single = ["point", "text"].includes(feature.kind)
                || (feature.kind === "symbol" && !PAIRED_SYMBOLS.includes(feature.symbol));
            if (single ? feature.points.length !== 1 : feature.points.length < 2) return false;
            if ((["arrow", "circle"].includes(feature.kind) || (feature.kind === "symbol" && !single)) && feature.points.length !== 2) return false;
        }
        if (feature.kind === "symbol" && (!SYMBOLS.includes(feature.symbol)
            || !["hostile", "friend", "neutral", "unknown"].includes(feature.side))) return false;
        return points(feature).every(coordinate);
    }
    function shiftFeature(feature, delta) {
        const shifted = clone(feature);
        const move = (p) => p.map((n, axis) => n + delta[axis]);
        if (shifted.center) shifted.center = move(shifted.center);
        if (shifted.points) shifted.points = shifted.points.map(move);
        return shifted;
    }

    function create(map, L, options) {
        let features = [], past = [], future = [];
        let active = false, mode = null, selected = null, draft = null, hover = null;
        let dragBefore = null, dragging = false, handleUpdates = [];
        let color = DEFAULT_COLOR, width = 4, symbol = "armor", side = "hostile";
        let gesture = null, suppressClickUntil = 0, savedNavigation = null;
        let laserTrail = [], laserHead = null, laserFrame = null;
        const drawing = global.BriefingAnnotationDrawing;
        const paneName = "briefingAnnotations", handlePane = "briefingAnnotationHandles";
        map.createPane(paneName).style.zIndex = 750;
        map.createPane(handlePane).style.zIndex = 790;
        const shapes = L.layerGroup().addTo(map), handles = L.layerGroup().addTo(map);
        const container = map.getContainer();
        const canvas = L.DomUtil.create("canvas", "briefing-annotation-canvas", map.getPane(paneName));
        canvas.setAttribute("aria-hidden", "true");
        const laserCanvas = L.DomUtil.create("canvas", "briefing-annotation-laser", map.getPane(paneName));
        laserCanvas.setAttribute("aria-hidden", "true");
        const hitContext = document.createElement("canvas").getContext("2d");
        const toMap = (p) => L.latLng(options.toMap(p));
        const fromMap = (p) => options.fromMap(L.latLng(p));
        const selectedFeature = () => draft || features.find((f) => f.id === selected);
        const inBounds = (p) => Array.isArray(p) && p.length === 2
            && p.every((n) => Number.isFinite(n) && n >= 0 && n <= options.extent);
        const snapshot = () => ({ version: 1, scope: options.scope, features: clone(features) });
        const makeFeature = (kind) => ({ id: global.crypto.randomUUID(), kind, label: "", color, width });
        const control = L.control({ position: "topleft" });
        let root, panel, status, labelInput, colorInput, inspector, palette, sizeInput;
        const buttons = {};
        const message = (value = "") => { status.textContent = value; };

        function changed(before) {
            if (!same(before, features)) {
                past.push(before);
                if (past.length > 50) past.shift();
                future = [];
                options.onChange?.(snapshot());
            }
            render();
        }
        function cancel(nextMode = null) {
            abortGesture();
            clearLaser();
            mode = nextMode;
            draft = null;
            hover = null;
            selected = null;
            message();
            render();
        }
        function setActive(value, { confirmEdit = false } = {}) {
            if (confirmEdit && active && !finishEditing()) return false;
            const opening = !!value && !active;
            if (opening) savedNavigation = {
                dragging: map.dragging.enabled(), doubleClickZoom: map.doubleClickZoom.enabled(),
                touchZoom: map.touchZoom.enabled(), boxZoom: map.boxZoom.enabled(),
            };
            active = !!value;
            cancel(opening ? "pan" : null);
            container.classList.toggle("briefing-annotation-active", active);
            if (active) {
                map.closePopup();
                options.onActivate?.();
            }
            navigation();
            return true;
        }
        function navigation() {
            if (active) {
                const pan = mode === "pan";
                map.dragging[pan ? "enable" : "disable"]();
                map.touchZoom[pan ? "enable" : "disable"]();
                map.doubleClickZoom.disable();
                map.boxZoom.disable();
            } else if (savedNavigation) {
                Object.entries(savedNavigation).forEach(([key, enabled]) => map[key][enabled ? "enable" : "disable"]());
                savedNavigation = null;
            }
        }
        function start(kind) {
            if (!setActive(true, { confirmEdit: true })) return;
            mode = kind === "select" ? null : kind;
            if (kind === "line") draft = { ...makeFeature(kind), points: [] };
            palette.hidden = kind !== "symbol";
            render();
        }
        function finish() {
            if (!draft) return;
            if (draft.kind === "text" && !draft.label.trim()) { cancel(); return; }
            if (!validFeature(draft, options.extent)) {
                message(draft.points?.length < 2 ? "Add point" : "Outside theater");
                return;
            }
            if (features.length >= 3000) { message("Annotation limit"); return; }
            const before = clone(features);
            features.push(draft);
            selected = draft.id;
            draft = null;
            mode = null;
            hover = null;
            message();
            changed(before);
        }
        function finishEditing() {
            abortGesture();
            const feature = selectedFeature();
            if (feature && feature.label !== labelInput.value) changeProperty("label", labelInput.value);
            if (draft && validFeature(draft, options.extent)) {
                finish();
                if (draft) return false;
            }
            cancel();
            if (root.contains(document.activeElement)) document.activeElement.blur();
            return true;
        }
        function history(redo = false) {
            const source = redo ? future : past, destination = redo ? past : future;
            if (!source.length || dragging) return;
            destination.push(clone(features));
            features = source.pop();
            cancel();
            options.onChange?.(snapshot());
        }
        function remove() {
            if (!selected || draft) return;
            const before = clone(features);
            features = features.filter((f) => f.id !== selected);
            selected = null;
            changed(before);
        }
        function select(feature) {
            if (!active || (mode && mode !== "erase")) return;
            if (mode === "erase") {
                const before = clone(features);
                features = features.filter((f) => f !== feature);
                changed(before);
                return;
            }
            selected = feature.id;
            message();
            render();
        }
        function changeProperty(key, value) {
            const feature = selectedFeature();
            if (!feature) return;
            const before = clone(features);
            feature[key] = value;
            if (draft) render();
            else changed(before);
        }

        control.onAdd = () => {
            root = L.DomUtil.create("div", "briefing-annotation-control");
            L.DomEvent.disableClickPropagation(root);
            L.DomEvent.disableScrollPropagation(root);
            const button = (parent, name, title, action, icon) => {
                const el = global.MapControls.button(title, icon, action);
                el.dataset.annotation = name;
                parent.append(el);
                buttons[name] = el;
                return el;
            };
            button(options.instrumentContainer, "toggle", "Draw", () => setActive(!active), "pencil");
            panel = document.createElement("div");
            panel.className = "briefing-annotation-panel";
            root.append(panel);
            const bar = document.createElement("div");
            bar.className = "briefing-annotation-bar map-control-surface";
            const strip = document.createElement("div");
            strip.className = "briefing-annotation-strip";
            bar.append(strip);
            panel.append(bar);
            const tools = document.createElement("div");
            tools.className = "briefing-annotation-tools";
            strip.append(tools);
            bar.setAttribute("role", "toolbar");
            bar.setAttribute("aria-label", "Annotations");
            for (const [kind, title] of [["pan", "Move map"], ["select", "Select"], ["laser", "Laser pointer"], ["pen", "Pen"],
                ["marker", "Marker"], ["arrow", "Arrow"], ["line", "Line"], ["circle", "Circle"],
                ["rectangle", "Box"], ["text", "Text"], ["symbol", "Symbol"], ["point", "Point"], ["erase", "Eraser"]]) {
                button(tools, kind, title, () => start(kind), kind);
            }
            button(tools, "undo", "Undo", () => history(), "undo");
            button(tools, "redo", "Redo", () => history(true), "redo");
            button(tools, "clear", "Clear", () => {
                const before = clone(features);
                cancel();
                features = [];
                changed(before);
            }, "clear");
            const styles = document.createElement("div");
            styles.className = "briefing-annotation-styles";
            strip.append(styles);
            drawing.COLORS.forEach((value) => {
                const swatch = button(styles, "color-" + value, value, () => {
                    color = value;
                    changeProperty("color", value);
                    render();
                });
                swatch.classList.add("annotation-swatch");
                swatch.style.backgroundColor = value;
            });
            colorInput = document.createElement("input");
            colorInput.type = "color";
            colorInput.title = "Color";
            colorInput.setAttribute("aria-label", "Color");
            colorInput.dataset.annotation = "color";
            colorInput.addEventListener("change", () => {
                color = colorInput.value;
                changeProperty("color", color);
                render();
            });
            styles.append(colorInput);
            [2, 4, 7].forEach((value, index) => {
                const weight = button(styles, "width-" + value, ["Thin", "Medium", "Thick"][index], () => {
                    width = value;
                    changeProperty("width", value);
                    render();
                });
                weight.classList.add("annotation-width");
                const line = document.createElement("i");
                line.style.height = value + "px";
                weight.append(line);
            });
            palette = document.createElement("div");
            palette.className = "briefing-annotation-palette map-control-surface";
            palette.hidden = true;
            panel.append(palette);
            const drawPalette = () => {
                palette.replaceChildren();
                const group = (label) => {
                    const row = document.createElement("div");
                    row.className = "annotation-palette-row";
                    row.setAttribute("role", "group");
                    row.setAttribute("aria-label", label);
                    palette.append(row);
                    return row;
                };
                const frames = group("Frame");
                Object.keys(drawing.SIDES).forEach((value) => {
                    const item = button(frames, "side-" + value, value[0].toUpperCase() + value.slice(1), () => {
                        side = value;
                        drawPalette();
                    });
                    item.insertAdjacentHTML("afterbegin", drawing.symbolIcon("armor", value));
                    item.setAttribute("aria-pressed", String(side === value));
                });
                for (const [name, entries] of [["Units", drawing.UNITS], ["Control", drawing.CONTROLS]]) {
                    const row = group(name);
                    entries.forEach(([value, title]) => {
                        const item = button(row, "symbol-" + value, title, () => {
                            symbol = value;
                            palette.hidden = true;
                            panel.scrollTop = 0;
                            render();
                        });
                        item.insertAdjacentHTML("afterbegin", drawing.symbolIcon(value, side, options.threatRingStyle));
                        item.setAttribute("aria-pressed", String(symbol === value));
                    });
                }
            };
            buttons.symbol.addEventListener("click", drawPalette);
            button(bar, "close", "Close drawing tools", () => setActive(false), "close");
            inspector = document.createElement("div");
            inspector.className = "briefing-annotation-inspector map-control-surface";
            panel.append(inspector);
            const field = document.createElement("label");
            labelInput = document.createElement("textarea");
            labelInput.setAttribute("aria-label", "Label");
            labelInput.title = "Label";
            labelInput.placeholder = "Label";
            labelInput.rows = 2;
            labelInput.maxLength = 2000;
            labelInput.dataset.annotation = "label";
            labelInput.addEventListener("change", () => changeProperty("label", labelInput.value));
            labelInput.addEventListener("input", () => {
                if (draft) { draft.label = labelInput.value; renderShapes(); }
            });
            field.append(labelInput);
            inspector.append(field);
            const sizeField = document.createElement("label");
            sizeInput = document.createElement("input");
            sizeInput.setAttribute("aria-label", "Size");
            sizeInput.title = "Size";
            sizeInput.type = "number";
            sizeInput.min = 10;
            sizeInput.max = 72;
            sizeInput.dataset.annotation = "size";
            sizeInput.addEventListener("change", () => {
                const value = Number(sizeInput.value);
                if (Number.isFinite(value) && value >= 10 && value <= 72) changeProperty("size", value);
                else render();
            });
            sizeField.append(sizeInput);
            inspector.append(sizeField);
            button(inspector, "cancel", "Cancel editing", () => cancel(), "close");
            button(inspector, "done", "Finish editing", finishEditing, "done");
            button(inspector, "delete", "Delete", remove, "delete");
            status = document.createElement("div");
            status.className = "briefing-annotation-status";
            status.setAttribute("role", "status");
            panel.append(status);
            root.addEventListener("pointerdown", (event) => event.stopPropagation());
            return root;
        };
        control.addTo(map);
        // The launcher stays fourth in the instrument stack. The toolbar is
        // positioned against the map itself, independent of that stack.
        container.append(root);

        function rotationPosition(feature, side) {
            const edge = map.latLngToContainerPoint(toMap(rectanglePoint(feature, 0, side * feature.b)));
            const center = map.latLngToContainerPoint(toMap(feature.center));
            const length = Math.hypot(edge.x - center.x, edge.y - center.y) || 1;
            return map.containerPointToLatLng([edge.x + (edge.x - center.x) * 24 / length,
                edge.y + (edge.y - center.y) * 24 / length]);
        }
        const pixel = (p) => map.latLngToContainerPoint(toMap(p));
        // The laser has its own canvas and never enters features or history.
        // Keep map coordinates so the fading trail follows zoom/pan correctly.
        function renderLaser(now = performance.now()) {
            const size = map.getSize(), ratio = global.devicePixelRatio || 1;
            L.DomUtil.setPosition(laserCanvas, map.containerPointToLayerPoint([0, 0]));
            const width = Math.ceil(size.x * ratio), height = Math.ceil(size.y * ratio);
            if (laserCanvas.width !== width || laserCanvas.height !== height) {
                laserCanvas.width = width;
                laserCanvas.height = height;
            }
            laserCanvas.style.width = size.x + "px";
            laserCanvas.style.height = size.y + "px";
            const ctx = laserCanvas.getContext("2d");
            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            ctx.clearRect(0, 0, width / ratio, height / ratio);
            drawing.drawLaser(ctx, laserTrail.map(({ latlng, time }) => ({
                point: latlng ? map.latLngToContainerPoint(latlng) : null, time,
            })), laserHead ? map.latLngToContainerPoint(laserHead) : null, now);
        }
        function animateLaser(now) {
            laserFrame = null;
            laserTrail = laserTrail.filter((sample) => now - sample.time < drawing.LASER_TTL);
            renderLaser(now);
            if (laserTrail.length) laserFrame = requestAnimationFrame(animateLaser);
        }
        function pointLaser(position) {
            const time = performance.now();
            if (laserHead && !laserTrail.length) laserTrail.push({ latlng: laserHead, time });
            laserHead = map.containerPointToLatLng(position);
            laserTrail.push({ latlng: laserHead, time });
            if (laserTrail.length > 512) laserTrail.shift();
            if (laserFrame === null) laserFrame = requestAnimationFrame(animateLaser);
        }
        function releaseLaser() {
            laserHead = null;
            // Break the trail between separate presses.
            if (laserTrail.length) laserTrail.push({ latlng: null, time: performance.now() });
        }
        function clearLaser() {
            laserHead = null;
            laserTrail = [];
            if (laserFrame !== null) cancelAnimationFrame(laserFrame);
            laserFrame = null;
            renderLaser();
        }
        function paintFeature(ctx, feature) {
            if (!feature.center && !feature.points?.length) return;
            let coords = points(feature).map(pixel);
            if (feature === draft && feature.kind === "line" && hover) coords = [...coords, pixel(hover)];
            drawing.draw(ctx, feature, coords, pixel(labelPoint(feature)), options.threatRingStyle,
                options.getThreatRingMode?.() || "filled");
        }
        function pick(position) {
            return [...features].reverse().find((feature) => !(feature.symbol === "ring" && options.getThreatRingMode?.() === "none")
                && drawing.hit(hitContext, feature,
                points(feature).map(pixel), pixel(labelPoint(feature)), position));
        }
        function renderShapes() {
            shapes.clearLayers();
            const size = map.getSize(), ratio = global.devicePixelRatio || 1;
            L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
            canvas.width = Math.ceil(size.x * ratio);
            canvas.height = Math.ceil(size.y * ratio);
            canvas.style.width = size.x + "px";
            canvas.style.height = size.y + "px";
            const ctx = canvas.getContext("2d");
            ctx.scale(ratio, ratio);
            const entries = draft ? [...features, draft] : features;
            entries.forEach((feature) => paintFeature(ctx, feature));
            const feature = selectedFeature();
            if (active && feature?.kind === "rectangle") {
                for (const side of [1, -1]) {
                    L.polyline([toMap(rectanglePoint(feature, 0, side * feature.b)), rotationPosition(feature, side)],
                        { pane: handlePane, color: feature.color, weight: 1, interactive: false,
                            className: "briefing-annotation-guide" }).addTo(shapes);
                }
                L.tooltip({ permanent: true, direction: "right", offset: [12, 0], pane: handlePane,
                    className: "briefing-annotation-label briefing-annotation-guide" }).setLatLng(rotationPosition(feature, 1))
                    .setContent(String(Math.round(feature.rotation % 360)).padStart(3, "0") + "°").addTo(shapes);
            }
            renderLaser();
        }
        function renderHandles() {
            handles.clearLayers();
            handleUpdates = [];
            const feature = selectedFeature();
            if (!active || !feature || gesture || (mode && !draft)) return;
            const handle = (kind, position, update, onStart) => {
                const marker = L.marker(position(), { pane: handlePane, draggable: true,
                    keyboard: false, bubblingMouseEvents: false,
                    icon: L.divIcon({ className: "briefing-annotation-handle " + kind,
                        html: "<i></i>", iconSize: [20, 20], iconAnchor: [10, 10] }) }).addTo(handles);
                marker.on("dragstart", () => {
                    dragging = true;
                    dragBefore = clone(features);
                    onStart?.();
                });
                marker.on("drag", () => {
                    const coord = fromMap(marker.getLatLng());
                    if (!coord || !coord.every(Number.isFinite)) return;
                    update(coord);
                    renderShapes();
                    handleUpdates.forEach((item) => {
                        if (item.marker !== marker) item.marker.setLatLng(item.position());
                    });
                });
                marker.on("dragend", () => {
                    dragging = false;
                    if (!draft && !validFeature(feature, options.extent)) {
                        features = dragBefore;
                        message("Outside theater");
                        render();
                    } else if (draft) render();
                    else changed(dragBefore);
                    dragBefore = null;
                });
                handleUpdates.push({ marker, position });
                return marker;
            };
            if (feature.kind !== "rectangle") {
                if (!["pen", "marker"].includes(feature.kind)) {
                    feature.points.forEach((p, index) => {
                        let origin;
                        handle("vertex", () => toMap(feature.points[index]), (coord) => {
                            if (index === 0 && (feature.kind === "circle" || feature.symbol === "ring")) {
                                feature.points = shiftFeature(origin, coord.map((n, i) => n - origin.points[0][i])).points;
                            } else feature.points[index] = coord;
                        }, () => { origin = clone(feature); });
                    });
                }
                if (feature.points.length > 1 && !["circle"].includes(feature.kind) && feature.symbol !== "ring") {
                    let origin, anchor;
                    handle("center", () => toMap(labelPoint(feature)), (coord) => {
                        feature.points = shiftFeature(origin, coord.map((n, i) => n - anchor[i])).points;
                    }, () => { origin = clone(feature); anchor = labelPoint(feature); });
                }
                return;
            }
            corners(feature).forEach((p, index) => {
                let opposite;
                handle("corner", () => toMap(corners(feature)[index]),
                    (coord) => resizeRectangle(feature, index, coord, opposite),
                    () => { opposite = corners(feature)[(index + 2) % 4]; });
            });
            handle("center", () => toMap(feature.center), (coord) => { feature.center = coord; });
            for (const side of [1, -1]) {
                handle("rotate", () => rotationPosition(feature, side), (coord) => {
                    feature.rotation = (Math.atan2(coord[0] - feature.center[0], coord[1] - feature.center[1])
                        * 180 / Math.PI + (side < 0 ? 180 : 0) + 360) % 360;
                });
            }
        }
        function render() {
            if (!root) return;
            root.hidden = !active;
            root.style.setProperty("--annotation-height", Math.max(80, map.getSize().y - 100) + "px");
            buttons.toggle.setAttribute("aria-pressed", String(active));
            for (const kind of ["pan", "select", "laser", "erase", ...KINDS]) {
                buttons[kind].setAttribute("aria-pressed", String(kind === "select" ? !mode : mode === kind));
            }
            buttons.undo.disabled = !past.length;
            buttons.redo.disabled = !future.length;
            buttons.clear.disabled = !features.length;
            const feature = selectedFeature();
            buttons.done.hidden = !feature;
            buttons.done.disabled = !!draft && draft.kind === "line" && draft.points.length < 2;
            inspector.hidden = !feature;
            if (feature) {
                if (document.activeElement !== labelInput) labelInput.value = feature.label;
                sizeInput.value = feature.size || 20;
            }
            sizeInput.parentElement.hidden = feature?.kind !== "text";
            colorInput.value = feature?.color || color;
            drawing.COLORS.forEach((value) => buttons["color-" + value].setAttribute("aria-pressed", String(value === colorInput.value)));
            [2, 4, 7].forEach((value) => buttons["width-" + value].setAttribute("aria-pressed", String(value === (feature?.width || width))));
            if (mode !== "symbol") palette.hidden = true;
            buttons.delete.hidden = !!draft;
            container.classList.toggle("briefing-annotation-adding", !!mode && mode !== "pan");
            container.classList.toggle("briefing-annotation-drawing", active && mode !== "pan");
            navigation();
            renderShapes();
            renderHandles();
        }
        function click(event) {
            if (!active || dragging) return;
            if (event.originalEvent && performance.now() < suppressClickUntil) return;
            if (mode === "pan" || mode === "laser") return;
            const coord = fromMap(event.latlng);
            if (!mode || mode === "erase") {
                const feature = pick(map.latLngToContainerPoint(event.latlng));
                if (feature) select(feature);
                else { selected = null; render(); }
                return;
            }
            if (!inBounds(coord)) { message("Outside theater"); return; }
            message();
            if (mode === "point") {
                draft = { ...makeFeature("point"), points: [coord] };
                finish();
            } else if (mode === "text" && !draft) {
                draft = { ...makeFeature("text"), points: [coord], size: 20 };
                render();
                labelInput.focus();
            } else if (mode === "symbol" && !PAIRED_SYMBOLS.includes(symbol)) {
                draft = { ...makeFeature("symbol"), symbol, side, points: [coord] };
                finish();
            } else if (mode === "line") {
                draft.points.push(coord);
                hover = null;
                render();
            } else if (mode === "rectangle" && !draft) {
                const margin = Math.min(coord[0], coord[1], options.extent - coord[0], options.extent - coord[1]);
                if (margin < 20) { message("Outside theater"); return; }
                draft = { ...makeFeature("rectangle"), center: coord,
                    a: Math.min(10 * NM, margin / 2), b: Math.min(6 * NM, margin / 2), rotation: 0 };
                render();
            }
        }
        function mousemove(event) {
            if (mode !== "line" || !draft?.points.length) return;
            const coord = fromMap(event.latlng);
            hover = inBounds(coord) ? coord : null;
            renderShapes();
        }
        const isControl = (event) => event.target.closest?.(".leaflet-control, .briefing-annotation-handle");
        const eventPixel = (event) => map.mouseEventToContainerPoint(event);
        const eventCoord = (event) => fromMap(map.containerPointToLatLng(eventPixel(event)));
        let spacePan = false;
        function abortGesture() {
            if (!gesture) return;
            if (gesture.kind === "laser") clearLaser();
            if (gesture.before) features = gesture.before;
            const id = gesture.id;
            gesture = null;
            dragging = false;
            draft = null;
            if (container.hasPointerCapture?.(id)) container.releasePointerCapture(id);
        }
        function pointerdown(event) {
            if (!active || gesture || isControl(event) || mode === "pan") return;
            const position = eventPixel(event), coord = eventCoord(event);
            const pan = event.button === 1 || (event.button === 0 && spacePan);
            if (!pan && (event.button !== 0 || (mode !== "laser" && !inBounds(coord)))) return;
            const feature = !mode ? pick(position) : null;
            const draw = ["laser", "pen", "marker", "arrow", "circle", "rectangle", "line"].includes(mode)
                || (mode === "symbol" && PAIRED_SYMBOLS.includes(symbol));
            if (!pan && !feature && mode !== "erase" && !draw) return;
            if (!pan && draft && (mode !== "line" || draft.points.length)) return;
            gesture = { id: event.pointerId, before: mode === "laser" ? null : clone(features), start: coord, position,
                last: position, kind: pan ? "pan" : feature ? "move" : mode,
                original: feature ? clone(feature) : null, moved: false };
            dragging = true;
            if (feature) selected = feature.id;
            if (mode === "erase" && !pan) eraseAt(position);
            if (gesture.kind === "laser") pointLaser(position);
            // A synthetic test event has no active pointer to capture.
            try { container.setPointerCapture(event.pointerId); } catch (_) { /* no active pointer */ }
            if (mode !== "line" && mode !== "rectangle" || pan || feature) event.preventDefault();
            render();
        }
        function eraseAt(position) {
            const feature = pick(position);
            if (feature) features = features.filter((f) => f.id !== feature.id);
        }
        function pointermove(event) {
            if (!gesture || event.pointerId !== gesture.id) return;
            const position = eventPixel(event), coord = eventCoord(event);
            const g = gesture;
            if (g.kind === "laser") {
                pointLaser(position);
                event.preventDefault();
                return;
            }
            if (g.kind === "pan") {
                map.panBy([g.last.x - position.x, g.last.y - position.y], { animate: false });
                g.last = position;
                g.moved = true;
                event.preventDefault();
                return;
            }
            if (!coord?.every(Number.isFinite)) return;
            if (!g.moved && position.distanceTo(g.position) < 3) return;
            g.moved = true;
            event.preventDefault();
            if (g.kind === "move") {
                const feature = features.find((f) => f.id === g.original.id);
                Object.assign(feature, shiftFeature(g.original, coord.map((n, i) => n - g.start[i])));
            } else if (g.kind === "erase") eraseAt(position);
            else if (g.kind === "rectangle") {
                draft = { ...makeFeature("rectangle"), center: g.start.map((n, i) => (n + coord[i]) / 2),
                    a: Math.max(10, Math.abs(g.start[0] - coord[0]) / 2),
                    b: Math.max(10, Math.abs(g.start[1] - coord[1]) / 2), rotation: 0 };
            } else if (["pen", "marker"].includes(g.kind)) {
                if (!draft) draft = { ...makeFeature(g.kind), points: [g.start, coord] };
                else if (position.distanceTo(g.last) >= 2 && draft.points.length < 4000) draft.points.push(coord);
            } else {
                if (!draft || g.kind === "line") draft = { ...makeFeature(g.kind), points: [g.start, coord] };
                else draft.points[1] = coord;
                if (g.kind === "symbol") Object.assign(draft, { symbol, side });
            }
            g.last = position;
            renderShapes();
        }
        function pointerup(event) {
            if (!gesture || event.pointerId !== gesture.id) return;
            pointermove(event);
            const g = gesture;
            gesture = null;
            dragging = false;
            if (container.hasPointerCapture?.(g.id)) container.releasePointerCapture(g.id);
            if (g.kind === "laser") {
                releaseLaser();
                suppressClickUntil = performance.now() + 350;
                render();
                return;
            }
            if (g.moved || g.kind === "erase" || g.kind === "move") suppressClickUntil = performance.now() + 350;
            if (g.kind === "move" || g.kind === "erase") {
                if (features.every((f) => validFeature(f, options.extent))) changed(g.before);
                else { features = g.before; message("Outside theater"); render(); }
            } else if (g.kind !== "pan" && g.moved) {
                if (validFeature(draft, options.extent)) {
                    finish();
                    if (["pen", "marker"].includes(g.kind)) { mode = g.kind; selected = null; }
                } else {
                    draft = null;
                    message("Outside theater");
                }
                if (mode === "line" && !draft) draft = { ...makeFeature("line"), points: [] };
                render();
            } else render();
        }
        function pointercancel(event) {
            if (!gesture || (event.pointerId !== undefined && event.pointerId !== gesture.id)) return;
            abortGesture();
            if (mode === "line") draft = { ...makeFeature("line"), points: [] };
            render();
        }
        function blockMapDrag(event) {
            if (active && mode !== "pan" && !isControl(event)) event.stopPropagation();
        }
        function contextmenu(event) {
            if (!active || event.target.closest?.(".leaflet-control")) return;
            event.preventDefault();
            event.stopPropagation();
            if (draft || selected || gesture || (mode && mode !== "pan")) {
                finishEditing();
                suppressClickUntil = performance.now() + 350;
            }
        }
        function keydown(event) {
            if (!active) return;
            const input = event.target.closest?.("input, textarea, select, [contenteditable]");
            if (input) {
                if (event.key === "Escape" && root.contains(input)) { event.preventDefault(); cancel(); input.blur(); }
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && input === labelInput) {
                    event.preventDefault(); finishEditing(); input.blur();
                }
                return;
            }
            if (event.code === "Space") { spacePan = true; event.preventDefault(); }
            if (dragging && event.key !== "Escape") return;
            if (event.key === "Escape") {
                event.preventDefault();
                if (mode || selected) cancel();
                else setActive(false);
            } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
                event.preventDefault();
                history(event.shiftKey);
            } else if (event.key === "Delete" || event.key === "Backspace") {
                event.preventDefault();
                remove();
            } else if (event.key === "Enter" && selectedFeature()) {
                event.preventDefault();
                finishEditing();
            }
        }
        function keyup(event) { if (event.code === "Space") spacePan = false; }
        function blur() { spacePan = false; pointercancel({}); clearLaser(); }
        function visibilityChanged() { if (document.hidden) blur(); }
        function zoom() { renderShapes(); if (!dragging) renderHandles(); }
        function resized() { render(); }
        map.on("click", click);
        map.on("mousemove", mousemove);
        map.on("move zoomend", zoom);
        map.on("resize", resized);
        document.addEventListener("keydown", keydown);
        document.addEventListener("keyup", keyup);
        document.addEventListener("visibilitychange", visibilityChanged);
        global.addEventListener("blur", blur);
        container.addEventListener("pointerdown", pointerdown, true);
        container.addEventListener("pointermove", pointermove, true);
        container.addEventListener("pointerup", pointerup, true);
        container.addEventListener("pointercancel", pointercancel, true);
        container.addEventListener("lostpointercapture", pointercancel, true);
        container.addEventListener("mousedown", blockMapDrag, true);
        container.addEventListener("contextmenu", contextmenu, true);
        render();

        return {
            snapshot, setActive, redraw: renderShapes,
            isActive: () => active,
            isBusy: () => dragging || !!draft || (!!mode && mode !== "pan")
                || (active && root.contains(document.activeElement) && document.activeElement.matches("input, textarea")),
            restore(data) {
                if (data?.version !== 1 || data.scope !== options.scope || !Array.isArray(data.features) || data.features.length > 3000) return false;
                const ids = new Set();
                if (!data.features.every((f) => {
                    if (!validFeature(f, options.extent) || ids.has(f.id)) return false;
                    ids.add(f.id);
                    return true;
                })) return false;
                abortGesture();
                features = clone(data.features);
                past = [];
                future = [];
                cancel();
                return true;
            },
            drawCanvas(ctx) {
                features.forEach((feature) => paintFeature(ctx, feature));
            },
            destroy() {
                setActive(false);
                map.off("click", click);
                map.off("mousemove", mousemove);
                map.off("move zoomend", zoom);
                map.off("resize", resized);
                document.removeEventListener("keydown", keydown);
                document.removeEventListener("keyup", keyup);
                document.removeEventListener("visibilitychange", visibilityChanged);
                global.removeEventListener("blur", blur);
                container.removeEventListener("pointerdown", pointerdown, true);
                container.removeEventListener("pointermove", pointermove, true);
                container.removeEventListener("pointerup", pointerup, true);
                container.removeEventListener("pointercancel", pointercancel, true);
                container.removeEventListener("lostpointercapture", pointercancel, true);
                container.removeEventListener("mousedown", blockMapDrag, true);
                container.removeEventListener("contextmenu", contextmenu, true);
                shapes.remove();
                handles.remove();
                canvas.remove();
                laserCanvas.remove();
                buttons.toggle.remove();
                control.remove();
                container.classList.remove("briefing-annotation-active", "briefing-annotation-adding", "briefing-annotation-drawing");
            },
        };
    }
    const api = { create, corners, resizeRectangle, validFeature, shiftFeature };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    else global.BriefingAnnotations = api;
})(typeof window === "undefined" ? globalThis : window);
