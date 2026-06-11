import subprocess
import json
import os
import time
from datetime import datetime

try:
    from AppKit import NSWorkspace
    import ApplicationServices as AX
    import objc

    PYOBJC_AVAILABLE = True
except ImportError:
    PYOBJC_AVAILABLE = False

# =========================================================
# INTERNAL UTILITIES & CORE OPTIMIZATIONS
# =========================================================


def _get_target_pid(app_name: str = None) -> int:
    """Helper to extract PID safely across native and web processes."""
    if not PYOBJC_AVAILABLE:
        return None
    workspace = NSWorkspace.sharedWorkspace()
    if app_name:
        apps = workspace.runningApplications()
        target = next(
            (a for a in apps if app_name.lower() in (a.localizedName() or "").lower()),
            None,
        )
        return target.processIdentifier() if target else None
    front_app = workspace.frontmostApplication()
    return front_app.processIdentifier() if front_app else None


def _extract_web_area(element, depth=0):
    """Deep-scans an application layout tree to isolate the webpage DOM from browser toolbars."""
    if depth > 12:
        return None
    try:
        _, role = AX.AXUIElementCopyAttributeValue(element, "AXRole", None)
        if str(role) == "AXWebArea":
            return element

        _, children = AX.AXUIElementCopyAttributeValue(element, "AXChildren", None)
        if children:
            for child in children:
                wa = _extract_web_area(child, depth + 1)
                if wa:
                    return wa
    except Exception:
        pass
    return None


def _wake_chromium_accessibility(app_ref, target_element=None):
    """Injects high-priority system flags to force Chrome/Electron to build its web DOM."""
    try:
        AX.AXUIElementSetAttributeValue(app_ref, "AXEnhancedUserInterface", objc.YES)
        AX.AXUIElementSetAttributeValue(app_ref, "AXManualAccessibility", objc.YES)
        if target_element:
            AX.AXUIElementSetAttributeValue(
                target_element, "AXEnhancedUserInterface", objc.YES
            )
            AX.AXUIElementCopyAttributeValue(target_element, "AXChildren", None)
        AX.AXUIElementCopyAttributeValue(app_ref, "AXFocusedUIElement", None)
    except Exception:
        pass


def _walk_ax_tree(element, depth: int, max_depth: int) -> list:
    """Recursively walks AX tree, filtering out structural clutter for data dumps."""
    if depth > max_depth:
        return []

    nodes = []
    try:
        err, role = AX.AXUIElementCopyAttributeValue(element, "AXRole", None)
        role = str(role) if role else None

        ignorable_containers = {
            "AXGroup",
            "AXLayoutArea",
            "AXScrollArea",
            "AXSplitGroup",
        }

        if role not in ignorable_containers:
            err, title = AX.AXUIElementCopyAttributeValue(element, "AXTitle", None)
            err, value = AX.AXUIElementCopyAttributeValue(element, "AXValue", None)
            err, desc = AX.AXUIElementCopyAttributeValue(element, "AXDescription", None)

            title = str(title) if title else None
            value = str(value) if value else None
            desc = str(desc) if desc else None

            meaningful_roles = {
                "AXButton",
                "AXTextField",
                "AXTextArea",
                "AXLink",
                "AXCheckBox",
                "AXRadioButton",
                "AXMenuItem",
                "AXMenuButton",
                "AXComboBox",
                "AXSearchField",
                "AXStaticText",
                "AXImage",
                "AXTab",
                "AXList",
                "AXCell",
                "AXWebArea",
            }

            label = title or desc or value
            if role in meaningful_roles and label:
                node = {"role": role, "label": label, "depth": depth}
                if value and value != label:
                    node["value"] = value
                nodes.append(node)

        err, children = AX.AXUIElementCopyAttributeValue(element, "AXChildren", None)
        if children:
            for child in children:
                nodes.extend(_walk_ax_tree(child, depth + 1, max_depth))
    except Exception:
        pass
    return nodes


# =========================================================
# EXPOSED FRIDAY RUNTIME INTERACTION ENGINE
# =========================================================


