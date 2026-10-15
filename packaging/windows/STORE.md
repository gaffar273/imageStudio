# Image Studio in the Microsoft Store

The Store signs the package itself, so people who install from the Store see no SmartScreen
warning and no "unknown publisher" prompt. `python packaging/build.py --msix` makes the package
(an `.msix` file). This page covers what the build cannot do for you, in the order you do it.

## 1. A developer account (once, free)

Sign up at <https://storedeveloper.microsoft.com> with a personal Microsoft account. Individual
accounts cost nothing and need no card. Microsoft checks your identity with a photo of a
government ID and a selfie, then opens Partner Center.

## 2. Reserve the name and copy the identity

In Partner Center: **Apps and games → New product → MSIX or PWA app**, and reserve a name.
"Image Studio" alone is taken; "AGS Labs Image Studio" matches the website. Then open
**Product management → Product identity** and fill in `packaging/windows/store.json`:

| Partner Center shows                    | store.json key           |
| --------------------------------------- | ------------------------ |
| the name you reserved, exactly          | `display_name`           |
| Package/Identity/Name                   | `name`                   |
| Package/Identity/Publisher              | `publisher` (`CN=...`)   |
| Package/Properties/PublisherDisplayName | `publisher_display_name` |

The Store checks that the package carries the reserved name, so it is also the name in the Start
menu; the app's own window still says Image Studio. `build.py --msix` refuses to run until all four
are filled in. These values are not secret.

## 3. Build

```
python packaging/build.py --msix
```

This makes `dist/ImageStudio-<version>.msix`, with the version from `pyproject.toml`. The Store
needs a higher version for every upload, so raise `version` in `pyproject.toml` first.

To try the package on your own PC before uploading it, use `--msix-test` instead. That builds
the same package under a test name, signed with a certificate made on this PC. The build prints
the one administrator command that makes Windows trust that certificate, and how to install and
remove the package.

## 4. The submission

**Pricing and availability**: free, all markets.

**Properties**: category *Photo & video*. Under system requirements, mention an NVIDIA graphics
card with 8 GB for local models. Without one, the app works through cloud providers.

**Age ratings**: the questionnaire. The app makes pictures from text people type, so say so
honestly (the result is usually a teen or 12+ rating).

**Packages**: upload the `.msix`.

**Store listing**: the description below, at least one screenshot (1366×768 or larger; the
website's `public/media/` has real ones), and the privacy policy URL
<https://agslabs.tech/privacy/> (`website/public/privacy/index.html`).

**Generative AI** (policy 11.16): answer yes where Partner Center asks whether the product uses
live generative AI. The description says so too, and the app has "Report this picture" in Library
and "Report a problem" in Settings → This PC; both open a GitHub issue, so watch the repository's
issues and act on reports.

A description that covers what the policies ask (11.16 generative AI, 10.2.2 what gets
downloaded, 10.2.7 removing everything):

> Make and edit pictures on your own PC by describing them. Image Studio uses generative AI
> models: write a picture in Create, or drop in a photo and say what to change in Edit.
> PhotoCraft turns a described retouch into real, editable layers, and the same assistant works
> inside Krita.
>
> The models run on your NVIDIA graphics card, so your pictures stay on your PC. No NVIDIA card?
> Connect a cloud provider (OpenAI, Google Gemini, fal.ai, Replicate, OpenRouter and others) with
> your own key instead.
>
> The app itself is small. On first start it installs its engine (PyTorch and the model libraries,
> about 3.5 GB, or about 60 MB in cloud mode) and then the models you choose, each downloaded from
> its maker. Settings → Models removes the engine again before you uninstall; your models folder
> is shown in Settings → This PC.
>
> To report a picture that should not have been made, open it in Library and choose Report this
> picture.

**Releases elsewhere**: the website and GitHub release can link to the Store page once it is
live, alongside the installer.

**Restricted capabilities**: Partner Center asks why the package uses two of them. Text that
fits:

> **runFullTrust**: Image Studio is a desktop app (Qt) that runs its own Python engine on the
> PC's graphics card and starts the user's own editors (Krita, PhotoCraft).
>
> **unvirtualizedResources**: the app installs a plugin into Krita's plugin folder
> (%APPDATA%\krita\pykrita) so Krita can use the app's engine. Its engine (several GB of
> libraries the user installs from the app), models and settings live in
> %LOCALAPPDATA%\Image Studio, where the user opens and manages them in Explorer. With AppData
> virtualized, Krita would not see the plugin and Explorer would not show those folders.

**Notes for certification**: the first start shows Settings, where the engine and models are
installed. A tester without an NVIDIA card can choose "Engine in cloud mode" (about 60 MB).
Image creation then needs a provider key, which a tester does not have, so ask them to check
that the app installs, starts and shows its pages.

Certification usually takes a few days. Each later update is the same upload with a higher
version number. People who installed from the Store get the update by themselves.

## How the package differs from the installer

- Windows installs each version into a new, read-only folder under `C:\Program Files\WindowsApps`.
  Nothing outside the package may start a program inside it. So the app copies its own Python
  (without Qt, about 80 MB) to `%LOCALAPPDATA%\Image Studio\runtime` and makes the engine from
  that copy. After an update it copies Python again and re-points the engine by itself, in a few
  seconds, with no download (`core/engine_env.py`, `sync_runtime` and `repoint`).
- AppData is not redirected (see `AppxManifest.xml`), so the engine, models, settings, logs and
  the Krita plugin are in the same folders as with the installer. Both versions can share an
  engine that is already set up.
- Uninstalling from the Store removes only the app: a Store package cannot run code when it is
  uninstalled. So Settings → Models has **Remove the engine**, which deletes the engine and the
  Python copy (`engine_env.remove`), and the listing says so (policy 10.2.7). The installer's
  uninstaller removes the engine by itself.
