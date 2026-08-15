import ast
from pathlib import Path


BACKEND = Path(__file__).parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def _literal_keyword(call, name, default=""):
    for keyword in call.keywords:
        if keyword.arg == name:
            return ast.literal_eval(keyword.value)
    return default


def _decorated_routes(path, router_name, prefix=""):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in HTTP_METHODS or not decorator.args:
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != router_name:
                continue
            yield decorator.func.attr.upper(), prefix + ast.literal_eval(decorator.args[0]), path, node.lineno


def _router_prefix(tree):
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets):
            continue
        if isinstance(node.value, ast.Call):
            return _literal_keyword(node.value, "prefix")
    return ""


def _included_routers(main_tree):
    included = {}
    for node in ast.walk(main_tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
            continue
        if not node.args or not isinstance(node.args[0], ast.Attribute) or not isinstance(node.args[0].value, ast.Name):
            continue
        included[node.args[0].value.id] = _literal_keyword(node, "prefix")
    return included


def test_registered_route_contracts_are_unique():
    main_path = BACKEND / "main.py"
    main_tree = ast.parse(main_path.read_text(), filename=str(main_path))
    routes = list(_decorated_routes(main_path, "app"))

    for module_name, include_prefix in _included_routers(main_tree).items():
        router_path = BACKEND / "routers" / f"{module_name}.py"
        router_tree = ast.parse(router_path.read_text(), filename=str(router_path))
        routes.extend(_decorated_routes(router_path, "router", include_prefix + _router_prefix(router_tree)))

    declarations = {}
    for method, path, source, line in routes:
        declarations.setdefault((method, path), []).append(f"{source.relative_to(BACKEND)}:{line}")
    duplicates = {contract: locations for contract, locations in declarations.items() if len(locations) > 1}

    assert not duplicates, f"Duplicate route declarations: {duplicates}"
    legacy_routes = {
        ("POST", "/transcribe/"),
        ("POST", "/transcribe_local/"),
        ("POST", "/transcribe_local_stream/"),
        ("POST", "/transcribe_gcs_stream/"),
    }
    assert legacy_routes.isdisjoint(declarations)
    assert not {
        contract: locations
        for contract, locations in declarations.items()
        if contract[1].startswith("/transcribe")
    }
    assert ("GET", "/") in declarations


def test_legacy_transcription_routes_are_removed():
    config_source = (BACKEND / "config.py").read_text()
    transcription_source = (BACKEND / "routers" / "transcription.py").read_text()
    main_source = (BACKEND / "main.py").read_text()

    assert 'LOCAL_MODE: bool = os.getenv("LOCAL_MODE", "false")' in config_source
    assert "ENABLE_LEGACY_TRANSCRIPTION_ENDPOINTS" not in config_source
    for symbol in (
        '"/transcribe/"',
        '"/transcribe_local/"',
        '"/transcribe_local_stream/"',
        "transcribe_video",
        "transcribe_local",
        "transcribe_local_stream",
        "transcribe_gcs_stream",
        "_legacy_transcription_route",
    ):
        assert symbol not in transcription_source
        assert symbol not in main_source


def test_screenshot_regeneration_uses_owner_scoped_media_storage():
    source = (BACKEND / "routers" / "transcription.py").read_text()
    start = source.index("async def regenerate_screenshots_for_video")
    end = source.index("\n\ndef create_silent_segments_for_gaps", start)
    endpoint = source[start:end]

    assert "transcription_repository.get_job(video_hash, user_id)" in endpoint
    assert "get_media_storage" in endpoint
    assert "media_storage.download_to_temp" in endpoint
    assert "media_storage.is_owned_media_key" in endpoint
    assert "media_storage.upload_screenshots_batch" in endpoint
    assert "user_id=user_id" in endpoint
    assert "gcs_service" not in endpoint
    assert "tempfile.mkdtemp" in endpoint
    assert "SCREENSHOTS_DIR" not in endpoint


def test_public_static_mount_and_media_fallbacks_are_absent():
    main_source = (BACKEND / "main.py").read_text()
    transcription_source = (BACKEND / "routers" / "transcription.py").read_text()
    chat_source = (BACKEND / "routers" / "chat.py").read_text()
    worker_source = (BACKEND / "services" / "background_worker.py").read_text()

    assert 'app.mount("/static"' not in main_source
    assert "StaticFiles" not in main_source
    assert "LargeUploadMiddleware" not in main_source
    assert "BaseHTTPMiddleware" not in main_source
    assert "/static" not in transcription_source
    assert "/static" not in chat_source
    assert 'os.path.join("static", "screenshots")' not in worker_source
    assert "tempfile.mkdtemp" in worker_source
    assert "_owner_scoped_screenshot_url" in chat_source
    assert "storage.is_owned_screenshot_key" in chat_source
    assert "_refresh_owned_screenshot_urls" in transcription_source
