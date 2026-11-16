from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from sysop import views as sysop_views

urlpatterns = [
    path('sysop/', include('sysop.urls')),
    path('admin/', admin.site.urls),

    path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    path('login/', auth_views.LoginView.as_view()),
    path('accounts/logout/', auth_views.logout_then_login, name='logout'),
    path('accounts/profile/', sysop_views.user_detail, name='user_detail'),
    path('accounts/password/change/',
         auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password/change/done/',
         auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('accounts/password/reset/',
         auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password/reset/done/',
         auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/password/reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/password/done/',
         auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # Everything in sysop.urls has historically also been served from the
    # site root, and external consumers fetch /servers.json, /rotates.json
    # and /APRServe2.txt from there. The namespace keeps reverse() pointing
    # at the canonical /sysop/ URLs.
    path('', include(('sysop.urls', 'sysop'), namespace='root')),
]
