/* SPDX-License-Identifier: AGPL-3.0-only
 * Adapted from BMS-Cards briefing.js and mapsymbols.js at 7436fa4:
 * https://github.com/Evilangel19/BMS-Cards (AGPLv3).
 * Changes (2026-11-17): standalone canvas drawing and hit testing, shared by
 * briefing display/export, with projected BMS coordinates and no room state.
 * Changes (2026-11-19): render separately licensed Wikimedia NATO artwork.
 * Changes (2026-11-19): standalone BMS-Cards laser glow and fading trail.
 */
(function (global) {
    "use strict";
    const COLORS = ["#f5c842", "#ef4444", "#38bdf8", "#4ade80", "#ffffff"];
    const LASER_TTL = 900;
    const SIDES = { hostile: "#ff5d5d", friend: "#4f8cff", neutral: "#4cc38a", unknown: "#f5d742" };
    const UNITS = [
        ["armor", "Armor"], ["inf", "Infantry"], ["art", "Artillery"],
        ["missile", "SSM"], ["ad", "Air defence"], ["hq", "HQ"], ["eng", "Engineer"], ["generic", "Generic"],
    ];
    const CONTROLS = [["trk", "Radar track"], ["ab", "Airbase"], ["IP", "IP"], ["CP", "CP"],
        ["tgt", "Target"], ["bull", "Bullseye"], ["orbit", "CAP orbit"], ["hold", "Holding"], ["ring", "Threat ring"]];
    const paths = new WeakMap();
    function tacticalPaths(symbol, side) {
        return global.BriefingNatoSymbols[symbol]?.[side];
    }
    function tacticalIcon(shapes) {
        return '<svg viewBox="-16 -16 32 32" xmlns="http://www.w3.org/2000/svg">' + shapes.map((shape) =>
            `<path d="${shape.d}" transform="matrix(${shape.matrix.join(" ")})" fill="${shape.fill}" stroke="${shape.stroke}" stroke-width="${shape.width}" stroke-linecap="${shape.cap}" stroke-linejoin="${shape.join}" stroke-miterlimit="${shape.miter}"/>`
        ).join("") + '</svg>';
    }
    function drawTactical(ctx, shapes) {
        for (const shape of shapes) {
            if (!paths.has(shape)) paths.set(shape, new Path2D(shape.d));
            ctx.save();
            ctx.transform(...shape.matrix);
            ctx.lineWidth = shape.width;
            ctx.lineCap = shape.cap;
            ctx.lineJoin = shape.join;
            ctx.miterLimit = shape.miter;
            if (shape.fill !== "none") {
                ctx.fillStyle = shape.fill;
                ctx.fill(paths.get(shape));
            }
            if (shape.stroke !== "none") {
                ctx.strokeStyle = shape.stroke;
                ctx.stroke(paths.get(shape));
            }
            ctx.restore();
        }
    }
    function symbolIcon(symbol, side, threatRingStyle) {
        const shapes = tacticalPaths(symbol, side);
        if (shapes) return tacticalIcon(shapes);
        if (symbol === "ring" && threatRingStyle) {
            const style = threatRingStyle;
            return `<svg viewBox="-16 -16 32 32" xmlns="http://www.w3.org/2000/svg"><circle r="11" fill="${style.fillColor}" fill-opacity="${style.fillOpacity}" stroke="${style.color}" stroke-opacity="${style.opacity}" stroke-width="${style.weight}" stroke-linecap="${style.lineCap}" stroke-dasharray="${style.dashPattern.join(" ")}"/></svg>`;
        }
        const color = SIDES[side];
        const control = {
            trk: '<path d="M-4-4H4V4H-4ZM4-4L13-10"/>',
            ab: '<path d="M-7 10L4-10M-3 10L8-10M-10-1L10 5"/>',
            IP: '<text y="4" text-anchor="middle" fill="currentColor" stroke="none">IP</text>',
            CP: '<text y="4" text-anchor="middle" fill="currentColor" stroke="none">CP</text>',
            tgt: '<circle r="7"/><path d="M0-12V12M-12 0H12"/>',
            bull: '<circle r="11"/><circle r="7"/><circle r="3"/>',
            orbit: '<rect x="-14" y="-7" width="28" height="14" rx="7"/><path d="M0-7l4-3v6z"/>',
            hold: '<rect x="-14" y="-7" width="28" height="14" rx="7"/><path d="M8 7l-4-3v6z"/>',
            ring: '<circle r="11" stroke-dasharray="3 2"/>',
        };
        return `<svg viewBox="-16 -16 32 32" xmlns="http://www.w3.org/2000/svg" style="color:${color}" fill="none" stroke="${color}" stroke-width="1.6">${control[symbol]}</svg>`;
    }
    function text(ctx, value, x, y, color = "#fff", size = 12, align = "center") {
        ctx.save();
        ctx.font = `700 ${size}px system-ui,sans-serif`;
        ctx.textAlign = align;
        ctx.textBaseline = "bottom";
        ctx.strokeStyle = "#111";
        ctx.lineWidth = 3;
        ctx.fillStyle = color;
        String(value).split("\n").forEach((line, i) => {
            ctx.strokeText(line, x, y + i * size * 1.25);
            ctx.fillText(line, x, y + i * size * 1.25);
        });
        ctx.restore();
    }
    function pathFor(f, p) {
        const path = new Path2D();
        if (!p.length) return path;
        const [a, b] = p;
        if (f.kind === "point") path.arc(a.x, a.y, 6, 0, Math.PI * 2);
        else if (f.kind === "symbol" && ["orbit", "hold"].includes(f.symbol)) {
            const angle = Math.atan2(b.y - a.y, b.x - a.x), r = Math.max(7, a.distanceTo(b) * .22);
            const nx = -Math.sin(angle), ny = Math.cos(angle), off = f.symbol === "hold" ? r : 0;
            const A = { x: a.x + nx * off, y: a.y + ny * off }, B = { x: b.x + nx * off, y: b.y + ny * off };
            path.moveTo(A.x - nx * r, A.y - ny * r);
            path.lineTo(B.x - nx * r, B.y - ny * r);
            path.arc(B.x, B.y, r, angle - Math.PI / 2, angle + Math.PI / 2);
            path.lineTo(A.x + nx * r, A.y + ny * r);
            path.arc(A.x, A.y, r, angle + Math.PI / 2, angle + Math.PI * 1.5);
            const x = (A.x + B.x) / 2 - nx * r, y = (A.y + B.y) / 2 - ny * r;
            path.moveTo(x - 7 * Math.cos(angle - .5), y - 7 * Math.sin(angle - .5));
            path.lineTo(x, y);
            path.lineTo(x - 7 * Math.cos(angle + .5), y - 7 * Math.sin(angle + .5));
            if (f.symbol === "hold") path.rect(b.x - 3, b.y - 3, 6, 6);
        } else {
            path.moveTo(a.x, a.y);
            if (["pen", "marker"].includes(f.kind)) {
                for (let i = 1; i < p.length - 1; i++) {
                    path.quadraticCurveTo(p[i].x, p[i].y, (p[i].x + p[i + 1].x) / 2, (p[i].y + p[i + 1].y) / 2);
                }
                path.lineTo(p.at(-1).x, p.at(-1).y);
            } else p.slice(1).forEach((q) => path.lineTo(q.x, q.y));
            if (f.kind === "rectangle" || f.kind === "circle" || f.symbol === "ring") path.closePath();
            if (f.kind === "arrow" && p.length > 1) {
                const end = p.at(-1), prev = p.at(-2), angle = Math.atan2(end.y - prev.y, end.x - prev.x);
                const length = 10 + (f.width || 2.5) * 2.2;
                path.moveTo(end.x - length * Math.cos(angle - .45), end.y - length * Math.sin(angle - .45));
                path.lineTo(end.x, end.y);
                path.lineTo(end.x - length * Math.cos(angle + .45), end.y - length * Math.sin(angle + .45));
            }
        }
        return path;
    }
    function drawSymbol(ctx, f, p) {
        const color = SIDES[f.side], a = p[0];
        const shapes = tacticalPaths(f.symbol, f.side);
        ctx.save();
        ctx.translate(a.x, a.y);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.8;
        ctx.fillStyle = "#0d1b2ad9";
        if (shapes) {
            drawTactical(ctx, shapes);
        } else if (f.symbol === "trk") {
            ctx.strokeRect(-5, -5, 10, 10);
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(p[1].x - a.x, p[1].y - a.y);
            ctx.stroke();
            ctx.setLineDash([1, 6]);
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo((a.x - p[1].x) * .75, (a.y - p[1].y) * .75);
            ctx.stroke();
        } else if (["IP", "CP"].includes(f.symbol)) {
            const pin = new Path2D("M0 0L-9-15A11 11 0 1 1 9-15Z");
            ctx.fill(pin);
            ctx.stroke(pin);
            text(ctx, f.symbol, 0, -14, color, 10);
        } else if (f.symbol === "ab") {
            ctx.stroke(new Path2D("M-7 10L4-10M-3 10L8-10M-10-1L10 5"));
        } else {
            ctx.beginPath();
            (f.symbol === "bull" ? [16, 10.5, 5] : [8]).forEach((r) => { ctx.moveTo(r, 0); ctx.arc(0, 0, r, 0, Math.PI * 2); });
            ctx.moveTo(0, -20); ctx.lineTo(0, 20);
            ctx.moveTo(-20, 0); ctx.lineTo(20, 0);
            ctx.stroke();
        }
        ctx.restore();
    }
    function draw(ctx, f, p, anchor, threatRingStyle, threatRingMode = "filled") {
        if (!p.length) return;
        ctx.save();
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.setLineDash([]);
        const color = f.symbol === "ring" && threatRingStyle ? threatRingStyle.color
            : f.kind === "symbol" ? SIDES[f.side] : f.color;
        const width = f.width || 2.5;
        if (f.kind === "text") text(ctx, f.label, anchor.x, anchor.y, color, f.size || 20, "left");
        else if (f.kind === "symbol" && !["orbit", "hold", "ring"].includes(f.symbol)) drawSymbol(ctx, f, p);
        else {
            const path = pathFor(f, p);
            if (f.symbol === "ring" && threatRingStyle) {
                // Share the campaign threat style; annotation width and
                // affiliation do not change the appearance of a threat ring.
                if (threatRingMode === "filled") {
                    ctx.fillStyle = threatRingStyle.fillColor;
                    ctx.globalAlpha = threatRingStyle.fillOpacity;
                    ctx.fill(path);
                }
                if (threatRingMode !== "none") {
                    ctx.globalAlpha = threatRingStyle.opacity;
                    ctx.strokeStyle = threatRingStyle.color;
                    ctx.lineWidth = threatRingStyle.weight;
                    ctx.lineCap = threatRingStyle.lineCap;
                    ctx.setLineDash(threatRingStyle.dashPattern);
                    ctx.stroke(path);
                }
                ctx.globalAlpha = 1;
            } else if (f.kind === "marker") {
                ctx.globalAlpha = .35;
                ctx.lineWidth = width * 4 + 6;
                ctx.strokeStyle = color;
                ctx.stroke(path);
            } else {
                if (["rectangle", "circle", "point"].includes(f.kind) || f.symbol === "ring") {
                    ctx.fillStyle = color;
                    ctx.globalAlpha = f.kind === "point" ? 1 : .08;
                    ctx.fill(path);
                    ctx.globalAlpha = 1;
                }
                if (f.symbol === "ring") ctx.setLineDash([7, 5]);
                ctx.strokeStyle = "#1119";
                ctx.lineWidth = width + 2.5;
                ctx.stroke(path);
                ctx.strokeStyle = color;
                ctx.lineWidth = width;
                ctx.stroke(path);
            }
        }
        if (f.label && f.kind !== "text") text(ctx, f.label, anchor.x, anchor.y - 16, color);
        if (f.symbol === "ring" && threatRingMode !== "none") {
            const radius = Math.hypot(f.points[1][0] - f.points[0][0], f.points[1][1] - f.points[0][1]);
            text(ctx, (radius / 6076.12).toFixed(1) + " NM", anchor.x, anchor.y + 18, color);
        }
        ctx.restore();
    }
    // Transient overlay only: callers must not use this in saved map exports.
    function drawLaser(ctx, samples, head, now) {
        ctx.save();
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        for (let i = 1; i < samples.length; i++) {
            const a = samples[i - 1].point, b = samples[i].point;
            if (!a || !b) continue;
            const fade = Math.max(0, 1 - (now - samples[i].time) / LASER_TTL);
            ctx.strokeStyle = `rgba(255,40,40,${.25 * fade})`;
            ctx.lineWidth = 12 * fade + 2;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
            ctx.strokeStyle = `rgba(255,90,90,${.9 * fade})`;
            ctx.lineWidth = 3 * fade + .5;
            ctx.stroke();
        }
        if (head) {
            const glow = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, 14);
            glow.addColorStop(0, "rgba(255,255,255,1)");
            glow.addColorStop(.25, "rgba(255,60,60,.95)");
            glow.addColorStop(1, "rgba(255,0,0,0)");
            ctx.fillStyle = glow;
            ctx.beginPath();
            ctx.arc(head.x, head.y, 14, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.restore();
    }
    function hit(ctx, f, p, anchor, at) {
        if (!p.length) return false;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (f.kind === "text") {
            const size = f.size || 20, lines = f.label.split("\n");
            ctx.font = `700 ${size}px system-ui,sans-serif`;
            const width = Math.max(...lines.map((line) => ctx.measureText(line).width), 12);
            return at.x >= anchor.x - 5 && at.x <= anchor.x + width + 5
                && at.y >= anchor.y - size - 5 && at.y <= anchor.y + (lines.length - 1) * size * 1.25 + 5;
        }
        if (f.kind === "symbol" && !["orbit", "hold", "ring"].includes(f.symbol)) {
            if (Math.hypot(at.x - p[0].x, at.y - p[0].y) <= 22) return true;
            if (f.symbol !== "trk") return false;
        }
        ctx.lineWidth = f.kind === "marker" ? (f.width || 2.5) * 4 + 14 : (f.width || 2.5) + 12;
        const path = pathFor(f, p);
        return ctx.isPointInStroke(path, at.x, at.y)
            || ((["point", "rectangle", "circle"].includes(f.kind) || f.symbol === "ring") && ctx.isPointInPath(path, at.x, at.y));
    }
    global.BriefingAnnotationDrawing = { COLORS, SIDES, UNITS, CONTROLS, LASER_TTL, symbolIcon, draw, drawLaser, hit };
})(window);
