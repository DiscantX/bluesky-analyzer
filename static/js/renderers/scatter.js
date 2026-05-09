/**
 * static/js/renderers/scatter.js
 * Scatter plot SVG renderer.
 * Registers itself on ChartBase.RENDERERS["scatter"].
 */

(function () {
    'use strict';

    function renderScatterSVG(container, apiResponse, options = {}) {
        const { data, axes, total, truncated } = apiResponse;
        const { interactive, animated, colorPalette, cssVars: css, onPointClick } = options;

        // Clear previous
        container.innerHTML = '';
        if (!data || data.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No data to display</div>`;
            return;
        }

        const W = container.clientWidth  || 800;
        const H = container.clientHeight || 500;
        const margin = { top: 24, right: 32, bottom: 60, left: 72 };
        const width  = W - margin.left - margin.right;
        const height = H - margin.top  - margin.bottom;

        const svg = d3.select(container).append('svg')
            .attr('width', W).attr('height', H)
            .style('overflow', 'visible');

        const defs = svg.append('defs');
        // Clip path
        defs.append('clipPath').attr('id', 'scatter-clip')
            .append('rect').attr('width', width).attr('height', height);

        const g = svg.append('g')
            .attr('transform', `translate(${margin.left},${margin.top})`);

        // ── Scales ────────────────────────────────────────────────────────────
        const xCfg = axes.x || {};
        const yCfg = axes.y || {};
        const cCfg = axes.color;
        const sCfg = axes.size;

        const xDomain = xCfg.domain || [0, 1];
        const yDomain = yCfg.domain || [0, 1];

        const xScale = ChartBase.buildScale(xCfg.scale || 'linear', xDomain, [0, width]);
        const yScale = ChartBase.buildScale(yCfg.scale || 'linear', yDomain, [height, 0]);

        // Color scale
        let colorScale;
        if (cCfg) {
            const colorDomain = [...new Set(data.map(d => d.color).filter(v => v != null))].sort();
            colorScale = typeof colorDomain[0] === 'number'
                ? d3.scaleSequential().domain([Math.min(...colorDomain), Math.max(...colorDomain)]).interpolator(d3.interpolatePlasma)
                : d3.scaleOrdinal().domain(colorDomain).range(colorPalette);
        }

        // Size scale
        let sizeScale;
        if (sCfg) {
            const sizeDomain = sCfg.domain || [0, 1];
            sizeScale = d3.scaleSqrt().domain([0, Math.max(...sizeDomain, 1)]).range([2, 12]).clamp(true);
        }

        // ── Grid ──────────────────────────────────────────────────────────────
        ChartBase.drawGridLines(g, xScale, yScale, width, height, css);

        // ── Axes ──────────────────────────────────────────────────────────────
        const xAxisG = g.append('g')
            .attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(xScale).ticks(6).tickFormat(d => ChartBase.fmtVal(d)));

        xAxisG.select('.domain').attr('stroke', css.border);
        xAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        xAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');

        // X label
        g.append('text')
            .attr('x', width / 2).attr('y', height + 48)
            .attr('text-anchor', 'middle')
            .attr('fill', css.muted)
            .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
            .text(xCfg.label || 'X');

        const yAxisG = g.append('g')
            .call(d3.axisLeft(yScale).ticks(5).tickFormat(d => ChartBase.fmtVal(d)));

        yAxisG.select('.domain').attr('stroke', css.border);
        yAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        yAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');

        // Y label
        g.append('text')
            .attr('transform', 'rotate(-90)')
            .attr('x', -height / 2).attr('y', -56)
            .attr('text-anchor', 'middle')
            .attr('fill', css.muted)
            .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
            .text(yCfg.label || 'Y');

        // ── Points ────────────────────────────────────────────────────────────
        const pointsG = g.append('g').attr('clip-path', 'url(#scatter-clip)');

        const tooltip = new ChartBase.ChartTooltip(container);
        let selectedPoint = null;

        const pointsData = data.filter(d => d.x != null && d.y != null);

        const circles = pointsG.selectAll('circle')
            .data(pointsData)
            .join('circle')
            .attr('cx', d => xScale(d.x))
            .attr('cy', d => yScale(d.y))
            .attr('r', d => sCfg && sizeScale && d.size != null ? sizeScale(d.size) : 4)
            .attr('fill', d => {
                if (colorScale && d.color != null) return colorScale(d.color);
                return colorPalette[0];
            })
            .attr('fill-opacity', 0.72)
            .attr('stroke', css.surface)
            .attr('stroke-width', 0.5)
            .style('cursor', interactive ? 'pointer' : 'default')
            .style('transition', 'r 0.15s, fill-opacity 0.15s');

        if (animated) {
            circles
                .attr('r', 0)
                .attr('fill-opacity', 0)
                .transition().duration(600).delay((d, i) => Math.min(i * 0.5, 300))
                .attr('r', d => sCfg && sizeScale && d.size != null ? sizeScale(d.size) : 4)
                .attr('fill-opacity', 0.72);
        }

        if (interactive) {
            circles
                .on('mouseover', function (event, d) {
                    d3.select(this).raise()
                        .attr('r', function () { return parseFloat(d3.select(this).attr('r')) * 1.6; })
                        .attr('fill-opacity', 1)
                        .attr('stroke', css.accent)
                        .attr('stroke-width', 1.5);
                    tooltip.show(ChartBase.buildTooltipHtml(d, axes), event);
                })
                .on('mousemove', (event) => tooltip.move(event))
                .on('mouseout', function (event, d) {
                    const isSelected = selectedPoint === d;
                    d3.select(this)
                        .attr('r', sCfg && sizeScale && d.size != null ? sizeScale(d.size) : 4)
                        .attr('fill-opacity', isSelected ? 1 : 0.72)
                        .attr('stroke', isSelected ? css.accent : css.surface)
                        .attr('stroke-width', isSelected ? 1.5 : 0.5);
                    tooltip.hide();
                })
                .on('click', function (event, d) {
                    event.stopPropagation();
                    selectedPoint = d;
                    // Reset all
                    circles.attr('fill-opacity', 0.35).attr('stroke', css.surface).attr('stroke-width', 0.5);
                    d3.select(this)
                        .attr('fill-opacity', 1)
                        .attr('stroke', css.accent)
                        .attr('stroke-width', 1.5)
                        .raise();
                    if (onPointClick && d.did) onPointClick(d.did, d);
                });
        }

        // Click background to deselect
        svg.on('click', () => {
            selectedPoint = null;
            circles.attr('fill-opacity', 0.72).attr('stroke', css.surface).attr('stroke-width', 0.5);
        });

        // ── Truncation notice ─────────────────────────────────────────────────
        if (truncated) {
            g.append('text')
                .attr('x', width).attr('y', -8)
                .attr('text-anchor', 'end')
                .attr('fill', css.muted2)
                .style('font-family', css.mono).style('font-size', '9px')
                .text(`Showing ${data.length.toLocaleString()} of ${total.toLocaleString()} — raise limit to see more`);
        }

        // ── Color legend ──────────────────────────────────────────────────────
        if (colorScale && cCfg && typeof colorScale.domain === 'function' && colorScale.domain().length <= 12) {
            const legendG = g.append('g').attr('transform', `translate(${width + 8}, 0)`);
            const domain = colorScale.domain();
            domain.slice(0, 10).forEach((val, i) => {
                const row = legendG.append('g').attr('transform', `translate(0, ${i * 16})`);
                row.append('circle').attr('r', 4).attr('fill', colorScale(val)).attr('cy', 7).attr('cx', 4);
                row.append('text')
                    .attr('x', 12).attr('y', 11)
                    .attr('fill', css.muted)
                    .style('font-family', css.mono).style('font-size', '9px')
                    .text(cCfg.label === 'Community' ? `Comm ${val}` : String(val));
            });
        }

        // ── Zoom & pan ────────────────────────────────────────────────────────
        const zoom = d3.zoom()
            .scaleExtent([0.5, 20])
            .on('zoom', (event) => {
                const t = event.transform;
                const newX = t.rescaleX(xScale);
                const newY = t.rescaleY(yScale);
                circles
                    .attr('cx', d => newX(d.x))
                    .attr('cy', d => newY(d.y));
                xAxisG.call(d3.axisBottom(newX).ticks(6).tickFormat(d => ChartBase.fmtVal(d)));
                xAxisG.select('.domain').attr('stroke', css.border);
                xAxisG.selectAll('.tick line').attr('stroke', css.muted2);
                xAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
                yAxisG.call(d3.axisLeft(newY).ticks(5).tickFormat(d => ChartBase.fmtVal(d)));
                yAxisG.select('.domain').attr('stroke', css.border);
                yAxisG.selectAll('.tick line').attr('stroke', css.muted2);
                yAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
            });

        svg.call(zoom);
        svg.on('dblclick.zoom', () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity));

        return {
            destroy: () => { tooltip.destroy(); container.innerHTML = ''; },
        };
    }

    ChartBase.registerRenderer('scatter', { svg: renderScatterSVG });

})();
