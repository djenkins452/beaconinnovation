"""Product-specific release configuration.

The release *engine* (``engine.py``) is completely product-agnostic. Everything
that differs between AIMS Field, WLJ, UTMC, etc. lives here as a
:class:`ProductConfig` entry in the :data:`PRODUCTS` registry.

To onboard a new product, add a new :class:`ProductConfig` to :data:`PRODUCTS`
and create a ``.claude/commands/release-<key>.md`` slash command that calls::

    python3 scripts/release/release.py <key>

Nothing in the engine needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ProductConfig:
    """Everything the release engine needs to publish one product."""

    # --- identity ---
    key: str                       # short slug used on the CLI / command name
    product_title: str             # branded name shown on the release portal

    # --- source (where Xcode / the build tool drops the export) ---
    source_dir: str                # folder that holds timestamped export folders
    source_folder_glob: str        # glob matching those export folders
    ipa_source_name: str           # IPA filename inside an export folder

    # --- destination (repo-relative, served publicly) ---
    downloads_dir: str             # dir served at download_url_path
    ipa_dest_name: str
    manifest_name: str
    install_page_name: str

    # --- public URLs ---
    base_url: str
    download_url_path: str         # public path prefix for downloads_dir

    # --- archive + deployment ---
    releases_dir: str              # repo-relative permanent archive root
    deploy_branch: str             # branch Railway deploys from
    changelog_path: Optional[str] = None    # optional changelog to append to
    expected_bundle_id: Optional[str] = None  # guard: abort if the IPA disagrees

    # ---- URL helpers -------------------------------------------------
    def public_url(self, filename: str) -> str:
        return f"{self.base_url}{self.download_url_path}/{filename}"

    @property
    def ipa_url(self) -> str:
        return self.public_url(self.ipa_dest_name)

    @property
    def manifest_url(self) -> str:
        return self.public_url(self.manifest_name)

    @property
    def install_url(self) -> str:
        return self.public_url(self.install_page_name)


# ---------------------------------------------------------------------------
# Product registry
# ---------------------------------------------------------------------------
# AIMS Field is fully configured. The commented stubs below show how future
# products slot into the same engine (see FUTURE DESIGN in the release spec).

PRODUCTS: Dict[str, ProductConfig] = {
    "aims": ProductConfig(
        key="aims",
        product_title="AIMS Field",
        source_dir="~/Desktop/AIMS Release Test",
        source_folder_glob="AIMSField *",
        ipa_source_name="AIMSField.ipa",
        downloads_dir="static/downloads",
        ipa_dest_name="AIMSField.ipa",
        manifest_name="manifest.plist",
        install_page_name="install.html",
        base_url="https://beacon-innovation.com",
        download_url_path="/static/downloads",
        releases_dir="releases/aims",
        deploy_branch="main",
        changelog_path="docs/beacon_claude_changelog.md",
        expected_bundle_id="com.beaconinnovation.aims.field",
    ),

    # --- future products (uncomment + fill in when ready) ---
    # "wlj": ProductConfig(
    #     key="wlj",
    #     product_title="WLJ",
    #     source_dir="~/Desktop/WLJ Release Test",
    #     source_folder_glob="WLJ *",
    #     ipa_source_name="WLJ.ipa",
    #     downloads_dir="static/downloads/wlj",
    #     ipa_dest_name="WLJ.ipa",
    #     manifest_name="manifest.plist",
    #     install_page_name="install.html",
    #     base_url="https://beacon-innovation.com",
    #     download_url_path="/static/downloads/wlj",
    #     releases_dir="releases/wlj",
    #     deploy_branch="main",
    # ),
}


def get_product(key: str) -> ProductConfig:
    """Look up a product config or raise a helpful error."""
    try:
        return PRODUCTS[key]
    except KeyError:
        available = ", ".join(sorted(PRODUCTS)) or "(none configured)"
        raise KeyError(
            f"Unknown product '{key}'. Configured products: {available}."
        )
