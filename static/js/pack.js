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
        const res = await fetch(`/api/graph/${ALIAS}?mode=packing`);
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
        const scale  = Math.min(width, height) / (node.r * 2 + 40);
        const tx     = width  / 2 - node.x * scale;
        const ty     = height / 2 - node.y * scale;

        const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);

        if (animated) {
            g.transition().duration(650).ease(d3.easeCubicInOut)
                .attr("transform", transform);
        } else {
            g.attr("transform", transform);
        }

        currentFocus = node;
        updateLabelVisibility(node, scale);
    }

    function updateLabelVisibility(focus, scale) {
        // Show profile-level labels only when zoomed into a community
        const isZoomedIn = focus.depth === 1;

        label.filter(d => d.depth === 2)
            .transition().duration(300)
            .style("opacity", isZoomedIn ? 1 : 0)
            .style("pointer-events", isZoomedIn ? "auto" : "none");

        label.filter(d => d.depth === 1)
            .transition().duration(300)
            .style("opacity", isZoomedIn ? 0 : 1);
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
                } else {
                    zoomTo(d);             // zoom into community
                }
            } else if (d.depth === 2 && d.data.did) {
                window.open(`https://bsky.app/profile/${d.data.did}`, "_blank");
            }
        });

    // Background click → zoom out
    svg.on("click", () => zoomTo(root));

    // ── Draw labels ────────────────────────────────────────────────────────────
    const label = g.selectAll("g.label")
        .data(root.descendants().filter(d => d.depth > 0))
        .join("g")
        .attr("class", "label")
        .attr("transform", d => `translate(${d.x},${d.y})`)
        .style("pointer-events", "none")
        .style("text-anchor", "middle");

    // Community labels (visible when zoomed out)
    label.filter(d => d.depth === 1)
        .append("text")
        .attr("class", "comm-name")
        .attr("dy", "-0.2em")
        .style("font-family", "'DM Mono', monospace")
        .style("font-size", d => `${Math.max(8, Math.min(14, d.r / 8))}px`)
        .style("fill", d => color(d.data.id))
        .style("font-weight", "700")
        .style("letter-spacing", "0.03em")
        .text(d => d.data.name);

    label.filter(d => d.depth === 1)
        .append("text")
        .attr("dy", "1.1em")
        .style("font-family", "'DM Mono', monospace")
        .style("font-size", d => `${Math.max(7, Math.min(11, d.r / 11))}px`)
        .style("fill", "#6b7280")
        .text(d => `${d.children?.length ?? 0} profiles`);

    // Profile labels (visible only when zoomed into community)
    const profileLabel = label.filter(d => d.depth === 2)
        .style("opacity", 0);   // hidden initially

    profileLabel.append("text")
        .attr("class", "profile-handle")
        .attr("dy", d => d.data.keywords?.length ? "-0.6em" : "0.35em")
        .style("font-family", "'DM Mono', monospace")
        .style("font-size", d => `${clamp(d.r * 0.28, 6, 11)}px`)
        .style("fill", "#e8eaf0")
        .style("font-weight", "600")
        .text(d => `@${d.data.name}`);

    // Keyword chips — rendered as small tspan lines below handle
    profileLabel.each(function(d) {
        const kws = d.data.keywords || [];
        if (!kws.length) return;
        const g_el = d3.select(this);
        const fs = clamp(d.r * 0.2, 5, 9);

        kws.slice(0, 3).forEach((kw, i) => {
            g_el.append("text")
                .attr("dy", `${0.8 + i * 1.1}em`)
                .style("font-family", "'DM Mono', monospace")
                .style("font-size", `${fs}px`)
                .style("fill", "#94a3b8")
                .text(kw);
        });
    });

    // ── Tooltip ────────────────────────────────────────────────────────────────
    const tooltip = d3.select("#pack-tooltip");

    node.filter(d => d.depth === 2)
        .style("cursor", "pointer")
        .on("mouseover.tip", function(event, d) {
            const kws = d.data.keywords?.join(", ") || "—";
            tooltip
                .style("opacity", 1)
                .html(`
                    <div style="font-weight:700;color:#5b8cf8">@${d.data.name}</div>
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