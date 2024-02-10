import logging
from abc import abstractmethod

from fastapi import HTTPException, Request

from .authz.openfga import Query
from .schemas import SessionStatus

logger = logging.getLogger(__name__)


class Expression:
    async def __call__(self, request: Request):
        if request.state.session.status != SessionStatus.VALID:
            raise HTTPException(status_code=403, detail="Missing session token")

        if not await self.test_with_cache(request):
            logger.warning(
                f"Permission denied for user {request.state.session.user.id} on {self}"
            )
            raise HTTPException(status_code=403, detail="Missing required role")

    async def test_with_cache(self, request: Request) -> bool:
        if not hasattr(request.state, "permissions"):
            request.state.permissions = dict[str, bool]()

        key = str(self)
        if key not in request.state.permissions:
            request.state.permissions[key] = await self.test(request)

        return request.state.permissions[key]

    @abstractmethod
    async def test(self, request: Request) -> bool:
        ...

    def __or__(self, other):
        return Or(self, other)

    def __and__(self, other):
        return And(self, other)

    def __invert__(self):
        return Not(self)

    def __ror__(self, other):
        return Or(other, self)

    def __rand__(self, other):
        return And(other, self)

    def __str__(self):
        return f"{self.__class__.__name__}()"


class Or(Expression):
    def __init__(self, *args: Expression):
        self.args = args

    async def test(self, request: Request) -> bool:
        for arg in self.args:
            if await arg.test(request):
                return True
        return False

    def __str__(self):
        return f"Or({', '.join(str(arg) for arg in self.args)})"


class And(Expression):
    def __init__(self, *args: Expression):
        self.args = args

    async def test(self, request: Request) -> bool:
        for arg in self.args:
            if not await arg.test(request):
                return False
        return True

    def __str__(self):
        return f"And({', '.join(str(arg) for arg in self.args)})"


class Not(Expression):
    def __init__(self, arg: Expression):
        self.arg = arg

    async def test(self, request: Request) -> bool:
        return not await self.arg.test(request)

    def __str__(self):
        return f"Not({self.arg})"


class IsSuper(Expression):
    async def test(self, request: Request) -> bool:
        return request.state.session.user.super_admin


class IsUser(Expression):
    def __init__(self, user_id_field):
        self.user_id_field = user_id_field

    async def test(self, request: Request) -> bool:
        return request.state.session.user.id == int(
            request.path_params[self.user_id_field]
        )


class CanRead(Expression):
    def __init__(self, model, id_field):
        self.model = model
        self.id_field = id_field

    async def test(self, request: Request) -> bool:
        # Get the model ID from the request path.
        model_id = request.path_params[self.id_field]
        # Get the model from the database.
        return await self.model.can_read(
            request.state.db, model_id, request.state.session.user
        )

    def __str__(self):
        return f"CanRead({self.model.__name__}, {self.id_field})"


class CanWrite(Expression):
    def __init__(self, model, id_field):
        self.model = model
        self.id_field = id_field

    async def test(self, request: Request) -> bool:
        # Get the model ID from the request path.
        model_id = request.path_params[self.id_field]
        # Get the model from the database.
        return await self.model.can_write(
            request.state.db, model_id, request.state.session.user
        )

    def __str__(self):
        return f"CanWrite({self.model.__name__}, {self.id_field})"


class CanManage(Expression):
    def __init__(self, model, id_field):
        self.model = model
        self.id_field = id_field

    async def test(self, request: Request) -> bool:
        # Get the model ID from the request path.
        model_id = request.path_params[self.id_field]
        # Get the model from the database.
        return await self.model.can_manage(
            request.state.db, model_id, request.state.session.user
        )

    def __str__(self):
        return f"CanManage({self.model.__name__}, {self.id_field})"


class LoggedIn(Expression):
    async def test(self, request: Request) -> bool:
        return request.state.session.status == SessionStatus.VALID

    def __str__(self):
        return "LoggedIn()"


class Authz(Expression):
    def __init__(self, relation: str, target: str | None = None):
        self.relation = relation
        self.target = target

    async def test(self, request: Request) -> bool:
        try:
            response = await request.state.authz.check(
                Query(request.state.session.user.id, self.relation, self.target),
            )
            return response.allowed
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def __str__(self):
        return f"Authz({self.relation}, {self.target})"
