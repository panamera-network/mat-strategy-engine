# 🛠 Setup virtual environment and install dependencies
setup:
    python -m venv .venv
    . .venv/bin/activate && pip install -r requirements.txt

# 🚀 Run the main engine
run:
    . .venv/bin/activate && python main.py

# 🧪 Run all tests
test:
    . .venv/bin/activate && pytest tests/

# 🧼 Lint the codebase
lint:
    . .venv/bin/activate && flake8 core/ api/ mt5/

# 🧹 Clean up cache and compiled files
clean:
    find . -type d -name '__pycache__' -exec rm -r {} +
    find . -type f -name '*.pyc' -delete
