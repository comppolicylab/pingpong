import json
import logging
from typing import List, Tuple

from openfga_sdk import Configuration, Node, TupleKey
from openfga_sdk.client import OpenFgaClient
from openfga_sdk.client.models import (
    ClientCheckRequest,
    ClientExpandRequest,
    ClientListObjectsRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.models import CreateStoreRequest

from .base import AuthzClient, AuthzDriver, RelatedObject, Relation

logger = logging.getLogger(__name__)


_ROOT = "root:0"
"""Singleton root object."""


def _expand_relations(rx: List[Relation] | None) -> List[ClientTuple]:
    if not rx:
        return []
    return [
        ClientTuple(
            user=entity,
            relation=relation,
            object=target,
        )
        for entity, relation, target in rx
    ]


class OpenFgaAuthzClient(AuthzClient):
    def __init__(self, config: Configuration):
        self._cli = OpenFgaClient(config)

    @property
    def root(self) -> str:
        return _ROOT

    async def connect(self):
        return

    async def close(self):
        return await self._cli.close()

    async def list(self, entity: str, relation: str, type_: str) -> list[int]:
        query = ClientListObjectsRequest(
            user=entity,
            relation=relation,
            type=type_,
        )
        response = await self._cli.list_objects(query)
        n = len(type_) + 1
        return [int(slug[n:]) for slug in response.objects]

    async def expand(
        self, entity: str, relation: str, max_depth: int = 1
    ) -> List[RelatedObject]:
        agg = list[RelatedObject]()
        thunks: List[Tuple[str, str, List[str]]] = [(entity, relation, [])]

        def _parse_userset(q: str) -> Tuple[str, str]:
            parts = q.rpartition("#")
            return (parts[0], parts[2])

        def _process_node(node: Node, ctx: list[str]):
            new_ctx = ctx + [node.name]

            # Handle leaf nodes
            if node.leaf:
                if node.leaf.users:
                    for user in node.leaf.users.users:
                        agg.append(
                            RelatedObject(
                                path=new_ctx,
                                entity=user,
                                is_group=False,
                            )
                        )

                if node.leaf.tuple_to_userset:
                    t_ctx = ctx + [node.leaf.tuple_to_userset.tupleset]
                    if len(new_ctx) < max_depth:
                        for computed in node.leaf.tuple_to_userset.computed:
                            new_entity, new_relation = _parse_userset(computed.userset)
                            thunks.append((new_entity, new_relation, t_ctx))
                    else:
                        for computed in node.leaf.tuple_to_userset.computed:
                            agg.append(
                                RelatedObject(
                                    path=t_ctx,
                                    entity=computed.userset,
                                    is_group=True,
                                )
                            )

                if node.leaf.computed:
                    if len(new_ctx) < max_depth:
                        new_entity, new_relation = _parse_userset(
                            node.leaf.computed.userset
                        )
                        thunks.append((new_entity, new_relation, new_ctx))
                    else:
                        agg.append(
                            RelatedObject(
                                path=new_ctx,
                                entity=node.leaf.computed.userset,
                                is_group=True,
                            )
                        )

            # Handle unions by processing each child
            if node.union:
                for child in node.union.nodes:
                    # NOTE: don't pass the *new* context,
                    # just pull it from the union's children.
                    _process_node(child, ctx)

            # Difference and intersection aren't supported yet :(
            # The problem with `max_depth` is that we won't be able to properly
            # compute these operations without a full traversal.
            if node.difference:
                raise NotImplementedError("Difference not supported")

            if node.intersection:
                raise NotImplementedError("Intersection not supported")

        while thunks:
            ent, rel, ctx = thunks.pop()
            query = ClientExpandRequest(
                relation=rel,
                object=ent,
            )
            response = await self._cli.expand(query)
            _process_node(response.tree.root, ctx)

        return agg

    async def check(self, checks: List[Relation]) -> List[bool]:
        query = [
            ClientCheckRequest(
                user=entity,
                relation=relation,
                object=target,
            )
            for entity, relation, target in checks
        ]
        response = await self._cli.batch_check(query)
        return [c.allowed for c in response]

    async def write(
        self,
        grant: List[Relation] | None = None,
        revoke: List[Relation] | None = None,
    ):
        if not grant and not revoke:
            return

        ops = [(True, op) for op in _expand_relations(grant)] + [
            (False, op) for op in _expand_relations(revoke)
        ]
        print("OPS", ops)

        # Can only process 10 operations at a time.
        for i in range(0, len(ops), 10):
            batch = ops[i : i + 10]
            if not batch:
                break
            query = ClientWriteRequest(
                writes=[op for _, op in batch if _] or None,
                deletes=[op for _, op in batch if not _] or None,
            )
            await self._cli.write(query)

    async def create_root_user(self, user_id: int):
        return await self.grant(f"user:{user_id}", "admin", self.root)

    async def write_safe(
        self,
        grant: List[Relation] | None = None,
        revoke: List[Relation] | None = None,
    ):
        filtered_grants = list[Relation]()
        filtered_revokes = list[Relation]()

        #  Filter grants and revokes based on current state.
        for ent, rel, obj in grant or []:
            result = await self._cli.read(
                TupleKey(
                    user=ent,
                    relation=rel,
                    object=obj,
                )
            )
            if not result.tuples:
                filtered_grants.append((ent, rel, obj))

        for ent, rel, obj in revoke or []:
            result = await self._cli.read(
                TupleKey(
                    user=ent,
                    relation=rel,
                    object=obj,
                )
            )
            if result.tuples:
                filtered_revokes.append((ent, rel, obj))

        return await self.write(
            grant=filtered_grants,
            revoke=filtered_revokes,
        )


class OpenFgaAuthzDriver(AuthzDriver):
    def __init__(
        self,
        *,
        scheme: str,
        host: str,
        store: str,
        model_config: str,
        key: str | None = None,
    ):
        cred: Credentials | None = None
        if key:
            cred = Credentials(
                method="api_token",
                configuration=CredentialConfiguration(
                    api_token=key,
                ),
            )

        self.config = Configuration(
            api_scheme=scheme,
            api_host=host,
            credentials=cred,
        )
        self.store = store
        self.model_config = model_config

    def get_client(self):
        return OpenFgaAuthzClient(self.config)

    async def get_or_create_store_by_name(self, name: str):
        async with self.get_client() as ac:
            c = ac._cli
            stores = await c.list_stores()
            for store in stores.stores:
                if store.name == name:
                    logger.info(f"Found store {name} with id {store.id}")
                    return store.id

            req = CreateStoreRequest(name=name)
            resp = await c.create_store(req)
            logger.info(f"Created store {name} with id {resp.id}")
            await c.close()
            return resp.id

    async def init(self):
        store_id = await self.get_or_create_store_by_name(self.store)
        self.config.store_id = store_id

        async with self.get_client() as ac:
            c = ac._cli
            try:
                latest = await c.read_latest_authorization_model()
                self.config.authorization_model_id = latest.authorization_model.id
                logger.info(
                    f"Using existing model with id {self.config.authorization_model_id}"
                )
            except IndexError:
                with open(self.model_config) as f:
                    model = json.load(f)
                    resp = await c.write_authorization_model(model)
                    self.config.authorization_model_id = resp.authorization_model_id
                    logger.info(
                        f"Created model with id {self.config.authorization_model_id}"
                    )

            await c.close()
