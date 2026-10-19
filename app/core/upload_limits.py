"""Bound request bodies before multipart spooling, and files before a second copy."""
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024
UPLOAD_PATHS = frozenset(('/api/v1/v9/analyze', '/visualization/analyze', '/visualization/batch'))
PROJECT_UPLOAD_PATH = '/api/v1/intersections'
PROJECT_REQUEST_BYTES = 16 * 1024**3 + 1024 * 1024
ONLINE_REQUEST_BYTES = 16 * 1024**2


class UploadLimitExceeded(HTTPException):
    # FastAPI retains HTTPException during dependency/multipart parsing; a plain
    # ValueError is converted into generic 400 before outer middleware can see it.
    def __init__(self, reason):
        super().__init__(status_code=413, detail=reason)

    def __str__(self):
        return str(self.detail)


def copy_upload(source, sink, *, max_bytes=MAX_UPLOAD_BYTES):
    size = 0
    while chunk := source.read(min(1024 * 1024, max_bytes - size + 1)):
        size += len(chunk)
        if size > max_bytes:
            raise UploadLimitExceeded('UPLOAD_BYTE_BUDGET_EXCEEDED')
        sink.write(chunk)
    return size


class UploadLimitMiddleware:
    def __init__(self, app, *, max_bytes=MAX_REQUEST_BYTES):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        online=scope.get('path','').startswith('/api/v1/intersections/') and '/online/' in scope.get('path','')
        if scope['type'] != 'http' or scope['method'] != 'POST' or (scope['path'] not in UPLOAD_PATHS | {PROJECT_UPLOAD_PATH} and not online):
            return await self.app(scope, receive, send)
        limit = ONLINE_REQUEST_BYTES if online else PROJECT_REQUEST_BYTES if scope['path'] == PROJECT_UPLOAD_PATH else self.max_bytes
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
            if declared < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({'detail': 'INVALID_CONTENT_LENGTH'}, 400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({'detail': 'REQUEST_BYTE_BUDGET_EXCEEDED'}, 413)(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message['type'] == 'http.request':
                size += len(message.get('body', b''))
                if size > limit:
                    raise UploadLimitExceeded('REQUEST_BYTE_BUDGET_EXCEEDED')
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except UploadLimitExceeded as exc:
            await JSONResponse({'detail': str(exc)}, 413)(scope, receive, send)
