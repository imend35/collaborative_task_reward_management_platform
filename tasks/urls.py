from django.contrib.auth import views as auth_views
from django.urls import path

from .views import dashboard, register


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("accounts/register/", register, name="register"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
]
