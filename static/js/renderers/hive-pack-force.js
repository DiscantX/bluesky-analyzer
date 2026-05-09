/**
 * static/js/renderers/hive.js
 * Hive plot SVG renderer — adapted from static/js/hive.js, now registry-aware.
 */

(function () {
    'use strict';

    function renderHiveSVG(container, apiResponse, options = {}) {
        const { data, axes } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick } = options;

        container.innerHTML = '';
        if (!data || data.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No data</div>`;
            return;
        }

        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;
        const cx = W / 2, cy = H / 2;
        const innerRadius = 40;
        const outerRadius = Math.min(W, H) / 2 - 80;

        // Collect axis keys (axis_0, axis_1, axis_2, ...)
        const axisKeys = Object.keys(axes).filter(k => k.startsWith('axis_')).sort();
        const numAxes  = axisKeys.length;
        if (numAxes < 2) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">Need at least 2 axes</div>`;
            return;
        }

        const svgEl = d3.select(container).append('svg').attr('width', W).attr('height', H);
        const g = svgEl.append('g').attr('transform', `translate(${cx},${cy})`);

        // Scales per axis
        const scales = {};
        axisKeys.forEach(key => {
            const cfg = axes[key];
            const domain = cfg.domain || [0, 1];
            scales[key] = ChartBase.buildScale(cfg.scale || 'log', [Math.max(domain[0] || 1e-9, 1e-10), Math.max(domain[1] || 1, 1e-9)], [innerRadius, outerRadius]);
        });

        // Assign each node to the axis where it ranks highest relative to domain
        const assignAxis = (d) => {
            let bestAxis = axisKeys[0], bestPct = -1;
            axisKeys.forEach(key => {
                const cfg = axes[key];
                const domain = cfg.domain || [0, 1];
                const val = d[key];
                if (val == null) return;
                const pct = (val - domain[0]) / Math.max(domain[1] - domain[0], 1e-9);
                if (pct > bestPct) { bestPct = pct; bestAxis = key; }
            });
            return bestAxis;
        };

        const getAngle = (axisIdx) => {
            return -Math.PI / 2 + (axisIdx / numAxes) * 2 * Math.PI;
        };

        const getCoords = (d) => {
            const axisKey = d._axis;
            const axisIdx = axisKeys.indexOf(axisKey);
            const angle   = getAngle(axisIdx);
            const val     = d[axisKey];
            const r       = val != null ? scales[axisKey](val) : innerRadius;
            return [r * Math.cos(angle), r * Math.sin(angle)];
        };

        const nodes = data.map(d => ({ ...d, _axis: assignAxis(d) }));

        // Link color scale
        const linkColorCfg = axes.link_color;
        const commColors   = colorPalette;
        const linkColorFn  = (d) => {
            if (linkColorCfg && d.color != null) {
                return commColors[Math.abs(Math.round(d.color)) % commColors.length];
            }
            const axisIdx = axisKeys.indexOf(d._axis);
            return commColors[axisIdx % commColors.length];
        };

        // Draw axes
        axisKeys.forEach((key, i) => {
            const angle = getAngle(i);
            g.append('line')
                .attr('x1', innerRadius * Math.cos(angle)).attr('y1', innerRadius * Math.sin(angle))
                .attr('x2', outerRadius * Math.cos(angle)).attr('y2', outerRadius * Math.sin(angle))
                .attr('stroke', css.border).attr('stroke-width', 2);

            const cfg = axes[key];
            g.append('text')
                .attr('x', (outerRadius + 20) * Math.cos(angle))
                .attr('y', (outerRadius + 20) * Math.sin(angle))
                .attr('text-anchor', 'middle')
                .attr('fill', css.muted)
                .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
                .text(cfg.label || key);
        });

        // Draw cross-axis links
        const nodeMap = new Map(nodes.map(n => [n.did || n.handle, n]));
        const tooltip = new ChartBase.ChartTooltip(container);

        // Draw nodes
        const circles = g.selectAll('.hive-node').data(nodes).join('circle')
            .attr('class', 'hive-node')
            .attr('cx', d => getCoords(d)[0])
            .attr('cy', d => getCoords(d)[1])
            .attr('r', 3.5)
            .attr('fill', d => linkColorFn(d))
            .attr('fill-opacity', 0.8)
            .style('cursor', 'pointer');

        circles
            .on('mouseover', function (event, d) {
                d3.select(this).attr('r', 6).attr('fill-opacity', 1).attr('stroke', css.accent).attr('stroke-width', 1.5);
                const axisLabels = {};
                axisKeys.forEach(k => { if (axes[k]) axisLabels[k] = axes[k]; });
                tooltip.show(ChartBase.buildTooltipHtml(d, axisLabels), event);
            })
            .on('mousemove', (e) => tooltip.move(e))
            .on('mouseout', function () {
                d3.select(this).attr('r', 3.5).attr('fill-opacity', 0.8).attr('stroke', 'none').attr('stroke-width', 0);
                tooltip.hide();
            })
            .on('click', (event, d) => { if (onPointClick && d.did) onPointClick(d.did, d); });

        return { destroy: () => { tooltip.destroy(); container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('hive', { svg: renderHiveSVG });
})();


/**
 * static/js/renderers/circle-packing.js
 * Circle packing renderer — adapted from static/js/pack.js.
 */

(function () {
    'use strict';

    function renderCirclePackingSVG(container, apiResponse, options = {}) {
        const { data } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick } = options;

        container.innerHTML = '';

        // data here is the hierarchy object from the packing query
        const rootData = data && data.children ? data : (data && Array.isArray(data) ? { name: 'Root', children: data } : null);
        if (!rootData || !rootData.children || rootData.children.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No community data — run a sync and graph analysis first</div>`;
            return;
        }

        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;

        const color = d3.scaleOrdinal()
            .domain(rootData.children.map(c => c.id))
            .range(colorPalette);

        const pack = d3.pack().size([W - 4, H - 4]).padding(6);
        const hierarchy = d3.hierarchy(rootData).sum(d => d.value || 1).sort((a, b) => b.value - a.value);
        const root = pack(hierarchy);

        const svg = d3.select(container).append('svg')
            .attr('width', W).attr('height', H)
            .style('cursor', 'pointer');

        const g = svg.append('g');
        let currentFocus = root;

        const zoomTo = (node, animated = true) => {
            const scale = Math.min(W, H) / (node.r * 2 + 40);
            const tx = W / 2 - node.x * scale;
            const ty = H / 2 - node.y * scale;
            const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);
            if (animated) g.transition().duration(600).ease(d3.easeCubicInOut).attr('transform', transform);
            else g.attr('transform', transform);
            currentFocus = node;
            label.filter(d => d.depth === 1).style('opacity', node.depth === 0 ? 1 : 0);
            label.filter(d => d.depth === 2).style('opacity', d => node.depth === 1 && d.parent === node ? 1 : 0);
        };

        const node = g.selectAll('circle')
            .data(root.descendants().filter(d => d.depth > 0))
            .join('circle')
            .attr('cx', d => d.x).attr('cy', d => d.y).attr('r', d => d.r)
            .attr('fill', d => {
                const cid = d.depth === 1 ? d.data.id : d.parent?.data.id;
                return d.depth === 1 ? color(cid) + '28' : color(cid) + 'bb';
            })
            .attr('stroke', d => color(d.depth === 1 ? d.data.id : d.parent?.data.id))
            .attr('stroke-width', d => d.depth === 1 ? 1.5 : 0.5)
            .on('click', function (event, d) {
                event.stopPropagation();
                if (d.depth === 1) {
                    zoomTo(currentFocus === d ? root : d);
                } else if (d.depth === 2 && d.data && onPointClick) {
                    onPointClick(d.data.did || d.data.handle, d.data);
                }
            });

        const label = g.selectAll('text')
            .data(root.descendants().filter(d => d.depth > 0))
            .join('text')
            .attr('x', d => d.x).attr('y', d => d.y)
            .attr('text-anchor', 'middle')
            .style('pointer-events', 'none')
            .style('font-family', css.mono)
            .style('fill', d => d.depth === 1 ? color(d.data.id) : css.text)
            .style('font-size', d => d.depth === 1 ? `${Math.max(8, Math.min(14, d.r / 5))}px` : `${Math.max(6, Math.min(10, d.r / 3))}px`)
            .style('opacity', d => d.depth === 1 ? 1 : 0)
            .text(d => d.depth === 1 ? (d.data.name || `Comm ${d.data.id}`) : `@${d.data.handle || ''}`);

        svg.on('click', () => zoomTo(root));
        zoomTo(root, false);

        return { destroy: () => { container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('circle_packing', { svg: renderCirclePackingSVG });
})();


/**
 * static/js/renderers/force-directed.js
 * Force-directed graph renderer using force-graph library.
 * Falls back to a simple D3 simulation if force-graph is unavailable.
 */

(function () {
    'use strict';

    function renderForceDirected(container, apiResponse, options = {}) {
        const { data, axes } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick, interactive } = options;

        container.innerHTML = '';

        const nodes = (data && data.nodes) ? data.nodes : [];
        const links = (data && data.links) ? data.links : [];

        if (nodes.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No graph data — run a sync with graph analysis</div>`;
            return;
        }

        // Use ForceGraph library if available (loaded on graph.html)
        if (typeof ForceGraph === 'function') {
            const fg = ForceGraph()(container)
                .graphData({ nodes: nodes.map(n => ({ ...n, id: n.did || n.id })), links })
                .nodeId('id')
                .nodeLabel(n => `@${n.handle}`)
                .nodeColor(n => colorPalette[(n.comm || 0) % colorPalette.length])
                .nodeVal(n => Math.sqrt(n.rank || 0.001) * 100 + 1)
                .linkColor(() => 'rgba(255,255,255,0.08)')
                .backgroundColor(css.bg || '#0c0e14')
                .onNodeClick(n => { if (onPointClick && n.did) onPointClick(n.did, n); });

            if (!interactive) fg.pauseAnimation();
            return { destroy: () => { container.innerHTML = ''; } };
        }

        // Fallback: D3 simulation
        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;

        const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
        const g   = svg.append('g');

        const colorScale = d3.scaleOrdinal().domain([...new Set(nodes.map(n => n.comm))]).range(colorPalette);

        const sim = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.did || d.id).distance(40))
            .force('charge', d3.forceManyBody().strength(-80))
            .force('center', d3.forceCenter(W / 2, H / 2))
            .force('collide', d3.forceCollide(6));

        const link = g.append('g').selectAll('line').data(links).join('line')
            .attr('stroke', 'rgba(255,255,255,0.07)').attr('stroke-width', 0.5);

        const nodeG = g.append('g').selectAll('circle').data(nodes).join('circle')
            .attr('r', n => Math.sqrt(n.rank || 0.001) * 50 + 2)
            .attr('fill', n => colorScale(n.comm))
            .attr('fill-opacity', 0.8)
            .style('cursor', 'pointer')
            .call(d3.drag()
                .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
                .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
                .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

        if (onPointClick) nodeG.on('click', (e, d) => { if (d.did) onPointClick(d.did, d); });

        const tooltip = new ChartBase.ChartTooltip(container);
        nodeG.on('mouseover', (e, d) => { tooltip.show(`<div style="color:var(--accent);font-weight:700">@${d.handle}</div><div style="color:var(--muted);font-size:0.68rem">FlowRank: ${ChartBase.fmtVal(d.rank)}</div>`, e); })
             .on('mousemove', (e) => tooltip.move(e))
             .on('mouseout', () => tooltip.hide());

        svg.call(d3.zoom().on('zoom', e => g.attr('transform', e.transform)));

        sim.on('tick', () => {
            link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
            nodeG.attr('cx', d => d.x).attr('cy', d => d.y);
        });

        if (!interactive) sim.stop();

        return { destroy: () => { sim.stop(); tooltip.destroy(); container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('force_directed', { svg: renderForceDirected, webgl: renderForceDirected });
})();
