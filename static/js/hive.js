async function initHive() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const innerRadius = 40;
    const outerRadius = Math.min(width, height) / 2 - 80;

    let allNodes = [];
    let allLinks = [];
    let selectedNode = null;

    // Placeholders for functions that need access to current scales/coords
    let centerOnNode = () => {};
    let updateHighlighting = () => {};

    const svgElement = d3.select("#hive-svg")
        .attr("width", width)
        .attr("height", height);

    // Add a container group for zoom and pan
    const zoomGroup = svgElement.append("g");
    
    // Add a centering group inside the zoom group
    const svg = zoomGroup.append("g")
        .attr("transform", `translate(${width / 2},${height / 2})`);

    // Zoom setup
    const zoom = d3.zoom()
        .scaleExtent([0.1, 8])
        .on("zoom", (event) => {
            zoomGroup.attr("transform", event.transform);
        });

    svgElement.call(zoom);

    const tooltip = d3.select("#tooltip");
    const thresholdInput = document.getElementById("follower-threshold");
    const thresholdVal = document.getElementById("threshold-val");
    const colorByCommToggle = document.getElementById("color-by-comm");


    // 1. Fetch Data
    const response = await fetch(`/api/graph/${encodeURIComponent(ACTIVE_ALIAS)}?mode=macro&limit=2000`);
    if (!response.ok) return;
    const data = await response.json();
    if (!data.nodes || data.nodes.length === 0) return;

    allNodes = data.nodes;
    allLinks = data.links;

    // Listen for panel toggles to re-center active focus
    if (!window._hivePanelListener) {
        window.addEventListener('infopanel:toggle', (e) => {
            if (!e.detail.open) {
                if (selectedNode) {
                    selectedNode = null;
                    updateHighlighting();
                }
            } else if (selectedNode) {
                centerOnNode(selectedNode, true);
            }
        });
        window._hivePanelListener = true;
    }

    // Adjust slider range based on actual data
    const maxF = d3.max(allNodes, d => d.followers_count) || 1000;
    thresholdInput.max = maxF > 5000 ? 5000 : maxF;

    const commColors = ['#5b8cf8', '#a78bfa', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6'];

    // Initial render
    render(0);

    svgElement.on("click", (event) => {
        if (event.target === svgElement.node()) {
            selectedNode = null;
            if (typeof InfoPanel !== 'undefined') InfoPanel.close();
            updateHighlighting();
        }
    });

    function render(minFollowers) {
        svg.selectAll("*").remove();
        const useCommColor = colorByCommToggle.checked;

    // 1. Threshold-based Filtering
    const filteredNodes = allNodes.filter(d => d.followers_count >= minFollowers);

    // 2. Axis Partitioning Logic
    // We use quantiles to decide which "strength" a node represents most
    const topRank = d3.quantile(filteredNodes.map(d => d.rank || 0).sort(d3.ascending), 0.7);
    // If most nodes have 0 CC, ensure we pick nodes that actually have some clustering
    const topCC = Math.max(0.05, d3.quantile(filteredNodes.map(d => d.cc || 0).sort(d3.ascending), 0.7));

    const nodes = filteredNodes.map(n => {
        let axis = 1; // Default: Activity
        if ((n.cc || 0) > topCC) axis = 2; // Priority 1: Structural Core
        else if ((n.rank || 0) > topRank) axis = 0; // Priority 2: Influencer
        return { ...n, axis };
    });

    // 3. Define scales for each axis specifically
    const scales = {
        0: d3.scaleLog()
            .domain([d3.min(nodes, d => d.rank) || 0.0001, d3.max(nodes, d => d.rank) || 1])
            .range([innerRadius, outerRadius]).clamp(true),
        1: d3.scaleLog()
            .domain([1, d3.max(nodes, d => d.posts_count) || 10000])
            .range([innerRadius, outerRadius]).clamp(true),
        2: d3.scaleLinear()
            .domain([0, 1])
            .range([innerRadius, outerRadius]).clamp(true)
    };

    const colorScale = d3.scaleOrdinal()
        .domain([0, 1, 2])
        .range(["#38bdf8", "#fbbf24", "#10b981"]); 

    // Helper to get coordinates
    const getCoords = (d) => {
        // Specific angles for 3-axis layout (Top, Left-Bottom, Right-Bottom)
        const angles = [-Math.PI / 2, (5 * Math.PI) / 6, Math.PI / 6];
        const angle = angles[d.axis];
                
        let r;
        if (d.axis === 0) r = scales[0](d.rank || 0.0001);
        else if (d.axis === 1) r = scales[1](d.posts_count || 1);
        else r = scales[2](d.cc || 0);
    
        return [r * Math.cos(angle), r * Math.sin(angle)];
    };

    updateHighlighting = () => {
        d3.selectAll(".link")
            .style("stroke-opacity", l => {
                if (!selectedNode) return 0.2;
                return (l.source === selectedNode.did || l.target === selectedNode.did) ? 0.8 : 0.05;
            })
            .style("stroke-width", l => {
                if (!selectedNode) return 1;
                return (l.source === selectedNode.did || l.target === selectedNode.did) ? 2 : 1;
            });

        d3.selectAll(".node")
            .style("stroke", d => d === selectedNode ? "#fff" : "#0f172a")
            .style("stroke-width", d => d === selectedNode ? 2 : 1);
    };

    centerOnNode = (d, animate = true) => {
        const coords = getCoords(d);
        const panel = document.getElementById('info-panel');
        const isPanelOpen = panel && panel.classList.contains('open');
        const panelWidth = isPanelOpen ? 380 : 0;
        
        const targetZoom = 2; // Fixed zoom for selection
        const availableWidth = width - panelWidth;
        
        // Screen position = T.x + (coords[0] + width/2) * S
        const tx = (availableWidth / 2) - (coords[0] + width / 2) * targetZoom;
        const ty = (height / 2) - (coords[1] + height / 2) * targetZoom;

        const transform = d3.zoomIdentity.translate(tx, ty).scale(targetZoom);

        if (animate) {
            svgElement.transition().duration(750).ease(d3.easeCubicInOut)
                .call(zoom.transform, transform);
        } else {
            svgElement.call(zoom.transform, transform);
        }
    };

    // 3. Draw Axes
    [0, 1, 2].forEach(axis => {
        const angles = [-Math.PI / 2, (5 * Math.PI) / 6, Math.PI / 6];
        const angle = angles[axis];
        svg.append("line")
            .attr("class", "axis")
            .attr("x1", innerRadius * Math.cos(angle))
            .attr("y1", innerRadius * Math.sin(angle))
            .attr("x2", outerRadius * Math.cos(angle))
            .attr("y2", outerRadius * Math.sin(angle));
        
        const labels = ["Influence (FlowRank)", "Activity (Posts)", "Core (Clustering)"];
        svg.append("text")
            .attr("class", "axis-label")
            .attr("x", (outerRadius + 20) * Math.cos(angle))
            .attr("y", (outerRadius + 20) * Math.sin(angle))
            .attr("text-anchor", "middle")
            .text(labels[axis]);
    });

    // 4. Draw Links
    const nodeMap = new Map(nodes.map(n => [n.did, n]));
    const validLinks = allLinks.filter(l => nodeMap.has(l.source) && nodeMap.has(l.target));

    svg.append("g")
        .selectAll(".link")
        .data(validLinks)
        .enter().append("path")
        .attr("class", "link")
        .attr("stroke", d => {
            const s = nodeMap.get(d.source);
            if (useCommColor && s.comm != null) return commColors[s.comm % commColors.length];
            return colorScale(s.axis);
        })
        .attr("d", d => {
            const s = nodeMap.get(d.source);
            const t = nodeMap.get(d.target);
            if (s.axis === t.axis) return null; // Only draw cross-axis links for clarity

            const start = getCoords(s);
            const end = getCoords(t);
            
            // Use a quadratic bezier curve for that distinct "Hive Plot" look
            // Control point is at the center
            return `M${start[0]},${start[1]} Q0,0 ${end[0]},${end[1]}`;
        });

    // 5. Draw Nodes
    svg.append("g")
        .selectAll(".node")
        .data(nodes)
        .enter().append("circle")
        .attr("class", "node")
        .attr("r", 4)
        .attr("fill", d => {
            if (useCommColor && d.comm != null) return commColors[d.comm % commColors.length];
            return colorScale(d.axis);
        })
        .attr("cx", d => getCoords(d)[0])
        .attr("cy", d => getCoords(d)[1])
        .on("click", (event, d) => {
            event.stopPropagation();
            if (selectedNode === d) {
                selectedNode = null;
                if (typeof InfoPanel !== 'undefined') InfoPanel.close();
            } else {
                selectedNode = d;
                if (typeof InfoPanel !== 'undefined') InfoPanel.open('profile', d.did || d.handle);
                centerOnNode(d);
            }
            updateHighlighting();
        })
        .on("mouseover", (event, d) => {
            tooltip.style("opacity", 1)
                .html(`
                    <div style="font-weight:bold; color:#38bdf8">@${d.handle}</div>
                    <div>Rank: ${(d.rank * 1000).toFixed(4)}</div>
                    <div>Posts: ${d.posts_count}</div>
                    <div>Clustering: ${(d.cc || 0).toFixed(3)}</div>
                    <div style="font-size:10px; margin-top:4px; color:#94a3b8">Primary Trait: ${["Influence", "Activity", "Community Core"][d.axis]}</div>
                `)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 10) + "px");
            
            // Highlight links
            d3.selectAll(".link")
                .style("stroke-opacity", l => {
                    if (selectedNode) return (l.source === selectedNode.did || l.target === selectedNode.did) ? 0.8 : 0.05;
                    return (l.source === d.did || l.target === d.did) ? 0.8 : 0.05;
                })
                .style("stroke-width", l => {
                    if (selectedNode) return (l.source === selectedNode.did || l.target === selectedNode.did) ? 2 : 1;
                    return (l.source === d.did || l.target === d.did) ? 2 : 1;
                });
        })
        .on("mouseout", () => {
            tooltip.style("opacity", 0);
            updateHighlighting();
        });

        updateHighlighting();
    }

    // Slider Listener
    thresholdInput.addEventListener("input", (e) => {
        const val = parseInt(e.target.value);
        thresholdVal.textContent = val.toLocaleString();
        render(val);
    });

    colorByCommToggle.addEventListener("change", () => {
        render(parseInt(thresholdInput.value));
    });
}

initHive();
window.addEventListener('resize', () => location.reload());