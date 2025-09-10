import subprocess
import os
import time

# --- CONFIGURATION ---
MUSIC_FILE_PATH = "/home/Ares/Music/Calm/ambient_focus_calm.wav"
WALLPAPER_IMAGE_PATH = "/home/Ares/Pictures/Wallpapers/serene_blue.jpg"


def test_play_music():
    """
    Opens VLC as an app and plays the music file.
    """
    print("--- 1. Testing Music Playback ---")

    if not os.path.exists(MUSIC_FILE_PATH):
        print(f"❌ ERROR: Music file not found at: {MUSIC_FILE_PATH}")
        return

    print(f"🎵 Opening VLC player with: {MUSIC_FILE_PATH}")

    try:
        subprocess.run(["killall", "vlc"], check=False, capture_output=True)
        time.sleep(1)

        # Launch full VLC app
        subprocess.Popen(
            ["vlc", "--play-and-exit", MUSIC_FILE_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print("✅ SUCCESS: VLC launched. You should see the player and hear sound!")

    except FileNotFoundError:
        print("❌ ERROR: VLC not found. Install with: sudo apt install vlc")
    except Exception as e:
        print(f"❌ ERROR: Unexpected error: {e}")


def detect_desktop_env():
    """
    Detects the desktop environment.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in desktop:
        return "kde"
    elif "xfce" in desktop:
        return "xfce"
    else:
        return "unknown"


def test_change_wallpaper():
    """
    Changes wallpaper depending on desktop environment (KDE or XFCE).
    """
    print("\n--- 2. Testing Wallpaper Change ---")

    if not os.path.exists(WALLPAPER_IMAGE_PATH):
        print(f"❌ ERROR: Wallpaper image not found at: {WALLPAPER_IMAGE_PATH}")
        return

    env = detect_desktop_env()
    print(f"🖼️  Detected Desktop Environment: {env.upper()}")

    try:
        if env == "kde":
            # KDE Plasma wallpaper change
            script = f"""
var Desktops = desktops();
for (i=0;i<Desktops.length;i++) {{
    d = Desktops[i];
    d.wallpaperPlugin = 'org.kde.image';
    d.currentConfigGroup = Array('Wallpaper', 'org.kde.image', 'General');
    d.writeConfig('Image', 'file://{WALLPAPER_IMAGE_PATH}');
}}
"""
            subprocess.run([
                "qdbus",
                "org.kde.plasmashell",
                "/PlasmaShell",
                "org.kde.PlasmaShell.evaluateScript",
                script
            ], check=True)
            print("✅ SUCCESS: Wallpaper changed in KDE Plasma.")

        elif env == "xfce":
            command = [
                "xfconf-query",
                "-c", "xfce4-desktop",
                "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                "-s", WALLPAPER_IMAGE_PATH
            ]
            subprocess.run(command, check=True)
            subprocess.run(["xfdesktop", "--reload"], check=False)
            print("✅ SUCCESS: Wallpaper changed in XFCE.")

        else:
            print("⚠️ WARNING: Unknown desktop environment. Wallpaper not changed.")

    except FileNotFoundError as e:
        print(f"❌ ERROR: Required command not found: {e}")
    except subprocess.CalledProcessError as e:
        print(f"❌ ERROR: Wallpaper command failed. Details: {e.stderr}")
    except Exception as e:
        print(f"❌ ERROR: Unexpected error: {e}")


if __name__ == "__main__":
    print(">>> Starting local action test script <<<\n")
    test_play_music()
    test_change_wallpaper()
    print("\n>>> Test script finished. <<<\n")
