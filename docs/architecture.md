# Architecture

The frontend owns presentation and browser interaction. The backend owns model loading, file storage, rendering and desktop integration. Neither layer imports UI code from the other.

## Backend

`core/paths.py` is the source of truth for project, model, image and cache locations. Absolute package imports replace the former root-level imports. Install the project with `pip install -e .`; command-line tools use `python -m image_studio...`.

`api/schemas.py` validates requests before GPU work starts. `api/routes.py` provides configuration, library metadata, original downloads, thumbnails, image generation, masked editing, layout planning, job status and Krita commands. FastAPI serves the compiled frontend at `/`, original images at `/images`, and JSON endpoints at `/api`.

`services/workflows.py` retains the original generation pipeline, including prompt rewriting, retry/checking, face variation, reference faces, repair, layout guidance, LoRA, photo finish and Accurate-to-RealVisXL finishing. It uses plain Python progress callbacks and results; Gradio is no longer a dependency. `services/jobs.py` adds asynchronous execution, progress polling and cancellation. `services/runtime.py` admits a single complete GPU session across browser and Krita requests.

`services/library.py` reads original PNG/JSON pairs without relocating them. Thumbnails are cached under the work directory. Metadata filtering works without a search model. Semantic search runs the existing worker in the separate search environment, keeping its newer Transformers dependencies out of the inference environment.

`integrations/bridge.py` preserves Krita's local protocol on port 7861. The React app accesses that bridge through the same-origin API. The server binds to loopback and rejects browser mutation requests from foreign origins.

## Frontend

React + TypeScript + Vite, with Lucide icons and locally bundled DM Sans/Manrope fonts. Page components cover editing, library, Krita and model status. Shared components cover navigation, prompt configuration, progress, gallery tiles and image details. CSS supports desktop, tablet and narrow mobile viewports and reduced motion.

The typed API helper reports server errors as visible notifications. Job polling stops at terminal states and reconnects to an active job after refresh. PNG download links serve original files. Favorites and draft generation settings live in browser local storage; model files and saved image metadata remain authoritative on disk.

## Verification

`npm run build` type-checks the frontend and produces the static bundle. Backend tests use FastAPI's test client and fake renderer boundaries so validation and queue behavior can be checked without loading gigabytes of model weights. Real inference smoke tests are performed separately against the installed local models.
