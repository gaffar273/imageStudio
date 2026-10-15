# Image Studio in the Microsoft Store

The Store signs the package itself, so people who install from the Store see no SmartScreen
warning and no "unknown publisher" prompt. `python packaging/build.py --msix` makes the package
(an `.msix` file). This page covers what the build cannot do for you, in the order you do it.

## 1. A developer account (once, free)

Sign up at <https://storedeveloper.microsoft.com> with a personal Microsoft account. Individual
accounts cost nothing and need no card. Microsoft checks your identity with a photo of a
government ID and a selfie, then opens Partner Center.

## 2. Reserve the name and copy the identity

In Partner Center: **Apps and games → New product → MSIX or PWA app**, and reserve
**Image Studio** (or the closest free name). Then open **Product management → Product identity**
and copy three values into `packaging/windows/store.json`:

| Partner Center shows        | store.json key           |
| --------------------------- | ------------------------ |
| Package/Identity/Name       | `name`                   |
| Package/Identity/Publisher  | `publisher` (`CN=...`)   |
| Package/Properties/PublisherDisplayName | `publisher_display_name` |

`build.py --msix` refuses to run until all three are filled in. These values are not secret.

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

**Store listing**: a description, at least one screenshot (1366×768 or larger), and a privacy
policy URL. A policy is needed because people store API keys and pictures in the app. The
website can host it, for example at agslabs.tech/privacy. In short, the policy says: everything
stays on the PC, nothing is collected, and prompts go to a cloud provider only when the person
connects one.

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
- Uninstalling from the Store removes only the app. The engine (several GB) and the Python copy
  stay in `%LOCALAPPDATA%\Image Studio` until the person deletes that folder. The installer's
  uninstaller removes the engine. A Store package cannot run code when it is uninstalled.
