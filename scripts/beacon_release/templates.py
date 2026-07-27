"""Rendered deployment artifacts (manifest + Release Portal).

Templates use ``{{TOKEN}}`` placeholders (not ``str.format``) so CSS braces don't
collide. :func:`render` does a plain replace of every ``{{KEY}}``.
"""

from __future__ import annotations

from typing import Dict


def render(template: str, context: Dict[str, str]) -> str:
    out = template
    for key, value in context.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


MANIFEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>items</key>
    <array>
        <dict>
            <key>assets</key>
            <array>
                <dict>
                    <key>kind</key>
                    <string>software-package</string>
                    <key>url</key>
                    <string>{{IPA_URL}}</string>
                </dict>
            </array>
            <key>metadata</key>
            <dict>
                <key>bundle-identifier</key>
                <string>{{BUNDLE_ID}}</string>
                <key>bundle-version</key>
                <string>{{VERSION}}</string>
                <key>kind</key>
                <string>software</string>
                <key>title</key>
                <string>{{PRODUCT_TITLE}}</string>
            </dict>
        </dict>
    </array>
</dict>
</plist>
"""


INSTALL_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Install {{PRODUCT_TITLE}}</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0b1622;
            color: #f5f7fa;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 40px 24px 64px;
        }
        .card { width: 100%; max-width: 460px; }
        header { text-align: center; margin-bottom: 32px; }
        h1 { font-size: 1.9rem; margin-bottom: 6px; }
        .meta { color: #8fa3b8; font-size: 0.95rem; line-height: 1.5; }
        .meta strong { color: #cdd9e5; font-weight: 600; }
        .install-btn {
            display: block;
            width: 100%;
            padding: 22px 24px;
            margin: 28px 0 8px;
            font-size: 1.35rem;
            font-weight: 600;
            color: #fff;
            background: #0a84ff;
            border: none;
            border-radius: 16px;
            text-decoration: none;
            text-align: center;
            box-shadow: 0 8px 24px rgba(10, 132, 255, 0.35);
            -webkit-tap-highlight-color: transparent;
        }
        .install-btn:active { background: #0060df; }
        .notes {
            margin-top: 28px;
            background: #10202f;
            border: 1px solid #1c3346;
            border-radius: 14px;
            padding: 20px 22px;
        }
        .notes h2 {
            font-size: 1.0rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #7fb2ff;
            margin-bottom: 12px;
        }
        .notes ul { list-style: none; }
        .notes li {
            position: relative;
            padding-left: 20px;
            margin-bottom: 8px;
            font-size: 0.95rem;
            line-height: 1.45;
            color: #dbe4ee;
        }
        .notes li::before {
            content: "";
            position: absolute;
            left: 4px;
            top: 8px;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #0a84ff;
        }
        .notes li.muted { color: #8fa3b8; }
        .notes li.muted::before { background: #4a5f74; }
        .history { margin-top: 20px; }
        .history table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        .history th, .history td {
            text-align: left; padding: 8px 10px; border-bottom: 1px solid #1c3346;
            color: #cdd9e5;
        }
        .history th { color: #7fb2ff; font-weight: 600; font-size: 0.8rem;
            text-transform: uppercase; letter-spacing: 0.04em; }
        .note {
            margin-top: 28px;
            font-size: 0.85rem;
            line-height: 1.5;
            color: #8fa3b8;
            text-align: center;
        }
        footer {
            margin-top: 32px;
            font-size: 0.72rem;
            color: #5c6f82;
            text-align: center;
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <div class="card">
        <header>
            <h1>{{PRODUCT_TITLE}}</h1>
            <p class="meta">
                Version <strong>{{VERSION}}</strong> &middot; Build <strong>{{BUILD}}</strong><br>
                Released {{RELEASE_DATE}}
            </p>
        </header>

        <a class="install-btn"
           href="itms-services://?action=download-manifest&amp;url={{MANIFEST_URL}}">
            Install {{PRODUCT_TITLE}}
        </a>

{{WHATS_NEW_SECTION}}{{BUG_FIXES_SECTION}}{{KNOWN_ISSUES_SECTION}}{{PREVIOUS_RELEASES_SECTION}}
        <p class="note">
            Open this page in Safari on your iPhone, then tap the button above.
            When prompted, tap <strong>Install</strong>. After installation, go to
            <strong>Settings &rarr; General &rarr; VPN &amp; Device Management</strong>
            and trust the developer to launch the app.
        </p>

        <footer>
            {{BUNDLE_ID}} &middot; requires iOS {{MIN_IOS}}+<br>
            Beacon Innovation LLC
        </footer>
    </div>
</body>
</html>
"""


NOTES_SECTION_TEMPLATE = """\
        <section class="notes">
            <h2>{{HEADING}}</h2>
            <ul>
{{ITEMS}}
            </ul>
        </section>

"""


PREVIOUS_RELEASES_TEMPLATE = """\
        <section class="notes history">
            <h2>Previous Releases</h2>
            <table>
                <tr><th>Version</th><th>Build</th><th>Released</th></tr>
{{ROWS}}
            </table>
        </section>

"""
