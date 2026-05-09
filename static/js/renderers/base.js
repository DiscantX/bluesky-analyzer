/**
 * static/js/renderers/base.js
 * Shared utilities for all chart renderers.
 * Loaded first; all other renderers depend on this.
 */

// ── Shared color palette ──────────────────────────────────────────────────────
const CHART_PALETTE = [
    '#5b8cf8', '#a78bfa', '#10b981', '#f59e0b',
    '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6',
    '#34d399', '#fb923c', '#38bdf8', '#e879f9',
    '#fbbf24', '#4ade80', '#f472b6', '#60a5fa',
];

// CSS variables — read at render time to match theme
function getCSSVars() {
    const style = getComputedStyle(document.documentElement);
    return {
        bg:       style.getPropertyValue('--bg').trim()       || '#0c0e14',
        surface:  style.getPropertyValue('--surface').trim()  || '#13161f',
        surface2: style.getPropertyValue('--surface2').trim() || '#1a1d29',
        border:   style.getPropertyValue('--border').trim()   || '#252837',
        accent:   style.getPropertyValue('--accent').trim()   || '#5b8cf8',
        accent2:  style.getPropertyValue('--accent2').trim()  || '#a78bfa',
        text:     style.getPropertyValue('--text').trim()     || '#e8eaf0',
        muted:    style.getPropertyValue('--muted').trim()    || '#6b7280',
        muted2:   style.getPropertyValue('--muted2').trim()   || '#4b5563',
        mono:     "'DM Mono', monospace",
        sans:     "'Syne', sans-serif",
    };
}

// ── Scale builders ────────────────────────────────────────────────────────────
function buildScale(type, domain, range) {
    // type: 'linear' | 'log' | 'sqrt' | 'time'
    // Ensure valid domain for log scale
    if (type === 'log') {
        const lo = Math.max(domain[0] || 0.0001, 1e-10);
        const hi = Math.max(domain[1] || 1,      1e-9);
        return d3.scaleLog().domain([lo, hi]).range(range).clamp(true);
    }
    if (type === 'sqrt') {
        return d3.scaleSqrt().domain(domain).range(range).clamp(true);
    }
    if (type === 'time') {
        return d3.scaleTime()
            .domain(domain.map(v => v instanceof Date ? v : new Date(v)))
            .range(range);
    }
    return d3.scaleLinear().domain(domain).range(range).clamp(true);
}

