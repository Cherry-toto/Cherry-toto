#!/usr/bin/env python3
"""
Generate self-hosted profile SVG cards from real GitHub data.

Why this exists: external card services (github-readme-stats.vercel.app,
github-readme-streak-stats.demolab.com, github-profile-trophy.vercel.app,
readme-typing-svg.demolab.com, github-readme-activity-graph.vercel.app)
are frequently unreachable from mainland China, leaving broken images on the
GitHub profile. This script fetches the owner's real data via the GitHub API
and renders everything into committed SVGs served from the repo's own CDN,
which is reliable everywhere.

Run locally:   GH_TOKEN=xxx python3 scripts/gen_profile.py
In CI:        the default GITHUB_TOKEN works (repo owner can read its own data).

No third-party dependencies — Python standard library only.
"""

import os
import sys
import json
import datetime
import urllib.request
import urllib.error

USER = "Cherry-toto"
API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
os.makedirs(OUT_DIR, exist_ok=True)

# ---- palette ----
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
CYAN = "#21d4fd"
PURPLE = "#b721ff"
PINK = "#ff6ec4"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
GREEN0 = "#161b22"
GREEN1 = "#0e4429"
GREEN2 = "#006d32"
GREEN3 = "#26a641"
GREEN4 = "#39d353"

LANG_COLORS = {
    "PHP": "#777BB4", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#563d7c", "Python": "#3572A5",
    "Vue": "#41b883", "Shell": "#89e51b", "C++": "#f34b7d",
    "C": "#555555", "C#": "#178600", "Java": "#b07219",
    "Go": "#00ADD8", "Rust": "#dea584", "Ruby": "#701516",
    "Swift": "#F05138", "Kotlin": "#A97BFF", "Dart": "#00B4AB",
    "Redis": "#d82c20", "nginx": "#009639", "Dockerfile": "#384d54",
    "MySQL": "#4479A1", "PLpgSQL": "#336791", "Lua": "#000080",
    "Objective-C": "#438eff", "CoffeeScript": "#244776", "SCSS": "#c6538c",
    "Less": "#1d365d", "Makefile": "#427819", "Batchfile": "#C1F12E",
}

# ----------------------------------------------------------------------------
# network helpers
# ----------------------------------------------------------------------------
def _req(url, post=None):
    data = json.dumps(post).encode() if post is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if post else "GET")
    req.add_header("Accept", "application/json" if post else "application/vnd.github+json")
    req.add_header("User-Agent", "cherry-profile-gen")
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    if post is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=30)


def get_json(url):
    try:
        with _req(url) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        sys.stderr.write("WARN get_json %s -> %s\n" % (url, e))
        return None


def graphql(query, variables=None):
    body = {"query": query}
    if variables:
        body["variables"] = variables
    try:
        with _req(API + "/graphql", post=body) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        sys.stderr.write("WARN graphql -> %s\n" % e)
        return None


def fmt(n):
    try:
        return "{:,}".format(int(n))
    except Exception:
        return str(n)


