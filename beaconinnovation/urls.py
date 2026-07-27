from django.contrib import admin
from django.urls import path, re_path, include
from django.conf import settings
from django.conf.urls.static import static

from distribution import views as distribution_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin-console/', include('admin_console.urls')),
    path('finance/', include('finance.urls')),
    path('products/', include('products.urls')),
    path('wlj/', include('wlj.urls')),
    # Beacon distribution: release portals + artifacts at /downloads/<product>/
    re_path(r'^downloads/(?P<product>[\w-]+)/$',
            distribution_views.download_index, name='download_index'),
    re_path(r'^downloads/(?P<product>[\w-]+)/(?P<path>.+)$',
            distribution_views.serve_download, name='serve_download'),
    path('', include('website.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
