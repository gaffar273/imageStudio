# Prompt edits in a marked area

In PhotoCraft's Assistant panel, choose **Mark an area** before planning:

1. Paint with **Brush**, or draw a loop with **Lasso**. Each stroke adds to the selection, so you can target several separate spots with one prompt.
2. Use **Erase**, **Undo mark**, and **Clear marks** to refine the green overlay. Zoom in for fine details. Brush size is relative to the photo and stays aligned when zoom changes.
3. Describe the change and choose **Plan**, then review and apply. The prompt affects only the marked area. Choose **Whole image** to return to normal prompt targeting.

Changing the marks discards the previous plan. Opening another document or moving to another revision clears the marks. Layout, crop, and layer operations cannot run in marked-area mode; they require Whole image. An empty or unusably small selection produces an error rather than becoming a global edit.

The API accepts normalized brush/lasso/erase strokes in `PromptRequest.area`. The planner sees both the original preview and the highlighted area. Server-owned plans retain the strokes and revision. The compiler uses the drawn selection instead of object detection, and generative edits receive the mask as well. Local filters never reuse a prior request's different selection. Engine contours stay one pixel inside the painted boundary to account for rasterization differences.

Before committing a marked edit, the server renders both versions at full resolution and checks every RGBA channel outside the mask. If any outside pixel changes, the operation fails and document history stays unchanged. The result check reports a successful boundary check. Existing layers and native revisions remain editable.

Selections fade inward before editing, with the softened mask clipped to the original boundary. This avoids visible patches without altering pixels outside the marks. Brightness, contrast, exposure and shadow/highlight adjustments use Luminosity blending to retain the underlying hue; requested color changes still use normal blending.

An older running backend does not advertise the `marked_area` capability, so the new UI keeps marking disabled until it is restarted. This prevents an old server from silently ignoring the new area field.
