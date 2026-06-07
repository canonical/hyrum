"""Sphinx configuration for hyrum documentation."""

import datetime

project = 'Hyrum'
author = 'Canonical Ltd.'
copyright = f'{datetime.date.today().year}'
html_title = project + ' documentation'
ogp_site_url = '/'
ogp_site_name = project
ogp_image = 'https://assets.ubuntu.com/v1/cc828679-docs_illustration.svg'
slug = 'hyrum'

html_baseurl = 'https://canonical.github.io/hyrum/'

extensions = [
    'canonical_sphinx',
    'notfound.extension',
    'sphinx_design',
    'sphinx_reredirects',
    'sphinx_tabs.tabs',
    'sphinxcontrib.jquery',
    'sphinxext.opengraph',
    'sphinx_config_options',
    'sphinx_contributor_listing',
    'sphinx_filtered_toctree',
    'sphinx_llm.txt',
    'sphinx_related_links',
    'sphinx_roles',
    'sphinx_terminal',
    'sphinx_ubuntu_images',
    'sphinx_youtube_links',
    'sphinxcontrib.cairosvgconverter',
    'sphinx_last_updated_by_git',
    'sphinx_sitemap',
]

myst_enable_extensions = {
    'deflist',
    'colon_fence',
}

html_context = {
    'discourse': 'https://discourse.charmhub.io',
    'github_issues': 'https://github.com/canonical/hyrum/issues',
    'repo_default_branch': 'main',
    'repo_folder': 'docs/',
}

linkcheck_ignore = [
    r'https://matrix\.to/.*',
    r'https://www\.hyrumslaw\.com/.*',
]
linkcheck_anchors_ignore_for_url = [
    r'https://github\.com/.*',
    r'https://matrix\.to/.*',
]
linkcheck_retries = 3

sitemap_url_scheme = '{lang}latest/{link}'

exclude_patterns = [
    '_build',
    '.venv',
    '_dev',
    '_templates',
    'Thumbs.db',
    '.DS_Store',
]
