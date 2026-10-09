/* Layout placement is independent of the briefing's editable content. */
(function (global) {
    "use strict";

    function edit(state, action) {
        const next = {
            pages: state.pages.map((page) => [...page]),
            pageKeys: [...state.pageKeys],
            styleEdits: { ...state.styleEdits },
        };
        const pageIndex = next.pageKeys.indexOf(action.pageKey);
        if (action.type === "addPage") {
            if (!/^page\d+$/.test(action.key) || next.pageKeys.includes(action.key)) return state;
            const index = Math.max(0, Math.min(action.index, next.pages.length));
            next.pageKeys.splice(index, 0, action.key);
            next.pages.splice(index, 0, []);
        } else if (action.type === "remove") {
            next.pages = next.pages.map((page) => page.filter((id) => id !== action.section));
        } else if (pageIndex < 0) {
            return state;
        } else if (action.type === "shift") {
            const page = next.pages[pageIndex];
            const from = page.indexOf(action.section);
            const to = from + action.offset;
            if (from < 0 || ![-1, 1].includes(action.offset) || to < 0 || to >= page.length) return state;
            [page[from], page[to]] = [page[to], page[from]];
        } else if (action.type === "place") {
            if (action.anchor === action.section) return state;
            next.pages = next.pages.map((page) => page.filter((id) => id !== action.section));
            const page = next.pages[pageIndex];
            const anchor = page.indexOf(action.anchor);
            const index = anchor < 0 ? page.length : anchor + (action.after ? 1 : 0);
            page.splice(index, 0, action.section);
        } else if (action.type === "deletePage") {
            if (next.pages.length === 1) return state;
            next.pages.splice(pageIndex, 1);
            next.pageKeys.splice(pageIndex, 1);
            for (const name of ["font_size", "spacing"]) next.styleEdits[`${action.pageKey}_${name}`] = null;
        } else if (action.type === "style") {
            if (!["font_size", "spacing"].includes(action.name)) return state;
            if (action.value !== null) {
                if (action.name === "font_size" && (!Number.isFinite(Number(action.value)) || Number(action.value) < 6 || Number(action.value) > 32)) return state;
                if (action.name === "spacing" && !["normal", "compact"].includes(action.value)) return state;
            }
            next.styleEdits[`${action.pageKey}_${action.name}`] = action.value === null ? null : String(action.value);
        } else {
            return state;
        }
        return JSON.stringify(next) === JSON.stringify(state) ? state : next;
    }

    function attach(win, options) {
        const doc = win.document;
        const sections = new Map(Array.from(doc.querySelectorAll("[data-section]"), (el) => [el.dataset.section, el]));
        const pageNodes = new Map(Array.from(doc.querySelectorAll("[data-page-key]"), (el) => [el.dataset.pageKey, el]));
        let state, busy = false, popup = null, popupOwner = null;
        const css = doc.createElement("link");
        css.rel = "stylesheet";
        css.href = "/templates/layout_editor.css";
        doc.head.appendChild(css);

        function node(tag, text, className) {
            const el = doc.createElement(tag);
            if (text !== undefined) el.textContent = text;
            if (className) el.className = className;
            return el;
        }

        function closeMenu(restoreFocus = false) {
            popup?.remove();
            popup = null;
            if (restoreFocus && popupOwner?.isConnected) popupOwner.focus({ preventScroll: true });
            popupOwner = null;
        }

        function dispatch(action) {
            closeMenu();
            if (!busy) options.change(action);
        }

        function button(label, title, callback, disabled = false) {
            const el = node("button", label);
            el.type = "button";
            el.title = title;
            el.setAttribute("aria-label", title);
            el.disabled = disabled || busy;
            el.dataset.unavailable = disabled ? "1" : "0";
            el.addEventListener("click", (event) => {
                event.stopPropagation();
                if (!busy) callback(event);
            });
            return el;
        }

        function labeledControl(parent, label, input) {
            const wrapper = node("label", undefined, "layout-editor-field");
            wrapper.append(node("span", label), input);
            parent.append(wrapper);
        }

        function sectionPicker(parent, label, pageKey, anchor, after) {
            const select = node("select");
            select.append(new win.Option("—", ""));
            const available = node("optgroup");
            available.label = "Available";
            const placed = node("optgroup");
            placed.label = "Placed";
            Object.keys(options.labels).sort((a, b) => options.labels[a].localeCompare(options.labels[b])).forEach((id) => {
                if (id === anchor) return;
                const index = state.pages.findIndex((page) => page.includes(id));
                const label = options.labels[id] + (index < 0 ? "" : ` — Page ${index + 1}`);
                (index < 0 ? available : placed).append(new win.Option(label, id));
            });
            select.append(available, placed);
            select.addEventListener("change", () => {
                if (select.value) dispatch({ type: "place", section: select.value, pageKey, anchor, after });
            });
            labeledControl(parent, label, select);
        }

        function showMenu(pageKey, section, x, y, owner) {
            if (busy) return;
            closeMenu();
            const index = state.pageKeys.indexOf(pageKey);
            if (index < 0) return;
            popupOwner = owner;
            popup = node("div", undefined, "layout-editor-ui layout-editor-menu");
            popup.setAttribute("role", "dialog");
            popup.setAttribute("aria-label", "Layout");
            popup.append(node("strong", section ? options.labels[section] || section : `Page ${index + 1}`));
            if (section) {
                const position = state.pages[index].indexOf(section);
                const row = node("div", undefined, "layout-editor-actions");
                row.append(
                    button("↑", "Move up", () => dispatch({ type: "shift", section, pageKey, offset: -1 }), position <= 0),
                    button("↓", "Move down", () => dispatch({ type: "shift", section, pageKey, offset: 1 }), position === state.pages[index].length - 1),
                    button("Remove", "Remove section", () => dispatch({ type: "remove", section })),
                );
                popup.append(row);
                const select = node("select");
                select.append(new win.Option("—", ""));
                state.pageKeys.forEach((key, i) => {
                    if (key !== pageKey) select.append(new win.Option(`Page ${i + 1}`, key));
                });
                select.disabled = state.pages.length === 1;
                select.addEventListener("change", () => {
                    if (select.value) dispatch({ type: "place", section, pageKey: select.value });
                });
                labeledControl(popup, "Move to page", select);
                sectionPicker(popup, "Insert before", pageKey, section, false);
                sectionPicker(popup, "Insert after", pageKey, section, true);
                popup.append(node("hr"));
            } else {
                sectionPicker(popup, "Add section", pageKey);
            }
            const style = options.pageStyle(index);
            const font = node("input");
            font.type = "number";
            font.min = "6";
            font.max = "32";
            font.step = "any";
            font.value = style.font_size;
            font.addEventListener("change", () => {
                if (font.value && font.reportValidity()) dispatch({ type: "style", pageKey, name: "font_size", value: Number(font.value) });
            });
            labeledControl(popup, "Font (px)", font);
            const spacing = node("select");
            spacing.append(new win.Option("Normal", "normal"), new win.Option("Compact", "compact"));
            spacing.value = style.spacing;
            spacing.addEventListener("change", () => dispatch({ type: "style", pageKey, name: "spacing", value: spacing.value }));
            labeledControl(popup, "Spacing", spacing);
            const actions = node("div", undefined, "layout-editor-actions");
            actions.append(
                button("+ Before", "Add page before", () => dispatch({ type: "addPage", index })),
                button("+ After", "Add page after", () => dispatch({ type: "addPage", index: index + 1 })),
                button("Delete page", "Delete page", () => dispatch({ type: "deletePage", pageKey }), state.pages.length === 1),
            );
            popup.append(actions);
            popup.addEventListener("contextmenu", (event) => event.preventDefault());
            popup.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    event.preventDefault();
                    closeMenu(true);
                } else if (event.key === "Tab") {
                    const controls = Array.from(popup.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled)"));
                    const first = controls[0], last = controls.at(-1);
                    if (event.shiftKey && doc.activeElement === first) { event.preventDefault(); last.focus(); }
                    else if (!event.shiftKey && doc.activeElement === last) { event.preventDefault(); first.focus(); }
                }
            });
            doc.body.append(popup);
            const rect = popup.getBoundingClientRect();
            popup.style.left = `${Math.max(4, Math.min(x, win.innerWidth - rect.width - 4))}px`;
            popup.style.top = `${Math.max(4, Math.min(y, win.innerHeight - rect.height - 4))}px`;
            popup.querySelector("button:not(:disabled), select:not(:disabled), input")?.focus();
        }

        function menuButton(pageKey, section) {
            const el = button("⋯", section ? "Section menu" : "Page menu", () => {
                const rect = el.getBoundingClientRect();
                showMenu(pageKey, section, rect.left, rect.bottom, el);
            });
            el.setAttribute("aria-haspopup", "dialog");
            return el;
        }

        function render(next) {
            if (!canRender(next)) return false;
            closeMenu();
            state = next;
            // Park removed sections outside the document, retaining their DOM and handlers.
            const visible = new Set(state.pages.flat());
            sections.forEach((el, id) => { if (!visible.has(id)) el.remove(); });
            state.pages.forEach((parts, index) => {
                const key = state.pageKeys[index];
                let page = pageNodes.get(key);
                if (!page) {
                    page = node("div");
                    page.dataset.pageKey = key;
                    pageNodes.set(key, page);
                }
                if (page.nextElementSibling?.tagName === "BR") page.nextElementSibling.remove();
                page.id = `page_${index + 1}`;
                page.classList.toggle("page", index < state.pages.length - 1);
                const style = options.pageStyle(index);
                page.style.setProperty("--brief-font-size", `${style.font_size}px`);
                page.style.setProperty("--brief-heading-font-size", `${style.font_size * 0.95}px`);
                page.style.setProperty("--brief-cell-padding", style.spacing === "compact" ? "1px 2px" : "3px");
                page.style.setProperty("--brief-row-height", style.spacing === "compact" ? "1.3em" : "1.7em");
                page.querySelectorAll(".layout-editor-ui").forEach((el) => el.remove());
                let heading = page.querySelector("[data-page-header]");
                if (!heading) {
                    heading = node("div", undefined, "header brief-page-header");
                    heading.setAttribute("data-page-header", "");
                    const label = node("span");
                    label.setAttribute("data-page-label", "");
                    heading.append(label);
                    page.prepend(heading);
                }
                heading.querySelector("[data-page-label]").textContent = `Page ${index + 1}`;
                const pageControls = node("span", undefined, "layout-editor-ui layout-editor-page-controls");
                pageControls.append(menuButton(key));
                heading.append(pageControls);
                parts.forEach((id, position) => {
                    const el = sections.get(id);
                    el.querySelectorAll(".layout-editor-ui").forEach((ui) => ui.remove());
                    let header = el.querySelector('[id$="_header"]');
                    if (!header) {
                        header = node("div", options.labels[id] || id, "layout-editor-ui layout-editor-section-heading");
                        el.prepend(header);
                    }
                    const controls = node("span", undefined, "layout-editor-ui layout-editor-section-controls");
                    controls.addEventListener("click", (event) => event.stopPropagation());
                    controls.append(
                        button("↑", "Move up", () => dispatch({ type: "shift", section: id, pageKey: key, offset: -1 }), position === 0),
                        button("↓", "Move down", () => dispatch({ type: "shift", section: id, pageKey: key, offset: 1 }), position === parts.length - 1),
                        button("×", "Remove section", () => dispatch({ type: "remove", section: id })),
                        menuButton(key, id),
                    );
                    header.append(controls);
                    page.append(el);
                });
                doc.body.append(page, node("br"));
            });
            pageNodes.forEach((el, key) => {
                if (!state.pageKeys.includes(key)) {
                    if (el.nextElementSibling?.tagName === "BR") el.nextElementSibling.remove();
                    el.remove();
                }
            });
            return true;
        }

        function canRender(next) {
            return next.pages.every((page) => page.every((id) => sections.has(id)));
        }

        doc.addEventListener("contextmenu", (event) => {
            if (event.target.closest(".layout-editor-menu")) return;
            const page = event.target.closest("[data-page-key]");
            if (!page || event.target.closest('[contenteditable="true"], input, select, textarea, .leaflet-container')) return;
            event.preventDefault();
            const section = event.target.closest("[data-section]");
            const owner = section?.querySelector('.layout-editor-section-controls button[aria-haspopup]') || page.querySelector('[data-page-header] button');
            const rect = owner.getBoundingClientRect();
            showMenu(page.dataset.pageKey, section?.dataset.section, event.clientX || rect.left, event.clientY || rect.bottom, owner);
        });
        doc.addEventListener("pointerdown", (event) => { if (popup && !popup.contains(event.target)) closeMenu(); });
        win.addEventListener("blur", () => closeMenu());
        return {
            render, canRender,
            setBusy(value) {
                busy = value;
                if (busy) closeMenu();
                doc.querySelectorAll(".layout-editor-ui button").forEach((el) => {
                    el.disabled = busy || el.dataset.unavailable === "1";
                });
            },
        };
    }

    const api = { edit, attach };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    else global.LayoutEditor = api;
})(typeof window === "undefined" ? globalThis : window);
