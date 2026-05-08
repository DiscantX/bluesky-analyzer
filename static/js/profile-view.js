/**
 * static/js/profile-view.js
 * Dedicated renderer for Profile information within the InfoPanel.
 */

const ProfileView = {
    render(u) {
        if (!u) return '<div class="state-box">Profile not found.</div>';
        
        const avatarHtml = u.avatar_url 
            ? `<img src="${u.avatar_url}" class="skeleton-avatar" style="border:1px solid var(--border); object-fit: cover;">` 
            : `<div class="avatar-placeholder" style="width:56px; height:56px; font-size:1.2rem;">${(u.display_name || u.handle || 'U')[0].toUpperCase()}</div>`;

        return `
            <div class="profile-view">
                <header style="display:flex; gap:1rem; align-items:center; margin-bottom:1.5rem;">
                    ${avatarHtml}
                    <div style="overflow:hidden;">
                        <h2 style="font-weight:800; font-size:1.1rem; margin:0; white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">${u.display_name || '—'}</h2>
                        <div style="font-family:var(--mono); font-size:0.75rem; color:var(--accent);">@${u.handle}</div>
                    </div>
                </header>

                ${u.description ? `<p style="font-size:0.85rem; color:var(--muted); line-height:1.4; margin-bottom:1.5rem; white-space: pre-wrap;">${u.description}</p>` : ''}

                <div class="info-section-label">Network Position</div>
                <div class="info-card">
                    <div class="info-card-row"><span>FlowRank</span><span class="info-card-val">${(u.flowrank_score * 1000).toFixed(4)}</span></div>
                    <div class="info-card-row">
                        <span>Community</span>
                        <span class="js-community-trigger" data-id="${u.community_id}" style="color:var(--accent2); cursor:pointer; font-weight:bold;">
                            ${u.comm_name || '#' + (u.community_id ?? '—')}
                        </span></div>
                    <div class="info-card-row"><span>Followers</span><span>${(u.followers_count || 0).toLocaleString()}</span></div>
                    <div class="info-card-row"><span>Following</span><span>${(u.follows_count || 0).toLocaleString()}</span></div>
                </div>

                <div class="info-section-label">Activity Signals</div>
                <div class="info-card">
                    <div class="info-card-row"><span>Repost Ratio</span><span>${(u.repost_ratio * 100).toFixed(1)}%</span></div>
                    <div class="info-card-row"><span>Last Post</span><span>${u.days_since_post != null ? u.days_since_post + 'd ago' : '—'}</span></div>
                    <div class="info-card-row"><span>Interacted</span><span style="color:${u.interacted_with_owner ? 'var(--accent2)' : 'var(--muted)'}; font-weight:bold;">${u.interacted_with_owner ? 'YES' : 'NO'}</span></div>
                </div>

                <div style="margin-top: 2rem;">
                    <a href="https://bsky.app/profile/${u.did}" target="_blank" class="btn btn-primary" style="width:100%; justify-content:center; text-decoration:none; font-weight: 700;">
                        Open in Bluesky
                    </a>
                </div>
            </div>
        `;
    }
};