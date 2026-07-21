import os
import sys
import re
import json
import glob
import argparse
import urllib.request
from xml.sax.saxutils import escape

CARD_W = 340
CARD_H = 170

START_MARKER = "<!-- PINNED-PROJECTS:START -->"
END_MARKER = "<!-- PINNED-PROJECTS:END -->"

def graphql(query, token):
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "User-Agent": "profile-readme-card-generator",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def fetch_pinned(username, token):
    query = f'''
    {{
      user(login: "{username}") {{
        pinnedItems(first: 6, types: [REPOSITORY]) {{
          nodes {{
            ... on Repository {{
              name
              url
              description
              stargazerCount
              primaryLanguage {{ name color }}
            }}
          }}
        }}
      }}
    }}
    '''
    data = graphql(query, token)
    return data["data"]["user"]["pinnedItems"]["nodes"]

def load_local_projects(config_path="projects.json"):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def merge_with_local_overrides(api_repos, local_projects):
    overrides = {p["name"]: p for p in local_projects}
    for repo in api_repos:
        name = repo["name"]
        if name in overrides:
            ov = overrides[name]
            repo["language"] = ov.get("language", repo.get("language"))
            repo["language_color"] = ov.get("language_color", repo.get("language_color"))
            if "description" in ov:
                repo["description"] = ov["description"]
            if "stars" in ov:
                repo["stargazerCount"] = ov["stars"]
    return api_repos

def safe_filename(name):
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name).lower()

def wrap_text(text, max_chars=46):
    words = text.split()
    lines, current = [], ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = (current + " " + w).strip()
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines[:2]

def render_card_svg(repo):
    name = repo["name"]
    description = repo.get("description") or ""
    lang_name = repo.get("language") or repo.get("primaryLanguage", {}).get("name", "Unknown")
    lang_color = repo.get("language_color") or repo.get("primaryLanguage", {}).get("color") or "#8b949e"
    stars = repo.get("stars") or repo.get("stargazerCount", 0)
    url = repo.get("url", "#")

    desc_lines = wrap_text(description)
    desc_svg = ""
    for i, line in enumerate(desc_lines):
        desc_svg += f'<text x="24" y="{78 + i * 20}" fill="#8b949e" font-size="13">{escape(line)}</text>\n'

    footer_y = 78 + len(desc_lines) * 20 + 14

    return f'''<svg viewBox="0 0 {CARD_W} {CARD_H}" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif">
  <rect x="1" y="1" width="{CARD_W - 2}" height="{CARD_H - 2}" rx="6" fill="#0d1117" stroke="#30363d"/>
  <g transform="translate(24,32) scale(0.9)">
    <path fill="#8b949e" d="M0 2a2 2 0 012-2h9.5a.25.25 0 01.25.25V5H14V.25A.25.25 0 0114.25 0H16a2 2 0 012 2v12.5a.25.25 0 01-.25.25h-1.5a.25.25 0 01-.25-.25V13H2v1.5a.25.25 0 01-.25.25H.25A.25.25 0 010 14.5V2z"/>
  </g>
  <text x="46" y="38" fill="#58a6ff" font-size="16" font-weight="600">{escape(name)}</text>
  {desc_svg}
  <circle cx="28" cy="{footer_y}" r="6" fill="{lang_color}"/>
  <text x="40" y="{footer_y + 5}" fill="#8b949e" font-size="12">{escape(lang_name)}</text>
  <text x="130" y="{footer_y + 5}" fill="#8b949e" font-size="12">&#9733; {stars}</text>
</svg>'''

def update_readme(readme_path, cards_markdown):
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    if START_MARKER not in content or END_MARKER not in content:
        print(f"::error::Could not find {START_MARKER} / {END_MARKER} markers in {readme_path}")
        sys.exit(1)

    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    replacement = f"{START_MARKER}\n{cards_markdown}\n{END_MARKER}"
    new_content = pattern.sub(replacement, content)

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_content)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate project cards for GitHub profile README")
    parser.add_argument("--local", action="store_true", help="Read projects from local projects.json instead of GitHub API")
    parser.add_argument("--config", default="projects.json", help="Path to local projects config (default: projects.json)")
    parser.add_argument("username", nargs="?", help="GitHub username (required for API mode)")
    parser.add_argument("repo_owner_repo", nargs="?", help="repo_owner/repo_name where card SVGs + README live (required for API mode)")
    args = parser.parse_args()

    if args.local:
        repos = load_local_projects(args.config)
        repo_owner_repo = os.environ.get("GITHUB_REPOSITORY") or "xinitkey/xinitkey"
    else:
        username = args.username
        repo_owner_repo = args.repo_owner_repo
        if not username or not repo_owner_repo:
            parser.error("username and repo_owner_repo are required for API mode (use --local for local mode)")
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("GITHUB_TOKEN not set, falling back to local mode")
            repos = load_local_projects(args.config)
        else:
            repos = fetch_pinned(username, token)
            local = load_local_projects(args.config)
            repos = merge_with_local_overrides(repos, local)

    for f in glob.glob("card-*.svg"):
        os.remove(f)

    cards_md_parts = []
    for repo in repos:
        fname = f"card-{safe_filename(repo['name'])}.svg"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(render_card_svg(repo))
        raw_url = f"https://raw.githubusercontent.com/{repo_owner_repo}/main/{fname}"
        cards_md_parts.append(
            f'  <a href="{repo["url"]}"><img src="{raw_url}" width="340" /></a>'
        )

    cards_markdown = '<p align="center">\n' + "\n".join(cards_md_parts) + "\n</p>"
    update_readme("README.md", cards_markdown)
    print(f"Generated {len(repos)} card(s)")
