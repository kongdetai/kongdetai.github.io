# AGENTS.md

## Cursor Cloud specific instructions

### What this repo is
A personal GitHub Pages site (`kongdetai.github.io`, a Chinese finance blog "每日财经日志")
built on the **Minimal Mistakes** Jekyll theme, plus a **Python daily finance-log
generator**. The repo also still contains the upstream Minimal Mistakes theme sources
(`_layouts`, `_sass`, `_includes`, `assets`) and its demo/test harnesses under `docs/`
and `test/`.

There are two relevant "services":
1. The Jekyll site (root `_config.yml`) — the main product.
2. `scripts/generate_daily_finance_log.py` — generates the daily post (run by the
   `daily-finance-log` GitHub Action).

### Environment / dependencies
- Ruby 3.2 + Bundler are used for the site. Bundler is configured with a global gem
  path (`~/.gem-bundle`), so `bundle install` works without `sudo`. The update script
  runs `bundle install` against the **root** `Gemfile` (which pulls in `github-pages`).
- Node is only needed for the theme's optional JS build tooling (`package.json`).
- The Python generator is **stdlib-only** (no pip install needed).

### Running the site (main product)
- Build: `bundle exec jekyll build`
- Serve (dev): `bundle exec jekyll serve --host 0.0.0.0 --port 4000` then open
  `http://localhost:4000/`.
- Gotcha: `_config.yml` uses `remote_theme: "mmistakes/minimal-mistakes"`, so the first
  build **fetches the theme from GitHub** (needs network). Local `_layouts`/`_sass`/etc.
  override the remote theme. The homepage uses the custom `finance-home` layout.
- The `GitHub Metadata: No GitHub API authentication...` warning during build is harmless.

### Running the finance-log generator
- `python3 scripts/generate_daily_finance_log.py`
- It reads the `.claude/skills/zhengxi-views` submodule for the method framework. If you
  need it populated, run `git submodule update --init --recursive`; the script still
  runs and degrades gracefully ("skill references missing") when the submodule is empty.
- It fetches public Chinese market endpoints (Tencent/Sina are usually reachable;
  Eastmoney/Xueqiu may report "unavailable") and **overwrites** today's
  `_posts/<YYYY-MM-DD>-finance-log.md`. Back up / `git checkout` that file if you don't
  intend to commit a regenerated version.

### Tests / lint
- There is no formal test suite or linter. Verify changes by building/serving the site
  and by running the generator.
- Optional theme JS build: `npm install && npm run build:js` (re-minifies
  `assets/js/main.min.js`; don't commit the regenerated file unless that is the intent).
- `docs/` and `test/` have their own `Gemfile`s (theme demo site & local-gem test
  harness, e.g. `bundle exec rake preview`); they are not needed to run the main site.
