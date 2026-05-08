/**
 * static/js/info-panel.js
 * Shared orchestrator for the slide-out info panels.
 */

const InfoPanel = {
    cache: new Map(),
    currentType: null,
    currentId: null,
    initialized: false,
    panel: null,
    backdrop: null,
    content: null,
    skeleton: null,

    init() {
        if (this.initialized) return;
        this.panel = document.getElementById('info-panel');
        this.backdrop = document.getElementById('info-panel-backdrop');
        this.content = document.getElementById('info-panel-content');
        this.skeleton = this.content.querySelector('.info-panel-skeleton');

        if (!this.panel) return; // Wait until partial is in DOM
        this.initialized = true;

        // Global listener for closing on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.close();
        });

        // Global listener for InfoPanel triggers (Profiles and Communities)
        document.addEventListener('click', (e) => {
            const profileTrigger = e.target.closest('.js-profile-trigger');
            if (profileTrigger) {
                const did = profileTrigger.dataset.did;
                if (did) this.open('profile', did);
                return;
            }

            const communityTrigger = e.target.closest('.js-community-trigger');
            if (communityTrigger) {
                const id = communityTrigger.dataset.id;
                if (id !== "null" && id !== undefined) this.open('community', id);
            }
        });
    },

    /**
     * Opens the panel for a specific entity.
     * @param {string} type - 'profile' or 'community'
     * @param {string} id - The unique identifier (DID, handle, or community ID)
     */
    async open(type, id) {
        if (!this.initialized) this.init();
        if (!this.panel) {
            console.warn("InfoPanel: Container #info-panel not found. Ensure the partial is included in the template.");
            return;
        }

        this.currentType = type;
        this.currentId = id;

        // 1. UI Feedback: Show panel and skeleton
        this.panel.classList.add('open');
        this.backdrop.classList.add('visible');
        this.skeleton.style.display = 'block';
        
        // Remove any existing view content
        const existingView = this.content.querySelector('.info-view');
        if (existingView) existingView.remove();

        // Notify charts that they might need to re-center
        window.dispatchEvent(new CustomEvent('infopanel:toggle', { 
            detail: { open: true, type, id } 
        }));

        try {
            const data = await this.getData(type, id);
            if (this.currentId === id) { // Ensure user hasn't clicked something else
                this.render(type, data);
            }
        } catch (err) {
            console.error('InfoPanel fetch failed:', err);
            this.skeleton.style.display = 'none';
            const errorDiv = document.createElement('div');
            errorDiv.className = 'info-view state-box';
            errorDiv.innerHTML = `<div style="color:var(--danger)">Failed to load ${type} info.</div>`;
            this.content.appendChild(errorDiv);
        }
    },

    close() {
        if (!this.panel) return;
        this.panel.classList.remove('open');
        this.backdrop.classList.remove('visible');
        this.currentType = null;
        this.currentId = null;

        window.dispatchEvent(new CustomEvent('infopanel:toggle', { 
            detail: { open: false } 
        }));
    },

    async getData(type, id) {
        const cacheKey = `${type}:${id}`;
        if (this.cache.has(cacheKey)) return this.cache.get(cacheKey);

        let data;
        
        // Robust alias detection for shared views
        let alias = null;
        if (typeof state !== 'undefined' && state.activeAlias) {
            alias = state.activeAlias;
        } else if (typeof ACTIVE_ALIAS !== 'undefined') {
            alias = ACTIVE_ALIAS;
        } else if (typeof ALIAS !== 'undefined') {
            alias = ALIAS;
        } else {
            // Fallback to URL path, ensuring we decode spaces/special chars
            alias = decodeURIComponent(window.location.pathname.split('/').pop());
        }

        if (type === 'profile') {
            const filter = id.startsWith('did:') ? { field: "did", op: "eq", value: id } : { field: "handle", op: "eq", value: id };
            const res = await fetch(`/api/users/${encodeURIComponent(alias)}?limit=1&filter_tree=${JSON.stringify({ op: "AND", conditions: [filter] })}`);
            if (!res.ok) throw new Error(`User fetch failed: ${res.status}`);
            const result = await res.json();
            data = result.users[0];
        }

        if (type === 'community') {
            const res = await fetch(`/api/graph/${encodeURIComponent(alias)}/community/${id}`);
            if (!res.ok) throw new Error(`Community fetch failed: ${res.status}`);
            data = await res.json();
        }

        if (data) {
            this.cache.set(cacheKey, data);
            // Limit cache size to 50 entries
            if (this.cache.size > 50) this.cache.delete(this.cache.keys().next().value);
        }
        return data;
    },

    render(type, data) {
        this.skeleton.style.display = 'none';
        let html = '';

        if (type === 'profile') html = ProfileView.render(data);
        else if (type === 'community') html = CommunityView.render(data);

        const viewDiv = document.createElement('div');
        viewDiv.className = 'info-view';
        viewDiv.innerHTML = html;
        this.content.appendChild(viewDiv);
    }
};

// Auto-init when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => InfoPanel.init());
} else {
    InfoPanel.init();
}

/**
 * Global helper to filter dashboard by community.
 * If on the dashboard, it applies the filter immediately.
 * If on a graph page, it redirects to the dashboard with a query parameter.
 */
window.filterByCommunity = function(id) {
    if (id === null || id === undefined) return;

    // Detect if we are on the main dashboard (where the global 'state' object lives)
    if (typeof state !== 'undefined' && state.filters) {
        state.filters.filter_tree = {
            op: "AND",
            conditions: [{ field: "community_id", op: "eq", value: Number(id) }]
        };
        state.activeTab = "custom-community";
        if (typeof renderNav === 'function') renderNav();
        if (typeof fetchUsers === 'function') fetchUsers();
        InfoPanel.close();
        if (typeof toast === 'function') toast(`Filtering by Community #${id}`);
    } else {
        // Redirect to dashboard with filter instruction
        window.location.href = `/?filter_community=${id}`;
    }
};