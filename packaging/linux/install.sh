#!/bin/sh
# Adds Image Studio to the applications menu, run from the folder it is unpacked in:
#   ./install.sh            add the menu entry and icon (for this user)
#   ./install.sh --remove   take them away again (the folder itself is yours to delete)
# Models, pictures and settings live in ~/.local/share/image-studio and ~/.config/image-studio.
set -e
here="$(dirname "$(readlink -f "$0")")"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
entry="$data/applications/image-studio.desktop"
icon="$data/icons/hicolor/256x256/apps/image-studio.png"

if [ "$1" = "--remove" ]; then
    rm -f "$entry" "$icon"
    rm -rf "$data/image-studio/engine"
    echo "Image Studio is removed from the menu. Its engine libraries are removed too."
    exit 0
fi

mkdir -p "$(dirname "$entry")" "$(dirname "$icon")"
cp "$here/image-studio.png" "$icon"
cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Name=Image Studio
Comment=Create and edit pictures with local AI models
Exec="$here/image-studio" %F
Icon=image-studio
Terminal=false
Categories=Graphics;
EOF
chmod +x "$here/image-studio"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data/applications" || true
echo "Image Studio is in your applications menu."
