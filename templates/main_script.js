window.onload = function()
{
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

function saveChangedData() {
    const contenteditableElements = document.querySelectorAll('[contenteditable="true"]');
    const contentData = {};
    contenteditableElements.forEach(el => {
        const key = el.id;
        contentData[key] = el.innerHTML;
    });
    const hidableElements = document.querySelectorAll('.hidable');
    hidableElements.forEach(el => {
	const key = el.id + '_display';
	contentData[key] = el.style.display;
    });

    if (typeof map != 'undefined') {
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
    // persist target image data URLs so PDF generation can embed them
    ["tgt1Img", "tgt2Img", "tgt3Img"].forEach((id) => {
        const imgEl = document.getElementById(id);
        if (imgEl && imgEl.src) {
            if (imgEl.src.startsWith("data:")) {
                contentData[id + "_src"] = imgEl.src;
            } else {
                try {
                    const canvas = document.createElement("canvas");
                    canvas.width = imgEl.naturalWidth || imgEl.width || 1024;
                    canvas.height = imgEl.naturalHeight || imgEl.height || 1024;
                    const ctx = canvas.getContext("2d");
                    ctx.drawImage(imgEl, 0, 0, canvas.width, canvas.height);
                    contentData[id + "_src"] = canvas.toDataURL("image/png");
                } catch (e) {
                    console.error("Failed to serialize image", id, e);
                }
            }
        }
    });
    localStorage.setItem('contenteditables', JSON.stringify(contentData));
}

function saveContenteditablesDefaults() {
    const contenteditableElements = document.querySelectorAll('[contenteditable="true"]');
    const contentDataDef = {};
    contenteditableElements.forEach(el => {
        const key = el.id;
        contentDataDef[key] = el.innerHTML;
    });
    try {
	contentDataDef["mapInput"] = "map.png";
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
	drawMap("../assets/maps/" + contentData["mapInput"]);
    }
    try {
	map.setView(contentData["mapCenter"], contentData["mapZoom"]);
	setBullseye(contentData['bullseyePos']);
    }
    catch (error) {
	console.error(error);
    }


    let imageRow = document.getElementById("refImageRow");

    let imageDisplay1 = document.getElementById("tgt1Img");
    let imageDisplay2 = document.getElementById("tgt2Img");
    let imageDisplay3 = document.getElementById("tgt3Img");
    if (contentData["tgt1Img_src"]) {
        imageRow.style.visibility = "";
        imageDisplay1.src = contentData["tgt1Img_src"];
    } else if (typeof contentData["tgt1Input"] != 'undefined') {
	imageRow.style.visibility = "";
	imageDisplay1.src = "../assets/targets/" + contentData["tgt1Input"];
    }
    if (contentData["tgt2Img_src"]) {
        imageRow.style.visibility = "";
        imageDisplay2.src = contentData["tgt2Img_src"];
    } else if (typeof contentData["tgt2Input"] != 'undefined') {
	imageRow.style.visibility = "";
	imageDisplay2.src = "../assets/targets/" + contentData["tgt2Input"];
    }
    if (contentData["tgt3Img_src"]) {
        imageRow.style.visibility = "";
        imageDisplay3.src = contentData["tgt3Img_src"];
    } else if (typeof contentData["tgt3Input"] != 'undefined') {
	imageRow.style.visibility = "";
	imageDisplay3.src = "../assets/targets/" + contentData["tgt3Input"];
    }

}

function loadContenteditables() {
    const contentData = JSON.parse(localStorage.getItem('contenteditables') || '{}');
    Object.keys(contentData).forEach(key => {
        const el = document.getElementById(key);
        if (el) {
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
