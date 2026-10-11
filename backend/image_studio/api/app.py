"""FastAPI server and built React assets on a single local origin."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from image_studio.core.paths import IMAGES, FRONTEND
from image_studio.api.routes import router
from image_studio.api.photocraft import router as photocraft_router
from image_studio.services import workflows, assistant
from image_studio.integrations import bridge
from image_studio.services.runtime import render_session


def editor_handler(name):
    def run(request, progress):
        if not render_session.acquire(blocking=False):
            raise ValueError(
                'The studio is already rendering. Wait for it to finish before starting another job.'
            )
        try:
            workflows.engine.cancelled.clear()
            return getattr(workflows, f'editor_{name}')(request, progress)
        finally:
            render_session.release()

    return run


@asynccontextmanager
async def lifespan(app):
    assistant.before_load.append(
        lambda: workflows.engine.unload() if workflows.engine.model_key == 'kontext' else None
    )
    bridge.library_saver = workflows.save_from_editor
    server = bridge.start(
        {name: editor_handler(name) for name in ['create', 'edit', 'plan', 'segment', 'enhance', 'faces', 'grade']},
        workflows.stop,
    )
    yield
    workflows.stop()
    server.shutdown()
    server.server_close()


app = FastAPI(title='Local Image Studio', version='2.0.0', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


@app.middleware('http')
async def local_requests(request, call_next):
    # Browsers on other websites cannot submit GPU work or desktop commands. The engine's own
    # address is allowed too: the desktop app may run it on another port when 7860 is taken
    # (the Host header is already limited to this machine by TrustedHostMiddleware).
    origin = request.headers.get('origin')
    if (
        request.method not in ('GET', 'HEAD', 'OPTIONS')
        and origin
        and origin
        not in {
            'http://127.0.0.1:7860',
            'http://localhost:7860',
            'http://127.0.0.1:5173',
            'http://localhost:5173',
            f'http://{request.headers.get("host", "")}',
        }
    ):
        return JSONResponse({'detail': 'Only the local studio can submit requests.'}, status_code=403)
    return await call_next(request)


app.include_router(router)
app.include_router(photocraft_router)
IMAGES.mkdir(parents=True, exist_ok=True)
app.mount('/images', StaticFiles(directory=IMAGES), name='images')
if FRONTEND.exists():
    app.mount('/', StaticFiles(directory=FRONTEND, html=True), name='frontend')
else:

    @app.get('/')
    def missing_frontend():
        return JSONResponse(
            {'message': 'Build the React frontend: cd frontend && npm ci && npm run build'}, status_code=503
        )
