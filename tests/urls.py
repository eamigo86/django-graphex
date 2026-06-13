from django.contrib import admin
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from django_graphex.views import GraphQLView as GraphQLView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql", csrf_exempt(GraphQLView.as_view(graphiql=True)), name="graphql"),
]
