"""Product configuration — loaded from a product repo's `release.yaml`.

The engine is product-agnostic: everything product-specific comes from
`release.yaml`. This module loads it, validates the required fields, and exposes
a typed :class:`ProductConfig`. The engine never guesses — a missing or invalid
field is a hard error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from yamlcompat import load_yaml


class ConfigError(Exception):
    """Raised when release.yaml is missing or invalid."""


@dataclass(frozen=True)
class ProductConfig:
    # identity
    key: str
    display_name: str
    name: Optional[str]           # CFBundleName guard (validated vs IPA)
    bundle_id: Optional[str]      # CFBundleIdentifier guard (validated vs IPA)

    # source (in the product repo)
    pending_dir: str
    ipa_name: Optional[str]

    # beacon repo (deploy target); None -> engine's own repo root
    beacon_repo: Optional[str]

    # deploy
    base_url: str
    url_path: str                 # canonical public path, e.g. /downloads/aims
    deploy_branch: str
    poll_timeout: int
    legacy_redirects: List[str] = field(default_factory=list)

    # portal
    show_previous_releases: bool = True

    # fixed artifact filenames
    manifest_name: str = "manifest.plist"
    install_page_name: str = "install.html"

    # ---- URL helpers ----
    def public_url(self, filename: str) -> str:
        return f"{self.base_url.rstrip('/')}{self.url_path.rstrip('/')}/{filename}"

    @property
    def install_url(self) -> str:
        return self.public_url(self.install_page_name)

    @property
    def manifest_url(self) -> str:
        return self.public_url(self.manifest_name)

    def ipa_url(self, ipa_filename: str) -> str:
        return self.public_url(ipa_filename)

    @property
    def downloads_subpath(self) -> str:
        """Path component after /downloads/, e.g. 'aims' from '/downloads/aims'."""
        return self.url_path.strip("/").split("/", 1)[-1]


def load_product_config(product_repo: Path) -> ProductConfig:
    yaml_path = Path(product_repo) / "release.yaml"
    if not yaml_path.is_file():
        raise ConfigError(
            f"No release.yaml in {product_repo}. This is not a Beacon product repo — "
            f"install the release starter kit first (see scripts/beacon_release/starter-kit/)."
        )
    try:
        data = load_yaml(yaml_path.read_text())
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"Could not parse {yaml_path}: {exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"{yaml_path} did not parse to a mapping.")

    product = data.get("product") or {}
    source = data.get("source") or {}
    beacon = data.get("beacon") or {}
    deploy = data.get("deploy") or {}
    portal = data.get("portal") or {}

    def require(section: dict, section_name: str, key: str):
        val = section.get(key)
        if val in (None, ""):
            raise ConfigError(f"release.yaml: missing required '{section_name}.{key}'.")
        return val

    key = str(require(product, "product", "key")).strip()
    display_name = str(require(product, "product", "display_name")).strip()
    base_url = str(require(deploy, "deploy", "base_url")).strip()
    url_path = str(require(deploy, "deploy", "url_path")).strip()
    if not url_path.startswith("/"):
        raise ConfigError("release.yaml: deploy.url_path must start with '/' (e.g. /downloads/aims).")

    legacy = deploy.get("legacy_redirects") or []
    if isinstance(legacy, str):
        legacy = [legacy]

    return ProductConfig(
        key=key,
        display_name=display_name,
        name=(str(product["name"]).strip() if product.get("name") else None),
        bundle_id=(str(product["bundle_id"]).strip() if product.get("bundle_id") else None),
        pending_dir=str(source.get("pending_dir", "releases/pending")),
        ipa_name=(str(source["ipa_name"]).strip() if source.get("ipa_name") else None),
        beacon_repo=(str(beacon["repo"]).strip() if beacon.get("repo") else None),
        base_url=base_url,
        url_path=url_path,
        deploy_branch=str(deploy.get("deploy_branch", "main")),
        poll_timeout=int(deploy.get("poll_timeout", 900)),
        legacy_redirects=[str(x).strip() for x in legacy if str(x).strip()],
        show_previous_releases=bool(portal.get("show_previous_releases", True)),
    )
