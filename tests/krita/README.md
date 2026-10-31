Run `python tests/krita/run_workflow.py --krita C:/path/to/krita-x64-6.0.4` with no other Krita session open.
Use an extracted official Windows portable build. The runner temporarily enables an isolated test plugin,
restores the user's Krita settings in `finally`, and writes its JSON report under `build/krita-project-lab`.

This uses real native documents and checks create, original-size placement, transforms, editable masks,
save/close/reopen, clear/restore, repeated open without duplicate views, transparent live previews,
autosave reentrancy during preview, normal autosave, and 16-bit document preservation.
The backend transport/portable archive tests run separately in `tests/test_projects.py`.
