/**
 * static/js/renderers/histogram.js
 * Histogram SVG renderer.
 */

(function () {
    'use strict';

    function renderHistogramSVG(container, apiResponse, options = {}) {
        const { data, axes } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick, animated } = options;

        container.innerHTML = '';
        if (!data || data.length === 0) {
            container.innerHTML = `<div class="state-box">No data for this variable.<br><small style="color:var(--muted)">The selected field may be empty for these accounts.</small></div>`;
            return;
        }

        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;
        const margin = { top: 24, right: 32, bottom: 60, left: 72 };
        const width  = W - margin.left - margin.right;
        const height = H - margin.top  - margin.bottom;

        const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
        const g   = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        const xCfg = axes.x || {};
        
        // Filter out null/undefined/NaN but keep 0
        const values = data.map(d => d.x).filter(v => v !== null && v !== undefined && isFinite(v));

        if (values.length === 0) {
            container.innerHTML = `<div class="state-box">No numeric data available for "${xCfg.label || 'X'}" in this selection.</div>`;
            return;
        }

        const xScale = ChartBase.buildScale(xCfg.scale || 'linear', xCfg.domain || d3.extent(values), [0, width]);
        const binCount = 30;
        const bins = d3.bin().domain(xScale.domain()).thresholds(xScale.ticks(binCount))(values);

        const yScale = d3.scaleLinear()
            .domain([0, d3.max(bins, d => d.length) * 1.05])
            .range([height, 0]);

        ChartBase.drawGridLines(g, xScale, yScale, width, height, css);

        // Axes
        const xAxisG = g.append('g').attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(xScale).ticks(8).tickFormat(d => ChartBase.fmtVal(d)));
        xAxisG.select('.domain').attr('stroke', css.border);
        xAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        xAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
        g.append('text').attr('x', width / 2).attr('y', height + 48).attr('text-anchor', 'middle')
            .attr('fill', css.muted).style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
            .text(xCfg.label || 'Value');

        const yAxisG = g.append('g').call(d3.axisLeft(yScale).ticks(5).tickFormat(d => d3.format(',.0f')(d)));
        yAxisG.select('.domain').attr('stroke', css.border);
        yAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        yAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
        g.append('text').attr('transform', 'rotate(-90)').attr('x', -height / 2).attr('y', -56)
            .attr('text-anchor', 'middle').attr('fill', css.muted)
            .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600').text('Count');

        const tooltip = new ChartBase.ChartTooltip(container);

        const bars = g.selectAll('.bar').data(bins).join('rect')
            .attr('class', 'bar')
            .attr('x', d => xScale(d.x0) + 1)
            .attr('width', d => Math.max(0, xScale(d.x1) - xScale(d.x0) - 1))
            .attr('y', d => animated ? height : yScale(d.length))
            .attr('height', d => animated ? 0 : height - yScale(d.length))
            .attr('fill', colorPalette[0])
            .attr('fill-opacity', 0.7)
            .attr('rx', 2)
            .style('cursor', 'pointer');

        if (animated) {
            bars.transition().duration(600).delay((d, i) => i * 10)
                .attr('y', d => yScale(d.length))
                .attr('height', d => height - yScale(d.length));
        }

        bars.on('mouseover', function (event, d) {
            d3.select(this).attr('fill-opacity', 1).attr('fill', css.accent);
            tooltip.show(`
                <div style="color:${css.accent};font-weight:700;margin-bottom:4px">${ChartBase.fmtVal(d.x0)} – ${ChartBase.fmtVal(d.x1)}</div>
                <div style="display:flex;justify-content:space-between;gap:1rem">
                    <span style="color:${css.muted}">Count</span>
                    <span>${d.length.toLocaleString()}</span>
                </div>
            `, event);
        })
        .on('mousemove', (event) => tooltip.move(event))
        .on('mouseout', function () {
            d3.select(this).attr('fill-opacity', 0.7).attr('fill', colorPalette[0]);
            tooltip.hide();
        });

        return { destroy: () => { tooltip.destroy(); container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('histogram', { svg: renderHistogramSVG });
})();
