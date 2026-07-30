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
class LegacyInstall:
    """Temporary secondary publication target (e.g. a public /static/downloads/
    installer used until a customer has Portal access).

    It is NOT a second release artifact: only the lightweight ``install.html`` +
    ``manifest.plist`` are published here, and the manifest points its OTA asset
    at the canonical Portal IPA. One IPA, one SHA-256. ``enabled: false`` (or
    omitting the block) disables it with no effect on the primary workflow.
    """
    enabled: bool = False
    url_path: str = "/static/downloads"       # public path that serves the two files
    served_dirs: tuple = ()                    # Beacon-repo dirs backing url_path
    manifest_name: str = "manifest.plist"
    install_page_name: str = "install.html"


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

    # release must come from a fully synchronized product repo (fetch + exact
    # match to origin/<deploy_branch> + clean tree). Default on; deterministic.
    require_sync: bool = True

    # Provenance-based publishing (Design Amendment 001). When the exported IPA
    # carries a Beacon provenance stamp, the engine verifies it (built commit ==
    # HEAD == origin/<branch>, and clean == true). `require_provenance` makes a
    # valid stamp MANDATORY — an unstamped or dirty artifact is then refused.
    # Default off during migration: unstamped IPAs still publish under the existing
    # step-0 clean-tree guard, and a stamp, when present, is verified as a bonus.
    require_provenance: bool = False

    # portal
    show_previous_releases: bool = True

    # optional metadata (products become almost configuration-only; all optional)
    public_name: Optional[str] = None   # user-facing name (overrides display_name on the portal)
    description: Optional[str] = None    # short product description shown on the portal
    icon: Optional[str] = None           # icon URL (absolute, or path under the download namespace)
    platform: str = "ios"               # ios | android | … (informational; default ios)

    # fixed artifact filenames
    manifest_name: str = "manifest.plist"
    install_page_name: str = "install.html"

    # temporary secondary publication target (optional; disabled by default)
    legacy_install: LegacyInstall = field(default_factory=LegacyInstall)

    @property
    def portal_title(self) -> str:
        """User-facing title: public_name if given, else the branded display_name."""
        return self.public_name or self.display_name

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

    # ---- legacy install target URLs (only meaningful when enabled) ----
    def legacy_url(self, filename: str) -> str:
        base = self.base_url.rstrip("/")
        path = self.legacy_install.url_path.rstrip("/")
        return f"{base}{path}/{filename}"

    @property
    def legacy_install_url(self) -> str:
        return self.legacy_url(self.legacy_install.install_page_name)

    @property
    def legacy_manifest_url(self) -> str:
        return self.legacy_url(self.legacy_install.manifest_name)


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

    legacy_install = _parse_legacy_install(deploy.get("legacy_install") or {})

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
        require_sync=bool(deploy.get("require_sync", True)),
        require_provenance=bool(deploy.get("require_provenance", False)),
        show_previous_releases=bool(portal.get("show_previous_releases", True)),
        # optional metadata — all absent-safe
        public_name=(str(product["public_name"]).strip() if product.get("public_name") else None),
        description=(str(product["description"]).strip() if product.get("description") else None),
        icon=(str(product["icon"]).strip() if product.get("icon") else None),
        platform=(str(product.get("platform", "ios")).strip() or "ios"),
        legacy_install=legacy_install,
    )


def _parse_legacy_install(raw: dict) -> LegacyInstall:
    """Parse the optional `deploy.legacy_install` block. Absent/disabled → a
    disabled LegacyInstall (the engine then behaves exactly as before)."""
    enabled = bool(raw.get("enabled", False))
    url_path = str(raw.get("url_path", "/static/downloads")).strip()
    dirs = raw.get("served_dirs") or []
    if isinstance(dirs, str):
        dirs = [dirs]
    served_dirs = tuple(str(d).strip() for d in dirs if str(d).strip())
    if enabled:
        if not url_path.startswith("/"):
            raise ConfigError(
                "release.yaml: deploy.legacy_install.url_path must start with '/' "
                "(e.g. /static/downloads)."
            )
        if not served_dirs:
            raise ConfigError(
                "release.yaml: deploy.legacy_install.served_dirs is required when "
                "legacy_install.enabled is true (the Beacon-repo dir(s) that back "
                "url_path, e.g. static/downloads + staticfiles/downloads)."
            )
    return LegacyInstall(
        enabled=enabled,
        url_path=url_path,
        served_dirs=served_dirs,
        manifest_name=str(raw.get("manifest_name", "manifest.plist")).strip() or "manifest.plist",
        install_page_name=str(raw.get("install_page_name", "install.html")).strip() or "install.html",
    )
