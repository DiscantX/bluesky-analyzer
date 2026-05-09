/**
 * static/js/renderers/force-directed-3d.js
 *
 * 3D force-directed graph renderer using the `3d-force-graph` library
 * (https://github.com/vasturiano/3d-force-graph) via CDN.
 *
 * Supports two projection modes:
 *   - "3d"  — Full 3D with orbital camera (WebGL via Three.js)
 *   - "2d"  — Flat 2D projection (z-force disabled, rendered orthographically)
 *
 * The mode is read from chart_options.projection (default "3d").
 * Users can toggle it in real-time via the floating control panel injected
 * into the container.
 *
 * Registered as: ChartBase.RENDERERS["force_directed_3d"]
 */

(function () {
    'use strict';

    const LIBRARY_URL = 'https://unpkg.com/3d-force-graph@1.73.5/dist/3d-force-graph.min.js';

    // ── CDN loader (idempotent) ───────────────────────────────────────────────
    function load3DLib() {
        return new Promise((resolve, reject) => {
            if (window.ForceGraph3D) { resolve(); return; }
            const existing = document.querySelector(`script[src="${LIBRARY_URL}"]`);
            if (existing) {
                existing.addEventListener('load', resolve);
                existing.addEventListener('error', reject);
                return;
            }
            const s = document.createElement('script');
            s.src = LIBRARY_URL;
            s.onload  = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    }

    // ── Palette helper ────────────────────────────────────────────────────────
    function commColor(commId, palette) {
        if (commId == null) return palette[0];
        return palette[Math.abs(Math.round(commId)) % palette.length];
    }

    // ── Main renderer ─────────────────────────────────────────────────────────
    async function renderForceDirected3D(container, apiResponse, options = {}) {
        const { data, axes, chart_options = {} } = apiResponse;
        const { colorPalette, cssVars: css, onPointClick, interactive } = options;

        const nodes = (data && data.nodes) ? data.nodes : [];
        const links = (data && data.links) ? data.links : [];

        // Empty state
        container.innerHTML = '';
        if (nodes.length === 0) {
            container.innerHTML = `
                <div style="display:flex;align-items:center;justify-content:center;
                            height:100%;color:${css.muted};font-family:${css.mono};font-size:0.82rem;
                            flex-direction:column;gap:0.75rem;">
                    <span style="font-size:2rem">🌐</span>
                    No graph data — run a Sync with graph analysis first.
                </div>`;
            return null;
        }

        // Projection mode — "3d" or "2d"
        let projectionMode = chart_options.projection || '3d';
        const showLabels   = chart_options.show_labels !== false;
        const particleSpeed = parseFloat(chart_options.particle_speed ?? 0.005);

        // ── Load library ──────────────────────────────────────────────────────
        try {
            await load3DLib();
        } catch (e) {
            container.innerHTML = `
                <div style="display:flex;align-items:center;justify-content:center;
                            height:100%;color:var(--danger);font-family:${css.mono};font-size:0.8rem;">
                    Failed to load 3D graph library. Check your internet connection.
                </div>`;
            return null;
        }

        const W = container.clientWidth  || 800;
        const H = container.clientHeight || 600;

        // ── Graph data ────────────────────────────────────────────────────────
        const graphNodes = nodes.map(n => ({
            ...n,
            id: n.did || n.id || n.handle,
        }));
        const graphLinks = links.map(l => ({
            source: l.source,
            target: l.target,
        }));

        // ── Size scale ────────────────────────────────────────────────────────
        const maxRank = Math.max(...graphNodes.map(n => n.rank || 0), 0.0001);
        const nodeRadius = (n) => Math.sqrt((n.rank || 0.0001) / maxRank) * 8 + 1.5;

        // ── Build 3D graph ────────────────────────────────────────────────────
        let graph3d = null;

        function buildGraph(mode) {
            if (graph3d) {
                // Destroy previous instance
                try { graph3d._destructor && graph3d._destructor(); } catch (_) {}
                container.querySelectorAll('canvas').forEach(c => c.remove());
                container.querySelectorAll('.fg3d-wrapper').forEach(c => c.remove());
            }

            const wrapper = document.createElement('div');
            wrapper.className = 'fg3d-wrapper';
            wrapper.style.cssText = 'position:absolute;inset:0;';
            container.appendChild(wrapper);

            graph3d = ForceGraph3D({ controlType: mode === '2d' ? 'orbit' : 'orbit' })(wrapper)
                .width(wrapper.clientWidth || W)
                .height(wrapper.clientHeight || H)
                .backgroundColor(css.bg || '#0c0e14')
                .graphData({ nodes: graphNodes, links: graphLinks })
                .nodeId('id')
                .nodeLabel(n => `@${n.handle}${n.comm_name ? ` [${n.comm_name}]` : ''}\nFlowRank: ${((n.rank || 0) * 1000).toFixed(4)}`)
                .nodeColor(n => commColor(n.comm, colorPalette))
                .nodeOpacity(0.85)
                .nodeVal(n => nodeRadius(n))
                .linkColor(() => 'rgba(255,255,255,0.08)')
                .linkOpacity(0.5)
                .linkDirectionalParticles(3)
                .linkDirectionalParticleSpeed(particleSpeed)
                .linkDirectionalParticleColor(() => 'rgba(167,139,250,0.6)')
                .onNodeClick(n => {
                    if (onPointClick && n.did) onPointClick(n.did, n);
                });

            if (showLabels) {
                graph3d.nodeThreeObject(n => {
                    const group = new THREE.Group();

                    // Sphere
                    const r = nodeRadius(n);
                    const geo  = new THREE.SphereGeometry(r, 12, 12);
                    const mat  = new THREE.MeshLambertMaterial({ color: commColor(n.comm, colorPalette), transparent: true, opacity: 0.85 });
                    group.add(new THREE.Mesh(geo, mat));

                    // Label (only for higher-FlowRank nodes to avoid clutter)
                    if ((n.rank || 0) * 1000 > 0.1) {
                        const sprite = makeTextSprite(`@${n.handle}`, css);
                        sprite.position.set(0, r + 2, 0);
                        group.add(sprite);
                    }

                    return group;
                }).nodeThreeObjectExtend(false);
            }

            // 2D mode: disable z-axis force so graph stays flat
            if (mode === '2d') {
                graph3d.d3Force('z', null);
                // Lock camera to overhead view
                setTimeout(() => {
                    try {
                        const cam = graph3d.camera();
                        cam.position.set(0, 0, 400);
                        cam.lookAt(0, 0, 0);
                    } catch (_) {}
                }, 100);
            }

            if (!interactive) {
                setTimeout(() => { try { graph3d.pauseAnimation(); } catch (_) {} }, 3000);
            }
        }

        // ── Text sprite helper ────────────────────────────────────────────────
        function makeTextSprite(text, css) {
            const canvas = document.createElement('canvas');
            canvas.width  = 256;
            canvas.height = 64;
            const ctx = canvas.getContext('2d');
            ctx.font = 'bold 24px "DM Mono", monospace';
            ctx.fillStyle = 'rgba(0,0,0,0.5)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#e8eaf0';
            ctx.textAlign  = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(text, 128, 32);

            const texture = new THREE.CanvasTexture(canvas);
            const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
            const sprite = new THREE.Sprite(material);
            sprite.scale.set(20, 5, 1);
            return sprite;
        }

        // ── Controls overlay ──────────────────────────────────────────────────
        function injectControls() {
            // Remove old controls if any
            container.querySelectorAll('.fg3d-controls').forEach(el => el.remove());

            const ctrl = document.createElement('div');
            ctrl.className = 'fg3d-controls';
            ctrl.style.cssText = [
                'position:absolute',
                'top:0.75rem',
                'left:0.75rem',
                'z-index:50',
                'display:flex',
                'flex-direction:column',
                'gap:0.4rem',
                'pointer-events:none',
            ].join(';');

            ctrl.innerHTML = `
                <div style="
                    background:rgba(19,22,31,0.88);
                    border:1px solid var(--border,#252837);
                    border-radius:8px;
                    padding:0.6rem 0.85rem;
                    font-family:'DM Mono',monospace;
                    font-size:0.7rem;
                    color:var(--muted,#6b7280);
                    pointer-events:all;
                    display:flex;
                    flex-direction:column;
                    gap:0.4rem;
                    min-width:160px;
                ">
                    <div style="font-weight:700;color:var(--text,#e8eaf0);margin-bottom:0.15rem;display:flex;align-items:center;gap:0.4rem;">
                        🌐 3D Network
                    </div>
                    <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;">
                        <input type="radio" name="proj-${Date.now()}" id="proj-3d" value="3d"
                               ${projectionMode === '3d' ? 'checked' : ''}
                               style="accent-color:var(--accent,#5b8cf8)">
                        Full 3D (orbit)
                    </label>
                    <label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;">
                        <input type="radio" name="proj-${Date.now()}" id="proj-2d" value="2d"
                               ${projectionMode === '2d' ? 'checked' : ''}
                               style="accent-color:var(--accent,#5b8cf8)">
                        2D projection
                    </label>
                    <div style="border-top:1px solid var(--border,#252837);margin-top:0.2rem;padding-top:0.35rem;font-size:0.65rem;color:var(--muted2,#4b5563);">
                        ${projectionMode === '3d'
                            ? 'Drag to orbit · Scroll to zoom'
                            : 'Drag to pan · Scroll to zoom'
                        }
                    </div>
                    <div style="font-size:0.65rem;color:var(--muted2,#4b5563);">
                        ${nodes.length.toLocaleString()} nodes · ${links.length.toLocaleString()} edges
                    </div>
                </div>
            `;

            container.style.position = 'relative';
            container.appendChild(ctrl);

            // Wire radio buttons
            ctrl.querySelectorAll('input[type=radio]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    projectionMode = e.target.value;
                    buildGraph(projectionMode);
                    injectControls();     // refresh hint text
                });
            });
        }

        // ── Initial render ────────────────────────────────────────────────────
        container.style.position = 'relative';
        buildGraph(projectionMode);
        injectControls();

        // ── Resize handler ────────────────────────────────────────────────────
        const resizeObs = new ResizeObserver(() => {
            if (!graph3d) return;
            const w = container.clientWidth;
            const h = container.clientHeight;
            try { graph3d.width(w).height(h); } catch (_) {}
        });
        resizeObs.observe(container);

        return {
            destroy() {
                resizeObs.disconnect();
                try { graph3d && graph3d._destructor && graph3d._destructor(); } catch (_) {}
                container.innerHTML = '';
            },
        };
    }

    // Register — both svg and webgl point to the same async renderer
    ChartBase.registerRenderer('force_directed_3d', {
        svg:   renderForceDirected3D,
        webgl: renderForceDirected3D,
    });

})();
