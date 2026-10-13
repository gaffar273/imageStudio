# Image Studio

A private image workspace with a React + TypeScript interface and a local Python/FastAPI backend. Generate images, edit photos with painted masks, browse and search your saved images, and work with the Krita AI panel.

## Desktop app (Windows; Linux next)

Double-click **Start Image Studio app.bat**. It opens Image Studio as a native Qt window (no browser), starts the engine, and stops it again when you close the window, which frees the GPU. If the app ends abruptly, Windows closes the engine with it. Krita and PhotoCraft windows opened from the studio stay open.

- Every screen is native, in a light theme: **Create**, **Edit** and **Library**, the apps **PhotoCraft** and **Krita**, and **Settings** (Providers, Models, Personalization and This PC). Create has the same form as the web version (model, format, photo style, fine-tuning, sketch guide), shows the render's progress with a Stop button, and remembers your last settings. Ctrl + Enter generates. In a picture's details, **Use these settings** loads how it was made back into Create.
- **Edit image** takes a photo you drop on it, paste (Ctrl + V), choose from a file, or pick from your recent creations; **Edit image** in a picture's details opens it there too. PhotoCraft changes light and color across the whole photo and saves a layered PSD; AI content editing (FLUX.1 Kontext) changes what is in the picture, and can be limited to an area you paint (Ctrl + Z takes back a stroke). Before and After compare the result with the photo it came from, and **Keep editing** carries on from the result. Ctrl + Enter applies the edit.
- **PhotoCraft studio** is native too, with everything described in [PhotoCraft studio](#photocraft-studio) below: the Assistant (describe an edit, optionally only inside an area you mark with a brush or lasso, review the plan, apply it and see the result check), the Adjust, Looks, Crop, Select, Text, Filters and All tools panels, layers and history, Compare (drag the split), zoom, and Export to a file you choose. **Open** opens a photo or layered document from the PC (or drop one on the screen), a picture from your library (a PhotoCraft edit opens with its layers), a recent document, or a new blank canvas. **Open in PhotoCraft** on Edit brings the photo on screen along. Ctrl + Z / Ctrl + Y undo and redo (while marking an area, Ctrl + Z takes back a mark), Ctrl + Enter plans, Ctrl + O opens. In a narrow window the tool panel and the layers take turns (the layers button switches).
- **Settings → Providers** connects cloud services with your own API key: OpenAI, Google Gemini, fal.ai and Replicate create pictures (their models appear in Create's model list, under "Cloud"), OpenAI, Gemini and fal.ai edit photos (in Edit's tool list), and Anthropic, OpenRouter, Ollama, LM Studio or any OpenAI-compatible server can run the editing assistant that plans PhotoCraft edits. **Test connection** checks the key and lists the models it can reach; model names are editable, since providers rename them. Keys are stored in `credentials.json` next to the settings, encrypted for your Windows account (DPAPI; elsewhere readable by you only), never in `settings.json`, and an environment variable such as `OPENAI_API_KEY` takes priority. Cloud pictures are saved to the library like local ones.
- **Settings → This PC** shows which graphics card will be used, whether the local models will run on it, the engine's state, and the models and library folders.
- **Krita canvas** opens a picture in Krita (from a file, a drop, Ctrl + V or your library) or a blank canvas, shows Krita's live canvas, layers and activity, and sends typed edits to it (Ctrl + Enter), with Undo, Stop and Save to library. Krita is found as the portable copy in the models folder, a normal installation, or `IMAGE_STUDIO_KRITA`; without it the screen links to krita.org.
- **Settings → Personalization** shows what the studio has learned from you: your style training (train now, or overnight), the words you taught, how strong you like edits, and your usual settings (**Use these** loads them into Create). **Settings → Models** installs each model with one click: it downloads from the maker into your models folder, shows progress, resumes after a dropped connection, and can be stopped and resumed later. FLUX.1 Kontext first asks you to accept its licence on Hugging Face and paste a read token, which is used for that download only. It also shows whether PhotoCraft and Krita were found.
- The engine card at the foot of the sidebar shows the engine's state and live GPU and RAM use; its memory button unloads every model, so a game gets the video memory back. Messages appear briefly near the top of the window.

The app needs Qt for Python: `pip install -e .[desktop]`. Run it with `python -m image_studio.desktop` or the `image-studio-app` command.

### Installing it (Windows)

Run **ImageStudio-<version>-Setup.exe**. It installs for your user only (no administrator prompt) and adds Image Studio to the Start menu. The installer is small because it carries only the app and its own Python. On first start the app opens **Settings → Models**, where the **Engine** row installs PyTorch with CUDA and the model libraries in one click (about 3.5 GB to download). After that, install the models you want from the same page. The engine needs an NVIDIA graphics card to run models; on a PC without one, **Engine in cloud mode** installs it without PyTorch (about 60 MB), and Create and Edit work through the providers connected in Settings → Providers. The full engine can be added later on the same page.

The installer is not code-signed yet, so Windows SmartScreen asks once before it runs (**More info**, then **Run anyway**). Uninstalling removes the app and the engine's libraries. Your models, pictures and settings stay.

### Building the installer

```powershell
python packaging\build.py
```

This works with any Python 3.10 or newer. It downloads a standalone Python (checked against its published SHA-256) and installs the window's pinned libraries (`packaging/requirements-app.txt`). It copies the studio, removes unused parts of Qt, builds the launcher with the C# compiler that ships with Windows, and checks that the whole window opens. The app folder lands in `build\windows\Image Studio`. **Inno Setup 6** (`winget install JRSoftware.InnoSetup`) then turns it into `dist\ImageStudio-<version>-Setup.exe`. Use `--no-installer` to stop after the app folder.

On Linux, `python3 packaging/build.py` makes `dist/image-studio-<version>-linux-x86_64.tar.gz`. Unpack it anywhere and run `./install.sh` to add a menu entry, or `./image-studio` to start it. Qt needs `libxcb-cursor0` on X11. The Linux build has not been tested yet.

In an installed copy the engine runs on its own environment in `%LOCALAPPDATA%\Image Studio\engine` (Linux: `~/.local/share/image-studio/engine`, or `IMAGE_STUDIO_ENGINE_ENV`). `python -m image_studio.cli.setup_engine` sets it up or refreshes it from the command line. When an update pins different libraries, Settings → Models asks to finish the engine update, and only what changed downloads.

### Where files are kept

Each folder is taken from an environment variable, then from the settings file the app writes, then from a default:

| Folder | Variable | Default |
| --- | --- | --- |
| Models | `IMAGE_STUDIO_WORK` | `%LOCALAPPDATA%\Image Studio\models` (Linux: `~/.local/share/image-studio/models`) |
| Library | `IMAGE_STUDIO_LIBRARY` | `Pictures\Image Studio` |

Settings live in `%APPDATA%\Image Studio\settings.json` (Linux: `~/.config/image-studio/settings.json`), and the engine log in `%LOCALAPPDATA%\Image Studio\logs\engine.log`. A source checkout next to an existing `../../work` folder keeps using it and its `images/` folder, so older setups need no changes.

## Open the studio in the browser

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
│   │   ├── pipelines/       # Every edit as a pipeline: registry, library/, measure, checks, models/
│   │   ├── integrations/    # PhotoCraft planner, builder and workspace; Krita bridge and plugin installer
│   │   ├── workers/         # Isolated image-search worker
│   │   ├── cli/             # Start/stop and model download commands
│   │   └── __main__.py      # Local server entry point
│   ├── requirements-torch.txt   # CUDA PyTorch for the engine
│   ├── requirements-models.txt
│   ├── requirements-cloud.txt   # the engine in cloud mode (no PyTorch)
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
├── packaging/              # Installer build: Python runtime, launcher, Inno Setup, Linux files
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

To set up another computer from source, install `backend/requirements-torch.txt`, then `backend/requirements-models.txt`. Image search uses a separate environment; its setup shortcut is in `scripts/windows/`.

## Using the workspace

- **Create image:** describe an idea, choose a model and format, then generate. Fine-tune opens seed, steps, negative prompt, high-detail passes, face repair, references, checking, and LoRA options. Upload a sketch or ask the prompt assistant to plan one.
- **Edit image:** upload or select a library image, describe the change, and optionally paint a mask. Download the result or continue editing it.
- **My library:** filter saved prompts, search images visually, sort, favorite, download, or reuse settings. Favorites and draft settings are kept in the current browser.
- **Krita canvas:** upload or drop an image, or choose one from your library, to open a new document in Krita. Follow the live canvas and layers, send editing instructions (Ctrl+Enter), create a blank canvas, undo, stop, or save to the library. Paint, select areas, and manage layers in Krita. Imports are normalized to PNG in `studio-cache/krita-imports` without changing the source file.
- **Settings:** connect cloud providers, install models and optional tools, and review what the studio has learned.

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
- **Pipelines**: every professional procedure and whole job the engine knows (115 of them: product
  listings, real-estate interiors, full portrait retouching, graduated filters, split toning, film
  looks…). Pick one, fill in its few choices and run it. These are the same pipelines the assistant
  chooses from.
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

### The pipeline engine and any model

Every edit is a **pipeline** in code (`backend/image_studio/pipelines/`): what must be found and
measured, the exact PhotoCraft commands and settings, the retoucher's order, and measured checks.
The language model only chooses pipelines from a closed menu; it never writes a setting. The design,
and what running every pipeline in the real engine taught, is in
[docs/pipeline-engine.md](docs/pipeline-engine.md); the full list is generated into
[docs/pipelines.md](docs/pipelines.md) by `python scripts/pipeline_catalog.py`.

The model is replaceable per role (planner, grounder, checker): the bundled local model (default), any
OpenAI-compatible server (Ollama, LM Studio, vLLM, OpenAI, Gemini, OpenRouter) or Claude. Answers are
validated against the schema, repaired where that needs no guess, and asked for again otherwise; a
choice whose pipeline does not fit the words is re-asked with that pipeline off the menu. Finding
objects stays on the bundled model when the assistant is a model not trained to give boxes (Claude,
GPT), and the Providers page says so. An edit that measures too faint is run once more a step stronger.
`python scripts/planner_bench.py --set holdout|direction|all [--planner preset:model]` measures the
planner on requests it was never tuned on, and on any connected model.

```powershell
# which model answers each role
curl http://127.0.0.1:7860/api/photocraft/models
# connect the planner to a local Ollama model (keys, when needed, stay in environment variables)
curl -X PUT http://127.0.0.1:7860/api/photocraft/models -H "Content-Type: application/json" `
     -d '{"role": "planner", "preset": "ollama", "model": "qwen3-vl:8b"}'
```

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
