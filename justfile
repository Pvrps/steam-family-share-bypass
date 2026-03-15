# Check if we are inside a nix-shell environment
in_nix := env_var_or_default("IN_NIX_SHELL", "")

# Default recipe
default:
	@just --list

# Run the application
run:
	{{ if in_nix == "" { "nix-shell --run 'uv run python main.py'" } else { "uv run python main.py" } }}

# Build the executable
build:
	{{ if in_nix == "" { "nix-shell --run 'uv run pyinstaller main.spec'" } else { "uv run pyinstaller main.spec" } }}

# Install dependencies
install:
	{{ if in_nix == "" { "nix-shell --run 'uv sync'" } else { "uv sync" } }}
