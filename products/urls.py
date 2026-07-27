"""URL configuration for the product download portal."""
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import Group
from django.urls import path, reverse_lazy

from . import views
from .views import PASSWORD_CHANGE_REQUIRED_GROUP

app_name = 'products'


class PortalPasswordChangeView(auth_views.PasswordChangeView):
    """Standard password change that also clears the 'must change password'
    flag once the user sets a new password."""
    template_name = 'products/password_change.html'
    success_url = reverse_lazy('products:password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        group = Group.objects.filter(name=PASSWORD_CHANGE_REQUIRED_GROUP).first()
        if group:
            self.request.user.groups.remove(group)
        return response

urlpatterns = [
    # Authentication
    path('login/', views.portal_login, name='login'),
    path('logout/', views.portal_logout, name='logout'),

    # Password management (reuses Django's built-in secure views).
    path('password/change/', PortalPasswordChangeView.as_view(), name='password_change'),
    path(
        'password/change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='products/password_change_done.html',
        ),
        name='password_change_done',
    ),

    # Portal
    path('', views.my_products, name='my_products'),
    path('<slug:slug>/', views.product_detail, name='detail'),
    path('<slug:slug>/download/', views.product_download, name='download'),
]
