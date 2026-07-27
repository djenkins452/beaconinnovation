"""
Views for the secure product download portal.

Workflow: log in -> My Products (only authorized products) -> product page ->
Download Latest Version. Downloads are served through an authenticated view
that re-checks authorization on every request; the underlying file URL is
never exposed to users.
"""
import mimetypes
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Product

LOGIN_URL = 'products:login'

# Users placed in this group at bootstrap must change their (temporary) password
# before they can use the portal. Django's built-in Group is reused as a simple,
# persistent flag — no extra model needed. The flag is cleared on first change.
PASSWORD_CHANGE_REQUIRED_GROUP = 'portal_must_change_password'


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
    """Show a single product with a Download Latest Version button.

    Returns 404 (not 403) for products the user isn't authorized to access, so
    the portal never reveals the existence of products a user can't see.
    """
    product = get_object_or_404(Product, slug=slug)
    if not product.user_can_access(request.user):
        raise Http404("Product not found")
    return render(request, 'products/product_detail.html', {'product': product})


@login_required(login_url=LOGIN_URL)
@require_password_changed
def product_download(request, slug):
    """Serve the current build to an authorized user.

    Authorization is re-verified here on every request. The file is streamed as
    an attachment; the storage URL is never handed to the client.
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
