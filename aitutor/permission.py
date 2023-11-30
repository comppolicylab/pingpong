from abc import abstractmethod

from fastapi import HTTPException, Request

from .auth import SessionStatus


class Expression:
    async def __call__(self, request: Request):
        if request.state.session.status != SessionStatus.VALID:
            raise HTTPException(status_code=403, detail="Missing session token")

        if not await self.test(request):
            raise HTTPException(status_code=403, detail="Missing required role")

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


class Or(Expression):
    def __init__(self, *args: Expression):
        self.args = args

    async def test(self, request: Request) -> bool:
        for arg in self.args:
            if await arg.test(request):
                return True
        return False


class And(Expression):
    def __init__(self, *args: Expression):
        self.args = args

    async def test(self, request: Request) -> bool:
        for arg in self.args:
            if not await arg.test(request):
                return False
        return True


class Not(Expression):
    def __init__(self, arg: Expression):
        self.arg = arg

    async def test(self, request: Request) -> bool:
        return not await self.arg.test(request)


class IsSuper(Expression):
    async def test(self, request: Request) -> bool:
        return request.state.session.user.super_admin


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


class LoggedIn(Expression):
    async def test(self, request: Request) -> bool:
        return request.state.session.status == SessionStatus.VALID
