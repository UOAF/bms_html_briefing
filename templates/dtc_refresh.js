/* Drafts owned by the DTC iframe, separate from the shared ICP/FCC store. */
(function () {
    const controls = () => Array.from(document.querySelectorAll("[data-popup-field], [data-slider-value-for]"));
    const key = (el) => el.dataset.popupField ? "field:" + el.dataset.popupField : "readout:" + el.dataset.sliderValueFor;
    const state = () => ({
        nav: structuredClone(dtcNavOffsets),
        laser: collectDtcLaserSettings(),
        popup: Object.fromEntries(controls().map((el) => [key(el), el.dataset.popupValue ?? el.value])),
    });
    const baseline = state();
    window.dtcSaveRevision = 0;
    window.acknowledgeDtcDraft = (section, submitted) => {
        baseline[section] = structuredClone(submitted);
        window.dtcSaveRevision++;
    };
    window.collectDtcRefreshDraft = () => ({
        scope: dtcSourceScope, route: dtcPopupScope,
        baseline: structuredClone(baseline), values: state(),
        selected: dtcSelectedStptNumber,
        tab: document.querySelector(".dtc-main-tabs .is-active")?.dataset.dtcPageTab,
        center: typeof map !== "undefined" ? map.getCenter() : null,
        zoom: typeof map !== "undefined" ? map.getZoom() : null,
    });
    window.canRefreshDtc = (payload) => {
        const current = state();
        if (window.dtcSaveBusy || window.dtcPendingEdits || dtcPopupElevationRequests.size) return false;
        if (payload.scope !== dtcSourceScope) return DraftState.equal(baseline, current);
        // Keep geometry drafts attached to the route they were authored against.
        return payload.popup_scope === dtcPopupScope || (
            DraftState.equal(baseline.nav, current.nav) && DraftState.equal(baseline.popup, current.popup));
    };
    window.restoreDtcRefreshDraft = (draft) => {
        if (draft.scope !== dtcSourceScope) return;
        const fresh = state();
        const merged = DraftState.rebase(draft.baseline, draft.values, fresh);
        const sameRoute = draft.route === dtcPopupScope;
        if (sameRoute) {
            Object.keys(dtcNavOffsets).forEach((name) => delete dtcNavOffsets[name]);
            Object.assign(dtcNavOffsets, merged.nav);
            controls().forEach((el) => {
                const value = merged.popup[key(el)];
                if (value === undefined) return;
                if (el.dataset.popupValue !== undefined) el.dataset.popupValue = value;
                else el.value = value;
            });
        }
        Object.assign(dtcLaserSettings, merged.laser);
        renderDtcLaserSettings();
        if (sameRoute && getStptRow(draft.selected)) dtcSelectedStptNumber = draft.selected;
        selectDtcPageTab(draft.tab);
        renderDtcStptSelectionLayer();
        renderOffsetPanel();
        if (sameRoute && draft.center && typeof map !== "undefined") map.setView(draft.center, draft.zoom);
    };
})();
