import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("FLASK_RUN_PORT") or 5000)
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("APP_ENV", "development") == "development")
