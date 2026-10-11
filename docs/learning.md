# How the studio learns from you

Everything is kept on this computer, in `../../work/studio-memory/memory.json` and
`../../work/personal-lora/`. Settings → *What the studio has learned from you* shows all of it
and can forget any part.

## Your words (instant, no training)

In Krita's AI panel or the browser's Krita tab:

| You type | What happens |
| --- | --- |
| `remember: make it pop means more contrast and vibrance` | Learned. From now on "make it pop" anywhere in a request is understood that way. Also: `when I say moody, I mean darker and cooler` |
| `no, I meant make it warmer` (right after a request) | The last request's layers are removed, the new one is applied, and the old phrase is learned to mean the new one |
| `too much` / `less` / `more` / `not enough` (right after a request) | Redone weaker (×0.6) or stronger (×1.5), and that kind of step is made a little weaker or stronger from then on |
| `forget make it pop` / `forget everything` | Forgotten |

The Edit page also understands taught words. Settings has a form to teach words directly.

A correction removes only the layers the last request added (found by comparing the layer list
before and after it). If that request changed the picture in place (crop, resize, flatten...),
the studio still learns the correction but asks you to press Undo first. Code:
`backend/image_studio/services/memory.py`, used by `workflows.editor_plan`.

## My style LoRA (trained, about 10–25 minutes)

Mark pictures you love as favorites in the Library (at least 12). The studio copies them,
describes what is in each one (never its style), and trains a small LoRA for RealVisXL, so the
look they share is what it learns. Use it with the **My style** slider in Create → Fine-tune
(Realistic model, and the RealVisXL finish in Accurate mode).

It trains when you press **Train now** in Settings, or **overnight** (1–5 AM) when the studio is
open and idle and at least 5 favorites changed since the last training. While it trains, rendering
is paused. Log: `../../work/personal-lora.log`.

Command line (with the studio running or closed):

```powershell
& ..\..\work\image-env\Scripts\python.exe -m image_studio.cli.personal_lora
& ..\..\work\image-env\Scripts\python.exe -m image_studio.cli.personal_lora --if-needed
```

`--if-needed` suits Windows Task Scheduler, for nights when the studio is closed.
Code: `backend/image_studio/services/personal.py`, `backend/image_studio/cli/personal_lora.py`,
and `training/lora/train_lora.py` (now with `--data` and `--out`).
