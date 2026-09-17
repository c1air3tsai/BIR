from django.urls import path
from . import views

app_name = "search"

urlpatterns = [
    path("", views.search_view, name="home"),
    path("articles/", views.articles_view, name="articles"),
    path("document/<int:pk>/", views.document_detail_view, name="document_detail"),
    path("document/<int:pk>/xml/", views.download_xml_view, name="download_xml"),
    path("document/<int:pk>/delete/", views.delete_document_view, name="delete_document"),
    path("upload/", views.import_view, name="import"),
]
