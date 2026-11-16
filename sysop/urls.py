from django.urls import path

from . import views

urlpatterns = [
    path('', views.own_servers, name='own_servers'),
    path('all', views.all_servers, name='all_servers'),
    path('server/<int:server_id>/', views.server_detail, name='server_detail'),
    path('servers.json', views.servers_json, name='servers_json'),
    path('rotates.json', views.rotates_json, name='rotates_json'),
    path('APRServe2.txt', views.server_list, name='server_list'),
]
