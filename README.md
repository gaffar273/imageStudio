# Image Studio

A private image workspace with a React + TypeScript interface and a local Python/FastAPI backend. Generate images, edit photos with painted masks, browse and search your saved images, and work with the Krita AI panel.

## Open the studio

Double-click **Start image generator.bat**, then open **http://127.0.0.1:7860**. Use **Stop image generator.bat** to shut down the server and release the GPU. **Start Krita with AI.bat** starts the studio and Krita together.

The frontend is built and the Python package is installed in the existing `../../work/image-env` environment. Models remain in `../../work`; saved images and JSON metadata remain in `images/`.

## Project structure

```text
text-to-image/
├── backend/
│   ├── image_studio/
│   │   ├── api/             # FastAPI routes and request validation
│   │   ├── core/            # Inference engine, model catalog, stable paths
│   │   ├── services/        # Workflows, jobs, library, search, image processing
│   │   ├── integrations/    # Krita bridge and plugin installer
│   │   ├── workers/         # Isolated image-search worker
│   │   ├── cli/             # Start/stop and model download commands
│   │   └── __main__.py      # Local server entry point
│   ├── requirements-models.txt
│   └── requirements-search.txt
├── frontend/
│   ├── src/
│   │   ├── components/      # Shared controls, navigation, canvas, image dialog
│   │   ├── pages/           # Library, editor, Krita, settings
│   │   ├── lib/             # Typed API client and data contracts
│   │   ├── App.tsx          # Navigation and workspace state
│   │   └── styles.css       # Responsive design system
│   ├── public/             # Static assets
│   └── dist/               # Built assets served by Python (generated)
├── integrations/krita-plugin/
├── training/lora/           # Data preparation, captions, training, evaluation
├── scripts/windows/        # Model download and face-pool shortcuts
├── tests/                  # Backend integration and job-lifecycle tests
├── docs/                   # Architecture, model guide, screenshots
├── images/                 # Original generated PNGs and metadata
├── pyproject.toml          # Installable Python package and API dependencies
└── Start image generator.bat
```

## Development

Run from the project root, using the existing CUDA-enabled Python environment:

```powershell
& ..\..\work\image-env\Scripts\python.exe -m pip install -e .
& ..\..\work\image-env\Scripts\python.exe -m image_studio
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Vite runs on http://127.0.0.1:5173 and forwards `/api` and `/images` to the Python server. For the desktop launcher, build once with `npm run build`. The Python server serves `frontend/dist` directly, so Node is only needed for frontend development and builds.

Fonts are bundled with the frontend. The app does not need a hosted service or API key after model setup. Use `IMAGE_STUDIO_WORK` to override the model/cache directory. Desktop batch shortcuts assume the existing `../../work/image-env` layout.

## Commands

```powershell
# Download or resume a model
& ..\..\work\image-env\Scripts\python.exe -m image_studio.cli.download_model --model realistic

# Generate from the command line
& ..\..\work\image-env\Scripts\python.exe -m image_studio.core.engine "A forest cabin at sunrise" --model turbo --seed 42

# Build the face-reference pool
& ..\..\work\image-env\Scripts\python.exe -m image_studio.services.faces build

