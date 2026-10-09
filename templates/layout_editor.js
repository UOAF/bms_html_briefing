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
        let submenu = null, submenuOwner = null, submenuId = 0;
        let menuWidth = 0, menuHeight = 0;
        const submenuOpeners = new WeakMap();
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
            closeSubmenu();
            popup?.remove();
            popup = null;
            if (restoreFocus && popupOwner?.isConnected) popupOwner.focus({ preventScroll: true });
            popupOwner = null;
        }

        function closeSubmenu(restoreFocus = false) {
            const owner = submenuOwner;
            submenu?.remove();
            submenu = null;
            submenuOwner = null;
            owner?.setAttribute("aria-expanded", "false");
            owner?.removeAttribute("aria-controls");
            if (restoreFocus && owner?.isConnected) owner.focus({ preventScroll: true });
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

        function menuItem(parent, label, callback, disabled = false) {
            const el = button(label, label, callback, disabled);
            el.className = "layout-editor-item";
            el.setAttribute("role", "menuitem");
            el.tabIndex = -1;
            const leaveOtherSubmenu = () => {
                if (parent === popup && submenuOwner !== el) closeSubmenu();
            };
            el.addEventListener("pointerenter", leaveOtherSubmenu);
            el.addEventListener("focus", leaveOtherSubmenu);
            parent.append(el);
            return el;
        }

        function menuControls(panel) {
            return panel ? Array.from(panel.querySelectorAll("button:not(:disabled)")) : [];
        }

        function menuKeydown(event) {
            const inSubmenu = submenu?.contains(event.target);
            if (event.key === "Escape" || (event.key === "ArrowLeft" && inSubmenu)) {
                event.preventDefault();
                if (submenu) closeSubmenu(true);
                else closeMenu(true);
            } else if (event.key === "ArrowRight" && submenuOpeners.has(event.target)) {
                event.preventDefault();
                submenuOpeners.get(event.target)(true);
            } else if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                const controls = menuControls(inSubmenu ? submenu : popup);
                const index = controls.indexOf(doc.activeElement);
                const next = event.key === "Home" ? 0 : event.key === "End" ? controls.length - 1
                    : (index + (event.key === "ArrowUp" ? -1 : 1) + controls.length) % controls.length;
                controls[next]?.focus();
            } else if (event.key === "Tab") {
                closeMenu(true);
            }
        }

        function submenuItem(parent, label, fill, disabled = false) {
            const el = menuItem(parent, label, () => open(true), disabled);
            const arrow = node("span", "›", "layout-editor-submenu-arrow");
            arrow.setAttribute("aria-hidden", "true");
            el.append(arrow);
            el.setAttribute("aria-haspopup", "menu");
            el.setAttribute("aria-expanded", "false");
            function open(focus = false) {
                if (el.disabled) return;
                if (submenuOwner !== el) {
                    closeSubmenu();
                    submenuOwner = el;
                    submenu = node("div", undefined, "layout-editor-ui layout-editor-menu layout-editor-submenu");
                    submenu.id = `layout-submenu-${++submenuId}`;
                    submenu.setAttribute("role", "menu");
                    submenu.setAttribute("aria-label", label);
                    el.setAttribute("aria-expanded", "true");
                    el.setAttribute("aria-controls", submenu.id);
                    fill(submenu);
                    submenu.addEventListener("keydown", menuKeydown);
                    doc.body.append(submenu);
                    const parentRect = popup.getBoundingClientRect();
                    const rect = submenu.getBoundingClientRect();
                    const right = parentRect.right - 2;
                    const x = right + rect.width <= win.innerWidth - 4 ? right : parentRect.left - rect.width + 2;
                    submenu.style.left = `${Math.max(4, Math.min(x, win.innerWidth - rect.width - 4))}px`;
                    submenu.style.top = `${Math.max(4, Math.min(el.getBoundingClientRect().top - 4, win.innerHeight - rect.height - 4))}px`;
                }
                if (focus) menuControls(submenu)[0]?.focus();
            }
            submenuOpeners.set(el, open);
            el.addEventListener("pointerenter", (event) => { if (event.pointerType !== "touch") open(); });
            return el;
        }

        function styleChoices(parent, label, pageKey, name, current, choices) {
            submenuItem(parent, label, (list) => {
                for (const [value, title] of choices) {
                    const item = menuItem(list, title, () => dispatch({ type: "style", pageKey, name, value }));
                    item.value = value;
                    item.setAttribute("role", "menuitemradio");
                    item.setAttribute("aria-checked", String(String(current) === String(value)));
                    if (String(current) === String(value)) {
                        const check = node("span", "✓");
                        check.setAttribute("aria-hidden", "true");
                        item.append(check);
                    }
                }
            });
        }

        function sectionPicker(parent, label, pageKey, anchor, after) {
            submenuItem(parent, label, (list) => {
                const entries = Object.keys(options.labels).filter((id) => id !== anchor)
                    .sort((a, b) => options.labels[a].localeCompare(options.labels[b]))
                    .map((id) => ({ id, index: state.pages.findIndex((page) => page.includes(id)) }));
                for (const [heading, placed] of [["Available", false], ["Placed", true]]) {
                    const group = entries.filter((entry) => (entry.index >= 0) === placed);
                    if (!group.length) continue;
                    list.append(node("div", heading, "layout-editor-group-label"));
                    group.forEach(({ id, index }) => {
                        const label = options.labels[id] + (placed ? ` — Page ${index + 1}` : "");
                        const item = menuItem(list, label, () => dispatch({ type: "place", section: id, pageKey, anchor, after }));
                        item.value = id;
                    });
                }
            });
        }

        function showMenu(pageKey, section, x, y, owner) {
            if (busy) return;
            closeMenu();
            const index = state.pageKeys.indexOf(pageKey);
            if (index < 0) return;
            menuWidth = win.innerWidth;
            menuHeight = win.innerHeight;
            popupOwner = owner;
            popup = node("div", undefined, "layout-editor-ui layout-editor-menu");
            popup.setAttribute("role", "menu");
            popup.setAttribute("aria-label", "Layout");
            popup.append(node("strong", section ? options.labels[section] || section : `Page ${index + 1}`));
            if (section) {
                submenuItem(popup, "Move to page", (list) => {
                    state.pageKeys.forEach((key, i) => {
                        if (key === pageKey) return;
                        const item = menuItem(list, `Page ${i + 1}`, () => dispatch({ type: "place", section, pageKey: key }));
                        item.value = key;
                    });
                }, state.pages.length === 1);
                sectionPicker(popup, "Insert before", pageKey, section, false);
                sectionPicker(popup, "Insert after", pageKey, section, true);
                popup.append(node("strong", `Page ${index + 1}`));
            } else {
                sectionPicker(popup, "Add section", pageKey);
            }
            const style = options.pageStyle(index);
            styleChoices(popup, "Font size", pageKey, "font_size", style.font_size,
                [13, 14, 15, 16, 17, 18].map((value) => [value, `${value} px`]));
            styleChoices(popup, "Spacing", pageKey, "spacing", style.spacing,
                [["normal", "Normal"], ["compact", "Compact"]]);
            popup.append(node("hr"));
            menuItem(popup, "Add page before", () => dispatch({ type: "addPage", index }));
            menuItem(popup, "Add page after", () => dispatch({ type: "addPage", index: index + 1 }));
            menuItem(popup, "Delete page", () => dispatch({ type: "deletePage", pageKey }), state.pages.length === 1);
            popup.append(node("hr"));
            menuItem(popup, "Save briefing layout", () => { closeMenu(); options.save(); }).title = "Save briefing layout to config.ini";
            popup.addEventListener("keydown", menuKeydown);
            popup.addEventListener("scroll", () => closeSubmenu());
            // Measure the submenu's CSS width to show its opening direction.
            const submenuProbe = node("div", undefined, "layout-editor-ui layout-editor-menu layout-editor-submenu");
            submenuProbe.style.visibility = "hidden";
            doc.body.append(popup, submenuProbe);
            const submenuWidth = submenuProbe.getBoundingClientRect().width;
            submenuProbe.remove();
            const rect = popup.getBoundingClientRect();
            popup.style.left = `${Math.max(4, Math.min(x, win.innerWidth - rect.width - 4))}px`;
            popup.style.top = `${Math.max(4, Math.min(y, win.innerHeight - rect.height - 4))}px`;
            const opensRight = popup.getBoundingClientRect().right - 2 + submenuWidth <= win.innerWidth - 4;
            popup.querySelectorAll(".layout-editor-submenu-arrow").forEach((arrow) => {
                arrow.textContent = opensRight ? "›" : "‹";
            });
            menuControls(popup)[0]?.focus({ preventScroll: true });
        }

        function menuButton(pageKey, section) {
            const el = button("⋯", section ? "Section menu" : "Page menu", () => {
                const rect = el.getBoundingClientRect();
                showMenu(pageKey, section, rect.left, rect.bottom, el);
            });
            el.setAttribute("aria-haspopup", "menu");
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

        doc.addEventListener("pointerdown", (event) => {
            if (popup && !popup.contains(event.target) && !submenu?.contains(event.target)) closeMenu();
        });
        win.addEventListener("blur", () => closeMenu());
        win.addEventListener("resize", () => {
            if (win.innerWidth !== menuWidth || win.innerHeight !== menuHeight) closeMenu(true);
        });
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
