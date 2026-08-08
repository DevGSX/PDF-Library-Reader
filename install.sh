#!/usr/bin/env bash
# Sets up PDF Library Reader: creates a virtual environment, installs
# dependencies, and adds a launcher to your applications menu.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Setting up PDF Library Reader in $DIR ..."

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but was not found. Install Python 3.9+ first." >&2
    exit 1
fi

if ! python3 -c "import ensurepip" &> /dev/null; then
    echo "Error: the 'venv'/'ensurepip' module is missing." >&2
    echo "On Debian/Ubuntu, run: sudo apt install python3-venv" >&2
    exit 1
fi

echo "Creating virtual environment (.venv)..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip > /dev/null
echo "Installing dependencies (PySide6, PyMuPDF)... this can take a minute."
pip install -r requirements.txt
deactivate

cat > run.sh <<EOF
#!/usr/bin/env bash
cd "$DIR"
source "$DIR/.venv/bin/activate"
exec python3 "$DIR/main.py"
EOF
chmod +x run.sh

mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/pdf-library-reader.desktop <<EOF
[Desktop Entry]
Type=Application
Name=PDF Library Reader
Comment=Read and organize your PDF books
Exec=$DIR/run.sh
Icon=$DIR/resources/icon.svg
Terminal=false
Categories=Office;Viewer;
EOF

echo ""
echo "Done! Launch it from your applications menu (search \"PDF Library Reader\"),"
echo "or run it directly with: $DIR/run.sh"
