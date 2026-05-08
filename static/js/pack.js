/**
 * static/js/pack.js  (standalone page — circle packing visualizer)
 *
 * Fetches /api/graph/{alias}?mode=packing and renders a zoomable circle
 * packing where:
 *   - outer circles  = communities (colored, sized by member count)
 *   - inner circles  = top-100 profiles per community (sized by FlowRank)
 *   - labels inside  = @handle + up to 5 keyword chips
 *
 * Clicking a community zooms in; clicking background zooms back out.
 */

(async function initPack() {
    const width  = window.innerWidth;
    const height = window.innerHeight;

    // ── Fetch data ─────────────────────────────────────────────────────────────
    let data;
    try {
        const res = await fetch(`/api/graph/${encodeURIComponent(ACTIVE_ALIAS)}?mode=packing`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data = await res.json();
    } catch (err) {
        console.error("Pack fetch failed:", err);
        showError("Failed to load community data. Make sure you have run a sync and graph analysis.");
        return;
    }

    // The API returns { name, children, metadata } for packing mode
    const root_data = data.children ? data : null;
    if (!root_data || !root_data.children || root_data.children.length === 0) {
        showError(
            "No community data found.<br>" +
            "Run <b>Sync</b> then let graph analysis complete (triggered automatically after sync)."
        );
        return;
    }

    // ── Colour palette ─────────────────────────────────────────────────────────
    const PALETTE = [
        '#5b8cf8', '#a78bfa', '#10b981', '#f59e0b',
        '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6',
        '#34d399', '#fb923c', '#38bdf8', '#e879f9',
    ];
    const color = d3.scaleOrdinal()
        .domain(root_data.children.map(c => c.id))
        .range(PALETTE);

    // ── D3 Pack layout ─────────────────────────────────────────────────────────
    const pack = d3.pack()
        .size([width - 4, height - 4])
        .padding(6);

    const hierarchy = d3.hierarchy(root_data)
        .sum(d => d.value || 1)
        .sort((a, b) => b.value - a.value);

    const root = pack(hierarchy);

    // ── SVG setup ──────────────────────────────────────────────────────────────
    const svg = d3.select("#pack-svg")
        .attr("width",  width)
        .attr("height", height)
        .attr("viewBox", `0 0 ${width} ${height}`)
        .style("background", "#0c0e14")
        .style("cursor", "pointer");

    // Clip path so labels don't bleed outside their circle
    svg.append("defs").append("clipPath")
        .attr("id", "circle-clip")
        .append("circle").attr("r", 9999);

    const g = svg.append("g");

    // ── Zoom behaviour ─────────────────────────────────────────────────────────
    let currentFocus = root;

    function zoomTo(node, animated = true) {
        // Profile nodes get minimal padding (2px) to zoom in as much as possible for tiny nodes
        const padding = node.depth === 2 ? 1 : 40;
        const scale  = Math.min(width, height) / (node.r * 2 + padding);

        // Offset to keep node centered in the workspace when sidebar is open
        const panel = document.getElementById('info-panel');
        const isPanelOpen = panel && panel.classList.contains('open');
        // Use fixed width matching info-panel.css
        const panelWidth = isPanelOpen ? 380 : 0;
        
        // Center the node in the remaining viewport space
        const availableWidth = width - panelWidth;
        const tx     = (availableWidth / 2) - node.x * scale;
        const ty     = height / 2 - node.y * scale;

        const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);

        if (animated) {
            g.transition().duration(750).ease(d3.easeCubicInOut)
                .attr("transform", transform);
        } else {
            g.attr("transform", transform);
        }

        // Listen for panel toggles to re-center active focus
        if (!window._packPanelListener) {
            window.addEventListener('infopanel:toggle', () => {
                if (currentFocus) zoomTo(currentFocus);
            });
            window._packPanelListener = true;
        }

        currentFocus = node;
        updateLabelVisibility(node, scale, animated);
    }

    function updateLabelVisibility(focus, scale, animated = true) {
        const duration = animated ? 750 : 0;
        const t = d3.transition().duration(duration).ease(d3.easeCubicInOut);

        // Community labels: visible only when looking at the whole root
        label.filter(d => d.depth === 1)
            .transition(t)
            .style("opacity", focus.depth === 0 ? 1 : 0);

        // Profile labels: 
        // - Always show if this specific node is focused.
        // - Show if focused on parent community AND circle is physically large enough (>25px radius on screen)
        label.filter(d => d.depth === 2)
            .transition(t)
            .style("opacity", d => {
                if (d === focus) return 1;
                if (focus.depth === 1 && d.parent === focus && (d.r * scale) > 25) return 1;
                return 0;
            })
            .style("pointer-events", d => (d === focus || (focus.depth === 1 && d.parent === focus)) ? "auto" : "none");

        // Semantic Font Scaling:
        // Community Names (Depth 1)
        label.selectAll(".comm-name")
            .transition(t)
            .style("font-size", d => (Math.min(22, d.r * scale * 0.25) / scale) + "px")
            .style("stroke-width", d => (Math.min(22, d.r * scale * 0.25) / scale * 0.15) + "px");

        // Profile Names (Depth 2)
        label.selectAll(".profile-handle")
            .transition(t)
            .style("font-size", d => {
                const screenTarget = (focus.depth === 2 && d === focus) ? 28 : (focus.depth === 1 ? 15 : 10);
                return (Math.min(screenTarget, d.r * scale * 0.8) / scale) + "px";
            })
            .style("stroke-width", d => {
                const screenTarget = (focus.depth === 2 && d === focus) ? 28 : (focus.depth === 1 ? 15 : 10);
                return (Math.min(screenTarget, d.r * scale * 0.8) / scale * 0.25) + "px";
            });

        // Keywords (Depth 2)
        label.selectAll(".keyword-tag")
            .transition(t)
            .style("font-size", d => {
                const screenTarget = (focus.depth === 2 && d === focus) ? 14 : (focus.depth === 1 ? 8 : 6);
                return (Math.min(screenTarget, d.r * scale * 0.5) / scale) + "px";
            })
            .style("stroke-width", d => {
                const screenTarget = (focus.depth === 2 && d === focus) ? 14 : (focus.depth === 1 ? 8 : 6);
                return (Math.min(screenTarget, d.r * scale * 0.5) / scale * 0.2) + "px";
            });
    }

    // ── Draw circles ───────────────────────────────────────────────────────────
    const node = g.selectAll("circle")
        .data(root.descendants().filter(d => d.depth > 0))
        .join("circle")
        .attr("cx", d => d.x)
        .attr("cy", d => d.y)
        .attr("r",  d => d.r)
        .attr("fill", d => {
            const commId = d.depth === 1 ? d.data.id : d.parent?.data.id;
            return d.depth === 1
                ? color(commId) + "28"   // community ring: translucent
                : color(commId) + "bb";  // profile node: semi-opaque
        })
        .attr("stroke", d => {
            const commId = d.depth === 1 ? d.data.id : d.parent?.data.id;
            return color(commId);
        })
        .attr("stroke-width", d => d.depth === 1 ? 1.5 : 0.5)
        .style("cursor", d => d.depth === 1 ? "pointer" : "default")
        .on("mouseover", function(event, d) {
            if (d.depth === 1) d3.select(this).attr("fill", color(d.data.id) + "50");
        })
        .on("mouseout", function(event, d) {
            d3.select(this).attr("fill",
                d.depth === 1 ? color(d.data.id) + "28" : color(d.parent?.data.id) + "bb"
            );
        })
        .on("click", function(event, d) {
            event.stopPropagation();
            if (d.depth === 1) {
                if (currentFocus === d) {
                    zoomTo(root);           // already zoomed in → zoom out
                    if (typeof InfoPanel !== 'undefined') InfoPanel.close();
                } else {
                    zoomTo(d);             // zoom into community
                    if (typeof InfoPanel !== 'undefined') InfoPanel.open('community', d.data.id);
                }
            } else if (d.depth === 2 && d.data) {
                // Use shared InfoPanel logic
                if (typeof InfoPanel !== 'undefined') InfoPanel.open('profile', d.data.did || d.data.handle);
                zoomTo(d);
            }
        });

    // Background click → zoom out
    svg.on("click", () => {
        zoomTo(root);
        if (typeof InfoPanel !== 'undefined') InfoPanel.close();
    });

    // ── Draw labels ────────────────────────────────────────────────────────────
    const label = g.selectAll("g.label")
        .data(root.descendants().filter(d => d.depth > 0))
        .join("g")
        .attr("class", "label")
        .attr("transform", d => `translate(${d.x},${d.y})`)
        .style("pointer-events", "none")
        .style("text-anchor", "middle");

    // Community labels (visible when zoomed out)
    const commLabel = label.filter(d => d.depth === 1);
    
    commLabel
        .append("text")
        .attr("class", "comm-name")
        .style("font-family", "'DM Mono', monospace")
        .style("fill", d => color(d.data.id))
        .style("font-weight", "700")
        .style("letter-spacing", "0.03em")
        .style("text-rendering", "optimizeLegibility")
        .style("paint-order", "stroke")
        .style("stroke", "#0c0e14")
        .style("stroke-width", "4px")
        .style("stroke-linejoin", "round")
        .each(function(d) {
            const words = d.data.name.split(" ");
            const mid = Math.ceil(words.length / 2);
            const lines = words.length > 1 ? [words.slice(0, mid).join(" "), words.slice(mid).join(" ")] : [d.data.name];
            
            d3.select(this).selectAll("tspan")
                .data(lines)
                .join("tspan")
                .attr("x", 0)
                .attr("dy", (l, i) => i === 0 ? (lines.length > 1 ? "-0.4em" : "0.35em") : "1.1em")
                .text(l => l);
        });

    label.filter(d => d.depth === 1)
        .append("text")
        .attr("dy", "1.1em")
        .style("font-family", "'DM Mono', monospace")
        .style("font-size", d => `${Math.max(7, Math.min(11, d.r / 11))}px`)
        .style("fill", "#6b7280")
        .style("paint-order", "stroke")
        .style("stroke", "#0c0e14")
        .style("stroke-width", "3px")
        .style("stroke-linejoin", "round")
        .text(d => `${d.children?.length ?? 0} profiles`);

    // Profile labels (visible only when zoomed into community)
    const profileLabel = label.filter(d => d.depth === 2)
        .style("opacity", 0);   // hidden initially

    profileLabel.append("text")
        .attr("class", "profile-handle")
        .style("font-family", "'DM Mono', monospace")
        .style("fill", "#e8eaf0")
        .style("font-weight", "700")
        .style("text-rendering", "optimizeLegibility")
        .style("paint-order", "stroke")
        .style("stroke", "#0c0e14")
        .style("stroke-width", "4px")
        .style("stroke-linejoin", "round")
        .each(function(d) {
            // Resilient name resolution: checks for display_name in various possible JSON paths
            let raw = d.data;
            let displayName = raw.display_name || raw.displayName || raw.profile?.display_name || raw.handle || (typeof raw === 'string' ? raw : (raw.name || "Unknown"));
            
            // If it's a handle, ensure it has the @ prefix for clarity
            const isHandle = (displayName === raw.handle || displayName === raw.profile?.handle || displayName.includes('.bsky.social'));
            if (isHandle && !displayName.startsWith('@')) displayName = '@' + displayName;
            
            const words = displayName.split(/\s+/);
            const lines = (words.length > 1 && !isHandle) 
                ? [words.slice(0, Math.ceil(words.length/2)).join(" "), words.slice(Math.ceil(words.length/2)).join(" ")] 
                : [displayName];

            d.handleLines = lines.length;
            
            d3.select(this).selectAll("tspan")
                .data(lines)
                .join("tspan")
                .attr("x", 0)
                .attr("dy", (l, i) => i === 0 ? (lines.length > 1 ? "-0.4em" : "0.35em") : "1.1em")
                .text(l => l);
        });

    // Keyword chips — rendered as small tspan lines below handle
    profileLabel.each(function(d) {
        const kws = d.data.keywords || [];
        if (!kws.length) return;
        const g_el = d3.select(this);
        const startDy = d.handleLines > 1 ? 3.6 : 2.8; // Increased padding to prevent overlap

        kws.slice(0, 3).forEach((kw, i) => {
            g_el.append("text")
                .attr("class", "keyword-tag")
                .attr("dy", `${startDy + i * 1.7}em`) 
                .style("font-family", "'DM Mono', monospace")
                .style("fill", "#94a3b8")
                .style("paint-order", "stroke")
                .style("stroke", "#0c0e14")
                .style("stroke-width", "3px")
                .text(kw);
        });
    });


    // ── Tooltip ────────────────────────────────────────────────────────────────
    const tooltip = d3.select("#pack-tooltip");

    node.filter(d => d.depth === 2)
        .style("cursor", "pointer")
        .on("mouseover.tip", function(event, d) {
            const kws = d.data.keywords?.join(", ") || "—";
            const name = d.data.display_name || d.data.displayName || d.data.handle || (typeof d.data === 'string' ? d.data : d.data.name);

            tooltip
                .style("opacity", 1)
                .html(`
                    <div style="font-weight:700;color:#5b8cf8">${name}</div>
                    <div style="color:#6b7280;font-size:10px">FlowRank: ${(d.data.value * 1000).toFixed(4)}</div>
                    <div style="margin-top:4px;color:#94a3b8;font-size:10px">${kws}</div>
                `)
                .style("left", (event.pageX + 12) + "px")
                .style("top",  (event.pageY - 8)  + "px");
        })
        .on("mouseout.tip", () => tooltip.style("opacity", 0))
        .on("mousemove.tip", function(event) {
            tooltip
                .style("left", (event.pageX + 12) + "px")
                .style("top",  (event.pageY - 8)  + "px");
        });

    // ── Initial zoom ───────────────────────────────────────────────────────────
    zoomTo(root, false);

    // ── Resize ────────────────────────────────────────────────────────────────
    window.addEventListener("resize", () => location.reload());

    // ── Helpers ────────────────────────────────────────────────────────────────
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function showError(msg) {
        d3.select("body").append("div")
            .attr("style", [
                "position:fixed;inset:0;display:flex;flex-direction:column",
                "align-items:center;justify-content:center;background:#0c0e14",
                "color:#6b7280;font-family:'DM Mono',monospace;font-size:0.85rem",
                "text-align:center;padding:2rem;gap:1rem;z-index:200"
            ].join(";"))
            .html(`<div style="font-size:2rem">⭕</div><div>${msg}</div>
                   <a href="/graph/${ALIAS}" style="color:#5b8cf8;margin-top:1rem">← Back to Network Graph</a>`);
    }
})();