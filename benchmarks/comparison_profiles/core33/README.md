# Named whole-stack comparison inputs

The four constraint files are exact freezes observed from isolated Python
3.12.11/Django 6.0.8 installations. They are NOT benchmark measurements.
Graphex uses current source with its runtime dependencies, including Pydantic,
dateutil, and unidecode; Graphene retains the django-filter package imported
by its unchanged benchmark adapter. Graphex and Strawberry use GraphQL-core
3.3.0; Graphene and Ariadne use their compatible GraphQL-core 3.2.13.

The historical eight result files and shared constraints remain unchanged.
Bootstrap with `benchmarks/setup_envs.sh --profile core33` after reviewing the
root benchmark guide. The separate runner must record the source commit and
must not claim these dependency freezes are timing results.
