/**
 * static/js/community-view.js
 * Dedicated renderer for Community/Cluster information within the InfoPanel.
 */

const CommunityView = {
    render(c) {
        if (!c) return '<div class="state-box">Community data not found.</div>';

        const keywords = Object.entries(c.top_keywords || {})
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10)
            .map(([word]) => `<span class="badge" style="background:var(--surface2); border:1px solid var(--border); color:var(--text);">${word}</span>`)
            .join('');

        const members = (c.representative_members || []).map(m => `
            <div class="info-card-row js-profile-trigger" data-did="${m.did}" style="cursor:pointer; padding: 4px 0;">
                <span style="color:var(--accent); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">@${m.handle}</span>
                <span style="color:var(--muted); font-size:0.7rem;">→</span>
            </div>
        `).join('');

        return `
            <div class="community-view">
                <header style="margin-bottom:1.5rem;">
                    <div class="info-section-label" style="margin-top:0;">Community Network</div>
                    <h2 style="font-weight:800; font-size:1.1rem; margin:0; color:var(--accent2);">${c.name || 'Unnamed Cluster'}</h2>
                </header>

                <p style="font-size:0.85rem; color:var(--muted); line-height:1.4; margin-bottom:1.5rem;">
                    ${c.description || 'No description available for this community.'}
                </p>

                <div class="info-section-label">Top Keywords</div>
                <div style="display:flex; gap:0.4rem; flex-wrap:wrap; margin-bottom:1.5rem;">
                    ${keywords || '<span style="color:var(--muted2)">No keywords extracted.</span>'}
                </div>

                <div class="info-section-label">Key Influencers</div>
                <div class="info-card">
                    ${members || '<div style="color:var(--muted2)">No members found.</div>'}
                </div>

                <div style="margin-top: 2rem;">
                    <button class="btn btn-primary" style="width:100%; justify-content:center; font-weight: 700;" onclick="filterByCommunity('${c.id}')">
                        Filter Dashboard by Community
                    </button>
                </div>
            </div>
        `;
    }
};