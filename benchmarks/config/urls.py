"""Root URLconf: mount the active library's GraphQL view at /graphql/.

The active library is selected by the BENCH_LIB env var. We import
libs/<BENCH_LIB>/bench_schema.py dynamically and mount its exported
graphql_view — a ready-to-use Django view callable each library provides
via the shared operation contract (see benchmarks/README.md).
"""

import importlib
import os

from django.urls import path

_BENCH_LIB = os.environ.get("BENCH_LIB", "graphex")
_bench_schema = importlib.import_module(f"libs.{_BENCH_LIB}.bench_schema")

urlpatterns = [
    path("graphql/", _bench_schema.graphql_view),
]
