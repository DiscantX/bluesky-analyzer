/**
 * static/js/renderers/bar.js
 * Bar chart SVG renderer (aggregated data).
 */

(function () {
    'use strict';

    function renderBarSVG(container, apiResponse, options = {}) {
        const { data, axes } = apiResponse;
        const { colorPalette, cssVars: css, animated } = options;

        container.innerHTML = '';
        if (!data || data.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No data</div>`;
            return;
        }

        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;
        const margin = { top: 24, right: 32, bottom: 80, left: 72 };
        const width  = W - margin.left - margin.right;
        const height = H - margin.top  - margin.bottom;

        const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
        const g   = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        const xCfg = axes.x || {};
        const yCfg = axes.y || {};

        const xScale = d3.scaleBand()
            .domain(data.map(d => String(d.x)))
            .range([0, width])
            .padding(0.2);

        const yDomain = [0, d3.max(data, d => d.y) * 1.05];
        const yScale = ChartBase.buildScale(yCfg.scale || 'linear', yDomain, [height, 0]);

        ChartBase.drawGridLines(g, null, yScale, width, height, css);

        const xAxisG = g.append('g').attr('transform', `translate(0,${height})`)
            .call(d3.axisBottom(xScale));
        xAxisG.select('.domain').attr('stroke', css.border);
        xAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        xAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px')
            .attr('transform', 'rotate(-30)').attr('text-anchor', 'end');
        g.append('text').attr('x', width / 2).attr('y', height + 72).attr('text-anchor', 'middle')
            .attr('fill', css.muted).style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
            .text(xCfg.label || 'Group');

        const yAxisG = g.append('g').call(d3.axisLeft(yScale).ticks(5).tickFormat(d => ChartBase.fmtVal(d)));
        yAxisG.select('.domain').attr('stroke', css.border);
        yAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        yAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
        g.append('text').attr('transform', 'rotate(-90)').attr('x', -height / 2).attr('y', -56)
            .attr('text-anchor', 'middle').attr('fill', css.muted)
            .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600').text(yCfg.label || 'Value');

        const commColorScale = d3.scaleOrdinal().domain(data.map(d => d.x)).range(colorPalette);
        const tooltip = new ChartBase.ChartTooltip(container);

        const bars = g.selectAll('.bar').data(data).join('rect')
            .attr('class', 'bar')
            .attr('x', d => xScale(String(d.x)))
            .attr('width', xScale.bandwidth())
            .attr('y', d => animated ? height : yScale(d.y || 0))
            .attr('height', d => animated ? 0 : height - yScale(d.y || 0))
            .attr('fill', d => commColorScale(d.x))
            .attr('fill-opacity', 0.75)
            .attr('rx', 3)
            .style('cursor', 'pointer');

        if (animated) {
            bars.transition().duration(700).delay((d, i) => i * 30)
                .attr('y', d => yScale(d.y || 0))
                .attr('height', d => height - yScale(d.y || 0));
        }

        bars.on('mouseover', function (event, d) {
            d3.select(this).attr('fill-opacity', 1);
            tooltip.show(`
                <div style="color:var(--accent);font-weight:700;margin-bottom:4px">${xCfg.label || 'Group'}: ${d.x}</div>
                <div style="display:flex;justify-content:space-between;gap:1rem">
                    <span style="color:var(--muted)">${yCfg.label || 'Value'}</span>
                    <span>${ChartBase.fmtVal(d.y)}</span>
                </div>
                <div style="display:flex;justify-content:space-between;gap:1rem">
                    <span style="color:var(--muted)">Members</span>
                    <span>${(d.member_count || 0).toLocaleString()}</span>
                </div>
            `, event);
        })
        .on('mousemove', (e) => tooltip.move(e))
        .on('mouseout', function () { d3.select(this).attr('fill-opacity', 0.75); tooltip.hide(); });

        return { destroy: () => { tooltip.destroy(); container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('bar', { svg: renderBarSVG });
})();


/**
 * static/js/renderers/bubble.js
 * Bubble chart SVG renderer (scatter with size dimension).
 */

(function () {
    'use strict';

    function renderBubbleSVG(container, apiResponse, options = {}) {
        const { data, axes } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick, animated } = options;

        container.innerHTML = '';
        if (!data || data.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No data</div>`;
            return;
        }

        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;
        const margin = { top: 24, right: 32, bottom: 60, left: 72 };
        const width  = W - margin.left - margin.right;
        const height = H - margin.top  - margin.bottom;

        const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
        svg.append('defs').append('clipPath').attr('id', 'bubble-clip')
            .append('rect').attr('width', width).attr('height', height);
        const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        const xCfg = axes.x || {}, yCfg = axes.y || {}, sCfg = axes.size || {};
        const xScale = ChartBase.buildScale(xCfg.scale || 'linear', xCfg.domain || [0, 1], [0, width]);
        const yScale = ChartBase.buildScale(yCfg.scale || 'linear', yCfg.domain || [0, 1], [height, 0]);
        const sizeDomain = sCfg.domain || [0, 1];
        const sizeScale  = d3.scaleSqrt().domain([0, Math.max(...sizeDomain, 1e-9)]).range([3, 20]).clamp(true);

        const cCfg = axes.color;
        let colorScale;
        if (cCfg) {
            const cDomain = [...new Set(data.map(d => d.color).filter(v => v != null))];
            colorScale = typeof cDomain[0] === 'number'
                ? d3.scaleSequential().domain(d3.extent(cDomain)).interpolator(d3.interpolateCool)
                : d3.scaleOrdinal().domain(cDomain).range(colorPalette);
        }

        ChartBase.drawGridLines(g, xScale, yScale, width, height, css);

        [['bottom', xCfg], ['left', yCfg]].forEach(([orient, cfg]) => {
            const axisG = g.append('g')
                .attr('transform', orient === 'bottom' ? `translate(0,${height})` : '')
                .call((orient === 'bottom' ? d3.axisBottom(xScale) : d3.axisLeft(yScale))
                    .ticks(5).tickFormat(d => ChartBase.fmtVal(d)));
            axisG.select('.domain').attr('stroke', css.border);
            axisG.selectAll('.tick line').attr('stroke', css.muted2);
            axisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');

            if (orient === 'bottom') {
                g.append('text')
                    .attr('x', width / 2)
                    .attr('y', height + 48)
                    .attr('text-anchor', 'middle').attr('fill', css.muted)
                    .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
                    .text(cfg.label || 'X');
            } else {
                g.append('text')
                    .attr('transform', 'rotate(-90)')
                    .attr('x', -height / 2)
                    .attr('y', -56)
                    .attr('text-anchor', 'middle').attr('fill', css.muted)
                    .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
                    .text(cfg.label || 'Y');
            }
        });

        const tooltip = new ChartBase.ChartTooltip(container);
        const pointsG = g.append('g').attr('clip-path', 'url(#bubble-clip)');
        const validData = data.filter(d => d.x != null && d.y != null).sort((a, b) => (b.size || 0) - (a.size || 0));

        const circles = pointsG.selectAll('circle').data(validData).join('circle')
            .attr('cx', d => xScale(d.x))
            .attr('cy', d => yScale(d.y))
            .attr('r', d => d.size != null ? sizeScale(d.size) : 6)
            .attr('fill', d => colorScale && d.color != null ? colorScale(d.color) : colorPalette[0])
            .attr('fill-opacity', animated ? 0 : 0.6)
            .attr('stroke', css.surface).attr('stroke-width', 0.5)
            .style('cursor', 'pointer');

        if (animated) {
            circles.transition().duration(700).delay((d, i) => i * 2)
                .attr('fill-opacity', 0.6);
        }

        circles
            .on('mouseover', function (event, d) {
                d3.select(this).raise().attr('fill-opacity', 0.9).attr('stroke', css.accent).attr('stroke-width', 1.5);
                tooltip.show(ChartBase.buildTooltipHtml(d, axes), event);
            })
            .on('mousemove', (e) => tooltip.move(e))
            .on('mouseout', function () {
                d3.select(this).attr('fill-opacity', 0.6).attr('stroke', css.surface).attr('stroke-width', 0.5);
                tooltip.hide();
            })
            .on('click', (event, d) => { if (onPointClick && d.did) onPointClick(d.did, d); });

        return { destroy: () => { tooltip.destroy(); container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('bubble', { svg: renderBubbleSVG });
})();


/**
 * static/js/renderers/timeline.js
 * Timeline / dot plot SVG renderer.
 */

(function () {
    'use strict';

    function renderTimelineSVG(container, apiResponse, options = {}) {
        const { data, axes } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick, animated } = options;

        container.innerHTML = '';
        if (!data || data.length === 0) {
            container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem">No data</div>`;
            return;
        }

        const W = container.clientWidth || 800;
        const H = container.clientHeight || 500;
        const margin = { top: 24, right: 32, bottom: 60, left: 72 };
        const width  = W - margin.left - margin.right;
        const height = H - margin.top  - margin.bottom;

        const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
        svg.append('defs').append('clipPath').attr('id', 'timeline-clip')
            .append('rect').attr('width', width).attr('height', height);
        const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

        const xCfg = axes.x || {}, yCfg = axes.y || {}, cCfg = axes.color;
        const validData = data.filter(d => d.x != null && d.y != null);

        const dateDomain = d3.extent(validData, d => new Date(d.x));
        const xScale = d3.scaleTime().domain(dateDomain).range([0, width]);
        const yScale = ChartBase.buildScale(yCfg.scale || 'log', yCfg.domain || d3.extent(validData, d => d.y), [height, 0]);

        let colorScale;
        if (cCfg) {
            const cDomain = [...new Set(validData.map(d => d.color).filter(v => v != null))];
            colorScale = typeof cDomain[0] === 'number'
                ? d3.scaleSequential().domain(d3.extent(cDomain)).interpolator(d3.interpolatePlasma)
                : d3.scaleOrdinal().domain(cDomain).range(colorPalette);
        }

        ChartBase.drawGridLines(g, xScale, yScale, width, height, css);

        const xAxisG = g.append('g').attr('transform', `translate(0,${height})`).call(d3.axisBottom(xScale).ticks(7));
        xAxisG.select('.domain').attr('stroke', css.border);
        xAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        xAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
        g.append('text').attr('x', width / 2).attr('y', height + 48).attr('text-anchor', 'middle')
            .attr('fill', css.muted).style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600')
            .text(xCfg.label || 'Time');

        const yAxisG = g.append('g').call(d3.axisLeft(yScale).ticks(5).tickFormat(d => ChartBase.fmtVal(d)));
        yAxisG.select('.domain').attr('stroke', css.border);
        yAxisG.selectAll('.tick line').attr('stroke', css.muted2);
        yAxisG.selectAll('.tick text').attr('fill', css.muted).style('font-family', css.mono).style('font-size', '10px');
        g.append('text').attr('transform', 'rotate(-90)').attr('x', -height / 2).attr('y', -56)
            .attr('text-anchor', 'middle').attr('fill', css.muted)
            .style('font-family', css.sans).style('font-size', '11px').style('font-weight', '600').text(yCfg.label || 'Y');

        const tooltip = new ChartBase.ChartTooltip(container);
        const pointsG = g.append('g').attr('clip-path', 'url(#timeline-clip)');

        const circles = pointsG.selectAll('circle').data(validData).join('circle')
            .attr('cx', d => xScale(new Date(d.x)))
            .attr('cy', d => yScale(d.y))
            .attr('r', 4)
            .attr('fill', d => colorScale && d.color != null ? colorScale(d.color) : colorPalette[0])
            .attr('fill-opacity', animated ? 0 : 0.7)
            .attr('stroke', css.surface).attr('stroke-width', 0.5)
            .style('cursor', 'pointer');

        if (animated) {
            circles.transition().duration(800).delay((d, i) => Math.min(i * 1, 400))
                .attr('fill-opacity', 0.7);
        }

        circles
            .on('mouseover', function (event, d) {
                d3.select(this).raise().attr('fill-opacity', 1).attr('stroke', css.accent).attr('stroke-width', 1.5);
                tooltip.show(ChartBase.buildTooltipHtml(d, axes), event);
            })
            .on('mousemove', (e) => tooltip.move(e))
            .on('mouseout', function () {
                d3.select(this).attr('fill-opacity', 0.7).attr('stroke', css.surface).attr('stroke-width', 0.5);
                tooltip.hide();
            })
            .on('click', (event, d) => { if (onPointClick && d.did) onPointClick(d.did, d); });

        return { destroy: () => { tooltip.destroy(); container.innerHTML = ''; } };
    }

    ChartBase.registerRenderer('timeline', { svg: renderTimelineSVG });
})();
