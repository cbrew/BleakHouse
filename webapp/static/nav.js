// Shared navigation bar — injected into all pages
(function() {
    const currentPath = window.location.pathname;
    const links = [
        { href: '/tracker', label: 'Matrix', icon: '&#9638;' },
        { href: '/versions', label: 'Versions', icon: '&#916;' },
        { href: '/player', label: 'Player', icon: '&#9835;' },
        { href: '/about', label: 'How It Works', icon: '&#9881;' },
        { href: '/prompts', label: 'Prompts', icon: '&#10094;&#10095;' },
        { href: '/metrics', label: 'Metrics', icon: '&#9776;' },
        { href: '/examples', label: 'Examples', icon: '&#10077;' },
        { href: '/poster', label: 'Poster', icon: '&#167;' },
        { href: '/research', label: 'Research', icon: '&#9830;' },
        { href: '/blog', label: 'Blog', icon: '&#9998;' },
        { href: '/help', label: 'Help', icon: '&#10067;' },
    ];

    const nav = document.createElement('nav');
    nav.id = 'site-nav';
    nav.innerHTML = `
        <div class="nav-inner">
            <a class="nav-brand" href="/"><em>Not In Our Time</em></a>
            ${links.map(l => {
                const active = currentPath === l.href ||
                    (l.href !== '/' && currentPath.startsWith(l.href));
                return `<a href="${l.href}" class="nav-link${active ? ' active' : ''}">${l.icon} ${l.label}</a>`;
            }).join('')}
        </div>
    `;

    // Insert at top of body
    document.body.insertBefore(nav, document.body.firstChild);

    // Inject styles
    const style = document.createElement('style');
    style.textContent = `
        #site-nav {
            background: #0f1623;
            border-bottom: 2px solid #1a2744;
            padding: 0;
            position: sticky;
            top: 0;
            z-index: 1000;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif;
        }
        .nav-inner {
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 0;
            padding: 0 1em;
        }
        .nav-brand {
            color: #e94560;
            font-weight: 700;
            font-size: 1.1em;
            text-decoration: none;
            padding: 0.6em 1em 0.6em 0;
            margin-right: 1em;
            border-right: 1px solid #1a2744;
        }
        .nav-link {
            color: #8888aa;
            text-decoration: none;
            padding: 0.6em 0.8em;
            font-size: 0.85em;
            transition: color 0.15s, background 0.15s;
            border-radius: 4px;
        }
        .nav-link:hover {
            color: #e8e8e8;
            background: #1a2744;
        }
        .nav-link.active {
            color: #e8e8e8;
            background: #16213e;
        }
        /* Push page content below sticky nav */
        #site-nav + * { margin-top: 0; }
    `;
    document.head.appendChild(style);

    // --- Page view tracking ---
    fetch('/api/pageview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            page: window.location.pathname,
            ref: document.referrer || null,
        }),
    }).catch(() => {});

    // --- Provenance badge ---
    const pageName = currentPath.replace(/^\//, '').replace(/\//g, '_') || 'landing';
    fetch('/static/provenance.json').then(r => r.json()).then(prov => {
        const info = prov[pageName];
        if (!info) return;
        const colors = { red: '#e94560', yellow: '#e8d44d', green: '#6fdc6f', grey: '#888' };
        const bgColors = { red: '#3d1515', yellow: '#3d3510', green: '#1e4620', grey: '#333' };
        const badge = document.createElement('div');
        badge.style.cssText = `text-align:center;padding:6px;font-size:0.8em;font-family:sans-serif;color:${colors[info.color]};background:${bgColors[info.color]};border-top:1px solid #1a2744;`;
        badge.innerHTML = `<a href="${info.github_url}" style="color:${colors[info.color]};text-decoration:none;" target="_blank">` +
            `&#x1F4DD; <strong>${info.badge}</strong>` +
            ` (${info.total_commits} commit${info.total_commits !== 1 ? 's' : ''})` +
            ` &mdash; view git history</a>`;
        // Insert before feedback footer
        const fb = document.getElementById('feedback-footer');
        if (fb) document.body.insertBefore(badge, fb);
        else document.body.appendChild(badge);
    }).catch(() => {});

    // --- Feedback footer ---
    const feedback = document.createElement('div');
    feedback.id = 'feedback-footer';
    feedback.innerHTML = `
        <div class="fb-inner">
            <span class="fb-label">Was this page useful?</span>
            <button class="fb-btn fb-up" title="Yes">&#128077;</button>
            <button class="fb-btn fb-down" title="No">&#128078;</button>
            <input type="text" class="fb-text" placeholder="Optional comment..." maxlength="500">
            <button class="fb-send">Send</button>
            <span class="fb-thanks" style="display:none;color:#6fdc6f;">Thanks!</span>
        </div>
    `;
    document.body.appendChild(feedback);

    const fbStyle = document.createElement('style');
    fbStyle.textContent = `
        #feedback-footer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #0f1623;
            border-top: 1px solid #1a2744;
            padding: 6px 1em;
            z-index: 1000;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 0.85em;
        }
        .fb-inner {
            max-width: 800px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .fb-label { color: #8888aa; white-space: nowrap; }
        .fb-btn {
            background: none; border: 1px solid #1a2744; border-radius: 4px;
            padding: 2px 8px; cursor: pointer; font-size: 1.1em;
            transition: background 0.15s;
        }
        .fb-btn:hover { background: #1a2744; }
        .fb-btn.selected { background: #16213e; border-color: #e94560; }
        .fb-text {
            flex: 1; background: #16213e; border: 1px solid #1a2744;
            border-radius: 4px; color: #e8e8e8; padding: 4px 8px;
            font-size: 0.9em; min-width: 100px;
        }
        .fb-text::placeholder { color: #555; }
        .fb-send {
            background: #16213e; border: 1px solid #0f3460; border-radius: 4px;
            color: #6fa8dc; padding: 4px 12px; cursor: pointer;
            font-size: 0.9em;
        }
        .fb-send:hover { background: #0f3460; }
        /* Push page content above the fixed footer */
        body { padding-bottom: 50px; }
    `;
    document.head.appendChild(fbStyle);

    // Feedback logic
    let selectedRating = null;
    feedback.querySelector('.fb-up').addEventListener('click', function() {
        selectedRating = 'up';
        feedback.querySelector('.fb-up').classList.add('selected');
        feedback.querySelector('.fb-down').classList.remove('selected');
    });
    feedback.querySelector('.fb-down').addEventListener('click', function() {
        selectedRating = 'down';
        feedback.querySelector('.fb-down').classList.add('selected');
        feedback.querySelector('.fb-up').classList.remove('selected');
    });
    feedback.querySelector('.fb-send').addEventListener('click', function() {
        const text = feedback.querySelector('.fb-text').value.trim();
        if (!selectedRating && !text) return;
        fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                rating: selectedRating,
                text: text,
                page: window.location.pathname,
            }),
        }).then(() => {
            feedback.querySelector('.fb-thanks').style.display = 'inline';
            feedback.querySelector('.fb-send').style.display = 'none';
            feedback.querySelector('.fb-text').style.display = 'none';
            feedback.querySelector('.fb-up').style.display = 'none';
            feedback.querySelector('.fb-down').style.display = 'none';
        });
    });
})();
