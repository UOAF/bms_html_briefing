window.onload = function()
{
    bindClipboardImagePasteHandlers();
    saveContenteditablesDefaults();

    var restore = localStorage.getItem("onrefresh");
    if (restore == "restore") {
	loadChangedData();
	localStorage.setItem("onrefresh", "");
    }
    if (restore == "reset") {
	saveChangedData();
	localStorage.setItem("onrefresh", "");
	}
}

function getPersistentContenteditableElements() {
    return document.querySelectorAll('[contenteditable="true"]:not([data-local-storage="ignore"])');
}

function insertNodeAtCursor(node, fallbackContainer) {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || !fallbackContainer.contains(selection.anchorNode)) {
        fallbackContainer.appendChild(node);
        return;
    }
    const range = selection.getRangeAt(0);
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(node);
    range.setEndAfter(node);
    selection.removeAllRanges();
    selection.addRange(range);
}

function bindClipboardImagePasteHandlers() {
    const contenteditableElements = document.querySelectorAll('[contenteditable="true"]');
    contenteditableElements.forEach((el) => {
        if (el.dataset.imagePasteBound === "1") {
            return;
        }
        el.dataset.imagePasteBound = "1";
        el.addEventListener("paste", (event) => {
            const items = Array.from((event.clipboardData && event.clipboardData.items) || []);
            const imageItems = items.filter((item) => item.kind === "file" && item.type.startsWith("image/"));
            if (!imageItems.length) {
                return;
            }
            event.preventDefault();
            imageItems.forEach((item) => {
                const file = item.getAsFile();
                if (!file) {
                    return;
                }
                const reader = new FileReader();
                reader.onload = function () {
                    const img = document.createElement("img");
                    img.src = reader.result;
                    img.style.maxWidth = "100%";
                    img.style.height = "auto";
                    insertNodeAtCursor(img, el);
                    saveChangedData();
                };
                reader.readAsDataURL(file);
            });
        });
    });
}

function serializeEditableContent(el) {
    if (!el) {
        return "";
    }
    const clone = el.cloneNode(true);
    const sourceImages = el.querySelectorAll("img");
    const clonedImages = clone.querySelectorAll("img");
    for (let i = 0; i < clonedImages.length; i++) {
        const cloneImg = clonedImages[i];
        const src = cloneImg.getAttribute("src") || "";
        if (!src || src.startsWith("data:")) {
            continue;
        }
        const sourceImg = sourceImages[i];
        if (!sourceImg) {
            continue;
        }
        try {
            const width = sourceImg.naturalWidth || sourceImg.width || 0;
            const height = sourceImg.naturalHeight || sourceImg.height || 0;
            if (!width || !height) {
                continue;
            }
            const canvas = document.createElement("canvas");
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(sourceImg, 0, 0, width, height);
            cloneImg.setAttribute("src", canvas.toDataURL("image/png"));
        }
        catch (error) {
            console.error("Failed to serialize pasted image", error);
        }
    }
    return clone.innerHTML;
}

function saveChangedData() {
    const contenteditableElements = getPersistentContenteditableElements();
    const contentData = {};
    contenteditableElements.forEach(el => {
        const key = el.id;
        contentData[key] = serializeEditableContent(el);
    });
    const hidableElements = document.querySelectorAll('.hidable');
    hidableElements.forEach(el => {
	const key = el.id + '_display';
	contentData[key] = el.style.display;
    });

    if (typeof map != 'undefined') {
	contentData["mapBaseMode"] = typeof MAP_BASE_MODE != 'undefined' ? MAP_BASE_MODE : "local_tiles";
	contentData["mapZoom"] = map.getZoom();
	contentData["mapCenter"] = map.getCenter();
	contentData['bullseyePos'] = bullseye_overlay.getCenter();
    }
    var selected_files = document.getElementsByClassName('imageFileInput');
    for (i = 0; i < selected_files.length; i++) {
	try {
	    contentData[selected_files[i].id] = selected_files[i].files[0].name;
	}
	catch (error) {
	    console.error(error);
	}

    }
    localStorage.setItem('contenteditables', JSON.stringify(contentData));
    return contentData;
}

function saveContenteditablesDefaults() {
    const contenteditableElements = getPersistentContenteditableElements();
    const contentDataDef = {};
    contenteditableElements.forEach(el => {
        const key = el.id;
        contentDataDef[key] = el.innerHTML;
    });
    try {
	contentDataDef["mapInput"] = "map.png";
	contentDataDef["mapBaseMode"] = typeof MAP_BASE_MODE != 'undefined' ? MAP_BASE_MODE : "local_tiles";
	contentDataDef["mapZoom"] = map.getZoom();
	contentDataDef["mapCenter"] = map.getCenter();
	contentDataDef['bullseyePos'] = bullseye_overlay.getCenter();
    }
    catch (error) {
	console.error(error);
    }
    localStorage.setItem('contenteditablesDef', JSON.stringify(contentDataDef));
}

