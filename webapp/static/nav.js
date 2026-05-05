// Shared navigation bar — injected into all pages
(function() {
    const currentPath = window.location.pathname;
    const links = [
        { href: '/tracker', label: 'Matrix', icon: '&#9638;' },
        { href: '/script-versions', label: 'Recommended', icon: '&#9733;' },
        { href: '/player', label: 'Player', icon: '&#9835;' },
        { href: '/about', label: 'How It Works', icon: '&#9881;' },
        { href: '/prep', label: 'Prep', icon: '&#128196;' },
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
            <a class="nav-brand" href="/lab"><em>Not In Our Time</em></a>
            <div class="nav-links">
                ${links.map(l => {
                    const active = currentPath === l.href ||
                        (l.href !== '/' && currentPath.startsWith(l.href));
                    return `<a href="${l.href}" class="nav-link${active ? ' active' : ''}">${l.icon} ${l.label}</a>`;
                }).join('')}
            </div>
            <div class="nav-overflow" hidden>
                <button class="nav-more" type="button" aria-haspopup="true" aria-expanded="false">More &#9662;</button>
                <div class="nav-more-menu" hidden></div>
            </div>
        </div>
    `;

    // Insert at top of body
    document.body.insertBefore(nav, document.body.firstChild);

    // Priority+ overflow: hide nav links that don't fit, mirror them into a "More" menu.
    const navLinksEl = nav.querySelector('.nav-links');
    const overflowEl = nav.querySelector('.nav-overflow');
    const moreBtn = nav.querySelector('.nav-more');
    const moreMenu = nav.querySelector('.nav-more-menu');
    const navItems = Array.from(navLinksEl.querySelectorAll('.nav-link'));

    function reflowNav() {
        navItems.forEach(a => a.classList.remove('nav-hidden'));
        overflowEl.hidden = true;
        moreMenu.innerHTML = '';
        const innerEl = nav.querySelector('.nav-inner');
        const innerWidth = innerEl.clientWidth;
        // If the nav fits, we're done.
        if (navLinksEl.scrollWidth <= navLinksEl.clientWidth + 1) return;
        // Otherwise, hide items from the right until it fits, accounting for the More button width.
        overflowEl.hidden = false;
        const moreWidth = overflowEl.offsetWidth || 80;
        const brandWidth = innerEl.querySelector('.nav-brand').offsetWidth;
        const budget = innerWidth - brandWidth - moreWidth - 16;
        let used = 0;
        const overflowed = [];
        for (const a of navItems) {
            used += a.offsetWidth;
            if (used > budget) {
                a.classList.add('nav-hidden');
                overflowed.push(a);
            }
        }
        if (overflowed.length === 0) {
            overflowEl.hidden = true;
            return;
        }
        overflowed.forEach(a => {
            const item = document.createElement('a');
            item.href = a.href;
            item.className = 'nav-more-item' + (a.classList.contains('active') ? ' active' : '');
            item.innerHTML = a.innerHTML;
            moreMenu.appendChild(item);
        });
    }

    moreBtn.addEventListener('click', () => {
        const open = !moreMenu.hidden;
        moreMenu.hidden = open;
        moreBtn.setAttribute('aria-expanded', String(!open));
    });
    document.addEventListener('click', (e) => {
        if (!overflowEl.contains(e.target)) {
            moreMenu.hidden = true;
            moreBtn.setAttribute('aria-expanded', 'false');
        }
    });
    window.addEventListener('resize', reflowNav);
    // Run after layout settles.
    requestAnimationFrame(reflowNav);

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
            max-width: min(1400px, 100vw - 2rem);
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
            white-space: nowrap;
            flex: 0 0 auto;
        }
        .nav-links {
            display: flex;
            flex: 1 1 auto;
            min-width: 0;
            overflow: hidden;
        }
        .nav-link {
            color: #8888aa;
            text-decoration: none;
            padding: 0.6em 0.8em;
            font-size: 0.85em;
            transition: color 0.15s, background 0.15s;
            border-radius: 4px;
            white-space: nowrap;
            flex: 0 0 auto;
        }
        .nav-link.nav-hidden { display: none; }
        .nav-link:hover {
            color: #e8e8e8;
            background: #1a2744;
        }
        .nav-link.active {
            color: #e8e8e8;
            background: #16213e;
        }
        .nav-overflow {
            position: relative;
            flex: 0 0 auto;
            margin-left: auto;
        }
        .nav-more {
            background: none;
            border: 1px solid #1a2744;
            color: #8888aa;
            padding: 0.5em 0.8em;
            font-size: 0.85em;
            font-family: inherit;
            border-radius: 4px;
            cursor: pointer;
        }
        .nav-more:hover { color: #e8e8e8; background: #1a2744; }
        .nav-more-menu {
            position: absolute;
            top: 100%;
            right: 0;
            margin-top: 4px;
            background: #0f1623;
            border: 1px solid #1a2744;
            border-radius: 6px;
            min-width: 180px;
            display: flex;
            flex-direction: column;
            box-shadow: 0 6px 20px rgba(0,0,0,0.4);
            z-index: 1001;
        }
        .nav-more-menu[hidden] { display: none; }
        .nav-more-item {
            color: #8888aa;
            text-decoration: none;
            padding: 0.55em 0.9em;
            font-size: 0.9em;
        }
        .nav-more-item:hover { color: #e8e8e8; background: #16213e; }
        .nav-more-item.active { color: #e8e8e8; background: #16213e; }
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
            background: #0f1623;
            border-top: 1px solid #1a2744;
            padding: 10px 1em;
            margin-top: 2em;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 0.85em;
        }
        .fb-inner {
            max-width: min(800px, 100vw - 2rem);
            margin: 0 auto;
            display: flex;
            flex-wrap: wrap;
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
