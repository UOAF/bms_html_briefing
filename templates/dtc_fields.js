/* Shared raw DTC values. Templates bind with data-dtc-field="SECTION:Field". */
(function (global) {
    "use strict";

    function numeric(value) {
        const text = String(value).trim();
        if (text.length > 128 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)
                || !Number.isFinite(Number(text)) || Math.abs(Number(text)) > Number.MAX_SAFE_INTEGER) {
            throw new Error("Enter a valid number.");
        }
        if (Number(text) === 0) return "0";
        const parts = text.replace(/^\+/, "").split(".");
        parts[0] = parts[0].replace(/^(-?)0+(?=\d)/, "$1");
        if (parts[0] === "" || parts[0] === "-") parts[0] += "0";
        const fraction = (parts[1] || "").replace(/0+$/, "");
        return parts[0] + (fraction ? "." + fraction : "");
    }

    function format(meta, raw) {
        if (meta.options) return meta.options.find((option) => option.value === numeric(raw))?.label || String(raw);
        const value = (Number(raw) + meta.displayOffset) / meta.scale;
        return meta.decimals == null ? String(value) : value.toLocaleString("en-US", {
            useGrouping: false,
            minimumFractionDigits: meta.decimals,
            maximumFractionDigits: meta.decimals,
        });
    }

    function parse(meta, display) {
        const text = String(display).trim().replace(/^MODE:\s*/i, "");
        if (meta.options) {
            const option = meta.options.find((item) => item.value === text || item.label.toUpperCase() === text.toUpperCase());
            if (!option) throw new Error("Choose one of: " + meta.options.map((item) => item.label).join(", "));
            return option.value;
        }
        const value = numeric(text);
        if (meta.scale === 1 && meta.displayOffset === 0) return value;
        return numeric((Number(value) * meta.scale - meta.displayOffset).toFixed(6));
    }

    function createStore(storage) {
        let scope = null;
        let fields = {};
        let values = {};
        let baseline = {};
        let revision = 0;
        const listeners = new Set();
        const validators = new Set();
        const storageKey = () => "dtc-fields:v1:" + scope;
        const emit = (event = {}) => listeners.forEach((listener) => listener(event));
        const read = (key) => {
            try { return JSON.parse(storage?.getItem(key) || "null"); }
            catch { return null; }
        };
        const persist = (draft) => storage?.setItem(storageKey(), JSON.stringify(draft));
        const overrides = () => Object.fromEntries(Object.entries(values).filter(([key, value]) => value !== baseline[key]));
        const validateRaw = (key, raw) => {
            const value = numeric(raw);
            if (!fields[key]) throw new Error("Unknown DTC field: " + key);
            if (fields[key].options && !fields[key].options.some((option) => option.value === value)) {
                throw new Error("Unsupported DTC value: " + key);
            }
            return value;
        };

        function migrate() {
            const legacy = read("contenteditables") || {};
            const defaults = read("contenteditablesDef") || {};
            const draft = {};
            const plainText = (html) => {
                const node = global.document.createElement("div");
                node.innerHTML = html;
                return node.textContent.trim();
            };
            for (const [key, meta] of Object.entries(fields)) {
                const candidates = [];
                for (const id of meta.legacyIds || []) {
                    if (typeof legacy[id] !== "string") continue;
                    try {
                        const value = parse(meta, plainText(legacy[id]));
                        const changed = defaults[id] == null
                            ? value !== baseline[key]
                            : value !== parse(meta, plainText(defaults[id]));
                        if (changed) candidates.push(value);
                    } catch { /* Leave invalid legacy text out of the DTC draft. */ }
                }
                // Prefer the original linked cell when two edited copies conflict.
                if (candidates.length) draft[key] = candidates[0];
                for (const id of meta.legacyIds || []) delete legacy[id];
            }
            persist(draft);
            storage?.setItem("contenteditables", JSON.stringify(legacy));
            return draft;
        }

        function load() {
            values = { ...baseline };
            const saved = read(storageKey()) ?? migrate();
            for (const [key, raw] of Object.entries(saved)) {
                try { values[key] = validateRaw(key, raw); }
                catch { /* Ignore stale or corrupt saved fields. */ }
            }
            emit({ force: true });
        }

        const store = {
            get scope() { return scope; },
            get fields() { return fields; },
            get revision() { return revision; },
            get: (key) => values[key],
            display: (key) => format(fields[key], values[key]),
            baselineDisplay: (key) => format(fields[key], baseline[key]),
            differs: (key) => values[key] !== baseline[key],
            parse: (key, value) => parse(fields[key], value),
            configure(payload, reset = false) {
                revision++;
                const changedScope = scope !== payload.scope;
                const previous = baseline;
                scope = payload.scope;
                fields = payload.fields;
                baseline = Object.fromEntries(Object.entries(payload.values).map(([key, value]) => [key, numeric(value)]));
                if (changedScope) {
                    load();
                } else {
                    for (const [key, value] of Object.entries(baseline)) {
                        if (reset || values[key] == null || values[key] === previous[key]) values[key] = value;
                    }
                    emit({ force: reset });
                }
                if (reset) store.reset();
            },
            set(key, raw, source) {
                const value = validateRaw(key, raw);
                if (values[key] === value) return;
                values[key] = value;
                emit({ key, source });
            },
            subscribe(listener) {
                listeners.add(listener);
                return () => listeners.delete(listener);
            },
            addValidator(validate) {
                validators.add(validate);
                return () => validators.delete(validate);
            },
            flush(sections) {
                let valid = true;
                validators.forEach((validate) => { if (!validate(sections)) valid = false; });
                if (!valid) throw new Error("Correct the highlighted DTC fields before saving or exporting.");
            },
            snapshot() {
                store.flush();
                return { scope, values: { ...values } };
            },
            section(section) {
                store.flush([section]);
                return Object.fromEntries(Object.entries(fields)
                    .filter(([, meta]) => meta.section === section)
                    .map(([key, meta]) => [meta.field, values[key]]));
            },
            save() {
                store.flush();
                if (scope != null) persist(overrides());
            },
            load,
            reset() {
                values = { ...baseline };
                if (scope != null) persist({});
                emit({ force: true });
            },
            acknowledge(savedScope, sections) {
                if (savedScope !== scope) return;
                revision++;
                const saved = read(storageKey()) || {};
                for (const [section, settings] of Object.entries(sections)) {
                    for (const [field, raw] of Object.entries(settings)) {
                        const key = section + ":" + field;
                        baseline[key] = numeric(raw);
                        delete saved[key];
                    }
                }
                persist(saved);
                emit();
            },
        };
        return store;
    }

    function bind(doc, store) {
        const elements = Array.from(doc.querySelectorAll("[data-dtc-field]"))
            .filter((el) => store.fields[el.dataset.dtcField]);
        const lastDisplay = new WeakMap();
        const isInput = (el) => el.tagName === "INPUT" || el.tagName === "TEXTAREA";
        const readText = (el) => isInput(el) ? el.value : el.textContent;
        const writeText = (el, text) => { if (isInput(el)) el.value = text; else el.textContent = text; };

        function render(event = {}) {
            for (const el of elements) {
                const key = el.dataset.dtcField;
                const editing = el === doc.activeElement && doc.hasFocus();
                if (!event.force && el !== event.committed && (editing || el.getAttribute("aria-invalid") === "true")) continue;
                const text = (el.dataset.dtcPrefix || "") + store.display(key);
                writeText(el, text);
                lastDisplay.set(el, text);
                el.removeAttribute("aria-invalid");
                el.classList.toggle("dtc-linked-diff", store.differs(key));
                el.title = store.differs(key) ? "Differs from callsign.ini: " + store.baselineDisplay(key) : "";
            }
        }

        function commit(el) {
            try {
                const text = readText(el).trim();
                if (text !== lastDisplay.get(el)) store.set(el.dataset.dtcField, store.parse(el.dataset.dtcField, text), el);
                el.removeAttribute("aria-invalid");
                return true;
            } catch (error) {
                el.setAttribute("aria-invalid", "true");
                el.title = error.message;
                return false;
            }
        }

        for (const el of elements) {
            const key = el.dataset.dtcField;
            const options = store.fields[key].options;
            if (options) {
                el.contentEditable = "false";
                el.tabIndex = 0;
                el.classList.add("dtc-cycle-field");
                if (el.tagName !== "BUTTON") el.setAttribute("role", "button");
                const cycle = () => {
                    const index = options.findIndex((option) => option.value === store.get(key));
                    store.set(key, options[(index + 1) % options.length].value);
                    render({ committed: el });
                };
                el.addEventListener("click", cycle);
                if (el.tagName !== "BUTTON") el.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); cycle(); }
                });
            } else {
                el.addEventListener("input", () => commit(el));
                el.addEventListener("blur", () => { if (commit(el)) render(); });
                el.addEventListener("change", () => commit(el));
                el.addEventListener("keydown", (event) => {
                    if (event.key === "Enter") { event.preventDefault(); el.blur(); }
                    if (event.key === "Escape") { event.preventDefault(); render({ committed: el }); el.blur(); }
                });
            }
        }
        const unsubscribe = store.subscribe(render);
        const removeValidator = store.addValidator((sections) => {
            let valid = true;
            for (const el of elements) {
                if (store.fields[el.dataset.dtcField].options) continue;
                if (sections && !sections.includes(store.fields[el.dataset.dtcField].section)) continue;
                if (!commit(el)) valid = false;
            }
            return valid;
        });
        render({ force: true });
        doc.defaultView.addEventListener("unload", () => { unsubscribe(); removeValidator(); }, { once: true });
        return { render };
    }

    function attach(win, payload) {
        let owner = win;
        try { if (win.parent.DtcFields) owner = win.parent; } catch { /* Standalone preview. */ }
        const store = owner.dtcFieldStore || (owner.dtcFieldStore = createStore(owner.localStorage));
        if (store.scope !== payload.scope) store.configure(payload);
        win.dtcFieldStore = store;
        return bind(win.document, store);
    }

    const api = { createStore, bind, attach, format, parse };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    else global.DtcFields = api;
})(typeof window === "undefined" ? globalThis : window);
