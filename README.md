# Swaraj's Plugin Marketplace

A custom Claude plugin marketplace for creative tools.

## Available Plugins

| Plugin | Description |
|--------|-------------|
| [video-reels](https://github.com/mahanswaray/video-reels-plugin) | Raw footage to polished short-form reels pipeline |
| [session-viewer](session-viewer/) | SQLite-backed Claude Code session browser, file recovery & usage analytics |

## How to use this marketplace

1. In Claude, run: `/plugin marketplace add mahanswaray/swaraj-plugins`
2. Browse available plugins: `/plugin marketplace list`
3. Install a plugin: `/plugin install video-reels`

## Adding plugins

Add new entries to `.claude-plugin/marketplace.json` and push to GitHub.