function loadChangedData() {
    loadContenteditables();
    loadImages();
}

function restoreDefaultAtId(id) {
    const toRestore = document.querySelectorAll("." + id);
    const contentDataDef = JSON.parse(localStorage.getItem('contenteditablesDef') || '{}');
    for (i = 0; i < toRestore.length; i ++) {
	toRestore[i].innerHTML = contentDataDef[toRestore[i].id];
    }
}

function loadImages() {
    const contentData = JSON.parse(localStorage.getItem('contenteditables') || '{}');

    if (contentData["mapInput"] !== "" && typeof contentData["mapInput"] !== 'undefined') {
	drawMap("assets/maps/" + contentData["mapInput"]);
    }
    restoreMapView(contentData);

    const refCellMappings = [
        { cellId: "tgt1Ref", legacySrcKey: "tgt1Img_src", legacyInputKey: "tgt1Input" },
        { cellId: "tgt2Ref", legacySrcKey: "tgt2Img_src", legacyInputKey: "tgt2Input" },
        { cellId: "tgt3Ref", legacySrcKey: "tgt3Img_src", legacyInputKey: "tgt3Input" },
    ];
    refCellMappings.forEach(({ cellId, legacySrcKey, legacyInputKey }) => {
        const cell = document.getElementById(cellId);
        if (!cell || (cell.innerHTML && cell.innerHTML.trim() !== "")) {
            return;
        }
        if (contentData[legacySrcKey]) {
            cell.innerHTML = '<img src="' + contentData[legacySrcKey] + '" alt="" style="max-width: 100%; height: auto; width: auto; display: block; margin: 0 auto;">';
            return;
        }
        if (typeof contentData[legacyInputKey] !== 'undefined' && contentData[legacyInputKey] !== "") {
            cell.innerHTML = '<img src="assets/targets/' + contentData[legacyInputKey] + '" alt="" style="max-width: 100%; height: auto; width: auto; display: block; margin: 0 auto;">';
        }
    });

}

function restoreMapView(contentData) {
    try {
	const currentMapBaseMode = typeof MAP_BASE_MODE != 'undefined' ? MAP_BASE_MODE : "local_tiles";
	const savedMapBaseMode = contentData["mapBaseMode"] || "local_tiles";
	if (savedMapBaseMode === currentMapBaseMode) {
	    map.setView(contentData["mapCenter"], contentData["mapZoom"]);
	    setBullseye(contentData['bullseyePos']);
	}
    }
    catch (error) {
	console.error(error);
    }
}

function loadContenteditables() {
    const contentData = JSON.parse(localStorage.getItem('contenteditables') || '{}');
    Object.keys(contentData).forEach(key => {
        const el = document.getElementById(key);
        if (el && el.dataset.localStorage !== "ignore") {
            el.innerHTML = contentData[key];
	}
        if (key.split("_").at(-1) == "display") {
	    const el_display = document.getElementById(key.split("_")[0]);
            if (el_display) {
		el_display.style.display = contentData[key];
		try {
		    const el_arrow = document.getElementById(key.split("_")[0] + "_header").querySelector(".arrow");
		    el_arrow.innerHTML = (contentData[key] == "none") ? "▸" : "▼";
		}
		catch (error) {
		    console.error(error);
		    console.log(key);
		}
            }
	}});
}

function reloadFromFiles() {
    localStorage.setItem("onrefresh", "restore");
    window.location.reload();
    return "false";
}

function resetContenteditables() {
    if (confirm("Are you sure? This will overwrite all changes.")){
        localStorage.setItem("onrefresh", "reset");
	var selected_files = document.getElementsByClassName('imageFileInput');
	for (i = 0; i < selected_files.length; i++) {
	    try {
		selected_files[i].value = "";
	    }
	    catch (error) {
		console.error(error);
	    }}
	window.location.reload();
        return "false";
    }
}
function toggleVis(chkbox) {
    var element_id = chkbox.id.split("_")[0];
    var element = document.getElementById(element_id).style.display = chkbox.checked ? "" : "none";
}

function toggleVisHeader(header) {
    var element_id = header.id.split("_")[0];
    var element = document.getElementById(element_id);
    var element_arrow = header.querySelector(".arrow");
    if (element.style.display == "none") {
	element.style.display = "";
	element_arrow.innerHTML = "▼";
    }
    else {
	element.style.display = "none";
	element_arrow.innerHTML = "▸";
    }
}