# Check API contracts, path safety, generation dispatch, cancellation and failures
& ..\..\work\image-env\Scripts\python.exe -m unittest discover -s tests -v
```

For browser checks with the local server running, use `cd frontend` then `npm run test:e2e`.
The tests use Microsoft Edge in headless mode and save desktop/mobile screenshots to `docs/screenshots/`.
For formatting, run `npx prettier --write src` inside `frontend`, or `python -m ruff format backend tests`
with the backend's optional `dev` dependencies installed.

Install `backend/requirements-models.txt` into an environment that already has CUDA PyTorch when setting up another computer. Image search uses a separate environment; its setup shortcut is in `scripts/windows/`.

## Using the workspace

- **Create image:** describe an idea, choose a model and format, then generate. Fine-tune opens seed, steps, negative prompt, high-detail passes, face repair, references, checking, and LoRA options. Upload a sketch or ask the prompt assistant to plan one.
- **Edit image:** upload or select a library image, describe the change, and optionally paint a mask. Download the result or continue editing it.
- **My library:** filter saved prompts, search images visually, sort, favorite, download, or reuse settings. Favorites and draft settings are kept in the current browser.
- **Krita canvas:** upload or drop an image, or choose one from your library, to open a new document in Krita. Follow the live canvas and layers, send editing instructions (Ctrl+Enter), create a blank canvas, undo, stop, or save to the library. Paint, select areas, and manage layers in Krita. Imports are normalized to PNG in `studio-cache/krita-imports` without changing the source file.
- **Studio settings:** inspect installed models and optional tools.

## PhotoCraft studio

**PhotoCraft studio** in the sidebar is a full-height editor for the installed PhotoCraft 0.7.0
engine. Open a photo or a layered PSD/PSB/PCraft/TIFF document, then either describe the edit or use
the tool rail:

- **Assistant**: type a request with as much detail as you like, for example *"Crop to 4:5 keeping
  the cat in frame, warm the cat slightly, blur the background, add 'Home Sweet Home' at the bottom in
  white, vibrance +12. Keep the dog unchanged."* The plan shows one card per change, outlines the objects
  it found on the canvas, and lists what it will keep and anything it did not understand. After you
  apply it, a **result check** measures each requirement (aspect ratio, exact text and placement,
  colours, brightness direction…) and adds the vision model's review.
- **Adjust, Looks, Crop, Select, Text, Filters**: dedicated panels with sliders and choices. They use
  the same exact compiler as the assistant, so manual and typed edits behave the same.
- **All tools**: all 858 PhotoCraft engine commands, with controls generated from their parameter
  specifications.
- **Inspector**: layers (visibility, opacity, blend mode, rename, delete, smart filters) and a clickable
  revision history. **Export** gives PSD, native PCraft, TIFF, PNG, JPEG or WebP.

Every change lands on its own named layer or smart filter, and the original pixels are never
overwritten. Small blemishes are removed with content-aware fill. Larger objects, and requests for new
content ("add a sailboat", "replace the sky"), are painted by FLUX.1 Kontext and come back as a masked
layer, which needs the editing model installed. How requests are understood, compiled and checked is
described in [docs/photocraft-assistant.md](docs/photocraft-assistant.md).

**Edit image** still offers a one-step PhotoCraft light-and-colour option for quick presets.
**Open desktop** hands a native copy to the PhotoCraft app; save there and use **Sync saved changes**
to bring it back as a new revision. The CLI is detected in `C:\Program Files\PhotoCraft` or on PATH;
set `IMAGE_STUDIO_PHOTOCRAFT_CLI` to override its location.

## Editing by prompt in Krita

Typed requests in the Krita AI panel are planned by the **editing brain**, Qwen3.5-9B (vision + language, 4-bit) served by a pinned llama.cpp CUDA build (`services/brain.py`; install with `scripts/windows/Download editing brain.bat`). It looks at the photo and decides; the craft is done by code:

- **Light, color and mood** (sunset light, golden hour, night, film, black and white, "make it pop") are graded by `services/grading.py`, a floating-point raw-developer / color-grading engine (exposure, white balance, tone, curves, HSL mixer, color wheels, split toning, clarity, dehaze, glow, grain, vignette, with luminance, color, graduated, radial and AI object masks). The brain picks a look, places it (sun position, horizon) and adjusts it; each grade is rendered on a preview, measured and judged before Krita gets it (`services/retoucher.py`). Krita receives a group of named layers with masks.
- **Recoloring an object** finds it (the brain boxes each object, SAM 2.1 outlines it) and adds a masked Hue/Saturation colorize layer, so texture and shading stay.
- **Content changes** (add, remove, replace objects) use FLUX.1 Kontext.
- Common commands ("make it brighter", "crop to square", "make the car red") are understood instantly by rules; a request mixing both is split.

Krita's curves filters cannot be configured from its Python API, which is why grading is computed in Image Studio and arrives as pixel layers: hide, fade or repaint their masks freely, but run the grade again after changing the layers below it.

`tests/krita/run_lab.py` runs the panel's Krita steps in a headless Krita (kritarunner) on real pictures, for checking changes without opening Krita.

Generation is limited to one GPU session across the browser and Krita. A stopped batch keeps completed images. Active browser jobs reconnect after a refresh; an interrupted server process cannot resume inference automatically.

See [architecture](docs/architecture.md) and the [model and training guide](docs/model-guide.md) for more detail. The source before the React migration was backed up to `../../work/image-studio-backups/before-react.zip`; the screenshots and verification records labeled “legacy” describe the earlier interface.
