import logging
from abc import abstractmethod

from fastapi import HTTPException, Request


logger = logging.getLogger(__name__)


class Expression:
    async def __call__(self, request: Request):
        if (
            not hasattr(request.state, "auth_user") or request.state.auth_user is None
        ) and (
            not hasattr(request.state, "is_anonymous") or not request.state.is_anonymous
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Missing valid session token: {request.state.session.status.value}",
            )

        if not await self.test_with_cache(request):
            raise HTTPException(status_code=403, detail="Missing required role")

    async def test_with_cache(self, request: Request) -> bool:
        if not hasattr(request.state, "permissions"):
            request.state.permissions = dict[str, bool]()

        key = str(self)
        if key not in request.state.permissions:
            request.state.permissions[key] = await self.test(request)

        return request.state.permissions[key]

    @abstractmethod
    async def test(self, request: Request) -> bool: ...

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


class LoggedIn(Expression):
    async def test(self, request: Request) -> bool:
        return (
            hasattr(request.state, "auth_user") and request.state.auth_user is not None
        ) or request.state.is_anonymous

    def __str__(self):
        return "LoggedIn()"


class Authz(Expression):
    def __init__(self, relation: str, target: str | None = None):
        self.relation = relation
        self.target = target

    async def test(self, request: Request) -> bool:
        try:
            # Format the target with path params.
            target = self.target
            if target:
                target = target.format_map(request.path_params or {})
            else:
                target = request.state.authz.root

            # If the user is anonymous, check their anonymous permissions.
            if request.state.is_anonymous:
                grants_to_check = []
                if request.state.anonymous_share_token_auth:
                    grants_to_check.append(
                        (
                            request.state.anonymous_share_token_auth,
                            self.relation,
                            target,
                        )
                    )
                if request.state.anonymous_session_token_auth:
                    grants_to_check.append(
                        (
                            request.state.anonymous_session_token_auth,
                            self.relation,
                            target,
                        )
                    )
                if not grants_to_check:
                    return False
                results = await request.state.authz.check(grants_to_check)
                return any(results)

            # If the user is logged in, check their permissions.
            return await request.state.authz.test(
                request.state.auth_user,
                self.relation,
                target,
            )
        except Exception as e:
            logger.exception("Error evaluating expression %s: %s", self, e)
            raise HTTPException(status_code=500, detail=str(e))

    def __str__(self):
        return f"Authz({self.relation}, {self.target})"