# ----------------------------------------------------------------------------
# data gathering
# ----------------------------------------------------------------------------
def gather():
    data = {
        "followers": 0, "following": 0, "public_repos": 0,
        "created_at": "", "total_stars": 0, "total_forks": 0,
        "lang_bytes": {}, "current_streak": 0, "longest_streak": 0,
        "year_contribs": 0, "calendar_days": [],
    }

    me = get_json(API + "/users/" + USER)
    if me:
        data["followers"] = me.get("followers", 0)
        data["following"] = me.get("following", 0)
        data["public_repos"] = me.get("public_repos", 0)
        data["created_at"] = me.get("created_at", "")

    repos = get_json(API + "/users/" + USER + "/repos?per_page=100&type=owner&sort=updated")
    if repos:
        owner_repos = [r for r in repos if not r.get("fork")]
        for r in owner_repos:
            data["total_stars"] += r.get("stargazers_count", 0) or 0
            data["total_forks"] += r.get("forks_count", 0) or 0
            # aggregate language bytes per repo for accurate top-langs
            langs = get_json(r.get("languages_url", ""))
            if langs:
                for lang, nbytes in langs.items():
                    data["lang_bytes"][lang] = data["lang_bytes"].get(lang, 0) + nbytes

    # contributions / streak / heatmap
    q = (
        "query($login: String!) {"
        " user(login: $login) {"
        "  contributionsCollection {"
        "   contributionCalendar {"
        "    totalContributions"
        "    weeks { contributionDays { contributionCount date } }"
        "   }"
        "  }"
        " }"
        " }"
    )
    g = graphql(q, {"login": USER})
    try:
        cal = g["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        data["year_contribs"] = cal.get("totalContributions", 0)
        days = []
        for w in cal.get("weeks", []):
            for d in w.get("contributionDays", []):
                days.append((d["date"], d["contributionCount"]))
        data["calendar_days"] = days
        # current streak: from the last recorded day backwards
        if days:
            cur = 0
            for _, c in reversed(days):
                if c > 0:
                    cur += 1
                else:
                    break
            data["current_streak"] = cur
            # longest streak
            best = run = 0
            for _, c in days:
                if c > 0:
                    run += 1
                    best = max(best, run)
                else:
                    run = 0
            data["longest_streak"] = best
    except Exception as e:
        sys.stderr.write("WARN parse calendar -> %s\n" % e)

    return data


# ----------------------------------------------------------------------------
# small svg helpers
# ----------------------------------------------------------------------------
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def heat_color(c):
    if c <= 0:
        return GREEN0
    if c <= 2:
        return GREEN1
    if c <= 4:
        return GREEN2
    if c <= 6:
        return GREEN3
    return GREEN4


# ----------------------------------------------------------------------------
# card renderers
# ----------------------------------------------------------------------------
def render_top_langs(d):
    langs = sorted(d["lang_bytes"].items(), key=lambda kv: kv[1], reverse=True)[:6]
    total = sum(v for _, v in langs) or 1
    bar_x = 150
    bar_max = 270
    rows = []
    for i, (lang, nbytes) in enumerate(langs):
        pct = nbytes * 100.0 / total
        w = max(2, int(bar_max * pct / 100.0))
        y = 56 + i * 30
        color = LANG_COLORS.get(lang, CYAN)
        rows.append(
            '<text x="16" y="%d" font-family="Segoe UI, PingFang SC, sans-serif" font-size="13" '
            'fill="%s">%s</text>' % (y + 4, TEXT, esc(lang))
            + '<rect x="%d" y="%d" width="%d" height="14" rx="7" fill="%s"/>'
            % (bar_x, y, bar_max, PANEL)
            + '<rect x="%d" y="%d" width="%d" height="14" rx="7" fill="%s"/>'
            % (bar_x, y, w, color)
            + '<text x="%d" y="%d" font-family="Segoe UI, PingFang SC, sans-serif" font-size="11" '
            'fill="%s" text-anchor="end">%.1f%%</text>' % (bar_x + bar_max, y + 12, MUTED, pct)
        )
    title = "Top Languages" if langs else "Top Languages"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 460 195" width="460" height="195">'
        '<defs><linearGradient id="g2" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
        '<rect x="0" y="0" width="460" height="195" rx="12" fill="%s"/>'
        '<rect x="0" y="0" width="460" height="4" rx="2" fill="url(#g2)"/>'
        '<text x="16" y="30" font-family="Segoe UI, PingFang SC, sans-serif" font-size="16" '
        'font-weight="800" fill="%s">%s</text>'
        '%s</svg>'
        % (CYAN, PURPLE, BG, TEXT, title, "".join(rows))
    )


def render_streak(d):
    cs = d["current_streak"]
    ls = d["longest_streak"]
    yc = d["year_contribs"]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 460 175" width="460" height="175">'
        '<defs><linearGradient id="g3" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
        '<rect x="0" y="0" width="460" height="175" rx="12" fill="%s"/>'
        '<rect x="0" y="0" width="460" height="4" rx="2" fill="url(#g3)"/>'
        '<text x="16" y="30" font-family="Segoe UI, PingFang SC, sans-serif" font-size="16" '
        'font-weight="800" fill="%s">Streak Stats</text>'
        # flame that flickers
        '<text x="28" y="92" font-size="34">\U0001F525'
        '<animate attributeName="opacity" values="1;0.6;1" dur="1.4s" repeatCount="indefinite"/></text>'
        '<text x="72" y="82" font-family="Segoe UI, PingFang SC, sans-serif" font-size="30" '
        'font-weight="800" fill="%s">%s</text>'
        '<text x="72" y="104" font-family="Segoe UI, PingFang SC, sans-serif" font-size="12" fill="%s">'
        'Current Streak (days)</text>'
        '<text x="250" y="72" font-family="Segoe UI, PingFang SC, sans-serif" font-size="22" '
        'font-weight="800" fill="%s">%s</text>'
        '<text x="250" y="92" font-family="Segoe UI, PingFang SC, sans-serif" font-size="11" fill="%s">Longest</text>'
        '<text x="250" y="124" font-family="Segoe UI, PingFang SC, sans-serif" font-size="22" '
        'font-weight="800" fill="%s">%s</text>'
        '<text x="250" y="144" font-family="Segoe UI, PingFang SC, sans-serif" font-size="11" fill="%s">'
        'Contributions (1y)</text>'
        '</svg>'
        % (PINK, PURPLE, BG, TEXT, PINK, fmt(cs), MUTED, CYAN, fmt(ls), MUTED, PURPLE, fmt(yc), MUTED)
    )


