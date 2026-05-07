async function initPack() {
    const width = window.innerWidth;
    const height = window.innerHeight;

    // 1. Fetch the hierarchical data from the new packing endpoint
    const response = await fetch(`/api/graph/${ALIAS}?mode=packing`);
    if (!response.ok) return;
    const data = await response.json();

    console.log("Packing Data Received:", data);

    if (!data.children || data.children.length === 0) {
        d3.select("body").append("div")
            .attr("class", "state-box")
            .attr("style", "position:fixed; inset:0; z-index:100; background:var(--bg)")
            .html(`
                <div>⭕</div>
                <div>No community data found. Please run <b>Graph Analysis</b> from the dashboard to cluster your network.</div>
            `);
        return;
    }

    const colorScale = d3.scaleOrdinal()
        .range(['#5b8cf8', '#a78bfa', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6']);

    // 2. Initialize the Pack Layout
    const pack = data => d3.pack()
        .size([width, height])
        .padding(3)
      (d3.hierarchy(data)
        .sum(d => d.value) // Radius determined by FlowRank
        .sort((a, b) => b.value - a.value));

    const root = pack(data);
    let focus = root;
    let view;

    // 3. Create SVG Container
    const svg = d3.select("#pack-svg")
        .attr("width", width)
        .attr("height", height)
        .attr("viewBox", `-${width / 2} -${height / 2} ${width} ${height}`)
        .style("display", "block")
        .style("background", "#0c0e14")
        .style("cursor", "pointer")
        .on("click", (event) => zoom(event, root));

    // 4. Draw Circles
    const node = svg.append("g")
      .selectAll("circle")
      .data(root.descendants().slice(1))
      .join("circle")
        .attr("fill", d => d.children ? colorScale(d.data.id) : "#1e293b")
        .attr("fill-opacity", d => d.children ? 0.2 : 1)
        .attr("stroke", d => d.children ? colorScale(d.data.id) : "none")
        .on("mouseover", function() { d3.select(this).attr("stroke", "#fff"); })
        .on("mouseout", function() { d3.select(this).attr("stroke", d => d.children ? colorScale(d.data.id) : "none"); })
        .on("click", (event, d) => focus !== d && (zoom(event, d), event.stopPropagation()));

    // 5. Draw Labels and Keywords
    const label = svg.append("g")
        .style("pointer-events", "none")
        .attr("text-anchor", "middle")
      .selectAll("g")
      .data(root.descendants())
      .join("g")
        .style("fill-opacity", d => d.parent === root ? 1 : 0)
        .style("display", d => d.parent === root ? "inline" : "none");

    // Main Label (Community Name or Profile Handle)
    label.append("text")
        .attr("class", "label")
        .text(d => d.data.name);

    // Secondary Keywords (Only for individual profiles/leaf nodes)
    label.filter(d => !d.children).append("text")
        .attr("class", "keyword")
        .attr("dy", "1.2em")
        .text(d => d.data.keywords ? d.data.keywords.slice(0, 5).join(", ") : "");

    // Initial Zoom State
    if (root) {
        zoomTo([root.x, root.y, root.r * 2]);
    }

    function zoomTo(v) {
        const k = width / (v[2] || 1);
        view = v;
        label.attr("transform", d => `translate(${(d.x - v[0]) * k}, ${(d.y - v[1]) * k})`);
        node.attr("transform", d => `translate(${(d.x - v[0]) * k}, ${(d.y - v[1]) * k})`);
        node.attr("r", d => Math.max(0, d.r * k));
    }

    function zoom(event, d) {
        focus = d;

        const transition = svg.transition()
            .duration(750)
            .tween("zoom", d => {
                const i = d3.interpolateZoom(view, [focus.x, focus.y, focus.r * 2]);
                return t => zoomTo(i(t));
            });

        label
          .filter(function(l) { return l.parent === focus || this.style.display === "inline"; })
          .transition(transition)
            .style("fill-opacity", l => l.parent === focus ? 1 : 0)
            .on("start", function(l) { if (l.parent === focus) this.style.display = "inline"; })
            .on("end", function(l) { if (l.parent !== focus) this.style.display = "none"; });
    }
}

initPack();

// Handle resizing to keep the visualization centered
window.addEventListener('resize', () => {
    const newWidth = window.innerWidth;
    const newHeight = window.innerHeight;
    d3.select("#pack-svg")
        .attr("width", newWidth)
        .attr("height", newHeight)
        .attr("viewBox", `-${newWidth / 2} -${newHeight / 2} ${newWidth} ${newHeight}`);
});