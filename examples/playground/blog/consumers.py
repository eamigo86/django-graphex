"""WebSocket consumer exposing the subscriptions (one per stream)."""

from django_graphex.subscriptions import GraphqlAPIDemultiplexer

from .schema import CommentSubscription, NoteModelType, PostSubscription


class AppDemultiplexer(GraphqlAPIDemultiplexer):
    # Iterable form: streams are derived from each Subscription/DjangoModelType
    # (NoteModelType is a DjangoModelType -> its generated subscription is used).
    subscriptions = {PostSubscription, CommentSubscription, NoteModelType}