def render_activity(d):
    days = d["calendar_days"]
    weeks = []
    # rebuild week columns (7 rows) from the flat list
    # GitHub returns weeks already; rebuild a grid of up to 53 columns x 7
    # we stored flat list; group into weeks of 7 by the original order.
    # Simpler: re-fetch structure not stored; rebuild column-major from flat days.
    cols = []
    for i in range(0, len(days), 7):
        cols.append(days[i:i + 7])
    cell = 13
    gap = 3
    left = 16
    top = 40
    blocks = []
    for ci, col in enumerate(cols):
        for ri, (date, cnt) in enumerate(col):
            x = left + ci * (cell + gap)
            y = top + ri * (cell + gap)
            blocks.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"/>'
                         % (x, y, cell, cell, heat_color(cnt)))
    grid_w = left + len(cols) * (cell + gap)
    H = top + 7 * (cell + gap) + 10
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">'
        '<rect x="0" y="0" width="%d" height="%d" rx="12" fill="%s"/>'
        '<text x="16" y="26" font-family="Segoe UI, PingFang SC, sans-serif" font-size="16" '
        'font-weight="800" fill="%s">\U0001F308 Contribution Activity</text>'
        '<text x="%d" y="%d" font-family="Segoe UI, PingFang SC, sans-serif" font-size="11" fill="%s">'
        'Last 12 months \u00b7 %s contributions</text>'
        '%s</svg>'
        % (grid_w, H, grid_w, H, grid_w, H, BG, TEXT, grid_w - 16, H - 8, MUTED,
           fmt(d["year_contribs"]), "".join(blocks))
    )


def render_typing():
    phrase = "Hi there! I'm Cherry-toto \U0001F44B"
    W, H = 720, 90
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + str(W) + ' ' + str(H) + '" width="' + str(W) + '" height="' + str(H) + '">'
        '<defs><clipPath id="typed">'
        '<rect x="0" y="0" width="' + str(W) + '" height="' + str(H) + '">'
        '<animate attributeName="width" values="0;' + str(W) + ';' + str(W) + ';0" keyTimes="0;0.7;0.95;1" '
        'dur="7s" repeatCount="indefinite"/></rect></clipPath></defs>'
        '<rect x="0" y="0" width="' + str(W) + '" height="' + str(H) + '" rx="12" fill="' + BG + '"/>'
        '<text x="24" y="54" font-family="Fira Code, Consolas, monospace" font-size="26" '
        'font-weight="700" fill="' + TEXT + '" clip-path="url(#typed)">' + esc(phrase) + '</text>'
        '<rect x="' + str(W - 20) + '" y="26" width="3" height="34" fill="' + PINK + '">'
        '<animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/></rect>'
        '</svg>'
    )


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    d = gather()
    sys.stderr.write("data: followers=%s repos=%s stars=%s streak=%s contribs=%s\n"
                     % (d["followers"], d["public_repos"], d["total_stars"],
                        d["current_streak"], d["year_contribs"]))
    out = {
        "top-langs.svg": render_top_langs(d),
        "streak.svg": render_streak(d),
        "activity.svg": render_activity(d),
        "typing.svg": render_typing(),
    }
    for name, svg in out.items():
        path = os.path.join(OUT_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        sys.stderr.write("wrote %s (%d bytes)\n" % (name, len(svg)))
    print("OK: generated %d SVGs into %s" % (len(out), os.path.normpath(OUT_DIR)))


if __name__ == "__main__":
    main()
