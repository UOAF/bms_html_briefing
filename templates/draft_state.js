/* Rebase local changes onto regenerated data without pinning untouched values. */
(function (global) {
    "use strict";
    const object = (value) => value != null && typeof value === "object" && !Array.isArray(value);
    function equal(a, b) {
        if (a === b) return true;
        if (!object(a) || !object(b)) return JSON.stringify(a) === JSON.stringify(b);
        const keys = Object.keys(a);
        return keys.length === Object.keys(b).length && keys.every((key) => Object.hasOwn(b, key) && equal(a[key], b[key]));
    }
    function rebase(baseline, draft, fresh) {
        if (equal(baseline, draft)) return structuredClone(fresh);
        if (!object(baseline) || !object(draft) || !object(fresh)) return structuredClone(draft);
        const result = {};
        for (const key of new Set([...Object.keys(baseline), ...Object.keys(draft), ...Object.keys(fresh)])) {
            const value = rebase(baseline[key], draft[key], fresh[key]);
            if (value !== undefined) result[key] = value;
        }
        return result;
    }
    function sourceKey(files) {
        if (!files?.briefing?.size || !files?.callsign?.size) return "";
        return JSON.stringify([files.briefing, files.callsign].map(({ path, mtime, size }) => [path, mtime, size]));
    }
    function createWatcher() {
        let rendered = "", candidate = "", since = 0;
        let renderedFiles = null;
        return {
            mark(files) {
                if (!sourceKey(files)) return;
                rendered = sourceKey(files);
                renderedFiles = structuredClone(files);
            },
            changes(files) {
                if (!renderedFiles || !files) return null;
                return {
                    briefChanged: !equal(renderedFiles.briefing, files.briefing),
                    callsignChanged: !equal(renderedFiles.callsign, files.callsign),
                };
            },
            stable(files, now = Date.now()) { return !!candidate && sourceKey(files) === candidate && now - since >= 750; },
            needsRefresh(files, now = Date.now()) {
                const key = sourceKey(files);
                if (key !== candidate) { candidate = key; since = now; }
                return !!key && key !== rendered && now - since >= 750;
            },
        };
    }
    const api = { equal, rebase, sourceKey, createWatcher };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    else global.DraftState = api;
})(typeof window === "undefined" ? globalThis : window);
