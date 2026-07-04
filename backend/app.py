import os

from flask import Flask

from config import Config
from models import db

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(app.instance_path, exist_ok=True)

db.init_app(app)


@app.route("/api/health")
def health():
    return {"status": "ok", "message": "Placement Portal API"}


if __name__ == "__main__":
    app.run(debug=True, port=5000)
