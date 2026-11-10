"""Open the environment collection for manual play."""

from player1.environments.browser.env import COLLECTION
from player1.environments.browser.server import AssetServer


if __name__ == "__main__":
    server = AssetServer(COLLECTION)
    try:
        print(f"Open {server.url} in your browser.")
        input("Press Enter to stop the server.\n")
    finally:
        server.close()
