import os

# Set environment variable to use test config
if "CONFIG_PATH" not in os.environ:
    os.environ["CONFIG_PATH"] = "test_config.toml"
