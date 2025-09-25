from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('calculate', views.calculate, name='calculate'),
    path('dashboard', views.dashboard, name='dashboard'),
    path('delete/<int:calc_id>/', views.delete_calculation, name='delete_calculation'),
    path('settings/', views.settings, name='settings'),
    path('ChatGPT/', views.ChatGPT, name='ChatGPT'),
    path('bootstrap/', views.bootstrap, name='bootstrap'),
    path('calculator/<str:calc_type>/', views.calculator, name='calculator'),
    path('password/', views.password, name='password'),
    path('meme/', views.meme_generator, name='meme_generator'),
    path('api/meme/', views.get_meme_api, name='get_meme_api'),
    path('startup/', views.startup_ideas, name='startup_ideas'),
    path('webtoons/', views.webtoon_recommendations, name='webtoon_recommendations'),
    path('api/webtoons/', views.get_webtoon_api, name='get_webtoon_api'),
    path('movies/', views.movie_recommendations, name='movie_recommendations'),
    path('api/movies/', views.get_movie_api, name='get_movie_api'),
    path('customer/<str:pk_test>/', views.customer, name='customer'),
]