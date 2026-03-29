// Shared navigation bar — injected into all pages
(function() {
    const currentPath = window.location.pathname;
    const links = [
        { href: '/tracker', label: 'Matrix', icon: '&#9638;' },
        { href: '/player', label: 'Player', icon: '&#9835;' },
        { href: '/about', label: 'Pipeline', icon: '&#9881;' },
        { href: '/prompts', label: 'Prompts', icon: '&#10094;&#10095;' },
        { href: '/metrics', label: 'Metrics', icon: '&#9776;' },
        { href: '/examples', label: 'Examples', icon: '&#10077;' },
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
})();
