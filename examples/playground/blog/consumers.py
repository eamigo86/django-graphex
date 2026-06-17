"""WebSocket consumer for subscriptions (v2.0 native graphql-transport-ws).

The legacy ``GraphqlAPIDemultiplexer`` (HTTP ``channelId`` handshake + per-stream
demultiplexing) was removed in v2.0. Subscriptions now run on the native engine
behind two standards-based transports; this module builds the WebSocket one.
"""

from django_graphex.subscriptions.transports.ws import subscription_ws_consumer

from .schema import schema

# A Channels AsyncJsonWebsocketConsumer subclass speaking graphql-transport-ws
# (connection_init/ack, multiplexed subscribe, ping/pong, per-id complete).
# The WS transport executes against the live graphql-core schema, so pass
# ``schema.graphql_schema`` (the GraphQLSchema), NOT the DjangoGraphQLSchema
# wrapper — graphql-core's validate / create_source_event_stream cannot consume
# the wrapper.
AppWSConsumer = subscription_ws_consumer(schema=schema.graphql_schema)
