from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogPayload:
    error_type: str | None
    level: str
    message: str
    test: bool = False

    def as_json(self) -> dict[str, str | bool | None]:
        body: dict[str, str | bool | None] = {
            "errortype": self.error_type,
            "level": self.level,
            "message": self.message,
        }
        if self.test:
            body["test"] = True
        return body