function buildColorScale(domain, palette) {
    if (typeof domain[0] === 'number') {
        return d3.scaleSequential()
            .domain(domain)
            .interpolator(d3.interpolatePlasma);
    }
    return d3.scaleOrdinal()
        .domain(domain)
        .range(palette || CHART_PALETTE);
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
class ChartTooltip {
    constructor(container) {
        this._el = document.createElement('div');
        this._el.style.cssText = [
            'position:fixed',
            'background:rgba(19,22,31,0.96)',
            'border:1px solid var(--border2,#2e3245)',
            'border-radius:6px',
            'padding:0.5rem 0.75rem',
            'font-family:var(--mono)',
            'font-size:0.72rem',
            'pointer-events:none',
            'opacity:0',
            'z-index:500',
            'transition:opacity 0.1s',
            'max-width:240px',
            'line-height:1.55',
        ].join(';');
        document.body.appendChild(this._el);
    }

    show(html, event) {
        this._el.innerHTML = html;
        this._el.style.opacity = '1';
        this._move(event);
    }

    _move(event) {
        const vw = window.innerWidth, vh = window.innerHeight;
        const w = this._el.offsetWidth + 16, h = this._el.offsetHeight + 16;
        let x = event.clientX + 12, y = event.clientY - 8;
        if (x + w > vw) x = event.clientX - w;
        if (y + h > vh) y = event.clientY - h;
        this._el.style.left = x + 'px';
        this._el.style.top  = y + 'px';
    }

    move(event) { if (this._el.style.opacity !== '0') this._move(event); }

    hide() { this._el.style.opacity = '0'; }

    destroy() { this._el.remove(); }
}

// ── Axis renderer ─────────────────────────────────────────────────────────────
function drawAxis(g, scale, orientation, label, css) {
    const axis = orientation === 'bottom'
        ? d3.axisBottom(scale).ticks(6)
        : d3.axisLeft(scale).ticks(6);

    // Format ticks
    if (scale.type === 'log' || scale._type === 'log') {
        axis.ticks(4, '~s');
    } else {
        axis.tickFormat(d => {
            if (typeof d === 'number') {
                if (Math.abs(d) >= 1e6) return d3.format('.2s')(d);
                if (Math.abs(d) >= 1e3) return d3.format('.2s')(d);
                if (d % 1 !== 0 && Math.abs(d) < 10) return d3.format('.2f')(d);
                return d3.format(',.0f')(d);
            }
            return d;
        });
    }

    const axisG = g.append('g').call(axis);

    axisG.select('.domain').attr('stroke', css.border);
    axisG.selectAll('.tick line').attr('stroke', css.muted2);
    axisG.selectAll('.tick text')
        .attr('fill', css.muted)
        .style('font-family', css.mono)
        .style('font-size', '10px');

    if (label) {
        const isBottom = orientation === 'bottom';
        axisG.append('text')
            .attr('fill', css.muted)
            .style('font-family', css.sans)
            .style('font-size', '11px')
            .style('font-weight', '600')
            .attr('text-anchor', 'middle')
            .attr('x', isBottom ? 0 : 0)
            .attr('y', isBottom ? 36 : -40)
            .attr('transform', isBottom ? '' : 'rotate(-90)')
            .text(label);
    }

    return axisG;
}

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtVal(v) {
    if (v == null) return '—';
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    if (typeof v === 'number') {
        if (Math.abs(v) < 0.001 && v !== 0) return v.toExponential(3);
        if (Math.abs(v) >= 1e6) return d3.format('.3s')(v);
        if (Math.abs(v) >= 1e3) return d3.format(',.0f')(v);
        if (v % 1 !== 0) return d3.format('.4f')(v);
        return d3.format(',.0f')(v);
    }
    return String(v);
}

function fmtDate(v) {
    if (!v) return '—';
    return new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' });
}

// ── Tooltip HTML builder ──────────────────────────────────────────────────────
function buildTooltipHtml(point, axes) {
    const name = point.display_name || point.handle;
    const comm = point.comm_name ? ` <span style="color:var(--muted)">[${point.comm_name}]</span>` : '';
    let html = `<div style="font-weight:700;color:var(--accent);margin-bottom:4px">@${point.handle}${comm}</div>`;
    if (point.display_name) {
        html += `<div style="color:var(--muted);font-size:0.68rem;margin-bottom:6px">${point.display_name}</div>`;
    }
    for (const [dim, axisInfo] of Object.entries(axes)) {
        const val = point[dim];
        if (val == null) continue;
        const label = axisInfo.label || dim;
        const fmt = axisInfo.scale === 'time' ? fmtDate(val) : fmtVal(val);
        html += `<div style="display:flex;justify-content:space-between;gap:1rem">
            <span style="color:var(--muted)">${label}</span>
            <span style="color:var(--text)">${fmt}</span>
        </div>`;
    }
    return html;
}

// ── Renderer registry ─────────────────────────────────────────────────────────
const RENDERERS = {};

function registerRenderer(chartType, renderers) {
    RENDERERS[chartType] = renderers;
}

function renderChart(container, apiResponse, options = {}) {
    const { chart_type, render_mode } = apiResponse;
    const available = RENDERERS[chart_type];
    if (!available) throw new Error(`No renderer for chart type: ${chart_type}`);

    const useWebGL = options.forceWebGL
        || (render_mode === 'webgl' && available.webgl)
        || ((apiResponse.total || 0) > 3000 && available.webgl);

    const renderer = useWebGL ? available.webgl : available.svg;
    if (!renderer) throw new Error(`No ${useWebGL ? 'WebGL' : 'SVG'} renderer for: ${chart_type}`);

    return renderer(container, apiResponse, {
        interactive: true,
        animated: true,
        labels: true,
        colorPalette: CHART_PALETTE,
        cssVars: getCSSVars(),
        onPointClick: options.onPointClick || null,
        ...options,
    });
}

// ── Grid lines helper ─────────────────────────────────────────────────────────
function drawGridLines(g, xScale, yScale, width, height, css) {
    // Horizontal grid
    g.append('g')
        .attr('class', 'grid-h')
        .selectAll('line')
        .data(yScale.ticks(5))
        .join('line')
        .attr('x1', 0).attr('x2', width)
        .attr('y1', d => yScale(d)).attr('y2', d => yScale(d))
        .attr('stroke', css.border)
        .attr('stroke-dasharray', '2,4')
        .attr('opacity', 0.5);

    // Vertical grid
    g.append('g')
        .attr('class', 'grid-v')
        .selectAll('line')
        .data(xScale.ticks(5))
        .join('line')
        .attr('x1', d => xScale(d)).attr('x2', d => xScale(d))
        .attr('y1', 0).attr('y2', height)
        .attr('stroke', css.border)
        .attr('stroke-dasharray', '2,4')
        .attr('opacity', 0.5);
}

// Expose globally
window.ChartBase = {
    PALETTE: CHART_PALETTE,
    getCSSVars,
    buildScale,
    buildColorScale,
    ChartTooltip,
    drawAxis,
    drawGridLines,
    fmtVal,
    fmtDate,
    buildTooltipHtml,
    registerRenderer,
    renderChart,
    RENDERERS,
};
