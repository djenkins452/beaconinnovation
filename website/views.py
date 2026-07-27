import copy
import platform

from django.http import JsonResponse
from django.shortcuts import render
from django.template.context import Context


# Create your views here.
def home(request):
	return render(request, 'home.html', {})


def healthz(request):
	"""Lightweight, unauthenticated health/version endpoint.

	Reports the running Python version and directly exercises the template
	context-copy code path (``copy.copy(Context(...))``) that fails on Python
	3.14 with Django 5.1 ("'super' object has no attribute 'dicts'"). This lets
	the fix be verified in production without needing an authenticated admin
	session.
	"""
	context_copy_ok = True
	error = None
	try:
		duplicate = copy.copy(Context({'probe': 1}))
		# Touch .dicts exactly as the admin change list rendering does.
		_ = duplicate.dicts
	except Exception as exc:  # pragma: no cover - only trips on unsupported Python
		context_copy_ok = False
		error = f'{type(exc).__name__}: {exc}'

	# Report the AIMS product's published build so a deploy can be verified in
	# production without an authenticated admin session. Read-only, defensive:
	# never let this 500 the health check.
	aims = None
	try:
		from products.models import Product
		p = Product.objects.filter(slug='aims').first()
		if p is not None:
			file_present = False
			try:
				file_present = bool(p.download_file and p.download_file.name
									 and p.download_file.storage.exists(p.download_file.name))
			except Exception:
				file_present = False
			aims = {
				'exists': True,
				'version': p.current_version,
				'build': p.current_build,
				'download_enabled': p.download_enabled,
				'file_present': file_present,
				'authorized_users': p.authorized_users.count(),
			}
		else:
			aims = {'exists': False}
	except Exception as exc:  # pragma: no cover
		aims = {'error': f'{type(exc).__name__}: {exc}'}

	return JsonResponse({
		'status': 'ok' if context_copy_ok else 'degraded',
		'python': platform.python_version(),
		'context_copy_ok': context_copy_ok,
		'error': error,
		'aims': aims,
	})
