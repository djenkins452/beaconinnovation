"""
Views for the secure product download portal.

Workflow: log in -> My Products (only authorized products) -> product page ->
Install (iOS OTA) or Download (raw file).

Two download paths, both authorization-enforced:

* Session path (``product_download``): the authenticated browser download used
  by the "Download IPA" action (desktop, or optional on iOS). Gated by the
  login session + product authorization.

* OTA path (``product_manifest`` / ``product_ota_download``): Apple's
  over-the-air install. The iOS system installer (itunesstored) fetches the
  manifest and IPA WITHOUT the browser's session cookie, so these endpoints
  cannot use ``@login_required``. Instead they are gated by a short-lived,
  signed token that is minted only inside the authenticated, authorized
  session (on the product page) and re-checked for authorization on every
  fetch. Knowing a URL is not enough — a valid, unexpired, correctly-scoped
  token is required, and the encoded user must still be authorized.
"""
import mimetypes
import plistlib
from functools import wraps
from urllib.parse import quote

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Product

LOGIN_URL = 'products:login'

# Users placed in this group at bootstrap must change their (temporary) password
# before they can use the portal. Django's built-in Group is reused as a simple,
# persistent flag — no extra model needed. The flag is cleared on first change.
PASSWORD_CHANGE_REQUIRED_GROUP = 'portal_must_change_password'

# OTA install tokens: signed (HMAC via SECRET_KEY) + timestamped, scoped to a
# (user, product). Short-lived — long enough to complete an install, short
# enough to limit exposure of a shared link.
OTA_TOKEN_SALT = 'products.ota.install.v1'
OTA_TOKEN_MAX_AGE = 20 * 60  # seconds


def user_must_change_password(user):
    """True if the user is flagged to change their temporary password."""
    return (
        user.is_authenticated
        and user.groups.filter(name=PASSWORD_CHANGE_REQUIRED_GROUP).exists()
    )


