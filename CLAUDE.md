# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JMComic-Crawler-Python (`jmcomic`) is a Python API and CLI tool for downloading manga from JMComic (18comic). It supports two client implementations: HTML (web scraping, faster but IP-restricted) and API (mobile app protocol with AES decryption, more compatible). Python >=3.9 required.

## Build & Test

```bash
# Setup dev environment
uv venv
uv pip install -r requirements-dev.txt -e ./

# Run all tests
cd ./tests/ && python -m unittest

# Run a single test module
cd ./tests/ && python -m unittest test_jmcomic.test_html_client

# Run a single test case
cd ./tests/ && python -m unittest test_jmcomic.test_html_client.TestHtmlClient.test_specific_method
```

No linter or formatter is configured in this project.

## Branch & Release Strategy

- **`dev`** — all code PRs target this branch
- **`docs`** — documentation-only changes
- **`master`** — production; push with commit message starting with `v` triggers auto-release via `release_auto.yml` (creates GitHub Release + publishes to PyPI)
- **Never open PRs directly to `master`**

Release commit format: `v<version>: <change1>; <change2>; ...` (parsed by `.github/release.py`)

## Architecture

Module dependency chain (left is depended upon by right):
```
config <--- entity <--- toolkit <--- client <--- option <--- downloader
```

| Module | Responsibility |
|--------|---------------|
| `jm_config.py` | Central config: constants, registries, logging (`jm_log`), default option dict, domain lists, crypto keys |
| `jm_entity.py` | Data models: `JmAlbumDetail`, `JmPhotoDetail`, `JmImageDetail`, search/favorite/category pages |
| `jm_toolkit.py` | Utilities: HTML/API parsing (regex), image scramble/decode, crypto (AES, MD5, token), DSL text resolution |
| `jm_client_interface.py` | Client interfaces: `JmcomicClient` composite interface + `JmDetailClient`, `JmImageClient`, etc. |
| `jm_client_impl.py` | Implementations: `JmHtmlClient` (web scraping), `JmApiClient` (mobile API with AES), `PhotoConcurrentFetcherProxy` (concurrent fetch) |
| `jm_option.py` | YAML config object (`JmOption`), `DirRule` (DSL path rules), `CacheRegistry`, client creation, plugin invocation |
| `jm_plugin.py` | Plugin system: `JmOptionPlugin` base + 17 built-in plugins (login, zip, img2pdf, email, etc.) |
| `jm_downloader.py` | Download orchestrator: multi-threaded album→photo→image pipeline with plugin hooks at each stage |
| `api.py` | Public API: `download_album()`, `download_photo()`, `create_option_by_file()`, `new_downloader()` |
| `cl.py` | CLI: `jmcomic` (downloader) and `jmv` (album viewer) entry points |

### Download Pipeline Flow

```
download_album() → JmDownloader.download_album()
  → before_album (plugin) → download_by_photo_detail (multi-thread)
    → before_photo (plugin) → download_by_image_detail (multi-thread)
      → client.download_by_image_detail() → JmImageResp.transfer_to()
    → after_photo (plugin)
  → after_album (plugin)
```

### Plugin System

Plugins extend functionality at lifecycle hooks. Each plugin has a `plugin_key` and `invoke(**kwargs)` method. Auto-registered at package init via `JmModuleConfig.register_plugin`. Plugin groups: `after_init`, `before_album`/`after_album`, `before_photo`/`after_photo`, `before_image`/`after_image`, `main`, `after_download`. Configured in YAML option files under `plugins:` key. Exception handling per plugin: `ignore`/`log`(default)/`raise`.

### Client Architecture

`AbstractJmClient` provides retry, domain switching, and caching. Two concrete implementations:
- `JmHtmlClient` — scrapes web pages, faster but IP-restricted
- `JmApiClient` — uses mobile app API, requires AES decryption, more compatible

Clients are registered in `JmModuleConfig` and selected via option config (`client.impl`).

## Coding Guidelines

- **Logging**: Use `from jmcomic import jm_log` — never `import logging` directly. Call `jm_log('topic', 'message')` or `jm_log('topic', exception_obj)` for auto-traceback.
- **Exceptions**: Use `ExceptionTool.raises()` / `raises_resp()` instead of raw `raise Exception()`. This ensures `ExceptionListener` callbacks fire correctly.
- **Type hints**: Add type annotations to all new code.
- **Version**: Update `__version__` in `src/jmcomic/__init__.py` for releases.

## Key Configuration

- Option files (YAML): `assets/option/` contains test and workflow configs
- `DEFAULT_OPTION_DICT` in `jm_config.py` defines the full config schema
- Test config loaded via env var `JM_OPTION_PATH_TEST`
- CI test workflows: `test_api.yml` (API client), `test_html.yml` (HTML client), both with 5-min timeout
