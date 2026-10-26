from django.urls import path

from . import views

urlpatterns = [
    path("routes/analyze", views.AnalyzeView.as_view(), name="analyze"),
    path("routes/analyze/", views.AnalyzeView.as_view()),
    path("heatmap", views.HeatmapView.as_view(), name="heatmap"),
    path("heatmap/", views.HeatmapView.as_view()),
    path("health", views.health, name="health"),
]
