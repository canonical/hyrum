"""Sphinx configuration for hyrum documentation.

Follows the Canonical Sphinx stack (https://github.com/canonical/sphinx-stack).
Sections marked [BEYOND SPHINX STACK] go beyond what the stack provides.
"""

import datetime

#######################
# Project information #
#######################

project = 'Hyrum'
author = 'Canonical Ltd.'
copyright = f'{datetime.date.today().year}'

# Sidebar documentation title.
html_title = project + ' documentation'

# [BEYOND SPHINX STACK] These docs are published to GitHub Pages rather than
# Read the Docs behind the canonical.com proxy, so there is no version slug and
# no Read the Docs flyout to rewrite.
html_baseurl = 'https://canonical.github.io/hyrum/'

# Documentation website URL.
ogp_site_url = html_baseurl

# Preview name of the documentation website.
ogp_site_name = project

# Preview image URL.
ogp_image = 'https://assets.ubuntu.com/v1/cc828679-docs_illustration.svg'

# Project slug.
slug = 'hyrum'

# Values passed into the Sphinx context for all pages.
html_context = {
    # Product page URL, without the 'https://' prefix.
    'product_page': 'github.com/canonical/hyrum',
    # Discourse instance URL.
    'discourse': 'https://discourse.charmhub.io',
    # Mattermost channel URL.
    'mattermost': '',
    # Matrix channel URL.
    'matrix': 'https://matrix.to/#/#charmhub-charmdev:ubuntu.com',
    # Documentation GitHub repository URL; adds links for viewing the
    # documentation source files at the bottom of each page.
    'github_url': 'https://github.com/canonical/hyrum',
    # Docs branch in the repo; used in links for viewing the source files.
    'repo_default_branch': 'main',
    # Docs location in the repo; used in links for viewing the source files.
    'repo_folder': '/docs/',
    # Listing contributors on individual pages.
    'display_contributors': False,
    # Required for the feedback button.
    'github_issues': 'enabled',
    # Passes the top-level 'author' value to the theme.
    'author': author,
    # Documentation license information.
    'license': {
        'name': 'Apache-2.0',
        'url': 'https://github.com/canonical/hyrum/blob/main/LICENSE.txt',
    },
}

#######################
# Sitemap configuration
#######################

# The docs are served from the root of the GitHub Pages site, and only one
# version is published, so page URLs are html_baseurl + link.
sitemap_url_scheme = '{link}'

# Include `lastmod` dates in the sitemap.
sitemap_show_lastmod = True

# Pages excluded from the sitemap.
sitemap_excludes = [
    '404/',
    'genindex/',
    'search/',
]

################################
# Template and asset locations #
################################

# There is no '_static' directory yet: the only custom CSS and JS are the
# Canonical cookie-banner assets, which are loaded from assets.ubuntu.com.
templates_path = ['_templates']

#############
# Redirects #
#############

# Add client-side redirects here, or set to 'redirects.txt' to load them from
# that file. See https://sphinxext-rediraffe.readthedocs.io/en/latest/
rediraffe_redirects = {}

# Strips '/index.html' from destination URLs when building with 'dirhtml'.
rediraffe_dir_only = True

############################
# sphinx-llm configuration #
############################

llms_txt_description = (
    'This is the documentation for hyrum, a tool that bulk-runs a check such as '
    'lint or unit tests across many charm repositories, optionally swapping out one '
    'of their dependencies first.'
)

###########################
# Link checker exceptions #
###########################

# A regex list of URLs that are ignored by 'make linkcheck'.
linkcheck_ignore = [
    r'https://matrix\.to/.*',
    r'https://www\.hyrumslaw\.com/.*',
]

# A regex list of URLs where anchors are ignored by 'make linkcheck'.
linkcheck_anchors_ignore_for_url = [
    r'https://github\.com/.*',
    r'https://matrix\.to/.*',
]

# Give linkcheck multiple tries on failure.
linkcheck_retries = 3

########################
# Configuration extras #
########################

# Custom MyST syntax extensions. Assigning to this replaces the set that
# canonical-sphinx enables by default, so the defaults are repeated here.
myst_enable_extensions = {
    'substitution',
    'deflist',
    'linkify',
    'colon_fence',
}

extensions = [
    'canonical_sphinx',
    'notfound.extension',
    'sphinx_design',
    'sphinx_rerediraffe',
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
    'sphinx.ext.intersphinx',
    'sphinx_sitemap',
]

# Excludes files or directories from processing. '_dev' holds the Vale styles,
# which contain Markdown that is not part of these docs.
exclude_patterns = [
    '_build',
    '.venv',
    '_dev',
    '_templates',
    'Thumbs.db',
    '.DS_Store',
]

# Adds custom CSS files, located remotely or in 'html_static_path'.
html_css_files = [
    'https://assets.ubuntu.com/v1/d86746ef-cookie_banner.css',
]

# Adds custom JavaScript files, located remotely or in 'html_static_path'.
html_js_files = [
    'https://assets.ubuntu.com/v1/287a5e8f-bundle.js',
]

# Configuration for Intersphinx projects.
intersphinx_mapping = {
    'juju': ('https://documentation.ubuntu.com/juju/3.6/', None),
    'operator': ('https://canonical.com/juju/docs/ops/latest/', None),
}
