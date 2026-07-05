default:
    @just --list

# Update devenv inputs (nixpkgs, devenv module versions) and sync deps
update:
    devenv update
    uv sync

# Garbage collect old devenv generations
gc:
    devenv gc

# Clean devenv cache (forces full rebuild on next shell)
clean:
    rm -rf .devenv devenv.lock

# Enter the devenv shell
shell:
    devenv shell

# Install/sync dependencies
install:
    devenv shell -- uv sync

# Run the application
run:
    devenv shell -- uv run python main.py

# Build the executable
build:
    devenv shell -- uv run pyinstaller main.spec
