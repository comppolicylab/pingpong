from pingpong import schemas


class ClassCredentialValidationUnavailableError(Exception):
    def __init__(
        self,
        provider: schemas.ClassCredentialProvider,
        message: str,
    ) -> None:
        super().__init__(message)
        self.provider = provider


class ClassCredentialValidationSSLError(ClassCredentialValidationUnavailableError):
    pass


class ClassCredentialVoiceValidationError(ValueError):
    pass
