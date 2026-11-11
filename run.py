"""Run the dev server:  python run.py   (then open http://localhost:5000)"""
import os

from brandguard.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