def press_enter() -> str:
    """Simulates a hardware Return key press via low-level virtual key codes."""
    try:
        script = 'tell application "System Events" to key code 36'
        subprocess.run(["osascript", "-e", script], check=True)
        return json.dumps({"status": "success", "message": "Pressed Enter Key."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def press_key(key: str, modifiers: list = None) -> str:
    """Presses a key with optional modifiers."""
    try:
        if modifiers:
            mod_str = ", ".join(f"{m} down" for m in modifiers)
            script = f'tell application "System Events" to keystroke "{key}" using {{{mod_str}}}'
        else:
            script = f'tell application "System Events" to keystroke "{key}"'
        subprocess.run(["osascript", "-e", script], check=True)
        return json.dumps({"status": "success", "message": f"Pressed {key}."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def type_text(text: str) -> str:
    """Types text safely, escaping quotation parsing layout anomalies."""
    try:
        safe_text = text.replace("\\", "\\\\").replace('"', '\\"')
        script = f"""
        tell application "System Events"
            keystroke "{safe_text}"
        end tell
        """
        subprocess.run(["osascript", "-e", script], check=True)
        return json.dumps(
            {
                "status": "success",
                "typed": text,
                "message": "Typed text payload successfully.",
            }
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def click_element_by_label(label: str, app_name: str = None) -> str:
    """Finds an element using isolated web window regions to bypass browser UI pollution."""
    try:
        pid = _get_target_pid(app_name)
        if not pid:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Target process '{app_name}' not found.",
                }
            )

        app_ref = AX.AXUIElementCreateApplication(pid)

        err, windows = AX.AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)
        if err != 0 or not windows or len(windows) == 0:
            err, target_root = AX.AXUIElementCopyAttributeValue(
                app_ref, "AXFocusedWindow", None
            )
            if err != 0 or not target_root:
                target_root = app_ref
        else:
            target_root = windows[0]

        _wake_chromium_accessibility(app_ref, target_root)

        # Isolate web layout region to screen out top control toolbars
        web_area = _extract_web_area(target_root)
        if web_area:
            target_root = web_area

        def _find_and_press(
            element, target_label, current_depth=0, max_depth=8
        ) -> bool:
            if current_depth > max_depth:
                return False
            try:
                _, title = AX.AXUIElementCopyAttributeValue(element, "AXTitle", None)
                _, desc = AX.AXUIElementCopyAttributeValue(
                    element, "AXDescription", None
                )
                _, value = AX.AXUIElementCopyAttributeValue(element, "AXValue", None)
                current_label = title or desc or value
                if current_label and target_label.lower() in str(current_label).lower():
                    # Force accessibility elements to request direct operational keyboard focus markers
                    AX.AXUIElementSetAttributeValue(element, "AXFocused", objc.YES)
                    if AX.AXUIElementPerformAction(element, "AXPress") == 0:
                        return True

                _, children = AX.AXUIElementCopyAttributeValue(
                    element, "AXChildren", None
                )
                if children:
                    for child in children:
                        if _find_and_press(
                            child, target_label, current_depth + 1, max_depth
                        ):
                            return True
            except Exception:
                pass
            return False

        if _find_and_press(target_root, label):
            return json.dumps(
                {
                    "status": "success",
                    "message": f"Successfully clicked element matching: '{label}'",
                }
            )
        else:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Could not find element matching label: '{label}'",
                }
            )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def read_accessibility_tree(app_name: str = None) -> str:
    """Scans application window layouts using isolated web regions if applicable."""
    try:
        pid = _get_target_pid(app_name)
        if not pid:
            return json.dumps(
                {"status": "error", "message": f"App '{app_name}' not running"}
            )

        app_ref = AX.AXUIElementCreateApplication(pid)

        err, windows = AX.AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)
        if err != 0 or not windows or len(windows) == 0:
            err, target_element = AX.AXUIElementCopyAttributeValue(
                app_ref, "AXFocusedWindow", None
            )
            if err != 0 or not target_element:
                target_element = app_ref
        else:
            target_element = windows[0]

        _wake_chromium_accessibility(app_ref, target_element)

        # Isolate web space if viewing a browser instance
        web_area = _extract_web_area(target_element)
        if web_area:
            target_element = web_area

        tree = _walk_ax_tree(target_element, depth=0, max_depth=8)
        return json.dumps(
            {
                "status": "success",
                "pid": pid,
                "element_count": len(tree),
                "tree": tree,
            }
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


# =========================================================
# SYSTEM DIAGNOSTICS & HARDWARE FALLBACKS
# =========================================================


def get_frontmost_app() -> str:
    if not PYOBJC_AVAILABLE:
        return json.dumps({"status": "error", "message": "pyobjc not available"})
    try:
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        return json.dumps(
            {
                "status": "success",
                "app": app.localizedName(),
                "bundle_id": app.bundleIdentifier(),
                "pid": app.processIdentifier(),
            }
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def get_running_apps() -> str:
    if not PYOBJC_AVAILABLE:
        return json.dumps({"status": "error", "message": "pyobjc not available"})
    try:
        workspace = NSWorkspace.sharedWorkspace()
        apps = workspace.runningApplications()
        app_list = [
            app.localizedName()
            for app in apps
            if app.activationPolicy() == 0 and app.localizedName()
        ]
        return json.dumps({"status": "success", "apps": sorted(app_list)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def get_clipboard() -> str:
    try:
        res = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
        return json.dumps({"status": "success", "content": res.stdout})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def set_clipboard(text: str) -> str:
    try:
        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
        process.communicate(input=text)
        return json.dumps({"status": "success", "message": "Copied to clipboard."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def take_screenshot(filename: str = "friday_vision.png") -> str:
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    filepath = os.path.abspath(os.path.join(cache_dir, filename))
    try:
        subprocess.run(["screencapture", "-x", filepath], check=True)
        return json.dumps(
            {
                "status": "success",
                "path": filepath,
                "timestamp": datetime.now().isoformat(),
            }
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def check_permissions() -> str:
    results = {}
    trusted = AX.AXIsProcessTrusted() if PYOBJC_AVAILABLE else False
    results["accessibility"] = "granted" if trusted else "MISSING"
    try:
        test_path = "/tmp/friday_test.png"
        subprocess.run(["screencapture", "-x", test_path], check=True, timeout=2)
        if os.path.exists(test_path):
            os.remove(test_path)
        results["screen_recording"] = "granted"
    except Exception:
        results["screen_recording"] = "MISSING"
    return json.dumps(results)


def focus_window(title_keyword: str, app_name: str = None) -> str:
    """Brings a specific window to front by matching title keyword."""
    try:
        pid = _get_target_pid(app_name)
        if not pid:
            return json.dumps({"status": "error", "message": "App not found"})

        app_ref = AX.AXUIElementCreateApplication(pid)
        _wake_chromium_accessibility(app_ref)
        err, windows = AX.AXUIElementCopyAttributeValue(app_ref, "AXWindows", None)

        for win in windows or []:
            err, title = AX.AXUIElementCopyAttributeValue(win, "AXTitle", None)
            if title and title_keyword.lower() in str(title).lower():
                AX.AXUIElementPerformAction(win, "AXRaise")
                return json.dumps({"status": "success", "message": f"Focused: {title}"})

        return json.dumps(
            {"status": "error", "message": f"No window matching '{title_keyword}'"}
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
