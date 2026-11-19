/* Expand the live Leaflet map without duplicating map or annotation state. */
(function (global) {
    "use strict";
    function attach(map, instruments) {
        const container = map.getContainer();
        const dialog = document.createElement("dialog");
        dialog.id = "briefingMapExpandedDialog";
        dialog.className = "map-expanded-dialog leaflet-container";
        dialog.setAttribute("aria-label", "Expanded map");
        const header = document.createElement("div");
        header.className = "map-expanded-header";
        const title = document.createElement("span");
        title.textContent = "Map";
        const dismiss = MapControls.button("Close expanded map", "close", close);
        dismiss.id = "mapCollapseButton";
        header.append(title, dismiss);
        dialog.append(header);
        document.body.append(dialog);
        const button = MapControls.button("Expand map", "expand", () => dialog.open ? close() : open());
        button.id = "mapExpandButton";
        button.setAttribute("aria-controls", dialog.id);
        button.setAttribute("aria-expanded", "false");
        instruments.append(button);
        let placeholder = null, restoreHost = null, scroll = null;
        const resize = () => map.invalidateSize({ animate: false });
        const observer = new ResizeObserver(resize);
        observer.observe(container);

        function raiseHostFrame() {
            const frame = global.frameElement;
            if (!frame) return null;
            const doc = frame.ownerDocument;
            const inert = [];
            // Keep the path to the preview interactive and disable its siblings.
            // Unlike moving the iframe into a dialog, this preserves its document.
            for (let node = frame; node.parentElement; node = node.parentElement) {
                for (const sibling of node.parentElement.children) {
                    if (sibling !== node) {
                        inert.push([sibling, sibling.getAttribute("inert")]);
                        sibling.setAttribute("inert", "");
                    }
                }
                if (node.parentElement === doc.body) break;
            }
            const overflow = doc.documentElement.style.overflow;
            doc.documentElement.style.overflow = "hidden";
            const backdrop = doc.createElement("div");
            backdrop.className = "map-expanded-backdrop";
            backdrop.addEventListener("click", close);
            doc.body.append(backdrop);
            frame.classList.add("map-expanded-host-frame");
            dialog.classList.add("in-frame");
            return () => {
                frame.classList.remove("map-expanded-host-frame");
                doc.documentElement.style.overflow = overflow;
                for (const [element, value] of inert) {
                    if (value === null) element.removeAttribute("inert");
                    else element.setAttribute("inert", value);
                }
                backdrop.remove();
                dialog.classList.remove("in-frame");
            };
        }
        function updateButton(expanded) {
            const label = expanded ? "Collapse map" : "Expand map";
            button.title = label;
            button.setAttribute("aria-label", label);
            button.setAttribute("aria-expanded", String(expanded));
            MapControls.setIcon(button, expanded ? "collapse" : "expand");
        }
        function open() {
            if (placeholder) return;
            scroll = [global.scrollX, global.scrollY];
            placeholder = document.createElement("div");
            placeholder.style.height = container.getBoundingClientRect().height + "px";
            placeholder.setAttribute("aria-hidden", "true");
            container.before(placeholder);
            restoreHost = raiseHostFrame();
            dialog.append(container);
            updateButton(true);
            if (global.InterfaceUI) global.InterfaceUI.openDialog(dialog, { focus: dismiss });
            else { dialog.showModal(); dismiss.focus(); }
            resize();
        }
        function restore() {
            if (!placeholder) return;
            placeholder.replaceWith(container);
            placeholder = null;
            restoreHost?.();
            restoreHost = null;
            updateButton(false);
            resize();
            global.scrollTo(...scroll);
            button.focus({ preventScroll: true });
        }
        function close() {
            if (dialog.open) dialog.close();
            // Synchronous restoration also puts the map back before printing.
            restore();
        }
        dialog.addEventListener("close", restore);
        dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
        global.addEventListener("beforeprint", close);
        global.addEventListener("pagehide", close);
        map.on("unload", () => {
            close();
            observer.disconnect();
            global.removeEventListener("beforeprint", close);
            global.removeEventListener("pagehide", close);
            button.remove();
            dialog.remove();
        });
        return { open, close, isOpen: () => dialog.open };
    }
    global.MapExpansion = { attach };
})(window);