def require_password_changed(view):
    """Redirect a flagged user to the change-password page before any portal page."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if user_must_change_password(request.user):
            return redirect('products:password_change')
        return view(request, *args, **kwargs)
    return wrapper


# =============================================================================
# OTA helpers
# =============================================================================

def make_ota_token(user, product):
    """Mint a signed, timestamped install token for (user, product)."""
    return signing.dumps({'u': user.pk, 'p': product.slug}, salt=OTA_TOKEN_SALT, compress=True)


def resolve_ota_token(token, slug):
    """Return the User a valid token belongs to (scoped to ``slug``), else None."""
    if not token:
        return None
    try:
        data = signing.loads(token, salt=OTA_TOKEN_SALT, max_age=OTA_TOKEN_MAX_AGE)
    except (signing.BadSignature, signing.SignatureExpired, Exception):
        return None
    if not isinstance(data, dict) or data.get('p') != slug:
        return None
    return get_user_model().objects.filter(pk=data.get('u')).first()


def _https_url(request, path_with_query):
    """Absolute URL forced to https (Apple OTA requires https end-to-end;
    behind Railway's TLS proxy request.scheme may otherwise be http)."""
    return f'https://{request.get_host()}{path_with_query}'


def _is_ios_user_agent(ua):
    """Server-side iOS detection. iPhone/iPod are reliable; iPadOS commonly
    reports a macOS UA (desktop-site default) and is refined client-side."""
    ua = ua or ''
    return ('iPhone' in ua) or ('iPad' in ua) or ('iPod' in ua)


def build_ota_manifest(product, ipa_url):
    """Return the Apple OTA manifest (.plist XML bytes) for ``product``."""
    plist = {
        'items': [{
            'assets': [{
                'kind': 'software-package',
                'url': ipa_url,
            }],
            'metadata': {
                'bundle-identifier': product.bundle_id,
                'bundle-version': product.current_version or '1.0',
                'kind': 'software',
                'title': product.name,
            },
        }],
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


# =============================================================================
# Authentication
# =============================================================================

def portal_login(request):
    """Log a user into the download portal."""
    if request.user.is_authenticated:
        return redirect('products:my_products')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next') or reverse('products:my_products')
            return redirect(next_url)
        error = 'Invalid username or password.'

    context = {
        'error': error,
        'next': request.GET.get('next', ''),
    }
    return render(request, 'products/login.html', context)


@login_required(login_url=LOGIN_URL)
def portal_logout(request):
    """Log the user out and return to the login page."""
    logout(request)
    return redirect('products:login')


# =============================================================================
# Portal
# =============================================================================

@login_required(login_url=LOGIN_URL)
@require_password_changed
def my_products(request):
    """List only the products the current user is authorized to access."""
    products = request.user.products.all().order_by('name')
    return render(request, 'products/my_products.html', {'products': products})


@login_required(login_url=LOGIN_URL)
@require_password_changed
def product_detail(request, slug):
    """Show a single product with device-aware install/download actions.

    Returns 404 (not 403) for products the user isn't authorized to access, so
    the portal never reveals the existence of products a user can't see.
    """
    product = get_object_or_404(Product, slug=slug)
    if not product.user_can_access(request.user):
        raise Http404("Product not found")

    is_ios = _is_ios_user_agent(request.META.get('HTTP_USER_AGENT', ''))

    # Build the OTA install link only for installable iOS builds. The token is
    # minted here, inside the authorized session.
    install_url = None
    if product.ota_capable:
        token = make_ota_token(request.user, product)
        manifest_url = _https_url(
            request,
            reverse('products:manifest', args=[product.slug]) + '?token=' + quote(token, safe=''),
        )
        install_url = 'itms-services://?action=download-manifest&url=' + quote(manifest_url, safe='')

    return render(request, 'products/product_detail.html', {
        'product': product,
        'is_ios': is_ios,
        'install_url': install_url,
    })


@login_required(login_url=LOGIN_URL)
@require_password_changed
def product_download(request, slug):
    """Serve the current build to an authorized, logged-in browser (the
    "Download IPA" action). Authorization re-verified per request; the file is
    streamed as an attachment; the storage URL is never handed to the client.
    """
    product = get_object_or_404(Product, slug=slug)

    if not product.user_can_access(request.user):
        raise Http404("Product not found")

    if not product.is_available:
        raise Http404("No download is currently available for this product.")

    content_type, _ = mimetypes.guess_type(product.filename)
    content_type = content_type or 'application/octet-stream'

    try:
        response = FileResponse(
            product.download_file.open('rb'),
            content_type=content_type,
        )
    except FileNotFoundError:
        raise Http404("Download file is missing. Please contact an administrator.")

    response['Content-Disposition'] = f'attachment; filename="{product.filename}"'
    return response


# =============================================================================
# OTA install (token-gated; NO session cookie — fetched by the iOS installer)
# =============================================================================

def product_manifest(request, slug):
    """Serve the Apple OTA manifest for a valid install token.

    Not @login_required: the iOS installer fetches this without cookies.
    Authorization is enforced by the signed token + a fresh authorization check.
    """
    product = get_object_or_404(Product, slug=slug)

    user = resolve_ota_token(request.GET.get('token', ''), slug)
    if user is None or not product.user_can_access(user):
        return HttpResponseForbidden('This installation link is invalid or has expired.')

    if not product.ota_capable:
        raise Http404('Over-the-air install is not available for this product.')

    # Mint a fresh token for the IPA fetch so the download step has a full window.
    ipa_token = make_ota_token(user, product)
    ipa_url = _https_url(
        request,
        reverse('products:ota_download', args=[slug]) + '?token=' + quote(ipa_token, safe=''),
    )

    response = HttpResponse(
        build_ota_manifest(product, ipa_url),
        content_type='text/xml; charset=utf-8',
    )
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    return response


def product_ota_download(request, slug):
    """Stream the IPA to the iOS installer for a valid install token.

    Not @login_required: fetched by the installer without cookies. Gated by the
    signed token + a fresh authorization check.
    """
    product = get_object_or_404(Product, slug=slug)

    user = resolve_ota_token(request.GET.get('token', ''), slug)
    if user is None or not product.user_can_access(user):
        return HttpResponseForbidden('This installation link is invalid or has expired.')

    if not product.is_available:
        raise Http404('No build is currently available for this product.')

    try:
        response = FileResponse(
            product.download_file.open('rb'),
            content_type='application/octet-stream',
        )
    except FileNotFoundError:
        raise Http404('Build file is missing. Please contact an administrator.')

    response['Content-Disposition'] = f'attachment; filename="{product.filename}"'
    response['Cache-Control'] = 'no-store'
    return response
