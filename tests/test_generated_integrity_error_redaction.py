"""Public GraphQL contracts for unmapped generated-mutation integrity failures."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import DatabaseError, IntegrityError, connection, models, transaction
from django.db.models.signals import post_save
from django.test import RequestFactory, override_settings
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.mutation import DjangoModelMutation
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair


class T10dCheck(models.Model):
    """Signed value constrained only by the database.

    The model is used only with disposable test tables.
    """

    amount = models.IntegerField()
    code = models.CharField(max_length=40, unique=True, null=True)

    class Meta:
        """Keep the regression table isolated from application models.

        It is local to the HTTP integrity-error regression schema.
        """

        app_label = "tests"
        db_table = "test_t10d_check"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="t10d_private_check_name"
            )
        ]


class T10dParent(models.Model):
    """Parent saved before a failing nested child.

    The model is used only with disposable test tables.
    """

    name = models.CharField(max_length=40)

    class Meta:
        """Keep the regression table isolated from application models.

        It is local to the HTTP integrity-error regression schema.
        """

        app_label = "tests"
        db_table = "test_t10d_parent"


class T10dChild(models.Model):
    """Nested child with a database-only check.

    The model is used only with disposable test tables.
    """

    parent = models.ForeignKey(
        T10dParent, on_delete=models.CASCADE, related_name="children"
    )
    amount = models.IntegerField()

    class Meta:
        """Keep the regression table isolated from application models.

        It is local to the HTTP integrity-error regression schema.
        """

        app_label = "tests"
        db_table = "test_t10d_child"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="t10d_private_child_name"
            )
        ]


class T10dConditional(models.Model):
    """Conditional uniqueness is enforced only by the database.

    The model is used only with disposable test tables.
    """

    code = models.CharField(max_length=40)
    active = models.BooleanField(default=True)

    class Meta:
        """Use a disposable partial unique index for the regression.

        It is local to the HTTP integrity-error regression schema.
        """

        app_label = "tests"
        db_table = "test_t10d_conditional"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(active=True),
                name="t10d_private_conditional_name",
            )
        ]


_REGISTRY = Registry()


class T10dCheckMutation(DjangoModelMutation):
    """Generate create and update through the mutation host.

    This test-local host exposes the generated operation under test.
    """

    class Meta:
        """Bind the check model to an isolated registry.

        It is local to the HTTP integrity-error regression schema.
        """

        model = T10dCheck
        registry = _REGISTRY


class T10dParentMutation(DjangoModelMutation):
    """Generate a nested create through the mutation host.

    This test-local host exposes the generated operation under test.
    """

    class Meta:
        """Bind the parent and child to an isolated registry.

        It is local to the HTTP integrity-error regression schema.
        """

        model = T10dParent
        nested_fields = {"children": T10dChild}
        registry = _REGISTRY


class T10dConditionalMutation(DjangoModelMutation):
    """Generate a conditional-uniqueness write through the mutation host.

    This test-local host exposes the generated operation under test.
    """

    class Meta:
        """Bind the conditional model to an isolated registry.

        It is local to the HTTP integrity-error regression schema.
        """

        model = T10dConditional
        registry = _REGISTRY


class T10dCheckType(DjangoModelType):
    """Generate create and update through the model-type host.

    This test-local host exposes the generated operation under test.
    """

    class Meta:
        """Bind the check model to the default registry.

        It is local to the HTTP integrity-error regression schema.
        """

        model = T10dCheck


class T10dParentType(DjangoModelType):
    """Generate a nested create through the model-type host.

    This test-local host exposes the generated operation under test.
    """

    class Meta:
        """Bind the parent and child to the default registry.

        It is local to the HTTP integrity-error regression schema.
        """

        model = T10dParent
        nested_fields = {"children": T10dChild}


class T10dQuery(ObjectType):
    """Provide the required query root for the HTTP schema.

    This test-local host exposes the generated operation under test.
    """

    ping = field(GraphQLString)


def _sibling_write(root: Any, info: Any) -> str:
    """Write a sibling row before a failing generated field.

    Args:
        root: GraphQL root value.
        info: GraphQL resolver metadata.

    Returns:
        The successful sibling field value.
    """
    T10dParent.objects.create(name="sibling")
    return "written"


def _handwritten_failure(root: Any, info: Any) -> str:
    """Raise outside the generated-field adapter.

    Args:
        root: GraphQL root value.
        info: GraphQL resolver metadata.

    Raises:
        IntegrityError: Always, to pin the adapter's generated-only scope.
    """
    raise IntegrityError("private-handwritten-integrity")


class T10dMutationRoot(ObjectType):
    """Mount generated fields from DjangoModelMutation.

    This test-local host exposes the generated operation under test.
    """

    sibling_write = field(GraphQLString, resolver=_sibling_write)
    handwritten_failure = field(GraphQLString, resolver=_handwritten_failure)
    check_create = T10dCheckMutation.CreateField()
    check_update = T10dCheckMutation.UpdateField()
    check_delete = T10dCheckMutation.DeleteField()
    parent_create = T10dParentMutation.CreateField()
    conditional_create = T10dConditionalMutation.CreateField()


class T10dTypeRoot(ObjectType):
    """Mount generated fields from DjangoModelType.

    This test-local host exposes the generated operation under test.
    """

    sibling_write = field(GraphQLString, resolver=_sibling_write)
    check_create = T10dCheckType.CreateField()
    check_update = T10dCheckType.UpdateField()
    check_delete = T10dCheckType.DeleteField()
    parent_create = T10dParentType.CreateField()


SCHEMAS = (
    DjangoGraphQLSchema(
        query=T10dQuery,
        mutation=T10dMutationRoot,
        registries=isolated_pair(_REGISTRY),
    ),
    DjangoGraphQLSchema(query=T10dQuery, mutation=T10dTypeRoot),
)
GENERIC_ERROR = "A database constraint prevented this operation."


def _ensure_tables() -> list[type[models.Model]]:
    """Create only the disposable test tables missing from this connection.

    Returns:
        Model classes whose tables were created here.
    """
    existing = set(connection.introspection.table_names())
    created: list[type[models.Model]] = []
    with connection.schema_editor() as editor:
        for model in (T10dCheck, T10dParent, T10dChild, T10dConditional):
            if model._meta.db_table not in existing:
                editor.create_model(model)
                created.append(model)
    return created


def _drop_tables(created: list[type[models.Model]]) -> None:
    """Remove only tables created by this test.

    Args:
        created: Model classes created by the matching setup.
    """
    with connection.schema_editor() as editor:
        for model in reversed(created):
            editor.delete_model(model)


def _post(schema: DjangoGraphQLSchema, query: str, *, atomic: bool = False) -> Any:
    """Execute a public HTTP mutation with production error formatting.

    Args:
        schema: Compiled generated-mutation schema.
        query: GraphQL mutation document.
        atomic: Whether sibling root writes share a transaction.

    Returns:
        The Django HTTP response.
    """
    request = RequestFactory().post(
        "/graphql/", json.dumps({"query": query}), content_type="application/json"
    )
    with override_settings(DEBUG=False, DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": atomic}):
        return GraphQLView.as_view(schema=schema)(request)


def _input_arg(schema: DjangoGraphQLSchema, field_name: str) -> str:
    """Read the generated input argument's wire name.

    Args:
        schema: Compiled schema.
        field_name: Mutation field's wire name.

    Returns:
        The single generated input argument name.
    """
    return next(iter(schema.graphql_schema.mutation_type.fields[field_name].args))


def _assert_generic_error(payload: dict[str, Any], field_name: str, line: int) -> None:
    """Require the approved top-level error without database details.

    Args:
        payload: Decoded HTTP response body.
        field_name: Mutation field that failed.
        line: Query line containing the field.
    """
    assert payload["data"][field_name] is None
    assert len(payload["errors"]) == 1
    error = payload["errors"][0]
    assert error == {
        "message": GENERIC_ERROR,
        "locations": [{"line": line, "column": 5}],
        "path": [field_name],
    }
    wire = json.dumps(payload)
    assert "t10d_private" not in wire
    assert "test_t10d_" not in wire
    assert "CHECK constraint failed" not in wire


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("operation", ["create", "update"])
def test_generated_root_check_failure_is_redacted(
    schema: DjangoGraphQLSchema, operation: str
) -> None:
    """Hide real check details for both generated hosts and write verbs.

    Args:
        schema: One generated frontend.
        operation: Create or update.
    """
    created = _ensure_tables()
    try:
        row = T10dCheck.objects.create(amount=2) if operation == "update" else None
        field_name = f"check{operation.title()}"
        arg_name = _input_arg(schema, field_name)
        fields = f'id:"{row.pk}", amount:-1' if row else "amount:-1"
        query = (
            "mutation {\n"
            f"    {field_name}({arg_name}: {{{fields}}}) "
            "{ ok errors { field messages } }\n}"
        )
        response = _post(schema, query)
        payload = json.loads(response.content)
        assert response.status_code == 200
        _assert_generic_error(payload, field_name, 2)
        assert list(T10dCheck.objects.values_list("amount", flat=True)) == (
            [2] if row else []
        )
        assert T10dCheck.objects.count() == (1 if row else 0)
    finally:
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("atomic", [False, True])
def test_nested_check_failure_rolls_back_without_leaking(
    schema: DjangoGraphQLSchema, atomic: bool
) -> None:
    """Preserve nested rollback and optional sibling rollback on real SQL failure.

    Args:
        schema: One generated frontend.
        atomic: Whether an earlier sibling also rolls back.
    """
    created = _ensure_tables()
    events: list[str] = []

    def record_commit(sender: Any, instance: T10dParent, **kwargs: Any) -> None:
        """Register a notification marker for a saved parent.

        Args:
            sender: Signal sender.
            instance: Saved parent row.
            **kwargs: Unused signal metadata.
        """
        if instance.name == "failed-parent":
            transaction.on_commit(lambda: events.append("failed-parent"))

    post_save.connect(record_commit, sender=T10dParent, weak=False)
    try:
        arg_name = _input_arg(schema, "parentCreate")
        query = (
            "mutation {\n"
            "    siblingWrite\n"
            f"    parentCreate({arg_name}: "
            '{name:"failed-parent", children:[{amount:-1}]}) '
            "{ ok errors { field messages } }\n}"
        )
        response = _post(schema, query, atomic=atomic)
        payload = json.loads(response.content)
        assert response.status_code == 200
        assert payload["data"]["siblingWrite"] == "written"
        _assert_generic_error(payload, "parentCreate", 3)
        assert T10dParent.objects.filter(name="failed-parent").count() == 0
        assert T10dChild.objects.count() == 0
        assert T10dParent.objects.filter(name="sibling").count() == (0 if atomic else 1)
        assert events == []
    finally:
        post_save.disconnect(record_commit, sender=T10dParent)
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
def test_mapped_unique_error_keeps_structured_payload(
    schema: DjangoGraphQLSchema,
) -> None:
    """Keep an attributable unique conflict out of top-level errors.

    Args:
        schema: One generated frontend.
    """
    created = _ensure_tables()
    try:
        T10dCheck.objects.create(amount=1, code="held")
        arg_name = _input_arg(schema, "checkCreate")
        query = (
            "mutation {\n"
            f'    checkCreate({arg_name}: {{amount:2, code:"held"}}) '
            "{ ok errors { field messages } }\n}"
        )
        response = _post(schema, query)
        payload = json.loads(response.content)
        assert response.status_code == 200
        assert "errors" not in payload
        result = payload["data"]["checkCreate"]
        assert result["ok"] is False
        assert result["errors"][0]["field"] == "code"
        assert T10dCheck.objects.count() == 1
    finally:
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
def test_conditional_unique_violation_is_redacted() -> None:
    """Confirm the documented database-only uniqueness path through HTTP.

    The check remains scoped to this generated-mutation contract.
    """
    created = _ensure_tables()
    try:
        T10dConditional.objects.create(code="held", active=True)
        schema = SCHEMAS[0]
        arg_name = _input_arg(schema, "conditionalCreate")
        query = (
            "mutation {\n"
            f'    conditionalCreate({arg_name}: {{code:"held", active:true}}) '
            "{ ok errors { field messages } }\n}"
        )
        response = _post(schema, query)
        payload = json.loads(response.content)
        assert response.status_code == 200
        _assert_generic_error(payload, "conditionalCreate", 2)
        assert T10dConditional.objects.count() == 1
    finally:
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
def test_direct_backend_keeps_unclassified_integrity_exception() -> None:
    """Keep the direct backend contract outside GraphQL unchanged.

    The check remains scoped to this generated-mutation contract.
    """
    created = _ensure_tables()
    try:
        info = SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))
        with pytest.raises(IntegrityError, match="t10d_private_check_name"):
            T10dCheckMutation._meta.backend.save_object(
                T10dCheckMutation, None, info, {"amount": -1}
            )
        assert T10dCheck.objects.count() == 0
    finally:
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
def test_generated_delete_integrity_failure_is_redacted(
    schema: DjangoGraphQLSchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply the same approved boundary to generated delete resolvers.

    Args:
        schema: One generated frontend.
        monkeypatch: Scoped replacement of model deletion.

    Raises:
        IntegrityError: Injected by the patched delete to simulate a constraint failure with private detail.
    """
    created = _ensure_tables()
    try:
        row = T10dCheck.objects.create(amount=1)

        def fail_delete(self: T10dCheck, **kwargs: Any) -> None:
            """Simulate a database constraint rejected during deletion.

            Args:
                self: Row being deleted.
                **kwargs: Unused Django deletion options.

            Raises:
                IntegrityError: Always.
            """
            raise IntegrityError("private-delete-table.constraint")

        monkeypatch.setattr(T10dCheck, "delete", fail_delete)
        query = (
            "mutation {\n"
            f'    checkDelete(id:"{row.pk}") '
            "{ ok errors { field messages } }\n}"
        )
        response = _post(schema, query)
        payload = json.loads(response.content)
        assert response.status_code == 200
        _assert_generic_error(payload, "checkDelete", 2)
        assert T10dCheck.objects.filter(pk=row.pk).exists()
    finally:
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("schema", SCHEMAS)
def test_generated_success_and_nonintegrity_error_use_http_diagnostics(
    schema: DjangoGraphQLSchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep successful payloads and safely classify unrelated database errors.

    Args:
        schema: One generated frontend.
        monkeypatch: Scoped model-save replacement.

    Raises:
        DatabaseError: Injected by the patched save to simulate a failure that is not an integrity error.
    """
    created = _ensure_tables()
    try:
        arg_name = _input_arg(schema, "checkCreate")
        query = (
            "mutation {\n"
            f"    checkCreate({arg_name}: {{amount:2}}) "
            "{ ok errors { field messages } }\n}"
        )
        response = _post(schema, query)
        payload = json.loads(response.content)
        assert response.status_code == 200
        assert payload["data"]["checkCreate"]["ok"] is True
        assert "errors" not in payload

        def fail_save(self: T10dCheck, **kwargs: Any) -> None:
            """Raise a non-integrity persistence exception.

            Args:
                self: Row being saved.
                **kwargs: Unused Django save options.

            Raises:
                DatabaseError: Always.
            """
            raise DatabaseError("unrelated-database-failure")

        monkeypatch.setattr(T10dCheck, "save", fail_save)
        failed = json.loads(_post(schema, query).content)
        assert failed["data"] == {"checkCreate": None}
        error = failed["errors"][0]
        assert error["message"] == "Unable to complete the data operation."
        assert error["extensions"]["code"] == "DATA_ACCESS_ERROR"
        assert len(error["extensions"]["errorId"]) == 32
        assert "unrelated-database-failure" not in json.dumps(failed)
    finally:
        _drop_tables(created)


@pytest.mark.django_db(transaction=True)
def test_handwritten_mutation_error_is_safe_in_production_http() -> None:
    """Classify an unhandled hand-written integrity failure at the HTTP edge.

    The generated-field adapter does not own this error path.
    """
    response = _post(SCHEMAS[0], "mutation {\n    handwrittenFailure\n}")
    payload = json.loads(response.content)
    assert response.status_code == 200
    assert payload["data"] == {"handwrittenFailure": None}
    error = payload["errors"][0]
    assert error["message"] == "Unable to complete the data operation."
    assert error["extensions"]["code"] == "DATA_ACCESS_ERROR"
    assert len(error["extensions"]["errorId"]) == 32
    assert "private-handwritten-integrity" not in json.dumps(payload)
