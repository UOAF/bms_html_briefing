/* Computed DTC results are shared by the calculator, briefing and PDF snapshot. */
(function (global) {
    "use strict";

    function createStore(storage) {
        let scope = null;
        let values = {};
        const listeners = new Set();
        const storageKey = () => "popup-briefing:v1:" + scope;
        const emit = () => listeners.forEach((listener) => listener());
        const clean = (data) => Object.fromEntries(Object.entries(data || {})
            .filter(([key, value]) => typeof value === "string" && value.length <= 512)
            // Older saved plans used a degree glyph that some PDF fonts lack.
            .map(([key, value]) => [key, value.replace(/°([MT])?/g,
                (_match, reference) => reference ? " deg " + reference : " deg")]));
        return {
            get scope() { return scope; },
            configure(nextScope) {
                if (scope === nextScope) return;
                scope = nextScope;
                try { values = clean(JSON.parse(storage?.getItem(storageKey()) || "{}")); }
                catch { values = {}; }
                emit();
            },
            publish(sourceScope, results) {
                // Ignore results from a DTC frame still showing an older route.
                if (!scope || sourceScope !== scope) return false;
                values = clean(results);
                try { storage?.setItem(storageKey(), JSON.stringify(values)); }
                catch { /* Live results still work when browser storage is full. */ }
                emit();
                return true;
            },
            snapshot() { return { scope, values: { ...values } }; },
            subscribe(listener) {
                listeners.add(listener);
                return () => listeners.delete(listener);
            },
        };
    }

    function attach(win, scope) {
        let owner = win;
        try { if (win.parent.PopupBriefing) owner = win.parent; } catch { /* Standalone page. */ }
        const store = owner.popupBriefingStore || (owner.popupBriefingStore = createStore(owner.localStorage));
        store.configure(scope);
        win.popupBriefingStore = store;
        const elements = Array.from(win.document.querySelectorAll("[data-popup-result]"));
        const render = () => {
            const values = store.scope === scope ? store.snapshot().values : {};
            for (const element of elements) {
                element.textContent = values[element.dataset.popupResult] ?? element.dataset.popupEmpty ?? "";
            }
        };
        const unsubscribe = store.subscribe(render);
        win.addEventListener("unload", unsubscribe, { once: true });
        render();
        return store;
    }

    const api = { createStore, attach };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    else global.PopupBriefing = api;
})(typeof window === "undefined" ? globalThis : window);
