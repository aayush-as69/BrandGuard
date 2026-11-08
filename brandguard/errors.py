"""Domain errors. NotFound and Forbidden are deliberately NOT LookupError / PermissionError:
those built-ins are also raised by genuine bugs (a missing dict key, an OS file error),
which would then be shown to users as a harmless 404 or 403."""


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class RateLimited(Exception):
    pass
